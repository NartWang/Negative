import importlib
from pathlib import Path

import pytest_asyncio


def _configure_database(monkeypatch, db_path: Path, upload_dir: Path):
    monkeypatch.setenv("ZHIJI_DB_PATH", str(db_path))
    monkeypatch.setenv("ZHIJI_UPLOAD_DIR", str(upload_dir))

    import config
    import database

    importlib.reload(config)
    importlib.reload(database)

    # The pre-migration module exposes a fixed DB_PATH. Keep the RED test safe by
    # redirecting that legacy attribute too; the migrated get_db reads config.
    monkeypatch.setattr(database, "DB_PATH", str(db_path), raising=False)
    return database


@pytest_asyncio.fixture
async def db(tmp_path, monkeypatch):
    db_path = tmp_path / "fresh.sqlite3"
    database = _configure_database(
        monkeypatch, db_path, tmp_path / "fresh-uploads"
    )
    connection = await database.get_db()
    try:
        await database.init_db(connection)
        yield connection
    finally:
        await connection.close()


LEGACY_V3_SCHEMA = """
CREATE TABLE schedules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    time TEXT,
    title TEXT NOT NULL,
    completed INTEGER DEFAULT 0,
    feeling TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    user_id INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE fragments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    content TEXT,
    photo_url TEXT,
    photo_description TEXT,
    mood_tag TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    user_id INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE diaries (
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
);
CREATE TABLE images (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    diary_id INTEGER REFERENCES diaries(id),
    style TEXT,
    style_prompt TEXT,
    url TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    kept INTEGER DEFAULT 1
);
CREATE TABLE checkins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    has_schedule INTEGER DEFAULT 0,
    has_fragment INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    user_id INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE profile (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nickname TEXT DEFAULT '我',
    avatar_url TEXT,
    signature TEXT DEFAULT '你和家人之间，多了一扇窗 ✨',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE weekly_comics (
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
);
CREATE TABLE dual_timeline_comics (
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
CREATE TABLE shares (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    diary_id INTEGER REFERENCES diaries(id),
    share_code TEXT NOT NULL UNIQUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP
);
"""


LEGACY_V3_SENTINELS = """
INSERT INTO profile (id, nickname, avatar_url, signature)
VALUES (1, 'legacy-one', '/api/upload/avatar-one.png', 'one'),
       (2, 'legacy-two', '/api/upload/avatar-two.png', 'two');
INSERT INTO schedules (id, date, time, title, completed, user_id)
VALUES (101, '2026-07-28', '09:00', 'sentinel schedule', 1, 2);
INSERT INTO fragments (id, date, content, photo_url, user_id)
VALUES (102, '2026-07-28', 'sentinel fragment', '/api/upload/fragment.png', 1);
INSERT INTO diaries (
    id, date, text, status, draft_text, source, user_id, last_sent_at
) VALUES (
    103, '2026-07-28', 'sentinel', 'confirmed', 'sentinel draft', 'ai', 2,
    '2026-07-29T10:00:00Z'
);
INSERT INTO images (id, diary_id, style, url, kept)
VALUES (104, 103, 'legacy', '/api/upload/diary.png', 1);
INSERT INTO weekly_comics (
    id, user_id, week_start, week_end, url, last_sent_at
) VALUES (
    105, 2, '2026-07-20', '2026-07-26', '/api/upload/weekly.png',
    '2026-07-27T08:00:00Z'
);
INSERT INTO dual_timeline_comics (
    id, date, user_a_id, user_b_id, url
) VALUES (106, '2026-07-28', 1, 2, '/api/upload/timeline.png');
INSERT INTO shares (id, diary_id, share_code, expires_at)
VALUES (107, 103, 'legacy-share-code', '2026-08-30T00:00:00Z');
"""


@pytest_asyncio.fixture
async def legacy_v3_db(tmp_path, monkeypatch):
    db_path = tmp_path / "legacy-v3.sqlite3"
    database = _configure_database(
        monkeypatch, db_path, tmp_path / "legacy-v3-uploads"
    )
    connection = await database.get_db()
    try:
        await connection.executescript(LEGACY_V3_SCHEMA)
        await connection.executescript(LEGACY_V3_SENTINELS)
        await connection.commit()
        yield connection
    finally:
        await connection.close()
