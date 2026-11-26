import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

import database
import migrations
from migrations import MIGRATIONS


NEW_TABLES = {
    "accounts",
    "auth_sessions",
    "rooms",
    "room_members",
    "room_invites",
    "room_posts",
    "post_likes",
    "post_comments",
    "room_temperature_snapshots",
    "media_assets",
    "room_post_media",
    "schema_migrations",
}

ASSET_COLUMNS = {
    "profile": "avatar_asset_id",
    "fragments": "photo_asset_id",
    "images": "asset_id",
    "weekly_comics": "asset_id",
    "dual_timeline_comics": "asset_id",
}

STORY_WORKFLOW_COLUMNS = {
    "kind",
    "stage",
    "source_snapshot_json",
    "source_snapshot_hash",
    "generation_error",
    "active_picturebook_job_id",
    "picturebook_job_id",
    "cover_asset_id",
    "source_start_date",
    "source_end_date",
    "display_start_date",
    "display_end_date",
    "selected_storyline_json",
    "storyline_candidates_json",
    "narrative_text",
    "stage_updated_at",
}

PICTUREBOOK_WORKFLOW_COLUMNS = {
    "diary_id",
    "work_id",
    "source_text",
    "source_signature",
    "allow_imaginative",
}


async def scalar(db, sql, params=()):
    cursor = await db.execute(sql, params)
    row = await cursor.fetchone()
    return row[0]


async def table_names(db):
    cursor = await db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )
    return {row["name"] for row in await cursor.fetchall()}


async def table_columns(db, table):
    cursor = await db.execute(f"PRAGMA table_info({table})")
    return {row["name"]: row for row in await cursor.fetchall()}


async def table_sql(db, table):
    cursor = await db.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
    )
    row = await cursor.fetchone()
    return row["sql"]


def compact(sql):
    return " ".join(sql.split())


async def migration_rows(db):
    cursor = await db.execute(
        "SELECT version, COUNT(*) AS count "
        "FROM schema_migrations GROUP BY version ORDER BY version"
    )
    return [(row["version"], row["count"]) for row in await cursor.fetchall()]


def story_snapshot_hash(snapshot):
    encoded = json.dumps(
        snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


async def legacy_story_snapshot(db, work_id):
    cursor = await db.execute("SELECT * FROM story_works WHERE id=?", (work_id,))
    work = await cursor.fetchone()
    cursor = await db.execute(
        "SELECT * FROM work_assets WHERE work_id=? ORDER BY ordinal ASC", (work_id,)
    )
    return {
        "id": work["id"],
        "title": work["title"],
        "medium": work["medium"],
        "narrative_mode": work["narrative_mode"],
        "style": work["style"],
        "assets": [dict(row) for row in await cursor.fetchall()],
        "selected_segments": json.loads(work["selected_segments_json"]),
    }


async def remove_personal_space_migration(db):
    await db.execute("DROP TABLE IF EXISTS work_responses")
    await db.execute("DROP TABLE IF EXISTS work_audience")
    await db.execute("DELETE FROM schema_migrations WHERE version=6")
    # Also roll back integrated publication artifacts so the upgrade path replays.
    await db.execute("DROP TABLE IF EXISTS work_likes")
    await db.execute("DROP TABLE IF EXISTS work_comments")
    await db.execute("DELETE FROM schema_migrations WHERE version IN (11, 12)")
    await db.commit()


async def seed_story_identity(db):
    await db.executemany(
        "INSERT INTO profile (id, nickname) VALUES (?, ?)",
        [
            (1, "owner"),
            (2, "subscriber-100"),
            (3, "subscriber-101"),
            (4, "subscriber-102"),
            (5, "subscriber-103"),
            (6, "subscriber-104"),
            (7, "subscriber-105"),
            (8, "subscriber-106"),
            (9, "other"),
        ],
    )
    await db.executemany(
        "INSERT INTO accounts (user_id, username_norm, password_hash) VALUES (?, ?, ?)",
        [
            (1, "owner", "not-a-real-hash"),
            (2, "subscriber-100", "not-a-real-hash"),
            (3, "subscriber-101", "not-a-real-hash"),
            (4, "subscriber-102", "not-a-real-hash"),
            (5, "subscriber-103", "not-a-real-hash"),
            (6, "subscriber-104", "not-a-real-hash"),
            (7, "subscriber-105", "not-a-real-hash"),
            (8, "subscriber-106", "not-a-real-hash"),
            (9, "other", "not-a-real-hash"),
        ],
    )
    await db.executemany(
        """
        INSERT INTO subscriptions (
            id, owner_user_id, subscriber_user_id, status, created_at, revoked_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            (100, 1, 2, "active", "2026-08-01T00:00:00+00:00", None),
            (101, 1, 3, "active", "2026-08-01T00:01:00+00:00", None),
            (102, 1, 4, "active", "2026-08-01T00:02:00+00:00", None),
            (
                103,
                1,
                5,
                "active",
                "2026-08-01T00:03:00+00:00",
                None,
            ),
            (
                104,
                1,
                6,
                "revoked",
                "2026-08-01T00:04:00+00:00",
                "2026-08-02T00:00:00+00:00",
            ),
            (105, 1, 7, "active", "2026-08-01T00:05:00+00:00", None),
            (106, 1, 8, "active", "2026-08-01T00:06:00+00:00", None),
        ],
    )
    for work_id in range(10, 17):
        await db.execute(
            """
            INSERT INTO story_works (
                id, owner_user_id, title, medium, narrative_mode, style,
                selected_segments_json, status, created_at, updated_at
            ) VALUES (?, 1, ?, 'picture_book', 'true_record', 'watercolor',
                ?, 'published', ?, ?)
            """,
            (
                work_id,
                f"story-{work_id}",
                json.dumps([f"segment-{work_id}"], ensure_ascii=False),
                f"2026-08-01T01:{work_id}:00+00:00",
                f"2026-08-01T01:{work_id}:00+00:00",
            ),
        )
        await db.execute(
            """
            INSERT INTO work_assets (
                id, work_id, ordinal, asset_type, url, asset_id, text, prompt, created_at
            ) VALUES (?, ?, 0, 'text', NULL, NULL, ?, ?, ?)
            """,
            (
                1000 + work_id,
                work_id,
                f"segment-{work_id}",
                "render prompt",
                f"2026-08-01T02:{work_id}:00+00:00",
            ),
        )
    await db.commit()


async def reset_story_workflow_to_v8(db):
    await db.commit()
    await db.execute("PRAGMA foreign_keys = OFF")
    try:
        await db.execute("DROP TABLE IF EXISTS story_work_diaries")
        await db.execute("DROP TABLE IF EXISTS _story_works_v8")
        await db.execute(
            """
            CREATE TABLE _story_works_v8 (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_user_id INTEGER NOT NULL REFERENCES accounts(user_id) ON DELETE CASCADE,
                source_diary_id INTEGER REFERENCES diaries(id) ON DELETE SET NULL,
                title TEXT NOT NULL,
                medium TEXT NOT NULL
                    CHECK (medium IN ('picture_book', 'comic', 'motion_comic', 'weekly')),
                narrative_mode TEXT NOT NULL,
                style TEXT NOT NULL,
                selected_segments_json TEXT NOT NULL,
                forbidden_content TEXT,
                render_prompt TEXT,
                status TEXT NOT NULL DEFAULT 'draft'
                    CHECK (status IN ('draft', 'ready', 'published', 'failed')),
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        await db.execute(
            """
            INSERT INTO _story_works_v8 (
                id, owner_user_id, source_diary_id, title, medium, narrative_mode,
                style, selected_segments_json, forbidden_content, render_prompt,
                status, created_at, updated_at
            )
            SELECT
                id, owner_user_id, source_diary_id, title, medium, narrative_mode,
                style, selected_segments_json, forbidden_content, render_prompt,
                status, created_at, updated_at
            FROM story_works
            """
        )
        await db.execute("DROP TABLE story_works")
        await db.execute("ALTER TABLE _story_works_v8 RENAME TO story_works")
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_story_works_owner "
            "ON story_works(owner_user_id, created_at DESC)"
        )

        await db.execute("DROP TABLE IF EXISTS _picturebook_jobs_v8")
        await db.execute(
            """
            CREATE TABLE _picturebook_jobs_v8 (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                diary_id INTEGER NOT NULL,
                style TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                stage TEXT NOT NULL DEFAULT 'queued',
                error TEXT,
                character_signature TEXT,
                story_json TEXT,
                pages_json TEXT,
                total_pages INTEGER NOT NULL DEFAULT 9,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        await db.execute(
            """
            INSERT INTO _picturebook_jobs_v8 (
                id, user_id, diary_id, style, status, stage, error,
                character_signature, story_json, pages_json, total_pages,
                created_at, updated_at
            )
            SELECT
                id, user_id, diary_id, style, status, stage, error,
                character_signature, story_json, pages_json, total_pages,
                created_at, updated_at
            FROM picturebook_jobs
            WHERE diary_id IS NOT NULL
            """
        )
        await db.execute("DROP TABLE picturebook_jobs")
        await db.execute("ALTER TABLE _picturebook_jobs_v8 RENAME TO picturebook_jobs")
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_picturebook_jobs_diary "
            "ON picturebook_jobs(diary_id, user_id)"
        )
        await db.execute("DELETE FROM schema_migrations WHERE version IN (9, 10)")
        await db.commit()
    finally:
        await db.execute("PRAGMA foreign_keys = ON")


async def seed_story_workflow_history(db):
    await db.execute(
        "INSERT INTO profile (id, nickname) VALUES (901, 'workflow-owner')"
    )
    await db.execute(
        "INSERT INTO accounts (user_id, username_norm, password_hash) "
        "VALUES (901, 'workflow-owner', 'not-a-real-hash')"
    )
    await db.execute(
        """
        INSERT INTO diaries (
            id, date, text, status, source, user_id, created_at
        ) VALUES (
            902, '2026-08-04', 'historical diary', 'confirmed', 'manual', 901,
            '2026-08-04T08:00:00+00:00'
        )
        """
    )
    await db.execute(
        """
        INSERT INTO story_works (
            id, owner_user_id, source_diary_id, title, medium, narrative_mode,
            style, selected_segments_json, status, created_at, updated_at
        ) VALUES (
            903, 901, 902, 'historical story', 'picture_book', 'true_record',
            'watercolor', '["segment"]', 'ready',
            '2026-08-05T09:00:00+00:00',
            '2026-08-05T09:01:00+00:00'
        )
        """
    )
    await db.execute(
        """
        INSERT INTO picturebook_jobs (
            id, user_id, diary_id, style, status, stage, error,
            character_signature, story_json, pages_json, total_pages,
            created_at, updated_at
        ) VALUES (
            904, 901, 902, 'watercolor', 'ready', 'done', NULL,
            'character-hash', '{"title":"old"}', '[{"page":1}]', 9,
            '2026-08-05T10:00:00+00:00',
            '2026-08-05T10:09:00+00:00'
        )
        """
    )
    await db.executemany(
        """
        INSERT INTO picturebook_pages (
            id, job_id, page_index, image_id, caption, image_prompt,
            asset_id, image_url, status, error, created_at, updated_at
        ) VALUES (?, 904, ?, ?, ?, ?, ?, ?, 'ready', NULL, ?, ?)
        """,
        [
            (
                910 + index,
                index,
                f"image-{index}",
                f"caption-{index}",
                f"prompt-{index}",
                f"asset-{index}",
                f"/uploads/page-{index}.png",
                f"2026-08-05T10:0{index}:00+00:00",
                f"2026-08-05T10:1{index}:00+00:00",
            )
            for index in range(9)
        ],
    )
    await db.commit()


async def seed_story_workflow_job_only_history(db):
    await db.execute(
        "INSERT INTO profile (id, nickname) VALUES (931, 'job-only-owner')"
    )
    await db.execute(
        "INSERT INTO accounts (user_id, username_norm, password_hash) "
        "VALUES (931, 'job-only-owner', 'not-a-real-hash')"
    )
    await db.execute(
        """
        INSERT INTO diaries (
            id, date, text, status, source, user_id, created_at
        ) VALUES (
            932, '2026-08-06', 'job only diary', 'confirmed', 'manual', 931,
            '2026-08-06T08:00:00+00:00'
        )
        """
    )
    await db.execute(
        """
        INSERT INTO picturebook_jobs (
            id, user_id, diary_id, style, status, stage, error,
            character_signature, story_json, pages_json, total_pages,
            created_at, updated_at
        ) VALUES (
            933, 931, 932, 'ink', 'ready', 'done', NULL,
            'job-only-character', '{"title":"job only"}', '[{"page":1}]', 9,
            '2026-08-06T10:00:00+00:00',
            '2026-08-06T10:09:00+00:00'
        )
        """
    )
    await db.executemany(
        """
        INSERT INTO picturebook_pages (
            id, job_id, page_index, image_id, caption, image_prompt,
            asset_id, image_url, status, error, created_at, updated_at
        ) VALUES (?, 933, ?, ?, ?, ?, ?, ?, 'ready', NULL, ?, ?)
        """,
        [
            (
                934 + index,
                index,
                f"job-only-image-{index}",
                f"job-only-caption-{index}",
                f"job-only-prompt-{index}",
                f"job-only-asset-{index}",
                f"/uploads/job-only-{index}.png",
                f"2026-08-06T10:0{index}:00+00:00",
                f"2026-08-06T10:1{index}:00+00:00",
            )
            for index in range(3)
        ],
    )
    await db.commit()


async def seed_story_workflow_missing_diary_history(db):
    await db.execute(
        "INSERT INTO profile (id, nickname) VALUES (941, 'missing-diary-owner')"
    )
    await db.execute(
        "INSERT INTO accounts (user_id, username_norm, password_hash) "
        "VALUES (941, 'missing-diary-owner', 'not-a-real-hash')"
    )
    await db.execute(
        """
        INSERT INTO story_works (
            id, owner_user_id, source_diary_id, title, medium, narrative_mode,
            style, selected_segments_json, status, created_at, updated_at
        ) VALUES (
            942, 941, NULL, 'missing diary story', 'picture_book',
            'true_record', 'watercolor', '["segment"]', 'ready',
            '2026-08-07T09:00:00+00:00',
            '2026-08-07T09:01:00+00:00'
        )
        """
    )
    await db.commit()


@pytest.mark.asyncio
async def test_resonance_v11_adds_publication_and_interaction_schema(db):
    await database.init_db(db)
    work_columns = await table_columns(db, "story_works")
    assert {"published_at", "unpublished_at"} <= set(work_columns)
    assert {"work_likes", "work_comments"} <= await table_names(db)
    comments_sql = compact(await table_sql(db, "work_comments"))
    assert "UNIQUE (work_id, author_user_id, client_request_id)" in comments_sql
    likes_sql = compact(await table_sql(db, "work_likes"))
    assert "UNIQUE (work_id, viewer_user_id)" in likes_sql
    assert await scalar(db, "SELECT MAX(version) FROM schema_migrations") == max(
        version for version, _name, _migration in MIGRATIONS
    )


@pytest.mark.asyncio
async def test_v11_backfills_publication_conservatively(db):
    # simulate a v10 database: drop integrated artifacts and remove v11/v12 markers
    await db.execute("PRAGMA foreign_keys = OFF")
    await db.execute("DROP TABLE IF EXISTS work_likes")
    await db.execute("DROP TABLE IF EXISTS work_comments")
    # rebuild story_works without published_at/unpublished_at
    await db.execute(
        """
        CREATE TABLE _story_works_v10 (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_user_id INTEGER NOT NULL REFERENCES accounts(user_id) ON DELETE CASCADE,
            source_diary_id INTEGER REFERENCES diaries(id) ON DELETE SET NULL,
            title TEXT NOT NULL,
            medium TEXT NOT NULL
                CHECK (medium IN ('picture_book', 'comic', 'motion_comic', 'weekly')),
            narrative_mode TEXT NOT NULL,
            style TEXT NOT NULL,
            selected_segments_json TEXT NOT NULL,
            forbidden_content TEXT,
            render_prompt TEXT,
            status TEXT NOT NULL DEFAULT 'draft'
                CHECK (status IN ('draft', 'ready', 'published', 'failed')),
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    await db.execute(
        """
        INSERT INTO _story_works_v10 (
            id, owner_user_id, title, medium, narrative_mode, style,
            selected_segments_json, status, created_at, updated_at
        )
        SELECT id, owner_user_id, title, medium, narrative_mode, style,
               selected_segments_json, status, created_at, updated_at
        FROM story_works
        """
    )
    await db.execute("DROP TABLE story_works")
    await db.execute("ALTER TABLE _story_works_v10 RENAME TO story_works")
    await db.execute("DELETE FROM schema_migrations WHERE version IN (11, 12)")
    await db.execute("PRAGMA foreign_keys = ON")
    await db.commit()

    await db.execute(
        "INSERT INTO profile (id, nickname) "
        "VALUES (1, 'owner'), (2, 'viewer'), (3, 'v3'), (4, 'v4'), (5, 'v5')"
    )
    await db.execute(
        "INSERT INTO accounts (user_id, username_norm, password_hash) "
        "VALUES (1, 'owner', 'h'), (2, 'viewer', 'h'), (3, 'v3', 'h'), "
        "(4, 'v4', 'h'), (5, 'v5', 'h')"
    )
    # one subscription per distinct subscriber
    for sub_id, subscriber in ((100, 2), (101, 3), (102, 4), (103, 5)):
        await db.execute(
            """
            INSERT INTO subscriptions (id, owner_user_id, subscriber_user_id, status, created_at)
            VALUES (?, 1, ?, 'active', '2026-08-01T00:00:00+00:00')
            """,
            (sub_id, subscriber),
        )
    works = [
        (10, "ready", "2026-08-01T01:00:00+00:00", "2026-08-01T01:00:00+00:00"),
        (11, "ready", "2026-08-01T02:00:00+00:00", "2026-08-01T02:00:00+00:00"),
        (12, "ready", "2026-08-01T03:00:00+00:00", "2026-08-01T03:00:00+00:00"),
        (13, "published", "2026-08-01T04:00:00+00:00", "2026-08-01T04:30:00+00:00"),
        (14, "ready", "2026-08-01T05:00:00+00:00", "2026-08-01T05:00:00+00:00"),
    ]
    for work_id, status, created_at, updated_at in works:
        await db.execute(
            """
            INSERT INTO story_works (
                id, owner_user_id, title, medium, narrative_mode, style,
                selected_segments_json, status, created_at, updated_at
            ) VALUES (?, 1, ?, 'picture_book', 'true_record', 'watercolor',
                '[]', ?, ?, ?)
            """,
            (work_id, f"work-{work_id}", status, created_at, updated_at),
        )
    # work 10: revoked (earlier) + active (later, with +08:00 offset)
    await db.execute(
        """
        INSERT INTO work_audience (work_id, subscription_id, status, granted_at, revoked_at, created_at)
        VALUES (10, 100, 'revoked', '2026-08-01 09:00:00', '2026-08-01T10:00:00+00:00', '2026-08-01 09:00:00')
        """
    )
    await db.execute(
        """
        INSERT INTO work_audience (work_id, subscription_id, status, granted_at, created_at)
        VALUES (10, 101, 'active', '2026-08-02T10:00:00+08:00', '2026-08-02T10:00:00+08:00')
        """
    )
    # work 11: only revoked audience -> stays ready
    await db.execute(
        """
        INSERT INTO work_audience (work_id, subscription_id, status, granted_at, revoked_at, created_at)
        VALUES (11, 102, 'revoked', '2026-08-01T11:00:00+00:00', '2026-08-01T12:00:00+00:00', '2026-08-01T11:00:00+00:00')
        """
    )
    # work 12: no audience -> stays ready
    # work 13: already published, no audience -> fallback to updated_at
    # work 14: active audience with unparseable granted_at -> fallback to updated_at
    await db.execute(
        """
        INSERT INTO work_audience (work_id, subscription_id, status, granted_at, created_at)
        VALUES (14, 103, 'active', 'not-a-timestamp', 'not-a-timestamp')
        """
    )
    # active text response on work 10 migrates; seen-only does not
    await db.execute(
        """
        INSERT INTO work_responses (
            id, work_id, author_user_id, seen_at, body_kind, body, created_at, updated_at, deleted_at
        ) VALUES (
            'r1', 10, 3, NULL, 'text', '好看', '2026-08-02T11:00:00+00:00',
            '2026-08-02T11:00:00+00:00', NULL
        )
        """
    )
    await db.execute(
        """
        INSERT INTO work_responses (
            id, work_id, author_user_id, seen_at, created_at, updated_at
        ) VALUES (
            'r2', 12, 2, '2026-08-02T12:00:00+00:00', '2026-08-02T12:00:00+00:00',
            '2026-08-02T12:00:00+00:00'
        )
        """
    )
    # response on revoked-only work 11 does not migrate (work stays ready)
    await db.execute(
        """
        INSERT INTO work_responses (
            id, work_id, author_user_id, seen_at, body_kind, body, created_at, updated_at, deleted_at
        ) VALUES (
            'r3', 11, 2, NULL, 'text', '已删', '2026-08-01T13:00:00+00:00',
            '2026-08-01T13:00:00+00:00', NULL
        )
        """
    )
    await db.commit()

    await database.init_db(db)

    cursor = await db.execute(
        "SELECT id, status, published_at FROM story_works ORDER BY id"
    )
    migrated = {row["id"]: dict(row) for row in await cursor.fetchall()}
    assert migrated[10]["status"] == "published"
    assert migrated[10]["published_at"] == "2026-08-01T09:00:00+00:00"
    assert migrated[11]["status"] == "ready"
    assert migrated[11]["published_at"] is None
    assert migrated[12]["status"] == "ready"
    assert migrated[12]["published_at"] is None
    assert migrated[13]["status"] == "published"
    assert migrated[13]["published_at"] == "2026-08-01T04:30:00+00:00"
    assert migrated[14]["status"] == "published"
    assert migrated[14]["published_at"] == "2026-08-01T05:00:00+00:00"

    # only the active text response on a published work migrated
    assert await scalar(db, "SELECT COUNT(*) FROM work_comments") == 1
    assert await scalar(
        db, "SELECT body FROM work_comments WHERE work_id=10"
    ) == "好看"
    # idempotency: re-running migrations does not duplicate comments
    await database.init_db(db)
    assert await scalar(db, "SELECT COUNT(*) FROM work_comments") == 1


@pytest.mark.asyncio
async def test_fresh_database_uses_isolated_configured_path(db, tmp_path):
    cursor = await db.execute("PRAGMA database_list")
    files = [Path(row["file"]).resolve() for row in await cursor.fetchall() if row["file"]]
    assert files == [(tmp_path / "fresh.sqlite3").resolve()]
    assert await scalar(db, "PRAGMA foreign_keys") == 1
    busy_timeout = await scalar(db, "PRAGMA busy_timeout")
    assert 0 < busy_timeout <= 10_000


@pytest.mark.asyncio
async def test_fresh_database_has_account_room_and_media_schema(db):
    assert NEW_TABLES <= await table_names(db)

    for table, column in ASSET_COLUMNS.items():
        cursor = await db.execute(f"PRAGMA table_info({table})")
        assert column in {row["name"] for row in await cursor.fetchall()}


@pytest.mark.asyncio
async def test_personal_space_access_schema_constraints_and_indexes(db):
    assert {"work_audience", "work_responses"} <= await table_names(db)
    assert await scalar(db, "SELECT MAX(version) FROM schema_migrations") == max(
        version for version, _name, _migration in MIGRATIONS
    )

    audience_sql = await table_sql(db, "work_audience")
    response_sql = await table_sql(db, "work_responses")
    assert "UNIQUE (work_id, subscription_id)" in compact(audience_sql)
    assert "UNIQUE (work_id, author_user_id)" in compact(response_sql)
    assert "body_kind = 'text'" in response_sql
    assert "deleted_at IS NOT NULL OR seen_at IS NOT NULL OR body IS NOT NULL" in compact(
        response_sql
    )

    for index_name in ("idx_work_audience_feed", "idx_work_responses_owner"):
        assert await scalar(
            db,
            "SELECT COUNT(*) FROM sqlite_master WHERE type='index' AND name=?",
            (index_name,),
        ) == 1
    for index_name, columns in {
        "idx_work_audience_feed": [
            "subscription_id",
            "status",
            "granted_at",
            "work_id",
        ],
        "idx_work_responses_owner": [
            "work_id",
            "deleted_at",
            "updated_at",
            "id",
        ],
    }.items():
        cursor = await db.execute(f"PRAGMA index_info({index_name})")
        assert [row["name"] for row in await cursor.fetchall()] == columns

    await seed_story_identity(db)
    await db.execute(
        """
        INSERT INTO work_audience (
            work_id, subscription_id, status, granted_at, created_at
        ) VALUES (
            10, 100, 'active',
            '2026-08-01T03:00:00+00:00',
            '2026-08-01T03:00:00+00:00'
        )
        """
    )
    with pytest.raises(sqlite3.IntegrityError):
        await db.execute(
            """
            INSERT INTO work_audience (
                work_id, subscription_id, status, granted_at, created_at
            ) VALUES (
                10, 100, 'active',
                '2026-08-01T03:00:00+00:00',
                '2026-08-01T03:00:00+00:00'
            )
            """
        )
    with pytest.raises(sqlite3.IntegrityError):
        await db.execute(
            """
            INSERT INTO work_audience (
                work_id, subscription_id, status, granted_at, revoked_at, created_at
            ) VALUES (
                11, 101, 'active',
                '2026-08-01T03:01:00+00:00',
                '2026-08-01T03:02:00+00:00',
                '2026-08-01T03:01:00+00:00'
            )
            """
        )
    with pytest.raises(sqlite3.IntegrityError):
        await db.execute(
            """
            INSERT INTO work_audience (
                work_id, subscription_id, status, granted_at, created_at
            ) VALUES (
                11, 101, 'revoked',
                '2026-08-01T03:03:00+00:00',
                '2026-08-01T03:03:00+00:00'
            )
            """
        )

    await db.execute(
        """
        INSERT INTO work_responses (
            id, work_id, author_user_id, seen_at, body_kind, body,
            created_at, updated_at
        ) VALUES (
            'response-10', 10, 2, '2026-08-01T04:00:00+00:00',
            'text', '收到',
            '2026-08-01T04:00:00+00:00',
            '2026-08-01T04:01:00+00:00'
        )
        """
    )
    with pytest.raises(sqlite3.IntegrityError):
        await db.execute(
            """
            INSERT INTO work_responses (
                id, work_id, author_user_id, seen_at, created_at, updated_at
            ) VALUES (
                'duplicate-author', 10, 2,
                '2026-08-01T04:02:00+00:00',
                '2026-08-01T04:02:00+00:00',
                '2026-08-01T04:02:00+00:00'
            )
            """
        )
    with pytest.raises(sqlite3.IntegrityError):
        await db.execute(
            """
            INSERT INTO work_responses (
                id, work_id, author_user_id, body_kind, body, created_at, updated_at
            ) VALUES (
                'bad-empty', 11, 3, NULL, NULL,
                '2026-08-01T04:03:00+00:00',
                '2026-08-01T04:03:00+00:00'
            )
            """
        )
    with pytest.raises(sqlite3.IntegrityError):
        await db.execute(
            """
            INSERT INTO work_responses (
                id, work_id, author_user_id, body_kind, body, created_at, updated_at
            ) VALUES (
                'bad-body-kind', 11, 3, 'emoji', '🙂',
                '2026-08-01T04:04:00+00:00',
                '2026-08-01T04:04:00+00:00'
            )
            """
        )


@pytest.mark.asyncio
async def test_story_workflow_preserves_version_8_history(db):
    await reset_story_workflow_to_v8(db)
    await seed_story_workflow_history(db)

    await database.init_db(db)

    assert await scalar(db, "SELECT COUNT(*) FROM story_works") == 1
    assert await scalar(db, "SELECT COUNT(*) FROM picturebook_jobs") == 1
    assert await scalar(db, "SELECT COUNT(*) FROM picturebook_pages") == 9

    cursor = await db.execute(
        """
        SELECT
            id, source_diary_id, source_start_date, source_end_date,
            display_start_date, display_end_date
        FROM story_works
        WHERE id = 903
        """
    )
    story_work = await cursor.fetchone()
    assert dict(story_work) == {
        "id": 903,
        "source_diary_id": 902,
        "source_start_date": "2026-08-04",
        "source_end_date": "2026-08-04",
        "display_start_date": "2026-08-04",
        "display_end_date": "2026-08-04",
    }

    cursor = await db.execute(
        """
        SELECT
            id, user_id, diary_id, work_id, style, status, stage,
            character_signature, story_json, pages_json, total_pages,
            source_text, source_signature, allow_imaginative, created_at, updated_at
        FROM picturebook_jobs
        WHERE id = 904
        """
    )
    job = dict(await cursor.fetchone())
    assert job == {
        "id": 904,
        "user_id": 901,
        "diary_id": 902,
        "work_id": None,
        "style": "watercolor",
        "status": "ready",
        "stage": "done",
        "character_signature": "character-hash",
        "story_json": '{"title":"old"}',
        "pages_json": '[{"page":1}]',
        "total_pages": 9,
        "source_text": None,
        "source_signature": None,
        "allow_imaginative": 0,
        "created_at": "2026-08-05T10:00:00+00:00",
        "updated_at": "2026-08-05T10:09:00+00:00",
    }

    cursor = await db.execute(
        "SELECT id, job_id, page_index FROM picturebook_pages ORDER BY page_index"
    )
    assert [(row["id"], row["job_id"], row["page_index"]) for row in await cursor.fetchall()] == [
        (910 + index, 904, index) for index in range(9)
    ]


@pytest.mark.asyncio
async def test_story_workflow_preserves_job_only_historical_picturebooks(db):
    await reset_story_workflow_to_v8(db)
    await seed_story_workflow_job_only_history(db)

    await database.init_db(db)

    assert await scalar(db, "SELECT COUNT(*) FROM story_works") == 0
    cursor = await db.execute(
        """
        SELECT id, user_id, diary_id, work_id, style, status, stage
        FROM picturebook_jobs
        WHERE id = 933
        """
    )
    assert dict(await cursor.fetchone()) == {
        "id": 933,
        "user_id": 931,
        "diary_id": 932,
        "work_id": None,
        "style": "ink",
        "status": "ready",
        "stage": "done",
    }
    cursor = await db.execute(
        "SELECT id, job_id, page_index FROM picturebook_pages ORDER BY page_index"
    )
    assert [(row["id"], row["job_id"], row["page_index"]) for row in await cursor.fetchall()] == [
        (934 + index, 933, index) for index in range(3)
    ]


@pytest.mark.asyncio
async def test_story_workflow_backfills_historical_dates_from_created_at_without_diary(db):
    await reset_story_workflow_to_v8(db)
    await seed_story_workflow_missing_diary_history(db)

    await database.init_db(db)

    cursor = await db.execute(
        """
        SELECT
            source_start_date, source_end_date, display_start_date, display_end_date
        FROM story_works
        WHERE id = 942
        """
    )
    assert dict(await cursor.fetchone()) == {
        "source_start_date": "2026-08-07",
        "source_end_date": "2026-08-07",
        "display_start_date": "2026-08-07",
        "display_end_date": "2026-08-07",
    }


@pytest.mark.asyncio
async def test_story_workflow_fresh_database_has_schema_constraints_and_indexes(db):
    assert "story_work_diaries" in await table_names(db)
    story_columns = await table_columns(db, "story_works")
    assert STORY_WORKFLOW_COLUMNS <= set(story_columns)

    diary_work_sql = compact(await table_sql(db, "story_work_diaries"))
    assert "PRIMARY KEY (work_id, diary_id)" in diary_work_sql
    assert "UNIQUE (work_id, ordinal)" in diary_work_sql
    assert "REFERENCES story_works(id) ON DELETE CASCADE" in diary_work_sql
    assert "REFERENCES diaries(id) ON DELETE CASCADE" in diary_work_sql

    job_columns = await table_columns(db, "picturebook_jobs")
    assert PICTUREBOOK_WORKFLOW_COLUMNS <= set(job_columns)
    assert job_columns["diary_id"]["notnull"] == 0
    assert job_columns["work_id"]["notnull"] == 0
    assert job_columns["allow_imaginative"]["notnull"] == 1
    assert job_columns["allow_imaginative"]["dflt_value"] == "0"

    job_sql = compact(await table_sql(db, "picturebook_jobs"))
    assert "CHECK ((diary_id IS NOT NULL) != (work_id IS NOT NULL))" in job_sql

    cursor = await db.execute("PRAGMA index_info(idx_picturebook_jobs_work)")
    assert [row["name"] for row in await cursor.fetchall()] == ["work_id", "user_id"]


@pytest.mark.asyncio
async def test_picturebook_jobs_require_exactly_one_source(db):
    await db.execute(
        """
        INSERT INTO picturebook_jobs (
            user_id, diary_id, work_id, style, created_at, updated_at
        ) VALUES (
            1, 902, NULL, 'watercolor',
            '2026-08-05T11:00:00+00:00',
            '2026-08-05T11:00:00+00:00'
        )
        """
    )
    await db.execute(
        """
        INSERT INTO picturebook_jobs (
            user_id, diary_id, work_id, style, created_at, updated_at
        ) VALUES (
            1, NULL, 903, 'watercolor',
            '2026-08-05T11:01:00+00:00',
            '2026-08-05T11:01:00+00:00'
        )
        """
    )
    with pytest.raises(sqlite3.IntegrityError):
        await db.execute(
            """
            INSERT INTO picturebook_jobs (
                user_id, diary_id, work_id, style, created_at, updated_at
            ) VALUES (
                1, 902, 903, 'watercolor',
                '2026-08-05T11:02:00+00:00',
                '2026-08-05T11:02:00+00:00'
            )
            """
        )
    with pytest.raises(sqlite3.IntegrityError):
        await db.execute(
            """
            INSERT INTO picturebook_jobs (
                user_id, diary_id, work_id, style, created_at, updated_at
            ) VALUES (
                1, NULL, NULL, 'watercolor',
                '2026-08-05T11:03:00+00:00',
                '2026-08-05T11:03:00+00:00'
            )
            """
        )


@pytest.mark.asyncio
async def test_story_work_diary_ordinals_are_unique_per_work(db):
    await db.execute("INSERT INTO profile (id, nickname) VALUES (921, 'ordinal')")
    await db.execute(
        "INSERT INTO accounts (user_id, username_norm, password_hash) "
        "VALUES (921, 'ordinal', 'not-a-real-hash')"
    )
    await db.executemany(
        "INSERT INTO diaries (id, date, text, user_id) VALUES (?, ?, ?, 921)",
        [
            (922, "2026-08-01", "one"),
            (923, "2026-08-02", "two"),
        ],
    )
    await db.execute(
        """
        INSERT INTO story_works (
            id, owner_user_id, title, medium, narrative_mode, style,
            selected_segments_json, status, created_at, updated_at
        ) VALUES (
            924, 921, 'ordinal story', 'picture_book', 'true_record',
            'watercolor', '[]', 'draft',
            '2026-08-02T10:00:00+00:00',
            '2026-08-02T10:00:00+00:00'
        )
        """
    )
    await db.execute(
        "INSERT INTO story_work_diaries (work_id, diary_id, ordinal) "
        "VALUES (924, 922, 0)"
    )
    await db.execute(
        "INSERT INTO story_work_diaries (work_id, diary_id, ordinal) "
        "VALUES (924, 923, 1)"
    )

    with pytest.raises(sqlite3.IntegrityError):
        await db.execute(
            "INSERT INTO story_work_diaries (work_id, diary_id, ordinal) "
            "VALUES (924, 922, 2)"
        )
    with pytest.raises(sqlite3.IntegrityError):
        await db.execute(
            "INSERT INTO story_work_diaries (work_id, diary_id, ordinal) "
            "VALUES (924, 923, 0)"
        )


@pytest.mark.asyncio
async def test_deleting_work_does_not_delete_historical_diary_picturebook_job(db):
    await reset_story_workflow_to_v8(db)
    await seed_story_workflow_history(db)
    await database.init_db(db)

    await db.execute("DELETE FROM story_works WHERE id = 903")

    assert await scalar(
        db,
        "SELECT COUNT(*) FROM picturebook_jobs "
        "WHERE id = 904 AND diary_id = 902 AND work_id IS NULL",
    ) == 1
    assert await scalar(
        db, "SELECT COUNT(*) FROM picturebook_pages WHERE job_id = 904"
    ) == 9


@pytest.mark.asyncio
async def test_story_workflow_migration_reruns_idempotently(db):
    await reset_story_workflow_to_v8(db)
    await seed_story_workflow_history(db)
    await database.init_db(db)

    before_rows = await migration_rows(db)
    before_counts = {
        "story_works": await scalar(db, "SELECT COUNT(*) FROM story_works"),
        "story_work_diaries": await scalar(db, "SELECT COUNT(*) FROM story_work_diaries"),
        "picturebook_jobs": await scalar(db, "SELECT COUNT(*) FROM picturebook_jobs"),
        "picturebook_pages": await scalar(db, "SELECT COUNT(*) FROM picturebook_pages"),
    }
    before_page_ids = await scalar(
        db,
        "SELECT group_concat(id, ',') FROM "
        "(SELECT id FROM picturebook_pages ORDER BY id)",
    )

    await db.execute("DELETE FROM schema_migrations WHERE version=9")
    await db.commit()
    await database.init_db(db)

    assert await migration_rows(db) == before_rows
    assert {
        "story_works": await scalar(db, "SELECT COUNT(*) FROM story_works"),
        "story_work_diaries": await scalar(db, "SELECT COUNT(*) FROM story_work_diaries"),
        "picturebook_jobs": await scalar(db, "SELECT COUNT(*) FROM picturebook_jobs"),
        "picturebook_pages": await scalar(db, "SELECT COUNT(*) FROM picturebook_pages"),
    } == before_counts
    assert await scalar(
        db,
        "SELECT group_concat(id, ',') FROM "
        "(SELECT id FROM picturebook_pages ORDER BY id)",
    ) == before_page_ids


@pytest.mark.asyncio
async def test_picturebook_mode_snapshot_backfills_false_and_survives_v9_rebuild(db):
    await reset_story_workflow_to_v8(db)
    await seed_story_workflow_history(db)

    await database.init_db(db)

    columns = await table_columns(db, "picturebook_jobs")
    assert "allow_imaginative" in columns
    assert columns["allow_imaginative"]["notnull"] == 1
    assert columns["allow_imaginative"]["dflt_value"] == "0"
    assert await scalar(
        db,
        "SELECT allow_imaginative FROM picturebook_jobs WHERE id=?",
        (904,),
    ) == 0
    assert await scalar(
        db,
        "SELECT COUNT(*) FROM schema_migrations WHERE version=?",
        (10,),
    ) == 1

    await db.execute(
        "UPDATE picturebook_jobs SET allow_imaginative=? WHERE id=?",
        (1, 904),
    )
    await db.execute(
        """
        CREATE TABLE _picturebook_jobs_force_v9 (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            diary_id INTEGER NOT NULL,
            allow_imaginative INTEGER NOT NULL DEFAULT 0,
            style TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            stage TEXT NOT NULL DEFAULT 'queued',
            error TEXT,
            character_signature TEXT,
            story_json TEXT,
            pages_json TEXT,
            total_pages INTEGER NOT NULL DEFAULT 9,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    await db.execute(
        """
        INSERT INTO _picturebook_jobs_force_v9 (
            id, user_id, diary_id, allow_imaginative, style, status, stage,
            error, character_signature, story_json, pages_json, total_pages,
            created_at, updated_at
        )
        SELECT
            id, user_id, diary_id, allow_imaginative, style, status, stage,
            error, character_signature, story_json, pages_json, total_pages,
            created_at, updated_at
        FROM picturebook_jobs
        WHERE diary_id IS NOT NULL
        """
    )
    await db.execute("DROP TABLE picturebook_jobs")
    await db.execute(
        "ALTER TABLE _picturebook_jobs_force_v9 RENAME TO picturebook_jobs"
    )
    await db.execute("DELETE FROM schema_migrations WHERE version=?", (9,))
    await db.commit()

    await database.init_db(db)

    assert await scalar(
        db,
        "SELECT allow_imaginative FROM picturebook_jobs WHERE id=?",
        (904,),
    ) == 1


@pytest.mark.asyncio
async def test_story_workflow_migration_rerun_does_not_backfill_v9_work_dates(db):
    await reset_story_workflow_to_v8(db)
    await seed_story_workflow_history(db)
    await database.init_db(db)
    await db.execute(
        """
        INSERT INTO story_works (
            id, owner_user_id, title, medium, narrative_mode, style,
            selected_segments_json, status, kind, stage, created_at, updated_at
        ) VALUES (
            951, 901, 'new v9 draft', 'picture_book', 'true_record',
            'watercolor', '[]', 'draft', 'daily_picturebook',
            'narrative_confirmed',
            '2026-08-08T09:00:00+00:00',
            '2026-08-08T09:01:00+00:00'
        )
        """
    )
    await db.execute("DELETE FROM schema_migrations WHERE version=9")
    await db.commit()

    await database.init_db(db)

    cursor = await db.execute(
        """
        SELECT source_start_date, source_end_date, display_start_date, display_end_date
        FROM story_works
        WHERE id = 951
        """
    )
    assert dict(await cursor.fetchone()) == {
        "source_start_date": None,
        "source_end_date": None,
        "display_start_date": None,
        "display_end_date": None,
    }


@pytest.mark.asyncio
async def test_fresh_database_does_not_seed_demo_profiles(db):
    assert await scalar(db, "SELECT COUNT(*) FROM profile") == 0


@pytest.mark.asyncio
async def test_current_v3_database_upgrades_without_data_loss(legacy_v3_db):
    await database.init_db(legacy_v3_db)

    assert await scalar(
        legacy_v3_db, "SELECT COUNT(*) FROM diaries WHERE id=103 AND text='sentinel'"
    ) == 1
    assert await scalar(
        legacy_v3_db,
        "SELECT COUNT(*) FROM profile WHERE id IN (1, 2) "
        "AND nickname IN ('legacy-one', 'legacy-two')",
    ) == 2
    assert await scalar(
        legacy_v3_db,
        "SELECT COUNT(*) FROM profile WHERE id=1 "
        "AND avatar_url='/api/upload/avatar-one.png' AND avatar_asset_id IS NULL",
    ) == 1
    assert await scalar(
        legacy_v3_db,
        "SELECT COUNT(*) FROM schedules WHERE id=101 AND user_id=2",
    ) == 1
    assert await scalar(
        legacy_v3_db,
        "SELECT COUNT(*) FROM fragments WHERE id=102 AND user_id=1 "
        "AND photo_url='/api/upload/fragment.png' AND photo_asset_id IS NULL",
    ) == 1
    assert await scalar(
        legacy_v3_db,
        "SELECT COUNT(*) FROM diaries WHERE id=103 AND user_id=2 "
        "AND last_sent_at='2026-07-29T10:00:00Z'",
    ) == 1
    assert await scalar(
        legacy_v3_db,
        "SELECT COUNT(*) FROM weekly_comics WHERE id=105 AND user_id=2 "
        "AND last_sent_at='2026-07-27T08:00:00Z'",
    ) == 1
    assert await scalar(
        legacy_v3_db,
        "SELECT COUNT(*) FROM images WHERE id=104 "
        "AND url='/api/upload/diary.png' AND asset_id IS NULL",
    ) == 1
    assert await scalar(
        legacy_v3_db,
        "SELECT COUNT(*) FROM dual_timeline_comics WHERE id=106 "
        "AND user_a_id=1 AND user_b_id=2 "
        "AND url='/api/upload/timeline.png' AND asset_id IS NULL",
    ) == 1
    assert await scalar(legacy_v3_db, "SELECT COUNT(*) FROM shares WHERE id=107") == 1
    assert await scalar(legacy_v3_db, "SELECT COUNT(*) FROM accounts") == 0


@pytest.mark.asyncio
async def test_fresh_migrations_are_idempotent(db):
    before = await migration_rows(db)
    await database.init_db(db)
    after_second_run = await migration_rows(db)
    await database.init_db(db)
    after_third_run = await migration_rows(db)

    assert before
    assert before == after_second_run == after_third_run
    assert all(count == 1 for _, count in before)


@pytest.mark.asyncio
async def test_legacy_migrations_are_idempotent(legacy_v3_db):
    await database.init_db(legacy_v3_db)
    after_first_run = await migration_rows(legacy_v3_db)
    await database.init_db(legacy_v3_db)
    after_second_run = await migration_rows(legacy_v3_db)

    assert after_first_run
    assert after_first_run == after_second_run
    assert all(count == 1 for _, count in after_first_run)


@pytest.mark.asyncio
async def test_personal_space_migrates_legacy_access_and_responses_conservatively(db):
    await remove_personal_space_migration(db)
    await seed_story_identity(db)
    snapshots = {
        work_id: story_snapshot_hash(await legacy_story_snapshot(db, work_id))
        for work_id in range(10, 17)
    }
    await db.executemany(
        """
        INSERT INTO publications (
            id, work_id, owner_user_id, subscription_id, snapshot_hash,
            snapshot_json, status, published_at, revoked_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                "active-current",
                10,
                1,
                100,
                snapshots[10],
                '{"stale":true}',
                "published",
                "2026-08-03T10:00:00+00:00",
                None,
            ),
            (
                "emoji-current",
                11,
                1,
                101,
                snapshots[11],
                "{}",
                "published",
                "2026-08-03T10:01:00+00:00",
                None,
            ),
            (
                "empty-current",
                12,
                1,
                102,
                snapshots[12],
                "{}",
                "published",
                "2026-08-03T10:02:00+00:00",
                None,
            ),
            (
                "revoked-a",
                13,
                1,
                103,
                snapshots[13],
                "{}",
                "published",
                "2026-08-03T11:00:00+00:00",
                None,
            ),
            (
                "revoked-z",
                13,
                1,
                103,
                snapshots[13],
                "{}",
                "revoked",
                "2026-08-03T11:00:00+00:00",
                "2026-08-03T11:30:00+00:00",
            ),
            (
                "revoked-subscription",
                14,
                1,
                104,
                snapshots[14],
                "{}",
                "published",
                "2026-08-03T12:00:00+00:00",
                None,
            ),
            (
                "mismatched-snapshot",
                15,
                1,
                105,
                "not-the-current-hash",
                "{}",
                "published",
                "2026-08-03T13:00:00+00:00",
                None,
            ),
            (
                "ownership-mismatch",
                16,
                3,
                106,
                snapshots[16],
                "{}",
                "published",
                "2026-08-03T14:00:00+00:00",
                None,
            ),
        ],
    )
    await db.executemany(
        """
        INSERT INTO responses (
            id, publication_id, author_user_id, kind, body, created_at, deleted_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                "active-seen-deleted",
                "active-current",
                2,
                "seen",
                None,
                "2026-08-03T08:00:00+00:00",
                "2026-08-03T08:01:00+00:00",
            ),
            (
                "active-seen-early",
                "active-current",
                2,
                "seen",
                None,
                "2026-08-03T08:10:00+00:00",
                None,
            ),
            (
                "active-seen-late",
                "active-current",
                2,
                "seen",
                None,
                "2026-08-03T08:20:00+00:00",
                None,
            ),
            (
                "active-text-old",
                "active-current",
                2,
                "text",
                "old text",
                "2026-08-03T08:30:00+00:00",
                None,
            ),
            (
                "active-emoji-y",
                "active-current",
                2,
                "emoji",
                "🙂",
                "2026-08-03T08:40:00+00:00",
                None,
            ),
            (
                "active-text-z",
                "active-current",
                2,
                "text",
                "latest text",
                "2026-08-03T08:40:00+00:00",
                None,
            ),
            (
                "active-text-blank",
                "active-current",
                2,
                "text",
                "   ",
                "2026-08-03T08:50:00+00:00",
                None,
            ),
            (
                "active-voice",
                "active-current",
                2,
                "voice",
                "voice-url",
                "2026-08-03T09:00:00+00:00",
                None,
            ),
            (
                "emoji-body",
                "emoji-current",
                3,
                "emoji",
                "❤️",
                "2026-08-03T09:10:00+00:00",
                None,
            ),
            (
                "empty-voice",
                "empty-current",
                4,
                "voice",
                "voice-url",
                "2026-08-03T09:20:00+00:00",
                None,
            ),
            (
                "empty-deleted-text",
                "empty-current",
                4,
                "text",
                "deleted",
                "2026-08-03T09:30:00+00:00",
                "2026-08-03T09:31:00+00:00",
            ),
        ],
    )
    await db.commit()

    await database.init_db(db)
    first_rows = await migration_rows(db)
    await database.init_db(db)
    assert await migration_rows(db) == first_rows

    cursor = await db.execute(
        """
        SELECT work_id, status, granted_at, revoked_at
        FROM work_audience
        ORDER BY work_id
        """
    )
    audience = {row["work_id"]: dict(row) for row in await cursor.fetchall()}
    assert {work_id: row["status"] for work_id, row in audience.items()} == {
        10: "active",
        11: "active",
        12: "active",
        13: "revoked",
        14: "revoked",
        15: "revoked",
        16: "revoked",
    }
    assert audience[10]["granted_at"] == "2026-08-03T10:00:00+00:00"
    assert audience[13]["revoked_at"] == "2026-08-03T11:30:00+00:00"
    assert await scalar(db, "SELECT COUNT(*) FROM work_audience") == 7
    # v11: works 10/11/12 have active audience -> published; 13/14/15/16 stay ready
    assert await scalar(
        db, "SELECT COUNT(*) FROM story_works WHERE status='published'"
    ) == 3
    assert await scalar(db, "SELECT COUNT(*) FROM story_works WHERE status='ready'") == 4

    cursor = await db.execute(
        "SELECT id, status, published_at FROM story_works ORDER BY id"
    )
    works = {row["id"]: dict(row) for row in await cursor.fetchall()}
    assert works[10]["status"] == "published"
    assert works[10]["published_at"] == "2026-08-03T10:00:00+00:00"
    assert works[11]["status"] == "published"
    assert works[11]["published_at"] == "2026-08-03T10:01:00+00:00"
    assert works[12]["status"] == "published"
    assert works[12]["published_at"] == "2026-08-03T10:02:00+00:00"
    for work_id in (13, 14, 15, 16):
        assert works[work_id]["status"] == "ready"
        assert works[work_id]["published_at"] is None

    cursor = await db.execute(
        """
        SELECT
            work_id, author_user_id, seen_at, body_kind, body,
            created_at, updated_at, deleted_at
        FROM work_responses
        ORDER BY work_id
        """
    )
    responses = {row["work_id"]: dict(row) for row in await cursor.fetchall()}
    assert set(responses) == {10, 11}
    assert responses[10]["author_user_id"] == 2
    assert responses[10]["seen_at"] == "2026-08-03T08:10:00+00:00"
    assert responses[10]["body_kind"] == "text"
    assert responses[10]["body"] == "latest text"
    assert responses[10]["updated_at"] == "2026-08-03T08:40:00+00:00"
    assert responses[10]["deleted_at"] is None
    assert responses[11]["seen_at"] is None
    assert responses[11]["body_kind"] == "text"
    assert responses[11]["body"] == "❤️"

    # v11: only the active text response on published work 10 becomes a comment.
    # work 11's response is emoji-only in legacy (`body_kind='text'` but the
    # aggregate had no text body) — actually body was '❤️' stored as text, so
    # it migrates too. Seen-only rows never migrate.
    cursor = await db.execute(
        "SELECT work_id, viewer_user_id, body FROM work_comments ORDER BY work_id"
    )
    comments = [dict(row) for row in await cursor.fetchall()]
    assert {(row["work_id"], row["viewer_user_id"]) for row in comments} == {
        (10, 2),
        (11, 3),
    }
    bodies = {row["work_id"]: row["body"] for row in comments}
    assert bodies[10] == "latest text"
    assert bodies[11] == "❤️"


@pytest.mark.asyncio
async def test_v4_normalizes_legacy_comment_timestamps_and_canonicalizes_default(db):
    await db.execute("DROP TABLE post_comments")
    await db.execute(
        """
        CREATE TABLE post_comments (
            id TEXT PRIMARY KEY,
            post_id TEXT NOT NULL REFERENCES room_posts(id) ON DELETE CASCADE,
            author_user_id INTEGER NOT NULL REFERENCES accounts(user_id),
            client_request_id TEXT NOT NULL,
            body TEXT NOT NULL CHECK (length(trim(body)) > 0),
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            deleted_at TIMESTAMP,
            UNIQUE (post_id, author_user_id, client_request_id)
        )
        """
    )
    await db.execute("DELETE FROM schema_migrations WHERE version=4")
    await db.execute(
        "INSERT INTO profile (id, nickname) VALUES (101, 'legacy-commenter')"
    )
    await db.execute(
        "INSERT INTO accounts (user_id, username_norm, password_hash) "
        "VALUES (101, 'legacy-commenter', 'not-a-real-hash')"
    )
    await db.execute(
        "INSERT INTO rooms (id, creator_user_id) VALUES ('legacy-comments-room', 101)"
    )
    await db.execute(
        "INSERT INTO room_posts "
        "(id, room_id, author_user_id, source_type, snapshot_hash, snapshot_json) "
        "VALUES ('legacy-comments-post', 'legacy-comments-room', 101, "
        "'note', 'hash', '{}')"
    )
    await db.execute(
        "INSERT INTO post_comments "
        "(id, post_id, author_user_id, client_request_id, body) "
        "VALUES ('legacy-default', 'legacy-comments-post', 101, 'default', 'one')"
    )
    await db.execute(
        "INSERT INTO post_comments "
        "(id, post_id, author_user_id, client_request_id, body, created_at, deleted_at) "
        "VALUES ('legacy-offset', 'legacy-comments-post', 101, 'offset', 'two', "
        "'2026-08-03T13:00:00+01:00', '2026-08-03T13:30:00+01:00')"
    )
    await db.commit()

    await database.init_db(db)

    cursor = await db.execute(
        "SELECT id, created_at, deleted_at FROM post_comments ORDER BY id"
    )
    rows = {row["id"]: row for row in await cursor.fetchall()}
    assert "T" in rows["legacy-default"]["created_at"]
    assert rows["legacy-default"]["created_at"].endswith("+00:00")
    assert rows["legacy-offset"]["created_at"] == "2026-08-03T12:00:00+00:00"
    assert rows["legacy-offset"]["deleted_at"] == "2026-08-03T12:30:00+00:00"
    assert await scalar(
        db, "SELECT COUNT(*) FROM schema_migrations WHERE version=4"
    ) == 1

    await db.execute(
        "INSERT INTO post_comments "
        "(id, post_id, author_user_id, client_request_id, body) "
        "VALUES ('new-default', 'legacy-comments-post', 101, 'new', 'three')"
    )
    default_value = await scalar(
        db, "SELECT created_at FROM post_comments WHERE id='new-default'"
    )
    assert "T" in default_value and default_value.endswith("+00:00")
    foreign_keys = await db.execute("PRAGMA foreign_key_list(post_comments)")
    foreign_key_rows = await foreign_keys.fetchall()
    actual_foreign_keys = {
        (row["table"], row["from"], row["on_delete"])
        for row in foreign_key_rows
    }
    assert actual_foreign_keys == {
        ("room_posts", "post_id", "CASCADE"),
        ("accounts", "author_user_id", "NO ACTION"),
    }
    with pytest.raises(sqlite3.IntegrityError):
        await db.execute(
            "INSERT INTO post_comments "
            "(id, post_id, author_user_id, client_request_id, body) "
            "VALUES ('duplicate-request', 'legacy-comments-post', 101, "
            "'offset', 'duplicate')"
        )
    with pytest.raises(sqlite3.IntegrityError):
        await db.execute(
            "INSERT INTO post_comments "
            "(id, post_id, author_user_id, client_request_id, body) "
            "VALUES ('missing-post', 'does-not-exist', 101, 'missing', 'bad')"
        )
    with pytest.raises(sqlite3.IntegrityError):
        await db.execute(
            "INSERT INTO post_comments "
            "(id, post_id, author_user_id, client_request_id, body) "
            "VALUES ('empty-body', 'legacy-comments-post', 101, 'empty', '   ')"
        )


async def fetch_fragment_times(db):
    cursor = await db.execute(
        "SELECT content, record_time FROM fragments ORDER BY id"
    )
    return {row["content"]: row["record_time"] for row in await cursor.fetchall()}


@pytest.mark.asyncio
async def test_fragment_record_time_migration_backfills_shanghai_clock(legacy_v3_db):
    await legacy_v3_db.execute(
        "UPDATE fragments SET created_at='2026-08-08 07:42:00' WHERE id=102"
    )
    await legacy_v3_db.execute(
        "INSERT INTO fragments(date, content, created_at, user_id) "
        "VALUES ('2026-08-08', 'offset', '2026-08-08T07:42:00+08:00', 1), "
        "('2026-08-08', 'broken', 'not-a-date', 1)"
    )
    await legacy_v3_db.commit()

    await migrations.migrate(legacy_v3_db)

    columns = await table_columns(legacy_v3_db, "fragments")
    assert "record_time" in columns
    rows = await fetch_fragment_times(legacy_v3_db)
    assert rows["sentinel fragment"] == "15:42"
    assert rows["offset"] == "07:42"
    assert rows["broken"] is None

    cursor = await legacy_v3_db.execute(
        "SELECT created_at FROM fragments WHERE content='sentinel fragment'"
    )
    assert (await cursor.fetchone())["created_at"] == "2026-08-08 07:42:00"


@pytest.mark.asyncio
async def test_fragment_record_time_migration_is_idempotent(legacy_v3_db):
    await legacy_v3_db.execute(
        "UPDATE fragments SET created_at='2026-08-08 07:42:00' WHERE id=102"
    )
    await legacy_v3_db.commit()

    await migrations.migrate(legacy_v3_db)
    first = await fetch_fragment_times(legacy_v3_db)
    assert first["sentinel fragment"] == "15:42"

    await legacy_v3_db.execute(
        "UPDATE fragments SET record_time='09:09' WHERE id=102"
    )
    await legacy_v3_db.commit()
    await migrations.migrate(legacy_v3_db)
    second = await fetch_fragment_times(legacy_v3_db)
    assert second["sentinel fragment"] == "09:09"

    assert await scalar(
        legacy_v3_db,
        "SELECT COUNT(*) FROM schema_migrations WHERE version=11",
    ) == 1


@pytest.mark.asyncio
async def test_fragment_record_time_column_exists_on_fresh_database(db):
    columns = await table_columns(db, "fragments")
    assert "record_time" in columns
    assert await scalar(
        db, "SELECT COUNT(*) FROM schema_migrations WHERE version=11"
    ) == 1


# ---------------------------------------------------------------------------
# v14 film folder: motion_comic_drafts + deterministic running-job reconcile
# ---------------------------------------------------------------------------


async def reset_film_folder_to_v13(db):
    """Drop v14 artifacts and mark the migration as not yet applied."""
    await db.commit()
    await db.execute("PRAGMA foreign_keys = OFF")
    try:
        await db.execute("DROP TABLE IF EXISTS motion_comic_drafts")
        await db.execute("DELETE FROM schema_migrations WHERE version=14")
        await db.commit()
    finally:
        await db.execute("PRAGMA foreign_keys = ON")


async def seed_film_folder_user(db, user_id, name):
    await db.execute(
        "INSERT INTO profile (id, nickname) VALUES (?, ?)", (user_id, name)
    )
    await db.execute(
        "INSERT INTO accounts (user_id, username_norm, password_hash) "
        "VALUES (?, ?, 'not-a-real-hash')",
        (user_id, name),
    )


async def seed_film_folder_diary(db, diary_id, user_id, date="2026-08-08"):
    await db.execute(
        """
        INSERT INTO diaries (id, date, text, status, source, user_id, created_at)
        VALUES (?, ?, 'film folder diary', 'confirmed', 'manual', ?, ?)
        """,
        (diary_id, date, user_id, f"{date}T08:00:00+00:00"),
    )


async def seed_picturebook_job(
    db,
    job_id,
    user_id,
    *,
    diary_id=None,
    work_id=None,
    status="running",
    stage="rendering",
    updated_at,
):
    await db.execute(
        """
        INSERT INTO picturebook_jobs (
            id, user_id, diary_id, work_id, style, status, stage,
            total_pages, created_at, updated_at
        ) VALUES (?, ?, ?, ?, 'watercolor', ?, ?, 9, '2026-08-09T01:00:00Z', ?)
        """,
        (job_id, user_id, diary_id, work_id, status, stage, updated_at),
    )


async def seed_picturebook_pages(db, job_id, ready_count, total=9):
    for index in range(total):
        status = "ready" if index < ready_count else "pending"
        await db.execute(
            """
            INSERT INTO picturebook_pages (
                job_id, page_index, image_id, caption, status,
                created_at, updated_at
            ) VALUES (?, ?, ?, 'caption', ?, '2026-08-09T01:00:00Z',
                      '2026-08-09T01:00:00Z')
            """,
            (job_id, index, f"img-{job_id}-{index}" if status == "ready" else "", status),
        )


async def seed_story_work(db, work_id, user_id, *, active_job_id=None, status="draft"):
    await db.execute(
        """
        INSERT INTO story_works (
            id, owner_user_id, title, medium, narrative_mode, style,
            selected_segments_json, status, stage, active_picturebook_job_id,
            created_at, updated_at
        ) VALUES (?, ?, '晚霞', 'picture_book', 'narrative', 'watercolor',
                  '[]', ?, 'rendering', ?, '2026-08-09T00:00:00Z',
                  '2026-08-09T00:00:00Z')
        """,
        (work_id, user_id, status, active_job_id),
    )


async def seed_video_job(
    db,
    job_id,
    user_id,
    *,
    picturebook_job_id,
    work_id=None,
    status="running",
    page_sequence="[0, 1, 2]",
    updated_at,
):
    await db.execute(
        """
        INSERT INTO picturebook_video_jobs (
            id, user_id, picturebook_job_id, work_id, style, source_signature,
            model, segment_duration, ratio, page_sequence, status, stage,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, 'watercolor', ?, 'model-x', 2, '16:9', ?, ?,
                  'rendering', '2026-08-09T01:00:00Z', ?)
        """,
        (
            job_id,
            user_id,
            picturebook_job_id,
            work_id,
            f"sig-{job_id}",
            page_sequence,
            status,
            updated_at,
        ),
    )


@pytest.mark.asyncio
async def test_v14_creates_motion_comic_drafts_schema(db):
    assert "motion_comic_drafts" in await table_names(db)

    columns = await table_columns(db, "motion_comic_drafts")
    assert {
        "id",
        "user_id",
        "source_kind",
        "source_id",
        "title",
        "page_sequence_json",
        "video_job_id",
        "created_at",
        "updated_at",
    } <= set(columns)

    cursor = await db.execute("PRAGMA index_list(motion_comic_drafts)")
    indexes = {row["name"]: row for row in await cursor.fetchall()}
    assert any(
        indexes[name]["unique"] for name in indexes if name != "sqlite_autoindex_motion_comic_drafts_1"
    ) or "sqlite_autoindex_motion_comic_drafts_1" in indexes

    assert await scalar(
        db, "SELECT COUNT(*) FROM schema_migrations WHERE version=14"
    ) == 1


@pytest.mark.asyncio
async def test_v14_reconciles_duplicate_running_picturebook_jobs(db):
    await reset_film_folder_to_v13(db)
    await seed_film_folder_user(db, 7, "alice-v14")
    await seed_film_folder_diary(db, 11, 7)
    await seed_film_folder_diary(db, 12, 7, date="2026-08-09")
    await seed_picturebook_job(
        db, 101, 7, diary_id=11, updated_at="2026-08-09T01:01:00Z"
    )
    await seed_picturebook_job(
        db, 102, 7, diary_id=12, updated_at="2026-08-09T01:02:00Z"
    )
    await seed_picturebook_pages(db, 101, ready_count=4)
    await db.commit()

    await database.init_db(db)

    cursor = await db.execute(
        "SELECT id, status FROM picturebook_jobs WHERE id IN (101, 102) ORDER BY id"
    )
    rows = {row["id"]: row["status"] for row in await cursor.fetchall()}
    assert rows == {101: "failed", 102: "running"}
    # Demoted job keeps its ready pages.
    assert await scalar(
        db,
        "SELECT COUNT(*) FROM picturebook_pages "
        "WHERE job_id=101 AND status='ready'",
    ) == 4
    # Safe retryable error recorded.
    cursor = await db.execute("SELECT error FROM picturebook_jobs WHERE id=101")
    assert (await cursor.fetchone())["error"]


@pytest.mark.asyncio
async def test_v14_restores_work_for_demoted_picturebook_job(db):
    await reset_film_folder_to_v13(db)
    await seed_film_folder_user(db, 21, "worker-v14")
    await seed_film_folder_diary(db, 31, 21)
    await seed_story_work(db, 41, 21, active_job_id=201)
    await seed_picturebook_job(
        db, 200, 21, work_id=41, updated_at="2026-08-09T01:03:00Z"
    )
    await seed_picturebook_job(
        db, 201, 21, work_id=41, updated_at="2026-08-09T01:01:00Z"
    )
    await db.commit()

    await database.init_db(db)

    cursor = await db.execute(
        "SELECT id, status FROM picturebook_jobs WHERE id IN (200, 201) ORDER BY id"
    )
    rows = {row["id"]: row["status"] for row in await cursor.fetchall()}
    assert rows == {200: "running", 201: "failed"}

    cursor = await db.execute(
        "SELECT status, stage, active_picturebook_job_id, generation_error "
        "FROM story_works WHERE id=41"
    )
    work = dict(await cursor.fetchone())
    assert work["status"] == "draft"
    assert work["stage"] == "render_failed"
    assert work["active_picturebook_job_id"] is None
    assert work["generation_error"]


@pytest.mark.asyncio
async def test_v14_reconciles_running_videos_and_backfills_drafts(db):
    await reset_film_folder_to_v13(db)
    await seed_film_folder_user(db, 51, "video-v14")
    await seed_film_folder_diary(db, 61, 51)
    await seed_picturebook_job(
        db, 301, 51, diary_id=61, status="ready", stage="done",
        updated_at="2026-08-09T01:00:00Z",
    )
    await seed_picturebook_job(
        db, 302, 51, diary_id=61, status="ready", stage="done",
        updated_at="2026-08-09T01:10:00Z",
    )
    await seed_video_job(
        db, 401, 51, picturebook_job_id=301, updated_at="2026-08-09T02:01:00Z"
    )
    await seed_video_job(
        db, 402, 51, picturebook_job_id=302, updated_at="2026-08-09T02:02:00Z"
    )
    await seed_video_job(
        db, 403, 51, picturebook_job_id=301, status="failed",
        updated_at="2026-08-09T01:30:00Z",
    )
    await db.commit()

    await database.init_db(db)

    cursor = await db.execute(
        "SELECT id, status FROM picturebook_video_jobs ORDER BY id"
    )
    rows = {row["id"]: row["status"] for row in await cursor.fetchall()}
    assert rows == {401: "failed", 402: "running", 403: "failed"}

    # Every running/failed historical video gains exactly one linked draft.
    cursor = await db.execute(
        "SELECT video_job_id, source_kind, source_id, page_sequence_json "
        "FROM motion_comic_drafts ORDER BY video_job_id"
    )
    drafts = [dict(row) for row in await cursor.fetchall()]
    assert [draft["video_job_id"] for draft in drafts] == [401, 402, 403]
    by_job = {draft["video_job_id"]: draft for draft in drafts}
    assert by_job[401]["source_kind"] == "job"
    assert by_job[401]["source_id"] == 301
    assert by_job[401]["page_sequence_json"] == "[0, 1, 2]"


@pytest.mark.asyncio
async def test_v14_backfilled_draft_prefers_work_source_when_present(db):
    await reset_film_folder_to_v13(db)
    await seed_film_folder_user(db, 71, "worksrc-v14")
    await seed_film_folder_diary(db, 81, 71)
    await seed_story_work(db, 91, 71, status="ready")
    await seed_picturebook_job(
        db, 501, 71, work_id=91, status="ready", stage="done",
        updated_at="2026-08-09T01:00:00Z",
    )
    await seed_video_job(
        db, 601, 71, picturebook_job_id=501, work_id=91, status="failed",
        page_sequence="[2, 0]", updated_at="2026-08-09T02:00:00Z",
    )
    await db.commit()

    await database.init_db(db)

    cursor = await db.execute(
        "SELECT source_kind, source_id, page_sequence_json "
        "FROM motion_comic_drafts WHERE video_job_id=601"
    )
    draft = dict(await cursor.fetchone())
    assert draft == {
        "source_kind": "work",
        "source_id": 91,
        "page_sequence_json": "[2, 0]",
    }


@pytest.mark.asyncio
async def test_v14_is_idempotent(db):
    await reset_film_folder_to_v13(db)
    await seed_film_folder_user(db, 99, "idem-v14")
    await seed_film_folder_diary(db, 98, 99)
    await seed_picturebook_job(
        db, 701, 99, diary_id=98, updated_at="2026-08-09T01:01:00Z"
    )
    await seed_picturebook_job(
        db, 702, 99, diary_id=98, updated_at="2026-08-09T01:02:00Z"
    )
    await db.commit()

    await database.init_db(db)
    first = await scalar(db, "SELECT COUNT(*) FROM motion_comic_drafts")
    await database.init_db(db)
    second = await scalar(db, "SELECT COUNT(*) FROM motion_comic_drafts")

    assert first == second
    assert await scalar(
        db, "SELECT COUNT(*) FROM schema_migrations WHERE version=14"
    ) == 1
    cursor = await db.execute(
        "SELECT status FROM picturebook_jobs WHERE id=701"
    )
    assert (await cursor.fetchone())["status"] == "failed"
