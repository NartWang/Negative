#!/usr/bin/env python3
"""给已有账号补挂底片示例:订阅底片发布者 + 注入示例作品授权。

配合 demo_seed 服务使用。新账号注册时自动调用,此脚本用于回溯已存在的账号。

示例:
    # 预览将补哪些账号
    python3 scripts/backfill_demo_seed.py

    # 真正执行
    python3 scripts/backfill_demo_seed.py --yes

默认跳过底片账号自己;默认跳过已订阅的(幂等检测)。
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "src/engine"
DB_PATH = Path(os.getenv("ZHIJI_DB_PATH", str(ENGINE / "data" / "zhiji.db")))

DEMO_PUBLISHER_USER_ID = int(os.getenv("DEMO_PUBLISHER_USER_ID", "9"))
PICTUREBOOK_WORK_IDS = [11, 12, 13, 14]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_subscription(conn: sqlite3.Connection, demo_uid: int, subscriber_uid: int) -> int | None:
    """确保 subscriber 已订阅 demo;返回 subscription_id,已存在返回 None。"""
    existing = conn.execute(
        "SELECT id, status FROM subscriptions "
        "WHERE owner_user_id = ? AND subscriber_user_id = ?",
        (demo_uid, subscriber_uid),
    ).fetchone()
    if existing and existing["status"] == "active":
        return None  # 已订阅,跳过

    if existing:
        conn.execute(
            "UPDATE subscriptions SET status = 'active', revoked_at = NULL WHERE id = ?",
            (existing["id"],),
        )
        return existing["id"]
    else:
        now = _now()
        cursor = conn.execute(
            "INSERT INTO subscriptions (owner_user_id, subscriber_user_id, status) "
            "VALUES (?, ?, 'active')",
            (demo_uid, subscriber_uid),
        )
        return cursor.lastrowid


def _ensure_work_audience(conn: sqlite3.Connection, sub_id: int, work_id: int, now: str) -> bool:
    """确保作品对该订阅授予 active 观众权限。返回是否新建或更新。"""
    existing = conn.execute(
        "SELECT status FROM work_audience WHERE work_id = ? AND subscription_id = ?",
        (work_id, sub_id),
    ).fetchone()
    if existing and existing["status"] == "active":
        return False

    conn.execute(
        "INSERT INTO work_audience (work_id, subscription_id, status, granted_at, revoked_at, created_at) "
        "VALUES (?, ?, 'active', ?, NULL, ?) "
        "ON CONFLICT(work_id, subscription_id) DO UPDATE SET "
        "status = 'active', granted_at = excluded.granted_at, revoked_at = NULL",
        (work_id, sub_id, now, now),
    )
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="给已有账号补挂底片示例")
    parser.add_argument("--yes", action="store_true", help="真正执行(默认 dry-run 只预览)")
    args = parser.parse_args()

    if not DB_PATH.exists():
        print(f"数据库不存在: {DB_PATH}", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    dry_run = not args.yes
    try:
        demo_exists = conn.execute(
            "SELECT 1 FROM accounts WHERE user_id = ?", (DEMO_PUBLISHER_USER_ID,)
        ).fetchone()
        if not demo_exists:
            print(f"DEMO_PUBLISHER_USER_ID={DEMO_PUBLISHER_USER_ID} 不存在")
            sys.exit(1)

        # 列出所有账号(除了底片自己)
        users = conn.execute(
            "SELECT user_id, username_norm FROM accounts WHERE user_id != ?",
            (DEMO_PUBLISHER_USER_ID,),
        ).fetchall()
        if not users:
            print("没有可回溯的账号")
            return

        print(f"DEMO_PUBLISHER_USER_ID: {DEMO_PUBLISHER_USER_ID}")
        print(f"绘本 work_ids: {PICTUREBOOK_WORK_IDS}")
        print(f"目标账号: {len(users)} 个\n")

        now = _now()
        for user in users:
            uid = user["user_id"]
            name = user["username_norm"]
            sub_id = _ensure_subscription(conn, DEMO_PUBLISHER_USER_ID, uid)
            already_sub = sub_id is None
            if already_sub:
                sub_row = conn.execute(
                    "SELECT id FROM subscriptions WHERE owner_user_id = ? AND subscriber_user_id = ?",
                    (DEMO_PUBLISHER_USER_ID, uid),
                ).fetchone()
                sub_id = sub_row["id"]

            # 检查各示例作品是否已有授权
            new_audience = 0
            for work_id in PICTUREBOOK_WORK_IDS:
                if _ensure_work_audience(conn, sub_id, work_id, now):
                    new_audience += 1

            if dry_run:
                tag = "[dry-run]"
                print(f"  {name} (uid={uid}): {'已订阅' if already_sub else '新订阅'}, 待授权 {new_audience} 作品 {tag}")
            else:
                print(f"  {name} (uid={uid}): {'已订阅' if already_sub else '新订阅'}, 已授权 {new_audience} 作品")

        if dry_run:
            print("\n[dry-run] 未做任何修改。加 --yes 真正执行。")
        else:
            conn.commit()
            print("\n已提交。")
    finally:
        conn.close()


if __name__ == "__main__":
    main()