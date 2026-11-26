"""底片夹读模型:所有权隔离、摘要契约、活动任务、未完成列表与详情。"""

from __future__ import annotations

import importlib
import sqlite3
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient


PASSWORD = "correct horse battery"


@pytest.fixture
def film_app(tmp_path, monkeypatch):
    db_path = tmp_path / "film.sqlite3"
    monkeypatch.setenv("ZHIJI_DB_PATH", str(db_path))
    monkeypatch.setenv("ZHIJI_UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("FRONTEND_ORIGINS", "http://localhost:5173")
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "false")
    monkeypatch.setenv("VIDEO_API_KEY", "test-video-key")

    import config
    import database
    import main

    importlib.reload(config)
    importlib.reload(database)
    app = importlib.reload(main).app
    return app, db_path


@contextmanager
def two_clients(app, db_path=None):
    with TestClient(app, base_url="http://testserver") as alice, TestClient(
        app, base_url="http://testserver"
    ) as bob:
        a = alice.post(
            "/api/auth/register",
            json={"username": "film-alice", "password": PASSWORD, "nickname": "A"},
        )
        b = bob.post(
            "/api/auth/register",
            json={"username": "film-bob", "password": PASSWORD, "nickname": "B"},
        )
        assert a.status_code == b.status_code == 201
        # 生成链路测试默认放开体验配额;配额语义由 test_generation_quota.py 单测。
        if db_path is not None:
            from conftest import grant_unlimited_quota

            grant_unlimited_quota(db_path)
        yield (alice, a.json()["id"]), (bob, b.json()["id"])


def seed_completed_work_book(db_path, user_id, work_id, job_id, *,
                             kind="daily_picturebook", title="晚霞",
                             start="2026-08-08", end="2026-08-08",
                             updated="2026-08-08T13:00:00Z"):
    """一部正式完成的作品绘本:work + done job + 9 张 work_assets 页。"""
    with sqlite3.connect(db_path) as db:
        db.execute(
            "INSERT INTO story_works (id, owner_user_id, title, medium, "
            "narrative_mode, style, selected_segments_json, status, kind, "
            "picturebook_job_id, source_start_date, source_end_date, "
            "display_start_date, display_end_date, created_at, updated_at) "
            "VALUES (?, ?, ?, 'picture_book', 'narrative', 'watercolor', '[]', "
            "'ready', ?, ?, ?, ?, ?, ?, 't', ?)",
            (work_id, user_id, title, kind, job_id, start, end, start, end, updated),
        )
        db.execute(
            "INSERT INTO picturebook_jobs (id, user_id, work_id, style, status, "
            "stage, total_pages, created_at, updated_at) "
            "VALUES (?, ?, ?, 'watercolor', 'done', 'done', 9, 't', ?)",
            (job_id, user_id, work_id, updated),
        )
        for index in range(9):
            db.execute(
                "INSERT INTO work_assets (work_id, ordinal, asset_type, url, text) "
                "VALUES (?, ?, 'image', ?, ?)",
                (work_id, index, f"/api/media/w{work_id}p{index}", f"cap{index}"),
            )
        db.commit()


def seed_historical_book(db_path, user_id, diary_id, job_id, *,
                         date="2026-07-01", updated="2026-07-01T10:00:00Z"):
    with sqlite3.connect(db_path) as db:
        db.execute(
            "INSERT INTO diaries (id, date, text, status, user_id) "
            "VALUES (?, ?, '历史日记正文第一句。剩余部分', 'confirmed', ?)",
            (diary_id, date, user_id),
        )
        db.execute(
            "INSERT INTO picturebook_jobs (id, user_id, diary_id, style, status, "
            "stage, total_pages, created_at, updated_at) "
            "VALUES (?, ?, ?, 'pixel', 'done', 'done', 9, 't', ?)",
            (job_id, user_id, diary_id, updated),
        )
        for index in range(9):
            db.execute(
                "INSERT INTO picturebook_pages (job_id, page_index, image_id, "
                "caption, status, image_url, created_at, updated_at) "
                "VALUES (?, ?, ?, 'c', 'ready', ?, 't', 't')",
                (job_id, index, f"img-{job_id}-{index}",
                 f"/api/media/h{job_id}p{index}"),
            )
        db.commit()


def seed_done_video(db_path, user_id, video_id, picturebook_job_id, *,
                    work_id=None, updated="2026-08-09T09:00:00Z"):
    with sqlite3.connect(db_path) as db:
        db.execute(
            "INSERT INTO video_assets (id, owner_user_id, storage_key, mime_type, "
            "size_bytes) VALUES (?, ?, ?, 'video/mp4', 10)",
            (f"va-{video_id}", user_id, f"vkey-{video_id}"),
        )
        db.execute(
            "INSERT INTO picturebook_video_jobs (id, user_id, picturebook_job_id, "
            "work_id, style, source_signature, model, segment_duration, ratio, "
            "page_sequence, status, stage, total_segments, asset_id, "
            "created_at, updated_at) "
            "VALUES (?, ?, ?, ?, 'pixel', ?, 'm', 5, '16:9', '[0,1]', 'done', "
            "'done', 1, ?, 't', ?)",
            (video_id, user_id, picturebook_job_id, work_id,
             f"sig-{video_id}", f"va-{video_id}", updated),
        )
        db.commit()


def test_picturebook_collection_isolation_and_summary_shape(film_app):
    app, db_path = film_app
    with two_clients(app, db_path) as ((alice, alice_id), (bob, bob_id)):
        seed_completed_work_book(db_path, alice_id, 101, 201)
        seed_historical_book(db_path, alice_id, 301, 401)
        seed_completed_work_book(db_path, bob_id, 102, 202, title="别人的书")

        response = alice.get("/api/film-folder/picturebooks")
        assert response.status_code == 200
        payload = response.json()
        assert payload["active_generation"] is None
        assert payload["unfinished_count"] == 0
        titles = {item["title"] for item in payload["items"]}
        assert "别人的书" not in titles
        assert len(payload["items"]) == 2

        work_item = next(
            item for item in payload["items"] if item["id"] == 101
        )
        assert work_item == {
            "id": 101,
            "source_kind": "canonical_work",
            "work_kind": "daily_picturebook",
            "title": "晚霞",
            "display_start_date": "2026-08-08",
            "display_end_date": "2026-08-08",
            "cover_url": "/api/media/w101p0",
            "completed_at": "2026-08-08T13:00:00Z",
            "published": False,
        }
        historical = next(
            item for item in payload["items"]
            if item["source_kind"] == "historical_job"
        )
        assert historical["work_kind"] is None
        assert historical["completed_at"] == "2026-07-01T10:00:00Z"


def test_time_stories_only_contains_completed_time_story_works(film_app):
    app, db_path = film_app
    with two_clients(app, db_path) as ((alice, alice_id), _):
        seed_completed_work_book(
            db_path, alice_id, 101, 201, kind="time_story", title="长线",
            start="2026-08-01", end="2026-08-05",
        )
        seed_completed_work_book(db_path, alice_id, 102, 202, title="当日")
        seed_historical_book(db_path, alice_id, 301, 401)

        payload = alice.get("/api/film-folder/time-stories").json()
        assert [item["title"] for item in payload["items"]] == ["长线"]
        item = payload["items"][0]
        assert item["work_kind"] == "time_story"
        assert item["display_start_date"] == "2026-08-01"
        assert item["display_end_date"] == "2026-08-05"


def test_picturebook_detail_and_foreign_404(film_app):
    app, db_path = film_app
    with two_clients(app, db_path) as ((alice, alice_id), (bob, _)):
        seed_completed_work_book(db_path, alice_id, 101, 201)

        detail = alice.get("/api/film-folder/picturebooks/canonical_work/101")
        assert detail.status_code == 200
        body = detail.json()
        assert len(body["pages"]) == 9
        assert body["title"] == "晚霞"

        foreign = bob.get("/api/film-folder/picturebooks/canonical_work/101")
        assert foreign.status_code == 404


def test_active_picturebook_generation_is_singular(film_app):
    app, db_path = film_app
    with two_clients(app, db_path) as ((alice, alice_id), _):
        with sqlite3.connect(db_path) as db:
            db.execute(
                "INSERT INTO diaries (id, date, text, status, user_id) "
                "VALUES (1, '2026-08-08', 'x', 'confirmed', ?)",
                (alice_id,),
            )
            db.execute(
                "INSERT INTO picturebook_jobs (id, user_id, diary_id, style, "
                "status, stage, total_pages, created_at, updated_at) "
                "VALUES (9, ?, 1, 'pixel', 'running', 'rendering', 9, 't', 't2')",
                (alice_id,),
            )
            for index in range(3):
                db.execute(
                    "INSERT INTO picturebook_pages (job_id, page_index, image_id, "
                    "caption, status, created_at, updated_at) "
                    "VALUES (9, ?, ?, 'c', 'ready', 't', 't')",
                    (index, f"i{index}"),
                )
            db.commit()
        payload = alice.get("/api/film-folder/picturebooks").json()
        active = payload["active_generation"]
        assert active["id"] == 9
        assert active["ready"] == 3
        assert active["total"] == 9
        # 不返回提示词或页面负载。
        assert "pages" not in active
        assert "story_json" not in active


def test_unfinished_picturebooks_list(film_app):
    app, db_path = film_app
    with two_clients(app, db_path) as ((alice, alice_id), _):
        with sqlite3.connect(db_path) as db:
            db.execute(
                "INSERT INTO diaries (id, date, text, status, user_id) "
                "VALUES (1, '2026-08-08', 'x', 'confirmed', ?)",
                (alice_id,),
            )
            db.execute(
                "INSERT INTO picturebook_jobs (id, user_id, diary_id, style, "
                "status, stage, error, total_pages, created_at, updated_at) "
                "VALUES (9, ?, 1, 'pixel', 'failed', 'failed', '生成过程出错了，可以重试', "
                "9, 't', 't9')",
                (alice_id,),
            )
            # 一部从未开始出图的 draft 作品。
            db.execute(
                "INSERT INTO story_works (id, owner_user_id, title, medium, "
                "narrative_mode, style, selected_segments_json, status, kind, "
                "display_start_date, display_end_date, created_at, updated_at) "
                "VALUES (5, ?, '未开始', 'picture_book', 'narrative', 'pixel', "
                "'[]', 'draft', 'daily_picturebook', '2026-08-08', '2026-08-08', "
                "'t', 't5')",
                (alice_id,),
            )
            db.commit()

        payload = alice.get("/api/film-folder/picturebooks/unfinished").json()
        assert len(payload["items"]) == 2
        failed = next(item for item in payload["items"] if item["id"] == 9)
        assert failed["error"] == "生成过程出错了，可以重试"
        assert failed["job_id"] == 9
        assert failed["source_kind"] == "historical_job"
        assert failed["display_start_date"] == "2026-08-08"
        draft = next(item for item in payload["items"] if item["id"] == 5)
        assert draft["work_kind"] == "daily_picturebook"
        assert draft["job_id"] is None
        assert draft["source_kind"] == "canonical_work"

        # running 任务不进未完成列表。
        with sqlite3.connect(db_path) as db:
            db.execute(
                "UPDATE picturebook_jobs SET status='running' WHERE id=9"
            )
            db.commit()
        payload = alice.get("/api/film-folder/picturebooks/unfinished").json()
        assert [item["id"] for item in payload["items"]] == [5]


def _seed_failed_canonical_work(db_path, user_id, work_id, job_id, *,
                                work_status="draft", work_stage="render_failed",
                                active_pointer="null",
                                work_kind="daily_picturebook",
                                start="2026-08-08", end="2026-08-08",
                                job_updated="2026-08-08T12:00:00Z"):
    """一部出图失败的 canonical 作品:draft/render_failed + failed job。"""
    active_value = str(job_id) if active_pointer == "job" else "NULL"
    with sqlite3.connect(db_path) as db:
        db.execute(
            "INSERT INTO story_works (id, owner_user_id, title, medium, "
            "narrative_mode, style, selected_segments_json, status, kind, stage, "
            "active_picturebook_job_id, display_start_date, display_end_date, "
            "created_at, updated_at) "
            f"VALUES (?, ?, '失败作品', 'picture_book', 'narrative', 'pixel', "
            f"'[]', ?, ?, ?, {active_value}, ?, ?, 't', 't')",
            (work_id, user_id, work_status, work_kind, work_stage, start, end),
        )
        db.execute(
            "INSERT INTO picturebook_jobs (id, user_id, work_id, style, status, "
            "stage, error, total_pages, created_at, updated_at) "
            "VALUES (?, ?, ?, 'pixel', 'failed', 'failed', '生成过程出错了，可以重试', "
            "9, 't', ?)",
            (job_id, user_id, work_id, job_updated),
        )
        db.commit()


def test_unfinished_canonical_failure_exposes_work_id_and_job_id(film_app):
    app, db_path = film_app
    with two_clients(app, db_path) as ((alice, alice_id), _):
        _seed_failed_canonical_work(db_path, alice_id, 101, 201)
        with sqlite3.connect(db_path) as db:
            db.execute(
                "INSERT INTO diaries (id, date, text, status, user_id) "
                "VALUES (301, '2026-07-01', 'x', 'confirmed', ?)",
                (alice_id,),
            )
            db.execute(
                "INSERT INTO picturebook_jobs (id, user_id, diary_id, style, "
                "status, stage, error, total_pages, created_at, updated_at) "
                "VALUES (401, ?, 301, 'pixel', 'failed', 'failed', "
                "'生成过程出错了，可以重试', 9, 't', '2026-07-01T10:00:00Z')",
                (alice_id,),
            )
            db.commit()

        payload = alice.get("/api/film-folder/picturebooks/unfinished").json()
        canonical = next(item for item in payload["items"] if item["id"] == 101)
        assert canonical == {
            "id": 101,
            "job_id": 201,
            "source_kind": "canonical_work",
            "work_kind": "daily_picturebook",
            "style": "pixel",
            "stage": "render_failed",
            "title": "失败作品",
            "display_start_date": "2026-08-08",
            "display_end_date": "2026-08-08",
            "error": "生成过程出错了，可以重试",
            "updated_at": canonical["updated_at"],
        }
        historical = next(item for item in payload["items"] if item["id"] == 401)
        assert historical["job_id"] == 401
        assert historical["source_kind"] == "historical_job"
        assert historical["display_start_date"] == "2026-07-01"
        assert historical["display_end_date"] == "2026-07-01"


def test_unfinished_pointer_cleared_draft_appears_once_with_latest_job(film_app):
    app, db_path = film_app
    with two_clients(app, db_path) as ((alice, alice_id), _):
        _seed_failed_canonical_work(db_path, alice_id, 101, 201)
        # 同一 draft 更早的一次失败尝试:只保留最新的 201。
        with sqlite3.connect(db_path) as db:
            db.execute(
                "INSERT INTO picturebook_jobs (id, user_id, work_id, style, "
                "status, stage, error, total_pages, created_at, updated_at) "
                "VALUES (200, ?, 101, 'pixel', 'failed', 'failed', "
                "'生成过程出错了，可以重试', 9, 't', '2026-08-08T11:00:00Z')",
                (alice_id,),
            )
            db.commit()

        payload = alice.get("/api/film-folder/picturebooks/unfinished").json()
        matches = [item for item in payload["items"] if item["id"] == 101]
        assert len(matches) == 1
        assert matches[0]["job_id"] == 201
        assert all(item["job_id"] != 200 for item in payload["items"])


def test_unfinished_excludes_obsolete_attempts_of_completed_works(film_app):
    app, db_path = film_app
    with two_clients(app, db_path) as ((alice, alice_id), _):
        # 作品已 ready:旧的失败尝试永远不进继续创作。
        _seed_failed_canonical_work(
            db_path, alice_id, 101, 201,
            work_status="ready", work_stage="done", active_pointer="job",
        )
        payload = alice.get("/api/film-folder/picturebooks/unfinished").json()
        assert payload["items"] == []


def test_unfinished_sanitizes_raw_provider_error(film_app):
    app, db_path = film_app
    with two_clients(app, db_path) as ((alice, alice_id), _):
        with sqlite3.connect(db_path) as db:
            db.execute(
                "INSERT INTO diaries (id, date, text, status, user_id) "
                "VALUES (301, '2026-07-01', 'x', 'confirmed', ?)",
                (alice_id,),
            )
            db.execute(
                "INSERT INTO picturebook_jobs (id, user_id, diary_id, style, "
                "status, stage, error, total_pages, created_at, updated_at) "
                "VALUES (401, ?, 301, 'pixel', 'failed', 'failed', "
                "'provider api_key=sk-secret refused at 10.0.0.1', 9, 't', 't9')",
                (alice_id,),
            )
            db.commit()
        payload = alice.get("/api/film-folder/picturebooks/unfinished").json()
        assert len(payload["items"]) == 1
        assert payload["items"][0]["error"] == "生成过程出错了，可以重试"
        assert "api_key" not in str(payload)


def test_motion_comic_collection_and_detail(film_app):
    app, db_path = film_app
    with two_clients(app, db_path) as ((alice, alice_id), (bob, _)):
        seed_completed_work_book(db_path, alice_id, 101, 201)
        seed_done_video(db_path, alice_id, 501, 201, work_id=101)

        payload = alice.get("/api/film-folder/motion-comics").json()
        assert payload["unfinished_count"] == 0
        assert len(payload["items"]) == 1
        item = payload["items"][0]
        assert item["id"] == 501
        assert item["title"] == "晚霞"
        assert item["video_url"] == "/api/picturebook-video/501/file"
        assert item["completed_at"] == "2026-08-09T09:00:00Z"

        detail = alice.get("/api/film-folder/motion-comics/501")
        assert detail.status_code == 200
        assert detail.json()["video_url"] == "/api/picturebook-video/501/file"

        assert bob.get("/api/film-folder/motion-comics/501").status_code == 404
        assert bob.get("/api/film-folder/motion-comics").json()["items"] == []


def test_unfinished_motion_comics_from_failed_draft(film_app):
    app, db_path = film_app
    with two_clients(app, db_path) as ((alice, alice_id), _):
        seed_completed_work_book(db_path, alice_id, 101, 201)
        with sqlite3.connect(db_path) as db:
            db.execute(
                "INSERT INTO picturebook_video_jobs (id, user_id, "
                "picturebook_job_id, work_id, style, source_signature, model, "
                "segment_duration, ratio, page_sequence, status, stage, error, "
                "total_segments, created_at, updated_at) "
                "VALUES (501, ?, 201, 101, 'pixel', 'sig', 'm', 5, '16:9', "
                "'[0,1]', 'failed', 'failed', '生成过程出错了，可以重试', 1, 't', 't9')",
                (alice_id,),
            )
            db.execute(
                "INSERT INTO motion_comic_drafts (user_id, source_kind, source_id, "
                "title, page_sequence_json, video_job_id, created_at, updated_at) "
                "VALUES (?, 'work', 101, '晚霞漫剧', '[0,1]', 501, 't', 't9')",
                (alice_id,),
            )
            # 未关联任务的纯草稿。
            db.execute(
                "INSERT INTO motion_comic_drafts (user_id, source_kind, source_id, "
                "title, page_sequence_json, video_job_id, created_at, updated_at) "
                "VALUES (?, 'work', 101, '未生成', '[0,1,2]', NULL, 't', 't8')",
                (alice_id,),
            )
            db.commit()

        payload = alice.get("/api/film-folder/motion-comics/unfinished").json()
        assert len(payload["items"]) == 2
        failed = next(i for i in payload["items"] if i["video_job_id"] == 501)
        assert failed["status"] == "failed"
        assert failed["title"] == "晚霞漫剧"
        draft = next(i for i in payload["items"] if i["video_job_id"] is None)
        assert draft["status"] == "draft"

        collection = alice.get("/api/film-folder/motion-comics").json()
        assert collection["unfinished_count"] == 2


def test_unfinished_motion_comics_sanitizes_raw_provider_error(film_app):
    app, db_path = film_app
    with two_clients(app, db_path) as ((alice, alice_id), _):
        seed_completed_work_book(db_path, alice_id, 101, 201)
        with sqlite3.connect(db_path) as db:
            db.execute(
                "INSERT INTO picturebook_video_jobs (id, user_id, "
                "picturebook_job_id, work_id, style, source_signature, model, "
                "segment_duration, ratio, page_sequence, status, stage, error, "
                "total_segments, created_at, updated_at) "
                "VALUES (501, ?, 201, 101, 'pixel', 'sig', 'm', 5, '16:9', "
                "'[0,1]', 'failed', 'failed', "
                "'provider api_key=sk-secret refused at 10.0.0.1', 1, 't', 't9')",
                (alice_id,),
            )
            db.execute(
                "INSERT INTO motion_comic_drafts (user_id, source_kind, source_id, "
                "title, page_sequence_json, video_job_id, created_at, updated_at) "
                "VALUES (?, 'work', 101, '晚霞漫剧', '[0,1]', 501, 't', 't9')",
                (alice_id,),
            )
            db.commit()

        payload = alice.get("/api/film-folder/motion-comics/unfinished").json()
        assert len(payload["items"]) == 1
        item = payload["items"][0]
        assert item["status"] == "failed"
        assert item["error"] == "生成过程出错了，可以重试"
        assert "api_key" not in str(payload)
