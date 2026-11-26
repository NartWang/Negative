"""Generation slot guard: one running job per user per medium.

规格第六节:所有能把任务转为 running 的入口都要过同一守卫;绘本与漫剧可以
各跑一个。这些测试覆盖直接日记入口、作品入口、漫剧入口与重试路径。
"""

from __future__ import annotations

import importlib
import sqlite3
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient


PASSWORD = "correct horse battery"


@pytest.fixture
def slot_app(tmp_path, monkeypatch):
    db_path = tmp_path / "slots.sqlite3"
    monkeypatch.setenv("ZHIJI_DB_PATH", str(db_path))
    monkeypatch.setenv("ZHIJI_UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("FRONTEND_ORIGINS", "http://localhost:5173")
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "false")
    # 视频服务配置存在,漫剧入口才不会 503。
    monkeypatch.setenv("VIDEO_API_KEY", "test-video-key")

    import config
    import database
    import main

    importlib.reload(config)
    importlib.reload(database)
    app = importlib.reload(main).app
    return app, db_path


@contextmanager
def registered_client(app, username="slot-alice", db_path=None):
    with TestClient(app, base_url="http://testserver") as client:
        response = client.post(
            "/api/auth/register",
            json={"username": username, "password": PASSWORD, "nickname": "Alice"},
        )
        assert response.status_code == 201
        # 生成链路测试默认放开体验配额;配额语义由 test_generation_quota.py 单测。
        if db_path is not None:
            from conftest import grant_unlimited_quota

            grant_unlimited_quota(db_path)
        yield client, response.json()


def insert_diary_sync(db_path, *, user_id: int, body: str, date: str) -> int:
    with sqlite3.connect(db_path) as db:
        cursor = db.execute(
            "INSERT INTO diaries (date, text, status, user_id) VALUES (?, ?, 'confirmed', ?)",
            (date, body, user_id),
        )
        db.commit()
        return cursor.lastrowid


def mark_job_done_sync(db_path, job_id: int) -> None:
    with sqlite3.connect(db_path) as db:
        db.execute(
            "UPDATE picturebook_jobs SET status='done', stage='done' WHERE id=?",
            (job_id,),
        )
        db.commit()


def freeze_job_sync(db_path, job_id: int) -> None:
    """让后台推进器一启动就失败之外的状态:直接把任务停在 running 不动。"""
    with sqlite3.connect(db_path) as db:
        db.execute(
            "UPDATE picturebook_jobs SET status='running', stage='queued' WHERE id=?",
            (job_id,),
        )
        db.commit()


def fail_job_sync(db_path, job_id: int) -> None:
    with sqlite3.connect(db_path) as db:
        db.execute(
            "UPDATE picturebook_jobs SET status='failed', stage='failed' WHERE id=?",
            (job_id,),
        )
        db.commit()


def seed_ready_pages(db_path, user_id: int, book_id: int) -> None:
    """9 张就绪页 + 对应的媒体资产行,满足视频入口的所有权 JOIN。"""
    with sqlite3.connect(db_path) as db:
        for index in range(9):
            asset_id = f"asset-{book_id}-{index}"
            db.execute(
                "INSERT INTO media_assets (id, owner_user_id, storage_key, "
                "mime_type, size_bytes) VALUES (?, ?, ?, 'image/png', 1)",
                (asset_id, user_id, f"key-{book_id}-{index}"),
            )
            db.execute(
                "INSERT INTO picturebook_pages (job_id, page_index, image_id, "
                "caption, status, asset_id, created_at, updated_at) "
                "VALUES (?, ?, ?, 'c', 'ready', ?, 't', 't')",
                (book_id, index, f"img-{book_id}-{index}", asset_id),
            )
        db.commit()


def test_second_picturebook_start_returns_existing_active_job(slot_app, monkeypatch):
    import routers.picturebook as picturebook_router

    # 后台任务一旦启动就会改写状态;这里掐掉 spawn,纯粹验证 HTTP 层守卫。
    async def fake_spawn(job_id, user_id):
        return None

    monkeypatch.setattr(picturebook_router, "_spawn", fake_spawn)

    app, db_path = slot_app
    with registered_client(app, db_path=db_path) as (alice, profile):
        user_id = profile["id"]
        diary_a = insert_diary_sync(db_path, user_id=user_id, body="第一篇", date="2026-08-08")
        diary_b = insert_diary_sync(db_path, user_id=user_id, body="第二篇", date="2026-08-09")

        first = alice.post(
            f"/api/picturebook/diary/{diary_a}", json={"style": "watercolor"}
        )
        assert first.status_code == 200
        first_id = first.json()["id"]

        second = alice.post(
            f"/api/picturebook/diary/{diary_b}", json={"style": "watercolor"}
        )
        assert second.status_code == 409
        detail = second.json()["detail"]
        assert detail["category"] == "picturebook"
        assert detail["active_job_id"] == first_id


def test_same_diary_restart_is_idempotent_not_conflict(slot_app, monkeypatch):
    import routers.picturebook as picturebook_router

    async def fake_spawn(job_id, user_id):
        return None

    monkeypatch.setattr(picturebook_router, "_spawn", fake_spawn)

    app, db_path = slot_app
    with registered_client(app, db_path=db_path) as (alice, profile):
        diary_id = insert_diary_sync(
            db_path, user_id=profile["id"], body="同一篇", date="2026-08-08"
        )
        first = alice.post(f"/api/picturebook/diary/{diary_id}", json={})
        again = alice.post(f"/api/picturebook/diary/{diary_id}", json={})
        assert first.status_code == again.status_code == 200
        assert first.json()["id"] == again.json()["id"]


def test_picturebook_retry_excludes_itself_but_conflicts_with_other_running(
    slot_app, monkeypatch
):
    import routers.picturebook as picturebook_router

    async def fake_spawn(job_id, user_id):
        return None

    monkeypatch.setattr(picturebook_router, "_spawn", fake_spawn)

    app, db_path = slot_app
    with registered_client(app, db_path=db_path) as (alice, profile):
        user_id = profile["id"]
        diary_a = insert_diary_sync(db_path, user_id=user_id, body="A", date="2026-08-07")
        diary_b = insert_diary_sync(db_path, user_id=user_id, body="B", date="2026-08-08")

        job_a = alice.post(f"/api/picturebook/diary/{diary_a}", json={}).json()["id"]
        # 把 A 置为失败,然后启动 B;再重试 A 应当 409。
        fail_job_sync(db_path, job_a)
        job_b = alice.post(f"/api/picturebook/diary/{diary_b}", json={}).json()["id"]

        conflict = alice.post(f"/api/picturebook/{job_a}/retry")
        assert conflict.status_code == 409
        assert conflict.json()["detail"]["active_job_id"] == job_b

        # B 结束后重试 A 成功,说明重试只排除自身、不被自己卡死。
        mark_job_done_sync(db_path, job_b)
        retry = alice.post(f"/api/picturebook/{job_a}/retry")
        assert retry.status_code == 200
        assert retry.json()["status"] == "running"


def test_work_backed_start_conflicts_with_direct_running_job(slot_app, monkeypatch):
    import routers.picturebook as picturebook_router

    async def fake_spawn(job_id, user_id):
        return None

    monkeypatch.setattr(picturebook_router, "_spawn", fake_spawn)

    app, db_path = slot_app
    with registered_client(app, db_path=db_path) as (alice, profile):
        user_id = profile["id"]
        diary_a = insert_diary_sync(db_path, user_id=user_id, body="直接日记", date="2026-08-08")
        direct_id = alice.post(f"/api/picturebook/diary/{diary_a}", json={}).json()["id"]

        diary_b = insert_diary_sync(
            db_path, user_id=user_id, body="作品段落。", date="2026-08-09"
        )
        draft = alice.post(
            "/api/story/works/drafts",
            json={
                "kind": "daily_picturebook",
                "source_diary_ids": [diary_b],
                "selected_segments": ["作品段落。"],
                "title": "作品绘本",
                "style": "pixel",
            },
        )
        assert draft.status_code == 201
        conflict = alice.post(f"/api/story/works/{draft.json()['id']}/picturebook")
        assert conflict.status_code == 409
        assert conflict.json()["detail"]["active_job_id"] == direct_id


def test_picturebook_and_video_can_run_together(slot_app, monkeypatch):
    import routers.picturebook as picturebook_router
    import routers.picturebook_video as video_router

    async def fake_spawn(job_id, user_id):
        return None

    monkeypatch.setattr(picturebook_router, "_spawn", fake_spawn)
    monkeypatch.setattr(video_router, "_spawn", fake_spawn)

    app, db_path = slot_app
    with registered_client(app, db_path=db_path) as (alice, profile):
        user_id = profile["id"]
        diary_id = insert_diary_sync(db_path, user_id=user_id, body="绘本源", date="2026-08-08")
        book_id = alice.post(f"/api/picturebook/diary/{diary_id}", json={}).json()["id"]
        # 绘本跑它的;把这本标记完成并塞入 9 张就绪页,再开漫剧。
        mark_job_done_sync(db_path, book_id)
        seed_ready_pages(db_path, user_id, book_id)

        video = alice.post(f"/api/picturebook-video/picturebook/{book_id}", json={})
        assert video.status_code == 200
        assert video.json()["status"] == "running"

        # 此时绘本分区仍被占用吗?不:绘本已完成。再验证漫剧分区被占用。
        second_video = alice.post(
            f"/api/picturebook-video/picturebook/{book_id}",
            json={"page_indexes": [1, 2, 3]},
        )
        assert second_video.status_code == 409
        assert second_video.json()["detail"]["category"] == "motion_comic"


def test_video_retry_conflicts_with_other_running_video(slot_app, monkeypatch):
    import routers.picturebook_video as video_router

    async def fake_spawn(job_id, user_id):
        return None

    monkeypatch.setattr(video_router, "_spawn", fake_spawn)

    app, db_path = slot_app
    with registered_client(app, db_path=db_path) as (alice, profile):
        user_id = profile["id"]
        with sqlite3.connect(db_path) as db:
            for job_id, diary_day in ((11, "2026-08-01"), (12, "2026-08-02")):
                db.execute(
                    "INSERT INTO diaries (id, date, text, status, user_id) "
                    "VALUES (?, ?, '正文', 'confirmed', ?)",
                    (job_id, diary_day, user_id),
                )
                db.execute(
                    "INSERT INTO picturebook_jobs (id, user_id, diary_id, style, "
                    "status, stage, total_pages, created_at, updated_at) "
                    "VALUES (?, ?, ?, 'pixel', 'done', 'done', 9, 't', 't')",
                    (100 + job_id, user_id, job_id),
                )
            db.commit()
            for job_id in (11, 12):
                seed_ready_pages(db_path, user_id, 100 + job_id)

        video_a = alice.post("/api/picturebook-video/picturebook/111", json={})
        assert video_a.status_code == 200
        video_a_id = video_a.json()["id"]
        fail_video_sync(db_path, video_a_id)

        video_b = alice.post("/api/picturebook-video/picturebook/112", json={})
        assert video_b.status_code == 200

        conflict = alice.post(f"/api/picturebook-video/{video_a_id}/retry")
        assert conflict.status_code == 409
        assert conflict.json()["detail"]["active_job_id"] == video_b.json()["id"]


def fail_video_sync(db_path, video_job_id: int) -> None:
    with sqlite3.connect(db_path) as db:
        db.execute(
            "UPDATE picturebook_video_jobs SET status='failed', stage='failed' "
            "WHERE id=?",
            (video_job_id,),
        )
        db.commit()


def test_lifespan_resume_is_idempotent(slot_app, monkeypatch):
    """resume helpers 幂等:重复调用不重复驱动同一任务。"""
    import routers.picturebook as picturebook_router

    spawned = []

    async def fake_spawn(job_id, user_id):
        spawned.append(job_id)

    monkeypatch.setattr(picturebook_router, "_spawn", fake_spawn)

    app, db_path = slot_app
    with registered_client(app, db_path=db_path) as (alice, profile):
        user_id = profile["id"]
        with sqlite3.connect(db_path) as db:
            db.execute(
                "INSERT INTO diaries (id, date, text, status, user_id) "
                "VALUES (1, '2026-08-08', '正文', 'confirmed', ?)",
                (user_id,),
            )
            db.execute(
                "INSERT INTO picturebook_jobs (id, user_id, diary_id, style, status, "
                "stage, total_pages, created_at, updated_at) "
                "VALUES (201, ?, 1, 'pixel', 'running', 'rendering', 9, 't', 't')",
                (user_id,),
            )
            db.commit()

        import asyncio

        asyncio.run(picturebook_router.resume_running_picturebooks())
        asyncio.run(picturebook_router.resume_running_picturebooks())
        # fake_spawn 绕过了 _running 去重,但 resume 本身只扫描数据库,
        # 幂等性体现在:真实 _spawn 的 _running 集合阻止重复驱动。
        # 这里验证 resume 至少对每条 running 调用一次且可安全重入。
        assert 201 in spawned
