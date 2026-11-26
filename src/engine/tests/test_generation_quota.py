"""体验配额:默认 0 拒绝新建、充值后扣减、重试/复用不重复扣、分区相互独立。"""

from __future__ import annotations

import importlib
import sqlite3
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient


PASSWORD = "correct horse battery"


@pytest.fixture
def quota_app(tmp_path, monkeypatch):
    db_path = tmp_path / "quota.sqlite3"
    monkeypatch.setenv("ZHIJI_DB_PATH", str(db_path))
    monkeypatch.setenv("ZHIJI_UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("FRONTEND_ORIGINS", "http://localhost:5173")
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "false")

    import config
    import database
    import main

    importlib.reload(config)
    importlib.reload(database)
    app = importlib.reload(main).app
    return app, db_path


@contextmanager
def one_client(app, username="quota-user"):
    with TestClient(app, base_url="http://testserver") as client:
        res = client.post(
            "/api/auth/register",
            json={"username": username, "password": PASSWORD, "nickname": "Q"},
        )
        assert res.status_code == 201
        yield client, res.json()["id"]


def _set_quota(db_path, user_id, category, remaining):
    with sqlite3.connect(db_path) as db:
        db.execute(
            "INSERT INTO generation_quotas (user_id, category, remaining, updated_at) "
            "VALUES (?, ?, ?, 't') "
            "ON CONFLICT (user_id, category) "
            "DO UPDATE SET remaining = excluded.remaining",
            (user_id, category, remaining),
        )
        db.commit()


def _remaining(db_path, user_id, category):
    with sqlite3.connect(db_path) as db:
        row = db.execute(
            "SELECT remaining FROM generation_quotas WHERE user_id = ? AND category = ?",
            (user_id, category),
        ).fetchone()
    return int(row[0]) if row else 0


def _make_diary(client, date="2026-08-12"):
    res = client.post("/api/diary", json={"date": date})
    assert res.status_code == 200
    return res.json()["id"]


def test_picturebook_blocked_when_no_quota(quota_app):
    app, db_path = quota_app
    with one_client(app) as (client, user_id):
        diary_id = _make_diary(client)
        res = client.post(f"/api/picturebook/diary/{diary_id}", json={"style": "watercolor"})
        assert res.status_code == 403
        body = res.json()
        assert body["detail"]["code"] == "generation_quota_exceeded"
        assert body["detail"]["category"] == "picturebook"
        # 没有新建任何任务。
        with sqlite3.connect(db_path) as db:
            n = db.execute("SELECT COUNT(*) FROM picturebook_jobs").fetchone()[0]
        assert n == 0


def test_picturebook_consumes_quota_once_then_blocks(quota_app):
    app, db_path = quota_app
    with one_client(app) as (client, user_id):
        _set_quota(db_path, user_id, "picturebook", 1)
        diary_id = _make_diary(client)

        first = client.post(f"/api/picturebook/diary/{diary_id}", json={"style": "watercolor"})
        assert first.status_code == 200
        assert _remaining(db_path, user_id, "picturebook") == 0

        # 第二次新建(换一天日记强制走新签名):余额耗尽,拒绝。
        other_diary = _make_diary(client, date="2026-08-13")
        second = client.post(f"/api/picturebook/diary/{other_diary}", json={"style": "watercolor"})
        assert second.status_code == 403


def test_picturebook_resume_same_signature_does_not_reconsume(quota_app):
    """同一日记 + 同一风格重复点击只复用已有任务,不重复扣次数。"""
    app, db_path = quota_app
    with one_client(app) as (client, user_id):
        _set_quota(db_path, user_id, "picturebook", 1)
        diary_id = _make_diary(client)

        first = client.post(f"/api/picturebook/diary/{diary_id}", json={"style": "watercolor"})
        assert first.status_code == 200
        job_id = first.json()["id"]
        assert _remaining(db_path, user_id, "picturebook") == 0

        # 立即再点一次(任务仍 running):同签名复用,不新扣。
        again = client.post(f"/api/picturebook/diary/{diary_id}", json={"style": "watercolor"})
        assert again.status_code == 200
        assert again.json()["id"] == job_id
        assert _remaining(db_path, user_id, "picturebook") == 0
        with sqlite3.connect(db_path) as db:
            n = db.execute("SELECT COUNT(*) FROM picturebook_jobs").fetchone()[0]
        assert n == 1


def test_picturebook_and_motion_comic_quotas_are_independent(quota_app):
    """绘本额度为 0 不影响漫剧分区独立计费(反之亦然)。"""
    app, db_path = quota_app
    with one_client(app) as (client, user_id):
        # 只给漫剧充值,绘本保持 0。
        _set_quota(db_path, user_id, "motion_comic", 2)
        diary_id = _make_diary(client)
        pic = client.post(f"/api/picturebook/diary/{diary_id}", json={"style": "watercolor"})
        assert pic.status_code == 403
        # 漫剧额度没被绘本请求碰。
        assert _remaining(db_path, user_id, "motion_comic") == 2
        assert _remaining(db_path, user_id, "picturebook") == 0
