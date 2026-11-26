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
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR42mP8"
    "/5+hHgAHggJ/PvKVWQAAAABJRU5ErkJggg=="
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


def insert_pdf_canonical_picturebook(
    db,
    *,
    user_id,
    diary_id,
    day,
    title="Canonical PDF Book",
    page_prefix="pdf-canonical",
    status="ready",
    stage="ready",
    active=False,
    page_indexes=range(9),
    assets_by_page=None,
):
    cursor = db.execute(
        """
        INSERT INTO story_works (
            owner_user_id, source_diary_id, title, medium, narrative_mode,
            style, selected_segments_json, status, kind, stage,
            source_start_date, source_end_date, display_start_date,
            display_end_date, selected_storyline_json, narrative_text,
            created_at, updated_at
        ) VALUES (?, ?, ?, 'picture_book', 'daily', 'watercolor', '[]', ?,
            'daily_picturebook', ?, ?, ?, ?, ?, '[]', 'narrative', ?, ?)
        """,
        (
            user_id,
            diary_id,
            title,
            status,
            stage,
            day,
            day,
            day,
            day,
            "2026-08-12T12:00:00Z",
            "2026-08-12T12:00:00Z",
        ),
    )
    work_id = cursor.lastrowid
    cursor = db.execute(
        """
        INSERT INTO picturebook_jobs (
            user_id, diary_id, work_id, source_text, source_signature, style,
            status, stage, total_pages, created_at, updated_at
        ) VALUES (?, NULL, ?, 'source text', 'source signature', 'watercolor',
            ?, ?, 9, ?, ?)
        """,
        (
            user_id,
            work_id,
            "running" if active else "done",
            "rendering" if active else "done",
            "2026-08-12T12:00:00Z",
            "2026-08-12T12:00:00Z",
        ),
    )
    job_id = cursor.lastrowid
    for index in page_indexes:
        owned_asset = (assets_by_page or {}).get(index)
        page_url = owned_asset["url"] if owned_asset else f"/api/upload/missing-{page_prefix}-{index}.png"
        asset_id = owned_asset["asset_id"] if owned_asset else f"{page_prefix}-asset-{index}"
        db.execute(
            """
            INSERT INTO picturebook_pages (
                job_id, page_index, image_id, caption, image_url, asset_id,
                status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'ready', ?, ?)
            """,
            (
                job_id,
                index,
                f"{page_prefix}-image-{index}",
                f"{page_prefix} job page {index}",
                page_url,
                asset_id,
                "2026-08-12T12:00:00Z",
                "2026-08-12T12:00:00Z",
            ),
        )
        if status in {"ready", "published"}:
            db.execute(
                """
                INSERT INTO work_assets (
                    work_id, ordinal, asset_type, url, asset_id, text
                ) VALUES (?, ?, 'image', ?, ?, ?)
                """,
                (
                    work_id,
                    index,
                    page_url,
                    asset_id,
                    f"{page_prefix} formal page {index}",
                ),
            )
    if active:
        db.execute(
            "UPDATE story_works SET active_picturebook_job_id = ? WHERE id = ?",
            (job_id, work_id),
        )
    else:
        db.execute(
            """
            UPDATE story_works
            SET picturebook_job_id = ?, cover_asset_id = ?
            WHERE id = ?
            """,
            (job_id, (assets_by_page or {}).get(0, {}).get("asset_id", f"{page_prefix}-asset-0"), work_id),
        )
    return work_id, job_id


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
            bob.delete(f"/api/diary/{diary['id']}"),
            bob.post(
                f"/api/diary/{diary['id']}/ai-fill",
                json={"emotion_mode": "imagery"},
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


def test_owned_diary_can_be_deleted_without_touching_other_users(private_app):
    with two_accounts(private_app) as (alice, bob, alice_profile, bob_profile):
        _, _, alice_diary = create_private_records(
            alice, supplied_user_id=alice_profile["id"]
        )
        _, _, bob_diary = create_private_records(
            bob, supplied_user_id=alice_profile["id"]
        )

        blocked = bob.delete(f"/api/diary/{alice_diary['id']}")
        assert blocked.status_code == 404

        deleted = alice.delete(f"/api/diary/{alice_diary['id']}")
        assert deleted.status_code == 204
        assert alice.get("/api/diary", params={"date": RECORD_DATE}).json() is None
        assert bob.get("/api/diary", params={"date": RECORD_DATE}).json()["id"] == bob_diary["id"]


def test_diary_ai_fill_uses_only_current_users_source_records(private_app):
    with two_accounts(private_app) as (alice, bob, alice_profile, bob_profile):
        assert alice.post(
            "/api/schedules",
            json={"date": RECORD_DATE, "title": "alice private source"},
        ).status_code == 200
        bob_diary = bob.post("/api/diary", json={"date": RECORD_DATE}).json()

        response = bob.post(
            f"/api/diary/{bob_diary['id']}/ai-fill",
            json={"emotion_mode": "imagery"},
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


def test_day_pdf_export_includes_owned_complete_day_flow_and_images(
    private_app, monkeypatch
):
    import config
    import routers.export

    captured_paths = []
    cover_paths = []

    class RecordingDocument:
        def __init__(self, target, **kwargs):
            self.target = target

        def build(self, flow):
            cover_paths.extend(
                item.cover_path
                for item in flow
                if getattr(item, "cover_path", None) is not None
            )
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
        registration = owner.post(
            "/api/auth/register",
            json={
                "username": "day-pdf-owner",
                "password": PASSWORD,
                "nickname": "Day PDF Owner",
            },
        )
        assert registration.status_code == 201
        user_id = registration.json()["id"]

        uploaded_response = owner.post(
            "/api/upload",
            files={"file": ("fragment.png", PNG_BYTES, "image/png")},
        )
        assert uploaded_response.status_code == 200
        uploaded = uploaded_response.json()

        assert owner.post(
            "/api/schedules",
            json={
                "date": "2026-08-08",
                "time": "09:00",
                "title": "晨间散步",
                "completed": True,
                "feeling": "轻松",
            },
        ).status_code == 200
        fragment_response = owner.post(
            "/api/fragments",
            json={
                "date": "2026-08-08",
                "content": "桥边的光落在水面上。",
                "photo_url": uploaded["url"],
                "photo_asset_id": uploaded["asset_id"],
                "photo_description": "桥边水面反光",
                "mood_tag": "明亮",
            },
        )
        assert fragment_response.status_code == 200
        assert owner.post(
            "/api/schedules",
            json={
                "date": "2026-08-08",
                "time": "11:00",
                "title": "写下观察",
                "completed": False,
                "feeling": "专注",
            },
        ).status_code == 200
        diary = owner.post("/api/diary", json={"date": "2026-08-08"}).json()
        assert owner.put(
            f"/api/diary/{diary['id']}",
            json={"text": "今天的片段已经串起来了。", "status": "confirmed"},
        ).status_code == 200

        with sqlite3.connect(config.get_db_path()) as db:
            db.execute(
                "UPDATE fragments SET created_at = ? WHERE id = ?",
                ("2026-08-08T02:00:00Z", fragment_response.json()["id"]),
            )
            cursor = db.execute(
                """
                INSERT INTO picturebook_jobs (
                    user_id, diary_id, style, status, stage,
                    total_pages, created_at, updated_at
                ) VALUES (?, ?, 'watercolor', 'done', 'done', 9, ?, ?)
                """,
                (
                    user_id,
                    diary["id"],
                    "2026-08-08T12:00:00Z",
                    "2026-08-08T12:00:00Z",
                ),
            )
            job_id = cursor.lastrowid
            for page_index, caption in enumerate(
                [
                    "水边拍照的一天",
                    "桥边的光",
                    "写下观察",
                    "午后的影子",
                    "晚风",
                    "回家的路",
                    "灯光",
                    "睡前回想",
                    "一天结束",
                ]
            ):
                db.execute(
                    """
                    INSERT INTO picturebook_pages (
                        job_id, page_index, image_id, caption, image_url, status,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, 'ready', ?, ?)
                    """,
                    (
                        job_id,
                        page_index,
                        f"page-{page_index}",
                        caption,
                        f"/api/upload/missing-page-{page_index}.png",
                        "2026-08-08T12:00:00Z",
                        "2026-08-08T12:00:00Z",
                    ),
                )
            cursor = db.execute(
                """
                INSERT INTO story_works (
                    owner_user_id, source_diary_id, title, medium, narrative_mode,
                    style, selected_segments_json, status, created_at, updated_at
                ) VALUES (?, ?, '桥边的光', 'picture_book', 'warm', 'watercolor',
                    '["桥边的光落在水面上。"]', 'ready', ?, ?)
                """,
                (
                    user_id,
                    diary["id"],
                    "2026-08-08T12:30:00Z",
                    "2026-08-08T12:30:00Z",
                ),
            )
            work_id = cursor.lastrowid
            db.execute(
                """
                INSERT INTO work_assets (work_id, ordinal, asset_type, text)
                VALUES (?, 0, 'text', '一部短短的水边故事。')
                """,
                (work_id,),
            )
            db.commit()

        exported = owner.post("/api/export/day/2026-08-08/pdf")

    assert exported.status_code == 200, exported.text
    assert (
        exported.headers["content-disposition"]
        == 'attachment; filename="zhiji-2026-08-08.pdf"'
    )
    text = exported.content.decode("utf-8")
    expected_order = [
        "2026年8月8日",
        "桥边的光",
        "09:00",
        "晨间散步",
        "轻松",
        "10:00",
        "桥边的光落在水面上。",
        "明亮",
        "11:00",
        "写下观察",
        "专注",
        "今天的片段已经串起来了。",
        "水边拍照的一天",
        "桥边的光",
        "写下观察",
        "午后的影子",
        "晚风",
        "回家的路",
        "灯光",
        "睡前回想",
        "一天结束",
        "一部短短的水边故事。",
    ]
    cursor = 0
    for item in expected_order:
        cursor = text.index(item, cursor) + len(item)
    assert "知己" not in text
    assert "桥边水面反光" not in text
    assert len(cover_paths) == 1
    assert cover_paths[0].read_bytes() == PNG_BYTES
    assert len(captured_paths) == 1
    assert captured_paths[0].read_bytes() == PNG_BYTES


def test_day_pdf_export_renders_canonical_picturebook_once(private_app, monkeypatch):
    import config
    import routers.export

    captured_paths = []
    cover_paths = []

    class ImageMarker:
        def __init__(self, index):
            self.index = index

        def getPlainText(self):
            return f"IMAGE-{self.index}"

    class RecordingDocument:
        def __init__(self, target, **kwargs):
            self.target = target

        def build(self, flow):
            cover_paths.extend(
                item.cover_path
                for item in flow
                if getattr(item, "cover_path", None) is not None
            )
            text = "|".join(
                item.getPlainText() for item in flow if hasattr(item, "getPlainText")
            )
            self.target.write(text.encode("utf-8"))

    def recording_image(path, **kwargs):
        captured_paths.append(path)
        return ImageMarker(len(captured_paths) - 1)

    monkeypatch.setattr(routers.export, "SimpleDocTemplate", RecordingDocument)
    monkeypatch.setattr(routers.export, "RLImage", recording_image)

    with TestClient(private_app, base_url="http://testserver") as owner:
        registration = owner.post(
            "/api/auth/register",
            json={
                "username": "canonical-day-pdf",
                "password": PASSWORD,
                "nickname": "Canonical Day PDF",
            },
        )
        assert registration.status_code == 201
        user_id = registration.json()["id"]

        diary = owner.post("/api/diary", json={"date": "2026-08-12"}).json()
        assert owner.put(
            f"/api/diary/{diary['id']}",
            json={"text": "Canonical source diary.", "status": "confirmed"},
        ).status_code == 200
        page_assets = {}
        for page_index in range(9):
            upload = owner.post(
                "/api/upload",
                files={"file": (f"page-{page_index}.png", PNG_BYTES, "image/png")},
            )
            assert upload.status_code == 200
            page_assets[page_index] = upload.json()

        with sqlite3.connect(config.get_db_path()) as db:
            insert_pdf_canonical_picturebook(
                db,
                user_id=user_id,
                diary_id=diary["id"],
                day="2026-08-12",
                title="Canonical PDF Book",
                page_prefix="canonical-pdf",
                assets_by_page=page_assets,
            )
            insert_pdf_canonical_picturebook(
                db,
                user_id=user_id,
                diary_id=diary["id"],
                day="2026-08-12",
                title="Active Partial PDF Book",
                status="draft",
                stage="render_failed",
                active=True,
                page_indexes=range(2),
                page_prefix="active-partial-pdf",
            )
            db.commit()

        exported = owner.post("/api/export/day/2026-08-12/pdf")

    assert exported.status_code == 200, exported.text
    text = exported.content.decode("utf-8")
    captions = [f"canonical-pdf formal page {index}" for index in range(9)]
    cursor = 0
    for caption in captions:
        assert text.count(caption) == 1
        cursor = text.index(caption, cursor) + len(caption)
    for index, caption in enumerate(captions):
        assert text.index(f"IMAGE-{index}") < text.index(caption)
    assert "active-partial-pdf" not in text
    assert "canonical-pdf job page" not in text
    assert len(cover_paths) == 1
    assert cover_paths[0].read_bytes() == PNG_BYTES
    assert len(captured_paths) == 9
    assert all(path.read_bytes() == PNG_BYTES for path in captured_paths)


def test_day_pdf_export_rejects_empty_foreign_and_invalid_days(private_app):
    with two_accounts(private_app) as (alice, bob, alice_profile, bob_profile):
        assert alice.post(
            "/api/fragments",
            json={"date": "2026-08-08", "content": "alice-only day"},
        ).status_code == 200

        owner_export = alice.post("/api/export/day/2026-08-08/pdf")
        empty_export = alice.post("/api/export/day/2026-08-09/pdf")
        foreign_export = bob.post("/api/export/day/2026-08-08/pdf")
        invalid_export = alice.post("/api/export/day/not-a-date/pdf")

    assert owner_export.status_code == 200
    assert empty_export.status_code in {400, 404}
    assert foreign_export.status_code in {400, 404}
    assert invalid_export.status_code == 400


def test_day_pdf_export_excludes_draft_diary_text(private_app, monkeypatch):
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

    with TestClient(private_app, base_url="http://testserver") as owner:
        assert owner.post(
            "/api/auth/register",
            json={
                "username": "draft-day-pdf",
                "password": PASSWORD,
                "nickname": "Draft Day PDF",
            },
        ).status_code == 201
        assert owner.post(
            "/api/fragments",
            json={"date": "2026-08-14", "content": "可以导出的真实片段。"},
        ).status_code == 200
        diary = owner.post("/api/diary", json={"date": "2026-08-14"}).json()
        assert owner.put(
            f"/api/diary/{diary['id']}",
            json={"text": "绝不能进入 PDF 的草稿。", "draft_text": "绝不能进入 PDF 的草稿。"},
        ).status_code == 200

        exported = owner.post("/api/export/day/2026-08-14/pdf")

    assert exported.status_code == 200
    assert "可以导出的真实片段。" in exported.content.decode("utf-8")
    assert "绝不能进入 PDF 的草稿。" not in exported.content.decode("utf-8")


def test_day_pdf_export_embeds_owned_cover_image(private_app):
    with TestClient(private_app, base_url="http://testserver") as owner:
        assert owner.post(
            "/api/auth/register",
            json={
                "username": "embedded-day-cover",
                "password": PASSWORD,
                "nickname": "Embedded Day Cover",
            },
        ).status_code == 201
        uploaded = owner.post(
            "/api/upload",
            files={"file": ("cover.png", PNG_BYTES, "image/png")},
        ).json()
        assert owner.post(
            "/api/fragments",
            json={
                "date": "2026-08-15",
                "content": "这张照片成为封面。",
                "photo_url": uploaded["url"],
                "photo_asset_id": uploaded["asset_id"],
            },
        ).status_code == 200

        exported = owner.post("/api/export/day/2026-08-15/pdf")

    assert exported.status_code == 200
    assert exported.content.startswith(b"%PDF")
    assert b"/Subtype /Image" in exported.content


def test_day_pdf_export_escapes_markup_and_ignores_remote_image_urls(
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
                "username": "day-pdf-markup",
                "password": PASSWORD,
                "nickname": "Day PDF Markup",
            },
        ).status_code == 201
        malicious_text = '<img src="http://169.254.169.254/latest/meta-data"/>'
        response = owner.post(
            "/api/fragments",
            json={
                "date": "2026-08-10",
                "content": malicious_text,
                "photo_description": malicious_text,
            },
        )
        assert response.status_code == 200
        with sqlite3.connect(config.get_db_path()) as db:
            db.execute(
                """
                UPDATE fragments
                SET photo_url = 'https://attacker.example/remote.png'
                WHERE id = ?
                """,
                (response.json()["id"],),
            )
            db.commit()

        exported = owner.post("/api/export/day/2026-08-10/pdf")

    assert exported.status_code == 200
    assert malicious_text.encode() in exported.content
    assert captured_paths == []


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
        ("delete", "/api/diary/1", None),
        ("post", "/api/diary/1/ai-fill", {"emotion_mode": "imagery"}),
        (
            "post",
            "/api/diary/1/ai-rewrite",
            {"paragraph": "x", "direction": "warmer"},
        ),
        ("get", "/api/profile", None),
        ("put", "/api/profile", {"nickname": "x"}),
        ("get", "/api/stats", None),
        ("post", "/api/export/pdf", None),
        ("post", "/api/export/day/2026-08-08/pdf", None),
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
        ("delete", "/api/diary/1", None),
        ("post", "/api/diary/1/ai-fill", {"emotion_mode": "imagery"}),
        (
            "post",
            "/api/diary/1/ai-rewrite",
            {"paragraph": "x", "direction": "warmer"},
        ),
        ("put", "/api/profile", {"nickname": "x"}),
        ("post", "/api/export/pdf", None),
        ("post", "/api/export/day/2026-08-08/pdf", None),
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
