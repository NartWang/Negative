import hashlib
import importlib
import json
import sqlite3
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient


PASSWORD = "correct horse battery"
FOREIGN_ORIGIN = "https://attacker.example"
RECORD_DATE = "2026-08-03"


@pytest.fixture
def generated_app(tmp_path, monkeypatch):
    db_path = tmp_path / "generated.sqlite3"
    monkeypatch.setenv("ZHIJI_DB_PATH", str(db_path))
    monkeypatch.setenv("ZHIJI_UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("FRONTEND_ORIGINS", "http://localhost:5173")
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "false")

    import config
    import database
    import main
    import agents.image_agent
    import routers.dual_timeline
    import routers.image
    import routers.thermometer
    import routers.transform
    import routers.weekly_comic

    importlib.reload(config)
    importlib.reload(database)
    importlib.reload(routers.image)
    weekly_router = importlib.reload(routers.weekly_comic)
    thermometer_router = importlib.reload(routers.thermometer)
    dual_router = importlib.reload(routers.dual_timeline)
    transform_router = importlib.reload(routers.transform)
    main = importlib.reload(main)

    calls = {"dual_plan": []}

    fake_png = (
        "data:image/png;base64,"
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
        "/wcAAusB9Wl2nWQAAAAASUVORK5CYII="
    )

    async def fake_batch(**kwargs):
        return [fake_png]

    async def fake_weekly_plan(**kwargs):
        return "weekly prompt", "weekly caption"

    async def fake_image(**kwargs):
        return fake_png

    async def fake_temperature(nickname, schedules, fragments):
        return 0, f"{nickname}:{len(schedules)}:{len(fragments)}"

    async def fake_summary(date, user_a_name, events_a, user_b_name, events_b):
        return f"{user_a_name}:{len(events_a)}|{user_b_name}:{len(events_b)}"

    async def fake_dual_plan(**kwargs):
        calls["dual_plan"].append(kwargs)
        return "dual prompt", "dual caption"

    async def fake_transform(nag_text, relation):
        return {
            "help_request": f"help:{relation}",
            "co_challenge": "challenge",
            "warm_echo": nag_text,
        }

    monkeypatch.setattr(agents.image_agent, "generate_batch", fake_batch)
    monkeypatch.setattr(weekly_router, "plan_weekly_comic", fake_weekly_plan)
    monkeypatch.setattr(weekly_router, "generate_image", fake_image)
    monkeypatch.setattr(
        thermometer_router, "ai_score_and_comment", fake_temperature
    )
    monkeypatch.setattr(dual_router, "summarize", fake_summary)
    monkeypatch.setattr(dual_router, "plan_comic", fake_dual_plan)
    monkeypatch.setattr(dual_router, "generate_image", fake_image)
    monkeypatch.setattr(transform_router, "transform_nagging", fake_transform)

    return main.app, db_path, calls


@contextmanager
def two_accounts(app):
    with TestClient(app, base_url="http://testserver") as alice, TestClient(
        app, base_url="http://testserver"
    ) as bob:
        alice_profile = alice.post(
            "/api/auth/register",
            json={
                "username": "alice-generated",
                "password": PASSWORD,
                "nickname": "Alice",
            },
        )
        bob_profile = bob.post(
            "/api/auth/register",
            json={
                "username": "bob-generated",
                "password": PASSWORD,
                "nickname": "Bob",
            },
        )
        assert alice_profile.status_code == bob_profile.status_code == 201
        yield alice, bob, alice_profile.json(), bob_profile.json()


def seed_active_pair(db_path, alice_id, bob_id):
    with sqlite3.connect(db_path) as db:
        db.execute(
            "INSERT INTO rooms (id, creator_user_id, status) VALUES (?, ?, 'active')",
            ("room-generated", alice_id),
        )
        db.executemany(
            "INSERT INTO room_members (room_id, user_id, role, slot) "
            "VALUES ('room-generated', ?, ?, ?)",
            [(alice_id, "owner", 1), (bob_id, "member", 2)],
        )
        db.commit()


def seed_partner_post(
    db_path,
    bob_id,
    *,
    post_id="partner-published",
    status="published",
    date=RECORD_DATE,
    content="PARTNER-PUBLISHED-SNAPSHOT",
):
    snapshot = {"date": date, "body": content, "kind": "note"}
    snapshot_json = json.dumps(snapshot, ensure_ascii=False, sort_keys=True)
    with sqlite3.connect(db_path) as db:
        db.execute(
            "INSERT INTO room_posts "
            "(id, room_id, author_user_id, source_type, source_id, "
            "source_revision, snapshot_hash, snapshot_json, status) "
            "VALUES (?, 'room-generated', ?, 'note', NULL, NULL, ?, ?, ?)",
            (
                post_id,
                bob_id,
                hashlib.sha256(snapshot_json.encode()).hexdigest(),
                snapshot_json,
                status,
            ),
        )
        db.commit()
    return snapshot


def create_diary_with_text(client, date=RECORD_DATE, text="private diary"):
    diary = client.post("/api/diary", json={"date": date})
    assert diary.status_code == 200
    updated = client.put(
        f"/api/diary/{diary.json()['id']}",
        json={"text": text},
    )
    assert updated.status_code == 200
    return updated.json()


def test_image_generation_and_keep_require_owned_diary(generated_app):
    app, _, _ = generated_app
    with two_accounts(app) as (alice, bob, alice_profile, bob_profile):
        alice_diary = create_diary_with_text(alice, text="ALICE-DIARY")

        assert bob.post(
            f"/api/image/diary/{alice_diary['id']}/images/batch",
            json={"style": "watercolor"},
        ).status_code == 404
        assert bob.put(
            f"/api/image/diary/{alice_diary['id']}/images",
            json={"keep_ids": []},
        ).status_code == 404

        alice_generated = alice.post(
            f"/api/image/diary/{alice_diary['id']}/images/batch",
            json={"style": "watercolor"},
        )
        assert alice_generated.status_code == 200
        alice_image_id = alice_generated.json()["candidates"][0]["id"]

        bob_diary = create_diary_with_text(bob, date="2026-08-04", text="BOB")
        bob_generated = bob.post(
            f"/api/image/diary/{bob_diary['id']}/images/batch",
            json={"style": "watercolor"},
        )
        bob_image_id = bob_generated.json()["candidates"][0]["id"]

        foreign_keep = alice.put(
            f"/api/image/diary/{alice_diary['id']}/images",
            json={"keep_ids": [alice_image_id, bob_image_id]},
        )
        assert foreign_keep.status_code == 404

        own_keep = alice.put(
            f"/api/image/diary/{alice_diary['id']}/images",
            json={"keep_ids": [alice_image_id]},
        )
        assert own_keep.status_code == 200
        assert [item["id"] for item in own_keep.json()["images"]] == [
            alice_image_id
        ]


def test_weekly_comics_always_use_current_owner(generated_app):
    app, _, _ = generated_app
    with two_accounts(app) as (alice, bob, alice_profile, bob_profile):
        assert alice.post(
            "/api/schedules",
            json={"date": RECORD_DATE, "title": "ALICE-WEEKLY-SOURCE"},
        ).status_code == 200

        generated = alice.post(
            "/api/weekly-comic/generate",
            json={
                "user_id": bob_profile["id"],
                "week_start": RECORD_DATE,
                "week_end": RECORD_DATE,
                "style": "watercolor",
            },
        )
        assert generated.status_code == 200
        assert generated.json()["user_id"] == alice_profile["id"]
        comic_id = generated.json()["id"]

        assert bob.get(
            "/api/weekly-comic/list",
            params={"user_id": alice_profile["id"]},
        ).json() == []
        assert bob.delete(f"/api/weekly-comic/{comic_id}").status_code == 404
        assert [item["id"] for item in alice.get(
            "/api/weekly-comic/list"
        ).json()] == [comic_id]

        assert alice.delete(f"/api/weekly-comic/{comic_id}").status_code == 200
        assert alice.get("/api/weekly-comic/list").json() == []


def test_thermometer_has_no_public_user_selector(generated_app):
    app, _, _ = generated_app
    with two_accounts(app) as (alice, bob, alice_profile, bob_profile):
        assert alice.post(
            "/api/fragments",
            json={"date": RECORD_DATE, "content": "ALICE-THERMOMETER-SECRET"},
        ).status_code == 200

        response = bob.get(
            "/api/thermometer",
            params={"date": RECORD_DATE, "user_id": alice_profile["id"]},
        )
        assert response.status_code == 200
        assert response.json()["inputs"]["fragments_count"] == 0
        assert response.json()["comment"].startswith("Bob:")

        parameters = app.openapi()["paths"]["/api/thermometer"]["get"][
            "parameters"
        ]
        assert "user_id" not in {item["name"] for item in parameters}


def test_dual_timeline_without_pair_never_reads_requested_users_private_data(
    generated_app,
):
    app, _, _ = generated_app
    with two_accounts(app) as (alice, bob, alice_profile, bob_profile):
        assert alice.post(
            "/api/schedules",
            json={"date": RECORD_DATE, "time": "08:00", "title": "ALICE-OWN"},
        ).status_code == 200
        assert bob.post(
            "/api/schedules",
            json={"date": RECORD_DATE, "time": "09:00", "title": "BOB-PRIVATE"},
        ).status_code == 200

        response = alice.get(
            "/api/dual-timeline",
            params={
                "date": RECORD_DATE,
                "user_a": bob_profile["id"],
                "user_b": bob_profile["id"],
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["user_a"]["id"] == alice_profile["id"]
        assert payload["user_b"] is None
        assert [event["title"] for event in payload["events_a"]] == [
            "ALICE-OWN"
        ]
        assert payload["events_b"] == []
        assert "BOB-PRIVATE" not in response.text


def test_dual_timeline_partner_side_uses_only_active_published_snapshots(
    generated_app,
):
    app, db_path, _ = generated_app
    with two_accounts(app) as (alice, bob, alice_profile, bob_profile):
        seed_active_pair(db_path, alice_profile["id"], bob_profile["id"])
        assert bob.post(
            "/api/fragments",
            json={"date": RECORD_DATE, "content": "BOB-PRIVATE-FRAGMENT"},
        ).status_code == 200

        before_publication = alice.get(
            "/api/dual-timeline", params={"date": RECORD_DATE}
        )
        assert before_publication.status_code == 200
        assert before_publication.json()["events_b"] == []

        published_snapshot = seed_partner_post(db_path, bob_profile["id"])
        seed_partner_post(
            db_path,
            bob_profile["id"],
            post_id="partner-revoked",
            status="revoked",
            content="REVOKED-SNAPSHOT",
        )
        seed_partner_post(
            db_path,
            bob_profile["id"],
            post_id="partner-other-day",
            date="2026-08-02",
            content="OTHER-DAY-SNAPSHOT",
        )

        response = alice.get(
            "/api/dual-timeline", params={"date": RECORD_DATE}
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["user_b"] == {
            "id": bob_profile["id"],
            "nickname": "Bob",
        }
        assert len(payload["events_b"]) == 1
        assert payload["events_b"][0]["id"] == "partner-published"
        assert payload["events_b"][0]["snapshot"] == published_snapshot
        assert "BOB-PRIVATE-FRAGMENT" not in response.text
        assert "REVOKED-SNAPSHOT" not in response.text
        assert "OTHER-DAY-SNAPSHOT" not in response.text


def test_dual_comic_generation_listing_and_delete_derive_active_pair(
    generated_app,
):
    app, db_path, calls = generated_app
    with two_accounts(app) as (alice, bob, alice_profile, bob_profile):
        seed_active_pair(db_path, alice_profile["id"], bob_profile["id"])
        seed_partner_post(db_path, bob_profile["id"])
        assert alice.post(
            "/api/schedules",
            json={"date": RECORD_DATE, "time": "08:00", "title": "ALICE-OWN"},
        ).status_code == 200
        timeline = alice.get(
            "/api/dual-timeline", params={"date": RECORD_DATE}
        ).json()
        assert timeline["events_b"], "published partner snapshot must be selectable"

        generated = alice.post(
            "/api/dual-timeline/comic/generate",
            json={
                "date": RECORD_DATE,
                "user_a": bob_profile["id"],
                "user_b": alice_profile["id"],
                "selected_a": [timeline["events_a"][0]],
                "selected_b": [timeline["events_b"][0]],
                "style": "watercolor",
            },
        )
        assert generated.status_code == 200
        comic = generated.json()
        assert comic["user_a_id"] == alice_profile["id"]
        assert comic["user_b_id"] == bob_profile["id"]
        assert calls["dual_plan"][0]["selected_b"] == timeline["events_b"]

        comic_id = comic["id"]
        assert bob.get(
            "/api/dual-timeline/comic/list",
            params={"user_id": alice_profile["id"]},
        ).json() == []
        assert bob.delete(
            f"/api/dual-timeline/comic/{comic_id}"
        ).status_code == 404
        assert [item["id"] for item in alice.get(
            "/api/dual-timeline/comic/list"
        ).json()] == [comic_id]
        assert alice.delete(
            f"/api/dual-timeline/comic/{comic_id}"
        ).status_code == 200


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        (
            "post",
            "/api/image/diary/1/images/batch",
            {"style": "watercolor"},
        ),
        ("put", "/api/image/diary/1/images", {"keep_ids": []}),
        (
            "post",
            "/api/weekly-comic/generate",
            {
                "week_start": RECORD_DATE,
                "week_end": RECORD_DATE,
                "style": "watercolor",
            },
        ),
        ("get", "/api/weekly-comic/list", None),
        ("delete", "/api/weekly-comic/1", None),
        ("get", f"/api/thermometer?date={RECORD_DATE}", None),
        ("get", f"/api/dual-timeline?date={RECORD_DATE}", None),
        (
            "post",
            "/api/dual-timeline/comic/generate",
            {"date": RECORD_DATE, "selected_a": [{"type": "schedule", "id": 1}]},
        ),
        ("get", "/api/dual-timeline/comic/list", None),
        ("delete", "/api/dual-timeline/comic/1", None),
        ("get", "/api/transform/nagging/inbox", None),
        (
            "post",
            "/api/transform/nagging/transform",
            {"nag_text": "早点睡"},
        ),
    ],
)
def test_generated_routes_require_auth(generated_app, method, path, payload):
    app, _, _ = generated_app
    with TestClient(app, base_url="http://testserver") as client:
        response = client.request(method, path, json=payload)

    assert response.status_code == 401
    assert response.json() == {"detail": "authentication required"}


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        (
            "post",
            "/api/image/diary/1/images/batch",
            {"style": "watercolor"},
        ),
        ("put", "/api/image/diary/1/images", {"keep_ids": []}),
        (
            "post",
            "/api/weekly-comic/generate",
            {
                "week_start": RECORD_DATE,
                "week_end": RECORD_DATE,
                "style": "watercolor",
            },
        ),
        ("delete", "/api/weekly-comic/1", None),
        (
            "post",
            "/api/dual-timeline/comic/generate",
            {"date": RECORD_DATE, "selected_a": [{"type": "schedule", "id": 1}]},
        ),
        ("delete", "/api/dual-timeline/comic/1", None),
        (
            "post",
            "/api/transform/nagging/transform",
            {"nag_text": "早点睡"},
        ),
    ],
)
def test_generated_mutations_reject_foreign_origin(
    generated_app, method, path, payload
):
    app, _, _ = generated_app
    with TestClient(app, base_url="http://testserver") as client:
        assert client.post(
            "/api/auth/register",
            json={
                "username": "generated-origin",
                "password": PASSWORD,
                "nickname": "Origin",
            },
        ).status_code == 201
        response = client.request(
            method,
            path,
            json=payload,
            headers={"Origin": FOREIGN_ORIGIN},
        )

    assert response.status_code == 403
    assert response.json() == {"detail": "origin not allowed"}
