#!/usr/bin/env python3
"""清理体验账号:删除指定账号的全部数据(数据库行 + 磁盘媒体文件)。

对外 Demo 结束后用。给定一个或多个用户名,把它们的账号、日记、绘本/漫剧任务、
作品、订阅、回响互动、配额,以及上传/生成的图片视频文件一并删除。

安全约定:
- 默认 dry-run,只打印将删除的内容,不真正动手;加 --yes 才执行。
- 只删显式列出的账号,绝不动其他账号。
- 磁盘文件按数据库里记录的 storage_key 精确删除,不整目录清空。

示例:
    # 预览将删除 demo01 / demo02 的哪些数据
    python3 scripts/reset_demo_accounts.py demo01 demo02

    # 真正执行
    python3 scripts/reset_demo_accounts.py demo01 demo02 --yes

环境变量 ZHIJI_DB_PATH / ZHIJI_UPLOAD_DIR / ZHIJI_VIDEO_DIR 可覆盖默认路径。
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "src/engine"


def _paths() -> tuple[Path, Path, Path]:
    db = Path(os.getenv("ZHIJI_DB_PATH", str(ENGINE / "data" / "zhiji.db")))
    upload = Path(os.getenv("ZHIJI_UPLOAD_DIR", str(ENGINE / "data" / "uploads")))
    video = Path(os.getenv("ZHIJI_VIDEO_DIR", str(ENGINE / "data" / "videos")))
    return db, upload, video


# 直接按 user_id 删的表(该用户"拥有"的数据)。
# 顺序:先删无外键/弱关联的,再删有 CASCADE 的(accounts/profile 最后,靠级联兜底)。
_OWNED_TABLES = [
    "generation_quotas",
    "motion_comic_drafts",
    "picturebook_video_jobs",   # 其 segments 靠 CASCADE 删
    "picturebook_jobs",         # 其 pages 需手动(无外键),单独处理
    "schedules",
    "checkins",
    "weekly_comics",
    "images",
    "work_likes",               # 该用户作为 viewer 的点赞
    "work_comments",            # 该用户作为 author/viewer 的评论
    "work_responses",
    "responses",
    "post_likes",
    "post_comments",
    "room_temperature_snapshots",
    "room_members",
    "room_posts",
    "room_invites",             # creator / consumed_by
    "rooms",                    # creator
    "subscription_invites",     # owner / accepted_by
    "subscriptions",            # owner / subscriber
    "story_works",              # owner;级联 work_assets/work_audience/story_work_diaries
    "diaries",                  # 级联 story_work_diaries;fragments 单独
    "fragments",
    "dual_timeline_comics",     # user_a_id / user_b_id
    "auth_sessions",
    "character_profiles",
    "accounts",                 # 级联 profile 之外的账号关联
    "profile",
]

# 需要按"非 user_id 列"删除的表: (表, 列)
_CUSTOM_COLUMN_TABLES = [
    ("dual_timeline_comics", ("user_a_id", "user_b_id")),
    ("room_invites", ("creator_user_id", "consumed_by_user_id")),
    ("subscription_invites", ("owner_user_id", "accepted_by_user_id")),
    ("subscriptions", ("owner_user_id", "subscriber_user_id")),
    ("work_comments", ("author_user_id", "viewer_user_id")),
    ("work_likes", ("viewer_user_id",)),
    ("work_responses", ("author_user_id",)),
    ("responses", ("author_user_id",)),
    ("post_comments", ("author_user_id",)),
    ("room_invites", ("creator_user_id", "consumed_by_user_id")),
]


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _user_id(conn: sqlite3.Connection, username: str) -> int | None:
    row = conn.execute(
        "SELECT user_id FROM accounts WHERE username_norm = ?",
        (username.strip().casefold(),),
    ).fetchone()
    return int(row[0]) if row else None


def _collect_media_keys(conn: sqlite3.Connection, user_id: int) -> tuple[list[str], list[str]]:
    """返回该用户拥有的 (图片 storage_keys, 视频 storage_keys)。"""
    image_keys: list[str] = []
    video_keys: list[str] = []
    if _table_exists(conn, "media_assets"):
        image_keys = [
            r[0]
            for r in conn.execute(
                "SELECT storage_key FROM media_assets WHERE owner_user_id = ?", (user_id,)
            )
        ]
    if _table_exists(conn, "video_assets"):
        video_keys = [
            r[0]
            for r in conn.execute(
                "SELECT storage_key FROM video_assets WHERE owner_user_id = ?", (user_id,)
            )
        ]
    return image_keys, video_keys


def _delete_user_rows(conn: sqlite3.Connection, user_id: int) -> dict[str, int]:
    """删除该用户在各表中的行,返回每表删除条数。幂等、只动该用户。"""
    deleted: dict[str, int] = {}

    def run(table: str, where: str, params: tuple) -> None:
        if not _table_exists(conn, table):
            return
        cur = conn.execute(f"DELETE FROM {table} WHERE {where}", params)
        if cur.rowcount:
            deleted[table] = deleted.get(table, 0) + cur.rowcount

    # 1. 先删通过 job 关联、自身无 user_id 的子表。
    if _table_exists(conn, "picturebook_pages") and _table_exists(conn, "picturebook_jobs"):
        run(
            "picturebook_pages",
            "job_id IN (SELECT id FROM picturebook_jobs WHERE user_id = ?)",
            (user_id,),
        )
    if _table_exists(conn, "picturebook_video_segments") and _table_exists(
        conn, "picturebook_video_jobs"
    ):
        run(
            "picturebook_video_segments",
            "video_job_id IN (SELECT id FROM picturebook_video_jobs WHERE user_id = ?)",
            (user_id,),
        )

    # 2. 多列归属的表(任一列命中即删)。
    handled = set()
    for table, cols in _CUSTOM_COLUMN_TABLES:
        if not _table_exists(conn, table):
            continue
        existing = [c for c in cols if c in _columns(conn, table)]
        if not existing:
            continue
        where = " OR ".join(f"{c} = ?" for c in existing)
        run(table, where, tuple([user_id] * len(existing)))
        handled.add(table)

    # 3. 单 user_id 列的表。
    for table in _OWNED_TABLES:
        if table in handled or not _table_exists(conn, table):
            continue
        cols = _columns(conn, table)
        if "user_id" in cols:
            run(table, "user_id = ?", (user_id,))
        elif "owner_user_id" in cols:
            run(table, "owner_user_id = ?", (user_id,))
        elif table == "profile" and "id" in cols:
            run(table, "id = ?", (user_id,))

    # 4. 该用户拥有的媒体资产行(文件在删行前先已收集)。
    run("media_assets", "owner_user_id = ?", (user_id,))
    run("video_assets", "owner_user_id = ?", (user_id,))

    return deleted


def _delete_files(keys: list[str], base: Path, dry_run: bool) -> int:
    count = 0
    for key in keys:
        # 防路径穿越:只取文件名部分。
        safe = Path(key).name
        target = (base / safe).resolve()
        if target.parent != base.resolve():
            continue
        if target.exists():
            count += 1
            if not dry_run:
                target.unlink()
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description="清理体验账号的全部数据")
    parser.add_argument("usernames", nargs="+", help="要清理的账号用户名(登录名)")
    parser.add_argument("--yes", action="store_true", help="真正执行(默认 dry-run 只预览)")
    args = parser.parse_args()

    db_path, upload_dir, video_dir = _paths()
    if not db_path.exists():
        print(f"数据库不存在: {db_path}", file=sys.stderr)
        sys.exit(1)

    dry_run = not args.yes
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        for username in args.usernames:
            uid = _user_id(conn, username)
            if uid is None:
                print(f"[跳过] 账号不存在: {username}")
                continue

            image_keys, video_keys = _collect_media_keys(conn, uid)
            print(f"\n=== {username} (user_id={uid}) ===")

            if dry_run:
                # 预览:统计各表将删多少行。
                for table in _OWNED_TABLES:
                    if not _table_exists(conn, table):
                        continue
                    cols = _columns(conn, table)
                    col = "user_id" if "user_id" in cols else (
                        "owner_user_id" if "owner_user_id" in cols else (
                            "id" if table == "profile" else None))
                    if col:
                        n = conn.execute(
                            f"SELECT COUNT(*) FROM {table} WHERE {col} = ?", (uid,)
                        ).fetchone()[0]
                        if n:
                            print(f"  {table}: {n} 行")
                print(f"  图片文件: {len(image_keys)} 个, 视频文件: {len(video_keys)} 个")
            else:
                deleted = _delete_user_rows(conn, uid)
                img_n = _delete_files(image_keys, upload_dir, dry_run=False)
                vid_n = _delete_files(video_keys, video_dir, dry_run=False)
                for table, n in sorted(deleted.items()):
                    print(f"  删除 {table}: {n} 行")
                print(f"  删除图片文件: {img_n} 个, 视频文件: {vid_n} 个")

        if not dry_run:
            conn.commit()
            print("\n已提交。")
        else:
            print("\n[dry-run] 未做任何修改。加 --yes 真正执行。")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
