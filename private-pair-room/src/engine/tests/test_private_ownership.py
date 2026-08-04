import base64
import importlib
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Barrier

import pytest
from fastapi.testclient import TestClient


PASSWORD = "correct horse battery"
FOREIGN_ORIGIN = "https://attacker.example"
RECORD_DATE = "2026-08-03"
PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "/wcAAusB9Wl2nWQAAAAASUVORK5CYII="
)


@pytest.fixture
def private_app(tmp_path, monkeypatch):
    monkeypatch.setenv("ZHIJI_DB_PATH", str(tmp_path / "private.sqlite3"))
    monkeypatch.setenv("ZHIJI_UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("FRONTEND_ORIGINS", "http://localhost:5173")
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "false")

    import config
    import database
    import main
    import routers.diary
    import routers.export

    importlib.reload(config)
    importlib.reload(database)
    importlib.reload(routers.diary)
    importlib.reload(routers.export)
    main = importlib.reload(main)

    async def fake_generate_diary(**kwargs):
        return "generated from " + ",".join(
            item.get("title", item.get("content", ""))
            for item in kwargs["schedules"] + kwargs["fragments"]
        )

    async def fake_rewrite(paragraph, direction, custom_prompt):
        return f"rewritten:{paragraph}"

    monkeypatch.setattr(routers.diary, "generate_diary", fake_generate_diary)
    monkeypatch.setattr(routers.diary, "rewrite_paragraph", fake_rewrite)
    return main.app


@contextmanager
def two_accounts(app):
    with TestClient(app, base_url="http://testserver") as alice, TestClient(
        app, base_url="http://testserver"
    ) as bob:
        alice_profile = alice.post(
            "/api/auth/register",
            json={
                "username": "alice",
                "password": PASSWORD,
                "nickname": "Alice",
            },
        )
        bob_profile = bob.post(
            "/api/auth/register",
            json={
                "username": "bob",
                "password": PASSWORD,
                "nickname": "Bob",
            },
        )
        assert alice_profile.status_code == bob_profile.status_code == 201
        yield alice, bob, alice_profile.json(), bob_profile.json()


def create_private_records(client, supplied_user_id):
    schedule = client.post(
        "/api/schedules",
        json={
            "date": RECORD_DATE,
            "time": "09:00",
            "title": "alice schedule",
            "user_id": supplied_user_id,
        },
    )
    fragment = client.post(
        "/api/fragments",
        json={
            "date": RECORD_DATE,
            "content": "alice fragment",
            "user_id": supplied_user_id,
        },
    )
    diary = client.post(
        "/api/diary",
        json={"date": RECORD_DATE, "user_id": supplied_user_id},
    )
    assert schedule.status_code == fragment.status_code == diary.status_code == 200
    return schedule.json(), fragment.json(), diary.json()


def test_concurrent_blank_diary_creation_returns_one_owned_row(private_app):
    date = "2026-08-05"
    with TestClient(private_app, base_url="http://testserver") as owner:
        registration = owner.post(
            "/api/auth/register",
            json={
                "username": "concurrent-owner",
                "password": PASSWORD,
                "nickname": "Concurrent Owner",
            },
        )
        assert registration.status_code == 201
        user_id = registration.json()["id"]
        session_token = owner.cookies["zhiji_session"]

        workers = [
            TestClient(
                private_app,
                base_url="http://testserver",
                raise_server_exceptions=False,
            )
            for _ in range(2)
        ]
        start = Barrier(2)

        def create_diary(worker):
            start.wait(timeout=5)
            return worker.post(
                "/api/diary",
                json={"date": date},
                headers={"Cookie": f"zhiji_session={session_token}"},
            )

        try:
            with ThreadPoolExecutor(max_workers=2) as executor:
                responses = list(executor.map(create_diary, workers))
        finally:
            for worker in workers:
                worker.close()

    assert [response.status_code for response in responses] == [200, 200]
    response_ids = {response.json()["id"] for response in responses}
    assert len(response_ids) == 1

    import config

    with sqlite3.connect(config.get_db_path()) as db:
        rows = db.execute(
            "SELECT id FROM diaries WHERE user_id = ? AND date = ?",
            (user_id, date),
        ).fetchall()
    assert rows == [(response_ids.pop(),)]


def test_creates_ignore_client_user_id_and_reads_are_current_user_only(private_app):
    with two_accounts(private_app) as (alice, bob, alice_profile, bob_profile):
        schedule, fragment, diary = create_private_records(
            alice, supplied_user_id=bob_profile["id"]
        )

        assert schedule["user_id"] == alice_profile["id"]
        assert fragment["user_id"] == alice_profile["id"]
        assert diary["user_id"] == alice_profile["id"]

        assert bob.get(
            "/api/schedules",
            params={"date": RECORD_DATE, "user_id": alice_profile["id"]},
        ).json() == []
        assert bob.get(
            "/api/fragments",
            params={"date": RECORD_DATE, "user_id": alice_profile["id"]},
        ).json() == []
        assert bob.get(
            "/api/diary",
            params={"date": RECORD_DATE, "user_id": alice_profile["id"]},
        ).json() is None
        assert bob.get(
            "/api/diary/list", params={"user_id": alice_profile["id"]}
        ).json() == []

        bob_schedule = bob.post(
            "/api/schedules",
            json={
                "date": RECORD_DATE,
                "title": "bob schedule",
                "user_id": alice_profile["id"],
            },
        )
        assert bob_schedule.status_code == 200
        assert bob_schedule.json()["user_id"] == bob_profile["id"]


def test_foreign_record_ids_cannot_be_updated_deleted_or_used_by_ai(private_app):
    with two_accounts(private_app) as (alice, bob, alice_profile, bob_profile):
        schedule, fragment, diary = create_private_records(
            alice, supplied_user_id=alice_profile["id"]
        )

        attempts = [
            bob.put(
                f"/api/schedules/{schedule['id']}",
                json={"title": "stolen schedule"},
            ),
            bob.delete(f"/api/schedules/{schedule['id']}"),
            bob.put(
                f"/api/fragments/{fragment['id']}",
                json={"content": "stolen fragment"},
            ),
            bob.delete(f"/api/fragments/{fragment['id']}"),
            bob.put(
                f"/api/diary/{diary['id']}",
                json={"text": "stolen diary"},
            ),
            bob.post(
                f"/api/diary/{diary['id']}/ai-fill",
                json={"emotion_mode": "warm"},
            ),
            bob.post(
                f"/api/diary/{diary['id']}/ai-rewrite",
                json={"paragraph": "private", "direction": "warmer"},
            ),
        ]
        assert [response.status_code for response in attempts] == [404] * len(
            attempts
        )

        assert alice.get(
            "/api/schedules", params={"date": RECORD_DATE}
        ).json()[0]["title"] == "alice schedule"
        assert alice.get(
            "/api/fragments", params={"date": RECORD_DATE}
        ).json()[0]["content"] == "alice fragment"
        assert alice.get("/api/diary", params={"date": RECORD_DATE}).json()[
            "text"
        ] == ""


def test_diary_ai_fill_uses_only_current_users_source_records(private_app):
    with two_accounts(private_app) as (alice, bob, alice_profile, bob_profile):
        assert alice.post(
            "/api/schedules",
            json={"date": RECORD_DATE, "title": "alice private source"},
        ).status_code == 200
        bob_diary = bob.post("/api/diary", json={"date": RECORD_DATE}).json()

        response = bob.post(
            f"/api/diary/{bob_diary['id']}/ai-fill",
            json={"emotion_mode": "warm"},
        )

        assert response.status_code == 400
        assert response.json() == {"detail": "当天没有任何记录，无法用 AI 填充"}


def test_profile_stats_streak_and_export_cannot_select_another_user(
    private_app, monkeypatch
):
    import routers.export

    class RecordingDocument:
        def __init__(self, target, **kwargs):
            self.target = target

        def build(self, flow):
            text = "|".join(
                item.getPlainText() for item in flow if hasattr(item, "getPlainText")
            )
            self.target.write(text.encode("utf-8"))

    monkeypatch.setattr(routers.export, "SimpleDocTemplate", RecordingDocument)

    with two_accounts(private_app) as (alice, bob, alice_profile, bob_profile):
        create_private_records(alice, supplied_user_id=alice_profile["id"])
        alice_diary = alice.get(
            "/api/diary", params={"date": RECORD_DATE}
        ).json()
        assert alice.put(
            f"/api/diary/{alice_diary['id']}",
            json={"text": "ALICE-EXPORT-SECRET", "status": "confirmed"},
        ).status_code == 200

        profile = bob.get(
            "/api/profile", params={"user_id": alice_profile["id"]}
        )
        assert profile.status_code == 200
        assert profile.json()["id"] == bob_profile["id"]
        updated = bob.put(
            "/api/profile",
            params={"user_id": alice_profile["id"]},
            json={"nickname": "Bob Updated", "user_id": alice_profile["id"]},
        )
        assert updated.status_code == 200
        assert updated.json()["id"] == bob_profile["id"]
        assert alice.get("/api/profile").json()["nickname"] == "Alice"

        stats = bob.get(
            "/api/stats", params={"user_id": alice_profile["id"]}
        ).json()
        assert stats["diary_count"] == 0
        assert stats["fragment_count"] == 0
        assert stats["month_checkins"] == 0
        streaks = bob.get(
            "/api/streaks", params={"user_id": alice_profile["id"]}
        ).json()
        assert streaks["calendar_data"] == {}

        poisoned_export = bob.post(
            "/api/export/pdf", params={"user_id": alice_profile["id"]}
        )
        assert poisoned_export.status_code == 400

        bob_diary = bob.post("/api/diary", json={"date": "2026-08-04"}).json()
        assert bob.put(
            f"/api/diary/{bob_diary['id']}",
            json={"text": "BOB-EXPORT-ONLY", "status": "confirmed"},
        ).status_code == 200
        own_export = bob.post(
            "/api/export/pdf", params={"user_id": alice_profile["id"]}
        )
        assert own_export.status_code == 200
        assert b"BOB-EXPORT-ONLY" in own_export.content
        assert b"ALICE-EXPORT-SECRET" not in own_export.content


def test_pdf_export_includes_owned_canonical_images_and_escapes_markup(
    private_app, monkeypatch
):
    import config
    import routers.export

    captured_paths = []

    class RecordingDocument:
        def __init__(self, target, **kwargs):
            self.target = target

        def build(self, flow):
            text = "|".join(
                item.getPlainText() for item in flow if hasattr(item, "getPlainText")
            )
            self.target.write(text.encode("utf-8"))

    def recording_image(path, **kwargs):
        captured_paths.append(path)
        return object()

    monkeypatch.setattr(routers.export, "SimpleDocTemplate", RecordingDocument)
    monkeypatch.setattr(routers.export, "RLImage", recording_image)

    with TestClient(private_app, base_url="http://testserver") as owner:
        assert owner.post(
            "/api/auth/register",
            json={
                "username": "pdf-owner",
                "password": PASSWORD,
                "nickname": "PDF Owner",
            },
        ).status_code == 201
        uploaded_response = owner.post(
            "/api/upload",
            files={"file": ("diary.png", PNG_BYTES, "image/png")},
        )
        assert uploaded_response.status_code == 200
        uploaded = uploaded_response.json()

        malicious_date = '<img src="http://127.0.0.1/date.png"/>'
        malicious_text = '<img src="http://169.254.169.254/latest/meta-data"/>'
        diary = owner.post("/api/diary", json={"date": malicious_date}).json()
        assert owner.put(
            f"/api/diary/{diary['id']}",
            json={"text": malicious_text, "status": "confirmed"},
        ).status_code == 200

        with sqlite3.connect(config.get_db_path()) as db:
            db.execute(
                "INSERT INTO images "
                "(diary_id, style, url, asset_id, kept) VALUES (?, ?, ?, ?, 1)",
                (
                    diary["id"],
                    "watercolor",
                    uploaded["url"],
                    uploaded["asset_id"],
                ),
            )
            db.commit()

        exported = owner.post("/api/export/pdf")
        assert exported.status_code == 200
        assert malicious_date.encode() in exported.content
        assert malicious_text.encode() in exported.content
        assert len(captured_paths) == 1
        assert captured_paths[0].read_bytes() == PNG_BYTES


def test_unknown_diary_update_is_404_and_users_endpoint_is_removed(private_app):
    with two_accounts(private_app) as (alice, bob, alice_profile, bob_profile):
        response = alice.put("/api/diary/999999", json={"text": "missing"})
        assert response.status_code == 404
        assert response.json() == {"detail": "diary not found"}

        assert alice.get("/api/users").status_code == 404
        assert TestClient(private_app).get("/api/users").status_code == 404


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("post", "/api/schedules", {"date": RECORD_DATE, "title": "x"}),
        ("get", f"/api/schedules?date={RECORD_DATE}", None),
        ("put", "/api/schedules/1", {"title": "x"}),
        ("delete", "/api/schedules/1", None),
        ("post", "/api/fragments", {"date": RECORD_DATE, "content": "x"}),
        ("get", f"/api/fragments?date={RECORD_DATE}", None),
        ("put", "/api/fragments/1", {"content": "x"}),
        ("delete", "/api/fragments/1", None),
        ("get", "/api/streaks", None),
        ("post", "/api/diary", {"date": RECORD_DATE}),
        ("get", f"/api/diary?date={RECORD_DATE}", None),
        ("get", "/api/diary/list", None),
        ("put", "/api/diary/1", {"text": "x"}),
        ("post", "/api/diary/1/ai-fill", {"emotion_mode": "warm"}),
        (
            "post",
            "/api/diary/1/ai-rewrite",
            {"paragraph": "x", "direction": "warmer"},
        ),
        ("get", "/api/profile", None),
        ("put", "/api/profile", {"nickname": "x"}),
        ("get", "/api/stats", None),
        ("post", "/api/export/pdf", None),
    ],
)
def test_all_private_routes_require_auth(private_app, method, path, payload):
    with TestClient(private_app, base_url="http://testserver") as client:
        response = client.request(method, path, json=payload)

    assert response.status_code == 401
    assert response.json() == {"detail": "authentication required"}


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("post", "/api/schedules", {"date": RECORD_DATE, "title": "x"}),
        ("put", "/api/schedules/1", {"title": "x"}),
        ("delete", "/api/schedules/1", None),
        ("post", "/api/fragments", {"date": RECORD_DATE, "content": "x"}),
        ("put", "/api/fragments/1", {"content": "x"}),
        ("delete", "/api/fragments/1", None),
        ("post", "/api/diary", {"date": RECORD_DATE}),
        ("put", "/api/diary/1", {"text": "x"}),
        ("post", "/api/diary/1/ai-fill", {"emotion_mode": "warm"}),
        (
            "post",
            "/api/diary/1/ai-rewrite",
            {"paragraph": "x", "direction": "warmer"},
        ),
        ("put", "/api/profile", {"nickname": "x"}),
        ("post", "/api/export/pdf", None),
    ],
)
def test_all_private_mutations_reject_foreign_origin(
    private_app, method, path, payload
):
    with TestClient(private_app, base_url="http://testserver") as client:
        assert client.post(
            "/api/auth/register",
            json={
                "username": "origin-user",
                "password": PASSWORD,
                "nickname": "Origin User",
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
