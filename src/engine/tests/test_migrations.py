import sqlite3
from pathlib import Path

import pytest

import database


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


async def scalar(db, sql, params=()):
    cursor = await db.execute(sql, params)
    row = await cursor.fetchone()
    return row[0]


async def table_names(db):
    cursor = await db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )
    return {row["name"] for row in await cursor.fetchall()}


async def migration_rows(db):
    cursor = await db.execute(
        "SELECT version, COUNT(*) AS count "
        "FROM schema_migrations GROUP BY version ORDER BY version"
    )
    return [(row["version"], row["count"]) for row in await cursor.fetchall()]


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
