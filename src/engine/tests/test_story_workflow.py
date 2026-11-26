import asyncio
import importlib
import hashlib
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient


PASSWORD = "correct horse battery"
FOREIGN_ORIGIN = "https://attacker.example"
PNG_DATA_URL = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
)


@pytest.fixture
def workflow_app(tmp_path, monkeypatch):
    db_path = tmp_path / "story-workflow.sqlite3"
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
def registered_clients(app, db_path=None):
    with TestClient(app, base_url="http://testserver") as alice, TestClient(
        app, base_url="http://testserver"
    ) as bob:
        alice_profile = alice.post(
            "/api/auth/register",
            json={
                "username": "workflow-alice",
                "password": PASSWORD,
                "nickname": "Alice",
            },
        )
        bob_profile = bob.post(
            "/api/auth/register",
            json={
                "username": "workflow-bob",
                "password": PASSWORD,
                "nickname": "Bob",
            },
        )
        assert alice_profile.status_code == bob_profile.status_code == 201
        # 生成链路测试默认放开体验配额;配额语义由 test_generation_quota.py 单测。
        if db_path is not None:
            from conftest import grant_unlimited_quota

            grant_unlimited_quota(db_path)
        yield alice, bob, alice_profile.json(), bob_profile.json()


async def create_account(db, user_id: int) -> None:
    await db.execute(
        "INSERT INTO profile (id, nickname) VALUES (?, ?)",
        (user_id, f"user-{user_id}"),
    )
    await db.execute(
        "INSERT INTO accounts (user_id, username_norm, password_hash) "
        "VALUES (?, ?, ?)",
        (user_id, f"user-{user_id}", "not-a-real-password-hash"),
    )
    # 生成链路测试默认放开体验配额;配额语义由 test_generation_quota.py 单测。
    for category in ("picturebook", "motion_comic"):
        await db.execute(
            "INSERT INTO generation_quotas (user_id, category, remaining, updated_at) "
            "VALUES (?, ?, 1000000, 'test') "
            "ON CONFLICT (user_id, category) DO UPDATE SET remaining = excluded.remaining",
            (user_id, category),
        )
    await db.commit()


async def insert_diary(
    db,
    *,
    user_id: int,
    body: str,
    date: str = "2026-08-08",
    status: str = "confirmed",
) -> int:
    cursor = await db.execute(
        """
        INSERT INTO diaries (date, text, status, user_id)
        VALUES (?, ?, ?, ?)
        """,
        (date, body, status, user_id),
    )
    await db.commit()
    return cursor.lastrowid


def insert_diary_sync(
    db_path,
    *,
    user_id: int,
    body: str,
    date: str = "2026-08-08",
    status: str = "confirmed",
) -> int:
    with sqlite3.connect(db_path) as db:
        cursor = db.execute(
            """
            INSERT INTO diaries (date, text, status, user_id)
            VALUES (?, ?, ?, ?)
            """,
            (date, body, status, user_id),
        )
        db.commit()
        return cursor.lastrowid


def fetch_one_sync(db_path, sql: str, params=()):
    with sqlite3.connect(db_path) as db:
        db.row_factory = sqlite3.Row
        row = db.execute(sql, params).fetchone()
    return dict(row) if row else None


def insert_character_profile_sync(db_path, *, user_id: int, preset: str = "p01"):
    with sqlite3.connect(db_path) as db:
        db.execute(
            """
            INSERT INTO character_profiles (
                user_id, reference_image_url, character_description, nickname,
                visual_profile, source_type
            ) VALUES (?, ?, 'brave and warm', 'Nana', 'fixed visual profile',
                'preset')
            ON CONFLICT(user_id) DO UPDATE SET
                reference_image_url=excluded.reference_image_url,
                visual_profile=excluded.visual_profile
            """,
            (user_id, f"/characters/main/{preset}.webp"),
        )
        db.commit()


def preset_character_signature(preset: str = "p01") -> str:
    path = (
        Path(__file__).resolve().parents[2]
        / "app"
        / "frontend"
        / "public"
        / "characters"
        / "main"
        / f"{preset}.webp"
    )
    return hashlib.sha256(path.read_bytes()).hexdigest()[:32]


async def fetch_one(db, sql: str, params=()):
    cursor = await db.execute(sql, params)
    row = await cursor.fetchone()
    return dict(row) if row else None


async def fetch_all(db, sql: str, params=()):
    cursor = await db.execute(sql, params)
    return [dict(row) for row in await cursor.fetchall()]


async def insert_picturebook_render_pages(
    db,
    *,
    user_id: int,
    page_count: int = 9,
) -> int:
    await create_account(db, user_id)
    diary_id = await insert_diary(
        db,
        user_id=user_id,
        body="Render source paragraph.",
    )
    timestamp = "2026-08-08T00:00:00Z"
    cursor = await db.execute(
        """
        INSERT INTO picturebook_jobs (
            user_id, diary_id, style, status, stage, total_pages,
            created_at, updated_at
        ) VALUES (?, ?, 'pixel', 'running', 'rendering', ?, ?, ?)
        """,
        (user_id, diary_id, page_count, timestamp, timestamp),
    )
    job_id = cursor.lastrowid
    for index in reversed(range(page_count)):
        await db.execute(
            """
            INSERT INTO picturebook_pages (
                job_id, page_index, image_id, caption, image_prompt, status,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)
            """,
            (
                job_id,
                index,
                f"page-{index}",
                f"caption-{index}",
                f"prompt-{index}",
                timestamp,
                timestamp,
            ),
        )
    await db.commit()
    return job_id


@pytest.mark.asyncio
async def test_picturebook_pages_render_concurrently_with_distinct_stable_keys(
    db, monkeypatch
):
    import routers.picturebook as picturebook_router

    job_id = await insert_picturebook_render_pages(db, user_id=41)
    entered = []
    all_entered = asyncio.Event()
    release = asyncio.Event()

    async def fake_generate_page_image(prompt, character, api_key=None):
        entered.append((int(prompt.removeprefix("prompt-")), api_key))
        if len(entered) == 9:
            all_entered.set()
        await release.wait()
        return PNG_DATA_URL

    monkeypatch.setattr(
        picturebook_router,
        "image_api_key_for_page",
        lambda page_index: f"pool-{page_index}",
        raising=False,
    )
    monkeypatch.setattr(
        picturebook_router,
        "generate_page_image",
        fake_generate_page_image,
    )

    render = asyncio.create_task(
        picturebook_router._render_pending_pages(db, job_id, 41, None)
    )
    try:
        await asyncio.wait_for(all_entered.wait(), timeout=1)
    except BaseException:
        render.cancel()
        await asyncio.gather(render, return_exceptions=True)
        raise
    finally:
        release.set()

    assert await render == 0
    assert sorted(entered) == [(index, f"pool-{index}") for index in range(9)]
    assert await fetch_all(
        db,
        "SELECT page_index, status FROM picturebook_pages "
        "WHERE job_id=? ORDER BY page_index",
        (job_id,),
    ) == [
        {"page_index": index, "status": "ready"}
        for index in range(9)
    ]


@pytest.mark.asyncio
async def test_picturebook_partial_failure_keeps_successes_and_retry_key_mapping(
    db, monkeypatch
):
    import routers.picturebook as picturebook_router

    job_id = await insert_picturebook_render_pages(db, user_id=42)
    first_keys = []

    async def fake_generate_page_image(prompt, character, api_key=None):
        index = int(prompt.removeprefix("prompt-"))
        first_keys.append((index, api_key))
        if index == 4:
            raise picturebook_router.GenerationServiceError(
                "image service is temporarily unavailable"
            )
        return PNG_DATA_URL

    monkeypatch.setattr(
        picturebook_router,
        "image_api_key_for_page",
        lambda page_index: f"pool-{page_index}",
        raising=False,
    )
    monkeypatch.setattr(
        picturebook_router,
        "generate_page_image",
        fake_generate_page_image,
    )

    assert await picturebook_router._render_pending_pages(db, job_id, 42, None) == 1
    rows = await fetch_all(
        db,
        "SELECT page_index, status, asset_id FROM picturebook_pages "
        "WHERE job_id=? ORDER BY page_index",
        (job_id,),
    )
    assert [row["status"] for row in rows] == [
        "ready",
        "ready",
        "ready",
        "ready",
        "failed",
        "ready",
        "ready",
        "ready",
        "ready",
    ]
    assert rows[4]["asset_id"] is None
    assert all(row["asset_id"] for row in rows[:4] + rows[5:])
    assert await fetch_one(
        db,
        "SELECT COUNT(*) AS count FROM media_assets WHERE owner_user_id=?",
        (42,),
    ) == {"count": 8}

    retry_keys = []

    async def fake_retry(prompt, character, api_key=None):
        retry_keys.append((int(prompt.removeprefix("prompt-")), api_key))
        return PNG_DATA_URL

    monkeypatch.setattr(picturebook_router, "generate_page_image", fake_retry)

    assert await picturebook_router._render_pending_pages(db, job_id, 42, None) == 0
    assert retry_keys == [(4, "pool-4")]
    assert await fetch_one(
        db,
        "SELECT status FROM picturebook_pages WHERE job_id=? AND page_index=4",
        (job_id,),
    ) == {"status": "ready"}


@pytest.mark.asyncio
async def test_picturebook_page_cancellation_is_safely_reraised_after_successes(
    db, monkeypatch
):
    import routers.picturebook as picturebook_router

    job_id = await insert_picturebook_render_pages(db, user_id=43)
    sensitive_marker = "cancel-sensitive-placeholder"

    async def fake_generate_page_image(prompt, character, api_key=None):
        if prompt == "prompt-4":
            raise asyncio.CancelledError(sensitive_marker)
        return PNG_DATA_URL

    monkeypatch.setattr(
        picturebook_router,
        "image_api_key_for_page",
        lambda page_index: f"pool-{page_index}",
    )
    monkeypatch.setattr(
        picturebook_router,
        "generate_page_image",
        fake_generate_page_image,
    )

    with pytest.raises(asyncio.CancelledError) as caught:
        await picturebook_router._render_pending_pages(db, job_id, 43, None)

    assert sensitive_marker not in str(caught.value)
    rows = await fetch_all(
        db,
        "SELECT page_index, status FROM picturebook_pages "
        "WHERE job_id=? ORDER BY page_index",
        (job_id,),
    )
    assert [row["status"] for row in rows].count("ready") == 8
    assert rows[4] == {"page_index": 4, "status": "rendering"}


@pytest.mark.asyncio
async def test_picturebook_unexpected_page_error_is_safely_reraised_after_successes(
    db, monkeypatch
):
    import routers.picturebook as picturebook_router

    job_id = await insert_picturebook_render_pages(db, user_id=44)
    sensitive_marker = "unexpected-sensitive-placeholder"

    async def fake_generate_page_image(prompt, character, api_key=None):
        if prompt == "prompt-4":
            raise RuntimeError(sensitive_marker)
        return PNG_DATA_URL

    monkeypatch.setattr(
        picturebook_router,
        "image_api_key_for_page",
        lambda page_index: f"pool-{page_index}",
    )
    monkeypatch.setattr(
        picturebook_router,
        "generate_page_image",
        fake_generate_page_image,
    )

    with pytest.raises(RuntimeError) as caught:
        await picturebook_router._render_pending_pages(db, job_id, 44, None)

    assert str(caught.value) == "picturebook page rendering failed"
    assert sensitive_marker not in repr(caught.value.__cause__)
    rows = await fetch_all(
        db,
        "SELECT page_index, status FROM picturebook_pages "
        "WHERE job_id=? ORDER BY page_index",
        (job_id,),
    )
    assert [row["status"] for row in rows].count("ready") == 8
    assert rows[4] == {"page_index": 4, "status": "rendering"}


def test_stale_generation_error_describes_any_generation_basis_change():
    from services.story_workflow import sanitize_generation_error

    assert sanitize_generation_error("internal detail", stale=True) == (
        "生成依据已更新，请重新生成绘本"
    )


@pytest.mark.asyncio
async def test_daily_draft_create_snapshots_owned_diary_and_association(db):
    from services.story_workflow import create_daily_picturebook_draft

    await create_account(db, 1)
    diary_id = await insert_diary(
        db,
        user_id=1,
        date="2026-08-07",
        status="confirmed",
        body="First full paragraph.\n\nSecond full paragraph.",
    )

    work = await create_daily_picturebook_draft(
        db,
        owner_user_id=1,
        diary_id=diary_id,
        selected_segments=["Second full paragraph."],
        title="Bedtime Book",
        style="watercolor",
    )

    row = await fetch_one(db, "SELECT * FROM story_works WHERE id=?", (work["id"],))
    snapshot = json.loads(row["source_snapshot_json"])
    assert row["owner_user_id"] == 1
    assert row["source_diary_id"] == diary_id
    assert row["kind"] == "daily_picturebook"
    assert row["status"] == "draft"
    assert row["stage"] == "narrative_confirmed"
    assert row["source_start_date"] == "2026-08-07"
    assert row["source_end_date"] == "2026-08-07"
    assert json.loads(row["selected_segments_json"]) == ["Second full paragraph."]
    assert snapshot == {
        "diaries": [
            {
                "id": diary_id,
                "date": "2026-08-07",
                "status": "confirmed",
                "body": "First full paragraph.\n\nSecond full paragraph.",
            }
        ]
    }
    assert row["source_snapshot_hash"]
    assert await fetch_all(
        db, "SELECT work_id, diary_id, ordinal FROM story_work_diaries"
    ) == [{"work_id": work["id"], "diary_id": diary_id, "ordinal": 0}]
    assert work["source_snapshot"] == snapshot
    assert work["selected_segments"] == ["Second full paragraph."]


@pytest.mark.asyncio
async def test_daily_draft_create_rejects_foreign_empty_and_non_paragraph_inputs(db):
    from services.story_workflow import (
        StoryWorkflowNotFound,
        StoryWorkflowValidationError,
        create_daily_picturebook_draft,
    )

    await create_account(db, 1)
    await create_account(db, 2)
    foreign_diary_id = await insert_diary(
        db, user_id=2, body="Private full paragraph."
    )
    empty_diary_id = await insert_diary(db, user_id=1, body=" \n\n ")
    owned_diary_id = await insert_diary(
        db,
        user_id=1,
        body="First full paragraph.\n\nSecond full paragraph.",
    )

    with pytest.raises(StoryWorkflowNotFound):
        await create_daily_picturebook_draft(
            db,
            owner_user_id=1,
            diary_id=foreign_diary_id,
            selected_segments=["Private full paragraph."],
            title="Nope",
            style="pixel",
        )

    invalid_cases = [
        (empty_diary_id, ["anything"]),
        (owned_diary_id, []),
        (owned_diary_id, [""]),
        (owned_diary_id, ["First full paragraph. Second full paragraph."]),
        (owned_diary_id, ["First"]),
    ]
    for diary_id, selected_segments in invalid_cases:
        with pytest.raises(StoryWorkflowValidationError):
            await create_daily_picturebook_draft(
                db,
                owner_user_id=1,
                diary_id=diary_id,
                selected_segments=selected_segments,
                title="Invalid",
                style="pixel",
            )


@pytest.mark.asyncio
async def test_time_story_draft_create_from_range_snapshots_owned_diaries_in_order(db):
    from services.story_workflow import create_time_story_draft

    await create_account(db, 1)
    await create_account(db, 2)
    first_id = await insert_diary(
        db,
        user_id=1,
        date="2026-08-01",
        status="confirmed",
        body="第一天的有效正文。",
    )
    await insert_diary(db, user_id=1, date="2026-08-02", body="   ")
    second_id = await insert_diary(
        db,
        user_id=1,
        date="2026-08-03",
        status="confirmed",
        body="第三天的有效正文。",
    )
    await insert_diary(
        db,
        user_id=2,
        date="2026-08-02",
        status="confirmed",
        body="Bob 的私人日记。",
    )

    work = await create_time_story_draft(
        db,
        owner_user_id=1,
        start_date="2026-08-01",
        end_date="2026-08-03",
        title="八月小故事",
        style="watercolor",
    )

    row = await fetch_one(db, "SELECT * FROM story_works WHERE id=?", (work["id"],))
    snapshot = json.loads(row["source_snapshot_json"])
    assert row["owner_user_id"] == 1
    assert row["source_diary_id"] is None
    assert row["kind"] == "time_story"
    assert row["status"] == "draft"
    assert row["stage"] == "sources_selected"
    assert row["source_start_date"] == "2026-08-01"
    assert row["source_end_date"] == "2026-08-03"
    assert row["display_start_date"] == "2026-08-01"
    assert row["display_end_date"] == "2026-08-03"
    assert row["selected_segments_json"] == "[]"
    assert snapshot == {
        "diaries": [
            {
                "id": first_id,
                "date": "2026-08-01",
                "status": "confirmed",
                "body": "第一天的有效正文。",
            },
            {
                "id": second_id,
                "date": "2026-08-03",
                "status": "confirmed",
                "body": "第三天的有效正文。",
            },
        ]
    }
    assert await fetch_all(
        db,
        "SELECT diary_id, ordinal FROM story_work_diaries WHERE work_id=?",
        (work["id"],),
    ) == [
        {"diary_id": first_id, "ordinal": 0},
        {"diary_id": second_id, "ordinal": 1},
    ]
    assert work["source_diary_ids"] == [first_id, second_id]


@pytest.mark.asyncio
async def test_time_story_draft_rejects_invalid_ranges_duplicate_and_foreign_ids(db):
    from services.story_workflow import (
        StoryWorkflowNotFound,
        StoryWorkflowValidationError,
        create_time_story_draft,
    )

    await create_account(db, 1)
    await create_account(db, 2)
    owned_id = await insert_diary(
        db, user_id=1, date="2026-08-05", body="owned body"
    )
    foreign_id = await insert_diary(
        db, user_id=2, date="2026-08-06", body="foreign body"
    )

    invalid_ranges = [
        {"start_date": "2026-08-06", "end_date": "2026-08-05"},
        {"start_date": "2026-08-01", "end_date": "2026-09-01"},
        {"start_date": "2026-08-01", "end_date": "2026-08-02"},
    ]
    for kwargs in invalid_ranges:
        with pytest.raises(StoryWorkflowValidationError):
            await create_time_story_draft(
                db,
                owner_user_id=1,
                title="invalid",
                style="pixel",
                **kwargs,
            )

    with pytest.raises(StoryWorkflowValidationError):
        await create_time_story_draft(
            db,
            owner_user_id=1,
            source_diary_ids=[owned_id, owned_id],
            title="duplicate",
            style="pixel",
        )
    with pytest.raises(StoryWorkflowNotFound):
        await create_time_story_draft(
            db,
            owner_user_id=1,
            source_diary_ids=[owned_id, foreign_id],
            title="foreign",
            style="pixel",
        )


@pytest.mark.asyncio
async def test_time_story_sources_replace_resets_draft_generation_without_deleting_assets(
    db,
):
    from services.story_workflow import (
        replace_time_story_sources,
        create_time_story_draft,
    )

    await create_account(db, 1)
    first_id = await insert_diary(db, user_id=1, date="2026-08-01", body="first")
    second_id = await insert_diary(db, user_id=1, date="2026-08-02", body="second")
    replacement_id = await insert_diary(
        db, user_id=1, date="2026-08-03", body="replacement"
    )
    work = await create_time_story_draft(
        db,
        owner_user_id=1,
        source_diary_ids=[first_id, second_id],
        title="mutable range",
        style="pixel",
    )
    await db.execute(
        """
        UPDATE story_works
        SET stage='narrative_editing',
            storyline_candidates_json='[{"id":"old"}]',
            selected_storyline_json='{"id":"old"}',
            narrative_text='old narrative',
            generation_error='raw provider failure',
            active_picturebook_job_id=123,
            picturebook_job_id=456,
            cover_asset_id='cover'
        WHERE id=?
        """,
        (work["id"],),
    )
    await db.execute(
        """
        INSERT INTO media_assets (id, owner_user_id, storage_key, mime_type, size_bytes)
        VALUES ('historical', 1, 'historical.png', 'image/png', 1)
        """
    )
    await db.execute(
        """
        INSERT INTO work_assets (work_id, ordinal, asset_type, url, asset_id, text)
        VALUES (?, 0, 'image', '/api/media/historical', 'historical', 'historical page')
        """,
        (work["id"],),
    )
    await db.commit()

    updated = await replace_time_story_sources(
        db,
        owner_user_id=1,
        work_id=work["id"],
        source_diary_ids=[replacement_id],
    )

    row = await fetch_one(db, "SELECT * FROM story_works WHERE id=?", (work["id"],))
    assert updated["stage"] == "sources_selected"
    assert updated["pages"] == []
    assert row["storyline_candidates_json"] is None
    assert row["selected_storyline_json"] is None
    assert row["narrative_text"] is None
    assert row["generation_error"] is None
    assert row["active_picturebook_job_id"] is None
    assert row["picturebook_job_id"] is None
    assert row["cover_asset_id"] is None
    assert await fetch_all(
        db,
        "SELECT diary_id, ordinal FROM story_work_diaries WHERE work_id=?",
        (work["id"],),
    ) == [{"diary_id": replacement_id, "ordinal": 0}]
    assert await fetch_one(
        db,
        "SELECT COUNT(*) AS count FROM work_assets WHERE work_id=?",
        (work["id"],),
    ) == {"count": 1}


@pytest.mark.asyncio
async def test_time_story_storylines_select_narrative_confirm_and_render_source(
    db,
    monkeypatch,
):
    from agents.time_story_agent import StorylineCandidate, StorylineResponse
    from services import story_workflow

    await create_account(db, 1)
    diary_id = await insert_diary(
        db, user_id=1, date="2026-08-01", body="可用于长故事的正文。"
    )

    async def fake_candidates(snapshots):
        assert [item["date"] for item in snapshots] == ["2026-08-01"]
        return StorylineResponse(
            items=[
                StorylineCandidate(
                    id="one",
                    title="第一条线",
                    summary="只来自日记的摘要",
                    source_dates=["2026-08-01"],
                ),
                StorylineCandidate(
                    id="two",
                    title="第二条线",
                    summary="另一个角度",
                    source_dates=["2026-08-01"],
                ),
                StorylineCandidate(
                    id="three",
                    title="第三条线",
                    summary="第三个角度",
                    source_dates=["2026-08-01"],
                ),
            ]
        )

    narrative_calls = []

    async def fake_narrative(snapshots, candidate):
        narrative_calls.append((snapshots, candidate.id))
        return "围绕第一条线写成的长文本。"

    monkeypatch.setattr(
        story_workflow.time_story_agent,
        "generate_storyline_candidates",
        fake_candidates,
    )
    monkeypatch.setattr(
        story_workflow.time_story_agent,
        "generate_time_story_narrative",
        fake_narrative,
    )

    work = await story_workflow.create_time_story_draft(
        db,
        owner_user_id=1,
        source_diary_ids=[diary_id],
        title="闭环故事",
        style="crayon",
    )
    first = await story_workflow.generate_time_story_storylines(
        db,
        owner_user_id=1,
        work_id=work["id"],
    )
    repeated = await story_workflow.generate_time_story_storylines(
        db,
        owner_user_id=1,
        work_id=work["id"],
    )
    selected = await story_workflow.select_time_story_storyline(
        db,
        owner_user_id=1,
        work_id=work["id"],
        selected_storyline_id="one",
    )
    narrative = await story_workflow.generate_time_story_narrative(
        db,
        owner_user_id=1,
        work_id=work["id"],
    )
    confirmed = await story_workflow.confirm_time_story_narrative(
        db,
        owner_user_id=1,
        work_id=work["id"],
    )
    job = await story_workflow.start_work_picturebook_generation(
        db,
        owner_user_id=1,
        work_id=work["id"],
    )

    assert first["stage"] == "storylines_ready"
    assert repeated["storyline_candidates"] == first["storyline_candidates"]
    assert selected["selected_storyline"]["id"] == "one"
    assert selected["stage"] == "storylines_ready"
    assert narrative["narrative_text"] == "围绕第一条线写成的长文本。"
    assert narrative["stage"] == "narrative_editing"
    assert confirmed["stage"] == "narrative_confirmed"
    assert narrative_calls == [([{
        "id": diary_id,
        "date": "2026-08-01",
        "status": "confirmed",
        "body": "可用于长故事的正文。",
    }], "one")]
    assert job["source_text"] == "围绕第一条线写成的长文本。"
    assert job["work_id"] == work["id"]
    assert job["diary_id"] is None


@pytest.mark.asyncio
async def test_time_story_narrative_mutations_require_narrative_editing_stage(db):
    from services import story_workflow
    from services.story_workflow import StoryWorkflowConflict

    await create_account(db, 1)
    diary_id = await insert_diary(
        db, user_id=1, date="2026-08-01", body="还没有选择故事线的正文。"
    )
    work = await story_workflow.create_time_story_draft(
        db,
        owner_user_id=1,
        source_diary_ids=[diary_id],
        title="阶段门禁",
        style="crayon",
    )

    await db.execute(
        "UPDATE story_works SET narrative_text=? WHERE id=?",
        ("不应被直接确认的文本。", work["id"]),
    )
    await db.commit()

    with pytest.raises(StoryWorkflowConflict):
        await story_workflow.confirm_time_story_narrative(
            db,
            owner_user_id=1,
            work_id=work["id"],
        )

    with pytest.raises(StoryWorkflowConflict):
        await story_workflow.update_time_story_narrative(
            db,
            owner_user_id=1,
            work_id=work["id"],
            narrative_text="也不应绕过故事线阶段。",
        )


@pytest.mark.asyncio
async def test_time_story_narrative_rejects_stale_storyline_after_provider_returns(
    db,
    monkeypatch,
):
    from agents.time_story_agent import StorylineCandidate, StorylineResponse
    from services import story_workflow
    from services.story_workflow import StoryWorkflowConflict

    await create_account(db, 1)
    diary_id = await insert_diary(
        db, user_id=1, date="2026-08-01", body="可用于长故事的正文。"
    )
    candidates = [
        StorylineCandidate("one", "第一条线", "第一条摘要", ["2026-08-01"]),
        StorylineCandidate("two", "第二条线", "第二条摘要", ["2026-08-01"]),
        StorylineCandidate("three", "第三条线", "第三条摘要", ["2026-08-01"]),
    ]

    async def fake_candidates(_snapshots):
        return StorylineResponse(items=candidates)

    async def fake_narrative(_snapshots, _candidate):
        await db.execute(
            "UPDATE story_works SET selected_storyline_json=? WHERE id=?",
            (json.dumps(candidates[1].to_dict(), ensure_ascii=False), work["id"]),
        )
        await db.commit()
        return "这是旧故事线生成出的文本。"

    monkeypatch.setattr(
        story_workflow.time_story_agent,
        "generate_storyline_candidates",
        fake_candidates,
    )
    monkeypatch.setattr(
        story_workflow.time_story_agent,
        "generate_time_story_narrative",
        fake_narrative,
    )

    work = await story_workflow.create_time_story_draft(
        db,
        owner_user_id=1,
        source_diary_ids=[diary_id],
        title="竞态故事",
        style="crayon",
    )
    await story_workflow.generate_time_story_storylines(
        db, owner_user_id=1, work_id=work["id"]
    )
    await story_workflow.select_time_story_storyline(
        db,
        owner_user_id=1,
        work_id=work["id"],
        selected_storyline_id="one",
    )

    with pytest.raises(StoryWorkflowConflict):
        await story_workflow.generate_time_story_narrative(
            db,
            owner_user_id=1,
            work_id=work["id"],
        )

    row = await fetch_one(
        db,
        "SELECT selected_storyline_json, narrative_text FROM story_works WHERE id=?",
        (work["id"],),
    )
    assert json.loads(row["selected_storyline_json"])["id"] == "two"
    assert row["narrative_text"] is None


@pytest.mark.asyncio
async def test_time_story_replace_storylines_rejects_selection_race_after_provider_returns(
    db,
    monkeypatch,
):
    from agents.time_story_agent import StorylineCandidate, StorylineResponse
    from services import story_workflow
    from services.story_workflow import StoryWorkflowConflict

    await create_account(db, 1)
    diary_id = await insert_diary(
        db, user_id=1, date="2026-08-01", body="可用于长故事的正文。"
    )
    original = [
        StorylineCandidate("one", "第一条线", "第一条摘要", ["2026-08-01"]),
        StorylineCandidate("two", "第二条线", "第二条摘要", ["2026-08-01"]),
        StorylineCandidate("three", "第三条线", "第三条摘要", ["2026-08-01"]),
    ]
    replacement = [
        StorylineCandidate("new-one", "新第一条", "新摘要一", ["2026-08-01"]),
        StorylineCandidate("new-two", "新第二条", "新摘要二", ["2026-08-01"]),
        StorylineCandidate("new-three", "新第三条", "新摘要三", ["2026-08-01"]),
    ]

    async def first_candidates(_snapshots):
        return StorylineResponse(items=original)

    monkeypatch.setattr(
        story_workflow.time_story_agent,
        "generate_storyline_candidates",
        first_candidates,
    )
    work = await story_workflow.create_time_story_draft(
        db,
        owner_user_id=1,
        source_diary_ids=[diary_id],
        title="竞态故事线",
        style="crayon",
    )
    await story_workflow.generate_time_story_storylines(
        db, owner_user_id=1, work_id=work["id"]
    )

    async def replace_candidates(_snapshots):
        await story_workflow.select_time_story_storyline(
            db,
            owner_user_id=1,
            work_id=work["id"],
            selected_storyline_id="one",
        )
        return StorylineResponse(items=replacement)

    monkeypatch.setattr(
        story_workflow.time_story_agent,
        "generate_storyline_candidates",
        replace_candidates,
    )

    with pytest.raises(StoryWorkflowConflict):
        await story_workflow.generate_time_story_storylines(
            db,
            owner_user_id=1,
            work_id=work["id"],
            replace=True,
        )

    row = await fetch_one(
        db,
        "SELECT storyline_candidates_json, selected_storyline_json FROM story_works WHERE id=?",
        (work["id"],),
    )
    assert [item["id"] for item in json.loads(row["storyline_candidates_json"])] == [
        "one",
        "two",
        "three",
    ]
    assert json.loads(row["selected_storyline_json"])["id"] == "one"


@pytest.mark.asyncio
async def test_time_story_generation_failure_is_sanitized_and_stale_output_is_discarded(
    db,
    monkeypatch,
):
    from services import story_workflow

    await create_account(db, 1)
    diary_id = await insert_diary(db, user_id=1, date="2026-08-01", body="safe body")
    work = await story_workflow.create_time_story_draft(
        db,
        owner_user_id=1,
        source_diary_ids=[diary_id],
        title="stale",
        style="pixel",
    )

    async def fake_failure(_snapshots):
        raise RuntimeError("raw model output: safe body /private/tmp/key")

    monkeypatch.setattr(
        story_workflow.time_story_agent,
        "generate_storyline_candidates",
        fake_failure,
    )

    failed = await story_workflow.generate_time_story_storylines(
        db,
        owner_user_id=1,
        work_id=work["id"],
    )
    row = await fetch_one(db, "SELECT * FROM story_works WHERE id=?", (work["id"],))
    assert failed["stage"] == "sources_selected"
    assert failed["generation_error"] == "生成过程出错了，可以重试"
    assert row["storyline_candidates_json"] is None
    assert row["generation_error"] == "生成过程出错了，可以重试"


@pytest.mark.asyncio
async def test_time_story_contract_failure_uses_grounded_local_fallback(db, monkeypatch):
    from services import story_workflow

    await create_account(db, 1)
    diary_id = await insert_diary(db, user_id=1, date="2026-08-01", body="喝水，开会。")
    work = await story_workflow.create_time_story_draft(
        db,
        owner_user_id=1,
        source_diary_ids=[diary_id],
        title="fallback",
        style="watercolor",
    )

    async def invalid_contract(_snapshots):
        raise story_workflow.time_story_agent.TimeStoryAIContractError()

    monkeypatch.setattr(
        story_workflow.time_story_agent,
        "generate_storyline_candidates",
        invalid_contract,
    )
    resumed = await story_workflow.generate_time_story_storylines(
        db, owner_user_id=1, work_id=work["id"]
    )

    assert resumed["stage"] == "storylines_ready"
    assert resumed["generation_error"] is None
    assert len(resumed["storyline_candidates"]) == 3
    assert all("喝水，开会。" in item["summary"] for item in resumed["storyline_candidates"])


@pytest.mark.asyncio
async def test_duplicate_completed_time_story_copies_story_state_as_editing_draft(db):
    from services import story_workflow

    await create_account(db, 1)
    diary_id = await insert_diary(db, user_id=1, date="2026-08-01", body="copy body")
    work = await story_workflow.create_time_story_draft(
        db,
        owner_user_id=1,
        source_diary_ids=[diary_id],
        title="completed range",
        style="watercolor",
    )
    candidates = [
        {"id": "one", "title": "一", "summary": "一", "source_dates": ["2026-08-01"]},
        {"id": "two", "title": "二", "summary": "二", "source_dates": ["2026-08-01"]},
        {"id": "three", "title": "三", "summary": "三", "source_dates": ["2026-08-01"]},
    ]
    await db.execute(
        """
        UPDATE story_works
        SET status='ready',
            stage='ready',
            storyline_candidates_json=?,
            selected_storyline_json=?,
            narrative_text='confirmed narrative',
            active_picturebook_job_id=99,
            picturebook_job_id=100,
            cover_asset_id='cover'
        WHERE id=?
        """,
        (
            json.dumps(candidates, ensure_ascii=False),
            json.dumps(candidates[0], ensure_ascii=False),
            work["id"],
        ),
    )
    await db.commit()

    duplicate = await story_workflow.duplicate_daily_picturebook_draft(
        db,
        owner_user_id=1,
        work_id=work["id"],
    )
    copied = await fetch_one(db, "SELECT * FROM story_works WHERE id=?", (duplicate["id"],))

    assert copied["kind"] == "time_story"
    assert copied["status"] == "draft"
    assert copied["stage"] == "narrative_editing"
    assert json.loads(copied["storyline_candidates_json"]) == candidates
    assert json.loads(copied["selected_storyline_json"]) == candidates[0]
    assert copied["narrative_text"] == "confirmed narrative"
    assert copied["active_picturebook_job_id"] is None
    assert copied["picturebook_job_id"] is None
    assert copied["cover_asset_id"] is None


@pytest.mark.asyncio
async def test_replace_daily_draft_source_invalidates_unfinished_outputs(db):
    from services.story_workflow import (
        create_daily_picturebook_draft,
        replace_daily_picturebook_sources,
    )

    await create_account(db, 1)
    first_diary_id = await insert_diary(db, user_id=1, body="Old paragraph.")
    second_diary_id = await insert_diary(
        db,
        user_id=1,
        date="2026-08-09",
        body="New full paragraph.\n\nAnother full paragraph.",
    )
    work = await create_daily_picturebook_draft(
        db,
        owner_user_id=1,
        diary_id=first_diary_id,
        selected_segments=["Old paragraph."],
        title="Mutable Draft",
        style="pixel",
    )
    await db.execute(
        """
        INSERT INTO picturebook_jobs (
            user_id, work_id, source_text, source_signature, style, status,
            stage, error, total_pages, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, 'failed', 'failed', ?, 9, ?, ?)
        """,
        (
            1,
            work["id"],
            "Old paragraph.",
            "old-signature",
            "pixel",
            "raw provider prompt /private/tmp/leak.png",
            "2026-08-08T00:00:00Z",
            "2026-08-08T00:00:00Z",
        ),
    )
    job_id = (await fetch_one(db, "SELECT id FROM picturebook_jobs"))["id"]
    await db.execute(
        """
        UPDATE story_works
        SET stage='render_failed',
            active_picturebook_job_id=?,
            generation_error='raw provider prompt /private/tmp/leak.png',
            cover_asset_id='asset-cover',
            selected_storyline_json='{"old":true}',
            storyline_candidates_json='[{"old":true}]',
            narrative_text='old narrative'
        WHERE id=?
        """,
        (job_id, work["id"]),
    )
    await db.execute(
        """
        INSERT INTO work_assets (work_id, ordinal, asset_type, url, text)
        VALUES (?, 0, 'image', '/api/media/assets/old', 'old')
        """,
        (work["id"],),
    )
    await db.commit()

    updated = await replace_daily_picturebook_sources(
        db,
        owner_user_id=1,
        work_id=work["id"],
        diary_id=second_diary_id,
        selected_segments=["New full paragraph."],
    )

    row = await fetch_one(db, "SELECT * FROM story_works WHERE id=?", (work["id"],))
    snapshot = json.loads(row["source_snapshot_json"])
    assert updated["stage"] == "narrative_confirmed"
    assert row["source_diary_id"] == second_diary_id
    assert row["stage"] == "narrative_confirmed"
    assert row["active_picturebook_job_id"] is None
    assert row["generation_error"] is None
    assert row["cover_asset_id"] is None
    assert row["selected_storyline_json"] is None
    assert row["storyline_candidates_json"] is None
    assert row["narrative_text"] is None
    assert json.loads(row["selected_segments_json"]) == ["New full paragraph."]
    assert snapshot["diaries"][0]["id"] == second_diary_id
    assert await fetch_all(
        db,
        "SELECT diary_id, ordinal FROM story_work_diaries WHERE work_id=?",
        (work["id"],),
    ) == [{"diary_id": second_diary_id, "ordinal": 0}]
    assert await fetch_one(
        db,
        "SELECT COUNT(*) AS count FROM work_assets WHERE work_id=?",
        (work["id"],),
    ) == {"count": 0}


@pytest.mark.asyncio
async def test_replace_daily_draft_source_rejects_rendering_ready_and_published(db):
    from services.story_workflow import (
        StoryWorkflowConflict,
        create_daily_picturebook_draft,
        replace_daily_picturebook_sources,
    )

    await create_account(db, 1)
    old_diary_id = await insert_diary(db, user_id=1, body="Old paragraph.")
    new_diary_id = await insert_diary(db, user_id=1, body="New paragraph.")

    for status, stage in [
        ("draft", "rendering"),
        ("ready", "ready"),
        ("published", "ready"),
    ]:
        work = await create_daily_picturebook_draft(
            db,
            owner_user_id=1,
            diary_id=old_diary_id,
            selected_segments=["Old paragraph."],
            title=f"{status}-{stage}",
            style="pixel",
        )
        await db.execute(
            "UPDATE story_works SET status=?, stage=? WHERE id=?",
            (status, stage, work["id"]),
        )
        await db.commit()

        with pytest.raises(StoryWorkflowConflict):
            await replace_daily_picturebook_sources(
                db,
                owner_user_id=1,
                work_id=work["id"],
                diary_id=new_diary_id,
                selected_segments=["New paragraph."],
            )


@pytest.mark.asyncio
async def test_render_failed_style_change_invalidates_stale_picturebook_attempt(db):
    from services.story_workflow import (
        create_daily_picturebook_draft,
        update_daily_picturebook_draft_metadata,
    )

    await create_account(db, 1)
    diary_id = await insert_diary(db, user_id=1, body="Old paragraph.")
    work = await create_daily_picturebook_draft(
        db,
        owner_user_id=1,
        diary_id=diary_id,
        selected_segments=["Old paragraph."],
        title="Failed Draft",
        style="pixel",
    )
    await db.execute(
        """
        INSERT INTO picturebook_jobs (
            user_id, work_id, source_text, source_signature, style, status,
            stage, error, total_pages, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, 'failed', 'failed', ?, 9, ?, ?)
        """,
        (
            1,
            work["id"],
            "Old paragraph.",
            "old-signature",
            "pixel",
            "raw provider failure",
            "2026-08-08T00:00:00Z",
            "2026-08-08T00:00:00Z",
        ),
    )
    job_id = (await fetch_one(db, "SELECT id FROM picturebook_jobs"))["id"]
    await db.execute(
        """
        UPDATE story_works
        SET stage='render_failed',
            active_picturebook_job_id=?,
            generation_error='raw provider failure',
            cover_asset_id='cover-asset'
        WHERE id=?
        """,
        (job_id, work["id"]),
    )
    await db.execute(
        """
        INSERT INTO work_assets (work_id, ordinal, asset_type, url, text)
        VALUES (?, 0, 'image', '/api/media/assets/old-cover', 'old cover')
        """,
        (work["id"],),
    )
    await db.commit()

    updated = await update_daily_picturebook_draft_metadata(
        db,
        owner_user_id=1,
        work_id=work["id"],
        style="watercolor",
    )

    row = await fetch_one(db, "SELECT * FROM story_works WHERE id=?", (work["id"],))
    assert updated["stage"] == "narrative_confirmed"
    assert row["style"] == "watercolor"
    assert row["stage"] == "narrative_confirmed"
    assert row["active_picturebook_job_id"] is None
    assert row["picturebook_job_id"] is None
    assert row["generation_error"] is None
    assert row["cover_asset_id"] is None
    assert await fetch_one(
        db,
        "SELECT COUNT(*) AS count FROM work_assets WHERE work_id=?",
        (work["id"],),
    ) == {"count": 0}


@pytest.mark.asyncio
async def test_duplicate_ready_or_published_daily_work_as_clean_draft(db):
    from services.story_workflow import (
        StoryWorkflowConflict,
        create_daily_picturebook_draft,
        duplicate_daily_picturebook_draft,
    )

    await create_account(db, 1)
    diary_id = await insert_diary(
        db, user_id=1, body="Copy me.\n\nKeep this selected paragraph."
    )
    draft = await create_daily_picturebook_draft(
        db,
        owner_user_id=1,
        diary_id=diary_id,
        selected_segments=["Keep this selected paragraph."],
        title="Original Ready Work",
        style="crayon",
    )

    with pytest.raises(StoryWorkflowConflict):
        await duplicate_daily_picturebook_draft(db, owner_user_id=1, work_id=draft["id"])

    await db.execute(
        """
        INSERT INTO picturebook_jobs (
            user_id, work_id, source_text, source_signature, style, status,
            stage, total_pages, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, 'done', 'done', 9, ?, ?)
        """,
        (
            1,
            draft["id"],
            "Keep this selected paragraph.",
            "signature",
            "crayon",
            "2026-08-08T00:00:00Z",
            "2026-08-08T00:00:00Z",
        ),
    )
    job_id = (await fetch_one(db, "SELECT id FROM picturebook_jobs"))["id"]
    await db.execute(
        """
        UPDATE story_works
        SET status='ready',
            stage='ready',
            active_picturebook_job_id=?,
            picturebook_job_id=?,
            cover_asset_id='cover-asset'
        WHERE id=?
        """,
        (job_id, job_id, draft["id"]),
    )
    await db.execute(
        """
        INSERT INTO work_assets (work_id, ordinal, asset_type, url, text)
        VALUES (?, 0, 'image', '/api/media/assets/cover-asset', 'cover')
        """,
        (draft["id"],),
    )
    await db.commit()

    duplicate = await duplicate_daily_picturebook_draft(
        db, owner_user_id=1, work_id=draft["id"]
    )
    copied = await fetch_one(db, "SELECT * FROM story_works WHERE id=?", (duplicate["id"],))

    assert duplicate["id"] != draft["id"]
    assert copied["status"] == "draft"
    assert copied["stage"] == "narrative_confirmed"
    assert copied["kind"] == "daily_picturebook"
    assert copied["title"] == "Original Ready Work"
    assert copied["style"] == "crayon"
    assert copied["active_picturebook_job_id"] is None
    assert copied["picturebook_job_id"] is None
    assert copied["cover_asset_id"] is None
    assert json.loads(copied["selected_segments_json"]) == [
        "Keep this selected paragraph."
    ]
    assert json.loads(copied["source_snapshot_json"]) == json.loads(
        (await fetch_one(db, "SELECT source_snapshot_json FROM story_works WHERE id=?", (draft["id"],)))[
            "source_snapshot_json"
        ]
    )
    assert await fetch_all(
        db,
        "SELECT diary_id, ordinal FROM story_work_diaries WHERE work_id=?",
        (duplicate["id"],),
    ) == [{"diary_id": diary_id, "ordinal": 0}]
    assert await fetch_one(
        db,
        "SELECT COUNT(*) AS count FROM work_assets WHERE work_id=?",
        (duplicate["id"],),
    ) == {"count": 0}


def test_api_creates_reads_and_lists_only_owner_drafts(workflow_app):
    app, db_path = workflow_app
    with registered_clients(app, db_path) as (alice, bob, alice_profile, bob_profile):
        alice_diary_id = insert_diary_sync(
            db_path,
            user_id=alice_profile["id"],
            body="First paragraph.\n\nSecond paragraph.",
        )
        bob_diary_id = insert_diary_sync(
            db_path,
            user_id=bob_profile["id"],
            body="Bob paragraph.",
        )

        created = alice.post(
            "/api/story/works/drafts",
            json={
                "kind": "daily_picturebook",
                "source_diary_ids": [alice_diary_id],
                "selected_segments": ["First paragraph."],
                "title": "Alice Draft",
                "style": "pixel",
            },
        )
        assert created.status_code == 201
        body = created.json()
        assert body["kind"] == "daily_picturebook"
        assert body["status"] == "draft"
        assert body["stage"] == "narrative_confirmed"
        assert body["selected_segments"] == ["First paragraph."]
        assert body["source_diary_ids"] == [alice_diary_id]
        assert body["source_diaries"] == [
            {
                "id": alice_diary_id,
                "date": "2026-08-08",
                "status": "confirmed",
                "text": "First paragraph.\n\nSecond paragraph.",
            }
        ]
        assert body["source_snapshot"]["diaries"][0]["body"] == (
            "First paragraph.\n\nSecond paragraph."
        )
        assert body["created_at"]
        assert body["updated_at"]
        assert body["generation_error"] is None
        assert body["active_picturebook_job"] is None
        assert body["picturebook_job"] is None
        assert body["pages"] == []

        assert bob.get(f"/api/story/works/{body['id']}").status_code == 404
        stolen_source = bob.post(
            "/api/story/works/drafts",
            json={
                "kind": "daily_picturebook",
                "source_diary_ids": [alice_diary_id],
                "selected_segments": ["First paragraph."],
                "title": "Stolen",
                "style": "pixel",
            },
        )
        assert stolen_source.status_code == 404

        second = alice.post(
            "/api/story/works/drafts",
            json={
                "kind": "daily_picturebook",
                "source_diary_ids": [alice_diary_id],
                "selected_segments": ["Second paragraph."],
                "title": "Alice Second Draft",
                "style": "pixel",
            },
        )
        bob_draft = bob.post(
            "/api/story/works/drafts",
            json={
                "kind": "daily_picturebook",
                "source_diary_ids": [bob_diary_id],
                "selected_segments": ["Bob paragraph."],
                "title": "Bob Draft",
                "style": "pixel",
            },
        )
        assert second.status_code == bob_draft.status_code == 201
        with sqlite3.connect(db_path) as db:
            db.execute(
                "UPDATE story_works SET status='ready', stage='ready' WHERE id=?",
                (body["id"],),
            )
            db.commit()

        listing = alice.get("/api/story/works/drafts")
        assert listing.status_code == 200
        assert [item["id"] for item in listing.json()["items"]] == [second.json()["id"]]

        rejected_multi_source = alice.post(
            "/api/story/works/drafts",
            json={
                "kind": "daily_picturebook",
                "source_diary_ids": [alice_diary_id, bob_diary_id],
                "selected_segments": ["First paragraph."],
                "title": "Too Many Sources",
                "style": "pixel",
            },
        )
        assert rejected_multi_source.status_code == 422


def test_api_rejects_same_origin_failures_and_client_controlled_fields(workflow_app):
    app, db_path = workflow_app
    with registered_clients(app, db_path) as (alice, _bob, alice_profile, _bob_profile):
        diary_id = insert_diary_sync(
            db_path, user_id=alice_profile["id"], body="Only paragraph."
        )

        blocked = alice.post(
            "/api/story/works/drafts",
            json={
                "kind": "daily_picturebook",
                "source_diary_ids": [diary_id],
                "selected_segments": ["Only paragraph."],
                "title": "Blocked",
                "style": "pixel",
            },
            headers={"Origin": FOREIGN_ORIGIN},
        )
        assert blocked.status_code == 403
        assert blocked.json() == {"detail": "origin not allowed"}

        controlled = alice.post(
            "/api/story/works/drafts",
            json={
                "kind": "daily_picturebook",
                "source_diary_ids": [diary_id],
                "selected_segments": ["Only paragraph."],
                "title": "Controlled",
                "style": "pixel",
                "owner_user_id": alice_profile["id"],
                "status": "ready",
                "stage": "ready",
                "job_id": 1,
                "asset_id": "asset",
            },
        )
        assert controlled.status_code == 422


def test_api_updates_metadata_sources_and_duplicates_with_owner_scope(workflow_app):
    app, db_path = workflow_app
    with registered_clients(app, db_path) as (alice, bob, alice_profile, _bob_profile):
        first_diary_id = insert_diary_sync(
            db_path,
            user_id=alice_profile["id"],
            body="Original paragraph.",
        )
        next_diary_id = insert_diary_sync(
            db_path,
            user_id=alice_profile["id"],
            body="Replacement paragraph.",
            date="2026-08-09",
        )
        created = alice.post(
            "/api/story/works/drafts",
            json={
                "kind": "daily_picturebook",
                "source_diary_ids": [first_diary_id],
                "selected_segments": ["Original paragraph."],
                "title": "Original",
                "style": "pixel",
            },
        )
        assert created.status_code == 201
        work_id = created.json()["id"]

        metadata = alice.put(
            f"/api/story/works/{work_id}",
            json={"title": "Renamed", "style": "watercolor"},
        )
        assert metadata.status_code == 200
        assert metadata.json()["title"] == "Renamed"
        assert metadata.json()["style"] == "watercolor"

        assert bob.put(
            f"/api/story/works/{work_id}",
            json={"title": "Stolen"},
        ).status_code == 404

        replaced = alice.put(
            f"/api/story/works/{work_id}/sources",
            json={
                "kind": "daily_picturebook",
                "source_diary_ids": [next_diary_id],
                "selected_segments": ["Replacement paragraph."],
            },
        )
        assert replaced.status_code == 200
        assert replaced.json()["source_diaries"] == [
            {
                "id": next_diary_id,
                "date": "2026-08-09",
                "status": "confirmed",
                "text": "Replacement paragraph.",
            }
        ]
        assert replaced.json()["stage"] == "narrative_confirmed"

        with sqlite3.connect(db_path) as db:
            db.execute(
                "UPDATE story_works SET status='ready', stage='ready' WHERE id=?",
                (work_id,),
            )
            db.commit()

        duplicate = alice.post(f"/api/story/works/{work_id}/duplicate-draft")
        assert duplicate.status_code == 201
        assert duplicate.json()["id"] != work_id
        assert duplicate.json()["status"] == "draft"
        assert duplicate.json()["stage"] == "narrative_confirmed"
        assert duplicate.json()["selected_segments"] == ["Replacement paragraph."]

        assert bob.post(f"/api/story/works/{work_id}/duplicate-draft").status_code == 404


def test_api_create_time_story_accepts_source_date_range_names(workflow_app):
    app, db_path = workflow_app
    with registered_clients(app, db_path) as (alice, _bob, alice_profile, _bob_profile):
        first_diary_id = insert_diary_sync(
            db_path,
            user_id=alice_profile["id"],
            date="2026-08-03",
            body="周一正文。",
        )
        second_diary_id = insert_diary_sync(
            db_path,
            user_id=alice_profile["id"],
            date="2026-08-05",
            body="",
            status="draft",
        )
        with sqlite3.connect(db_path) as db:
            db.execute(
                "UPDATE diaries SET draft_text=? WHERE id=?",
                ("周三草稿正文。", second_diary_id),
            )
            db.commit()

        created = alice.post(
            "/api/story/works/drafts",
            json={
                "kind": "time_story",
                "source_start_date": "2026-08-03",
                "source_end_date": "2026-08-09",
                "source_diary_ids": [first_diary_id, second_diary_id],
                "selected_segments": [],
                "title": "这一周",
                "style": "watercolor",
            },
        )
        created_without_segments = alice.post(
            "/api/story/works/drafts",
            json={
                "kind": "time_story",
                "source_start_date": "2026-08-03",
                "source_end_date": "2026-08-09",
                "source_diary_ids": [first_diary_id, second_diary_id],
                "title": "这一周的另一个版本",
                "style": "watercolor",
            },
        )
        daily_with_empty_segments = alice.post(
            "/api/story/works/drafts",
            json={
                "kind": "daily_picturebook",
                "source_diary_ids": [first_diary_id],
                "selected_segments": [],
                "title": "无段落绘本",
                "style": "watercolor",
            },
        )

    assert created.status_code == 201
    assert created_without_segments.status_code == 201
    assert daily_with_empty_segments.status_code == 422
    payload = created.json()
    assert payload["source_start_date"] == "2026-08-03"
    assert payload["source_end_date"] == "2026-08-09"
    assert payload["source_diary_ids"] == [first_diary_id, second_diary_id]
    assert payload["source_diaries"][1]["text"] == "周三草稿正文。"


def test_api_detail_returns_resumable_safe_generation_state(workflow_app):
    app, db_path = workflow_app
    with registered_clients(app, db_path) as (alice, _bob, alice_profile, _bob_profile):
        diary_id = insert_diary_sync(
            db_path, user_id=alice_profile["id"], body="Safe paragraph."
        )
        created = alice.post(
            "/api/story/works/drafts",
            json={
                "kind": "daily_picturebook",
                "source_diary_ids": [diary_id],
                "selected_segments": ["Safe paragraph."],
                "title": "Recoverable",
                "style": "pixel",
            },
        )
        assert created.status_code == 201
        work_id = created.json()["id"]
        owned_asset_id = str(uuid4())
        foreign_asset_id = str(uuid4())
        foreign_owner_id = alice_profile["id"] + 1000
        with sqlite3.connect(db_path) as db:
            db.execute(
                "INSERT INTO profile (id, nickname) VALUES (?, 'Foreign Asset Owner')",
                (foreign_owner_id,),
            )
            db.execute(
                "INSERT INTO accounts (user_id, username_norm, password_hash) "
                "VALUES (?, 'foreign-asset-owner', 'not-a-real-password-hash')",
                (foreign_owner_id,),
            )
            db.execute(
                """
                INSERT INTO media_assets (
                    id, owner_user_id, storage_key, mime_type, size_bytes
                ) VALUES (?, ?, 'owned.png', 'image/png', 1)
                """,
                (owned_asset_id, alice_profile["id"]),
            )
            db.execute(
                """
                INSERT INTO media_assets (
                    id, owner_user_id, storage_key, mime_type, size_bytes
                ) VALUES (?, ?, 'foreign.png', 'image/png', 1)
                """,
                (foreign_asset_id, foreign_owner_id),
            )
            cursor = db.execute(
                """
                INSERT INTO picturebook_jobs (
                    user_id, work_id, source_text, source_signature, style,
                    status, stage, error, total_pages, created_at, updated_at
                ) VALUES (?, ?, 'Safe paragraph.', 'sig-active', 'pixel',
                    'failed', 'failed', ?, 9, ?, ?)
                """,
                (
                    alice_profile["id"],
                    work_id,
                    "provider prompt=/private/tmp/raw.png filesystem path leaked",
                    "2026-08-08T00:00:00Z",
                    "2026-08-08T00:00:00Z",
                ),
            )
            active_job_id = cursor.lastrowid
            cursor = db.execute(
                """
                INSERT INTO picturebook_jobs (
                    user_id, work_id, source_text, source_signature, style,
                    status, stage, total_pages, created_at, updated_at
                ) VALUES (?, ?, 'Safe paragraph.', 'sig-formal', 'pixel',
                    'done', 'done', 9, ?, ?)
                """,
                (
                    alice_profile["id"],
                    work_id,
                    "2026-08-08T00:00:01Z",
                    "2026-08-08T00:00:01Z",
                ),
            )
            formal_job_id = cursor.lastrowid
            db.execute(
                """
                INSERT INTO picturebook_pages (
                    job_id, page_index, image_id, caption, image_url, asset_id,
                    status, created_at, updated_at
                ) VALUES (?, 0, 'raw-image-id', 'active caption',
                    '/private/tmp/active.png', ?, 'ready', ?, ?)
                """,
                (
                    active_job_id,
                    owned_asset_id,
                    "2026-08-08T00:00:00Z",
                    "2026-08-08T00:00:00Z",
                ),
            )
            db.execute(
                """
                INSERT INTO work_assets (
                    work_id, ordinal, asset_type, url, asset_id, text, prompt
                ) VALUES (?, 1, 'image', '/private/tmp/formal.png', ?, 'formal one',
                    'raw prompt')
                """,
                (work_id, owned_asset_id),
            )
            db.execute(
                """
                INSERT INTO work_assets (
                    work_id, ordinal, asset_type, url, asset_id, text, prompt
                ) VALUES (?, 2, 'image', '/api/media/assets/foreign', ?,
                    'formal foreign', 'raw prompt')
                """,
                (work_id, foreign_asset_id),
            )
            db.execute(
                """
                UPDATE story_works
                SET status='ready',
                    stage='ready',
                    generation_error=?,
                    active_picturebook_job_id=?,
                    picturebook_job_id=?,
                    cover_asset_id=?
                WHERE id=?
                """,
                (
                    "provider prompt=/private/tmp/raw.png filesystem path leaked",
                    active_job_id,
                    formal_job_id,
                    owned_asset_id,
                    work_id,
                ),
            )
            db.commit()

        detail = alice.get(f"/api/story/works/{work_id}")
        assert detail.status_code == 200
        payload = detail.json()
        encoded = json.dumps(payload, ensure_ascii=False)
        assert "prompt" not in encoded
        assert "/private/tmp" not in encoded
        assert "filesystem path" not in encoded
        assert "provider" not in encoded
        assert foreign_asset_id not in encoded
        assert payload["generation_error"] == "生成过程出错了，可以重试"
        assert payload["active_picturebook_job"] == {
            "id": active_job_id,
            "status": "failed",
            "stage": "failed",
            "total_pages": 9,
            "ready_pages": 1,
        }
        assert payload["picturebook_job"] == {
            "id": formal_job_id,
            "status": "done",
            "stage": "done",
            "total_pages": 9,
            "ready_pages": 0,
        }
        assert payload["pages"] == [
            {
                "page_index": 1,
                "image_url": f"/api/media/{owned_asset_id}",
                "caption": "formal one",
            }
        ]


def test_legacy_diary_picturebook_payload_keeps_nullable_work_id(workflow_app, monkeypatch):
    import routers.picturebook as picturebook_router

    async def fake_spawn(job_id, user_id):
        return None

    monkeypatch.setattr(picturebook_router, "_spawn", fake_spawn)

    app, db_path = workflow_app
    with registered_clients(app, db_path) as (alice, _bob, alice_profile, _bob_profile):
        diary_id = insert_diary_sync(
            db_path,
            user_id=alice_profile["id"],
            body="Legacy paragraph.",
        )
        with sqlite3.connect(db_path) as db:
            db.execute(
                "UPDATE diaries SET emotion_mode=? WHERE id=? AND user_id=?",
                ("imagery", diary_id, alice_profile["id"]),
            )
            db.commit()

        created = alice.post(
            f"/api/picturebook/diary/{diary_id}",
            json={"style": "pixel"},
        )
        assert created.status_code == 200
        assert created.json()["diary_id"] == diary_id
        assert created.json()["work_id"] is None

        job_id = created.json()["id"]
        assert fetch_one_sync(
            db_path,
            "SELECT allow_imaginative FROM picturebook_jobs "
            "WHERE id=? AND user_id=?",
            (job_id, alice_profile["id"]),
        ) == {"allow_imaginative": 1}
        with sqlite3.connect(db_path) as db:
            db.execute(
                "UPDATE diaries SET emotion_mode=? WHERE id=? AND user_id=?",
                ("real", diary_id, alice_profile["id"]),
            )
            db.commit()
        fetched = alice.get(f"/api/picturebook/{job_id}")
        latest = alice.get(f"/api/picturebook/diary/{diary_id}/latest?style=pixel")
        retried = alice.post(f"/api/picturebook/{job_id}/retry")
        assert fetched.status_code == latest.status_code == retried.status_code == 200
        assert fetched.json()["work_id"] is None
        assert latest.json()["id"] == job_id
        assert retried.json()["id"] == job_id


def test_direct_diary_picturebook_reuses_only_matching_source_snapshot(
    workflow_app, monkeypatch
):
    import routers.picturebook as picturebook_router

    async def fake_spawn(job_id, user_id):
        return None

    monkeypatch.setattr(picturebook_router, "_spawn", fake_spawn)
    app, db_path = workflow_app
    with registered_clients(app, db_path) as (alice, _bob, alice_profile, _bob_profile):
        diary_id = insert_diary_sync(
            db_path,
            user_id=alice_profile["id"],
            body="Original final body.",
        )
        with sqlite3.connect(db_path) as db:
            db.execute(
                "UPDATE diaries SET draft_text=?, emotion_mode=? WHERE id=?",
                ("Original final draft.", "real", diary_id),
            )
            db.commit()

        first = alice.post(
            f"/api/picturebook/diary/{diary_id}", json={"style": "pixel"}
        ).json()
        same = alice.post(
            f"/api/picturebook/diary/{diary_id}", json={"style": "pixel"}
        ).json()
        assert same["id"] == first["id"]

        first_snapshot = fetch_one_sync(
            db_path,
            "SELECT source_text, source_signature, allow_imaginative "
            "FROM picturebook_jobs WHERE id=?",
            (first["id"],),
        )
        assert first_snapshot["source_text"] == "Original final draft."
        assert first_snapshot["source_signature"]
        assert "Original final draft." not in first_snapshot["source_signature"]
        assert first_snapshot["allow_imaginative"] == 0

        # 底片夹改版后同一用户同时只能有一个 running 绘本任务;第一个任务还
        # 在跑,后续不同签名的开始请求应返回 409 并携带活动任务 id。
        with sqlite3.connect(db_path) as db:
            db.execute(
                "UPDATE diaries SET draft_text=? WHERE id=?",
                ("Changed final draft.", diary_id),
            )
            db.commit()
        changed_text = alice.post(
            f"/api/picturebook/diary/{diary_id}", json={"style": "pixel"}
        )
        assert changed_text.status_code == 409
        assert changed_text.json()["detail"]["active_job_id"] == first["id"]

        with sqlite3.connect(db_path) as db:
            db.execute(
                "UPDATE diaries SET emotion_mode=? WHERE id=?",
                ("imagery", diary_id),
            )
            db.commit()
        changed_mode = alice.post(
            f"/api/picturebook/diary/{diary_id}", json={"style": "pixel"}
        )
        assert changed_mode.status_code == 409

        changed_style = alice.post(
            f"/api/picturebook/diary/{diary_id}", json={"style": "sketch"}
        )
        assert changed_style.status_code == 409

        # 第一个任务结束后,不同签名可以创建新任务。
        with sqlite3.connect(db_path) as db:
            db.execute(
                "UPDATE picturebook_jobs SET status='done', stage='done' WHERE id=?",
                (first["id"],),
            )
            db.commit()
        after_done = alice.post(
            f"/api/picturebook/diary/{diary_id}", json={"style": "sketch"}
        ).json()
        assert after_done["id"] != first["id"]


def test_direct_diary_picturebook_retry_returns_running_and_snapshots_legacy_job(
    workflow_app, monkeypatch
):
    import routers.picturebook as picturebook_router

    async def fake_spawn(job_id, user_id):
        return None

    monkeypatch.setattr(picturebook_router, "_spawn", fake_spawn)
    app, db_path = workflow_app
    with registered_clients(app, db_path) as (alice, _bob, alice_profile, _bob_profile):
        diary_id = insert_diary_sync(
            db_path,
            user_id=alice_profile["id"],
            body="Retry snapshot body.",
        )
        with sqlite3.connect(db_path) as db:
            cursor = db.execute(
                """
                INSERT INTO picturebook_jobs (
                    user_id, diary_id, style, status, stage, error,
                    total_pages, created_at, updated_at
                ) VALUES (?, ?, 'pixel', 'failed', 'failed', 'old failure',
                    9, '2026-08-08T00:00:00Z', '2026-08-08T00:00:00Z')
                """,
                (alice_profile["id"], diary_id),
            )
            job_id = cursor.lastrowid
            db.commit()

        retried = alice.post(f"/api/picturebook/{job_id}/retry")

        assert retried.status_code == 200
        assert retried.json()["status"] == "running"
        assert retried.json()["error"] is None
        snapshot = fetch_one_sync(
            db_path,
            "SELECT source_text, source_signature, status, error "
            "FROM picturebook_jobs WHERE id=?",
            (job_id,),
        )
        assert snapshot["source_text"] == "Retry snapshot body."
        assert snapshot["source_signature"]
        assert snapshot["status"] == "running"
        assert snapshot["error"] is None


def test_api_starts_work_picturebook_with_ordered_source_and_reuses_active_job(
    workflow_app, monkeypatch
):
    import routers.story_workflow as workflow_router
    from services.story_workflow import picturebook_source_signature

    spawned = []

    async def fake_spawn(job_id, user_id):
        spawned.append((job_id, user_id))

    monkeypatch.setattr(workflow_router, "_spawn_picturebook_job", fake_spawn, raising=False)

    app, db_path = workflow_app
    with registered_clients(app, db_path) as (alice, _bob, alice_profile, _bob_profile):
        insert_character_profile_sync(db_path, user_id=alice_profile["id"], preset="p01")
        diary_id = insert_diary_sync(
            db_path,
            user_id=alice_profile["id"],
            body="First paragraph.\n\nSecond paragraph.\n\nThird paragraph.",
        )
        created = alice.post(
            "/api/story/works/drafts",
            json={
                "kind": "daily_picturebook",
                "source_diary_ids": [diary_id],
                "selected_segments": ["Third paragraph.", "First paragraph."],
                "title": "Ordered Source",
                "style": "pixel",
            },
        )
        assert created.status_code == 201
        work_id = created.json()["id"]

        started = alice.post(
            f"/api/story/works/{work_id}/picturebook",
            json={"replace": False},
        )
        assert started.status_code == 200
        payload = started.json()
        job_id = payload["id"]
        assert payload["diary_id"] is None
        assert payload["work_id"] == work_id
        assert payload["status"] == "running"
        assert payload["stage"] == "queued"
        assert payload["total_pages"] == 9
        assert payload["ready_pages"] == 0
        assert payload["pages"] == []
        assert spawned == [(job_id, alice_profile["id"])]

        job = fetch_one_sync(db_path, "SELECT * FROM picturebook_jobs WHERE id=?", (job_id,))
        work = fetch_one_sync(db_path, "SELECT * FROM story_works WHERE id=?", (work_id,))
        source_text = "First paragraph.\n\nThird paragraph."
        character_signature = preset_character_signature("p01")
        signature_work = {
            **work,
            "source_diary_ids": [diary_id],
            "character_signature": character_signature,
        }
        assert job["diary_id"] is None
        assert job["work_id"] == work_id
        assert job["source_text"] == source_text
        assert job["allow_imaginative"] == 0
        assert job["source_signature"] == picturebook_source_signature(
            signature_work,
            source_text,
            False,
        )
        assert job["character_signature"] == character_signature
        assert work["status"] == "draft"
        assert work["stage"] == "rendering"
        assert work["active_picturebook_job_id"] == job_id
        assert work["generation_error"] is None

        with sqlite3.connect(db_path) as db:
            db.execute(
                "UPDATE picturebook_jobs SET status='failed', error='raw failure' "
                "WHERE id=?",
                (job_id,),
            )
            db.execute(
                "UPDATE story_works SET stage='render_failed', generation_error='raw failure' "
                "WHERE id=?",
                (work_id,),
            )
            db.commit()
        repeated = alice.post(
            f"/api/story/works/{work_id}/picturebook",
            json={"replace": False},
        )
        assert repeated.status_code == 200
        assert repeated.json()["id"] == job_id
        assert fetch_one_sync(
            db_path,
            "SELECT status, error FROM picturebook_jobs WHERE id=?",
            (job_id,),
        ) == {"status": "running", "error": None}
        assert fetch_one_sync(
            db_path,
            "SELECT COUNT(*) AS count FROM picturebook_jobs WHERE work_id=?",
            (work_id,),
        ) == {"count": 1}


def test_work_picturebook_payload_sanitizes_failed_page_errors(workflow_app, monkeypatch):
    import routers.story_workflow as workflow_router

    async def fake_spawn(job_id, user_id):
        return None

    monkeypatch.setattr(workflow_router, "_spawn_picturebook_job", fake_spawn, raising=False)

    app, db_path = workflow_app
    with registered_clients(app, db_path) as (alice, _bob, alice_profile, _bob_profile):
        diary_id = insert_diary_sync(
            db_path,
            user_id=alice_profile["id"],
            body="Private paragraph.",
        )
        created = alice.post(
            "/api/story/works/drafts",
            json={
                "kind": "daily_picturebook",
                "source_diary_ids": [diary_id],
                "selected_segments": ["Private paragraph."],
                "title": "Sanitize Page Error",
                "style": "pixel",
            },
        )
        job = alice.post(
            f"/api/story/works/{created.json()['id']}/picturebook",
            json={"replace": False},
        ).json()
        with sqlite3.connect(db_path) as db:
            db.execute(
                """
                INSERT INTO picturebook_pages (
                    job_id, page_index, image_id, caption, image_prompt, status,
                    error, created_at, updated_at
                ) VALUES (?, 0, 'cover', 'cover caption', 'raw prompt', 'failed',
                    ?, ?, ?)
                """,
                (
                    job["id"],
                    "provider prompt /private/tmp/generated.png",
                    "2026-08-08T00:00:00Z",
                    "2026-08-08T00:00:00Z",
                ),
            )
            db.commit()

        payload = alice.get(f"/api/picturebook/{job['id']}")

        assert payload.status_code == 200
        encoded = json.dumps(payload.json(), ensure_ascii=False)
        assert "provider" not in encoded
        assert "prompt" not in encoded
        assert "/private/tmp" not in encoded
        assert payload.json()["pages"][0]["error"] == "生成过程出错了，可以重试"


def test_legacy_retry_rejects_work_backed_jobs(workflow_app, monkeypatch):
    import routers.picturebook as picturebook_router
    import routers.story_workflow as workflow_router

    spawned = []

    async def fake_story_spawn(job_id, user_id):
        return None

    async def fake_legacy_spawn(job_id, user_id):
        spawned.append((job_id, user_id))

    monkeypatch.setattr(workflow_router, "_spawn_picturebook_job", fake_story_spawn, raising=False)
    monkeypatch.setattr(picturebook_router, "_spawn", fake_legacy_spawn)

    app, db_path = workflow_app
    with registered_clients(app, db_path) as (alice, _bob, alice_profile, _bob_profile):
        diary_id = insert_diary_sync(
            db_path,
            user_id=alice_profile["id"],
            body="Private paragraph.",
        )
        created = alice.post(
            "/api/story/works/drafts",
            json={
                "kind": "daily_picturebook",
                "source_diary_ids": [diary_id],
                "selected_segments": ["Private paragraph."],
                "title": "No Legacy Retry",
                "style": "pixel",
            },
        )
        job = alice.post(
            f"/api/story/works/{created.json()['id']}/picturebook",
            json={"replace": False},
        ).json()
        with sqlite3.connect(db_path) as db:
            db.execute(
                "UPDATE picturebook_jobs SET status='failed', stage='failed', "
                "error='safe failure' WHERE id=?",
                (job["id"],),
            )
            db.commit()

        retried = alice.post(f"/api/picturebook/{job['id']}/retry")

        assert retried.status_code == 409
        assert spawned == []
        assert fetch_one_sync(
            db_path,
            "SELECT status, stage, error FROM picturebook_jobs WHERE id=?",
            (job["id"],),
        ) == {"status": "failed", "stage": "failed", "error": "safe failure"}


def test_api_work_picturebook_rejects_foreign_state_and_missing_segments(
    workflow_app, monkeypatch
):
    import routers.story_workflow as workflow_router

    async def fake_spawn(job_id, user_id):
        return None

    monkeypatch.setattr(workflow_router, "_spawn_picturebook_job", fake_spawn, raising=False)

    app, db_path = workflow_app
    with registered_clients(app, db_path) as (alice, bob, alice_profile, _bob_profile):
        diary_id = insert_diary_sync(
            db_path,
            user_id=alice_profile["id"],
            body="First paragraph.\n\nSecond paragraph.",
        )
        created = alice.post(
            "/api/story/works/drafts",
            json={
                "kind": "daily_picturebook",
                "source_diary_ids": [diary_id],
                "selected_segments": ["Second paragraph."],
                "title": "Rejects",
                "style": "pixel",
            },
        )
        assert created.status_code == 201
        work_id = created.json()["id"]

        assert bob.post(f"/api/story/works/{work_id}/picturebook").status_code == 404

        with sqlite3.connect(db_path) as db:
            db.execute("UPDATE diaries SET text='First paragraph.' WHERE id=?", (diary_id,))
            db.commit()
        missing = alice.post(f"/api/story/works/{work_id}/picturebook")
        assert missing.status_code == 409

        with sqlite3.connect(db_path) as db:
            db.execute(
                "UPDATE diaries SET text='First paragraph.\n\nSecond paragraph.' "
                "WHERE id=?",
                (diary_id,),
            )
            for status, stage in (
                ("draft", "rendering"),
                ("ready", "ready"),
                ("published", "ready"),
            ):
                db.execute(
                    "UPDATE story_works SET status=?, stage=? WHERE id=?",
                    (status, stage, work_id),
                )
                db.commit()
                rejected = alice.post(f"/api/story/works/{work_id}/picturebook")
                assert rejected.status_code == 409


@pytest.mark.asyncio
async def test_work_picturebook_replace_true_creates_new_attempt_after_terminal(db):
    from services.story_workflow import (
        StoryWorkflowConflict,
        create_daily_picturebook_draft,
        start_work_picturebook_generation,
    )

    await create_account(db, 1)
    diary_id = await insert_diary(db, user_id=1, body="Retry this paragraph.")
    work = await create_daily_picturebook_draft(
        db,
        owner_user_id=1,
        diary_id=diary_id,
        selected_segments=["Retry this paragraph."],
        title="Retry Work",
        style="pixel",
    )

    first = await start_work_picturebook_generation(
        db,
        owner_user_id=1,
        work_id=work["id"],
        replace=False,
    )
    with pytest.raises(StoryWorkflowConflict):
        await start_work_picturebook_generation(
            db,
            owner_user_id=1,
            work_id=work["id"],
            replace=True,
        )

    await db.execute(
        "UPDATE picturebook_jobs SET status='failed', stage='failed' WHERE id=?",
        (first["id"],),
    )
    await db.execute(
        "UPDATE story_works SET stage='render_failed', generation_error='raw failure' "
        "WHERE id=?",
        (work["id"],),
    )
    await db.execute(
        """
        INSERT INTO picturebook_pages (
            job_id, page_index, image_id, caption, image_prompt, status,
            created_at, updated_at
        ) VALUES (?, 0, 'old', 'old caption', 'old prompt', 'ready', ?, ?)
        """,
        (first["id"], "2026-08-08T00:00:00Z", "2026-08-08T00:00:00Z"),
    )
    await db.commit()

    second = await start_work_picturebook_generation(
        db,
        owner_user_id=1,
        work_id=work["id"],
        replace=True,
    )

    assert second["id"] != first["id"]
    assert await fetch_one(
        db,
        "SELECT COUNT(*) AS count FROM picturebook_jobs WHERE work_id=?",
        (work["id"],),
    ) == {"count": 2}
    assert await fetch_one(
        db,
        "SELECT COUNT(*) AS count FROM picturebook_pages WHERE job_id=?",
        (first["id"],),
    ) == {"count": 1}
    assert await fetch_one(
        db,
        "SELECT active_picturebook_job_id, stage FROM story_works WHERE id=?",
        (work["id"],),
    ) == {"active_picturebook_job_id": second["id"], "stage": "rendering"}


@pytest.mark.asyncio
async def test_work_picturebook_mode_change_marks_active_attempt_stale(db):
    from services.story_workflow import (
        StoryWorkflowConflict,
        create_daily_picturebook_draft,
        start_work_picturebook_generation,
    )

    await create_account(db, 1)
    diary_id = await insert_diary(db, user_id=1, body="Mode snapshot paragraph.")
    await db.execute(
        "UPDATE diaries SET emotion_mode=? WHERE id=? AND user_id=?",
        ("real", diary_id, 1),
    )
    await db.commit()
    work = await create_daily_picturebook_draft(
        db,
        owner_user_id=1,
        diary_id=diary_id,
        selected_segments=["Mode snapshot paragraph."],
        title="Mode Snapshot",
        style="pixel",
    )
    first = await start_work_picturebook_generation(
        db,
        owner_user_id=1,
        work_id=work["id"],
    )

    await db.execute(
        "UPDATE picturebook_jobs SET status=?, stage=? "
        "WHERE id=? AND user_id=? AND work_id=?",
        ("failed", "failed", first["id"], 1, work["id"]),
    )
    await db.execute(
        "UPDATE story_works SET stage=? "
        "WHERE id=? AND owner_user_id=? AND active_picturebook_job_id=?",
        ("render_failed", work["id"], 1, first["id"]),
    )
    await db.execute(
        "UPDATE diaries SET emotion_mode=? WHERE id=? AND user_id=?",
        ("imagery", diary_id, 1),
    )
    await db.commit()

    with pytest.raises(StoryWorkflowConflict, match="stale"):
        await start_work_picturebook_generation(
            db,
            owner_user_id=1,
            work_id=work["id"],
        )

    stale = await fetch_one(
        db,
        "SELECT stage, allow_imaginative, source_signature "
        "FROM picturebook_jobs WHERE id=? AND user_id=?",
        (first["id"], 1),
    )
    assert stale["stage"] == "stale"
    assert stale["allow_imaginative"] == 0

    replacement = await start_work_picturebook_generation(
        db,
        owner_user_id=1,
        work_id=work["id"],
        replace=True,
    )
    assert replacement["allow_imaginative"] == 1
    assert replacement["source_signature"] != stale["source_signature"]


@pytest.mark.asyncio
async def test_work_picturebook_worker_uses_immutable_source_and_promotes(db, monkeypatch):
    import routers.picturebook as picturebook_router
    from services.story_workflow import (
        create_daily_picturebook_draft,
        start_work_picturebook_generation,
    )

    seen_adapter_calls = []
    seen_story_sources = []

    async def fake_adapt_for_picturebook(source_text, allow_imaginative):
        seen_adapter_calls.append((source_text, allow_imaginative))
        return f"Adapted: {source_text}"

    async def fake_write_story(source_text, profile_text, style):
        seen_story_sources.append(source_text)
        return {"pages": [{} for _ in range(8)]}

    async def fake_write_page_prompts(story, profile_text, style):
        return {
            "cover": {
                "image_id": "cover",
                "real_event": "cover caption",
                "image_prompt": "cover prompt",
            },
            "pages": [
                {
                    "page": index,
                    "image_id": f"page-{index}",
                    "real_event": f"caption {index}",
                    "image_prompt": f"prompt {index}",
                }
                for index in range(1, 9)
            ],
        }

    async def fake_generate_page_image(prompt, character, api_key=None):
        return PNG_DATA_URL

    monkeypatch.setattr(
        picturebook_router,
        "adapt_for_picturebook",
        fake_adapt_for_picturebook,
    )
    monkeypatch.setattr(picturebook_router, "write_story", fake_write_story)
    monkeypatch.setattr(picturebook_router, "write_page_prompts", fake_write_page_prompts)
    monkeypatch.setattr(picturebook_router, "generate_page_image", fake_generate_page_image)

    await create_account(db, 1)
    diary_id = await insert_diary(db, user_id=1, body="Original paragraph.")
    await db.execute(
        "UPDATE diaries SET emotion_mode=? WHERE id=? AND user_id=?",
        ("imagery", diary_id, 1),
    )
    await db.commit()
    work = await create_daily_picturebook_draft(
        db,
        owner_user_id=1,
        diary_id=diary_id,
        selected_segments=["Original paragraph."],
        title="Immutable",
        style="pixel",
    )
    job = await start_work_picturebook_generation(
        db,
        owner_user_id=1,
        work_id=work["id"],
    )
    await db.execute(
        "UPDATE diaries SET text=? WHERE id=? AND user_id=?",
        ("Mutated paragraph.", diary_id, 1),
    )
    await db.commit()

    await picturebook_router._advance(job["id"], 1)

    assert seen_adapter_calls == [("Original paragraph.", True)]
    assert seen_story_sources == ["Adapted: Original paragraph."]
    promoted = await fetch_one(db, "SELECT * FROM story_works WHERE id=?", (work["id"],))
    assert promoted["status"] == "ready"
    assert promoted["stage"] == "ready"
    assert promoted["picturebook_job_id"] == job["id"]
    assert promoted["active_picturebook_job_id"] is None
    assert promoted["cover_asset_id"]
    assert await fetch_one(
        db,
        "SELECT COUNT(*) AS count FROM work_assets WHERE work_id=?",
        (work["id"],),
    ) == {"count": 9}
    assert await fetch_all(
        db,
        "SELECT ordinal, text FROM work_assets WHERE work_id=? ORDER BY ordinal",
        (work["id"],),
    ) == [
        {"ordinal": 0, "text": "cover caption"},
        *[{"ordinal": index, "text": f"caption {index}"} for index in range(1, 9)],
    ]


@pytest.mark.asyncio
async def test_work_picturebook_worker_uses_snapshotted_mode_after_diary_mutation(
    db, monkeypatch
):
    import routers.picturebook as picturebook_router
    from services.story_workflow import (
        create_daily_picturebook_draft,
        start_work_picturebook_generation,
    )

    adapter_calls = []

    async def fake_adapt_for_picturebook(source_text, allow_imaginative):
        adapter_calls.append((source_text, allow_imaginative))
        return "Adapted immutable mode"

    async def fake_write_story(source_text, profile_text, style):
        return {"pages": [{} for _ in range(8)]}

    async def fake_write_page_prompts(story, profile_text, style):
        return {
            "cover": {
                "image_id": "cover",
                "real_event": "caption",
                "image_prompt": "prompt",
            },
            "pages": [],
        }

    async def fake_render_pending_pages(db, job_id, user_id, character):
        return 1

    monkeypatch.setattr(
        picturebook_router,
        "adapt_for_picturebook",
        fake_adapt_for_picturebook,
    )
    monkeypatch.setattr(picturebook_router, "write_story", fake_write_story)
    monkeypatch.setattr(
        picturebook_router,
        "write_page_prompts",
        fake_write_page_prompts,
    )
    monkeypatch.setattr(
        picturebook_router,
        "_render_pending_pages",
        fake_render_pending_pages,
    )

    await create_account(db, 1)
    diary_id = await insert_diary(db, user_id=1, body="Immutable mode paragraph.")
    await db.execute(
        "UPDATE diaries SET emotion_mode=? WHERE id=? AND user_id=?",
        ("imagery", diary_id, 1),
    )
    await db.commit()
    work = await create_daily_picturebook_draft(
        db,
        owner_user_id=1,
        diary_id=diary_id,
        selected_segments=["Immutable mode paragraph."],
        title="Immutable Mode",
        style="pixel",
    )
    job = await start_work_picturebook_generation(
        db,
        owner_user_id=1,
        work_id=work["id"],
    )
    await db.execute(
        "UPDATE diaries SET emotion_mode=? WHERE id=? AND user_id=?",
        ("real", diary_id, 1),
    )
    await db.commit()

    await picturebook_router._advance(job["id"], 1)

    assert job["allow_imaginative"] == 1
    assert adapter_calls == [("Immutable mode paragraph.", True)]


@pytest.mark.asyncio
async def test_work_picturebook_character_change_marks_attempt_stale(db, monkeypatch):
    import routers.picturebook as picturebook_router
    from services.story_workflow import (
        create_daily_picturebook_draft,
        start_work_picturebook_generation,
    )

    async def fail_if_story_rewritten(*_args, **_kwargs):
        raise AssertionError("stale work-backed jobs must not rewrite story")

    monkeypatch.setattr(picturebook_router, "write_story", fail_if_story_rewritten)

    await create_account(db, 1)
    await db.execute(
        """
        INSERT INTO character_profiles (
            user_id, reference_image_url, character_description, nickname,
            visual_profile, source_type
        ) VALUES (1, '/characters/main/p01.webp', 'warm', 'Nana',
            'fixed profile', 'preset')
        """
    )
    await db.commit()
    diary_id = await insert_diary(db, user_id=1, body="Character paragraph.")
    work = await create_daily_picturebook_draft(
        db,
        owner_user_id=1,
        diary_id=diary_id,
        selected_segments=["Character paragraph."],
        title="Stale Character",
        style="pixel",
    )
    job = await start_work_picturebook_generation(
        db,
        owner_user_id=1,
        work_id=work["id"],
    )

    await db.execute(
        "UPDATE character_profiles SET reference_image_url='/characters/main/p02.webp' "
        "WHERE user_id=1"
    )
    await db.commit()

    await picturebook_router._advance(job["id"], 1)

    assert await fetch_one(
        db,
        "SELECT status, stage FROM picturebook_jobs WHERE id=?",
        (job["id"],),
    ) == {"status": "failed", "stage": "stale"}
    assert await fetch_one(
        db,
        """
        SELECT status, stage, active_picturebook_job_id, picturebook_job_id
        FROM story_works WHERE id=?
        """,
        (work["id"],),
    ) == {
        "status": "draft",
        "stage": "render_failed",
        "active_picturebook_job_id": job["id"],
        "picturebook_job_id": None,
    }


@pytest.mark.asyncio
async def test_direct_diary_picturebook_generation_error_hides_source_and_credentials(
    db, monkeypatch
):
    import routers.picturebook as picturebook_router
    from services.generation_errors import GenerationUpstreamError

    async def fake_adapt_for_picturebook(source_text, allow_imaginative):
        return source_text

    async def fail_write_story(source_text, profile_text, style):
        raise GenerationUpstreamError(
            f"provider echoed {source_text} and credential-marker"
        )

    monkeypatch.setattr(
        picturebook_router,
        "adapt_for_picturebook",
        fake_adapt_for_picturebook,
    )
    monkeypatch.setattr(picturebook_router, "write_story", fail_write_story)

    await create_account(db, 1)
    diary_id = await insert_diary(db, user_id=1, body="PRIVATE-SOURCE-MARKER")
    cursor = await db.execute(
        """
        INSERT INTO picturebook_jobs (
            user_id, diary_id, source_text, source_signature,
            style, status, stage, total_pages, created_at, updated_at
        ) VALUES (?, ?, ?, 'opaque-signature', 'pixel', 'running', 'queued',
            9, ?, ?)
        """,
        (
            1,
            diary_id,
            "PRIVATE-SOURCE-MARKER",
            "2026-08-08T00:00:00Z",
            "2026-08-08T00:00:00Z",
        ),
    )
    await db.commit()

    await picturebook_router._advance(cursor.lastrowid, 1)

    failed = await fetch_one(
        db,
        "SELECT status, error FROM picturebook_jobs WHERE id=?",
        (cursor.lastrowid,),
    )
    assert failed == {
        "status": "failed",
        "error": "生成过程出错了，可以重试",
    }


@pytest.mark.asyncio
async def test_legacy_retry_invalidates_old_generation_cache_and_rebuilds_snapshot(
    db, monkeypatch
):
    import routers.picturebook as picturebook_router

    class SharedConnection:
        def __getattr__(self, name):
            return getattr(db, name)

        async def close(self):
            return None

    adapter_calls = []

    async def shared_db():
        return SharedConnection()

    async def fake_spawn(job_id, user_id):
        return None

    async def fake_adapt_for_picturebook(source_text, allow_imaginative):
        adapter_calls.append((source_text, allow_imaginative))
        return "rebuilt from current snapshot"

    async def fake_write_story(source_text, profile_text, style):
        return {"pages": [{} for _ in range(8)]}

    async def fake_write_page_prompts(story, profile_text, style):
        return {
            "cover": {
                "image_id": "cover",
                "real_event": "rebuilt caption",
                "image_prompt": "rebuilt prompt",
            },
            "pages": [],
        }

    async def fake_render_pending_pages(db, job_id, user_id, character):
        return 0

    monkeypatch.setattr(picturebook_router, "get_db", shared_db)
    monkeypatch.setattr(picturebook_router, "_spawn", fake_spawn)
    monkeypatch.setattr(
        picturebook_router,
        "adapt_for_picturebook",
        fake_adapt_for_picturebook,
    )
    monkeypatch.setattr(picturebook_router, "write_story", fake_write_story)
    monkeypatch.setattr(
        picturebook_router,
        "write_page_prompts",
        fake_write_page_prompts,
    )
    monkeypatch.setattr(
        picturebook_router,
        "_render_pending_pages",
        fake_render_pending_pages,
    )

    await create_account(db, 1)
    diary_id = await insert_diary(db, user_id=1, body="Current retry snapshot.")
    timestamp = "2026-08-08T00:00:00Z"
    cursor = await db.execute(
        """
        INSERT INTO picturebook_jobs (
            user_id, diary_id, style, status, stage, error,
            character_signature, story_json, pages_json, total_pages,
            created_at, updated_at
        ) VALUES (?, ?, 'pixel', 'failed', 'failed', 'old failure',
            'old-character', '{"old_story": true}', '{"old_pages": true}',
            9, ?, ?)
        """,
        (1, diary_id, timestamp, timestamp),
    )
    job_id = cursor.lastrowid
    await db.execute(
        """
        INSERT INTO picturebook_pages (
            job_id, page_index, image_id, image_prompt, status, error,
            created_at, updated_at
        ) VALUES (?, 0, 'old-page', 'old prompt', 'failed', 'old page error', ?, ?)
        """,
        (job_id, timestamp, timestamp),
    )
    await db.commit()

    retried = await picturebook_router.retry_picturebook_job(job_id, None, 1)

    assert retried["status"] == "running"
    invalidated = await fetch_one(
        db,
        "SELECT source_text, source_signature, story_json, pages_json, "
        "character_signature FROM picturebook_jobs WHERE id=?",
        (job_id,),
    )
    source_signature = invalidated.pop("source_signature")
    assert invalidated == {
        "source_text": "Current retry snapshot.",
        "story_json": None,
        "pages_json": None,
        "character_signature": None,
    }
    assert source_signature
    assert await fetch_one(
        db,
        "SELECT COUNT(*) AS count FROM picturebook_pages WHERE job_id=?",
        (job_id,),
    ) == {"count": 0}

    await picturebook_router._advance(job_id, 1)

    assert adapter_calls == [("Current retry snapshot.", False)]
    rebuilt = await fetch_one(
        db,
        "SELECT story_json, pages_json, status FROM picturebook_jobs WHERE id=?",
        (job_id,),
    )
    assert rebuilt["story_json"] is not None
    assert rebuilt["pages_json"] is not None
    assert rebuilt["status"] == "done"


@pytest.mark.asyncio
async def test_direct_diary_picturebook_worker_uses_immutable_source_snapshot(
    db, monkeypatch
):
    import routers.picturebook as picturebook_router

    class SharedConnection:
        def __getattr__(self, name):
            return getattr(db, name)

        async def close(self):
            return None

    adapter_calls = []

    async def fake_adapt_for_picturebook(source_text, allow_imaginative):
        adapter_calls.append((source_text, allow_imaginative))
        return "Adapted direct snapshot"

    async def fake_write_story(source_text, profile_text, style):
        return {"pages": [{} for _ in range(8)]}

    async def fake_write_page_prompts(story, profile_text, style):
        return {
            "cover": {
                "image_id": "cover",
                "real_event": "caption",
                "image_prompt": "prompt",
            },
            "pages": [],
        }

    async def fake_render_pending_pages(db, job_id, user_id, character):
        return 0

    async def shared_db():
        return SharedConnection()

    async def fake_spawn(job_id, user_id):
        return None

    monkeypatch.setattr(
        picturebook_router,
        "adapt_for_picturebook",
        fake_adapt_for_picturebook,
    )
    monkeypatch.setattr(picturebook_router, "write_story", fake_write_story)
    monkeypatch.setattr(
        picturebook_router,
        "write_page_prompts",
        fake_write_page_prompts,
    )
    monkeypatch.setattr(
        picturebook_router,
        "_render_pending_pages",
        fake_render_pending_pages,
    )
    monkeypatch.setattr(picturebook_router, "get_db", shared_db)
    monkeypatch.setattr(picturebook_router, "_spawn", fake_spawn)

    await create_account(db, 1)
    diary_id = await insert_diary(db, user_id=1, body="Original direct snapshot.")
    await db.execute(
        "UPDATE diaries SET emotion_mode=? WHERE id=?",
        ("imagery", diary_id),
    )
    await db.commit()
    job = await picturebook_router.create_picturebook_job(
        diary_id,
        picturebook_router.CreateJobRequest(style="pixel"),
        None,
        1,
    )
    await db.execute(
        "UPDATE diaries SET text=?, draft_text=?, emotion_mode=? WHERE id=?",
        ("Mutated live diary.", "Mutated live draft.", "real", diary_id),
    )
    await db.commit()

    await picturebook_router._advance(job["id"], 1)

    assert adapter_calls == [("Original direct snapshot.", True)]


@pytest.mark.asyncio
async def test_legacy_diary_picturebook_worker_rejects_missing_snapshot_without_live_read(
    db, monkeypatch
):
    import routers.picturebook as picturebook_router

    adapter_calls = []

    async def fake_adapt_for_picturebook(source_text, allow_imaginative):
        adapter_calls.append((source_text, allow_imaginative))
        return "Adapted legacy diary"

    async def fake_write_story(source_text, profile_text, style):
        raise AssertionError("worker must not generate from a missing snapshot")

    async def fake_write_page_prompts(story, profile_text, style):
        return {
            "cover": {
                "image_id": "cover",
                "real_event": "caption",
                "image_prompt": "prompt",
            },
            "pages": [],
        }

    async def fake_render_pending_pages(db, job_id, user_id, character):
        return 0

    monkeypatch.setattr(
        picturebook_router,
        "adapt_for_picturebook",
        fake_adapt_for_picturebook,
    )
    monkeypatch.setattr(picturebook_router, "write_story", fake_write_story)
    monkeypatch.setattr(
        picturebook_router,
        "write_page_prompts",
        fake_write_page_prompts,
    )
    monkeypatch.setattr(
        picturebook_router,
        "_render_pending_pages",
        fake_render_pending_pages,
    )

    await create_account(db, 1)
    diary_id = await insert_diary(db, user_id=1, body="Saved text.")
    await db.execute(
        "UPDATE diaries SET draft_text=?, emotion_mode=? WHERE id=? AND user_id=?",
        ("Saved draft.", "imagery", diary_id, 1),
    )
    cursor = await db.execute(
        """
        INSERT INTO picturebook_jobs (
            user_id, diary_id, style, allow_imaginative, status, stage, total_pages,
            created_at, updated_at
        ) VALUES (?, ?, 'pixel', ?, 'running', 'queued', 9, ?, ?)
        """,
        (1, diary_id, 1, "2026-08-08T00:00:00Z", "2026-08-08T00:00:00Z"),
    )
    await db.execute(
        "UPDATE diaries SET emotion_mode=? WHERE id=? AND user_id=?",
        ("real", diary_id, 1),
    )
    await db.commit()

    await picturebook_router._advance(cursor.lastrowid, 1)

    assert adapter_calls == []
    assert await fetch_one(
        db,
        "SELECT status, stage, error FROM picturebook_jobs WHERE id=?",
        (cursor.lastrowid,),
    ) == {
        "status": "failed",
        "stage": "failed",
        "error": "绘本来源快照不存在，请重新生成",
    }


@pytest.mark.asyncio
async def test_time_story_picturebook_worker_bypasses_daily_adapter(db, monkeypatch):
    import routers.picturebook as picturebook_router
    from services.story_workflow import (
        create_time_story_draft,
        start_work_picturebook_generation,
    )

    story_sources = []

    async def fail_if_adapted(*_args, **_kwargs):
        raise AssertionError("time-story narratives must bypass Prompt 2")

    async def fake_write_story(source_text, profile_text, style):
        story_sources.append(source_text)
        return {"pages": [{} for _ in range(8)]}

    async def fake_write_page_prompts(story, profile_text, style):
        return {
            "cover": {
                "image_id": "cover",
                "real_event": "caption",
                "image_prompt": "prompt",
            },
            "pages": [],
        }

    async def fake_render_pending_pages(db, job_id, user_id, character):
        return 1

    monkeypatch.setattr(
        picturebook_router,
        "adapt_for_picturebook",
        fail_if_adapted,
    )
    monkeypatch.setattr(picturebook_router, "write_story", fake_write_story)
    monkeypatch.setattr(
        picturebook_router,
        "write_page_prompts",
        fake_write_page_prompts,
    )
    monkeypatch.setattr(
        picturebook_router,
        "_render_pending_pages",
        fake_render_pending_pages,
    )

    await create_account(db, 1)
    diary_id = await insert_diary(db, user_id=1, body="Source diary.")
    work = await create_time_story_draft(
        db,
        owner_user_id=1,
        source_diary_ids=[diary_id],
        title="Time Story",
        style="pixel",
    )
    await db.execute(
        "UPDATE story_works SET narrative_text=?, stage=? "
        "WHERE id=? AND owner_user_id=?",
        ("Confirmed time-story narrative.", "narrative_confirmed", work["id"], 1),
    )
    await db.commit()
    job = await start_work_picturebook_generation(
        db,
        owner_user_id=1,
        work_id=work["id"],
    )

    await picturebook_router._advance(job["id"], 1)

    assert story_sources == ["Confirmed time-story narrative."]


@pytest.mark.asyncio
async def test_pointer_cleared_failed_picturebook_rebinds_existing_job(db):
    from services.story_workflow import (
        create_daily_picturebook_draft,
        start_work_picturebook_generation,
    )

    await create_account(db, 1)
    diary_id = await insert_diary(db, user_id=1, body="Rebind this paragraph.")
    work = await create_daily_picturebook_draft(
        db,
        owner_user_id=1,
        diary_id=diary_id,
        selected_segments=["Rebind this paragraph."],
        title="Rebind Work",
        style="pixel",
    )

    first = await start_work_picturebook_generation(
        db,
        owner_user_id=1,
        work_id=work["id"],
        replace=False,
    )
    await db.execute(
        "UPDATE picturebook_jobs SET status='failed', stage='failed', "
        "error='生成过程出错了，可以重试' WHERE id=?",
        (first["id"],),
    )
    await db.execute(
        "UPDATE story_works SET stage='render_failed', "
        "active_picturebook_job_id=NULL, generation_error='生成过程出错了，可以重试' "
        "WHERE id=?",
        (work["id"],),
    )
    await db.execute(
        """
        INSERT INTO picturebook_pages (
            job_id, page_index, image_id, caption, image_prompt, status,
            created_at, updated_at
        ) VALUES (?, 0, 'kept', 'kept caption', 'kept prompt', 'ready', ?, ?)
        """,
        (first["id"], "2026-08-08T00:00:00Z", "2026-08-08T00:00:00Z"),
    )
    await db.commit()

    rebound = await start_work_picturebook_generation(
        db,
        owner_user_id=1,
        work_id=work["id"],
        replace=False,
    )

    assert rebound["id"] == first["id"]
    assert rebound["status"] == "running"
    job = await fetch_one(db, "SELECT * FROM picturebook_jobs WHERE id=?", (first["id"],))
    assert job["status"] == "running"
    assert job["error"] is None
    work_row = await fetch_one(
        db, "SELECT * FROM story_works WHERE id=?", (work["id"],),
    )
    assert work_row["active_picturebook_job_id"] == first["id"]
    assert work_row["stage"] == "rendering"
    pages = await fetch_one(
        db,
        "SELECT * FROM picturebook_pages WHERE job_id=? AND page_index=0",
        (first["id"],),
    )
    assert pages["image_id"] == "kept"
    count = await fetch_one(
        db,
        "SELECT COUNT(*) AS count FROM picturebook_jobs WHERE work_id=?",
        (work["id"],),
    )
    assert count["count"] == 1


@pytest.mark.asyncio
async def test_pointer_cleared_stale_picturebook_starts_fresh_job(db):
    from services.story_workflow import (
        create_daily_picturebook_draft,
        start_work_picturebook_generation,
    )

    await create_account(db, 1)
    diary_id = await insert_diary(db, user_id=1, body="Original paragraph.")
    work = await create_daily_picturebook_draft(
        db,
        owner_user_id=1,
        diary_id=diary_id,
        selected_segments=["Original paragraph."],
        title="Stale Work",
        style="pixel",
    )

    first = await start_work_picturebook_generation(
        db,
        owner_user_id=1,
        work_id=work["id"],
        replace=False,
    )
    await db.execute(
        "UPDATE picturebook_jobs SET status='failed', stage='failed', "
        "source_signature='stale-signature' WHERE id=?",
        (first["id"],),
    )
    await db.execute(
        "UPDATE story_works SET stage='render_failed', "
        "active_picturebook_job_id=NULL WHERE id=?",
        (work["id"],),
    )
    await db.commit()

    fresh = await start_work_picturebook_generation(
        db,
        owner_user_id=1,
        work_id=work["id"],
        replace=False,
    )

    assert fresh["id"] != first["id"]
    old = await fetch_one(db, "SELECT * FROM picturebook_jobs WHERE id=?", (first["id"],))
    assert old["status"] == "failed"
    work_row = await fetch_one(
        db, "SELECT * FROM story_works WHERE id=?", (work["id"],),
    )
    assert work_row["active_picturebook_job_id"] == fresh["id"]


@pytest.mark.asyncio
async def test_pointer_cleared_never_resurrects_older_failed_attempt(db):
    from services.story_workflow import (
        create_daily_picturebook_draft,
        start_work_picturebook_generation,
    )

    await create_account(db, 1)
    diary_id = await insert_diary(db, user_id=1, body="Multi attempt paragraph.")
    work = await create_daily_picturebook_draft(
        db,
        owner_user_id=1,
        diary_id=diary_id,
        selected_segments=["Multi attempt paragraph."],
        title="Multi Work",
        style="pixel",
    )

    latest = await start_work_picturebook_generation(
        db,
        owner_user_id=1,
        work_id=work["id"],
        replace=False,
    )
    await db.execute(
        "UPDATE picturebook_jobs SET status='failed', stage='failed', "
        "updated_at='2026-08-08T12:00:00Z' WHERE id=?",
        (latest["id"],),
    )
    # 更早的一次失败尝试:来源相同但已过时,绝不被复活。
    await db.execute(
        """
        INSERT INTO picturebook_jobs (
            user_id, work_id, source_text, source_signature, style, status,
            stage, error, character_signature, total_pages, created_at, updated_at
        ) SELECT user_id, work_id, source_text, source_signature, style,
            'failed', 'failed', error, character_signature, total_pages,
            '2026-08-08T10:00:00Z', '2026-08-08T11:00:00Z'
        FROM picturebook_jobs WHERE id=?
        """,
        (latest["id"],),
    )
    older = await fetch_one(
        db,
        "SELECT id FROM picturebook_jobs WHERE work_id=? AND id!=?",
        (work["id"], latest["id"]),
    )
    await db.execute(
        "UPDATE story_works SET stage='render_failed', "
        "active_picturebook_job_id=NULL WHERE id=?",
        (work["id"],),
    )
    await db.commit()

    rebound = await start_work_picturebook_generation(
        db,
        owner_user_id=1,
        work_id=work["id"],
        replace=False,
    )

    assert rebound["id"] == latest["id"]
    older_row = await fetch_one(
        db, "SELECT * FROM picturebook_jobs WHERE id=?", (older["id"],),
    )
    assert older_row["status"] == "failed"
