import hashlib
import importlib
import re
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, contextmanager
from datetime import datetime, timezone
from uuid import UUID

import pytest
from fastapi.testclient import TestClient


FRONTEND_ORIGIN = "http://localhost:5173"
FOREIGN_ORIGIN = "https://attacker.example"
PASSWORD = "correct horse battery"
INVITE_PATTERN = re.compile(r"^[A-HJ-NP-Z2-9]{4}(?:-[A-HJ-NP-Z2-9]{4}){3}$")


@pytest.fixture
def rooms_app(tmp_path, monkeypatch):
    db_path = tmp_path / "rooms.sqlite3"
    monkeypatch.setenv("ZHIJI_DB_PATH", str(db_path))
    monkeypatch.setenv("ZHIJI_UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("FRONTEND_ORIGINS", FRONTEND_ORIGIN)
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "false")

    import config
    import database
    import main

    importlib.reload(config)
    importlib.reload(database)
    main = importlib.reload(main)
    return main.app, db_path


@contextmanager
def client_for(app):
    with TestClient(app, base_url="http://testserver") as client:
        yield client


def register(client, username, nickname, avatar_url=None):
    response = client.post(
        "/api/auth/register",
        json={"username": username, "password": PASSWORD, "nickname": nickname},
    )
    assert response.status_code == 201
    if avatar_url is not None:
        profile = client.put(
            "/api/profile", json={"nickname": nickname, "avatar_url": avatar_url}
        )
        assert profile.status_code == 200
    return response.json()


def fetch_one(db_path, sql, params=()):
    with sqlite3.connect(db_path) as db:
        db.row_factory = sqlite3.Row
        return db.execute(sql, params).fetchone()


def fetch_all(db_path, sql, params=()):
    with sqlite3.connect(db_path) as db:
        db.row_factory = sqlite3.Row
        return db.execute(sql, params).fetchall()


def execute(db_path, sql, params=()):
    with sqlite3.connect(db_path) as db:
        db.execute(sql, params)
        db.commit()


def assert_public_room(room):
    assert set(room) == {
        "id",
        "status",
        "state",
        "waiting",
        "created_at",
        "members",
        "partner",
    }
    assert room["status"] == "active"
    assert room["state"] in {"waiting", "paired"}
    assert room["waiting"] is (room["state"] == "waiting")
    UUID(room["id"])
    for member in room["members"]:
        assert set(member) == {"id", "nickname", "avatar_url", "role", "slot"}
        assert member["role"] in {"owner", "member"}
        assert member["slot"] in {1, 2}
    forbidden = {"username", "username_norm", "password", "password_hash", "signature"}
    assert forbidden.isdisjoint(str(room).lower().replace("'", " ").split())


def create_invite(client, room_id):
    response = client.post(f"/api/rooms/{room_id}/invites")
    assert response.status_code == 201
    assert set(response.json()) == {"code", "expires_at"}
    return response.json()


def test_room_mutations_require_authentication_and_reject_foreign_origin(rooms_app):
    app, _ = rooms_app
    mutations = [
        ("post", "/api/rooms", None),
        ("post", "/api/rooms/not-a-room/invites", None),
        ("post", "/api/room-invites/join", {"code": "ABCD-EFGH-JKMP-QRST"}),
        ("post", "/api/rooms/not-a-room/leave", None),
    ]
    with client_for(app) as client:
        for method, path, payload in mutations:
            response = client.request(method, path, json=payload)
            assert response.status_code == 401

        register(client, "owner", "房主")
        for method, path, payload in mutations:
            response = client.request(
                method,
                path,
                json=payload,
                headers={"Origin": FOREIGN_ORIGIN},
            )
            assert response.status_code == 403
            assert response.json() == {"detail": "origin not allowed"}


def test_create_room_sets_uuid_owner_slot_and_rejects_second_active_room(rooms_app):
    app, db_path = rooms_app
    with client_for(app) as owner:
        profile = register(owner, "owner", "房主")

        no_room = owner.get("/api/rooms/current")
        created = owner.post("/api/rooms")
        duplicate = owner.post("/api/rooms")

        assert no_room.status_code == 200
        assert no_room.json() is None
        assert created.status_code == 201
        room = created.json()
        assert_public_room(room)
        assert room["state"] == "waiting"
        assert room["partner"] is None
        assert room["members"] == [
            {
                "id": profile["id"],
                "nickname": "房主",
                "avatar_url": None,
                "role": "owner",
                "slot": 1,
            }
        ]
        assert duplicate.status_code == 409

    db_room = fetch_one(
        db_path,
        "SELECT id, creator_user_id, status, closed_at FROM rooms",
    )
    member = fetch_one(
        db_path,
        "SELECT room_id, user_id, role, slot, left_at FROM room_members",
    )
    assert UUID(db_room["id"])
    assert db_room["creator_user_id"] == profile["id"]
    assert db_room["status"] == "active"
    assert db_room["closed_at"] is None
    assert dict(member) == {
        "room_id": db_room["id"],
        "user_id": profile["id"],
        "role": "owner",
        "slot": 1,
        "left_at": None,
    }


def test_current_room_exposes_only_public_member_and_partner_fields(rooms_app):
    app, db_path = rooms_app
    with client_for(app) as owner, client_for(app) as member:
        owner_profile = register(owner, "owner", "甲")
        member_profile = register(member, "member", "乙")
        execute(
            db_path,
            "UPDATE profile SET avatar_url='/api/upload/owner.png' WHERE id=?",
            (owner_profile["id"],),
        )
        execute(
            db_path,
            "UPDATE profile SET avatar_url=? WHERE id=?",
            (
                "https://tracker.attacker.example/avatar.png",
                member_profile["id"],
            ),
        )
        room = owner.post("/api/rooms").json()
        code = create_invite(owner, room["id"])["code"]
        assert member.post("/api/room-invites/join", json={"code": code}).status_code == 200

        owner_current = owner.get("/api/rooms/current")
        member_current = member.get("/api/rooms/current")

    assert owner_current.status_code == member_current.status_code == 200
    for current in (owner_current.json(), member_current.json()):
        assert_public_room(current)
        assert current["state"] == "paired"
        assert current["waiting"] is False
        assert [item["slot"] for item in current["members"]] == [1, 2]
    assert owner_current.json()["partner"]["id"] == member_profile["id"]
    assert member_current.json()["partner"]["id"] == owner_profile["id"]
    assert owner_current.json()["partner"]["avatar_url"] is None
    assert member_current.json()["partner"]["avatar_url"] is None


def test_owner_rotates_hash_only_unambiguous_invite_with_24_hour_expiry(rooms_app):
    app, db_path = rooms_app
    with client_for(app) as owner:
        register(owner, "owner", "房主")
        room_id = owner.post("/api/rooms").json()["id"]

        first = create_invite(owner, room_id)
        second = create_invite(owner, room_id)

    assert first["code"] != second["code"]
    assert INVITE_PATTERN.fullmatch(first["code"])
    assert INVITE_PATTERN.fullmatch(second["code"])
    compact_code = second["code"].replace("-", "")
    assert len(compact_code) == 16
    rows = fetch_all(
        db_path,
        "SELECT id, code_hash, expires_at, consumed_at, revoked_at "
        "FROM room_invites ORDER BY created_at, id",
    )
    assert len(rows) == 2
    assert UUID(rows[0]["id"])
    assert UUID(rows[1]["id"])
    assert rows[0]["revoked_at"] is not None
    assert rows[1]["revoked_at"] is None
    assert rows[1]["consumed_at"] is None
    assert rows[1]["code_hash"] == hashlib.sha256(
        compact_code.encode("ascii")
    ).hexdigest()
    expires_at = datetime.fromisoformat(second["expires_at"].replace("Z", "+00:00"))
    seconds = (expires_at - datetime.now(timezone.utc)).total_seconds()
    assert 23.9 * 60 * 60 <= seconds <= 24 * 60 * 60
    database_bytes = db_path.read_bytes()
    assert second["code"].encode("ascii") not in database_bytes
    assert compact_code.encode("ascii") not in database_bytes


def test_invite_generation_requires_waiting_owner_and_active_room(rooms_app):
    app, _ = rooms_app
    with client_for(app) as owner, client_for(app) as member:
        register(owner, "owner", "甲")
        register(member, "member", "乙")
        room = owner.post("/api/rooms").json()
        code = create_invite(owner, room["id"])["code"]
        assert member.post("/api/room-invites/join", json={"code": code}).status_code == 200

        assert owner.post(f"/api/rooms/{room['id']}/invites").status_code == 409
        assert member.post(f"/api/rooms/{room['id']}/invites").status_code == 403
        assert owner.post(f"/api/rooms/{room['id']}/leave").status_code == 204
        assert owner.post(f"/api/rooms/{room['id']}/invites").status_code == 404


def test_join_failures_are_generic_and_success_is_single_use(rooms_app):
    app, db_path = rooms_app
    with (
        client_for(app) as owner,
        client_for(app) as member,
        client_for(app) as third,
        client_for(app) as already_paired,
    ):
        owner_profile = register(owner, "owner", "甲")
        member_profile = register(member, "member", "乙")
        register(third, "third", "丙")
        register(already_paired, "paired", "丁")
        assert already_paired.post("/api/rooms").status_code == 201
        room = owner.post("/api/rooms").json()

        revoked_code = create_invite(owner, room["id"])["code"]
        expired_code = create_invite(owner, room["id"])["code"]
        execute(
            db_path,
            "UPDATE room_invites SET expires_at=? WHERE code_hash=?",
            (
                "2000-01-01T00:00:00+00:00",
                hashlib.sha256(
                    expired_code.replace("-", "").encode("ascii")
                ).hexdigest(),
            ),
        )

        failures = [
            owner.post("/api/room-invites/join", json={"code": expired_code}),
            member.post("/api/room-invites/join", json={"code": revoked_code}),
            member.post(
                "/api/room-invites/join", json={"code": "ABCD-EFGH-JKMP-QRST"}
            ),
            member.post("/api/room-invites/join", json={"code": "A" * 65}),
        ]
        valid_code = create_invite(owner, room["id"])["code"]
        failures.append(
            already_paired.post("/api/room-invites/join", json={"code": valid_code})
        )
        joined = member.post("/api/room-invites/join", json={"code": valid_code})
        failures.extend(
            [
                member.post("/api/room-invites/join", json={"code": valid_code}),
                third.post("/api/room-invites/join", json={"code": valid_code}),
            ]
        )

    assert joined.status_code == 200
    assert_public_room(joined.json())
    assert joined.json()["state"] == "paired"
    assert joined.json()["partner"]["id"] == owner_profile["id"]
    assert [(failure.status_code, failure.json()) for failure in failures] == [
        (409, {"detail": "invite unavailable"})
    ] * len(failures)
    members = fetch_all(
        db_path,
        "SELECT user_id, role, slot FROM room_members "
        "WHERE room_id=? AND left_at IS NULL ORDER BY slot",
        (room["id"],),
    )
    assert [dict(row) for row in members] == [
        {"user_id": owner_profile["id"], "role": "owner", "slot": 1},
        {"user_id": member_profile["id"], "role": "member", "slot": 2},
    ]
    invites = fetch_all(
        db_path,
        "SELECT code_hash, consumed_at, consumed_by_user_id, revoked_at "
        "FROM room_invites WHERE room_id=?",
        (room["id"],),
    )
    assert sum(row["consumed_at"] is not None for row in invites) == 1
    assert all(
        row["consumed_at"] is not None or row["revoked_at"] is not None
        for row in invites
    )


def test_two_accounts_racing_same_invite_fill_slot_two_exactly_once(rooms_app):
    app, db_path = rooms_app
    with ExitStack() as stack:
        owner = stack.enter_context(client_for(app))
        first = stack.enter_context(client_for(app))
        second = stack.enter_context(client_for(app))
        register(owner, "owner", "甲")
        register(first, "first", "乙")
        register(second, "second", "丙")
        room = owner.post("/api/rooms").json()
        code = create_invite(owner, room["id"])["code"]
        barrier = threading.Barrier(3)

        def join(client):
            barrier.wait(timeout=5)
            response = client.post("/api/room-invites/join", json={"code": code})
            return response.status_code, response.json()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(join, first), pool.submit(join, second)]
            barrier.wait(timeout=5)
            results = [future.result(timeout=10) for future in futures]

    assert sorted(status_code for status_code, _ in results) == [200, 409]
    assert [body for status_code, body in results if status_code == 409] == [
        {"detail": "invite unavailable"}
    ]
    count = fetch_one(
        db_path,
        "SELECT COUNT(*) AS count FROM room_members "
        "WHERE room_id=? AND left_at IS NULL",
        (room["id"],),
    )["count"]
    assert count == 2
    assert fetch_one(
        db_path,
        "SELECT COUNT(*) AS count FROM room_members "
        "WHERE room_id=? AND slot=2 AND left_at IS NULL",
        (room["id"],),
    )["count"] == 1


@pytest.mark.parametrize("leaver", ["owner", "member"])
def test_leaving_waiting_or_paired_room_closes_it_for_everyone(rooms_app, leaver):
    app, db_path = rooms_app
    with client_for(app) as owner, client_for(app) as member:
        register(owner, f"owner-{leaver}", "甲")
        register(member, f"member-{leaver}", "乙")
        room = owner.post("/api/rooms").json()
        code = create_invite(owner, room["id"])["code"]
        if leaver == "member":
            assert member.post(
                "/api/room-invites/join", json={"code": code}
            ).status_code == 200

        closing_client = owner if leaver == "owner" else member
        closed = closing_client.post(f"/api/rooms/{room['id']}/leave")
        owner_current = owner.get("/api/rooms/current")
        member_current = member.get("/api/rooms/current")
        replay = member.post("/api/room-invites/join", json={"code": code})

    assert closed.status_code == 204
    assert owner_current.status_code == member_current.status_code == 200
    assert owner_current.json() is None
    assert member_current.json() is None
    assert replay.status_code == 409
    db_room = fetch_one(
        db_path, "SELECT status, closed_at FROM rooms WHERE id=?", (room["id"],)
    )
    assert db_room["status"] == "closed"
    assert db_room["closed_at"] is not None
    memberships = fetch_all(
        db_path, "SELECT left_at FROM room_members WHERE room_id=?", (room["id"],)
    )
    assert memberships
    assert all(row["left_at"] is not None for row in memberships)
    invite = fetch_one(
        db_path,
        "SELECT consumed_at, revoked_at FROM room_invites WHERE room_id=?",
        (room["id"],),
    )
    if leaver == "owner":
        assert invite["consumed_at"] is None
        assert invite["revoked_at"] is not None
    else:
        assert invite["consumed_at"] is not None


def test_unrelated_room_id_is_indistinguishable_from_missing_room(rooms_app):
    app, _ = rooms_app
    with client_for(app) as first, client_for(app) as second:
        register(first, "first", "甲")
        register(second, "second", "乙")
        first_room = first.post("/api/rooms").json()
        second_room = second.post("/api/rooms").json()

        real_invite = first.post(f"/api/rooms/{second_room['id']}/invites")
        fake_invite = first.post("/api/rooms/00000000-0000-0000-0000-000000000000/invites")
        real_leave = first.post(f"/api/rooms/{second_room['id']}/leave")
        fake_leave = first.post("/api/rooms/00000000-0000-0000-0000-000000000000/leave")

    assert first_room["id"] != second_room["id"]
    assert real_invite.status_code == fake_invite.status_code == 404
    assert real_invite.json() == fake_invite.json() == {"detail": "room not found"}
    assert real_leave.status_code == fake_leave.status_code == 404
    assert real_leave.json() == fake_leave.json() == {"detail": "room not found"}


def test_database_constraints_reject_third_slot_invalid_role_duplicate_active_and_fk(
    rooms_app,
):
    app, db_path = rooms_app
    with client_for(app) as owner, client_for(app) as other:
        owner_profile = register(owner, "owner", "甲")
        other_profile = register(other, "other", "乙")
        room = owner.post("/api/rooms").json()

    with sqlite3.connect(db_path) as db:
        db.execute("PRAGMA foreign_keys = ON")

        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                "INSERT INTO room_members (room_id, user_id, role, slot) "
                "VALUES (?, ?, 'member', 3)",
                (room["id"], other_profile["id"]),
            )
        db.rollback()

        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                "INSERT INTO room_members (room_id, user_id, role, slot) "
                "VALUES (?, ?, 'member', 1)",
                (room["id"], other_profile["id"]),
            )
        db.rollback()

        second_room_id = "00000000-0000-0000-0000-000000000001"
        db.execute(
            "INSERT INTO rooms (id, creator_user_id) VALUES (?, ?)",
            (second_room_id, owner_profile["id"]),
        )
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                "INSERT INTO room_members (room_id, user_id, role, slot) "
                "VALUES (?, ?, 'owner', 1)",
                (second_room_id, owner_profile["id"]),
            )
        db.rollback()

        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                "INSERT INTO room_members (room_id, user_id, role, slot) "
                "VALUES (?, 999999, 'member', 2)",
                (room["id"],),
            )
        db.rollback()
