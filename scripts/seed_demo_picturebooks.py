#!/usr/bin/env python3
"""Seed four complete, idempotent picturebook demos for the judge account."""

from __future__ import annotations

import hashlib
import shutil
import sqlite3
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "src/engine/data/zhiji.db"
UPLOAD_DIR = ROOT / "src/engine/data/uploads"
SOURCE_ROOT = ROOT.parent / "Q版2D像素角色App接入包"

CASES = [
    {
        "title": "示例故事｜地铁迷宫与黑屏魔王",
        "date": "2026-07-14",
        "style": "pixel",
        "published": True,
        "folder": SOURCE_ROOT / "像素风绘本测试/11_Image2完整绘本_温柔姐姐版",
        "captions": [
            "忙碌工作日被保存成一场温柔的像素冒险。",
            "早晨迟到的二十分钟，让今天从限时任务开始。",
            "她穿过拥挤的早高峰，像走进一座地铁迷宫。",
            "刚到工位，任务板上的工作突然增加。",
            "午间补给很短，但一杯咖啡让她重新站稳。",
            "下午三点的困意，成了今天需要面对的小 Boss。",
            "下班线以前，她完成了最后一次认真修改。",
            "晚上七点半，今天最重要的任务终于提交。",
            "回到家按下保存键，她为普通的一天留下存档点。",
        ],
    },
    {
        "title": "示例故事｜闹钟响起以前",
        "legacy_title": "示例故事｜雨停以前，我认真生活",
        "date": "2026-07-22",
        "style": "sketch",
        "published": True,
        "folder": SOURCE_ROOT / "素描风绘本测试/09_运行结果_闹钟响起以前",
        "captions": [
            "雨天里那些很小的照顾，也值得被认真画下来。",
            "第二次铃声响起，她终于从雨声中醒来。",
            "她撑着蓝伞，慢慢挤进潮湿的早高峰。",
            "上午的计划被临时消息改写，她重新整理清单。",
            "短短十五分钟，让紧绷的上午有了一点呼吸。",
            "她重新打开文件，从最小的一步继续向前。",
            "五点后的新消息没有打乱她刚找回的节奏。",
            "关机以后，雨停了，街灯在湿路面上亮起来。",
            "她为明天设好闹钟，也把今天轻轻收好。",
        ],
    },
    {
        "title": "示例故事｜通勤包里的一天",
        "legacy_title": "示例故事｜办公室里长出了一棵星期树",
        "date": "2026-07-29",
        "style": "crayon",
        "published": True,
        "folder": SOURCE_ROOT / "蜡笔风绘本测试/通勤包里的一天_Image2成品",
        "captions": [
            "一只通勤包，装下了星期一的忙乱和一点期待。",
            "早晨晚了十五分钟，她背起包匆匆出门。",
            "拥挤的车厢把每个人都挤成一张薄薄的纸。",
            "到达工位以后，新的任务纸片开始排队。",
            "午休的十分钟，是今天难得安静的一小格。",
            "刚完成一项工作，新的纸片又落进通勤包。",
            "她把事情一张一张折好，重新排出先后顺序。",
            "文件提交以后，沉重的纸片终于飞出窗外。",
            "回到家，包里还留着一小块属于周末的期待。",
        ],
    },
    {
        "title": "示例故事｜按下保存键以后",
        "legacy_titles": [
            "示例故事｜保存今天的人",
            "示例故事｜妈妈寄来的那场春天",
        ],
        "date": "2026-07-08",
        "style": "watercolor",
        "published": True,
        "folder": SOURCE_ROOT / "水彩风绘本测试/11_保存今天的人_九张成图",
        "captions": [
            "远方寄来的包裹，让出租屋里慢慢晕开一点春天。",
            "闹钟响起时，她又从一个匆忙的早晨出发。",
            "人还没到公司，工作已经先一步抵达。",
            "咖啡还没有变凉，她已经开始处理新的事情。",
            "午间十分钟的安静，让身体重新回到自己身边。",
            "差一点消失的表格，被她耐心地重新找回来。",
            "她把问题一行一行改清楚，也把慌乱慢慢放下。",
            "下班前按下提交，今天终于有了清楚的句点。",
            "街道尽头亮起暖光，她带着被保存的今天回家。",
        ],
    },
]


def image_files(folder: Path) -> list[Path]:
    files = sorted(
        path for path in folder.iterdir()
        if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
        and path.name[:2].isdigit()
        and path.name[:2] in {f"{index:02d}" for index in range(9)}
    )
    if len(files) != 9:
        raise RuntimeError(f"{folder} should contain exactly 9 story images, found {len(files)}")
    return files


def store_image(connection: sqlite3.Connection, user_id: int, source: Path) -> tuple[str, str]:
    content = source.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    suffix = source.suffix.lower().replace(".jpeg", ".jpg")
    storage_key = f"{digest[:32]}{suffix}"
    mime_type = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".webp": "image/webp",
    }[suffix]
    asset_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"zhiji-demo:{digest}"))
    destination = UPLOAD_DIR / storage_key
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    if not destination.exists():
        shutil.copy2(source, destination)
    connection.execute(
        """
        INSERT OR IGNORE INTO media_assets (
            id, owner_user_id, storage_key, mime_type, size_bytes, created_at
        ) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """,
        (asset_id, user_id, storage_key, mime_type, len(content)),
    )
    return asset_id, f"/api/media/{asset_id}"


def seed_case(connection: sqlite3.Connection, user_id: int, case: dict) -> tuple[int, bool]:
    timestamp = f"{case['date']}T12:00:00Z"
    candidate_titles = [case["title"]]
    if case.get("legacy_title"):
        candidate_titles.append(case["legacy_title"])
    candidate_titles.extend(case.get("legacy_titles", []))
    placeholders = ", ".join("?" for _ in candidate_titles)
    existing = connection.execute(
        f"SELECT id, title FROM story_works WHERE owner_user_id = ? AND title IN ({placeholders})",
        (user_id, *candidate_titles),
    ).fetchone()
    if existing:
        work_id = int(existing[0])
        status = "published" if case["published"] else "ready"
        connection.execute(
            """
            UPDATE story_works
            SET title = ?, source_start_date = ?, source_end_date = ?,
                display_start_date = ?, display_end_date = ?, status = ?,
                created_at = ?, updated_at = ?, stage_updated_at = ?, published_at = ?
            WHERE id = ?
            """,
            (
                case["title"], case["date"], case["date"], case["date"], case["date"],
                status,
                timestamp, timestamp, timestamp, timestamp if case["published"] else None,
                work_id,
            ),
        )
        connection.execute(
            "UPDATE picturebook_jobs SET created_at = ?, updated_at = ? WHERE work_id = ?",
            (timestamp, timestamp, work_id),
        )
        return work_id, False

    status = "published" if case["published"] else "ready"
    cursor = connection.execute(
        """
        INSERT INTO story_works (
            owner_user_id, source_diary_id, title, medium, narrative_mode,
            style, selected_segments_json, status, kind, stage,
            source_snapshot_json, source_snapshot_hash,
            source_start_date, source_end_date, display_start_date, display_end_date,
            created_at, updated_at, stage_updated_at, published_at
        ) VALUES (?, NULL, ?, 'picture_book', 'true_record', ?, '[]', ?,
                  'daily_picturebook', 'ready', '[]', ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id, case["title"], case["style"], status,
            hashlib.sha256(case["title"].encode()).hexdigest(),
            case["date"], case["date"], case["date"], case["date"],
            timestamp, timestamp, timestamp, timestamp if case["published"] else None,
        ),
    )
    work_id = int(cursor.lastrowid)
    job_cursor = connection.execute(
        """
        INSERT INTO picturebook_jobs (
            user_id, diary_id, work_id, source_text, source_signature,
            allow_imaginative, style, status, stage, error, character_signature,
            total_pages, created_at, updated_at
        ) VALUES (?, NULL, ?, ?, ?, 0, ?, 'done', 'done', NULL, 'demo-ahe', 9, ?, ?)
        """,
        (
            user_id, work_id, "\n".join(case["captions"]),
            hashlib.sha256((case["title"] + case["date"]).encode()).hexdigest(),
            case["style"], timestamp, timestamp,
        ),
    )
    job_id = int(job_cursor.lastrowid)

    for index, (source, caption) in enumerate(zip(image_files(case["folder"]), case["captions"])):
        asset_id, url = store_image(connection, user_id, source)
        connection.execute(
            """
            INSERT INTO picturebook_pages (
                job_id, page_index, image_id, caption, image_prompt,
                asset_id, image_url, status, error, created_at, updated_at
            ) VALUES (?, ?, ?, ?, '演示案例使用既有成图', ?, ?, 'ready', NULL, ?, ?)
            """,
            (job_id, index, "cover" if index == 0 else f"page-{index}", caption,
             asset_id, url, timestamp, timestamp),
        )
        connection.execute(
            """
            INSERT INTO work_assets (
                work_id, ordinal, asset_type, url, asset_id, text, prompt, created_at
            ) VALUES (?, ?, 'image', ?, ?, ?, '演示案例使用既有成图', ?)
            """,
            (work_id, index, url, asset_id, caption, timestamp),
        )

    cover_asset_id = connection.execute(
        "SELECT asset_id FROM picturebook_pages WHERE job_id = ? AND page_index = 0",
        (job_id,),
    ).fetchone()[0]
    connection.execute(
        "UPDATE story_works SET picturebook_job_id = ?, cover_asset_id = ? WHERE id = ?",
        (job_id, cover_asset_id, work_id),
    )
    return work_id, True


def main() -> None:
    connection = sqlite3.connect(DB_PATH)
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        account = connection.execute(
            "SELECT user_id FROM accounts WHERE username_norm = ?",
            ("底片",),
        ).fetchone()
        if not account:
            raise RuntimeError("judge account 底片 does not exist")
        user_id = int(account[0])
        created = []
        connection.execute("BEGIN IMMEDIATE")
        for case in CASES:
            work_id, was_created = seed_case(connection, user_id, case)
            created.append((work_id, case["title"], was_created, case["published"]))
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

    for work_id, title, was_created, published in created:
        state = "created" if was_created else "already exists"
        destination = "底片夹 + 回响" if published else "底片夹"
        print(f"{work_id}: {title} — {state} — {destination}")


if __name__ == "__main__":
    main()
