"""漫剧草稿 CRUD、所有权、页序校验与视频启动关联。"""

from __future__ import annotations

import sqlite3

import pytest

from tests.test_film_folder import (
    PASSWORD,
    film_app,
    seed_completed_work_book,
    seed_done_video,
    two_clients,
)


def _start_video(client, book_job_id, payload=None):
    return client.post(
        f"/api/picturebook-video/picturebook/{book_job_id}", json=payload or {}
    )


def test_create_draft_validates_source_and_sequence(film_app):
    app, db_path = film_app
    with two_clients(app, db_path) as ((alice, alice_id), (bob, bob_id)):
        seed_completed_work_book(db_path, alice_id, 101, 201)

        created = alice.post(
            "/api/film-folder/motion-comics/drafts",
            json={
                "source_kind": "work",
                "source_id": 101,
                "title": "下班路上的晚霞",
                "page_sequence": [1, 2, 4, 3],
            },
        )
        assert created.status_code == 201
        draft = created.json()
        assert draft["page_sequence"] == [1, 2, 4, 3]
        assert draft["video_job_id"] is None

        # 越权:别人的来源不可见。
        foreign = bob.post(
            "/api/film-folder/motion-comics/drafts",
            json={"source_kind": "work", "source_id": 101, "page_sequence": [1, 2]},
        )
        assert foreign.status_code == 404

        # 页索引必须属于来源(0..8)。
        bad_index = alice.post(
            "/api/film-folder/motion-comics/drafts",
            json={"source_kind": "work", "source_id": 101, "page_sequence": [1, 42]},
        )
        assert bad_index.status_code == 422

        # 重复页。
        dup = alice.post(
            "/api/film-folder/motion-comics/drafts",
            json={"source_kind": "work", "source_id": 101, "page_sequence": [1, 1]},
        )
        assert dup.status_code == 422

        # 太短。
        short = alice.post(
            "/api/film-folder/motion-comics/drafts",
            json={"source_kind": "work", "source_id": 101, "page_sequence": [1]},
        )
        assert short.status_code == 422


def test_update_draft_persists_order_and_foreign_404(film_app):
    app, db_path = film_app
    with two_clients(app, db_path) as ((alice, alice_id), (bob, _)):
        seed_completed_work_book(db_path, alice_id, 101, 201)
        draft = alice.post(
            "/api/film-folder/motion-comics/drafts",
            json={"source_kind": "work", "source_id": 101, "page_sequence": [1, 2]},
        ).json()

        updated = alice.put(
            f"/api/film-folder/motion-comics/drafts/{draft['id']}",
            json={"page_sequence": [3, 1, 2], "title": "新标题"},
        )
        assert updated.status_code == 200
        assert updated.json()["page_sequence"] == [3, 1, 2]
        assert updated.json()["title"] == "新标题"
        assert updated.json()["updated_at"] >= draft["updated_at"]

        assert bob.get(
            f"/api/film-folder/motion-comics/drafts/{draft['id']}"
        ).status_code == 404
        assert bob.put(
            f"/api/film-folder/motion-comics/drafts/{draft['id']}",
            json={"title": "劫持"},
        ).status_code == 404


def test_start_with_draft_links_it_and_blocks_sequence_edit(film_app, monkeypatch):
    import routers.picturebook_video as video_router

    async def fake_spawn(job_id, user_id):
        return None

    monkeypatch.setattr(video_router, "_spawn", fake_spawn)

    app, db_path = film_app
    with two_clients(app, db_path) as ((alice, alice_id), _):
        seed_completed_work_book(db_path, alice_id, 101, 201)
        # 视频页需要媒体资产:seed 一下。
        with sqlite3.connect(db_path) as db:
            for index in range(9):
                db.execute(
                    "INSERT INTO media_assets (id, owner_user_id, storage_key, "
                    "mime_type, size_bytes) VALUES (?, ?, ?, 'image/png', 1)",
                    (f"ma-{index}", alice_id, f"mkey-{index}"),
                )
                db.execute(
                    "INSERT INTO picturebook_pages (job_id, page_index, image_id, "
                    "caption, status, asset_id, created_at, updated_at) "
                    "VALUES (201, ?, ?, 'c', 'ready', ?, 't', 't')",
                    (index, f"img-{index}", f"ma-{index}"),
                )
            db.commit()

        draft = alice.post(
            "/api/film-folder/motion-comics/drafts",
            json={"source_kind": "work", "source_id": 101, "page_sequence": [1, 2, 3]},
        ).json()

        started = _start_video(
            alice, 201, {"page_indexes": [1, 2, 3], "draft_id": draft["id"]}
        )
        assert started.status_code == 200
        video_job_id = started.json()["id"]

        fetched = alice.get(f"/api/film-folder/motion-comics/drafts/{draft['id']}")
        assert fetched.json()["video_job_id"] == video_job_id

        # 已关联任务的草稿不允许改页序。
        edit = alice.put(
            f"/api/film-folder/motion-comics/drafts/{draft['id']}",
            json={"page_sequence": [2, 1, 3]},
        )
        assert edit.status_code == 409

        # 相同参数的重复启动复用任务,不新建草稿。
        again = _start_video(
            alice, 201, {"page_indexes": [1, 2, 3], "draft_id": draft["id"]}
        )
        assert again.status_code == 200
        assert again.json()["id"] == video_job_id
        with sqlite3.connect(db_path) as db:
            count = db.execute(
                "SELECT COUNT(*) FROM motion_comic_drafts WHERE video_job_id=?",
                (video_job_id,),
            ).fetchone()[0]
        assert count == 1


def test_legacy_start_creates_exactly_one_draft_and_reuses_it(film_app, monkeypatch):
    import routers.picturebook_video as video_router

    async def fake_spawn(job_id, user_id):
        return None

    monkeypatch.setattr(video_router, "_spawn", fake_spawn)

    app, db_path = film_app
    with two_clients(app, db_path) as ((alice, alice_id), _):
        seed_completed_work_book(db_path, alice_id, 101, 201)
        with sqlite3.connect(db_path) as db:
            for index in range(9):
                db.execute(
                    "INSERT INTO media_assets (id, owner_user_id, storage_key, "
                    "mime_type, size_bytes) VALUES (?, ?, ?, 'image/png', 1)",
                    (f"mb-{index}", alice_id, f"mkeyb-{index}"),
                )
                db.execute(
                    "INSERT INTO picturebook_pages (job_id, page_index, image_id, "
                    "caption, status, asset_id, created_at, updated_at) "
                    "VALUES (201, ?, ?, 'c', 'ready', ?, 't', 't')",
                    (index, f"imgb-{index}", f"mb-{index}"),
                )
            db.commit()

        first = _start_video(alice, 201, {"page_indexes": [1, 2, 3]})
        assert first.status_code == 200
        video_job_id = first.json()["id"]

        # 任务失败后,相同参数重启复用任务与既有草稿。
        with sqlite3.connect(db_path) as db:
            db.execute(
                "UPDATE picturebook_video_jobs SET status='failed' WHERE id=?",
                (video_job_id,),
            )
            db.commit()
        second = _start_video(alice, 201, {"page_indexes": [1, 2, 3]})
        assert second.status_code == 200
        assert second.json()["id"] == video_job_id

        with sqlite3.connect(db_path) as db:
            drafts = db.execute(
                "SELECT id, source_kind, source_id, page_sequence_json "
                "FROM motion_comic_drafts WHERE video_job_id=?",
                (video_job_id,),
            ).fetchall()
        assert len(drafts) == 1
        assert drafts[0][1] == "work"
        assert drafts[0][2] == 101


def test_conflicting_draft_for_linked_job_returns_existing_id(film_app, monkeypatch):
    import routers.picturebook_video as video_router

    async def fake_spawn(job_id, user_id):
        return None

    monkeypatch.setattr(video_router, "_spawn", fake_spawn)

    app, db_path = film_app
    with two_clients(app, db_path) as ((alice, alice_id), _):
        seed_completed_work_book(db_path, alice_id, 101, 201)
        with sqlite3.connect(db_path) as db:
            for index in range(9):
                db.execute(
                    "INSERT INTO media_assets (id, owner_user_id, storage_key, "
                    "mime_type, size_bytes) VALUES (?, ?, ?, 'image/png', 1)",
                    (f"mc-{index}", alice_id, f"mkeyc-{index}"),
                )
                db.execute(
                    "INSERT INTO picturebook_pages (job_id, page_index, image_id, "
                    "caption, status, asset_id, created_at, updated_at) "
                    "VALUES (201, ?, ?, 'c', 'ready', ?, 't', 't')",
                    (index, f"imgc-{index}", f"mc-{index}"),
                )
            db.commit()

        draft_a = alice.post(
            "/api/film-folder/motion-comics/drafts",
            json={"source_kind": "work", "source_id": 101, "page_sequence": [1, 2, 3]},
        ).json()
        draft_b = alice.post(
            "/api/film-folder/motion-comics/drafts",
            json={"source_kind": "work", "source_id": 101, "page_sequence": [1, 2, 3]},
        ).json()

        started = _start_video(
            alice, 201, {"page_indexes": [1, 2, 3], "draft_id": draft_a["id"]}
        )
        assert started.status_code == 200
        video_job_id = started.json()["id"]

        # 任务已关联 A;再用 B 启动同一任务 → 409,指向 A。
        with sqlite3.connect(db_path) as db:
            db.execute(
                "UPDATE picturebook_video_jobs SET status='failed' WHERE id=?",
                (video_job_id,),
            )
            db.commit()
        conflict = _start_video(
            alice, 201, {"page_indexes": [1, 2, 3], "draft_id": draft_b["id"]}
        )
        assert conflict.status_code == 409
        assert conflict.json()["detail"]["existing_draft_id"] == draft_a["id"]


def test_v14_backfilled_failed_job_appears_unfinished_and_retryable(film_app, monkeypatch):
    import routers.picturebook_video as video_router

    async def fake_spawn(job_id, user_id):
        return None

    monkeypatch.setattr(video_router, "_spawn", fake_spawn)

    app, db_path = film_app
    with two_clients(app, db_path) as ((alice, alice_id), _):
        seed_completed_work_book(db_path, alice_id, 101, 201)
        # 模拟 v14 回填:失败视频任务 + 关联草稿 + 失败分镜。
        with sqlite3.connect(db_path) as db:
            db.execute(
                "INSERT INTO picturebook_video_jobs (id, user_id, "
                "picturebook_job_id, work_id, style, source_signature, model, "
                "segment_duration, ratio, page_sequence, status, stage, error, "
                "total_segments, created_at, updated_at) "
                "VALUES (501, ?, 201, 101, 'pixel', 'sig-old', 'm', 5, '16:9', "
                "'[1,2,3]', 'failed', 'failed', '生成过程出错了，可以重试', 2, 't', 't')",
                (alice_id,),
            )
            for seg in (1, 2):
                db.execute(
                    "INSERT INTO picturebook_video_segments (video_job_id, "
                    "segment_index, first_page_index, last_page_index, status, "
                    "error, created_at, updated_at) "
                    "VALUES (501, ?, ?, ?, 'failed', '这一段没有生成成功，可以重试', 't', 't')",
                    (seg, seg, seg + 1),
                )
            db.execute(
                "INSERT INTO motion_comic_drafts (user_id, source_kind, source_id, "
                "title, page_sequence_json, video_job_id, created_at, updated_at) "
                "VALUES (?, 'work', 101, '', '[1,2,3]', 501, 't', 't')",
                (alice_id,),
            )
            db.commit()

        unfinished = alice.get("/api/film-folder/motion-comics/unfinished").json()
        assert len(unfinished["items"]) == 1
        assert unfinished["items"][0]["video_job_id"] == 501

        # 重试会重置失败分镜并把任务转回 running(需要页面资产存在)。
        with sqlite3.connect(db_path) as db:
            for index in range(9):
                db.execute(
                    "INSERT INTO media_assets (id, owner_user_id, storage_key, "
                    "mime_type, size_bytes) VALUES (?, ?, ?, 'image/png', 1)",
                    (f"md-{index}", alice_id, f"mkeyd-{index}"),
                )
                db.execute(
                    "INSERT INTO picturebook_pages (job_id, page_index, image_id, "
                    "caption, status, asset_id, created_at, updated_at) "
                    "VALUES (201, ?, ?, 'c', 'ready', ?, 't', 't')",
                    (index, f"imgd-{index}", f"md-{index}"),
                )
            db.commit()
        retry = alice.post("/api/picturebook-video/501/retry")
        assert retry.status_code == 200
        assert retry.json()["status"] == "running"
        assert all(
            segment["status"] == "pending"
            for segment in retry.json()["segments"]
        )
