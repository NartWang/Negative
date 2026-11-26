"""Turn a finished picturebook into one continuous video.

Pipeline: pair the pages (page k, page k+1) into N-1 segments -> submit every
segment in parallel with the two pages as first/last frame -> poll -> download
each segment -> stitch into one film.

Why pairing beats "animate each page on its own": bothends of every segment are
locked to artwork that already exists, so the protagonist and palette cannot
drift across cuts, and segment k's tail is literally segment k+1's head, which
makes the seams line up. Because every input already exists, the segments have
no dependency on one another and all of them can be in flight at once — the
whole film costs roughly as much wall-clock time as a single segment.

Rendering takes minutes and costs real money, so, exactly like the picturebook
pipeline: a job row owns the progress, a background task advances it, the client
polls, and every finished segment is persisted so a retry only re-renders what
actually failed.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from agents.image_agent import STYLE_PROMPTS
from agents.video_agent import (
    VideoFrame,
    VideoServiceError,
    build_segment_prompt,
    fetch_task,
    prepare_frame,
    submit_segment,
    video_generation_configured,
)
from auth.dependencies import get_current_user_id, require_same_origin
from config import (
    DEMO_MOTION_COMIC_VIDEO_JOB_ID,
    DEMO_PUBLISHER_USER_ID,
    VIDEO_INCLUDE_COVER,
    VIDEO_MAX_CONCURRENCY,
    VIDEO_MODEL,
    VIDEO_POLL_INTERVAL_SECONDS,
    VIDEO_POLL_TIMEOUT_SECONDS,
    VIDEO_RATIO,
    VIDEO_SEED,
    VIDEO_SEGMENT_DURATION,
    VIDEO_TRIM_DUPLICATE_FRAME,
    VIDEO_XFADE_SECONDS,
)
from database import get_db
from services.demo_seed import is_demo_subscriber
from services.generation_quota import (
    GenerationQuotaExceeded,
    consume_quota,
    quota_detail,
)
from services.generation_slots import (
    CATEGORY_MOTION_COMIC,
    GenerationSlotConflict,
    conflict_detail,
    require_available_slot,
)
from services.media_store import MediaAsset, MediaStoreError, asset_file_path
from services.story_workflow import sanitize_generation_error
from services.video_store import (
    VideoAsset,
    delete_video_asset,
    download_remote_video,
    require_owned_video,
    store_video_bytes,
    video_file_path,
)
from services.video_stitcher import VideoStitchError, stitch_segments

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/picturebook-video", tags=["picturebook-video"])

STAGE_LABELS = {
    "queued": "正在排队",
    "frames": "正在准备每一页的画面",
    "submitting": "正在提交分镜",
    "rendering": "正在让画面动起来",
    "stitching": "正在把分镜接成一条片子",
    "done": "视频已完成",
    "failed": "生成失败",
}

ALLOWED_RATIOS = {"adaptive", "21:9", "16:9", "4:3", "1:1", "3:4", "9:16"}
MIN_SEGMENT_DURATION = 3
MAX_SEGMENT_DURATION = 12
MIN_PAGES = 2
# 一段就是一次付费渲染，给页数封个顶，避免一次点击排出几十段。
MAX_PAGES = 24

_running: set[int] = set()
_lock = asyncio.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class CreateVideoRequest(BaseModel):
    # 封面通常是海报式构图，与第1页跨度过大，默认不接进来。
    include_cover: Optional[bool] = None
    segment_duration: Optional[int] = None
    ratio: Optional[str] = None
    # 漫剧向导允许挑页并重排，给了就严格按这个顺序两两配对；
    # 给了它就以它为准，include_cover 不再参与筛选。
    page_indexes: Optional[list[int]] = None
    # 底片夹新入口携带已保存草稿;旧调用方省略,服务端按规则补建/复用。
    draft_id: Optional[int] = None


# --------------------------------------------------------------------- reading


async def _picturebook_pages(
    db: Any,
    picturebook_job_id: int,
    user_id: int,
    *,
    include_cover: bool,
) -> list[dict]:
    """Ordered,ready pages whose artwork the caller actually owns.

    遵循SEC-AUTH-002 规范: the picturebook job, and every page asset it points
    at, must belong to the authenticated caller.
    """
    cursor = await db.execute(
        """
        SELECT page.page_index, page.caption, page.image_id,
               asset.id AS asset_id, asset.owner_user_id, asset.storage_key,
               asset.mime_type, asset.size_bytes
        FROM picturebook_pages AS page
        JOIN picturebook_jobs AS job ON job.id = page.job_id
        JOIN media_assets AS asset ON asset.id = page.asset_id
        WHERE page.job_id = ?
          AND job.user_id = ?
          AND asset.owner_user_id = job.user_id
          AND page.status = 'ready'
        ORDER BY page.page_index
        """,
        (picturebook_job_id, user_id),
    )
    pages = [dict(row) for row in await cursor.fetchall()]
    if not include_cover:
        pages = [page for page in pages if page["page_index"] > 0]
    return pages


def _validate_sequence(sequence: list[int]) -> list[int]:
    if not all(isinstance(index, int) and index >= 0 for index in sequence):
        raise HTTPException(status_code=422, detail="page_indexes must be page numbers")
    if len(set(sequence)) != len(sequence):
        # 同一页出现两次会配出一段首尾帧相同的静止镜头。
        raise HTTPException(status_code=422, detail="page_indexes must be unique")
    if not MIN_PAGES <= len(sequence) <= MAX_PAGES:
        raise HTTPException(
            status_code=422,
            detail=f"page_indexes must contain {MIN_PAGES} to {MAX_PAGES} pages",
        )
    return sequence


def _apply_sequence(pages: list[dict], sequence: list[int]) -> list[dict]:
    """Reorder to the caller's sequence; a missing page means the book changed."""
    by_index = {page["page_index"]: page for page in pages}
    ordered = []
    for index in sequence:
        page = by_index.get(index)
        if page is None:
            return []
        ordered.append(page)
    return ordered


async def _resolve_pages(
    db: Any,
    picturebook_job_id: int,
    user_id: int,
    *,
    include_cover: bool,
    sequence: Optional[list[int]],
) -> list[dict]:
    """The final, ordered page list this film is built from."""
    pages = await _picturebook_pages(
        db,
        picturebook_job_id,
        user_id,
        # 显式页序自己决定要不要封面，不能再被 include_cover 过滤掉。
        include_cover=True if sequence else include_cover,
    )
    if sequence:
        return _apply_sequence(pages, sequence)
    return pages


def _story_outline(pages: list[dict]) -> str:
    """One line per page, so a segment knows where it sits in the story."""
    lines = []
    for order, page in enumerate(pages, 1):
        caption = (page.get("caption") or "").strip()
        if caption:
            lines.append(f"{order}. {caption}")
    return "\n".join(lines)


def _source_signature(
    picturebook_job_id: int,
    pages: list[dict],
    *,
    style: str,
    segment_duration: int,
    ratio: str,
    include_cover: bool,
) -> str:
    """Any change to the pages, their order, or the settings means a new film."""
    snapshot = {
        "picturebook_job_id": picturebook_job_id,
        "page_asset_ids": [page["asset_id"] for page in pages],
        "page_indexes": [page["page_index"] for page in pages],
        "style": style,
        "model": VIDEO_MODEL,
        "segment_duration": segment_duration,
        "ratio": ratio,
        "include_cover": include_cover,
        "seed": VIDEO_SEED,
    }
    canonical = json.dumps(
        snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def _character_profile_text(db: Any, user_id: int) -> str:
    cursor = await db.execute(
        "SELECT nickname, character_description, visual_profile "
        "FROM character_profiles WHERE user_id = ?",
        (user_id,),
    )
    row = await cursor.fetchone()
    if not row:
        return ""
    lines = []
    if (row["nickname"] or "").strip():
        lines.append(f"昵称：{row['nickname'].strip()}")
    description = (row["character_description"] or "").strip()
    if description and description != (row["nickname"] or "").strip():
        lines.append(f"气质：{description}")
    if (row["visual_profile"] or "").strip():
        lines.append("可见特征（以角色母版为准，不得改动）：")
        lines.append(row["visual_profile"].strip())
    return "\n".join(lines)


async def _job_payload(db: Any, video_job_id: int, user_id: int) -> dict:
    cursor = await db.execute(
        "SELECT * FROM picturebook_video_jobs WHERE id = ? AND user_id = ?",
        (video_job_id, user_id),
    )
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="picturebook video job not found")
    job = dict(row)

    cursor = await db.execute(
        "SELECT segment_index, first_page_index, last_page_index, status, error "
        "FROM picturebook_video_segments WHERE video_job_id = ? ORDER BY segment_index",
        (video_job_id,),
    )
    segments = [dict(item) for item in await cursor.fetchall()]
    ready = sum(1 for segment in segments if segment["status"] == "ready")

    return {
        "id": job["id"],
        "picturebook_job_id": job["picturebook_job_id"],
        "work_id": job["work_id"],
        "style": job["style"],
        "status": job["status"],
        "stage": job["stage"],
        "stage_label": STAGE_LABELS.get(job["stage"], job["stage"]),
        "error": sanitize_generation_error(job["error"]) if job["error"] else None,
        "include_cover": bool(job["include_cover"]),
        "segment_duration": job["segment_duration"],
        "ratio": job["ratio"],
        "total_segments": job["total_segments"],
        "ready_segments": ready,
        "duration_seconds": job["duration_seconds"],
        # 成片按会话鉴权后由后端吐字节，不外泄上游签名 URL。
        "video_url": (
            f"/api/picturebook-video/{job['id']}/file" if job["asset_id"] else None
        ),
        "created_at": job["created_at"],
        "updated_at": job["updated_at"],
        "segments": [
            {
                "segment_index": segment["segment_index"],
                "first_page_index": segment["first_page_index"],
                "last_page_index": segment["last_page_index"],
                "status": segment["status"],
                "error": (
                    sanitize_generation_error(segment["error"])
                    if segment["error"]
                    else None
                ),
            }
            for segment in segments
        ],
    }


# --------------------------------------------------------------------- writing


async def _set_stage(
    db: Any, video_job_id: int, stage: str, status: str = "running"
) -> None:
    await db.execute(
        "UPDATE picturebook_video_jobs SET stage = ?, status = ?, updated_at = ? "
        "WHERE id = ?",
        (stage, status, _now(), video_job_id),
    )
    await db.commit()


async def _fail(db: Any, video_job_id: int, message: str) -> None:
    await db.execute(
        "UPDATE picturebook_video_jobs SET status = 'failed', stage = 'failed', "
        "error = ?, updated_at = ? WHERE id = ?",
        (message[:500], _now(), video_job_id),
    )
    await db.commit()


def _decode_sequence(raw: object) -> list[int]:
    if not isinstance(raw, str) or not raw.strip():
        return []
    try:
        decoded = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if not isinstance(decoded, list):
        return []
    return [item for item in decoded if isinstance(item, int)]


async def _load_frames(
    db: Any, job: dict, user_id: int
) -> tuple[dict[int, VideoFrame], dict[int, str], str]:
    """Read every participating page once and shrink it off the event loop."""
    pages = await _resolve_pages(
        db,
        job["picturebook_job_id"],
        user_id,
        include_cover=bool(job["include_cover"]),
        sequence=_decode_sequence(job.get("page_sequence")),
    )
    if len(pages) < MIN_PAGES:
        raise MediaStoreError("绘本页面已变化，请重新生成视频")

    frames: dict[int, VideoFrame] = {}
    captions: dict[int, str] = {}
    for page in pages:
        asset = MediaAsset(
            id=page["asset_id"],
            owner_user_id=page["owner_user_id"],
            storage_key=page["storage_key"],
            mime_type=page["mime_type"],
            size_bytes=page["size_bytes"],
        )
        path = asset_file_path(asset)
        if not path.is_file():
            raise MediaStoreError("a picturebook page file is missing")
        raw = VideoFrame(content=path.read_bytes(), mime_type=asset.mime_type)
        # Pillow 是纯 CPU 调用，别把事件循环卡住。
        frames[page["page_index"]] = await asyncio.to_thread(prepare_frame, raw)
        captions[page["page_index"]] = page["caption"] or ""
    return frames, captions, _story_outline(pages)


async def _submit_pending(
    db: Any,
    job: dict,
    segments: list[dict],
    frames: dict[int, VideoFrame],
    captions: dict[int, str],
    character_profile: str,
    story_outline: str,
) -> int:
    todo = [
        segment
        for segment in segments
        if segment["status"] != "ready" and not segment["provider_task_id"]
    ]
    if not todo:
        return 0

    style_description = STYLE_PROMPTS.get(job["style"]) or ""
    semaphore = asyncio.Semaphore(max(1, VIDEO_MAX_CONCURRENCY))
    failures = 0

    async with httpx.AsyncClient(timeout=180) as client:

        async def _submit(segment: dict) -> tuple[dict, Optional[str], Optional[str]]:
            """Third slot carries the prompt on success, the error text on failure."""
            first = frames.get(segment["first_page_index"])
            last = frames.get(segment["last_page_index"])
            if first is None or last is None:
                return segment, None, "绘本页面已变化，请重新生成视频"
            prompt = build_segment_prompt(
                from_caption=captions.get(segment["first_page_index"], ""),
                to_caption=captions.get(segment["last_page_index"], ""),
                style_description=style_description,
                character_profile=character_profile,
                segment_index=segment["segment_index"],
                total_segments=job["total_segments"],
                story_outline=story_outline,
            )
            async with semaphore:
                try:
                    task_id = await submit_segment(
                        client,
                        prompt,
                        first,
                        last,
                        duration=job["segment_duration"],
                        ratio=job["ratio"],
                        seed=job["seed"],
                    )
                except VideoServiceError as exc:
                    return segment, None, sanitize_generation_error(str(exc))
            return segment, task_id, prompt

        results = await asyncio.gather(*(_submit(item) for item in todo))

    for segment, task_id, extra in results:
        if task_id is None:
            failures += 1
            await db.execute(
                "UPDATE picturebook_video_segments SET status = 'failed', error = ?, "
                "updated_at = ? WHERE id = ?",
                (extra, _now(), segment["id"]),
            )
        else:
            segment["provider_task_id"] = task_id
            segment["status"] = "rendering"
            await db.execute(
                "UPDATE picturebook_video_segments SET provider_task_id = ?, "
                "prompt = ?, status = 'rendering', error = NULL, updated_at = ? "
                "WHERE id = ?",
                (task_id, extra or "", _now(), segment["id"]),
            )
        await db.commit()
    return failures


async def _collect_rendering(
    db: Any, job: dict, user_id: int, segments: list[dict]
) -> int:
    """Poll every in-flight segment, storing each render as it lands."""
    pending = {
        segment["id"]: segment
        for segment in segments
        if segment["status"] != "ready" and segment["provider_task_id"]
    }
    if not pending:
        return 0

    failures = 0
    started = asyncio.get_running_loop().time()
    async with httpx.AsyncClient(timeout=120) as client:
        while pending:
            for segment in list(pending.values()):
                try:
                    state = await fetch_task(client, segment["provider_task_id"])
                except VideoServiceError as exc:
                    failures += 1
                    pending.pop(segment["id"], None)
                    await db.execute(
                        "UPDATE picturebook_video_segments SET status = 'failed', "
                        "error = ?, updated_at = ? WHERE id = ?",
                        (sanitize_generation_error(str(exc)), _now(), segment["id"]),
                    )
                    await db.commit()
                    continue

                if not state.is_terminal:
                    continue
                pending.pop(segment["id"], None)
                if state.is_failure or not state.video_url:
                    failures += 1
                    await db.execute(
                        "UPDATE picturebook_video_segments SET status = 'failed', "
                        "error = ?, updated_at = ? WHERE id = ?",
                        ("这一段没有生成成功，可以重试", _now(), segment["id"]),
                    )
                    await db.commit()
                    continue

                try:
                    content = await download_remote_video(state.video_url)
                    asset = await store_video_bytes(
                        db,
                        user_id,
                        content,
                        duration_seconds=state.duration_seconds,
                    )
                except MediaStoreError as exc:
                    failures += 1
                    await db.execute(
                        "UPDATE picturebook_video_segments SET status = 'failed', "
                        "error = ?, updated_at = ? WHERE id = ?",
                        (str(exc)[:300], _now(), segment["id"]),
                    )
                    await db.commit()
                    continue

                segment["status"] = "ready"
                segment["asset_id"] = asset.id
                await db.execute(
                    "UPDATE picturebook_video_segments SET status = 'ready', "
                    "asset_id = ?, error = NULL, updated_at = ? WHERE id = ?",
                    (asset.id, _now(), segment["id"]),
                )
                await db.commit()

            if not pending:
                break
            if asyncio.get_running_loop().time() - started > VIDEO_POLL_TIMEOUT_SECONDS:
                # 任务 id 留在库里，重试时会接着轮询，不会重复付费。
                for segment in pending.values():
                    await db.execute(
                        "UPDATE picturebook_video_segments SET status = 'timeout', "
                        "error = ?, updated_at = ? WHERE id = ?",
                        ("这一段等太久了，可以重试", _now(), segment["id"]),
                    )
                await db.commit()
                failures += len(pending)
                break
            await asyncio.sleep(VIDEO_POLL_INTERVAL_SECONDS)
    return failures


async def _stitch_and_finish(db: Any, job: dict, user_id: int) -> None:
    cursor = await db.execute(
        """
        SELECT segment.segment_index, asset.storage_key
        FROM picturebook_video_segments AS segment
        JOIN video_assets AS asset ON asset.id = segment.asset_id
        WHERE segment.video_job_id = ?
          AND segment.status = 'ready'
          AND asset.owner_user_id = ?
        ORDER BY segment.segment_index
        """,
        (job["id"], user_id),
    )
    rows = [dict(row) for row in await cursor.fetchall()]
    if len(rows) != job["total_segments"]:
        await _fail(db, job["id"], "有分镜缺失，可以重试")
        return

    await _set_stage(db, job["id"], "stitching")
    paths: list[Path] = [
        video_file_path(
            VideoAsset(
                id="",
                owner_user_id=user_id,
                storage_key=row["storage_key"],
                mime_type="video/mp4",
                size_bytes=0,
            )
        )
        for row in rows
    ]

    content, duration = await stitch_segments(
        paths,
        trim_duplicate_frame=bool(VIDEO_TRIM_DUPLICATE_FRAME),
        xfade_seconds=float(VIDEO_XFADE_SECONDS),
    )
    previous_asset_id = job["asset_id"]
    asset = await store_video_bytes(db, user_id, content, duration_seconds=duration)
    await db.execute(
        "UPDATE picturebook_video_jobs SET asset_id = ?, duration_seconds = ?, "
        "status = 'done', stage = 'done', error = NULL, updated_at = ? WHERE id = ?",
        (asset.id, duration, _now(), job["id"]),
    )
    await db.commit()
    #旧成片只在新成片落库之后才删，避免中途失败留下无片可看的任务。
    if previous_asset_id and previous_asset_id != asset.id:
        await delete_video_asset(db, previous_asset_id)
        await db.commit()


async def _advance(video_job_id: int, user_id: int) -> None:
    """Drive one video job from wherever it is to done, persisting every stage."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM picturebook_video_jobs WHERE id = ? AND user_id = ?",
            (video_job_id, user_id),
        )
        row = await cursor.fetchone()
        if not row:
            return
        job = dict(row)

        cursor = await db.execute(
            "SELECT * FROM picturebook_video_segments WHERE video_job_id = ? "
            "ORDER BY segment_index",
            (video_job_id,),
        )
        segments = [dict(item) for item in await cursor.fetchall()]
        if not segments:
            return await _fail(db, video_job_id, "没有可生成的分镜")

        outstanding = [item for item in segments if item["status"] != "ready"]
        if outstanding:
            await _set_stage(db, video_job_id, "frames")
            frames, captions, story_outline = await _load_frames(db, job, user_id)
            character_profile = await _character_profile_text(db, user_id)

            await _set_stage(db, video_job_id, "submitting")
            failures = await _submit_pending(
                db, job, segments, frames, captions, character_profile, story_outline
            )

            await _set_stage(db, video_job_id, "rendering")
            failures += await _collect_rendering(db, job, user_id, segments)
            if failures:
                return await _fail(
                    db, video_job_id, f"有 {failures} 段没生成成功，可以重试这几段"
                )

        await _stitch_and_finish(db, job, user_id)
    except asyncio.CancelledError:
        raise
    except VideoStitchError:
        await _fail(db, video_job_id, "分镜拼接失败，可以重试")
    except VideoServiceError as exc:
        await _fail(db, video_job_id, sanitize_generation_error(str(exc)))
    except MediaStoreError as exc:
        await _fail(db, video_job_id, str(exc)[:300])
    except Exception:  # noqa: BLE001 - a background task must never vanish silently
        logger.exception("picturebook video job %s failed", video_job_id)
        await _fail(db, video_job_id, "生成过程出错了，可以重试")
    finally:
        await db.close()
        async with _lock:
            _running.discard(video_job_id)


async def _spawn(video_job_id: int, user_id: int) -> None:
    async with _lock:
        if video_job_id in _running:
            return
        _running.add(video_job_id)
    asyncio.create_task(_advance(video_job_id, user_id))


async def resume_running_videos() -> None:
    """进程重启后恢复所有保留的 running 漫剧任务;幂等,可重复调用。"""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT id, user_id FROM picturebook_video_jobs WHERE status = 'running'"
        )
        rows = await cursor.fetchall()
    finally:
        await db.close()
    for row in rows:
        await _spawn(int(row["id"]), int(row["user_id"]))


# --------------------------------------------------------------------- routes


def _resolve_settings(payload: CreateVideoRequest) -> tuple[bool, int, str]:
    include_cover = (
        VIDEO_INCLUDE_COVER if payload.include_cover is None else payload.include_cover
    )
    duration = (
        VIDEO_SEGMENT_DURATION
        if payload.segment_duration is None
        else payload.segment_duration
    )
    if not MIN_SEGMENT_DURATION <= duration <= MAX_SEGMENT_DURATION:
        raise HTTPException(
            status_code=422,
            detail=(
                f"segment_duration must be between {MIN_SEGMENT_DURATION} "
                f"and {MAX_SEGMENT_DURATION} seconds"
            ),
        )
    ratio = (payload.ratio or VIDEO_RATIO).strip()
    if ratio not in ALLOWED_RATIOS:
        raise HTTPException(status_code=422, detail="unsupported ratio")
    return bool(include_cover), int(duration), ratio


async def _resolve_work_picturebook_job(db: Any, work_id: int, user_id: int) -> int:
    """漫剧向导的来源可能是作品，取它名下最新那本画完的绘本。"""
    cursor = await db.execute(
        "SELECT id FROM picturebook_jobs WHERE work_id = ? AND user_id = ? "
        "AND status = 'done' ORDER BY id DESC LIMIT 1",
        (work_id, user_id),
    )
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="picturebook job not found")
    return int(dict(row)["id"])


async def _start_video(
    payload: CreateVideoRequest,
    user_id: int,
    *,
    picturebook_job_id: Optional[int] = None,
    work_id: Optional[int] = None,
) -> dict:
    """Create or resume the film for one picturebook, then kick the worker."""
    if not video_generation_configured():
        raise HTTPException(status_code=503, detail="video service is not configured")

    include_cover, segment_duration, ratio = _resolve_settings(payload)
    sequence = (
        _validate_sequence(list(payload.page_indexes))
        if payload.page_indexes is not None
        else None
    )

    db = await get_db()
    should_spawn = True
    try:
        await db.execute("BEGIN IMMEDIATE")
        job_id = picturebook_job_id
        if job_id is None:
            job_id = await _resolve_work_picturebook_job(db, int(work_id or 0), user_id)

        cursor = await db.execute(
            "SELECT id, user_id, work_id, style, status FROM picturebook_jobs "
            "WHERE id = ? AND user_id = ?",
            (job_id, user_id),
        )
        book = await cursor.fetchone()
        if not book:
            raise HTTPException(status_code=404, detail="picturebook job not found")
        if book["status"] != "done":
            raise HTTPException(status_code=409, detail="picturebook is not finished")

        pages = await _resolve_pages(
            db, job_id, user_id, include_cover=include_cover, sequence=sequence
        )
        if len(pages) < MIN_PAGES:
            # 显式页序里有页已经不在这本绘本里了，也会落到这里。
            raise HTTPException(
                status_code=409, detail="picturebook has too few pages for a video"
            )
        if len(pages) > MAX_PAGES:
            raise HTTPException(
                status_code=409, detail="picturebook has too many pages for one video"
            )

        signature = _source_signature(
            job_id,
            pages,
            style=book["style"],
            segment_duration=segment_duration,
            ratio=ratio,
            include_cover=include_cover,
        )
        cursor = await db.execute(
            "SELECT id, status FROM picturebook_video_jobs "
            "WHERE picturebook_job_id = ? AND user_id = ? AND source_signature = ? "
            "ORDER BY id DESC LIMIT 1",
            (job_id, user_id, signature),
        )
        existing = await cursor.fetchone()
        if existing:
            # 同一批页面 + 同一顺序 + 同一组参数只出一条片子，重复点击不重复付费。
            video_job_id = existing["id"]
            should_spawn = existing["status"] != "done"
            if should_spawn:
                await require_available_slot(
                    db,
                    user_id=user_id,
                    category=CATEGORY_MOTION_COMIC,
                    current_job_id=video_job_id,
                )
                await db.execute(
                    "UPDATE picturebook_video_jobs SET status = 'running', "
                    "stage = 'queued', error = NULL, updated_at = ? WHERE id = ?",
                    (_now(), video_job_id),
                )
        else:
            await require_available_slot(
                db,
                user_id=user_id,
                category=CATEGORY_MOTION_COMIC,
            )
            # 只有真正新建任务才扣体验次数;上面的复用分支(同签名重跑)不扣。
            await consume_quota(db, user_id=user_id, category=CATEGORY_MOTION_COMIC)
            # 页序总是照实存下来，哪怕调用方没指定：后台重跑时按它复现，
            # 不会因为默认值改了就换成另一条片子。
            page_sequence = json.dumps([page["page_index"] for page in pages])
            cursor = await db.execute(
                "INSERT INTO picturebook_video_jobs (user_id, picturebook_job_id, "
                "work_id, style, source_signature, model, segment_duration, ratio, "
                "seed, include_cover, page_sequence, status, stage, total_segments, "
                "created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'running', 'queued', ?, ?, ?)",
                (
                    user_id,
                    job_id,
                    book["work_id"],
                    book["style"],
                    signature,
                    VIDEO_MODEL,
                    segment_duration,
                    ratio,
                    VIDEO_SEED if VIDEO_SEED > 0 else None,
                    int(include_cover),
                    page_sequence,
                    len(pages) - 1,
                    _now(),
                    _now(),
                ),
            )
            video_job_id = cursor.lastrowid
            for index in range(len(pages) - 1):
                await db.execute(
                    "INSERT INTO picturebook_video_segments (video_job_id, "
                    "segment_index, first_page_index, last_page_index, status, "
                    "created_at, updated_at) VALUES (?, ?, ?, ?, 'pending', ?, ?)",
                    (
                        video_job_id,
                        index + 1,
                        pages[index]["page_index"],
                        pages[index + 1]["page_index"],
                        _now(),
                        _now(),
                    ),
                )

        # 草稿关联:同一事务内保证一个视频任务至多一条草稿。
        # 任务可能源自正式作品或历史任务,据此确定 source_kind。
        resolved_source_kind = "work" if book["work_id"] else "job"
        resolved_source_id = int(book["work_id"] or job_id)
        resolved_pages = [page["page_index"] for page in pages]
        cursor = await db.execute(
            "SELECT id FROM motion_comic_drafts WHERE video_job_id = ?",
            (video_job_id,),
        )
        linked = await cursor.fetchone()
        if linked:
            if payload.draft_id is not None and int(payload.draft_id) != int(linked["id"]):
                raise HTTPException(
                    status_code=409,
                    detail={
                        "detail": "video job is already linked to a draft",
                        "existing_draft_id": int(linked["id"]),
                    },
                )
            # 复用既有草稿,不新建。
        elif payload.draft_id is not None:
            draft_row = await db.execute(
                "SELECT id, source_kind, source_id, page_sequence_json, video_job_id "
                "FROM motion_comic_drafts WHERE id = ? AND user_id = ?",
                (payload.draft_id, user_id),
            )
            draft = await draft_row.fetchone()
            if not draft:
                raise HTTPException(status_code=404, detail="motion comic draft not found")
            if draft["video_job_id"] is not None:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "detail": "draft is already linked to another video job",
                        "existing_draft_id": int(draft["id"]),
                    },
                )
            if (
                draft["source_kind"] != resolved_source_kind
                or int(draft["source_id"]) != resolved_source_id
                or json.loads(draft["page_sequence_json"] or "[]") != resolved_pages
            ):
                raise HTTPException(
                    status_code=422,
                    detail="draft source or page sequence does not match this start",
                )
            await db.execute(
                "UPDATE motion_comic_drafts SET video_job_id = ?, updated_at = ? "
                "WHERE id = ? AND user_id = ?",
                (video_job_id, _now(), payload.draft_id, user_id),
            )
        else:
            await db.execute(
                "INSERT INTO motion_comic_drafts (user_id, source_kind, source_id, "
                "title, page_sequence_json, video_job_id, created_at, updated_at) "
                "VALUES (?, ?, ?, '', ?, ?, ?, ?)",
                (
                    user_id,
                    resolved_source_kind,
                    resolved_source_id,
                    json.dumps(resolved_pages, ensure_ascii=False),
                    video_job_id,
                    _now(),
                    _now(),
                ),
            )

        await db.commit()
        payload_out = await _job_payload(db, video_job_id, user_id)
    except GenerationSlotConflict as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=conflict_detail(exc)) from exc
    except GenerationQuotaExceeded as exc:
        await db.rollback()
        raise HTTPException(status_code=403, detail=quota_detail(exc)) from exc
    except HTTPException:
        await db.rollback()
        raise
    except Exception:
        await db.rollback()
        raise
    finally:
        await db.close()

    if should_spawn:
        await _spawn(video_job_id, user_id)
    return payload_out


@router.post("/picturebook/{picturebook_job_id}")
async def create_picturebook_video(
    picturebook_job_id: int,
    payload: CreateVideoRequest,
    _: None = Depends(require_same_origin),
    user_id: int = Depends(get_current_user_id),
):
    """Start (or resume) the video for a finished picturebook job."""
    return await _start_video(payload, user_id, picturebook_job_id=picturebook_job_id)


@router.post("/work/{work_id}")
async def create_work_video(
    work_id: int,
    payload: CreateVideoRequest,
    _: None = Depends(require_same_origin),
    user_id: int = Depends(get_current_user_id),
):
    """Same thing, keyed by the story work the picturebook belongs to."""
    return await _start_video(payload, user_id, work_id=work_id)


@router.get("/work/{work_id}/latest")
async def get_latest_work_video(
    work_id: int,
    user_id: int = Depends(get_current_user_id),
):
    """Newest film for a work, so reopening the wizard restores it."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT id FROM picturebook_video_jobs "
            "WHERE work_id = ? AND user_id = ? ORDER BY id DESC LIMIT 1",
            (work_id, user_id),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        return await _job_payload(db, dict(row)["id"], user_id)
    finally:
        await db.close()


@router.get("/picturebook/{picturebook_job_id}/latest")
async def get_latest_picturebook_video(
    picturebook_job_id: int,
    user_id: int = Depends(get_current_user_id),
):
    """The newest video for a picturebook, so reopening the page restores it."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT id FROM picturebook_video_jobs "
            "WHERE picturebook_job_id = ? AND user_id = ? ORDER BY id DESC LIMIT 1",
            (picturebook_job_id, user_id),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        return await _job_payload(db, dict(row)["id"], user_id)
    finally:
        await db.close()


@router.get("/{video_job_id}")
async def get_picturebook_video(
    video_job_id: int,
    user_id: int = Depends(get_current_user_id),
):
    db = await get_db()
    try:
        return await _job_payload(db, video_job_id, user_id)
    finally:
        await db.close()


@router.post("/{video_job_id}/retry")
async def retry_picturebook_video(
    video_job_id: int,
    _: None = Depends(require_same_origin),
    user_id: int = Depends(get_current_user_id),
):
    """Re-render only the segments that are missing; finished ones are reused."""
    if not video_generation_configured():
        raise HTTPException(status_code=503, detail="video service is not configured")

    db = await get_db()
    try:
        await db.execute("BEGIN IMMEDIATE")
        cursor = await db.execute(
            "SELECT id FROM picturebook_video_jobs WHERE id = ? AND user_id = ?",
            (video_job_id, user_id),
        )
        if not await cursor.fetchone():
            raise HTTPException(
                status_code=404, detail="picturebook video job not found"
            )
        # 只清掉没成的段的任务 id，让它们重新提交；已 ready 的段原样保留。
        await require_available_slot(
            db,
            user_id=user_id,
            category=CATEGORY_MOTION_COMIC,
            current_job_id=video_job_id,
        )
        await db.execute(
            "UPDATE picturebook_video_segments SET status = 'pending', "
            "provider_task_id = NULL, error = NULL, updated_at = ? "
            "WHERE video_job_id = ? AND status IN ('failed', 'timeout')",
            (_now(), video_job_id),
        )
        await db.execute(
            "UPDATE picturebook_video_jobs SET status = 'running', stage = 'queued', "
            "error = NULL, updated_at = ? WHERE id = ?",
            (_now(), video_job_id),
        )
        await db.commit()
        payload_out = await _job_payload(db, video_job_id, user_id)
    except GenerationSlotConflict as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=conflict_detail(exc)) from exc
    except HTTPException:
        await db.rollback()
        raise
    except Exception:
        await db.rollback()
        raise
    finally:
        await db.close()

    await _spawn(video_job_id, user_id)
    return payload_out


async def _resolve_demo_video_job(db: Any, video_job_id: int, user_id: int) -> Optional[dict]:
    """跨用户解析 demo 示例视频:若当前用户订阅了 DEMO 发布者,查 demo 的视频资产。"""
    if (
        video_job_id != DEMO_MOTION_COMIC_VIDEO_JOB_ID
        or not await is_demo_subscriber(db, user_id=user_id)
    ):
        return None
    cursor = await db.execute(
        "SELECT asset_id FROM picturebook_video_jobs WHERE id = ? AND user_id = ?",
        (video_job_id, DEMO_PUBLISHER_USER_ID),
    )
    row = await cursor.fetchone()
    return dict(row) if row and row["asset_id"] else None


@router.get("/{video_job_id}/file")
async def get_picturebook_video_file(
    video_job_id: int,
    user_id: int = Depends(get_current_user_id),
):
    # 遵循 SEC-AUTH-002 规范: 未授权与不存在统一返回 404，避免枚举资产。
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT asset_id FROM picturebook_video_jobs WHERE id = ? AND user_id = ?",
            (video_job_id, user_id),
        )
        row = await cursor.fetchone()
        owner_id = user_id
        if (not row or not row["asset_id"]) and video_job_id == DEMO_MOTION_COMIC_VIDEO_JOB_ID:
            demo_row = await _resolve_demo_video_job(db, video_job_id, user_id)
            if demo_row is not None:
                row = demo_row
                owner_id = DEMO_PUBLISHER_USER_ID
        if not row or not row["asset_id"]:
            raise HTTPException(status_code=404, detail="video not found")
        try:
            asset = await require_owned_video(db, owner_id, row["asset_id"])
        except MediaStoreError:
            raise HTTPException(status_code=404, detail="video not found") from None
    finally:
        await db.close()

    try:
        path = video_file_path(asset)
    except MediaStoreError:
        raise HTTPException(status_code=404, detail="video not found") from None
    if not path.is_file():
        raise HTTPException(status_code=404, detail="video not found")
    return FileResponse(
        path,
        media_type=asset.mime_type,
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
