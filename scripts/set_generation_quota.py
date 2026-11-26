#!/usr/bin/env python3
"""设置/查询体验账号的生成配额(绘本 / 漫剧可新建次数)。

对外 Demo 用法:体验账号默认额度为 0,无法新建任何生成任务;用本脚本按需充值。
账号不存在时会先报错,避免给 typo 用户名开了无效额度。

示例:
    # 给 username=demo01 充值:绘本 3 次、漫剧 2 次
    python3 scripts/set_generation_quota.py demo01 --picturebook 3 --motion-comic 2

    # 只加漫剧 1 次(在现有余额上累加)
    python3 scripts/set_generation_quota.py demo01 --motion-comic +1

    # 查看一个或多个账号当前额度;不带用户名则列出全部
    python3 scripts/set_generation_quota.py demo01 --show
    python3 scripts/set_generation_quota.py --show

环境变量 ZHIJI_DB_PATH 可覆盖数据库路径,默认读 src/engine/data/zhiji.db。
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "src/engine/data/zhiji.db"
VALID_CATEGORIES = ("picturebook", "motion_comic")


def _db_path() -> Path:
    return Path(os.getenv("ZHIJI_DB_PATH", str(DEFAULT_DB)))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _user_id(conn: sqlite3.Connection, username: str) -> int | None:
    row = conn.execute(
        "SELECT user_id FROM accounts WHERE username_norm = ?",
        (username.strip().casefold(),),
    ).fetchone()
    return int(row[0]) if row else None


def _parse_delta(value: str) -> tuple[str, int]:
    """'+2' / '-1' 表示在现有余额上累加;'3' 表示直接覆盖为 3。"""
    text = value.strip()
    if text.startswith(("+", "-")):
        return ("add", int(text))
    return ("set", int(text))


def _apply(conn: sqlite3.Connection, user_id: int, category: str, spec: str) -> int:
    mode, value = _parse_delta(spec)
    row = conn.execute(
        "SELECT remaining FROM generation_quotas WHERE user_id = ? AND category = ?",
        (user_id, category),
    ).fetchone()
    current = int(row[0]) if row else 0
    new_value = max(0, current + value) if mode == "add" else value
    if new_value < 0:
        new_value = 0
    conn.execute(
        "INSERT INTO generation_quotas (user_id, category, remaining, updated_at) "
        "VALUES (?, ?, ?, ?) "
        "ON CONFLICT (user_id, category) "
        "DO UPDATE SET remaining = excluded.remaining, updated_at = excluded.updated_at",
        (user_id, category, new_value, _now()),
    )
    return new_value


def _show(conn: sqlite3.Connection, username: str | None) -> None:
    if username:
        uid = _user_id(conn, username)
        if uid is None:
            print(f"账号不存在: {username}", file=sys.stderr)
            sys.exit(1)
        rows = conn.execute(
            "SELECT user_id, category, remaining, updated_at FROM generation_quotas "
            "WHERE user_id = ? ORDER BY category",
            (uid,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT user_id, category, remaining, updated_at FROM generation_quotas "
            "ORDER BY user_id, category"
        ).fetchall()
    if not rows:
        print("（没有任何配额记录——所有账号默认额度 0，无法新生成）")
        return
    print(f"{'user_id':<8} {'category':<14} {'remaining':<10} updated_at")
    for user_id, category, remaining, updated_at in rows:
        print(f"{user_id:<8} {category:<14} {remaining:<10} {updated_at}")


def main() -> None:
    parser = argparse.ArgumentParser(description="设置/查询体验账号的生成配额")
    parser.add_argument("username", nargs="?", help="目标账号用户名(登录名)")
    parser.add_argument("--picturebook", metavar="N", help="绘本次数:'3' 覆盖 / '+1' 累加")
    parser.add_argument("--motion-comic", metavar="N", help="漫剧次数:'2' 覆盖 / '+1' 累加")
    parser.add_argument("--show", action="store_true", help="只查看不修改")
    args = parser.parse_args()

    db_path = _db_path()
    if not db_path.exists():
        print(f"数据库不存在: {db_path}", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(str(db_path))
    try:
        if args.show or (args.picturebook is None and args.motion_comic is None):
            _show(conn, args.username)
            return

        if not args.username:
            parser.error("设置额度时必须提供用户名")
        uid = _user_id(conn, args.username)
        if uid is None:
            print(f"账号不存在: {args.username}", file=sys.stderr)
            sys.exit(1)

        if args.picturebook is not None:
            n = _apply(conn, uid, "picturebook", args.picturebook)
            print(f"{args.username} 绘本额度 -> {n}")
        if args.motion_comic is not None:
            n = _apply(conn, uid, "motion_comic", args.motion_comic)
            print(f"{args.username} 漫剧额度 -> {n}")
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    main()
