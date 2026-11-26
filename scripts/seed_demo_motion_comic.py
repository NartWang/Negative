#!/usr/bin/env python3
"""Seed the judge account's completed motion-comic demo, idempotently."""

from __future__ import annotations

import hashlib
import shutil
import sqlite3
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "src/engine/data/zhiji.db"
VIDEO_DIR = ROOT / "src/engine/data/videos"
SOURCE_VIDEO = Path(
    "/Users/eliash/Library/Containers/com.tencent.xinWeChat/Data/Documents/"
    "xwechat_files/wxid_56hql4gu5p5322_3533/msg/video/2026-08/"
    "248b61e194fd9c8189fc89bb31ec67ca.mp4"
)
SOURCE_SIGNATURE = "demo-motion-comic-case-v1"
CASE_TITLE = "案例故事｜地铁迷宫与黑屏魔王"
SOURCE_WORK_TITLE = "示例故事｜地铁迷宫与黑屏魔王"


def main() -> None:
    content = SOURCE_VIDEO.read_bytes()
    if len(content) < 12 or content[4:8] != b"ftyp":
        raise RuntimeError("the supplied demo is not a valid MP4 file")

    digest = hashlib.sha256(content).hexdigest()
    storage_key = f"{digest[:32]}.mp4"
    asset_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"zhiji-motion-demo:{digest}"))
    VIDEO_DIR.mkdir(parents=True, exist_ok=True)
    destination = VIDEO_DIR / storage_key
    if not destination.exists():
        shutil.copy2(SOURCE_VIDEO, destination)

    connection = sqlite3.connect(DB_PATH)
    try:
        user = connection.execute(
            "SELECT id FROM profile WHERE nickname = '底片'"
        ).fetchone()
        if not user:
            raise RuntimeError("judge account 底片 was not found")
        user_id = int(user[0])

        source = connection.execute(
            """
            SELECT jobs.id, works.id
            FROM story_works AS works
            JOIN picturebook_jobs AS jobs ON jobs.work_id = works.id
            WHERE works.owner_user_id = ? AND works.title = ? AND jobs.status = 'done'
            ORDER BY jobs.id DESC LIMIT 1
            """,
            (user_id, SOURCE_WORK_TITLE),
        ).fetchone()
        if not source:
            raise RuntimeError("run scripts/seed_demo_picturebooks.py before this script")
        picturebook_job_id, work_id = map(int, source)

        connection.execute(
            """
            INSERT OR REPLACE INTO video_assets (
                id, owner_user_id, storage_key, mime_type, size_bytes,
                duration_seconds, created_at
            ) VALUES (?, ?, ?, 'video/mp4', ?, 45, CURRENT_TIMESTAMP)
            """,
            (asset_id, user_id, storage_key, len(content)),
        )

        existing = connection.execute(
            "SELECT id FROM picturebook_video_jobs WHERE user_id = ? AND source_signature = ?",
            (user_id, SOURCE_SIGNATURE),
        ).fetchone()
        timestamp = "2026-07-14T20:30:00Z"
        if existing:
            job_id = int(existing[0])
            connection.execute(
                """
                UPDATE picturebook_video_jobs
                SET picturebook_job_id = ?, work_id = ?, style = 'pixel',
                    model = 'demo', segment_duration = 45, ratio = '16:9',
                    include_cover = 1, page_sequence = '[0,1,2,3,4,5,6,7,8]',
                    status = 'done', stage = 'done', error = NULL,
                    total_segments = 1, asset_id = ?, duration_seconds = 45,
                    updated_at = ?
                WHERE id = ?
                """,
                (picturebook_job_id, work_id, asset_id, timestamp, job_id),
            )
        else:
            cursor = connection.execute(
                """
                INSERT INTO picturebook_video_jobs (
                    user_id, picturebook_job_id, work_id, style, source_signature,
                    model, segment_duration, ratio, seed, include_cover,
                    page_sequence, status, stage, error, total_segments,
                    asset_id, duration_seconds, created_at, updated_at
                ) VALUES (?, ?, ?, 'pixel', ?, 'demo', 45, '16:9', NULL, 1,
                          '[0,1,2,3,4,5,6,7,8]', 'done', 'done', NULL, 1,
                          ?, 45, ?, ?)
                """,
                (user_id, picturebook_job_id, work_id, SOURCE_SIGNATURE,
                 asset_id, timestamp, timestamp),
            )
            job_id = int(cursor.lastrowid)

        connection.commit()
        print(f"Seeded motion comic {job_id}: {CASE_TITLE}")
    finally:
        connection.close()


if __name__ == "__main__":
    main()
