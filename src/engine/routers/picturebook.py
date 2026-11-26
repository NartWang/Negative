"""Picturebook jobs: diary -> story JSON -> nine image prompts -> nine pages.

The full pipeline takes several minutes (two long structured LLM calls plus nine
image renders against a proxy with a 60s gateway timeout), so it cannot live
inside one HTTP request. A job row owns the progress, a background task advances
it, and the client polls. Every stage result is persisted, so a retry re-renders
only the pages that failed and never repeats the two LLM calls.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from agents.diary_agent import adapt_for_picturebook
from agents.image_agent import generate_page_image, image_api_key_for_page
from agents.story_agent import (
    DEFAULT_STYLE,
    STYLES,
    TOTAL_IMAGES,
    GenerationServiceError,
    flatten_image_prompts,
    normalize_style,
    write_page_prompts,
    write_story,
)
from auth.dependencies import get_current_user_id, require_same_origin
from database import get_db
from services.character_assets import ensure_visual_profile, load_character_reference
from services.media_store import (
    MediaStoreError,
    staged_generated_media,
    store_generated_asset,
)
from services.generation_quota import (
    GenerationQuotaExceeded,
    consume_quota,
    quota_detail,
)
from services.generation_slots import (
    CATEGORY_PICTUREBOOK,
    GenerationSlotConflict,
    conflict_detail,
    require_available_slot,
)
from services.story_workflow import (
    DAILY,
    STALE_GENERATION_ERROR,
    TIME_STORY,
    mark_work_picturebook_failed,
    promote_completed_work_picturebook,
    sanitize_generation_error,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/picturebook", tags=["picturebook"])

# Stage labels are user-facing progress copy, not internal state names.
STAGE_LABELS = {
    "queued": "正在排队",
    "character": "正在读取你的小主角",
    "story": "正在把日记改写成故事",
    "prompts": "正在设计每一页的画面",
    "rendering": "正在逐页作画",
    "done": "绘本已完成",
    "failed": "生成失败",
}

_running: set[int] = set()
_lock = asyncio.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class CreateJobRequest(BaseModel):
    style: str = DEFAULT_STYLE


def _direct_diary_source_signature(
    diary_id: int,
    source_text: str,
    allow_imaginative: bool,
    style: str,
) -> str:
    snapshot = {
        "source_kind": "diary",
        "diary_id": diary_id,
        "source_text": source_text,
        "allow_imaginative": allow_imaginative,
        "style": style,
    }
    canonical = json.dumps(
        snapshot,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def _job_payload(db: Any, job_id: int, user_id: int) -> dict:
    cursor = await db.execute(
        "SELECT * FROM picturebook_jobs WHERE id = ? AND user_id = ?",
        (job_id, user_id),
    )
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="picturebook job not found")
    job = dict(row)

    cursor = await db.execute(
        "SELECT page_index, image_id, caption, image_url, status, error "
        "FROM picturebook_pages WHERE job_id = ? ORDER BY page_index",
        (job_id,),
    )
    pages = [dict(item) for item in await cursor.fetchall()]
    ready = sum(1 for page in pages if page["status"] == "ready")

    return {
        "id": job["id"],
        "diary_id": job["diary_id"],
        "work_id": job["work_id"],
        "style": job["style"],
        "status": job["status"],
        "stage": job["stage"],
        "stage_label": STAGE_LABELS.get(job["stage"], job["stage"]),
        "error": sanitize_generation_error(job["error"]) if job["error"] else None,
        "total_pages": job["total_pages"],
        "ready_pages": ready,
        "created_at": job["created_at"],
        "updated_at": job["updated_at"],
        # Only the rendered images are exposed; the intermediate story JSON and
        # prompt plan stay server-side.
        "pages": [
            {
                "page_index": page["page_index"],
                "image_id": page["image_id"],
                "caption": page["caption"],
                "image_url": page["image_url"],
                "status": page["status"],
                "error": sanitize_generation_error(page["error"])
                if page["error"]
                else None,
            }
            for page in pages
        ],
    }


async def _set_stage(db: Any, job_id: int, stage: str, status: str = "running") -> None:
    await db.execute(
        "UPDATE picturebook_jobs SET stage = ?, status = ?, updated_at = ? WHERE id = ?",
        (stage, status, _now(), job_id),
    )
    await db.commit()


async def _fail(
    db: Any,
    job_id: int,
    message: str,
    *,
    stage: str = "failed",
) -> None:
    cursor = await db.execute(
        "SELECT user_id, work_id FROM picturebook_jobs WHERE id = ?",
        (job_id,),
    )
    row = await cursor.fetchone()
    if row and row["work_id"] is not None:
        handled = await mark_work_picturebook_failed(
            db,
            user_id=row["user_id"],
            job_id=job_id,
            message=message,
            stale=stage == "stale",
        )
        if handled:
            return
    await db.execute(
        "UPDATE picturebook_jobs SET status = 'failed', stage = ?, error = ?, updated_at = ? "
        "WHERE id = ?",
        (stage, message[:500], _now(), job_id),
    )
    await db.commit()


async def _render_pending_pages(
    db: Any,
    job_id: int,
    user_id: int,
    character: object,
) -> int:
    """Render every page that is not ready yet. Returns the failure count.

    每张图一完成就落库并提交事务:用户轮询时 ready_pages 是真实进度,
    而不是整批 gather 结束后才从 0 跳到 9。
    """
    cursor = await db.execute(
        "SELECT page_index, image_prompt FROM picturebook_pages "
        "WHERE job_id = ? AND status != 'ready' ORDER BY page_index",
        (job_id,),
    )
    todo = [dict(row) for row in await cursor.fetchall()]
    if not todo:
        return 0

    await db.execute(
        "UPDATE picturebook_pages SET status = 'rendering', error = NULL, "
        "updated_at = ? WHERE job_id = ? AND status != 'ready'",
        (_now(), job_id),
    )
    await db.commit()

    async def render_one(page: dict) -> tuple[dict, Any, Optional[BaseException]]:
        try:
            result = await generate_page_image(
                page["image_prompt"],
                character,
                api_key=image_api_key_for_page(page["page_index"]),
            )
            return page, result, None
        except BaseException as exc:  # noqa: BLE001 - 交由统一分支分类处理
            return page, None, exc

    failures = 0
    cancelled = False
    unexpected_render_error = False
    tasks = [render_one(page) for page in todo]
    for completed in asyncio.as_completed(tasks):
        page, result, error = await completed
        index = page["page_index"]
        if isinstance(error, asyncio.CancelledError):
            cancelled = True
            continue
        if isinstance(error, GenerationServiceError):
            failures += 1
            await db.execute(
                "UPDATE picturebook_pages SET status = 'failed', error = ?, "
                "updated_at = ? WHERE job_id = ? AND page_index = ?",
                (sanitize_generation_error(str(error)), _now(), job_id, index),
            )
            await db.commit()
            continue
        if error is not None:
            unexpected_render_error = True
            continue

        try:
            async with staged_generated_media(db) as stage:
                asset = await store_generated_asset(
                    db,
                    user_id,
                    result,
                    stage=stage,
                )
                await db.execute(
                    "UPDATE picturebook_pages SET status = 'ready', asset_id = ?, "
                    "image_url = ?, error = NULL, updated_at = ? "
                    "WHERE job_id = ? AND page_index = ?",
                    (asset.id, asset.url, _now(), job_id, index),
                )
        except MediaStoreError as exc:
            failures += 1
            await db.execute(
                "UPDATE picturebook_pages SET status = 'failed', error = ?, "
                "updated_at = ? WHERE job_id = ? AND page_index = ?",
                (str(exc)[:300], _now(), job_id, index),
            )
            await db.commit()
        except Exception:
            raise RuntimeError("picturebook media storage failed") from None

    if cancelled:
        raise asyncio.CancelledError() from None
    if unexpected_render_error:
        raise RuntimeError("picturebook page rendering failed") from None
    return failures


async def _advance(job_id: int, user_id: int) -> None:
    """Drive one job from wherever it is to done, persisting every stage."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM picturebook_jobs WHERE id = ? AND user_id = ?",
            (job_id, user_id),
        )
        row = await cursor.fetchone()
        if not row:
            return
        job = dict(row)

        await _set_stage(db, job_id, "character")
        character = await load_character_reference(db, user_id)
        if character is not None:
            character = await ensure_visual_profile(db, user_id, character)
        profile_text = character.profile_text() if character else ""
        signature = character.signature if character else ""

        story = json.loads(job["story_json"]) if job["story_json"] else None
        plan = json.loads(job["pages_json"]) if job["pages_json"] else None
        is_work_job = job["work_id"] is not None
        # Legacy diary jobs can rebuild prompts after a character change. A
        # work-backed attempt is immutable: a different character makes the
        # attempt stale and the user must replace it.
        if is_work_job:
            if signature != (job["character_signature"] or ""):
                return await _fail(
                    db,
                    job_id,
                    STALE_GENERATION_ERROR,
                    stage="stale",
                )
        elif signature != (job["character_signature"] or ""):
            story = None
            plan = None

        if story is None:
            await _set_stage(db, job_id, "story")
            if is_work_job:
                diary_text = (job["source_text"] or "").strip()
                if not diary_text:
                    return await _fail(db, job_id, "绘本来源不存在")
                # 遵循 SEC-AUTH-002 规范: the work kind must belong to the
                # authenticated job owner before the attempt snapshot is used.
                cursor = await db.execute(
                    """
                    SELECT kind
                    FROM story_works AS work
                    WHERE work.id = ?
                      AND work.owner_user_id = ?
                    """,
                    (job["work_id"], user_id),
                )
                source_context = await cursor.fetchone()
                if not source_context:
                    return await _fail(db, job_id, "绘本来源不存在")
                if source_context["kind"] == DAILY:
                    diary_text = await adapt_for_picturebook(
                        diary_text,
                        allow_imaginative=bool(job["allow_imaginative"]),
                    )
                elif source_context["kind"] != TIME_STORY:
                    return await _fail(db, job_id, "绘本来源不存在")
                story = await write_story(diary_text, profile_text, job["style"])
                await db.execute(
                    "UPDATE picturebook_jobs SET story_json = ?, pages_json = NULL, "
                    "updated_at = ? WHERE id = ?",
                    (json.dumps(story, ensure_ascii=False), _now(), job_id),
                )
            else:
                diary_text = (job["source_text"] or "").strip()
                if not diary_text:
                    return await _fail(db, job_id, "绘本来源快照不存在，请重新生成")

                diary_text = await adapt_for_picturebook(
                    diary_text,
                    allow_imaginative=bool(job["allow_imaginative"]),
                )
                story = await write_story(diary_text, profile_text, job["style"])
                await db.execute(
                    "UPDATE picturebook_jobs SET story_json = ?, pages_json = NULL, "
                    "character_signature = ?, updated_at = ? WHERE id = ?",
                    (json.dumps(story, ensure_ascii=False), signature, _now(), job_id),
                )
            await db.commit()
            plan = None

        if plan is None:
            await _set_stage(db, job_id, "prompts")
            plan = await write_page_prompts(story, profile_text, job["style"])
            # Captions shown to people come from the approved Chinese story.
            # Stage 2 uses English for image prompts and must never overwrite UI copy.
            entries = flatten_image_prompts(plan, story)
            await db.execute(
                "UPDATE picturebook_jobs SET pages_json = ?, total_pages = ?, "
                "updated_at = ? WHERE id = ?",
                (
                    json.dumps(plan, ensure_ascii=False),
                    len(entries) or TOTAL_IMAGES,
                    _now(),
                    job_id,
                ),
            )
            await db.execute("DELETE FROM picturebook_pages WHERE job_id = ?", (job_id,))
            for entry in entries:
                await db.execute(
                    "INSERT INTO picturebook_pages (job_id, page_index, image_id, "
                    "caption, image_prompt, status, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)",
                    (
                        job_id,
                        entry["page_index"],
                        entry["image_id"],
                        entry["caption"],
                        entry["image_prompt"],
                        _now(),
                        _now(),
                    ),
                )
            await db.commit()

        await _set_stage(db, job_id, "rendering")
        failures = await _render_pending_pages(db, job_id, user_id, character)
        if failures:
            await _fail(db, job_id, f"有 {failures} 页没画成，可以重试这几页")
        elif is_work_job:
            await promote_completed_work_picturebook(db, user_id=user_id, job_id=job_id)
        else:
            await _set_stage(db, job_id, "done", status="done")
    except asyncio.CancelledError:
        raise
    except GenerationServiceError as exc:
        await _fail(db, job_id, sanitize_generation_error(str(exc)))
    except Exception:  # noqa: BLE001 - a background task must never vanish silently
        logger.exception("picturebook job %s failed", job_id)
        await _fail(db, job_id, "生成过程出错了，可以重试")
    finally:
        await db.close()
        async with _lock:
            _running.discard(job_id)


async def _spawn(job_id: int, user_id: int) -> None:
    async with _lock:
        if job_id in _running:
            return
        _running.add(job_id)
    asyncio.create_task(_advance(job_id, user_id))


async def resume_running_picturebooks() -> None:
    """进程重启后恢复所有保留的 running 绘本任务;幂等,可重复调用。"""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT id, user_id FROM picturebook_jobs WHERE status = 'running'"
        )
        rows = await cursor.fetchall()
    finally:
        await db.close()
    for row in rows:
        await _spawn(int(row["id"]), int(row["user_id"]))


@router.post("/diary/{diary_id}")
async def create_picturebook_job(
    diary_id: int,
    payload: CreateJobRequest,
    _: None = Depends(require_same_origin),
    user_id: int = Depends(get_current_user_id),
):
    """Start (or resume) the picturebook for a diary and return the job at once."""
    db = await get_db()
    should_spawn = True
    try:
        await db.execute("BEGIN IMMEDIATE")
        cursor = await db.execute(
            "SELECT id, text, draft_text, emotion_mode FROM diaries "
            "WHERE id = ? AND user_id = ?",
            (diary_id, user_id),
        )
        diary = await cursor.fetchone()
        if not diary:
            raise HTTPException(status_code=404, detail="diary not found")

        style = normalize_style(payload.style)
        source_text = (diary["draft_text"] or diary["text"] or "").strip()
        allow_imaginative = diary["emotion_mode"] == "imagery"
        source_signature = _direct_diary_source_signature(
            diary_id,
            source_text,
            allow_imaginative,
            style,
        )
        cursor = await db.execute(
            "SELECT * FROM picturebook_jobs WHERE diary_id = ? AND user_id = ? "
            "ORDER BY id DESC LIMIT 1",
            (diary_id, user_id),
        )
        existing = await cursor.fetchone()
        existing_job = dict(existing) if existing else None
        if (
            existing_job
            and existing_job["source_text"] is not None
            and existing_job["source_signature"] == source_signature
        ):
            job_id = existing_job["id"]
            should_spawn = existing_job["status"] != "done"
            if should_spawn:
                # 同一事务内先占分区槽位,再把这条任务翻回 running。
                await require_available_slot(
                    db,
                    user_id=user_id,
                    category=CATEGORY_PICTUREBOOK,
                    current_job_id=job_id,
                )
                await db.execute(
                    "UPDATE picturebook_jobs SET status = 'running', error = NULL, "
                    "updated_at = ? WHERE id = ?",
                    (_now(), job_id),
                )
        else:
            await require_available_slot(
                db,
                user_id=user_id,
                category=CATEGORY_PICTUREBOOK,
            )
            # 只有真正新建任务才扣体验次数;上面的复用分支(同签名重跑)不扣。
            await consume_quota(db, user_id=user_id, category=CATEGORY_PICTUREBOOK)
            cursor = await db.execute(
                "INSERT INTO picturebook_jobs (user_id, diary_id, source_text, "
                "source_signature, style, status, stage, allow_imaginative, "
                "total_pages, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, 'running', 'queued', ?, ?, ?, ?)",
                (
                    user_id,
                    diary_id,
                    source_text,
                    source_signature,
                    style,
                    int(allow_imaginative),
                    TOTAL_IMAGES,
                    _now(),
                    _now(),
                ),
            )
            job_id = cursor.lastrowid

        await db.commit()
        payload_out = await _job_payload(db, job_id, user_id)
    except GenerationSlotConflict as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=conflict_detail(exc)) from exc
    except GenerationQuotaExceeded as exc:
        await db.rollback()
        raise HTTPException(status_code=403, detail=quota_detail(exc)) from exc
    except Exception:
        await db.rollback()
        raise
    finally:
        await db.close()

    if should_spawn:
        await _spawn(job_id, user_id)
    return payload_out


@router.get("/{job_id}")
async def get_picturebook_job(
    job_id: int,
    user_id: int = Depends(get_current_user_id),
):
    db = await get_db()
    try:
        return await _job_payload(db, job_id, user_id)
    finally:
        await db.close()


@router.get("/diary/{diary_id}/latest")
async def get_latest_picturebook(
    diary_id: int,
    style: Optional[str] = None,
    user_id: int = Depends(get_current_user_id),
):
    """The newest book for a diary, so reopening the editor restores progress."""
    db = await get_db()
    try:
        if style:
            cursor = await db.execute(
                "SELECT id FROM picturebook_jobs WHERE diary_id = ? AND user_id = ? "
                "AND style = ? ORDER BY id DESC LIMIT 1",
                (diary_id, user_id, normalize_style(style)),
            )
        else:
            cursor = await db.execute(
                "SELECT id FROM picturebook_jobs WHERE diary_id = ? AND user_id = ? "
                "ORDER BY id DESC LIMIT 1",
                (diary_id, user_id),
            )
        row = await cursor.fetchone()
        if not row:
            return None
        return await _job_payload(db, dict(row)["id"], user_id)
    finally:
        await db.close()


@router.post("/{job_id}/retry")
async def retry_picturebook_job(
    job_id: int,
    _: None = Depends(require_same_origin),
    user_id: int = Depends(get_current_user_id),
):
    """Re-render only what is missing; the two LLM stages are reused as-is."""
    db = await get_db()
    try:
        payload_out = await _job_payload(db, job_id, user_id)
        if payload_out["work_id"] is not None:
            raise HTTPException(
                status_code=409,
                detail="work-backed picturebooks must be retried from the story work",
            )
        await db.execute("BEGIN IMMEDIATE")
        cursor = await db.execute(
            "SELECT diary_id, source_text, source_signature, allow_imaginative, style "
            "FROM picturebook_jobs WHERE id = ? AND user_id = ?",
            (job_id, user_id),
        )
        job = await cursor.fetchone()
        source_text = job["source_text"] if job else None
        snapshot_was_missing = source_text is None
        allow_imaginative = bool(job["allow_imaginative"]) if job else False
        if snapshot_was_missing:
            cursor = await db.execute(
                "SELECT text, draft_text, emotion_mode FROM diaries "
                "WHERE id = ? AND user_id = ?",
                (job["diary_id"], user_id),
            )
            diary = await cursor.fetchone()
            if not diary:
                raise HTTPException(status_code=409, detail="diary source is unavailable")
            source_text = (diary["draft_text"] or diary["text"] or "").strip()
            if not source_text:
                raise HTTPException(status_code=409, detail="diary source is unavailable")
            allow_imaginative = diary["emotion_mode"] == "imagery"
        source_signature = job["source_signature"] or _direct_diary_source_signature(
            job["diary_id"],
            source_text,
            allow_imaginative,
            job["style"],
        )
        if snapshot_was_missing:
            await db.execute(
                "UPDATE picturebook_jobs SET story_json = NULL, pages_json = NULL, "
                "character_signature = NULL WHERE id = ? AND user_id = ?",
                (job_id, user_id),
            )
            await db.execute(
                "DELETE FROM picturebook_pages WHERE job_id = ?",
                (job_id,),
            )
        await require_available_slot(
            db,
            user_id=user_id,
            category=CATEGORY_PICTUREBOOK,
            current_job_id=job_id,
        )
        await db.execute(
            "UPDATE picturebook_jobs SET source_text = ?, source_signature = ?, "
            "allow_imaginative = ?, status = 'running', stage = 'queued', "
            "error = NULL, updated_at = ? WHERE id = ? AND user_id = ?",
            (
                source_text,
                source_signature,
                int(allow_imaginative),
                _now(),
                job_id,
                user_id,
            ),
        )
        await db.commit()
        payload_out = await _job_payload(db, job_id, user_id)
    except GenerationSlotConflict as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=conflict_detail(exc)) from exc
    except Exception:
        await db.rollback()
        raise
    finally:
        await db.close()

    await _spawn(job_id, user_id)
    return payload_out


@router.get("/styles/list")
async def list_picturebook_styles():
    return {"styles": sorted(STYLES)}
