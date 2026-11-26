import importlib
import sqlite3
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient


PASSWORD = "correct horse battery"


@pytest.fixture
def notebook_app(tmp_path, monkeypatch):
    monkeypatch.setenv("ZHIJI_DB_PATH", str(tmp_path / "notebook.sqlite3"))
    monkeypatch.setenv("ZHIJI_UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("FRONTEND_ORIGINS", "http://localhost:5173")
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "false")

    import config
    import database
    import main

    importlib.reload(config)
    importlib.reload(database)
    return importlib.reload(main).app, tmp_path / "notebook.sqlite3"


@contextmanager
def two_users(app):
    with TestClient(app, base_url="http://testserver") as alice, TestClient(
        app, base_url="http://testserver"
    ) as bob:
        alice_profile = alice.post(
            "/api/auth/register",
            json={
                "username": "notebook-alice",
                "password": PASSWORD,
                "nickname": "Alice",
            },
        )
        bob_profile = bob.post(
            "/api/auth/register",
            json={
                "username": "notebook-bob",
                "password": PASSWORD,
                "nickname": "Bob",
            },
        )
        assert alice_profile.status_code == bob_profile.status_code == 201
        yield alice, bob, alice_profile.json(), bob_profile.json()


def execute(db_path, sql, params=()):
    with sqlite3.connect(db_path) as db:
        db.execute(sql, params)
        db.commit()


def insert_diary(
    db_path,
    *,
    user_id,
    date,
    text,
    status,
    confirmed_at=None,
    created_at,
):
    with sqlite3.connect(db_path) as db:
        cursor = db.execute(
            "INSERT INTO diaries "
            "(date, text, status, source, user_id, created_at, confirmed_at) "
            "VALUES (?, ?, ?, 'manual', ?, ?, ?)",
            (date, text, status, user_id, created_at, confirmed_at),
        )
        db.commit()
        return cursor.lastrowid


def test_notebook_index_returns_canonical_confirmed_only(notebook_app):
    app, db_path = notebook_app
    with two_users(app) as (alice, bob, alice_profile, bob_profile):
        canonical_old = insert_diary(
            db_path,
            user_id=alice_profile["id"],
            date="2026-08-07",
            text="old canonical",
            status="confirmed",
            confirmed_at="2026-08-07T22:00:00",
            created_at="2026-08-07T21:00:00",
        )
        insert_diary(
            db_path,
            user_id=alice_profile["id"],
            date="2026-08-07",
            text="older duplicate",
            status="confirmed",
            confirmed_at="2026-08-07T20:00:00",
            created_at="2026-08-07T19:00:00",
        )
        insert_diary(
            db_path,
            user_id=alice_profile["id"],
            date="2026-08-08",
            text="alice draft",
            status="draft",
            confirmed_at=None,
            created_at="2026-08-08T08:00:00",
        )
        canonical_new = insert_diary(
            db_path,
            user_id=alice_profile["id"],
            date="2026-08-09",
            text="new canonical",
            status="confirmed",
            confirmed_at="2026-08-09T22:00:00",
            created_at="2026-08-09T21:00:00",
        )
        insert_diary(
            db_path,
            user_id=bob_profile["id"],
            date="2026-08-09",
            text="bob diary",
            status="confirmed",
            confirmed_at="2026-08-09T23:00:00",
            created_at="2026-08-09T22:30:00",
        )

        response = alice.get("/api/diary/notebook/index")

    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {"diary_id": canonical_old, "date": "2026-08-07"},
            {"diary_id": canonical_new, "date": "2026-08-09"},
        ],
        "total": 2,
    }


def test_notebook_index_breaks_ties_with_null_confirmed_at_last(notebook_app):
    app, db_path = notebook_app
    with two_users(app) as (alice, _bob, alice_profile, _bob_profile):
        canonical = insert_diary(
            db_path,
            user_id=alice_profile["id"],
            date="2026-08-09",
            text="confirmed row",
            status="confirmed",
            confirmed_at="2026-08-09T10:00:00",
            created_at="2026-08-09T09:00:00",
        )
        insert_diary(
            db_path,
            user_id=alice_profile["id"],
            date="2026-08-09",
            text="null confirmed_at confirmed row",
            status="confirmed",
            confirmed_at=None,
            created_at="2026-08-09T23:00:00",
        )

        response = alice.get("/api/diary/notebook/index")

    assert response.status_code == 200
    assert response.json() == {
        "items": [{"diary_id": canonical, "date": "2026-08-09"}],
        "total": 1,
    }


def test_notebook_detail_returns_canonical_body_and_kept_images(notebook_app):
    app, db_path = notebook_app
    with two_users(app) as (alice, bob, alice_profile, bob_profile):
        canonical = insert_diary(
            db_path,
            user_id=alice_profile["id"],
            date="2026-08-09",
            text="今天的日记正文",
            status="confirmed",
            confirmed_at="2026-08-09T22:00:00",
            created_at="2026-08-09T21:00:00",
        )
        non_canonical = insert_diary(
            db_path,
            user_id=alice_profile["id"],
            date="2026-08-09",
            text="older duplicate",
            status="confirmed",
            confirmed_at="2026-08-09T20:00:00",
            created_at="2026-08-09T19:00:00",
        )
        draft = insert_diary(
            db_path,
            user_id=alice_profile["id"],
            date="2026-08-10",
            text="draft body",
            status="draft",
            confirmed_at=None,
            created_at="2026-08-10T08:00:00",
        )
        bob_diary = insert_diary(
            db_path,
            user_id=bob_profile["id"],
            date="2026-08-09",
            text="bob body",
            status="confirmed",
            confirmed_at="2026-08-09T22:30:00",
            created_at="2026-08-09T22:00:00",
        )
        execute(
            db_path,
            "INSERT INTO images (diary_id, style, url, kept) "
            "VALUES (?, 'watercolor', '/api/upload/kept.png', 1), "
            "(?, 'watercolor', '/api/upload/dropped.png', 0)",
            (canonical, canonical),
        )

        ok = alice.get(f"/api/diary/notebook/{canonical}")
        not_canonical = alice.get(f"/api/diary/notebook/{non_canonical}")
        draft_blocked = alice.get(f"/api/diary/notebook/{draft}")
        foreign_blocked = alice.get(f"/api/diary/notebook/{bob_diary}")
        missing = alice.get("/api/diary/notebook/99999")

    assert ok.status_code == 200
    body = ok.json()
    assert body["id"] == canonical
    assert body["text"] == "今天的日记正文"
    assert body["status"] == "confirmed"
    assert [image["url"] for image in body["images"]] == [
        "/api/upload/kept.png"
    ]
    assert not_canonical.status_code == 404
    assert draft_blocked.status_code == 404
    assert foreign_blocked.status_code == 404
    assert missing.status_code == 404
