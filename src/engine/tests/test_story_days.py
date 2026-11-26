import importlib
import sqlite3
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient


PASSWORD = "correct horse battery"


@pytest.fixture
def story_app(tmp_path, monkeypatch):
    db_path = tmp_path / "story-days.sqlite3"
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
def registered_clients(app):
    with TestClient(app, base_url="http://testserver") as alice, TestClient(
        app, base_url="http://testserver"
    ) as bob:
        alice_profile = alice.post(
            "/api/auth/register",
            json={
                "username": "story-alice",
                "password": PASSWORD,
                "nickname": "Alice",
            },
        )
        bob_profile = bob.post(
            "/api/auth/register",
            json={
                "username": "story-bob",
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


def insert_story_work(
    db_path,
    *,
    owner_user_id,
    diary_id,
    title,
    status="ready",
    updated_at="2026-08-08T00:00:00Z",
    cover_url=None,
    extra_cover_url=None,
):
    with sqlite3.connect(db_path) as db:
        cursor = db.execute(
            """
            INSERT INTO story_works (
                owner_user_id, source_diary_id, title, medium, narrative_mode,
                style, selected_segments_json, status, created_at, updated_at
            ) VALUES (?, ?, ?, 'picture_book', 'daily', 'pixel', ?, ?, ?, ?)
            """,
            (
                owner_user_id,
                diary_id,
                title,
                '["selected storyline"]',
                status,
                updated_at,
                updated_at,
            ),
        )
        work_id = cursor.lastrowid
        db.execute(
            """
            INSERT INTO work_assets (work_id, ordinal, asset_type, url, text)
            VALUES (?, 0, 'text', NULL, ?)
            """,
            (work_id, title),
        )
        if cover_url:
            db.execute(
                """
                INSERT INTO work_assets (work_id, ordinal, asset_type, url)
                VALUES (?, 1, 'image', ?)
                """,
                (work_id, cover_url),
            )
        if extra_cover_url:
            db.execute(
                """
                INSERT INTO work_assets (work_id, ordinal, asset_type, url)
                VALUES (?, 2, 'image', ?)
                """,
                (work_id, extra_cover_url),
            )
        db.commit()
    return work_id


def insert_ready_picturebook(db_path, *, user_id, diary_id):
    with sqlite3.connect(db_path) as db:
        cursor = db.execute(
            """
            INSERT INTO picturebook_jobs (
                user_id, diary_id, style, status, stage, total_pages,
                created_at, updated_at
            ) VALUES (?, ?, 'pixel', 'done', 'done', 9, ?, ?)
            """,
            (user_id, diary_id, "2026-08-08T01:00:00Z", "2026-08-08T01:00:00Z"),
        )
        job_id = cursor.lastrowid
        for index in range(9):
            db.execute(
                """
                INSERT INTO picturebook_pages (
                    job_id, page_index, image_id, caption, image_url, status,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'ready', ?, ?)
                """,
                (
                    job_id,
                    index,
                    f"image-{index}",
                    f"page {index}",
                    f"/api/media/book-{index}",
                    "2026-08-08T01:00:00Z",
                    "2026-08-08T01:00:00Z",
                ),
            )
        db.commit()
    return job_id


def insert_canonical_picturebook(
    db_path,
    *,
    owner_user_id,
    diary_id,
    title,
    day,
    status="ready",
    stage="ready",
    job_status="done",
    job_stage="done",
    active=False,
    page_indexes=range(9),
    updated_at="2026-08-11T03:00:00Z",
    style="watercolor",
    page_prefix="canonical",
):
    with sqlite3.connect(db_path) as db:
        cursor = db.execute(
            """
            INSERT INTO story_works (
                owner_user_id, source_diary_id, title, medium, narrative_mode,
                style, selected_segments_json, status, kind, stage,
                source_start_date, source_end_date, display_start_date,
                display_end_date, selected_storyline_json, narrative_text,
                created_at, updated_at
            ) VALUES (?, ?, ?, 'picture_book', 'daily', ?, ?, ?, 'daily_picturebook',
                ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                owner_user_id,
                diary_id,
                title,
                style,
                '["selected storyline"]',
                status,
                stage,
                day,
                day,
                day,
                day,
                '["selected storyline"]',
                "formal narrative",
                updated_at,
                updated_at,
            ),
        )
        work_id = cursor.lastrowid
        cursor = db.execute(
            """
            INSERT INTO picturebook_jobs (
                user_id, diary_id, work_id, source_text, source_signature,
                style, status, stage, total_pages, created_at, updated_at
            ) VALUES (?, NULL, ?, 'source text', 'source-signature', ?, ?, ?, 9, ?, ?)
            """,
            (
                owner_user_id,
                work_id,
                style,
                job_status,
                job_stage,
                updated_at,
                updated_at,
            ),
        )
        job_id = cursor.lastrowid
        for index in page_indexes:
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
                    f"{page_prefix}-job-image-{index}",
                    f"{page_prefix} job page {index}",
                    f"/api/media/{page_prefix}-job-{index}",
                    f"{page_prefix}-asset-{index}",
                    updated_at,
                    updated_at,
                ),
            )
            if status in {"ready", "published"}:
                db.execute(
                    """
                    INSERT INTO work_assets (
                        work_id, ordinal, asset_type, url, asset_id, text, created_at
                    ) VALUES (?, ?, 'image', ?, ?, ?, ?)
                    """,
                    (
                        work_id,
                        index,
                        f"/api/media/{page_prefix}-asset-{index}",
                        f"{page_prefix}-asset-{index}",
                        f"{page_prefix} formal page {index}",
                        updated_at,
                    ),
                )
        if active:
            db.execute(
                """
                UPDATE story_works
                SET active_picturebook_job_id = ?
                WHERE id = ?
                """,
                (job_id, work_id),
            )
        else:
            db.execute(
                """
                UPDATE story_works
                SET picturebook_job_id = ?, cover_asset_id = ?
                WHERE id = ?
                """,
                (job_id, f"{page_prefix}-asset-0", work_id),
            )
        db.commit()
    return work_id, job_id


def insert_completed_time_story(
    db_path,
    *,
    owner_user_id,
    diary_ids,
    title,
    source_start_date,
    source_end_date,
    status="ready",
    stage="ready",
    page0_url=None,
    page_prefix="time-story",
    updated_at="2026-08-20T03:00:00Z",
):
    with sqlite3.connect(db_path) as db:
        cursor = db.execute(
            """
            INSERT INTO story_works (
                owner_user_id, source_diary_id, title, medium, narrative_mode,
                style, selected_segments_json, status, kind, stage,
                source_start_date, source_end_date, display_start_date,
                display_end_date, narrative_text, created_at, updated_at
            ) VALUES (?, NULL, ?, 'picture_book', 'range', 'pixel', '[]', ?, 'time_story',
                ?, ?, ?, ?, ?, 'confirmed narrative', ?, ?)
            """,
            (
                owner_user_id,
                title,
                status,
                stage,
                source_start_date,
                source_end_date,
                source_start_date,
                source_end_date,
                updated_at,
                updated_at,
            ),
        )
        work_id = cursor.lastrowid
        for ordinal, diary_id in enumerate(diary_ids):
            db.execute(
                """
                INSERT INTO story_work_diaries (work_id, diary_id, ordinal)
                VALUES (?, ?, ?)
                """,
                (work_id, diary_id, ordinal),
            )
        cursor = db.execute(
            """
            INSERT INTO picturebook_jobs (
                user_id, diary_id, work_id, source_text, source_signature,
                style, status, stage, total_pages, created_at, updated_at
            ) VALUES (?, NULL, ?, 'confirmed narrative', 'time-story-signature',
                'pixel', 'done', 'done', 9, ?, ?)
            """,
            (owner_user_id, work_id, updated_at, updated_at),
        )
        job_id = cursor.lastrowid
        db.execute(
            """
            UPDATE story_works
            SET picturebook_job_id = ?, cover_asset_id = ?
            WHERE id = ?
            """,
            (job_id, f"{page_prefix}-asset-0", work_id),
        )
        if page0_url is not None:
            db.execute(
                """
                INSERT INTO work_assets (
                    work_id, ordinal, asset_type, url, asset_id, text
                ) VALUES (?, 0, 'image', ?, ?, 'cover page')
                """,
                (work_id, page0_url, f"{page_prefix}-asset-0"),
            )
        db.commit()
    return work_id


def insert_duplicate_canonical_reference(
    db_path,
    *,
    owner_user_id,
    diary_id,
    job_id,
    day,
):
    with sqlite3.connect(db_path) as db:
        cursor = db.execute(
            """
            INSERT INTO story_works (
                owner_user_id, source_diary_id, title, medium, narrative_mode,
                style, selected_segments_json, status, kind, stage,
                picturebook_job_id, source_start_date, source_end_date,
                display_start_date, display_end_date, created_at, updated_at
            ) VALUES (?, ?, 'duplicate canonical reference', 'picture_book', 'daily',
                'watercolor', '[]', 'ready', 'daily_picturebook', 'ready',
                ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                owner_user_id,
                diary_id,
                job_id,
                day,
                day,
                day,
                day,
                "2026-08-11T04:00:00Z",
                "2026-08-11T04:00:00Z",
            ),
        )
        duplicate_work_id = cursor.lastrowid
        for index in range(9):
            db.execute(
                """
                INSERT INTO work_assets (
                    work_id, ordinal, asset_type, url, asset_id, text
                ) VALUES (?, ?, 'image', ?, ?, ?)
                """,
                (
                    duplicate_work_id,
                    index,
                    f"/api/media/duplicate-asset-{index}",
                    f"duplicate-asset-{index}",
                    f"duplicate page {index}",
                ),
            )
        db.commit()
    return duplicate_work_id


def seed_chapter_records(db_path, alice_id, bob_id):
    execute(
        db_path,
        "INSERT INTO schedules (date, time, title, completed, user_id) VALUES (?, ?, ?, 0, ?)",
        ("2026-08-01", "09:00", "schedule only", alice_id),
    )
    execute(
        db_path,
        "INSERT INTO diaries (date, text, draft_text, status, user_id) VALUES (?, '', ?, 'draft', ?)",
        ("2026-08-02", "draft only", alice_id),
    )
    execute(
        db_path,
        """
        INSERT INTO fragments (
            date, content, photo_url, photo_asset_id, created_at, user_id
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            "2026-08-03",
            "",
            "/api/media/alice-fragment",
            "alice-fragment",
            "2026-08-03 02:00:00",
            alice_id,
        ),
    )
    execute(
        db_path,
        """
        INSERT INTO diaries (
            date, text, draft_text, status, confirmed_at, user_id
        ) VALUES (?, ?, '', 'confirmed', ?, ?)
        """,
        (
            "2026-08-04",
            "确认日记第一句。第二句。",
            "2026-08-04T12:00:00Z",
            alice_id,
        ),
    )
    execute(
        db_path,
        """
        INSERT INTO diaries (
            id, date, text, draft_text, status, confirmed_at, user_id
        ) VALUES (?, ?, ?, '', 'confirmed', ?, ?)
        """,
        (
            805,
            "2026-08-05",
            "same day diary",
            "2026-08-05T12:00:00Z",
            alice_id,
        ),
    )
    insert_story_work(
        db_path,
        owner_user_id=alice_id,
        diary_id=805,
        title="早一点完成的故事",
        updated_at="2026-08-05T01:00:00Z",
        cover_url="/api/media/older-cover",
    )
    insert_story_work(
        db_path,
        owner_user_id=alice_id,
        diary_id=805,
        title="晚一点完成的故事",
        updated_at="2026-08-05T03:00:00Z",
        cover_url="/api/media/newer-cover",
        extra_cover_url="/api/media/newer-second-image",
    )
    execute(
        db_path,
        """
        INSERT INTO diaries (
            id, date, text, draft_text, status, confirmed_at, user_id
        ) VALUES (?, ?, ?, '', 'confirmed', ?, ?)
        """,
        (
            806,
            "2026-08-06",
            "legacy book diary",
            "2026-08-06T12:00:00Z",
            alice_id,
        ),
    )
    insert_ready_picturebook(db_path, user_id=alice_id, diary_id=806)
    execute(
        db_path,
        "INSERT INTO diaries (date, text, draft_text, status, user_id) VALUES (?, '', '   ', 'draft', ?)",
        ("2026-08-07", alice_id),
    )
    execute(
        db_path,
        "INSERT INTO diaries (date, text, draft_text, status, user_id) VALUES (?, ?, '', 'draft', ?)",
        ("2026-08-07", "manual draft body", alice_id),
    )
    insert_story_work(
        db_path,
        owner_user_id=alice_id,
        diary_id=None,
        title="draft story",
        status="draft",
        updated_at="2026-08-07T02:00:00Z",
    )
    for status in ("ready", "published", "failed"):
        insert_story_work(
            db_path,
            owner_user_id=alice_id,
            diary_id=None,
            title=f"not counted {status}",
            status=status,
            updated_at="2026-08-07T03:00:00Z",
        )
    execute(
        db_path,
        """
        INSERT INTO fragments (
            date, content, photo_url, photo_asset_id, created_at, user_id
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            "2026-08-08",
            "bob only",
            "/api/media/bob-fragment",
            "bob-fragment",
            "2026-08-08T01:00:00Z",
            bob_id,
        ),
    )


def seed_timeline_records(db_path, alice_id, bob_id):
    execute(
        db_path,
        """
        INSERT INTO schedules (date, time, title, completed, feeling, user_id)
        VALUES (?, ?, ?, 1, ?, ?)
        """,
        ("2026-08-09", "11:00", "午前安排", "steady", alice_id),
    )
    execute(
        db_path,
        "INSERT INTO schedules (date, title, completed, user_id) VALUES (?, ?, 0, ?)",
        ("2026-08-09", "无时间安排", alice_id),
    )
    execute(
        db_path,
        "INSERT INTO schedules (date, time, title, completed, user_id) VALUES (?, ?, ?, 0, ?)",
        ("2026-08-09", "99:99", "非法时间安排", alice_id),
    )
    execute(
        db_path,
        """
        INSERT INTO fragments (date, content, created_at, user_id)
        VALUES (?, ?, ?, ?)
        """,
        ("2026-08-09", "UTC one means nine", "2026-08-09 01:00:00", alice_id),
    )
    execute(
        db_path,
        """
        INSERT INTO fragments (date, content, created_at, user_id)
        VALUES (?, ?, ?, ?)
        """,
        ("2026-08-09", "same clock tie", "2026-08-09T03:00:00Z", alice_id),
    )
    execute(
        db_path,
        """
        INSERT INTO fragments (date, content, created_at, user_id)
        VALUES (?, ?, ?, ?)
        """,
        ("2026-08-09", "foreign fragment", "2026-08-09T00:30:00Z", bob_id),
    )


def test_story_chapters_include_meaningful_owned_days_and_draft_count(story_app):
    app, db_path = story_app
    with registered_clients(app) as (alice, _bob, alice_profile, bob_profile):
        seed_chapter_records(db_path, alice_profile["id"], bob_profile["id"])

        response = alice.get("/api/story/chapters")

    assert response.status_code == 200
    payload = response.json()
    assert payload["draft_count"] == 3

    items = payload["items"]
    assert [item["date"] for item in items] == [
        "2026-08-06",
        "2026-08-05",
        "2026-08-04",
        "2026-08-03",
    ]
    assert "2026-08-01" not in {item["date"] for item in items}
    assert "2026-08-02" not in {item["date"] for item in items}
    assert "2026-08-08" not in {item["date"] for item in items}

    by_date = {item["date"]: item for item in items}
    assert by_date["2026-08-03"]["content_types"] == ["photo"]
    assert by_date["2026-08-04"]["content_types"] == ["diary"]
    assert by_date["2026-08-04"]["summary"] == "确认日记第一句。"
    assert by_date["2026-08-05"]["content_types"] == ["diary", "story"]
    assert by_date["2026-08-05"]["summary"] == "晚一点完成的故事"
    assert by_date["2026-08-05"]["cover_url"] == "/api/media/newer-cover"
    assert by_date["2026-08-06"]["content_types"] == ["diary", "picturebook"]


def test_story_chapters_show_completed_time_stories_as_independent_range_items(
    story_app,
):
    app, db_path = story_app
    with registered_clients(app) as (alice, _bob, alice_profile, bob_profile):
        for diary_id, day, text in [
            (821, "2026-08-01", "第一天正文"),
            (822, "2026-08-03", "第三天正文"),
            (823, "2026-08-05", "第五天正文"),
        ]:
            execute(
                db_path,
                """
                INSERT INTO diaries (
                    id, date, text, draft_text, status, confirmed_at, user_id
                ) VALUES (?, ?, ?, '', 'confirmed', ?, ?)
                """,
                (diary_id, day, text, f"{day}T12:00:00Z", alice_profile["id"]),
            )
        execute(
            db_path,
            """
            INSERT INTO fragments (
                date, content, photo_url, photo_asset_id, created_at, user_id
            ) VALUES (?, '', ?, ?, ?, ?)
            """,
            (
                "2026-08-01",
                "/api/media/photo-later",
                "photo-later",
                "2026-08-01T09:00:00Z",
                alice_profile["id"],
            ),
        )
        execute(
            db_path,
            """
            INSERT INTO fragments (
                date, content, photo_url, photo_asset_id, created_at, user_id
            ) VALUES (?, '', ?, ?, ?, ?)
            """,
            (
                "2026-08-01",
                "/api/media/photo-earliest",
                "photo-earliest",
                "2026-08-01T08:00:00Z",
                alice_profile["id"],
            ),
        )
        with sqlite3.connect(db_path) as db:
            db.execute(
                """
                INSERT INTO media_assets (
                    id, owner_user_id, storage_key, mime_type, size_bytes
                ) VALUES ('photo-earliest', ?, 'photo-earliest.png', 'image/png', 1)
                """,
                (alice_profile["id"],),
            )
            db.execute(
                """
                INSERT INTO media_assets (
                    id, owner_user_id, storage_key, mime_type, size_bytes
                ) VALUES ('photo-later', ?, 'photo-later.png', 'image/png', 1)
                """,
                (alice_profile["id"],),
            )
            db.commit()
        covered_id = insert_completed_time_story(
            db_path,
            owner_user_id=alice_profile["id"],
            diary_ids=[821, 822],
            title="有正式封面的范围故事",
            source_start_date="2026-08-01",
            source_end_date="2026-08-03",
            page0_url="/api/media/time-cover",
            page_prefix="covered-range",
        )
        photo_cover_id = insert_completed_time_story(
            db_path,
            owner_user_id=alice_profile["id"],
            diary_ids=[821, 823],
            title="用照片兜底的范围故事",
            source_start_date="2026-08-01",
            source_end_date="2026-08-05",
            page0_url=None,
            page_prefix="photo-range",
            updated_at="2026-08-20T04:00:00Z",
        )
        insert_completed_time_story(
            db_path,
            owner_user_id=alice_profile["id"],
            diary_ids=[821, 822],
            title="草稿不展示",
            source_start_date="2026-08-01",
            source_end_date="2026-08-03",
            status="draft",
            stage="narrative_confirmed",
            page0_url="/api/media/draft-cover",
        )
        insert_completed_time_story(
            db_path,
            owner_user_id=bob_profile["id"],
            diary_ids=[],
            title="跨用户不可见",
            source_start_date="2026-08-01",
            source_end_date="2026-08-03",
            page0_url="/api/media/bob-cover",
        )

        response = alice.get("/api/story/chapters")

    assert response.status_code == 200
    items = response.json()["items"]
    range_items = [item for item in items if item["kind"] == "range_work"]
    assert [item["source_id"] for item in range_items] == [photo_cover_id, covered_id]
    assert range_items[0]["source_kind"] == "time_story"
    assert range_items[0]["date"] == "2026-08-05"
    assert range_items[0]["month"] == "2026-08"
    assert range_items[0]["cover_url"] == "/api/media/photo-earliest"
    assert range_items[1]["cover_url"] == "/api/media/time-cover"
    assert [item["kind"] for item in items if item["date"] == "2026-08-03"] == [
        "range_work",
        "day",
    ]
    assert "草稿不展示" not in {item["title"] for item in items}
    assert "跨用户不可见" not in {item["title"] for item in items}


def test_story_chapters_include_legacy_weekly_comics_as_read_only_range_items(
    story_app,
):
    app, db_path = story_app
    with registered_clients(app) as (alice, _bob, alice_profile, bob_profile):
        execute(
            db_path,
            """
            INSERT INTO weekly_comics (
                user_id, week_start, week_end, style, url, caption, created_at
            ) VALUES (?, '2026-07-29', '2026-08-02', 'pixel',
                '/api/media/weekly-alice', '旧周漫', '2026-08-02T10:00:00Z')
            """,
            (alice_profile["id"],),
        )
        execute(
            db_path,
            """
            INSERT INTO weekly_comics (
                user_id, week_start, week_end, style, url, caption, created_at
            ) VALUES (?, '2026-07-29', '2026-08-02', 'pixel',
                '/api/media/weekly-bob', 'Bob 周漫', '2026-08-02T10:00:00Z')
            """,
            (bob_profile["id"],),
        )

        response = alice.get("/api/story/chapters")

    assert response.status_code == 200
    range_items = [
        item
        for item in response.json()["items"]
        if item["kind"] == "range_work" and item["source_kind"] == "legacy_weekly"
    ]
    assert range_items == [
        {
            "kind": "range_work",
            "source_kind": "legacy_weekly",
            "source_id": 1,
            "title": "旧周漫",
            "summary": "旧周漫",
            "date": "2026-08-02",
            "month": "2026-08",
            "start_date": "2026-07-29",
            "end_date": "2026-08-02",
            "source_start_date": "2026-07-29",
            "source_end_date": "2026-08-02",
            "cover_url": "/api/media/weekly-alice",
            "content_types": ["picturebook"],
        }
    ]


def test_canonical_picturebook_day_detail_deduplicates_formal_and_historical_books(
    story_app,
):
    app, db_path = story_app
    day = "2026-08-11"
    with registered_clients(app) as (alice, _bob, alice_profile, _bob_profile):
        execute(
            db_path,
            """
            INSERT INTO diaries (
                id, date, text, draft_text, status, confirmed_at, user_id
            ) VALUES (?, ?, ?, '', 'confirmed', ?, ?)
            """,
            (
                811,
                day,
                "historical source diary",
                "2026-08-11T12:00:00Z",
                alice_profile["id"],
            ),
        )
        ready_work_id, _ready_job_id = insert_canonical_picturebook(
            db_path,
            owner_user_id=alice_profile["id"],
            diary_id=811,
            title="canonical daily book",
            day=day,
            page_prefix="canonical-day",
        )
        partial_work_id, _partial_job_id = insert_canonical_picturebook(
            db_path,
            owner_user_id=alice_profile["id"],
            diary_id=811,
            title="partial active attempt",
            day=day,
            status="draft",
            stage="render_failed",
            job_status="failed",
            job_stage="failed",
            active=True,
            page_indexes=range(2),
            updated_at="2026-08-11T04:00:00Z",
            page_prefix="partial-day",
        )
        historical_job_id = insert_ready_picturebook(
            db_path,
            user_id=alice_profile["id"],
            diary_id=811,
        )

        chapters = alice.get("/api/story/chapters")
        detail = alice.get(f"/api/story/days/{day}")
        drafts = alice.get("/api/story/works/drafts")

    assert chapters.status_code == 200
    chapter_items = chapters.json()["items"]
    assert [item["date"] for item in chapter_items].count(day) == 1
    chapter = next(item for item in chapter_items if item["date"] == day)
    assert chapter["content_types"] == ["diary", "picturebook"]
    assert chapter["cover_url"] == "/api/media/canonical-day-asset-0"

    assert detail.status_code == 200
    payload = detail.json()
    assert [work["id"] for work in payload["story_works"]] == []
    assert [(book["source_kind"], book["source_id"]) for book in payload["picturebooks"]] == [
        ("canonical_work", ready_work_id),
        ("historical_job", historical_job_id),
    ]
    assert all(
        book["source_id"] != partial_work_id or book["source_kind"] != "canonical_work"
        for book in payload["picturebooks"]
    )
    assert [page["page_index"] for page in payload["picturebooks"][0]["pages"]] == list(
        range(9)
    )
    assert payload["picturebooks"][0]["pages"][0] == {
        "page_index": 0,
        "image_url": "/api/media/canonical-day-asset-0",
        "asset_id": "canonical-day-asset-0",
        "caption": "canonical-day formal page 0",
    }

    assert drafts.status_code == 200
    assert [item["id"] for item in drafts.json()["items"]] == [partial_work_id]


def test_completed_picturebooks_returns_normalized_owned_complete_books(story_app):
    app, db_path = story_app
    with registered_clients(app) as (alice, bob, alice_profile, bob_profile):
        execute(
            db_path,
            """
            INSERT INTO diaries (
                id, date, text, draft_text, status, confirmed_at, user_id
            ) VALUES (?, ?, ?, '', 'confirmed', ?, ?)
            """,
            (
                812,
                "2026-08-12",
                "historical title first sentence. more",
                "2026-08-12T12:00:00Z",
                alice_profile["id"],
            ),
        )
        execute(
            db_path,
            """
            INSERT INTO diaries (
                id, date, text, draft_text, status, confirmed_at, user_id
            ) VALUES (?, ?, ?, '', 'confirmed', ?, ?)
            """,
            (
                813,
                "2026-08-13",
                "canonical source",
                "2026-08-13T12:00:00Z",
                alice_profile["id"],
            ),
        )
        execute(
            db_path,
            """
            INSERT INTO diaries (
                id, date, text, draft_text, status, confirmed_at, user_id
            ) VALUES (?, ?, ?, '', 'confirmed', ?, ?)
            """,
            (
                814,
                "2026-08-14",
                "published source",
                "2026-08-14T12:00:00Z",
                alice_profile["id"],
            ),
        )
        execute(
            db_path,
            """
            INSERT INTO diaries (
                id, date, text, draft_text, status, confirmed_at, user_id
            ) VALUES (?, ?, ?, '', 'confirmed', ?, ?)
            """,
            (
                815,
                "2026-08-15",
                "partial source",
                "2026-08-15T12:00:00Z",
                alice_profile["id"],
            ),
        )
        execute(
            db_path,
            """
            INSERT INTO diaries (
                id, date, text, draft_text, status, confirmed_at, user_id
            ) VALUES (?, ?, ?, '', 'confirmed', ?, ?)
            """,
            (
                912,
                "2026-08-12",
                "foreign source",
                "2026-08-12T12:00:00Z",
                bob_profile["id"],
            ),
        )

        historical_job_id = insert_ready_picturebook(
            db_path,
            user_id=alice_profile["id"],
            diary_id=812,
        )
        canonical_work_id, canonical_job_id = insert_canonical_picturebook(
            db_path,
            owner_user_id=alice_profile["id"],
            diary_id=813,
            title="canonical complete",
            day="2026-08-13",
            updated_at="2026-08-13T03:00:00Z",
            page_prefix="canonical-complete",
        )
        published_work_id, _published_job_id = insert_canonical_picturebook(
            db_path,
            owner_user_id=alice_profile["id"],
            diary_id=814,
            title="published complete",
            day="2026-08-14",
            status="published",
            updated_at="2026-08-14T03:00:00Z",
            page_prefix="published-complete",
        )
        insert_duplicate_canonical_reference(
            db_path,
            owner_user_id=alice_profile["id"],
            diary_id=813,
            job_id=canonical_job_id,
            day="2026-08-13",
        )
        insert_canonical_picturebook(
            db_path,
            owner_user_id=alice_profile["id"],
            diary_id=815,
            title="partial formal",
            day="2026-08-15",
            page_indexes=range(2),
            updated_at="2026-08-15T03:00:00Z",
            page_prefix="partial-formal",
        )
        insert_canonical_picturebook(
            db_path,
            owner_user_id=alice_profile["id"],
            diary_id=815,
            title="failed formal",
            day="2026-08-15",
            status="failed",
            stage="render_failed",
            job_status="failed",
            job_stage="failed",
            page_indexes=range(9),
            updated_at="2026-08-15T04:00:00Z",
            page_prefix="failed-formal",
        )
        insert_canonical_picturebook(
            db_path,
            owner_user_id=bob_profile["id"],
            diary_id=912,
            title="foreign canonical",
            day="2026-08-12",
            page_prefix="foreign-canonical",
        )
        insert_ready_picturebook(db_path, user_id=bob_profile["id"], diary_id=912)

        response = alice.get("/api/story/picturebooks")
        with TestClient(app, base_url="http://testserver") as anonymous:
            unauthenticated = anonymous.get("/api/story/picturebooks")

    assert response.status_code == 200
    payload = response.json()
    assert [
        (item["source_kind"], item["source_id"], item["title"])
        for item in payload["items"]
    ] == [
        ("canonical_work", published_work_id, "published complete"),
        ("canonical_work", canonical_work_id, "canonical complete"),
        ("historical_job", historical_job_id, "historical title first sentence."),
    ]
    canonical = payload["items"][1]
    assert canonical["source_start_date"] == "2026-08-13"
    assert canonical["source_end_date"] == "2026-08-13"
    assert canonical["style"] == "watercolor"
    assert canonical["cover_url"] == "/api/media/canonical-complete-asset-0"
    assert canonical["pages"] == [
        {
            "page_index": index,
            "image_url": f"/api/media/canonical-complete-asset-{index}",
            "asset_id": f"canonical-complete-asset-{index}",
            "caption": f"canonical-complete formal page {index}",
        }
        for index in range(9)
    ]
    assert all("error" not in item and "prompt" not in item for item in payload["items"])
    assert unauthenticated.status_code == 401


def test_story_day_detail_excludes_completed_time_story_picturebooks(story_app):
    app, db_path = story_app
    with registered_clients(app) as (alice, _bob, alice_profile, _bob_profile):
        for diary_id, day in [(821, "2026-08-01"), (822, "2026-08-03")]:
            execute(
                db_path,
                """
                INSERT INTO diaries (
                    id, date, text, draft_text, status, confirmed_at, user_id
                ) VALUES (?, ?, ?, '', 'confirmed', ?, ?)
                """,
                (
                    diary_id,
                    day,
                    f"{day} 的正文",
                    f"{day}T12:00:00Z",
                    alice_profile["id"],
                ),
            )
        time_story_id = insert_completed_time_story(
            db_path,
            owner_user_id=alice_profile["id"],
            diary_ids=[821, 822],
            title="这一段时间",
            source_start_date="2026-08-01",
            source_end_date="2026-08-03",
            page0_url="/api/media/time-story-cover",
        )
        for index in range(1, 9):
            execute(
                db_path,
                """
                INSERT INTO work_assets (
                    work_id, ordinal, asset_type, url, asset_id, text
                ) VALUES (?, ?, 'image', ?, ?, ?)
                """,
                (
                    time_story_id,
                    index,
                    f"/api/media/time-story-{index}",
                    f"time-story-asset-{index}",
                    f"time story page {index}",
                ),
            )

        detail = alice.get("/api/story/days/2026-08-01")
        picturebooks = alice.get("/api/story/picturebooks")

    assert detail.status_code == 200
    assert detail.json()["picturebooks"] == []
    assert picturebooks.status_code == 200
    assert [
        (item["source_kind"], item["source_id"])
        for item in picturebooks.json()["items"]
    ] == [("canonical_work", time_story_id)]


def test_story_day_detail_merges_owned_timeline_by_shanghai_clock(story_app):
    app, db_path = story_app
    with registered_clients(app) as (alice, _bob, alice_profile, bob_profile):
        seed_timeline_records(db_path, alice_profile["id"], bob_profile["id"])

        response = alice.get("/api/story/days/2026-08-09")
        malformed = alice.get("/api/story/days/not-a-date")

    assert response.status_code == 200
    payload = response.json()
    assert payload["date"] == "2026-08-09"
    assert payload["draft_count"] == 0
    assert payload["content_types"] == ["text"]

    timeline = payload["timeline"]
    assert [(item["kind"], item["clock"], item["title"] or item["content"]) for item in timeline] == [
        ("fragment", "09:00", "UTC one means nine"),
        ("schedule", "11:00", "午前安排"),
        ("fragment", "11:00", "same clock tie"),
        ("schedule", "", "无时间安排"),
        ("schedule", "", "非法时间安排"),
    ]
    assert all(item.get("content") != "foreign fragment" for item in timeline)
    assert payload["schedules"][0]["feeling"] == "steady"
    assert malformed.status_code in {400, 422}


def test_confirmed_diary_summary_uses_earliest_sentence_terminator(story_app):
    app, db_path = story_app
    with registered_clients(app) as (alice, _bob, alice_profile, _bob_profile):
        execute(
            db_path,
            """
            INSERT INTO diaries (
                date, text, draft_text, status, confirmed_at, user_id
            ) VALUES (?, ?, '', 'confirmed', ?, ?)
            """,
            (
                "2026-08-10",
                "先惊叹！后面才有句号。再后来。",
                "2026-08-10T12:00:00Z",
                alice_profile["id"],
            ),
        )

        response = alice.get("/api/story/chapters")

    assert response.status_code == 200
    by_date = {item["date"]: item for item in response.json()["items"]}
    assert by_date["2026-08-10"]["summary"] == "先惊叹！"
