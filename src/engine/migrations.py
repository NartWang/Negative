import hashlib
import json
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo


SHANGHAI = ZoneInfo("Asia/Shanghai")


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


async def _personal_story_domain(db: Any) -> None:
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS character_profiles (
            user_id INTEGER PRIMARY KEY REFERENCES accounts(user_id) ON DELETE CASCADE,
            source_photo_url TEXT,
            reference_image_url TEXT,
            character_description TEXT NOT NULL DEFAULT '',
            version INTEGER NOT NULL DEFAULT 0 CHECK (version >= 0),
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS story_works (
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
        CREATE TABLE IF NOT EXISTS work_assets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            work_id INTEGER NOT NULL REFERENCES story_works(id) ON DELETE CASCADE,
            ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
            asset_type TEXT NOT NULL CHECK (asset_type IN ('text', 'image', 'video')),
            url TEXT,
            asset_id TEXT REFERENCES media_assets(id) ON DELETE SET NULL,
            text TEXT,
            prompt TEXT,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (work_id, ordinal)
        )
        """
    )
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_user_id INTEGER NOT NULL REFERENCES accounts(user_id) ON DELETE CASCADE,
            subscriber_user_id INTEGER NOT NULL REFERENCES accounts(user_id) ON DELETE CASCADE,
            status TEXT NOT NULL DEFAULT 'active'
                CHECK (status IN ('active', 'revoked')),
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            revoked_at TIMESTAMP,
            CHECK (owner_user_id != subscriber_user_id),
            UNIQUE (owner_user_id, subscriber_user_id)
        )
        """
    )
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS subscription_invites (
            id TEXT PRIMARY KEY,
            owner_user_id INTEGER NOT NULL REFERENCES accounts(user_id) ON DELETE CASCADE,
            token_hash TEXT NOT NULL UNIQUE,
            expires_at TIMESTAMP NOT NULL,
            accepted_by_user_id INTEGER REFERENCES accounts(user_id),
            accepted_at TIMESTAMP,
            revoked_at TIMESTAMP,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS publications (
            id TEXT PRIMARY KEY,
            work_id INTEGER NOT NULL REFERENCES story_works(id) ON DELETE CASCADE,
            owner_user_id INTEGER NOT NULL REFERENCES accounts(user_id) ON DELETE CASCADE,
            subscription_id INTEGER NOT NULL REFERENCES subscriptions(id) ON DELETE CASCADE,
            snapshot_hash TEXT NOT NULL,
            snapshot_json TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'published'
                CHECK (status IN ('published', 'revoked')),
            published_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            revoked_at TIMESTAMP,
            UNIQUE (work_id, subscription_id, status)
        )
        """
    )
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS responses (
            id TEXT PRIMARY KEY,
            publication_id TEXT NOT NULL REFERENCES publications(id) ON DELETE CASCADE,
            author_user_id INTEGER NOT NULL REFERENCES accounts(user_id) ON DELETE CASCADE,
            kind TEXT NOT NULL CHECK (kind IN ('seen', 'emoji', 'text', 'voice')),
            body TEXT,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            deleted_at TIMESTAMP
        )
        """
    )
    await _ensure_index(
        db,
        "idx_story_works_owner",
        "CREATE INDEX idx_story_works_owner "
        "ON story_works(owner_user_id, created_at DESC)",
    )
    await _ensure_index(
        db,
        "idx_publications_feed",
        "CREATE INDEX idx_publications_feed "
        "ON publications(subscription_id, status, published_at DESC)",
    )
    await _ensure_index(
        db,
        "idx_responses_publication",
        "CREATE INDEX idx_responses_publication "
        "ON responses(publication_id, created_at ASC)",
    )


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


async def _current_story_snapshot_hash(db: Any, work_id: int) -> Optional[str]:
    cursor = await db.execute("SELECT * FROM story_works WHERE id=?", (work_id,))
    work = await cursor.fetchone()
    if work is None:
        return None
    cursor = await db.execute(
        "SELECT * FROM work_assets WHERE work_id=? ORDER BY ordinal ASC",
        (work_id,),
    )
    try:
        selected_segments = json.loads(work["selected_segments_json"])
    except (TypeError, json.JSONDecodeError):
        return None
    snapshot = {
        "id": work["id"],
        "title": work["title"],
        "medium": work["medium"],
        "narrative_mode": work["narrative_mode"],
        "style": work["style"],
        "assets": [dict(row) for row in await cursor.fetchall()],
        "selected_segments": selected_segments,
    }
    encoded = _canonical_json(snapshot)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


async def _personal_space_access(db: Any) -> None:
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS work_audience (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            work_id INTEGER NOT NULL REFERENCES story_works(id) ON DELETE CASCADE,
            subscription_id INTEGER NOT NULL REFERENCES subscriptions(id) ON DELETE CASCADE,
            status TEXT NOT NULL DEFAULT 'active'
                CHECK (status IN ('active', 'revoked')),
            granted_at TIMESTAMP NOT NULL,
            revoked_at TIMESTAMP,
            created_at TIMESTAMP NOT NULL,
            CHECK (
                (status = 'active' AND revoked_at IS NULL)
                OR (status = 'revoked' AND revoked_at IS NOT NULL)
            ),
            UNIQUE (work_id, subscription_id)
        )
        """
    )
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS work_responses (
            id TEXT PRIMARY KEY,
            work_id INTEGER NOT NULL REFERENCES story_works(id) ON DELETE CASCADE,
            author_user_id INTEGER NOT NULL REFERENCES accounts(user_id) ON DELETE CASCADE,
            seen_at TIMESTAMP,
            body_kind TEXT CHECK (body_kind IS NULL OR body_kind = 'text'),
            body TEXT,
            created_at TIMESTAMP NOT NULL,
            updated_at TIMESTAMP NOT NULL,
            deleted_at TIMESTAMP,
            UNIQUE (work_id, author_user_id),
            CHECK (
                (body_kind IS NULL AND body IS NULL)
                OR (
                    body_kind = 'text'
                    AND body IS NOT NULL
                    AND length(trim(body)) BETWEEN 1 AND 2000
                )
            ),
            CHECK (deleted_at IS NOT NULL OR seen_at IS NOT NULL OR body IS NOT NULL)
        )
        """
    )
    await _ensure_index(
        db,
        "idx_work_audience_feed",
        "CREATE INDEX idx_work_audience_feed "
        "ON work_audience(subscription_id, status, granted_at DESC, work_id DESC)",
    )
    await _ensure_index(
        db,
        "idx_work_responses_owner",
        "CREATE INDEX idx_work_responses_owner "
        "ON work_responses(work_id, deleted_at, updated_at DESC, id DESC)",
    )

    cursor = await db.execute(
        """
        SELECT
            publication.id,
            publication.work_id,
            publication.owner_user_id AS publication_owner_user_id,
            publication.subscription_id,
            publication.snapshot_hash,
            publication.status,
            publication.published_at,
            publication.revoked_at,
            work.owner_user_id AS work_owner_user_id,
            subscription.owner_user_id AS subscription_owner_user_id,
            subscription.subscriber_user_id,
            subscription.status AS subscription_status,
            subscription.revoked_at AS subscription_revoked_at
        FROM publications AS publication
        LEFT JOIN story_works AS work ON work.id = publication.work_id
        LEFT JOIN subscriptions AS subscription ON subscription.id = publication.subscription_id
        ORDER BY publication.work_id, publication.subscription_id,
            publication.published_at DESC, publication.id DESC
        """
    )
    latest_publications = []
    seen_pairs: set[tuple[int, int]] = set()
    for row in await cursor.fetchall():
        pair = (row["work_id"], row["subscription_id"])
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        latest_publications.append(row)

    active_publication_ids: set[str] = set()
    for row in latest_publications:
        current_hash = await _current_story_snapshot_hash(db, row["work_id"])
        ownership_aligned = (
            row["work_owner_user_id"] is not None
            and row["subscription_owner_user_id"] is not None
            and row["publication_owner_user_id"]
            == row["work_owner_user_id"]
            == row["subscription_owner_user_id"]
        )
        is_active = (
            ownership_aligned
            and row["status"] == "published"
            and row["subscription_status"] == "active"
            and row["snapshot_hash"] == current_hash
        )
        if row["work_owner_user_id"] is None or row["subscriber_user_id"] is None:
            continue
        status = "active" if is_active else "revoked"
        granted_at = _canonical_utc_timestamp(row["published_at"])
        revoked_at = (
            None
            if is_active
            else _canonical_utc_timestamp(
                row["revoked_at"]
                or row["subscription_revoked_at"]
                or row["published_at"]
            )
        )
        await db.execute(
            """
            INSERT INTO work_audience (
                work_id, subscription_id, status, granted_at, revoked_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(work_id, subscription_id) DO UPDATE SET
                status = excluded.status,
                granted_at = excluded.granted_at,
                revoked_at = excluded.revoked_at
            """,
            (
                row["work_id"],
                row["subscription_id"],
                status,
                granted_at,
                revoked_at,
                granted_at,
            ),
        )
        if is_active:
            active_publication_ids.add(row["id"])

    cursor = await db.execute(
        """
        SELECT
            response.id,
            response.publication_id,
            response.author_user_id,
            response.kind,
            response.body,
            response.created_at,
            publication.work_id,
            subscription.subscriber_user_id
        FROM responses AS response
        JOIN publications AS publication ON publication.id = response.publication_id
        JOIN story_works AS work ON work.id = publication.work_id
        JOIN subscriptions AS subscription ON subscription.id = publication.subscription_id
        WHERE response.deleted_at IS NULL
          AND publication.status = 'published'
          AND publication.owner_user_id = work.owner_user_id
          AND subscription.owner_user_id = work.owner_user_id
          AND subscription.status = 'active'
          AND response.author_user_id = subscription.subscriber_user_id
        """
    )
    aggregates: dict[tuple[int, int], dict[str, Any]] = {}
    for row in await cursor.fetchall():
        if row["publication_id"] not in active_publication_ids:
            continue
        key = (row["work_id"], row["author_user_id"])
        aggregate = aggregates.setdefault(
            key,
            {
                "seen_at": None,
                "body": None,
                "created_at": None,
                "updated_at": None,
                "body_sort_key": None,
            },
        )
        created_at = _canonical_utc_timestamp(row["created_at"])
        if row["kind"] == "seen":
            if aggregate["seen_at"] is None or created_at < aggregate["seen_at"]:
                aggregate["seen_at"] = created_at
            timestamps = [value for value in (aggregate["created_at"], created_at) if value]
            aggregate["created_at"] = min(timestamps)
            aggregate["updated_at"] = max(
                value for value in (aggregate["updated_at"], created_at) if value
            )
            continue
        if row["kind"] not in {"emoji", "text"}:
            continue
        body = (row["body"] or "").strip()
        if not body:
            continue
        body_sort_key = (created_at, row["id"])
        if (
            aggregate["body_sort_key"] is None
            or body_sort_key > aggregate["body_sort_key"]
        ):
            aggregate["body"] = body
            aggregate["body_sort_key"] = body_sort_key
        timestamps = [value for value in (aggregate["created_at"], created_at) if value]
        aggregate["created_at"] = min(timestamps)
        aggregate["updated_at"] = max(
            value for value in (aggregate["updated_at"], created_at) if value
        )

    for (work_id, author_user_id), aggregate in aggregates.items():
        if aggregate["seen_at"] is None and aggregate["body"] is None:
            continue
        response_id = f"legacy-response:{work_id}:{author_user_id}"
        created_at = aggregate["created_at"] or aggregate["updated_at"]
        updated_at = aggregate["updated_at"] or created_at
        await db.execute(
            """
            INSERT INTO work_responses (
                id, work_id, author_user_id, seen_at, body_kind, body,
                created_at, updated_at, deleted_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)
            ON CONFLICT(work_id, author_user_id) DO UPDATE SET
                seen_at = excluded.seen_at,
                body_kind = excluded.body_kind,
                body = excluded.body,
                updated_at = excluded.updated_at,
                deleted_at = NULL
            """,
            (
                response_id,
                work_id,
                author_user_id,
                aggregate["seen_at"],
                "text" if aggregate["body"] is not None else None,
                aggregate["body"],
                created_at,
                updated_at,
            ),
        )

    await db.execute("UPDATE story_works SET status='ready' WHERE status='published'")


async def _character_display_fields(db: Any) -> None:
    """Give a confirmed character its own name, display action and origin."""
    await _ensure_column(
        db,
        "character_profiles",
        "nickname",
        "nickname TEXT NOT NULL DEFAULT ''",
    )
    await _ensure_column(
        db,
        "character_profiles",
        "display_action",
        "display_action TEXT",
    )
    await _ensure_column(
        db,
        "character_profiles",
        "source_type",
        "source_type TEXT NOT NULL DEFAULT ''",
    )


async def _picturebook_pipeline(db: Any) -> None:
    """Two-stage picturebook jobs: diary -> story JSON -> 9 rendered pages."""
    # Cached character_lock text, derived once from the character artwork so the
    # story/page prompts describe the same person the reference image shows.
    await _ensure_column(
        db,
        "character_profiles",
        "visual_profile",
        "visual_profile TEXT",
    )
    # No FK declarations here: `diaries` itself carries none, and the user table
    # is `profile(id)` (with `accounts.user_id` as its login row), so adding one
    # would only introduce a mismatch. Ownership is enforced in the queries.
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS picturebook_jobs (
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
        CREATE TABLE IF NOT EXISTS picturebook_pages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER NOT NULL,
            page_index INTEGER NOT NULL,
            image_id TEXT NOT NULL DEFAULT '',
            caption TEXT NOT NULL DEFAULT '',
            image_prompt TEXT NOT NULL DEFAULT '',
            asset_id TEXT,
            image_url TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE (job_id, page_index)
        )
        """
    )
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_picturebook_jobs_diary "
        "ON picturebook_jobs(diary_id, user_id)"
    )
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_picturebook_pages_job "
        "ON picturebook_pages(job_id, page_index)"
    )


PICTUREBOOK_JOB_WORKFLOW_COLUMNS = (
    "id",
    "user_id",
    "diary_id",
    "work_id",
    "source_text",
    "source_signature",
    "allow_imaginative",
    "style",
    "status",
    "stage",
    "error",
    "character_signature",
    "story_json",
    "pages_json",
    "total_pages",
    "created_at",
    "updated_at",
)


async def _picturebook_jobs_need_workflow_rebuild(db: Any) -> bool:
    columns = await _column_names(db, "picturebook_jobs")
    required_columns = {
        "work_id",
        "source_text",
        "source_signature",
    }
    if not required_columns <= columns:
        return True

    cursor = await db.execute("PRAGMA table_info(picturebook_jobs)")
    column_info = {row["name"]: row for row in await cursor.fetchall()}
    if column_info["diary_id"]["notnull"]:
        return True

    sql = await _table_sql(db, "picturebook_jobs")
    return "(diary_id IS NOT NULL) != (work_id IS NOT NULL)" not in compact_sql(sql)


def compact_sql(sql: str) -> str:
    return " ".join(sql.split())


async def _rebuild_picturebook_jobs_for_workflow(db: Any) -> None:
    if not await _picturebook_jobs_need_workflow_rebuild(db):
        return

    existing_columns = await _column_names(db, "picturebook_jobs")

    await db.execute("DROP TABLE IF EXISTS _picturebook_jobs_v9")
    await db.execute(
        """
        CREATE TABLE _picturebook_jobs_v9 (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            diary_id INTEGER,
            work_id INTEGER,
            source_text TEXT,
            source_signature TEXT,
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
            updated_at TEXT NOT NULL,
            CHECK ((diary_id IS NOT NULL) != (work_id IS NOT NULL))
        )
        """
    )

    select_columns = []
    for column in PICTUREBOOK_JOB_WORKFLOW_COLUMNS:
        if column in existing_columns:
            select_columns.append(column)
        elif column == "allow_imaginative":
            select_columns.append("0")
        else:
            select_columns.append("NULL")
    await db.execute(
        "INSERT INTO _picturebook_jobs_v9 "
        f"({', '.join(PICTUREBOOK_JOB_WORKFLOW_COLUMNS)}) "
        f"SELECT {', '.join(select_columns)} FROM picturebook_jobs"
    )
    await db.execute("DROP TABLE picturebook_jobs")
    await db.execute("ALTER TABLE _picturebook_jobs_v9 RENAME TO picturebook_jobs")


async def _story_workflow(db: Any) -> None:
    """Losslessly add workflow ownership fields for story generation."""
    for column, ddl in (
        ("kind", "kind TEXT"),
        ("stage", "stage TEXT"),
        ("source_snapshot_json", "source_snapshot_json TEXT"),
        ("source_snapshot_hash", "source_snapshot_hash TEXT"),
        ("generation_error", "generation_error TEXT"),
        ("active_picturebook_job_id", "active_picturebook_job_id INTEGER"),
        ("picturebook_job_id", "picturebook_job_id INTEGER"),
        ("cover_asset_id", "cover_asset_id TEXT"),
        ("source_start_date", "source_start_date TEXT"),
        ("source_end_date", "source_end_date TEXT"),
        ("display_start_date", "display_start_date TEXT"),
        ("display_end_date", "display_end_date TEXT"),
        ("selected_storyline_json", "selected_storyline_json TEXT"),
        ("storyline_candidates_json", "storyline_candidates_json TEXT"),
        ("narrative_text", "narrative_text TEXT"),
        ("stage_updated_at", "stage_updated_at TEXT"),
    ):
        await _ensure_column(db, "story_works", column, ddl)

    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS story_work_diaries (
            work_id INTEGER NOT NULL REFERENCES story_works(id) ON DELETE CASCADE,
            diary_id INTEGER NOT NULL REFERENCES diaries(id) ON DELETE CASCADE,
            ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
            PRIMARY KEY (work_id, diary_id),
            UNIQUE (work_id, ordinal)
        )
        """
    )

    await _rebuild_picturebook_jobs_for_workflow(db)

    await _ensure_index(
        db,
        "idx_picturebook_jobs_diary",
        "CREATE INDEX idx_picturebook_jobs_diary "
        "ON picturebook_jobs(diary_id, user_id)",
    )
    await _ensure_index(
        db,
        "idx_picturebook_jobs_work",
        "CREATE INDEX idx_picturebook_jobs_work "
        "ON picturebook_jobs(work_id, user_id)",
    )
    await _ensure_index(
        db,
        "idx_story_work_diaries_diary",
        "CREATE INDEX idx_story_work_diaries_diary "
        "ON story_work_diaries(diary_id, work_id)",
    )

    await db.execute(
        """
        UPDATE story_works
        SET
            source_start_date = COALESCE(
                source_start_date,
                (SELECT date FROM diaries WHERE id = story_works.source_diary_id),
                substr(created_at, 1, 10)
            ),
            source_end_date = COALESCE(
                source_end_date,
                (SELECT date FROM diaries WHERE id = story_works.source_diary_id),
                substr(created_at, 1, 10)
            ),
            display_start_date = COALESCE(
                display_start_date,
                (SELECT date FROM diaries WHERE id = story_works.source_diary_id),
                substr(created_at, 1, 10)
            ),
            display_end_date = COALESCE(
                display_end_date,
                (SELECT date FROM diaries WHERE id = story_works.source_diary_id),
                substr(created_at, 1, 10)
            )
        WHERE kind IS NULL
          AND (
              source_start_date IS NULL
              OR source_end_date IS NULL
              OR display_start_date IS NULL
              OR display_end_date IS NULL
          )
        """
    )


async def _picturebook_prompt_mode_snapshot(db: Any) -> None:
    """Persist the diary imagery choice on each immutable picturebook attempt."""
    await _ensure_column(
        db,
        "picturebook_jobs",
        "allow_imaginative",
        "allow_imaginative INTEGER NOT NULL DEFAULT 0",
    )


def _fragment_record_clock(value: Any) -> Optional[str]:
    try:
        parsed = datetime.fromisoformat(
            str(value).replace(" ", "T").replace("Z", "+00:00")
        )
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(SHANGHAI).strftime("%H:%M")


async def _fragment_record_time(db: Any) -> None:
    """Backfill user-editable fragment clock from the audit created_at."""
    await _ensure_column(db, "fragments", "record_time", "record_time TEXT")
    cursor = await db.execute(
        "SELECT id, created_at FROM fragments WHERE record_time IS NULL"
    )
    for row in await cursor.fetchall():
        clock = _fragment_record_clock(row["created_at"])
        if clock is not None:
            await db.execute(
                "UPDATE fragments SET record_time=? WHERE id=?",
                (clock, row["id"]),
            )


def _parse_utc_or_none(value: Any) -> Optional[str]:
    if value is None:
        return None
    try:
        return _canonical_utc_timestamp(value)
    except (TypeError, ValueError):
        return None


async def _resonance_publication_and_interactions(db: Any) -> None:
    """Add story-level publication state plus per-viewer likes and comments."""
    await _ensure_column(db, "story_works", "published_at", "published_at TEXT")
    await _ensure_column(db, "story_works", "unpublished_at", "unpublished_at TEXT")
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS work_likes (
            id TEXT PRIMARY KEY,
            work_id INTEGER NOT NULL REFERENCES story_works(id) ON DELETE CASCADE,
            viewer_user_id INTEGER NOT NULL REFERENCES accounts(user_id) ON DELETE CASCADE,
            created_at TEXT NOT NULL,
            deleted_at TEXT,
            UNIQUE (work_id, viewer_user_id)
        )
        """
    )
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS work_comments (
            id TEXT PRIMARY KEY,
            work_id INTEGER NOT NULL REFERENCES story_works(id) ON DELETE CASCADE,
            viewer_user_id INTEGER NOT NULL REFERENCES accounts(user_id) ON DELETE CASCADE,
            author_user_id INTEGER NOT NULL REFERENCES accounts(user_id) ON DELETE CASCADE,
            client_request_id TEXT NOT NULL,
            body TEXT NOT NULL CHECK (length(trim(body)) BETWEEN 1 AND 2000),
            created_at TEXT NOT NULL,
            deleted_at TEXT,
            UNIQUE (work_id, author_user_id, client_request_id)
        )
        """
    )

    # Conservative backfill: works with at least one active audience become
    # published; ready works without active audience stay unpublished.
    cursor = await db.execute(
        "SELECT id, status, updated_at, created_at FROM story_works"
    )
    works = await cursor.fetchall()
    for work in works:
        work_id = work["id"]
        audience_cursor = await db.execute(
            "SELECT status, granted_at FROM work_audience WHERE work_id = ?",
            (work_id,),
        )
        audience_rows = await audience_cursor.fetchall()
        active_rows = [row for row in audience_rows if row["status"] == "active"]
        if work["status"] == "ready" and not active_rows:
            continue

        # collect all parseable audience timestamps, take the earliest
        audience_times = [
            parsed
            for row in audience_rows
            if (parsed := _parse_utc_or_none(row["granted_at"])) is not None
        ]
        published_at = min(audience_times) if audience_times else None
        if published_at is None:
            published_at = _parse_utc_or_none(work["updated_at"])
        if published_at is None:
            published_at = _parse_utc_or_none(work["created_at"])

        if work["status"] == "ready" and active_rows:
            await db.execute(
                "UPDATE story_works SET status='published', published_at=? "
                "WHERE id=?",
                (published_at, work_id),
            )
        elif work["status"] == "published":
            await db.execute(
                "UPDATE story_works SET published_at=? WHERE id=?",
                (published_at, work_id),
            )

    # Migrate active text responses on published works into comments. Each
    # legacy response had (work_id, author_user_id) unique, so it becomes the
    # viewer's first comment.
    response_cursor = await db.execute(
        """
        SELECT response.id, response.work_id, response.author_user_id,
               response.body, response.created_at
        FROM work_responses AS response
        JOIN story_works AS work ON work.id = response.work_id
        WHERE response.deleted_at IS NULL
          AND response.body_kind = 'text'
          AND trim(response.body) <> ''
          AND work.status = 'published'
          AND EXISTS (
              SELECT 1 FROM work_audience AS audience
              JOIN subscriptions AS subscription
                ON subscription.id = audience.subscription_id
              WHERE audience.work_id = response.work_id
                AND audience.status = 'active'
                AND subscription.subscriber_user_id = response.author_user_id
                AND subscription.owner_user_id = work.owner_user_id
                AND subscription.status = 'active'
          )
        """
    )
    for row in await response_cursor.fetchall():
        comment_id = f"legacy-comment:{row['work_id']}:{row['author_user_id']}"
        created_at = _parse_utc_or_none(row["created_at"]) or _canonical_utc_timestamp(
            datetime.now(timezone.utc)
        )
        await db.execute(
            """
            INSERT INTO work_comments (
                id, work_id, viewer_user_id, author_user_id,
                client_request_id, body, created_at, deleted_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL)
            ON CONFLICT(work_id, author_user_id, client_request_id) DO NOTHING
            """,
            (
                comment_id,
                row["work_id"],
                row["author_user_id"],
                row["author_user_id"],
                comment_id,
                row["body"].strip(),
                created_at,
            ),
        )

    await _ensure_index(
        db,
        "idx_story_works_published_feed",
        "CREATE INDEX idx_story_works_published_feed "
        "ON story_works(status, published_at DESC, id DESC)",
    )
    await _ensure_index(
        db,
        "idx_work_likes_work",
        "CREATE INDEX idx_work_likes_work ON work_likes(work_id, deleted_at)",
    )
    await _ensure_index(
        db,
        "idx_work_comments_work_viewer",
        "CREATE INDEX idx_work_comments_work_viewer "
        "ON work_comments(work_id, viewer_user_id, deleted_at, created_at ASC)",
    )


async def _record_resonance_v11_compat(db: Any) -> None:
    """Ensure both parallel v11 branches are present after integration."""
    await _fragment_record_time(db)
    await _resonance_publication_and_interactions(db)


async def _picturebook_video_pipeline(db: Any) -> None:
    """绘本 → 首尾帧接力视频：N 页配对成 N-1 段，逐段生成后拼成一条成片。

    视频资产单独建表，不复用 `media_assets`：那张表的存储层强制图片 MIME 白名单
    与图片文件签名校验，且体积上限按图片设定，混进 MP4 会削弱这两道校验。
    这里也不往 `work_assets` 写行——那会改变作品快照哈希，让已授权的读者被判定
    为失效；视频是绘本之上的附加产物，独立成表即可。
    """
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS video_assets (
            id TEXT PRIMARY KEY,
            owner_user_id INTEGER NOT NULL,
            storage_key TEXT NOT NULL UNIQUE,
            mime_type TEXT NOT NULL,
            size_bytes INTEGER NOT NULL CHECK (size_bytes >= 0),
            duration_seconds REAL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    # 与 picturebook_jobs 一致：不声明外键，因为用户表是 profile(id) 而
    # picturebook_jobs 本身也没有外键，归属一律在查询里强制。
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS picturebook_video_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            picturebook_job_id INTEGER NOT NULL,
            work_id INTEGER,
            style TEXT NOT NULL,
            source_signature TEXT NOT NULL,
            model TEXT NOT NULL,
            segment_duration INTEGER NOT NULL,
            ratio TEXT NOT NULL,
            seed INTEGER,
            include_cover INTEGER NOT NULL DEFAULT 0,
            page_sequence TEXT NOT NULL DEFAULT '[]',
            status TEXT NOT NULL DEFAULT 'running'
                CHECK (status IN ('running', 'done', 'failed')),
            stage TEXT NOT NULL DEFAULT 'queued',
            error TEXT,
            total_segments INTEGER NOT NULL DEFAULT 0,
            asset_id TEXT REFERENCES video_assets(id) ON DELETE SET NULL,
            duration_seconds REAL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS picturebook_video_segments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            video_job_id INTEGER NOT NULL
                REFERENCES picturebook_video_jobs(id) ON DELETE CASCADE,
            segment_index INTEGER NOT NULL CHECK (segment_index >= 0),
            first_page_index INTEGER NOT NULL,
            last_page_index INTEGER NOT NULL,
            prompt TEXT NOT NULL DEFAULT '',
            provider_task_id TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            error TEXT,
            asset_id TEXT REFERENCES video_assets(id) ON DELETE SET NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE (video_job_id, segment_index)
        )
        """
    )
    #漫剧向导允许挑页并重排，成片必须按用户给的那个顺序走，
    # 所以页序要跟着任务一起存下来，重试时才能复现同一条片子。
    await _ensure_column(
        db,
        "picturebook_video_jobs",
        "page_sequence",
        "page_sequence TEXT NOT NULL DEFAULT '[]'",
    )
    await _ensure_index(
        db,
        "idx_pb_video_jobs_source",
        "CREATE UNIQUE INDEX idx_pb_video_jobs_source "
        "ON picturebook_video_jobs(picturebook_job_id, user_id, source_signature)",
    )
    await _ensure_index(
        db,
        "idx_pb_video_segments_job",
        "CREATE INDEX idx_pb_video_segments_job "
        "ON picturebook_video_segments(video_job_id, segment_index)",
    )


# 与 services/story_workflow.py 的安全错误文案保持一致：迁移是数据层操作，
# 不能引入服务层依赖，这里重复同一条用户可见的安全重试提示。
_V14_SAFE_RETRY_ERROR = "生成过程出错了，可以重试"


def _v14_now() -> str:
    """与应用运行时一致的 ISO8601 UTC 时间戳,避免与既有记录混排时错序。"""
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


async def _demote_excess_running_jobs(db: Any, *, table: str) -> list[int]:
    """同用户同表多个 running 任务按 updated_at DESC, id DESC 只保留第一条。

    返回被降级为 failed 的任务 id 列表。已完成页/分镜与媒体一律保留。
    """
    cursor = await db.execute(
        f"""
        SELECT id, user_id,
               ROW_NUMBER() OVER (
                   PARTITION BY user_id
                   ORDER BY updated_at DESC, id DESC
               ) AS rank
        FROM {table}
        WHERE status = 'running'
        """
    )
    rows = await cursor.fetchall()
    demoted = [row["id"] for row in rows if row["rank"] > 1]
    if not demoted:
        return []
    placeholders = ",".join("?" for _ in demoted)
    now = _v14_now()
    await db.execute(
        f"UPDATE {table} SET status='failed', stage='failed', error=?, "
        f"updated_at=? WHERE id IN ({placeholders})",
        (_V14_SAFE_RETRY_ERROR, now, *demoted),
    )
    return demoted


async def _film_folder_v14(db: Any) -> None:
    """底片夹改版:新增漫剧草稿表,并对历史并发运行任务做确定性收敛。

    - 同用户多个 running 绘本/漫剧任务:保留最新一条,其余转 failed(成果保留)。
    - 被降级的正式绘本任务对应的 story_works 恢复 draft/render_failed 并清理
      活动指针,使其进入「继续创作」。
    - 每条 running/failed 历史视频任务补一条 motion_comic_drafts 草稿,
      source 优先取 work_id,否则取 picturebook_job_id,页序复制 page_sequence。
    """
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS motion_comic_drafts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            source_kind TEXT NOT NULL CHECK (source_kind IN ('work', 'job')),
            source_id INTEGER NOT NULL,
            title TEXT NOT NULL DEFAULT '',
            page_sequence_json TEXT NOT NULL DEFAULT '[]',
            video_job_id INTEGER UNIQUE,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    await _ensure_index(
        db,
        "idx_motion_comic_drafts_user_updated",
        "CREATE INDEX idx_motion_comic_drafts_user_updated "
        "ON motion_comic_drafts(user_id, updated_at DESC, id DESC)",
    )

    demoted_picturebooks = await _demote_excess_running_jobs(
        db, table="picturebook_jobs"
    )
    if demoted_picturebooks:
        placeholders = ",".join("?" for _ in demoted_picturebooks)
        now = _v14_now()
        await db.execute(
            f"""
            UPDATE story_works
            SET status = 'draft',
                stage = 'render_failed',
                generation_error = ?,
                stage_updated_at = ?,
                active_picturebook_job_id = NULL,
                updated_at = ?
            WHERE active_picturebook_job_id IN ({placeholders})
            """,
            (_V14_SAFE_RETRY_ERROR, now, now, *demoted_picturebooks),
        )

    await _demote_excess_running_jobs(db, table="picturebook_video_jobs")

    now = _v14_now()
    await db.execute(
        """
        INSERT INTO motion_comic_drafts (
            user_id, source_kind, source_id, title,
            page_sequence_json, video_job_id, created_at, updated_at
        )
        SELECT
            jobs.user_id,
            CASE WHEN jobs.work_id IS NOT NULL THEN 'work' ELSE 'job' END,
            COALESCE(jobs.work_id, jobs.picturebook_job_id),
            '',
            jobs.page_sequence,
            jobs.id,
            ?,
            ?
        FROM picturebook_video_jobs AS jobs
        WHERE jobs.status IN ('running', 'failed')
          AND NOT EXISTS (
              SELECT 1 FROM motion_comic_drafts AS drafts
              WHERE drafts.video_job_id = jobs.id
          )
        """,
        (now, now),
    )


async def _generation_quota_v15(db: Any) -> None:
    """体验配额:每个用户在每个生成分区(绘本/漫剧)有可新建任务次数上限。

    对外 Demo 场景:体验账号默认没有额度(无行即 0),无法新建生成任务,
    防止被无限刷取消耗 token;由离线脚本按需给指定账号充值次数。
    同一任务的重试/恢复不重复扣次数,只有真正 INSERT 一条新 job 才扣。
    """
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS generation_quotas (
            user_id INTEGER NOT NULL,
            category TEXT NOT NULL CHECK (category IN ('picturebook', 'motion_comic')),
            remaining INTEGER NOT NULL DEFAULT 0 CHECK (remaining >= 0),
            updated_at TEXT NOT NULL,
            PRIMARY KEY (user_id, category)
        )
        """
    )


MIGRATIONS: tuple[Migration, ...] = (
    (1, "legacy_v3_base", _legacy_v3_base),
    (2, "private_pair_schema", _private_pair_schema),
    (3, "protected_media_references", _protected_media_references),
    (4, "canonical_comment_timestamps", _canonical_comment_timestamps),
    (5, "personal_story_domain", _personal_story_domain),
    (6, "personal_space_access", _personal_space_access),
    (7, "character_display_fields", _character_display_fields),
    (8, "picturebook_pipeline", _picturebook_pipeline),
    (9, "story_workflow", _story_workflow),
    (10, "picturebook_prompt_mode_snapshot", _picturebook_prompt_mode_snapshot),
    (11, "fragment_record_time", _fragment_record_time),
    (12, "record_resonance_v11_compat", _record_resonance_v11_compat),
    (13, "picturebook_video_pipeline_v13", _picturebook_video_pipeline),
    (14, "film_folder_v14", _film_folder_v14),
    (15, "generation_quota_v15", _generation_quota_v15),
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
