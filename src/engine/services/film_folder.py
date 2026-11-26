"""底片夹读模型:当前用户的绘本集、漫剧集、活动任务与未完成列表。

只读聚合,不搬动历史媒体:
- 完成绘本复用 story_days 的 canonical/historical 归一化逻辑;
- 完成漫剧从 picturebook_video_jobs(status=done 且 asset_id 有效)读取,
  标题/日期/封面通过来源绘本解析;
- active_generation 每分区至多一条(由 generation_slots 守卫保证);
- 未完成列表只含可恢复任务,运行中任务不出现。
- demo_seed: 若当前用户订阅了 DEMO_PUBLISHER_USER_ID,在底片夹列表顶部置入其示例作品作为只读参考。
"""

from __future__ import annotations

import config
from services.demo_seed import is_demo_subscriber

from typing import Any, Optional

from services.story_days import list_completed_picturebooks
from services.story_workflow import sanitize_generation_error
from services.generation_quota import remaining_quota
from services.generation_slots import CATEGORY_MOTION_COMIC, CATEGORY_PICTUREBOOK


class PicturebookDeleteError(ValueError):
    pass


async def delete_picturebook(
    db: Any, user_id: int, source_kind: str, source_id: int
) -> None:
    """Permanently remove one owned completed picturebook, never its diaries."""
    if source_kind == "canonical_work":
        cursor = await db.execute(
            "SELECT id FROM story_works WHERE id = ? AND owner_user_id = ?",
            (source_id, user_id),
        )
        if not await cursor.fetchone():
            raise PicturebookDeleteError("picturebook not found")
        cursor = await db.execute(
            "SELECT id, status FROM picturebook_jobs WHERE work_id = ? AND user_id = ?",
            (source_id, user_id),
        )
        jobs = [dict(row) for row in await cursor.fetchall()]
        if any(job["status"] == "running" for job in jobs):
            raise PicturebookDeleteError("picturebook is still generating")
        job_ids = [int(job["id"]) for job in jobs]
        await db.execute("BEGIN IMMEDIATE")
        try:
            for job_id in job_ids:
                await db.execute("DELETE FROM picturebook_pages WHERE job_id = ?", (job_id,))
                await db.execute(
                    "DELETE FROM picturebook_video_segments WHERE video_job_id IN "
                    "(SELECT id FROM picturebook_video_jobs WHERE picturebook_job_id = ? AND user_id = ?)",
                    (job_id, user_id),
                )
                await db.execute(
                    "DELETE FROM picturebook_video_jobs WHERE picturebook_job_id = ? AND user_id = ?",
                    (job_id, user_id),
                )
            await db.execute(
                "DELETE FROM picturebook_jobs WHERE work_id = ? AND user_id = ?",
                (source_id, user_id),
            )
            await db.execute(
                "DELETE FROM story_works WHERE id = ? AND owner_user_id = ?",
                (source_id, user_id),
            )
            await db.commit()
        except Exception:
            await db.rollback()
            raise
        return

    if source_kind == "historical_job":
        cursor = await db.execute(
            "SELECT id, status FROM picturebook_jobs "
            "WHERE id = ? AND user_id = ? AND work_id IS NULL",
            (source_id, user_id),
        )
        row = await cursor.fetchone()
        if not row:
            raise PicturebookDeleteError("picturebook not found")
        if row["status"] == "running":
            raise PicturebookDeleteError("picturebook is still generating")
        await db.execute("BEGIN IMMEDIATE")
        try:
            await db.execute("DELETE FROM picturebook_pages WHERE job_id = ?", (source_id,))
            await db.execute(
                "DELETE FROM picturebook_video_segments WHERE video_job_id IN "
                "(SELECT id FROM picturebook_video_jobs WHERE picturebook_job_id = ? AND user_id = ?)",
                (source_id, user_id),
            )
            await db.execute(
                "DELETE FROM picturebook_video_jobs WHERE picturebook_job_id = ? AND user_id = ?",
                (source_id, user_id),
            )
            await db.execute(
                "DELETE FROM picturebook_jobs WHERE id = ? AND user_id = ?",
                (source_id, user_id),
            )
            await db.commit()
        except Exception:
            await db.rollback()
            raise
        return

    raise PicturebookDeleteError("picturebook not found")


def _row_dict(row: Any) -> dict:
    return dict(row)


# --------------------------------------------------------------------- picturebooks


async def _active_picturebook(db: Any, user_id: int) -> Optional[dict]:
    cursor = await db.execute(
        """
        SELECT id, stage, status, total_pages, updated_at
        FROM picturebook_jobs
        WHERE user_id = ? AND status = 'running'
        ORDER BY updated_at DESC, id DESC
        LIMIT 1
        """,
        (user_id,),
    )
    row = await cursor.fetchone()
    if not row:
        return None
    job = _row_dict(row)
    cursor = await db.execute(
        "SELECT COUNT(*) AS count FROM picturebook_pages "
        "WHERE job_id = ? AND status = 'ready'",
        (job["id"],),
    )
    ready = (await cursor.fetchone())["count"]
    return {
        "id": job["id"],
        "stage": job["stage"],
        "status": job["status"],
        "total": job["total_pages"],
        "ready": ready,
        "updated_at": job["updated_at"],
    }


async def _unfinished_picturebooks(db: Any, user_id: int) -> list[dict]:
    """可恢复绘本:可重试的失败任务,或从未开始出图的 draft 作品。

    标识约定:canonical 作品项的 id 始终是 work_id(前端按它进入创作向导),
    job_id 单独给出;历史遗留任务项的 id 与 job_id 都是原任务 id。
    """
    # canonical 失败作品:仍是 draft/render_failed 且确实有失败任务。
    # 已完成(ready/published)作品的陈旧失败尝试永不出现在这里。
    cursor = await db.execute(
        """
        SELECT work.id AS work_id, work.kind AS work_kind, work.title AS work_title,
               work.style AS work_style, work.stage AS work_stage,
               work.display_start_date AS work_start_date,
               work.display_end_date AS work_end_date,
               work.updated_at AS work_updated_at,
               job.id AS job_id, job.error AS job_error, job.updated_at AS job_updated_at
        FROM story_works AS work
        JOIN picturebook_jobs AS job
          ON job.work_id = work.id AND job.user_id = work.owner_user_id
         AND job.status = 'failed'
        WHERE work.owner_user_id = ?
          AND work.status = 'draft'
          AND work.stage = 'render_failed'
        ORDER BY job.updated_at DESC, job.id DESC
        """,
        (user_id,),
    )
    items: list[dict] = []
    canonical_work_ids: set[int] = set()
    for row in (_row_dict(item) for item in await cursor.fetchall()):
        work_id = row["work_id"]
        # 一部作品只保留最近一次失败尝试(updated_at DESC, id DESC 的首行)。
        if work_id in canonical_work_ids:
            continue
        canonical_work_ids.add(work_id)
        items.append(
            {
                "id": work_id,
                "job_id": row["job_id"],
                "source_kind": "canonical_work",
                "work_kind": row["work_kind"],
                "style": row["work_style"],
                "stage": row["work_stage"],
                "title": row["work_title"],
                "display_start_date": row["work_start_date"],
                "display_end_date": row["work_end_date"],
                "error": sanitize_generation_error(row["job_error"]),
                "updated_at": row["job_updated_at"] or row["work_updated_at"],
            }
        )

    # 历史遗留失败任务(无作品归属),按日记日期展示。
    cursor = await db.execute(
        """
        SELECT job.id AS job_id, job.error AS job_error, job.updated_at AS job_updated_at,
               job.style AS job_style, job.stage AS job_stage,
               diary.date AS diary_date
        FROM picturebook_jobs AS job
        LEFT JOIN diaries AS diary
          ON diary.id = job.diary_id AND diary.user_id = job.user_id
        WHERE job.user_id = ?
          AND job.status = 'failed'
          AND job.work_id IS NULL
        ORDER BY job.updated_at DESC, job.id DESC
        """,
        (user_id,),
    )
    for row in (_row_dict(item) for item in await cursor.fetchall()):
        items.append(
            {
                "id": row["job_id"],
                "job_id": row["job_id"],
                "source_kind": "historical_job",
                "work_kind": None,
                "style": row["job_style"],
                "stage": row["job_stage"],
                "title": f"{row['diary_date'] or ''} 绘本".strip(),
                "display_start_date": row["diary_date"],
                "display_end_date": row["diary_date"],
                "error": sanitize_generation_error(row["job_error"]),
                "updated_at": row["job_updated_at"],
            }
        )

    # 从未开始出图、也没有活动任务指针的 draft 作品;
    # 已被失败记录覆盖的作品不重复追加。
    cursor = await db.execute(
        """
        SELECT id, kind, title, style, stage, display_start_date, display_end_date, updated_at
        FROM story_works
        WHERE owner_user_id = ?
          AND status = 'draft'
          AND kind IN ('daily_picturebook', 'time_story')
          AND active_picturebook_job_id IS NULL
          AND picturebook_job_id IS NULL
        ORDER BY updated_at DESC, id DESC
        """,
        (user_id,),
    )
    for row in (_row_dict(item) for item in await cursor.fetchall()):
        if row["id"] in canonical_work_ids:
            continue
        items.append(
            {
                "id": row["id"],
                "job_id": None,
                "source_kind": "canonical_work",
                "work_kind": row["kind"],
                "style": row["style"],
                "stage": row["stage"],
                "title": row["title"],
                "display_start_date": row["display_start_date"],
                "display_end_date": row["display_end_date"],
                "error": None,
                "updated_at": row["updated_at"],
            }
        )
    items.sort(key=lambda item: (item["updated_at"] or "", item["id"]), reverse=True)
    return items


def _summary_item(book: dict) -> dict:
    return {
        "id": book["source_id"],
        "source_kind": book["source_kind"],
        "work_kind": book["work_kind"],
        "title": book["title"],
        "display_start_date": book["start_date"],
        "display_end_date": book["end_date"],
        "cover_url": book["cover_url"],
        "completed_at": book["completed_at"] or "",
        "published": bool(book.get("published")),
    }


async def _demo_picturebook_items(db: Any, user_id: int) -> list[dict]:
    """若当前用户是 DEMO 发布者的订阅者,返回其示例绘本摘要列表。"""
    if not await is_demo_subscriber(db, user_id=user_id):
        return []
    demo_user_id = config.DEMO_PUBLISHER_USER_ID
    if demo_user_id <= 0:
        return []
    work_ids = config.DEMO_PICTUREBOOK_WORK_IDS
    if not work_ids:
        return []
    placeholders = ", ".join("?" for _ in work_ids)
    cursor = await db.execute(
        f"""
        SELECT work.id, work.kind, work.title, work.status,
               work.display_start_date, work.display_end_date,
               job.updated_at AS completed_at,
               cover.url AS cover_url
        FROM story_works AS work
        JOIN picturebook_jobs AS job
          ON job.id = work.picturebook_job_id
         AND job.user_id = work.owner_user_id
         AND job.status = 'done'
        LEFT JOIN work_assets AS cover
          ON cover.work_id = work.id
         AND cover.ordinal = 0
         AND cover.asset_type = 'image'
        WHERE work.id IN ({placeholders})
          AND work.owner_user_id = ?
          AND work.status IN ('ready', 'published')
        ORDER BY work.display_start_date DESC, work.id DESC
        """,
        (*work_ids, demo_user_id),
    )
    items = []
    for row in await cursor.fetchall():
        items.append(
            {
                "id": row["id"],
                "source_kind": "canonical_work",
                "work_kind": row["kind"] or "daily_picturebook",
                "title": (row["title"] or "").strip(),
                "display_start_date": row["display_start_date"] or "",
                "display_end_date": row["display_end_date"] or "",
                "cover_url": row["cover_url"],
                "completed_at": row["completed_at"] or "",
                "published": row["status"] == "published",
                "is_demo_seed": True,
                "read_only": True,
            }
        )
    return items


async def _demo_motion_comic_item(db: Any, user_id: int) -> Optional[dict]:
    if not await is_demo_subscriber(db, user_id=user_id):
        return None
    demo_user_id = config.DEMO_PUBLISHER_USER_ID
    video_job_id = config.DEMO_MOTION_COMIC_VIDEO_JOB_ID
    if demo_user_id <= 0 or video_job_id <= 0:
        return None
    cursor = await db.execute(
        """
        SELECT job.id, job.work_id, job.status, job.updated_at,
               work.title AS work_title, work.kind AS work_kind,
               work.display_start_date, work.display_end_date,
               cover.url AS cover_url
        FROM picturebook_video_jobs AS job
        LEFT JOIN story_works AS work
          ON work.id = job.work_id
         AND work.owner_user_id = job.user_id
        LEFT JOIN work_assets AS cover
          ON cover.work_id = work.id
         AND cover.ordinal = 0
         AND cover.asset_type = 'image'
        WHERE job.id = ?
          AND job.user_id = ?
          AND job.status = 'done'
          AND job.asset_id IS NOT NULL
        """,
        (video_job_id, demo_user_id),
    )
    row = await cursor.fetchone()
    if not row:
        return None
    return {
        "id": row["id"],
        "source_kind": "video_job",
        "work_kind": row["work_kind"] or "daily_picturebook",
        "title": (row["work_title"] or "").strip(),
        "display_start_date": row["display_start_date"] or "",
        "display_end_date": row["display_end_date"] or "",
        "cover_url": row["cover_url"],
        "completed_at": row["updated_at"] or "",
        "video_url": f"/api/picturebook-video/{row['id']}/file",
        "is_demo_seed": True,
        "read_only": True,
    }


async def list_picturebook_collection(db: Any, user_id: int) -> dict:
    books = await list_completed_picturebooks(db, user_id)
    unfinished = await _unfinished_picturebooks(db, user_id)
    demo_items = await _demo_picturebook_items(db, user_id)
    own_items = [_summary_item(book) for book in books]
    return {
        "active_generation": await _active_picturebook(db, user_id),
        "unfinished_count": len(unfinished),
        "items": [*demo_items, *own_items],
        "remaining": await remaining_quota(
            db, user_id=user_id, category=CATEGORY_PICTUREBOOK
        ),
    }


async def list_unfinished_picturebooks(db: Any, user_id: int) -> dict:
    return {"items": await _unfinished_picturebooks(db, user_id)}


async def get_picturebook_detail(
    db: Any, user_id: int, source_kind: str, source_id: int
) -> Optional[dict]:
    """按摘要键读取完整绘本(含页面),供阅读器使用。支持 cross-owner demo seed 示例。"""
    books = await list_completed_picturebooks(db, user_id)
    for book in books:
        if book["source_kind"] == source_kind and book["source_id"] == source_id:
            return {
                "id": book["source_id"],
                "source_kind": book["source_kind"],
                "work_kind": book["work_kind"],
                "title": book["title"],
                "display_start_date": book["start_date"],
                "display_end_date": book["end_date"],
                "cover_url": book["cover_url"],
                "completed_at": book["completed_at"] or "",
                "pages": book["pages"],
            }

    # 用户作品中未找到:可能是 demo seed 示例——检查订阅关系后跨用户查询。
    if (
        source_kind == "canonical_work"
        and source_id in config.DEMO_PICTUREBOOK_WORK_IDS
        and await is_demo_subscriber(db, user_id=user_id)
    ):
        demo_user_id = config.DEMO_PUBLISHER_USER_ID
        cursor = await db.execute(
            """
            SELECT work.id, work.title, work.kind, work.status,
                   work.display_start_date, work.display_end_date,
                   job.updated_at AS completed_at,
                   cover.url AS cover_url
            FROM story_works AS work
            JOIN picturebook_jobs AS job
              ON job.id = work.picturebook_job_id
             AND job.user_id = work.owner_user_id
             AND job.status = 'done'
            LEFT JOIN work_assets AS cover
              ON cover.work_id = work.id
             AND cover.ordinal = 0
             AND cover.asset_type = 'image'
            WHERE work.id = ? AND work.owner_user_id = ?
            """,
            (source_id, demo_user_id),
        )
        demo_work = await cursor.fetchone()
        if demo_work is None:
            return None
        pages_cursor = await db.execute(
            """
            SELECT asset.ordinal AS page_index, asset.url, asset.asset_id,
                   asset.text AS caption
            FROM work_assets AS asset
            JOIN story_works AS work
              ON work.id = asset.work_id
             AND work.owner_user_id = ?
            WHERE asset.work_id = ?
              AND asset.asset_type = 'image'
            ORDER BY asset.ordinal ASC
            """,
            (demo_user_id, source_id),
        )
        from services.story_days import _complete_picturebook_pages

        pages_rows = await pages_cursor.fetchall()
        pages = _complete_picturebook_pages(
            [dict(zip(["page_index", "url", "asset_id", "caption"], row)) for row in pages_rows]
        )
        if pages is None:
            return None
        return {
            "id": demo_work["id"],
            "source_kind": "canonical_work",
            "work_kind": demo_work["kind"] or "daily_picturebook",
            "title": (demo_work["title"] or "").strip(),
            "display_start_date": demo_work["display_start_date"] or "",
            "display_end_date": demo_work["display_end_date"] or "",
            "cover_url": demo_work["cover_url"],
            "completed_at": demo_work["completed_at"] or "",
            "pages": pages,
        }
    return None


async def list_time_stories(db: Any, user_id: int) -> dict:
    """只含正式完成、9 页完整的 time_story 作品;不按日期范围猜测。"""
    books = await list_completed_picturebooks(db, user_id)
    items = [
        _summary_item(book)
        for book in books
        if book["source_kind"] == "canonical_work"
        and book["work_kind"] == "time_story"
    ]
    return {"items": items}


# --------------------------------------------------------------------- motion comics


async def _active_motion_comic(db: Any, user_id: int) -> Optional[dict]:
    cursor = await db.execute(
        """
        SELECT id, stage, status, total_segments, updated_at
        FROM picturebook_video_jobs
        WHERE user_id = ? AND status = 'running'
        ORDER BY updated_at DESC, id DESC
        LIMIT 1
        """,
        (user_id,),
    )
    row = await cursor.fetchone()
    if not row:
        return None
    job = _row_dict(row)
    cursor = await db.execute(
        "SELECT COUNT(*) AS count FROM picturebook_video_segments "
        "WHERE video_job_id = ? AND status = 'ready'",
        (job["id"],),
    )
    ready = (await cursor.fetchone())["count"]
    return {
        "id": job["id"],
        "stage": job["stage"],
        "status": job["status"],
        "total": job["total_segments"],
        "ready": ready,
        "updated_at": job["updated_at"],
    }


async def _completed_picturebook_index(db: Any, user_id: int) -> dict[int, dict]:
    """job_id -> 归一化完成绘本,用于解析漫剧来源。"""
    index: dict[int, dict] = {}
    cursor = await db.execute(
        """
        SELECT work.picturebook_job_id AS job_id, work.id AS source_id
        FROM story_works AS work
        WHERE work.owner_user_id = ?
          AND work.picturebook_job_id IS NOT NULL
          AND work.status IN ('ready', 'published')
        """,
        (user_id,),
    )
    canonical = {int(row["job_id"]): int(row["source_id"]) for row in await cursor.fetchall()}
    books = await list_completed_picturebooks(db, user_id)
    by_key = {(book["source_kind"], book["source_id"]): book for book in books}
    for job_id, work_id in canonical.items():
        book = by_key.get(("canonical_work", work_id))
        if book:
            index[job_id] = book
    cursor = await db.execute(
        """
        SELECT id FROM picturebook_jobs
        WHERE user_id = ? AND work_id IS NULL AND status = 'done'
        """,
        (user_id,),
    )
    for row in await cursor.fetchall():
        book = by_key.get(("historical_job", int(row["id"])))
        if book:
            index[int(row["id"])] = book
    return index


async def list_motion_comic_collection(db: Any, user_id: int) -> dict:
    cursor = await db.execute(
        """
        SELECT id, picturebook_job_id, work_id, asset_id, source_signature,
               updated_at, created_at
        FROM picturebook_video_jobs
        WHERE user_id = ? AND status = 'done' AND asset_id IS NOT NULL
        ORDER BY updated_at DESC, id DESC
        """,
        (user_id,),
    )
    jobs = [_row_dict(row) for row in await cursor.fetchall()]
    books = await _completed_picturebook_index(db, user_id)

    items = []
    for job in jobs:
        book = books.get(int(job["picturebook_job_id"]))
        if book is None:
            continue
        is_demo_case = str(job["source_signature"]).startswith(
            "demo-motion-comic-case-"
        )
        items.append(
            {
                "id": job["id"],
                "source_kind": "video_job",
                "work_kind": book["work_kind"],
                "title": (
                    f"案例故事｜{book['title'].split('｜', 1)[-1]}"
                    if is_demo_case
                    else book["title"]
                ),
                "display_start_date": book["start_date"],
                "display_end_date": book["end_date"],
                "cover_url": (
                    "/motion-comic-cases/programmer-xiaoma-cover.png"
                    if is_demo_case
                    else book["cover_url"]
                ),
                "completed_at": job["updated_at"] or job["created_at"],
                "video_url": f"/api/picturebook-video/{job['id']}/file",
            }
        )

    unfinished = await _unfinished_motion_comics(db, user_id)
    demo_item = await _demo_motion_comic_item(db, user_id)
    if demo_item is not None:
        items.insert(0, demo_item)
    return {
        "active_generation": await _active_motion_comic(db, user_id),
        "unfinished_count": len(unfinished),
        "items": items,
        "remaining": await remaining_quota(
            db, user_id=user_id, category=CATEGORY_MOTION_COMIC
        ),
    }


async def _unfinished_motion_comics(db: Any, user_id: int) -> list[dict]:
    """可恢复漫剧:未关联任务的草稿,以及关联任务失败的草稿。"""
    cursor = await db.execute(
        """
        SELECT draft.id, draft.source_kind, draft.source_id, draft.title,
               draft.page_sequence_json, draft.video_job_id,
               draft.created_at, draft.updated_at,
               job.status AS video_status, job.error AS video_error,
               COALESCE(work.style, source_job.style) AS source_style,
               work.display_start_date AS source_start_date,
               work.display_end_date AS source_end_date
        FROM motion_comic_drafts AS draft
        LEFT JOIN picturebook_video_jobs AS job
          ON job.id = draft.video_job_id
         AND job.user_id = draft.user_id
        LEFT JOIN story_works AS work
          ON draft.source_kind = 'work'
         AND work.id = draft.source_id
         AND work.owner_user_id = draft.user_id
        LEFT JOIN picturebook_jobs AS source_job
          ON draft.source_kind = 'job'
         AND source_job.id = draft.source_id
         AND source_job.user_id = draft.user_id
        WHERE draft.user_id = ?
          AND (
              draft.video_job_id IS NULL
              OR job.status = 'failed'
          )
        ORDER BY draft.updated_at DESC, draft.id DESC
        """,
        (user_id,),
    )
    items = []
    for row in (_row_dict(item) for item in await cursor.fetchall()):
        items.append(
            {
                "id": row["id"],
                "source_kind": row["source_kind"],
                "source_id": row["source_id"],
                "title": row["title"],
                "video_job_id": row["video_job_id"],
                "status": "failed" if row["video_status"] == "failed" else "draft",
                "style": row["source_style"],
                "display_start_date": row["source_start_date"],
                "display_end_date": row["source_end_date"],
                # 读取边界统一脱敏:历史遗留的原始上游错误不外泄。
                "error": (
                    sanitize_generation_error(row["video_error"])
                    if row["video_error"] is not None
                    else None
                ),
                "updated_at": row["updated_at"],
            }
        )
    return items


async def list_unfinished_motion_comics(db: Any, user_id: int) -> dict:
    return {"items": await _unfinished_motion_comics(db, user_id)}


async def get_motion_comic_detail(
    db: Any, user_id: int, video_job_id: int
) -> Optional[dict]:
    """按 video_job_id 读取漫剧详情(含时长、视频链接),供只读播放器使用。

    支持 cross-owner demo seed 示例:若当前用户订阅了 DEMO 发布者,且
    video_job_id 恰好是 DEMO_MOTION_COMIC_VIDEO_JOB_ID,则跨用户查询。
    """
    async def _detail_for(db: Any, query_user_id: int) -> Optional[dict]:
        cursor = await db.execute(
            """
            SELECT id, picturebook_job_id, asset_id, duration_seconds,
                   source_signature, status, updated_at, created_at
            FROM picturebook_video_jobs
            WHERE id = ? AND user_id = ? AND status = 'done' AND asset_id IS NOT NULL
            """,
            (video_job_id, query_user_id),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        job = _row_dict(row)
        books = await _completed_picturebook_index(db, query_user_id)
        book = books.get(int(job["picturebook_job_id"]))
        title = book["title"] if book else ""
        if str(job["source_signature"]).startswith("demo-motion-comic-case-"):
            title = f"案例故事｜{title.split('｜', 1)[-1]}"
        return {
            "id": job["id"],
            "title": title,
            "display_start_date": book["start_date"] if book else None,
            "display_end_date": book["end_date"] if book else None,
            "cover_url": (
                "/motion-comic-cases/programmer-xiaoma-cover.png"
                if str(job["source_signature"]).startswith("demo-motion-comic-case-")
                else (book["cover_url"] if book else None)
            ),
            "completed_at": job["updated_at"] or job["created_at"],
            "duration_seconds": job["duration_seconds"],
            "video_url": f"/api/picturebook-video/{job['id']}/file",
        }

    detail = await _detail_for(db, user_id)
    if detail is not None:
        return detail
    # 跨用户:示例漫剧属于 DEMO 发布者而非当前用户。
    if (
        video_job_id == config.DEMO_MOTION_COMIC_VIDEO_JOB_ID
        and await is_demo_subscriber(db, user_id=user_id)
    ):
        return await _detail_for(db, config.DEMO_PUBLISHER_USER_ID)
    return None
