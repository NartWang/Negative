import importlib
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient


PASSWORD = "correct horse battery"
RECORD_DATE = "2026-08-03"
FOREIGN_ORIGIN = "https://attacker.example"
PUBLIC_SNAPSHOT_FIELDS = {"date", "score", "label", "color", "nickname"}


@pytest.fixture
def temperature_app(tmp_path, monkeypatch):
    db_path = tmp_path / "temperature.sqlite3"
    monkeypatch.setenv("ZHIJI_DB_PATH", str(db_path))
    monkeypatch.setenv("ZHIJI_UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("FRONTEND_ORIGINS", "http://localhost:5173")
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "false")

    import config
    import database
    import main
    import routers.rooms
    import routers.thermometer

    importlib.reload(config)
    importlib.reload(database)
    thermometer_router = importlib.reload(routers.thermometer)
    importlib.reload(routers.rooms)
    main = importlib.reload(main)

    async def fake_temperature(nickname, schedules, fragments):
        # Deterministic but identity-sensitive. The public room endpoint must
        # call this with the authenticated account's private inputs.
        identity_score = 3 if nickname == "Alice" else 11
        return identity_score, f"PRIVATE:{nickname}:{len(schedules)}:{len(fragments)}"

    monkeypatch.setattr(
        thermometer_router, "ai_score_and_comment", fake_temperature
    )
    return main.app, db_path


@contextmanager
def client_for(app):
    with TestClient(app, base_url="http://testserver") as client:
        yield client


def register(client, username, nickname):
    response = client.post(
        "/api/auth/register",
        json={"username": username, "password": PASSWORD, "nickname": nickname},
    )
    assert response.status_code == 201
    return response.json()


def pair_accounts(alice, bob):
    room = alice.post("/api/rooms")
    assert room.status_code == 201
    room_id = room.json()["id"]
    invite = alice.post(f"/api/rooms/{room_id}/invites")
    assert invite.status_code == 201
    joined = bob.post(
        "/api/room-invites/join", json={"code": invite.json()["code"]}
    )
    assert joined.status_code == 200
    return room_id


def fetch_all(db_path, sql, params=()):
    with sqlite3.connect(db_path) as db:
        db.row_factory = sqlite3.Row
        return db.execute(sql, params).fetchall()


def assert_unavailable(subject):
    assert subject == {"status": "unavailable"}


def assert_available(subject, expected_snapshot=None):
    assert set(subject) == {"status", "snapshot"}
    assert subject["status"] == "available"
    assert set(subject["snapshot"]) == PUBLIC_SNAPSHOT_FIELDS
    if expected_snapshot is not None:
        assert subject["snapshot"] == expected_snapshot


def test_temperature_routes_require_auth_pair_and_same_origin(temperature_app):
    app, _ = temperature_app
    with client_for(app) as anonymous:
        assert anonymous.get(
            "/api/rooms/missing/temperatures", params={"date": RECORD_DATE}
        ).status_code == 401
        assert anonymous.put(
            f"/api/rooms/missing/temperatures/{RECORD_DATE}"
        ).status_code == 401
        assert anonymous.delete(
            f"/api/rooms/missing/temperatures/{RECORD_DATE}"
        ).status_code == 401

    with client_for(app) as alice:
        register(alice, "alice", "Alice")
        waiting_room = alice.post("/api/rooms").json()["id"]
        for method in ("get", "put", "delete"):
            path = (
                f"/api/rooms/{waiting_room}/temperatures"
                if method == "get"
                else f"/api/rooms/{waiting_room}/temperatures/{RECORD_DATE}"
            )
            kwargs = {"params": {"date": RECORD_DATE}} if method == "get" else {}
            assert alice.request(method, path, **kwargs).status_code == 404

        assert alice.put(
            f"/api/rooms/{waiting_room}/temperatures/{RECORD_DATE}",
            headers={"Origin": FOREIGN_ORIGIN},
        ).status_code == 403
        assert alice.delete(
            f"/api/rooms/{waiting_room}/temperatures/{RECORD_DATE}",
            headers={"Origin": FOREIGN_ORIGIN},
        ).status_code == 403


def test_partner_is_unavailable_until_explicit_publication(temperature_app):
    app, _ = temperature_app
    with client_for(app) as alice, client_for(app) as bob:
        register(alice, "alice", "Alice")
        register(bob, "bob", "Bob")
        room_id = pair_accounts(alice, bob)
        assert alice.post(
            "/api/fragments",
            json={"date": RECORD_DATE, "content": "private but not shared"},
        ).status_code == 200
        assert alice.get(
            "/api/thermometer", params={"date": RECORD_DATE}
        ).status_code == 200

        response = alice.get(
            f"/api/rooms/{room_id}/temperatures", params={"date": RECORD_DATE}
        )

        assert response.status_code == 200
        assert set(response.json()) == {"own", "partner"}
        assert_unavailable(response.json()["own"])
        assert_unavailable(response.json()["partner"])


def test_publish_uses_authenticated_private_computation_and_public_shape(
    temperature_app,
):
    app, db_path = temperature_app
    with client_for(app) as alice, client_for(app) as bob:
        alice_profile = register(alice, "alice", "Alice")
        bob_profile = register(bob, "bob", "Bob")
        room_id = pair_accounts(alice, bob)
        assert alice.post(
            "/api/schedules",
            json={"date": RECORD_DATE, "title": "ALICE-PRIVATE", "completed": True},
        ).status_code == 200
        assert alice.post(
            "/api/fragments",
            json={"date": RECORD_DATE, "content": "ALICE-PRIVATE"},
        ).status_code == 200
        assert bob.post(
            "/api/fragments",
            json={"date": RECORD_DATE, "content": "BOB-PRIVATE"},
        ).status_code == 200

        private_temperature = alice.get(
            "/api/thermometer", params={"date": RECORD_DATE}
        )
        assert private_temperature.status_code == 200
        assert "PRIVATE:Alice" in private_temperature.json()["comment"]

        published = alice.put(
            f"/api/rooms/{room_id}/temperatures/{RECORD_DATE}",
            params={"subject": "partner", "user_id": bob_profile["id"]},
            json={
                "user_id": bob_profile["id"],
                "subject": "partner",
                "score": 100,
                "label": "HACKED",
                "color": "javascript:alert(1)",
                "nickname": "Mallory",
                "comment": "PRIVATE-COMMENT",
                "inputs": {"schedules": "STOLEN"},
            },
        )

        assert published.status_code == 200
        snapshot = published.json()
        assert set(snapshot) == PUBLIC_SNAPSHOT_FIELDS
        assert snapshot == {
            "date": RECORD_DATE,
            "score": private_temperature.json()["score"],
            "label": private_temperature.json()["label"],
            "color": private_temperature.json()["color"],
            "nickname": "Alice",
        }
        forbidden = {
            "comment",
            "quant_score",
            "ai_score",
            "inputs",
            "user_id",
            "subject",
            "schedules",
            "fragments",
            "consecutive_days",
        }
        assert forbidden.isdisjoint(snapshot)

        rows = fetch_all(
            db_path,
            "SELECT * FROM room_temperature_snapshots WHERE room_id=?",
            (room_id,),
        )
        assert len(rows) == 1
        assert rows[0]["user_id"] == alice_profile["id"]
        assert rows[0]["score"] == snapshot["score"]
        assert rows[0]["subject_nickname"] == "Alice"

        bob_view = bob.get(
            f"/api/rooms/{room_id}/temperatures",
            params={"date": RECORD_DATE, "user_id": alice_profile["id"]},
        )
        assert bob_view.status_code == 200
        assert_unavailable(bob_view.json()["own"])
        assert_available(bob_view.json()["partner"], snapshot)
        assert "PRIVATE-COMMENT" not in bob_view.text
        assert "ALICE-PRIVATE" not in bob_view.text


def test_upsert_republish_revoke_and_republish_are_scoped_to_current_user(
    temperature_app,
):
    app, db_path = temperature_app
    with client_for(app) as alice, client_for(app) as bob:
        alice_profile = register(alice, "alice", "Alice")
        register(bob, "bob", "Bob")
        room_id = pair_accounts(alice, bob)

        first = alice.put(
            f"/api/rooms/{room_id}/temperatures/{RECORD_DATE}"
        ).json()
        assert alice.post(
            "/api/fragments",
            json={"date": RECORD_DATE, "content": "new private signal"},
        ).status_code == 200
        second_response = alice.put(
            f"/api/rooms/{room_id}/temperatures/{RECORD_DATE}"
        )
        assert second_response.status_code == 200
        second = second_response.json()
        assert second["score"] > first["score"]

        rows = fetch_all(
            db_path,
            "SELECT * FROM room_temperature_snapshots WHERE room_id=?",
            (room_id,),
        )
        assert len(rows) == 1
        assert rows[0]["user_id"] == alice_profile["id"]
        assert rows[0]["revoked_at"] is None
        assert rows[0]["score"] == second["score"]

        # Bob can only revoke Bob's own nonexistent snapshot; Alice stays visible.
        assert bob.request(
            "delete",
            f"/api/rooms/{room_id}/temperatures/{RECORD_DATE}",
            params={"user_id": alice_profile["id"]},
            json={"subject": "partner"},
        ).status_code == 204
        assert_available(
            bob.get(
                f"/api/rooms/{room_id}/temperatures",
                params={"date": RECORD_DATE},
            ).json()["partner"],
            second,
        )

        assert alice.delete(
            f"/api/rooms/{room_id}/temperatures/{RECORD_DATE}"
        ).status_code == 204
        assert_unavailable(
            bob.get(
                f"/api/rooms/{room_id}/temperatures",
                params={"date": RECORD_DATE},
            ).json()["partner"]
        )

        republished = alice.put(
            f"/api/rooms/{room_id}/temperatures/{RECORD_DATE}"
        )
        assert republished.status_code == 200
        assert republished.json() == second
        row = fetch_all(
            db_path,
            "SELECT revoked_at FROM room_temperature_snapshots WHERE room_id=?",
            (room_id,),
        )[0]
        assert row["revoked_at"] is None


def test_snapshot_nickname_is_frozen_until_explicit_republish(temperature_app):
    app, _ = temperature_app
    with client_for(app) as alice, client_for(app) as bob:
        register(alice, "alice", "Alice")
        register(bob, "bob", "Bob")
        room_id = pair_accounts(alice, bob)
        old_snapshot = alice.put(
            f"/api/rooms/{room_id}/temperatures/{RECORD_DATE}"
        ).json()
        assert alice.put(
            "/api/profile", json={"nickname": "Alice New"}
        ).status_code == 200

        before_republish = bob.get(
            f"/api/rooms/{room_id}/temperatures", params={"date": RECORD_DATE}
        ).json()["partner"]["snapshot"]
        assert before_republish == old_snapshot

        new_snapshot = alice.put(
            f"/api/rooms/{room_id}/temperatures/{RECORD_DATE}"
        ).json()
        assert new_snapshot["nickname"] == "Alice New"
        assert bob.get(
            f"/api/rooms/{room_id}/temperatures", params={"date": RECORD_DATE}
        ).json()["partner"]["snapshot"] == new_snapshot


def test_concurrent_publish_upserts_one_active_snapshot(temperature_app):
    app, db_path = temperature_app
    with client_for(app) as alice, client_for(app) as alice_retry, client_for(
        app
    ) as bob:
        alice_profile = register(alice, "alice", "Alice")
        register(bob, "bob", "Bob")
        login = alice_retry.post(
            "/api/auth/login",
            json={"username": "alice", "password": PASSWORD},
        )
        assert login.status_code == 200
        room_id = pair_accounts(alice, bob)
        barrier = threading.Barrier(2)

        def publish(client):
            barrier.wait(timeout=5)
            return client.put(
                f"/api/rooms/{room_id}/temperatures/{RECORD_DATE}"
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(publish, (alice, alice_retry)))

        assert [response.status_code for response in responses] == [200, 200]
        assert responses[0].json() == responses[1].json()
        rows = fetch_all(
            db_path,
            "SELECT user_id, revoked_at FROM room_temperature_snapshots "
            "WHERE room_id=? AND snapshot_date=?",
            (room_id, RECORD_DATE),
        )
        assert [dict(row) for row in rows] == [
            {"user_id": alice_profile["id"], "revoked_at": None}
        ]


def test_database_connections_are_closed_before_temperature_ai_await(
    temperature_app, monkeypatch
):
    app, _ = temperature_app
    import routers.rooms as rooms_router
    import routers.thermometer as thermometer_router

    original_get_db = rooms_router.get_db
    tracked = []

    class TrackedConnection:
        def __init__(self, connection):
            self.connection = connection
            self.closed = False

        def __getattr__(self, name):
            return getattr(self.connection, name)

        async def close(self):
            await self.connection.close()
            self.closed = True

    async def tracked_get_db():
        connection = TrackedConnection(await original_get_db())
        tracked.append(connection)
        return connection

    async def assert_closed_before_ai(nickname, schedules, fragments):
        assert tracked
        assert all(connection.closed for connection in tracked)
        return 5, "resources released"

    monkeypatch.setattr(rooms_router, "get_db", tracked_get_db)
    monkeypatch.setattr(thermometer_router, "get_db", tracked_get_db)
    monkeypatch.setattr(
        thermometer_router, "ai_score_and_comment", assert_closed_before_ai
    )

    with client_for(app) as alice, client_for(app) as bob:
        register(alice, "alice", "Alice")
        register(bob, "bob", "Bob")
        room_id = pair_accounts(alice, bob)

        private_response = alice.get(
            "/api/thermometer", params={"date": RECORD_DATE}
        )
        assert private_response.status_code == 200
        assert tracked and all(connection.closed for connection in tracked)

        tracked.clear()
        shared_response = alice.put(
            f"/api/rooms/{room_id}/temperatures/{RECORD_DATE}"
        )
        assert shared_response.status_code == 200
        assert tracked and all(connection.closed for connection in tracked)


def test_profile_rejects_null_blank_and_oversized_nickname_but_allows_avatar_only(
    temperature_app,
):
    app, _ = temperature_app
    with client_for(app) as alice:
        register(alice, "alice", "Alice")

        avatar_only = alice.put("/api/profile", json={"avatar_url": None})
        assert avatar_only.status_code == 200
        assert avatar_only.json()["nickname"] == "Alice"

        for invalid in (None, "", "   ", "x" * 101):
            response = alice.put("/api/profile", json={"nickname": invalid})
            assert response.status_code == 422
        assert alice.get("/api/profile").json()["nickname"] == "Alice"

        trimmed = alice.put("/api/profile", json={"nickname": "  Alice New  "})
        assert trimmed.status_code == 200
        assert trimmed.json()["nickname"] == "Alice New"


@pytest.mark.parametrize("corrupted_nickname", [None, "   "])
def test_corrupted_legacy_nickname_still_publishes_safe_fallback(
    temperature_app, corrupted_nickname
):
    app, db_path = temperature_app
    with TestClient(
        app, base_url="http://testserver", raise_server_exceptions=False
    ) as alice, client_for(app) as bob:
        alice_profile = register(alice, "alice", "Alice")
        register(bob, "bob", "Bob")
        room_id = pair_accounts(alice, bob)
        with sqlite3.connect(db_path) as db:
            db.execute(
                "UPDATE profile SET nickname=? WHERE id=?",
                (corrupted_nickname, alice_profile["id"]),
            )
            db.commit()

        published = alice.put(
            f"/api/rooms/{room_id}/temperatures/{RECORD_DATE}"
        )

        assert published.status_code == 200
        assert published.json()["nickname"] == "你"
        assert set(published.json()) == PUBLIC_SNAPSHOT_FIELDS


def test_invalid_dates_and_leave_remove_temperature_access(temperature_app):
    app, _ = temperature_app
    with client_for(app) as alice, client_for(app) as bob:
        register(alice, "alice", "Alice")
        register(bob, "bob", "Bob")
        room_id = pair_accounts(alice, bob)

        for invalid in ("not-a-date", "2026-02-30", "2026-8-3", "20260803"):
            assert alice.get(
                f"/api/rooms/{room_id}/temperatures", params={"date": invalid}
            ).status_code == 400
            assert alice.put(
                f"/api/rooms/{room_id}/temperatures/{invalid}"
            ).status_code == 400
            assert alice.delete(
                f"/api/rooms/{room_id}/temperatures/{invalid}"
            ).status_code == 400

        assert alice.put(
            f"/api/rooms/{room_id}/temperatures/{RECORD_DATE}"
        ).status_code == 200
        assert bob.post(f"/api/rooms/{room_id}/leave").status_code == 204

        for client in (alice, bob):
            assert client.get(
                f"/api/rooms/{room_id}/temperatures",
                params={"date": RECORD_DATE},
            ).status_code == 404
            assert client.put(
                f"/api/rooms/{room_id}/temperatures/{RECORD_DATE}"
            ).status_code == 404
            assert client.delete(
                f"/api/rooms/{room_id}/temperatures/{RECORD_DATE}"
            ).status_code == 404
