from data.seed_family import seed_family_data

CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS schedules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    time TEXT,
    title TEXT NOT NULL,
    completed INTEGER DEFAULT 0,
    feeling TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS fragments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    content TEXT,
    photo_url TEXT,
    photo_description TEXT,
    mood_tag TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS diaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    text TEXT NOT NULL DEFAULT '',
    emotion_mode TEXT,
    status TEXT DEFAULT 'draft',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    confirmed_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS images (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    diary_id INTEGER REFERENCES diaries(id),
    style TEXT,
    style_prompt TEXT,
    url TEXT NOT NULL,
    ai_prompt TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS checkins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    has_schedule INTEGER DEFAULT 0,
    has_fragment INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS profile (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nickname TEXT DEFAULT '我',
    avatar_url TEXT,
    signature TEXT DEFAULT '你和家人之间，多了一扇窗 ✨',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS shares (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    diary_id INTEGER REFERENCES diaries(id),
    share_code TEXT NOT NULL UNIQUE,
    share_type TEXT DEFAULT 'diary',
    user_id INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS share_reactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    share_id INTEGER REFERENCES shares(id),
    emoji TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    seen INTEGER DEFAULT 0
);

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
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

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
);
"""


async def _ensure_column(db, table: str, column: str, ddl: str):
    cursor = await db.execute(f"PRAGMA table_info({table})")
    rows = await cursor.fetchall()
    cols = {r["name"] for r in rows}
    if column not in cols:
        await db.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


async def _ensure_index(db, name: str, ddl: str):
    cursor = await db.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name=?", (name,)
    )
    if not await cursor.fetchone():
        await db.execute(ddl)


async def _migrate_profile_drop_check(db):
    """v2 created profile with CHECK(id=1). SQLite can't drop CHECK in place — recreate the table."""
    cursor = await db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='profile'")
    row = await cursor.fetchone()
    if not row or "CHECK" not in (row["sql"] or ""):
        return
    await db.executescript(
        """
        BEGIN;
        CREATE TABLE _profile_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nickname TEXT DEFAULT '我',
            avatar_url TEXT,
            signature TEXT DEFAULT '你和家人之间，多了一扇窗 ✨',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        INSERT INTO _profile_new (id, nickname, avatar_url, signature, created_at)
            SELECT id, nickname, avatar_url, signature, created_at FROM profile;
        DROP TABLE profile;
        ALTER TABLE _profile_new RENAME TO profile;
        COMMIT;
        """
    )


async def _migrate_drop_unique_date(db, table: str, columns_csv: str):
    """v2 created `diaries` and `checkins` with UNIQUE(date). v3 needs (date, user_id)
    uniqueness instead, enforced by the composite index + app code. Recreate the table
    without the UNIQUE constraint if present.
    """
    cursor = await db.execute(f"SELECT sql FROM sqlite_master WHERE type='table' AND name='{table}'")
    row = await cursor.fetchone()
    if not row or "UNIQUE" not in (row["sql"] or ""):
        return
    if table == "diaries":
        new_ddl = """
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
                user_id INTEGER NOT NULL DEFAULT 1
            );
        """
    elif table == "checkins":
        new_ddl = """
            CREATE TABLE _checkins_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                has_schedule INTEGER DEFAULT 0,
                has_fragment INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                user_id INTEGER NOT NULL DEFAULT 1
            );
        """
    else:
        return
    await db.executescript(
        f"""
        BEGIN;
        {new_ddl}
        INSERT INTO _{table}_new ({columns_csv}) SELECT {columns_csv} FROM {table};
        DROP TABLE {table};
        ALTER TABLE _{table}_new RENAME TO {table};
        COMMIT;
        """
    )


async def init_db(db):
    await db.executescript(CREATE_TABLES_SQL)

    # v2 columns kept
    await _ensure_column(db, "diaries", "draft_text", "draft_text TEXT")
    await _ensure_column(db, "diaries", "source", "source TEXT DEFAULT 'manual'")
    await _ensure_column(db, "images", "kept", "kept INTEGER DEFAULT 1")

    # v3: user_id on every business table (default 1 to keep existing rows on user_id=1)
    await _ensure_column(db, "schedules", "user_id", "user_id INTEGER NOT NULL DEFAULT 1")
    await _ensure_column(db, "fragments", "user_id", "user_id INTEGER NOT NULL DEFAULT 1")
    await _ensure_column(db, "diaries",   "user_id", "user_id INTEGER NOT NULL DEFAULT 1")
    await _ensure_column(db, "images",    "user_id", "user_id INTEGER NOT NULL DEFAULT 1")
    await _ensure_column(db, "checkins",  "user_id", "user_id INTEGER NOT NULL DEFAULT 1")

    # v3.4: 寄给家人时间戳
    await _ensure_column(db, "diaries",       "last_sent_at", "last_sent_at TEXT")
    await _ensure_column(db, "weekly_comics", "last_sent_at", "last_sent_at TEXT")

    # v3.7: 分享链接增强（类型 + user_id）
    await _ensure_column(db, "shares", "share_type", "share_type TEXT DEFAULT 'diary'")
    await _ensure_column(db, "shares", "user_id", "user_id INTEGER NOT NULL DEFAULT 1")

    # v3: drop the legacy CHECK(id=1) on profile so we can hold multiple users.
    await _migrate_profile_drop_check(db)

    # v3: drop the legacy UNIQUE(date) on diaries/checkins; replaced by (date, user_id) composite index.
    await _migrate_drop_unique_date(
        db,
        "diaries",
        "id, date, text, emotion_mode, status, created_at, confirmed_at, draft_text, source, user_id",
    )
    await _migrate_drop_unique_date(
        db,
        "checkins",
        "id, date, has_schedule, has_fragment, created_at, user_id",
    )

    # diaries unique was UNIQUE(date) — SQLite can't drop, so use a composite index instead.
    # We rely on app code to enforce (date, user_id) uniqueness via UPSERT.
    # Note: on v2 DBs the old UNIQUE(date) on diaries/checkins may persist;
    # we rely on the composite index below + app code to enforce (date, user_id) uniqueness.
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
        "CREATE INDEX idx_weekly_comics_user ON weekly_comics(user_id, created_at DESC)",
    )
    await _ensure_index(
        db,
        "idx_dt_comics_user_date",
        "CREATE INDEX idx_dt_comics_user_date ON dual_timeline_comics(user_a_id, date DESC, created_at DESC)",
    )

    # Seed profile rows
    cursor = await db.execute("SELECT COUNT(*) as c FROM profile")
    count = (await cursor.fetchone())["c"]
    if count == 0:
        await db.execute(
            "INSERT INTO profile (id, nickname, signature) VALUES (1, '我', '你和家人之间，多了一扇窗 ✨')"
        )
        await db.execute(
            "INSERT INTO profile (id, nickname, signature) VALUES (2, '妈妈', '在另一头，悄悄记着你的一切')"
        )
    else:
        # Ensure user_id=2 exists (if user upgraded from v2 single profile row)
        cursor = await db.execute("SELECT id FROM profile WHERE id = 2")
        if not await cursor.fetchone():
            await db.execute(
                "INSERT INTO profile (id, nickname, signature) VALUES (2, '妈妈', '在另一头，悄悄记着你的一切')"
            )

    await db.commit()

    # Seed family mock data (idempotent)
    await seed_family_data(db)
