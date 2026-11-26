#!/usr/bin/env python3
"""Seed four idempotent collected-story demos for the judge account."""

from __future__ import annotations

import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "src/engine/data/zhiji.db"

CASES = [
    {
        "username": "demo-collection-xiaohu",
        "nickname": "小虎",
        "preset": "p08",
        "title": "案例故事-放学路上的纸飞机",
        "legacy_title": "放学路上的纸飞机",
        "style": "crayon",
        "date": "2026-08-06",
        "cover": "/demo-collections/xiaohu-crayon.png",
        "summary": "放学后，小虎追着一架纸飞机跑过树影。它没有飞得很远，却把普通的回家路变成了一场小小冒险。",
    },
    {
        "username": "demo-collection-xiaoman",
        "nickname": "小满",
        "preset": "p01",
        "title": "案例故事-夜里为自己煮一碗面",
        "legacy_title": "夜里为自己煮一碗面",
        "style": "watercolor",
        "date": "2026-07-30",
        "cover": "/demo-collections/xiaoman-watercolor.png",
        "summary": "忙碌的一天结束后，小满没有再用零食代替晚饭。厨房的一盏灯和一碗热面，让夜晚慢慢安静下来。",
    },
    {
        "username": "demo-collection-baidaifu",
        "nickname": "白大夫",
        "preset": "p26",
        "title": "案例故事-夜班结束前的最后一次巡房",
        "legacy_title": "夜班结束前的最后一次巡房",
        "style": "pixel",
        "date": "2026-07-20",
        "cover": "/demo-collections/baidaifu-pixel.png",
        "summary": "天快亮时，白大夫完成了夜班最后一次巡房。走廊尽头的晨光亮起来，他才发现忙碌的一夜已经被轻轻接住。",
    },
    {
        "username": "demo-collection-yunnainai",
        "nickname": "云奶奶",
        "preset": "p13",
        "title": "案例故事-阳台上的一盆薄荷",
        "legacy_title": "阳台上的一盆薄荷",
        "style": "sketch",
        "date": "2026-07-10",
        "cover": "/demo-collections/yunnainai-sketch.png",
        "summary": "云奶奶每天给阳台上的薄荷浇一点水。新叶长出来的时候，她也想起了那些被日常悄悄照顾的时光。",
    },
]


def ensure_owner(connection: sqlite3.Connection, case: dict, password_hash: str) -> int:
    account = connection.execute(
        "SELECT user_id FROM accounts WHERE username_norm = ?", (case["username"],)
    ).fetchone()
    if account:
        user_id = int(account[0])
    else:
        cursor = connection.execute(
            "INSERT INTO profile (nickname, signature) VALUES (?, ?)",
            (case["nickname"], "把普通的一天，留成自己的故事。"),
        )
        user_id = int(cursor.lastrowid)
        connection.execute(
            "INSERT INTO accounts (user_id, username_norm, password_hash) VALUES (?, ?, ?)",
            (user_id, case["username"], password_hash),
        )
    connection.execute(
        "UPDATE profile SET nickname = ?, signature = ? WHERE id = ?",
        (case["nickname"], "把普通的一天，留成自己的故事。", user_id),
    )
    avatar_url = f"/characters/main/{case['preset']}.webp"
    connection.execute(
        """
        INSERT INTO character_profiles (
            user_id, reference_image_url, character_description, version,
            nickname, display_action, source_type, visual_profile
        ) VALUES (?, ?, ?, 1, ?, 'idle', 'preset', ?)
        ON CONFLICT(user_id) DO UPDATE SET
            reference_image_url = excluded.reference_image_url,
            character_description = excluded.character_description,
            nickname = excluded.nickname,
            display_action = excluded.display_action,
            source_type = excluded.source_type,
            visual_profile = excluded.visual_profile,
            updated_at = CURRENT_TIMESTAMP
        """,
        (user_id, avatar_url, case["nickname"], case["nickname"], case["preset"]),
    )
    return user_id


def ensure_work(connection: sqlite3.Connection, owner_id: int, case: dict) -> int:
    timestamp = f"{case['date']}T12:00:00Z"
    existing = connection.execute(
        "SELECT id FROM story_works WHERE owner_user_id = ? AND title IN (?, ?)",
        (owner_id, case["title"], case["legacy_title"]),
    ).fetchone()
    if existing:
        work_id = int(existing[0])
        connection.execute(
            """
            UPDATE story_works SET title = ?, style = ?, status = 'published',
                display_start_date = ?, display_end_date = ?,
                source_start_date = ?, source_end_date = ?,
                updated_at = ?, stage_updated_at = ?, published_at = ?, unpublished_at = NULL
            WHERE id = ?
            """,
            (case["title"], case["style"], case["date"], case["date"], case["date"], case["date"],
             timestamp, timestamp, timestamp, work_id),
        )
    else:
        cursor = connection.execute(
            """
            INSERT INTO story_works (
                owner_user_id, title, medium, narrative_mode, style,
                selected_segments_json, status, kind, stage,
                source_start_date, source_end_date, display_start_date, display_end_date,
                created_at, updated_at, stage_updated_at, published_at
            ) VALUES (?, ?, 'picture_book', 'true_record', ?, '[]', 'published',
                      'daily_picturebook', 'ready', ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (owner_id, case["title"], case["style"], case["date"], case["date"],
             case["date"], case["date"], timestamp, timestamp, timestamp, timestamp),
        )
        work_id = int(cursor.lastrowid)
    assets = [
        (0, "image", case["cover"], None),
        (1, "text", None, case["summary"]),
    ]
    for ordinal, asset_type, url, text in assets:
        connection.execute(
            """
            INSERT INTO work_assets (work_id, ordinal, asset_type, url, text, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(work_id, ordinal) DO UPDATE SET
                asset_type = excluded.asset_type,
                url = excluded.url,
                text = excluded.text
            """,
            (work_id, ordinal, asset_type, url, text, timestamp),
        )
    return work_id


def grant_to_viewer(
    connection: sqlite3.Connection, owner_id: int, viewer_id: int, work_id: int, date: str
) -> None:
    timestamp = f"{date}T12:00:00Z"
    connection.execute(
        """
        INSERT INTO subscriptions (owner_user_id, subscriber_user_id, status, created_at)
        VALUES (?, ?, 'active', ?)
        ON CONFLICT(owner_user_id, subscriber_user_id) DO UPDATE SET
            status = 'active', revoked_at = NULL
        """,
        (owner_id, viewer_id, timestamp),
    )
    subscription_id = connection.execute(
        "SELECT id FROM subscriptions WHERE owner_user_id = ? AND subscriber_user_id = ?",
        (owner_id, viewer_id),
    ).fetchone()[0]
    connection.execute(
        """
        INSERT INTO work_audience (
            work_id, subscription_id, status, granted_at, revoked_at, created_at
        ) VALUES (?, ?, 'active', ?, NULL, ?)
        ON CONFLICT(work_id, subscription_id) DO UPDATE SET
            status = 'active', granted_at = excluded.granted_at, revoked_at = NULL
        """,
        (work_id, subscription_id, timestamp, timestamp),
    )


def main() -> None:
    connection = sqlite3.connect(DB_PATH)
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        judge = connection.execute(
            """
            SELECT account.user_id, account.password_hash
            FROM accounts AS account
            WHERE account.username_norm = '底片'
            """
        ).fetchone()
        if not judge:
            raise RuntimeError("judge account 底片 does not exist")
        viewer_id, password_hash = int(judge[0]), str(judge[1])
        seeded = []
        connection.execute("BEGIN IMMEDIATE")
        for case in CASES:
            owner_id = ensure_owner(connection, case, password_hash)
            work_id = ensure_work(connection, owner_id, case)
            grant_to_viewer(connection, owner_id, viewer_id, work_id, case["date"])
            seeded.append((case["nickname"], work_id, case["title"]))
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    for nickname, work_id, title in seeded:
        print(f"{nickname}: {work_id} — {title}")


if __name__ == "__main__":
    main()
