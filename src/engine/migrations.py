from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any


Migration = tuple[int, str, Callable[[Any], Awaitable[None]]]


LEGACY_TABLES = (
    """
    CREATE TABLE IF NOT EXISTS schedules (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT NOT NULL,
        time TEXT,
        title TEXT NOT NULL,
        completed INTEGER DEFAULT 0,
        feeling TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        user_id INTEGER NOT NULL DEFAULT 1
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS fragments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT NOT NULL,
        content TEXT,
        photo_url TEXT,
        photo_description TEXT,
        mood_tag TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        user_id INTEGER NOT NULL DEFAULT 1
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS diaries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT NOT NULL,
        text TEXT NOT NULL DEFAULT '',
        emotion_mode TEXT,
        status TEXT DEFAULT 'draft',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        confirmed_at TIMESTAMP,
        draft_text TEXT,
        source TEXT DEFAULT 'manual',
        user_id INTEGER NOT NULL DEFAULT 1,
        last_sent_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS images (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        diary_id INTEGER REFERENCES diaries(id),
        style TEXT,
        style_prompt TEXT,
        url TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        kept INTEGER DEFAULT 1
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS checkins (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT NOT NULL,
        has_schedule INTEGER DEFAULT 0,
        has_fragment INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        user_id INTEGER NOT NULL DEFAULT 1
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS profile (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nickname TEXT DEFAULT '我',
        avatar_url TEXT,
        signature TEXT DEFAULT '你和家人之间，多了一扇窗 ✨',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS weekly_comics (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        week_start TEXT NOT NULL,
        week_end TEXT NOT NULL,
        style TEXT,
        style_prompt TEXT,
        prompt TEXT,
        url TEXT NOT NULL,
        caption TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        last_sent_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS dual_timeline_comics (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT NOT NULL,
        user_a_id INTEGER NOT NULL,
        user_b_id INTEGER NOT NULL DEFAULT 2,
        selected_events_json TEXT,
        style TEXT,
        style_prompt TEXT,
        prompt TEXT,
        url TEXT NOT NULL,
        caption TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
)


PRIVATE_PAIR_TABLES = (
    """
    CREATE TABLE IF NOT EXISTS accounts (
        user_id INTEGER PRIMARY KEY REFERENCES profile(id) ON DELETE CASCADE,
        username_norm TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS auth_sessions (
        token_hash TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES accounts(user_id) ON DELETE CASCADE,
        expires_at TIMESTAMP NOT NULL,
        revoked_at TIMESTAMP,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS rooms (
        id TEXT PRIMARY KEY,
        creator_user_id INTEGER NOT NULL REFERENCES accounts(user_id),
        status TEXT NOT NULL DEFAULT 'active'
            CHECK (status IN ('active', 'closed')),
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        closed_at TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS room_members (
        room_id TEXT NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
        user_id INTEGER NOT NULL REFERENCES accounts(user_id),
        role TEXT NOT NULL CHECK (role IN ('owner', 'member')),
        slot INTEGER NOT NULL CHECK (slot IN (1, 2)),
        joined_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        left_at TIMESTAMP,
        PRIMARY KEY (room_id, user_id),
        UNIQUE (room_id, slot),
        CHECK (
            (role = 'owner' AND slot = 1)
            OR (role = 'member' AND slot = 2)
        )
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS room_invites (
        id TEXT PRIMARY KEY,
        room_id TEXT NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
        creator_user_id INTEGER NOT NULL REFERENCES accounts(user_id),
        code_hash TEXT NOT NULL UNIQUE,
        expires_at TIMESTAMP NOT NULL,
        consumed_at TIMESTAMP,
        consumed_by_user_id INTEGER REFERENCES accounts(user_id),
        revoked_at TIMESTAMP,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS room_posts (
        id TEXT PRIMARY KEY,
        room_id TEXT NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
        author_user_id INTEGER NOT NULL REFERENCES accounts(user_id),
        source_type TEXT NOT NULL
            CHECK (source_type IN ('note', 'diary', 'weekly_comic')),
        source_id INTEGER,
        source_revision TEXT,
        snapshot_hash TEXT NOT NULL,
        snapshot_json TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'published'
            CHECK (status IN ('published', 'revoked')),
        published_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        revoked_at TIMESTAMP,
        CHECK (
            (source_type = 'note' AND source_id IS NULL AND source_revision IS NULL)
            OR
            (source_type IN ('diary', 'weekly_comic')
             AND source_id IS NOT NULL AND source_revision IS NOT NULL)
        )
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS post_likes (
        post_id TEXT NOT NULL REFERENCES room_posts(id) ON DELETE CASCADE,
        user_id INTEGER NOT NULL REFERENCES accounts(user_id),
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (post_id, user_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS post_comments (
        id TEXT PRIMARY KEY,
        post_id TEXT NOT NULL REFERENCES room_posts(id) ON DELETE CASCADE,
        author_user_id INTEGER NOT NULL REFERENCES accounts(user_id),
        client_request_id TEXT NOT NULL,
        body TEXT NOT NULL CHECK (length(trim(body)) > 0),
        created_at TIMESTAMP NOT NULL DEFAULT (
            strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')
        ),
        deleted_at TIMESTAMP,
        UNIQUE (post_id, author_user_id, client_request_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS room_temperature_snapshots (
        room_id TEXT NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
        user_id INTEGER NOT NULL REFERENCES accounts(user_id),
        snapshot_date TEXT NOT NULL,
        score INTEGER NOT NULL CHECK (score BETWEEN 0 AND 100),
        label TEXT NOT NULL,
        color TEXT NOT NULL,
        subject_nickname TEXT NOT NULL,
        published_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        revoked_at TIMESTAMP,
        PRIMARY KEY (room_id, user_id, snapshot_date)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS media_assets (
        id TEXT PRIMARY KEY,
        owner_user_id INTEGER NOT NULL REFERENCES accounts(user_id),
        storage_key TEXT NOT NULL UNIQUE,
        mime_type TEXT NOT NULL,
        size_bytes INTEGER NOT NULL CHECK (size_bytes >= 0),
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS room_post_media (
        post_id TEXT NOT NULL REFERENCES room_posts(id) ON DELETE CASCADE,
        asset_id TEXT NOT NULL REFERENCES media_assets(id),
        ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
        PRIMARY KEY (post_id, asset_id),
        UNIQUE (post_id, ordinal)
    )
    """,
)


async def _table_sql(db: Any, table: str) -> str:
    cursor = await db.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
    )
    row = await cursor.fetchone()
    return (row["sql"] or "") if row else ""


async def _column_names(db: Any, table: str) -> set[str]:
    cursor = await db.execute(f"PRAGMA table_info({table})")
    return {row["name"] for row in await cursor.fetchall()}


async def _ensure_column(db: Any, table: str, column: str, ddl: str) -> None:
    if column not in await _column_names(db, table):
        await db.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


async def _ensure_index(db: Any, name: str, ddl: str) -> None:
    cursor = await db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='index' AND name=?", (name,)
    )
    if not await cursor.fetchone():
        await db.execute(ddl)


async def _drop_profile_singleton_check(db: Any) -> None:
    if "CHECK" not in (await _table_sql(db, "profile")).upper():
        return

    await db.execute("DROP TABLE IF EXISTS _profile_new")
    await db.execute(
        """
        CREATE TABLE _profile_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nickname TEXT DEFAULT '我',
            avatar_url TEXT,
            signature TEXT DEFAULT '你和家人之间，多了一扇窗 ✨',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    await db.execute(
        """
        INSERT INTO _profile_new (id, nickname, avatar_url, signature, created_at)
        SELECT id, nickname, avatar_url, signature, created_at FROM profile
        """
    )
    await db.execute("DROP TABLE profile")
    await db.execute("ALTER TABLE _profile_new RENAME TO profile")


async def _drop_unique_date(db: Any, table: str) -> None:
    if "UNIQUE" not in (await _table_sql(db, table)).upper():
        return

    await db.execute(f"DROP TABLE IF EXISTS _{table}_new")
    if table == "diaries":
        await db.execute(
            """
            CREATE TABLE _diaries_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                text TEXT NOT NULL DEFAULT '',
                emotion_mode TEXT,
                status TEXT DEFAULT 'draft',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                confirmed_at TIMESTAMP,
                draft_text TEXT,
                source TEXT DEFAULT 'manual',
                user_id INTEGER NOT NULL DEFAULT 1,
                last_sent_at TEXT
            )
            """
        )
        columns = (
            "id, date, text, emotion_mode, status, created_at, confirmed_at, "
            "draft_text, source, user_id, last_sent_at"
        )
    elif table == "checkins":
        await db.execute(
            """
            CREATE TABLE _checkins_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                has_schedule INTEGER DEFAULT 0,
                has_fragment INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                user_id INTEGER NOT NULL DEFAULT 1
            )
            """
        )
        columns = "id, date, has_schedule, has_fragment, created_at, user_id"
    else:
        return

    await db.execute(
        f"INSERT INTO _{table}_new ({columns}) SELECT {columns} FROM {table}"
    )
    await db.execute(f"DROP TABLE {table}")
    await db.execute(f"ALTER TABLE _{table}_new RENAME TO {table}")


async def _legacy_v3_base(db: Any) -> None:
    for statement in LEGACY_TABLES:
        await db.execute(statement)

    await _ensure_column(db, "diaries", "draft_text", "draft_text TEXT")
    await _ensure_column(db, "diaries", "source", "source TEXT DEFAULT 'manual'")
    await _ensure_column(db, "images", "kept", "kept INTEGER DEFAULT 1")
    await _ensure_column(
        db, "schedules", "user_id", "user_id INTEGER NOT NULL DEFAULT 1"
    )
    await _ensure_column(
        db, "fragments", "user_id", "user_id INTEGER NOT NULL DEFAULT 1"
    )
    await _ensure_column(
        db, "diaries", "user_id", "user_id INTEGER NOT NULL DEFAULT 1"
    )
    await _ensure_column(
        db, "checkins", "user_id", "user_id INTEGER NOT NULL DEFAULT 1"
    )
    await _ensure_column(db, "diaries", "last_sent_at", "last_sent_at TEXT")
    await _ensure_column(
        db, "weekly_comics", "last_sent_at", "last_sent_at TEXT"
    )

    await _drop_profile_singleton_check(db)
    await _drop_unique_date(db, "diaries")
    await _drop_unique_date(db, "checkins")

    await _ensure_index(
        db,
        "idx_diaries_date_user",
        "CREATE INDEX idx_diaries_date_user ON diaries(date, user_id)",
    )
    await _ensure_index(
        db,
        "idx_checkins_date_user",
        "CREATE INDEX idx_checkins_date_user ON checkins(date, user_id)",
    )
    await _ensure_index(
        db,
        "idx_weekly_comics_user",
        "CREATE INDEX idx_weekly_comics_user "
        "ON weekly_comics(user_id, created_at DESC)",
    )
    await _ensure_index(
        db,
        "idx_dt_comics_user_date",
        "CREATE INDEX idx_dt_comics_user_date "
        "ON dual_timeline_comics(user_a_id, date DESC, created_at DESC)",
    )


async def _private_pair_schema(db: Any) -> None:
    for statement in PRIVATE_PAIR_TABLES:
        await db.execute(statement)

    await _ensure_index(
        db,
        "idx_auth_sessions_user",
        "CREATE INDEX idx_auth_sessions_user ON auth_sessions(user_id, expires_at)",
    )
    await _ensure_index(
        db,
        "idx_room_members_one_active_room",
        "CREATE UNIQUE INDEX idx_room_members_one_active_room "
        "ON room_members(user_id) WHERE left_at IS NULL",
    )
    await _ensure_index(
        db,
        "idx_room_posts_one_active_source",
        "CREATE UNIQUE INDEX idx_room_posts_one_active_source "
        "ON room_posts(room_id, source_type, source_id) "
        "WHERE status = 'published' AND source_id IS NOT NULL",
    )
    await _ensure_index(
        db,
        "idx_room_posts_feed",
        "CREATE INDEX idx_room_posts_feed "
        "ON room_posts(room_id, status, published_at DESC, id DESC)",
    )
    await _ensure_index(
        db,
        "idx_room_invites_room",
        "CREATE INDEX idx_room_invites_room ON room_invites(room_id, expires_at)",
    )


async def _protected_media_references(db: Any) -> None:
    await _ensure_column(
        db,
        "profile",
        "avatar_asset_id",
        "avatar_asset_id TEXT REFERENCES media_assets(id) ON DELETE SET NULL",
    )
    await _ensure_column(
        db,
        "fragments",
        "photo_asset_id",
        "photo_asset_id TEXT REFERENCES media_assets(id) ON DELETE SET NULL",
    )
    for table in ("images", "weekly_comics", "dual_timeline_comics"):
        await _ensure_column(
            db,
            table,
            "asset_id",
            "asset_id TEXT REFERENCES media_assets(id) ON DELETE SET NULL",
        )


def _canonical_utc_timestamp(value: Any) -> str:
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError) as exc:
            raise ValueError("post comment timestamp is invalid") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


async def _canonical_comment_timestamps(db: Any) -> None:
    cursor = await db.execute(
        "SELECT id, post_id, author_user_id, client_request_id, body, "
        "created_at, deleted_at FROM post_comments"
    )
    rows = await cursor.fetchall()

    await db.execute("DROP TABLE IF EXISTS _post_comments_v4")
    await db.execute(
        """
        CREATE TABLE _post_comments_v4 (
            id TEXT PRIMARY KEY,
            post_id TEXT NOT NULL REFERENCES room_posts(id) ON DELETE CASCADE,
            author_user_id INTEGER NOT NULL REFERENCES accounts(user_id),
            client_request_id TEXT NOT NULL,
            body TEXT NOT NULL CHECK (length(trim(body)) > 0),
            created_at TIMESTAMP NOT NULL DEFAULT (
                strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')
            ),
            deleted_at TIMESTAMP,
            UNIQUE (post_id, author_user_id, client_request_id)
        )
        """
    )
    if rows:
        await db.executemany(
            "INSERT INTO _post_comments_v4 "
            "(id, post_id, author_user_id, client_request_id, body, "
            "created_at, deleted_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    row["id"],
                    row["post_id"],
                    row["author_user_id"],
                    row["client_request_id"],
                    row["body"],
                    _canonical_utc_timestamp(row["created_at"]),
                    (
                        _canonical_utc_timestamp(row["deleted_at"])
                        if row["deleted_at"] is not None
                        else None
                    ),
                )
                for row in rows
            ],
        )
    await db.execute("DROP TABLE post_comments")
    await db.execute("ALTER TABLE _post_comments_v4 RENAME TO post_comments")


MIGRATIONS: tuple[Migration, ...] = (
    (1, "legacy_v3_base", _legacy_v3_base),
    (2, "private_pair_schema", _private_pair_schema),
    (3, "protected_media_references", _protected_media_references),
    (4, "canonical_comment_timestamps", _canonical_comment_timestamps),
)


async def _needs_legacy_rebuild(db: Any) -> bool:
    profile_sql = (await _table_sql(db, "profile")).upper()
    diaries_sql = (await _table_sql(db, "diaries")).upper()
    checkins_sql = (await _table_sql(db, "checkins")).upper()
    return (
        "CHECK" in profile_sql
        or "UNIQUE" in diaries_sql
        or "UNIQUE" in checkins_sql
    )


async def migrate(db: Any) -> None:
    rebuild_with_foreign_keys_disabled = await _needs_legacy_rebuild(db)
    if rebuild_with_foreign_keys_disabled:
        await db.execute("PRAGMA foreign_keys = OFF")

    try:
        await db.execute("BEGIN IMMEDIATE")
        try:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            await db.commit()
        except Exception:
            await db.rollback()
            raise

        for version, name, migration in MIGRATIONS:
            await db.execute("BEGIN IMMEDIATE")
            try:
                cursor = await db.execute(
                    "SELECT 1 FROM schema_migrations WHERE version=?", (version,)
                )
                if await cursor.fetchone():
                    await db.commit()
                    continue

                await migration(db)
                await db.execute(
                    "INSERT INTO schema_migrations (version, name) VALUES (?, ?)",
                    (version, name),
                )
                await db.commit()
            except Exception:
                await db.rollback()
                raise
    finally:
        if rebuild_with_foreign_keys_disabled:
            await db.execute("PRAGMA foreign_keys = ON")
