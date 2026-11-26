from __future__ import annotations

import hashlib
import json
from datetime import date as date_type
from datetime import datetime, timezone
from typing import Any, Mapping, Optional

from agents import time_story_agent
from services.generation_errors import GenerationServiceError
from agents.story_agent import TOTAL_IMAGES, normalize_style
from agents.time_story_agent import StorylineCandidate
from services.character_assets import ensure_visual_profile, load_character_reference
from services.generation_quota import consume_quota
from services.generation_slots import (
    CATEGORY_PICTUREBOOK,
    require_available_slot,
)
from services.media_store import canonical_media_url, parse_canonical_media_url


DAILY = "daily_picturebook"
TIME_STORY = "time_story"
DRAFT = "draft"
READY = "ready"
PUBLISHED = "published"
SOURCES_SELECTED = "sources_selected"
STORYLINES_READY = "storylines_ready"
NARRATIVE_EDITING = "narrative_editing"
NARRATIVE_CONFIRMED = "narrative_confirmed"
RENDER_FAILED = "render_failed"
RENDERING = "rendering"
STALE = "stale"
EDITABLE_STAGES = {NARRATIVE_CONFIRMED, RENDER_FAILED}
SAFE_GENERATION_ERROR = "生成过程出错了，可以重试"
STALE_GENERATION_ERROR = "生成依据已更新，请重新生成绘本"


class StoryWorkflowError(Exception):
    pass


class StoryWorkflowNotFound(StoryWorkflowError):
    pass


class StoryWorkflowConflict(StoryWorkflowError):
    pass


class StoryWorkflowValidationError(StoryWorkflowError):
    pass


def utc_timestamp() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash_json(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def picturebook_source_signature(
    work: Mapping[str, Any],
    source_text: str,
    allow_imaginative: bool,
) -> str:
    payload = {
        "work_id": work["id"],
        "kind": work["kind"],
        "source_diary_ids": work["source_diary_ids"],
        "source_snapshot_hash": work["source_snapshot_hash"],
        "source_text": source_text,
        "allow_imaginative": allow_imaginative,
        "style": work["style"],
        "character_signature": work["character_signature"],
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def sanitize_generation_error(message: Optional[str], *, stale: bool = False) -> str:
    if stale:
        return STALE_GENERATION_ERROR
    cleaned = (message or "").strip()
    if cleaned.startswith("有 ") and "页没画成" in cleaned:
        return cleaned[:120]
    return SAFE_GENERATION_ERROR


def _paragraphs(body: str) -> list[str]:
    return [part.strip() for part in body.split("\n\n") if part.strip()]


def _clean_selected_segments(
    selected_segments: list[str],
    *,
    allowed_paragraphs: list[str],
) -> list[str]:
    cleaned = [segment.strip() for segment in selected_segments if segment.strip()]
    if not cleaned:
        raise StoryWorkflowValidationError("selected_segments is required")
    allowed = set(allowed_paragraphs)
    if any(segment not in allowed for segment in cleaned):
        raise StoryWorkflowValidationError("selected segment must match a paragraph")
    return cleaned


def _title_or_default(title: Optional[str], diary: Mapping[str, Any]) -> str:
    cleaned = (title or "").strip()
    return cleaned or f"{diary['date']} 的绘本"


def _style_or_default(style: Optional[str]) -> str:
    cleaned = (style or "").strip()
    if not cleaned:
        raise StoryWorkflowValidationError("style is required")
    return cleaned


def _parse_iso_date(value: str) -> date_type:
    try:
        return date_type.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise StoryWorkflowValidationError("date is invalid") from exc


def _time_story_title_or_default(
    title: Optional[str],
    *,
    start_date: str,
    end_date: str,
) -> str:
    cleaned = (title or "").strip()
    if cleaned:
        return cleaned
    if start_date == end_date:
        return f"{start_date} 的时光故事"
    return f"{start_date} 至 {end_date} 的时光故事"


def _ensure_time_story_work(work: Mapping[str, Any]) -> None:
    if work.get("kind") != TIME_STORY:
        raise StoryWorkflowConflict("story work kind is not time story")


def _snapshot_from_diaries(diaries: list[Mapping[str, Any]]) -> dict:
    return {
        "diaries": [
            {
                "id": diary["id"],
                "date": diary["date"],
                "status": diary["status"],
                "body": diary["body"],
            }
            for diary in diaries
        ]
    }


def _snapshot_diaries(snapshot: Mapping[str, Any]) -> list[dict]:
    diaries = snapshot.get("diaries") if isinstance(snapshot, Mapping) else []
    if not isinstance(diaries, list):
        return []
    results = []
    for diary in diaries:
        if not isinstance(diary, Mapping):
            continue
        body = str(diary.get("body") or "")
        if not body.strip():
            continue
        results.append(
            {
                "id": diary.get("id"),
                "date": diary.get("date"),
                "status": diary.get("status"),
                "body": body,
            }
        )
    return results


def _candidate_from_dict(value: Mapping[str, Any]) -> StorylineCandidate:
    source_dates = value.get("source_dates")
    if not isinstance(source_dates, list):
        raise StoryWorkflowConflict("storyline candidates are invalid")
    candidate = StorylineCandidate(
        id=str(value.get("id") or "").strip(),
        title=str(value.get("title") or "").strip(),
        summary=str(value.get("summary") or "").strip(),
        source_dates=[str(item).strip() for item in source_dates if str(item).strip()],
    )
    if not candidate.id or not candidate.title or not candidate.summary:
        raise StoryWorkflowConflict("storyline candidates are invalid")
    return candidate


def _candidate_dicts(value: Any) -> list[dict]:
    if not isinstance(value, list):
        raise StoryWorkflowConflict("storyline candidates are required")
    return [_candidate_from_dict(item).to_dict() for item in value]


def _db_text(value: Optional[str]) -> str:
    return value or ""


async def _load_owned_diary(db: Any, owner_user_id: int, diary_id: int) -> dict:
    cursor = await db.execute(
        """
        SELECT id, date, status, text
        FROM diaries
        WHERE id = ? AND user_id = ?
        """,
        (diary_id, owner_user_id),
    )
    row = await cursor.fetchone()
    if not row:
        raise StoryWorkflowNotFound("diary not found")
    body = row["text"] or ""
    paragraphs = _paragraphs(body)
    if not paragraphs:
        raise StoryWorkflowValidationError("diary body is empty")
    return {
        "id": row["id"],
        "date": row["date"],
        "status": row["status"],
        "body": body,
        "paragraphs": paragraphs,
    }


async def _load_owned_time_story_diaries_by_ids(
    db: Any,
    owner_user_id: int,
    source_diary_ids: list[int],
    *,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> list[dict]:
    if start_date is not None:
        start = _parse_iso_date(start_date)
    else:
        start = None
    if end_date is not None:
        end = _parse_iso_date(end_date)
    else:
        end = None
    if start is not None and end is not None:
        if end < start:
            raise StoryWorkflowValidationError("end_date must be on or after start_date")
        if (end - start).days > 30:
            raise StoryWorkflowValidationError("time story range cannot exceed 31 days")

    cleaned_ids: list[int] = []
    seen: set[int] = set()
    for diary_id in source_diary_ids:
        if diary_id <= 0:
            raise StoryWorkflowValidationError("source diary id is invalid")
        if diary_id in seen:
            raise StoryWorkflowValidationError("duplicate source diary id")
        seen.add(diary_id)
        cleaned_ids.append(diary_id)
    if not cleaned_ids:
        raise StoryWorkflowValidationError("at least one source diary is required")

    by_id: dict[int, dict] = {}
    for diary_id in cleaned_ids:
        cursor = await db.execute(
            """
            SELECT id, date, status, text, draft_text
            FROM diaries
            WHERE id = ? AND user_id = ?
            """,
            (diary_id, owner_user_id),
        )
        row = await cursor.fetchone()
        if not row:
            raise StoryWorkflowNotFound("diary not found")
        body = row["text"] or row["draft_text"] or ""
        if not body.strip():
            raise StoryWorkflowValidationError("diary body is empty")
        if start_date is not None and row["date"] < start_date:
            raise StoryWorkflowValidationError("source diary is outside date range")
        if end_date is not None and row["date"] > end_date:
            raise StoryWorkflowValidationError("source diary is outside date range")
        by_id[diary_id] = {
            "id": row["id"],
            "date": row["date"],
            "status": row["status"],
            "body": body,
        }
    return [by_id[diary_id] for diary_id in cleaned_ids]


async def _load_owned_time_story_diaries_by_range(
    db: Any,
    owner_user_id: int,
    *,
    start_date: str,
    end_date: str,
) -> list[dict]:
    start = _parse_iso_date(start_date)
    end = _parse_iso_date(end_date)
    if end < start:
        raise StoryWorkflowValidationError("end_date must be on or after start_date")
    if (end - start).days > 30:
        raise StoryWorkflowValidationError("time story range cannot exceed 31 days")
    cursor = await db.execute(
        """
        SELECT id, date, status, text, draft_text
        FROM diaries
        WHERE user_id = ?
          AND date >= ?
          AND date <= ?
          AND COALESCE(NULLIF(TRIM(text), ''), NULLIF(TRIM(draft_text), '')) IS NOT NULL
        ORDER BY date ASC, id ASC
        """,
        (owner_user_id, start.isoformat(), end.isoformat()),
    )
    diaries = [
        {
            "id": row["id"],
            "date": row["date"],
            "status": row["status"],
            "body": row["text"] or row["draft_text"] or "",
        }
        for row in await cursor.fetchall()
    ]
    if not diaries:
        raise StoryWorkflowValidationError("at least one source diary is required")
    return diaries


def _source_snapshot(diary: Mapping[str, Any]) -> dict:
    return {
        "diaries": [
            {
                "id": diary["id"],
                "date": diary["date"],
                "status": diary["status"],
                "body": diary["body"],
            }
        ]
    }


async def create_daily_picturebook_draft(
    db: Any,
    *,
    owner_user_id: int,
    diary_id: int,
    selected_segments: list[str],
    title: Optional[str] = None,
    style: Optional[str] = None,
) -> dict:
    diary = await _load_owned_diary(db, owner_user_id, diary_id)
    selected = _clean_selected_segments(
        selected_segments,
        allowed_paragraphs=diary["paragraphs"],
    )
    snapshot = _source_snapshot(diary)
    now = utc_timestamp()

    await db.execute("BEGIN IMMEDIATE")
    try:
        cursor = await db.execute(
            """
            INSERT INTO story_works (
                owner_user_id, source_diary_id, title, medium, narrative_mode,
                style, selected_segments_json, status, kind, stage,
                source_snapshot_json, source_snapshot_hash, source_start_date,
                source_end_date, display_start_date, display_end_date,
                stage_updated_at, created_at, updated_at
            ) VALUES (
                ?, ?, ?, 'picture_book', 'daily', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?
            )
            """,
            (
                owner_user_id,
                diary_id,
                _title_or_default(title, diary),
                _style_or_default(style),
                canonical_json(selected),
                DRAFT,
                DAILY,
                NARRATIVE_CONFIRMED,
                canonical_json(snapshot),
                _hash_json(snapshot),
                diary["date"],
                diary["date"],
                diary["date"],
                diary["date"],
                now,
                now,
                now,
            ),
        )
        work_id = cursor.lastrowid
        await db.execute(
            """
            INSERT INTO story_work_diaries (work_id, diary_id, ordinal)
            VALUES (?, ?, 0)
            """,
            (work_id, diary_id),
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    return await get_story_work_resume(db, owner_user_id=owner_user_id, work_id=work_id)


async def create_time_story_draft(
    db: Any,
    *,
    owner_user_id: int,
    source_diary_ids: Optional[list[int]] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    title: Optional[str] = None,
    style: Optional[str] = None,
) -> dict:
    if source_diary_ids:
        if start_date is not None:
            _parse_iso_date(start_date)
        if end_date is not None:
            _parse_iso_date(end_date)
        if start_date is not None and end_date is not None and end_date < start_date:
            raise StoryWorkflowValidationError("end_date must be on or after start_date")
        diaries = await _load_owned_time_story_diaries_by_ids(
            db,
            owner_user_id,
            source_diary_ids,
            start_date=start_date,
            end_date=end_date,
        )
    elif start_date is not None and end_date is not None:
        diaries = await _load_owned_time_story_diaries_by_range(
            db,
            owner_user_id,
            start_date=start_date,
            end_date=end_date,
        )
    else:
        raise StoryWorkflowValidationError("time story sources are required")

    source_start_date = start_date or min(str(diary["date"]) for diary in diaries)
    source_end_date = end_date or max(str(diary["date"]) for diary in diaries)
    snapshot = _snapshot_from_diaries(diaries)
    now = utc_timestamp()

    await db.execute("BEGIN IMMEDIATE")
    try:
        cursor = await db.execute(
            """
            INSERT INTO story_works (
                owner_user_id, source_diary_id, title, medium, narrative_mode,
                style, selected_segments_json, status, kind, stage,
                source_snapshot_json, source_snapshot_hash, source_start_date,
                source_end_date, display_start_date, display_end_date,
                stage_updated_at, created_at, updated_at
            ) VALUES (
                ?, NULL, ?, 'picture_book', 'range', ?, '[]', ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?
            )
            """,
            (
                owner_user_id,
                _time_story_title_or_default(
                    title,
                    start_date=source_start_date,
                    end_date=source_end_date,
                ),
                _style_or_default(style),
                DRAFT,
                TIME_STORY,
                SOURCES_SELECTED,
                canonical_json(snapshot),
                _hash_json(snapshot),
                source_start_date,
                source_end_date,
                source_start_date,
                source_end_date,
                now,
                now,
                now,
            ),
        )
        work_id = cursor.lastrowid
        for ordinal, diary in enumerate(diaries):
            await db.execute(
                """
                INSERT INTO story_work_diaries (work_id, diary_id, ordinal)
                VALUES (?, ?, ?)
                """,
                (work_id, diary["id"], ordinal),
            )
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    return await get_story_work_resume(db, owner_user_id=owner_user_id, work_id=work_id)


async def _require_owned_work(db: Any, owner_user_id: int, work_id: int) -> dict:
    # SDD BE-AUTH-001/SEC-AUTH-002: the caller supplies a server-derived user id,
    # and every resource read is scoped to that owner.
    cursor = await db.execute(
        "SELECT * FROM story_works WHERE id = ? AND owner_user_id = ?",
        (work_id, owner_user_id),
    )
    row = await cursor.fetchone()
    if not row:
        raise StoryWorkflowNotFound("story work not found")
    return dict(row)


def _ensure_daily_work(work: Mapping[str, Any]) -> None:
    if work.get("kind") != DAILY:
        raise StoryWorkflowConflict("story work kind is not editable here")


async def replace_daily_picturebook_sources(
    db: Any,
    *,
    owner_user_id: int,
    work_id: int,
    diary_id: int,
    selected_segments: list[str],
) -> dict:
    work = await _require_owned_work(db, owner_user_id, work_id)
    _ensure_daily_work(work)
    diary = await _load_owned_diary(db, owner_user_id, diary_id)
    selected = _clean_selected_segments(
        selected_segments,
        allowed_paragraphs=diary["paragraphs"],
    )
    snapshot = _source_snapshot(diary)
    now = utc_timestamp()

    await db.execute("BEGIN IMMEDIATE")
    try:
        # SDD BE-SQL-001/SEC-AUTH-002: parameterized, owner-scoped and
        # state-conditional so stale writers get a conflict.
        cursor = await db.execute(
            """
            UPDATE story_works
            SET source_diary_id = ?,
                selected_segments_json = ?,
                source_snapshot_json = ?,
                source_snapshot_hash = ?,
                source_start_date = ?,
                source_end_date = ?,
                display_start_date = ?,
                display_end_date = ?,
                stage = ?,
                active_picturebook_job_id = NULL,
                picturebook_job_id = NULL,
                generation_error = NULL,
                cover_asset_id = NULL,
                selected_storyline_json = NULL,
                storyline_candidates_json = NULL,
                narrative_text = NULL,
                stage_updated_at = ?,
                updated_at = ?
            WHERE id = ?
              AND owner_user_id = ?
              AND kind = ?
              AND status = ?
              AND stage IN (?, ?)
            """,
            (
                diary_id,
                canonical_json(selected),
                canonical_json(snapshot),
                _hash_json(snapshot),
                diary["date"],
                diary["date"],
                diary["date"],
                diary["date"],
                NARRATIVE_CONFIRMED,
                now,
                now,
                work_id,
                owner_user_id,
                DAILY,
                DRAFT,
                NARRATIVE_CONFIRMED,
                RENDER_FAILED,
            ),
        )
        if cursor.rowcount == 0:
            raise StoryWorkflowConflict("story work changed state")
        await db.execute("DELETE FROM story_work_diaries WHERE work_id = ?", (work_id,))
        await db.execute(
            """
            INSERT INTO story_work_diaries (work_id, diary_id, ordinal)
            VALUES (?, ?, 0)
            """,
            (work_id, diary_id),
        )
        await db.execute("DELETE FROM work_assets WHERE work_id = ?", (work_id,))
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    return await get_story_work_resume(db, owner_user_id=owner_user_id, work_id=work_id)


async def replace_time_story_sources(
    db: Any,
    *,
    owner_user_id: int,
    work_id: int,
    source_diary_ids: Optional[list[int]] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> dict:
    work = await _require_owned_work(db, owner_user_id, work_id)
    _ensure_time_story_work(work)
    if work["status"] != DRAFT or work["stage"] == RENDERING:
        raise StoryWorkflowConflict("story work changed state")
    if source_diary_ids:
        diaries = await _load_owned_time_story_diaries_by_ids(
            db,
            owner_user_id,
            source_diary_ids,
            start_date=start_date,
            end_date=end_date,
        )
    elif start_date is not None and end_date is not None:
        diaries = await _load_owned_time_story_diaries_by_range(
            db,
            owner_user_id,
            start_date=start_date,
            end_date=end_date,
        )
    else:
        raise StoryWorkflowValidationError("time story sources are required")

    source_start_date = start_date or min(str(diary["date"]) for diary in diaries)
    source_end_date = end_date or max(str(diary["date"]) for diary in diaries)
    snapshot = _snapshot_from_diaries(diaries)
    now = utc_timestamp()

    await db.execute("BEGIN IMMEDIATE")
    try:
        cursor = await db.execute(
            """
            UPDATE story_works
            SET source_diary_id = NULL,
                selected_segments_json = '[]',
                source_snapshot_json = ?,
                source_snapshot_hash = ?,
                source_start_date = ?,
                source_end_date = ?,
                display_start_date = ?,
                display_end_date = ?,
                stage = ?,
                active_picturebook_job_id = NULL,
                picturebook_job_id = NULL,
                generation_error = NULL,
                cover_asset_id = NULL,
                selected_storyline_json = NULL,
                storyline_candidates_json = NULL,
                narrative_text = NULL,
                stage_updated_at = ?,
                updated_at = ?
            WHERE id = ?
              AND owner_user_id = ?
              AND kind = ?
              AND status = ?
              AND stage != ?
            """,
            (
                canonical_json(snapshot),
                _hash_json(snapshot),
                source_start_date,
                source_end_date,
                source_start_date,
                source_end_date,
                SOURCES_SELECTED,
                now,
                now,
                work_id,
                owner_user_id,
                TIME_STORY,
                DRAFT,
                RENDERING,
            ),
        )
        if cursor.rowcount == 0:
            raise StoryWorkflowConflict("story work changed state")
        await db.execute("DELETE FROM story_work_diaries WHERE work_id = ?", (work_id,))
        for ordinal, diary in enumerate(diaries):
            await db.execute(
                """
                INSERT INTO story_work_diaries (work_id, diary_id, ordinal)
                VALUES (?, ?, ?)
                """,
                (work_id, diary["id"], ordinal),
            )
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    return await get_story_work_resume(db, owner_user_id=owner_user_id, work_id=work_id)


async def update_daily_picturebook_draft_metadata(
    db: Any,
    *,
    owner_user_id: int,
    work_id: int,
    title: Optional[str] = None,
    style: Optional[str] = None,
    selected_storyline_id: Optional[str] = None,
    narrative_text: Optional[str] = None,
) -> dict:
    work = await _require_owned_work(db, owner_user_id, work_id)
    if work.get("kind") == TIME_STORY:
        if selected_storyline_id is not None:
            return await select_time_story_storyline(
                db,
                owner_user_id=owner_user_id,
                work_id=work_id,
                selected_storyline_id=selected_storyline_id,
            )
        if narrative_text is not None:
            return await update_time_story_narrative(
                db,
                owner_user_id=owner_user_id,
                work_id=work_id,
                narrative_text=narrative_text,
            )
        return await update_time_story_draft_metadata(
            db,
            owner_user_id=owner_user_id,
            work_id=work_id,
            title=title,
            style=style,
        )
    _ensure_daily_work(work)
    if selected_storyline_id is not None or narrative_text is not None:
        raise StoryWorkflowConflict("story work kind is not editable here")
    next_title = work["title"] if title is None else title.strip()
    next_style = work["style"] if style is None else style.strip()
    if not next_title or not next_style:
        raise StoryWorkflowValidationError("title and style must be non-empty")
    style_changed = next_style != work["style"]
    now = utc_timestamp()

    await db.execute("BEGIN IMMEDIATE")
    try:
        # SDD BE-SQL-001/SEC-AUTH-002: parameterized owner-scoped conditional update.
        if style_changed:
            cursor = await db.execute(
                """
                UPDATE story_works
                SET title = ?,
                    style = ?,
                    stage = ?,
                    active_picturebook_job_id = NULL,
                    picturebook_job_id = NULL,
                    generation_error = NULL,
                    cover_asset_id = NULL,
                    stage_updated_at = ?,
                    updated_at = ?
                WHERE id = ?
                  AND owner_user_id = ?
                  AND kind = ?
                  AND status = ?
                  AND stage IN (?, ?)
                """,
                (
                    next_title,
                    next_style,
                    NARRATIVE_CONFIRMED,
                    now,
                    now,
                    work_id,
                    owner_user_id,
                    DAILY,
                    DRAFT,
                    NARRATIVE_CONFIRMED,
                    RENDER_FAILED,
                ),
            )
        else:
            cursor = await db.execute(
                """
                UPDATE story_works
                SET title = ?, style = ?, updated_at = ?
                WHERE id = ?
                  AND owner_user_id = ?
                  AND kind = ?
                  AND status = ?
                  AND stage IN (?, ?)
                """,
                (
                    next_title,
                    next_style,
                    now,
                    work_id,
                    owner_user_id,
                    DAILY,
                    DRAFT,
                    NARRATIVE_CONFIRMED,
                    RENDER_FAILED,
                ),
            )
        if cursor.rowcount == 0:
            raise StoryWorkflowConflict("story work changed state")
        if style_changed:
            await db.execute("DELETE FROM work_assets WHERE work_id = ?", (work_id,))
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    return await get_story_work_resume(db, owner_user_id=owner_user_id, work_id=work_id)


async def update_time_story_draft_metadata(
    db: Any,
    *,
    owner_user_id: int,
    work_id: int,
    title: Optional[str] = None,
    style: Optional[str] = None,
) -> dict:
    work = await _require_owned_work(db, owner_user_id, work_id)
    _ensure_time_story_work(work)
    if work["status"] != DRAFT or work["stage"] == RENDERING:
        raise StoryWorkflowConflict("story work changed state")
    next_title = work["title"] if title is None else title.strip()
    next_style = work["style"] if style is None else style.strip()
    if not next_title or not next_style:
        raise StoryWorkflowValidationError("title and style must be non-empty")
    style_changed = next_style != work["style"]
    if style_changed and work["stage"] not in EDITABLE_STAGES:
        raise StoryWorkflowConflict("style can only change after narrative confirmation")
    next_stage = NARRATIVE_CONFIRMED if style_changed else work["stage"]
    now = utc_timestamp()

    await db.execute("BEGIN IMMEDIATE")
    try:
        if style_changed:
            cursor = await db.execute(
                """
                UPDATE story_works
                SET title = ?,
                    style = ?,
                    stage = ?,
                    active_picturebook_job_id = NULL,
                    picturebook_job_id = NULL,
                    cover_asset_id = NULL,
                    generation_error = NULL,
                    stage_updated_at = ?,
                    updated_at = ?
                WHERE id = ?
                  AND owner_user_id = ?
                  AND kind = ?
                  AND status = ?
                  AND stage IN (?, ?)
                """,
                (
                    next_title,
                    next_style,
                    next_stage,
                    now,
                    now,
                    work_id,
                    owner_user_id,
                    TIME_STORY,
                    DRAFT,
                    NARRATIVE_CONFIRMED,
                    RENDER_FAILED,
                ),
            )
        else:
            cursor = await db.execute(
                """
                UPDATE story_works
                SET title = ?, style = ?, updated_at = ?
                WHERE id = ?
                  AND owner_user_id = ?
                  AND kind = ?
                  AND status = ?
                  AND stage != ?
                """,
                (
                    next_title,
                    next_style,
                    now,
                    work_id,
                    owner_user_id,
                    TIME_STORY,
                    DRAFT,
                    RENDERING,
                ),
            )
        if cursor.rowcount == 0:
            raise StoryWorkflowConflict("story work changed state")
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    return await get_story_work_resume(db, owner_user_id=owner_user_id, work_id=work_id)


async def duplicate_daily_picturebook_draft(
    db: Any,
    *,
    owner_user_id: int,
    work_id: int,
) -> dict:
    work = await _require_owned_work(db, owner_user_id, work_id)
    if work.get("kind") not in {DAILY, TIME_STORY}:
        raise StoryWorkflowConflict("story work kind is not editable here")
    if work["status"] not in {READY, PUBLISHED}:
        raise StoryWorkflowConflict("only completed works can be duplicated")
    duplicate_stage = (
        NARRATIVE_EDITING if work.get("kind") == TIME_STORY else NARRATIVE_CONFIRMED
    )
    now = utc_timestamp()

    await db.execute("BEGIN IMMEDIATE")
    try:
        cursor = await db.execute(
            """
            INSERT INTO story_works (
                owner_user_id, source_diary_id, title, medium, narrative_mode,
                style, selected_segments_json, forbidden_content, status, kind,
                stage, source_snapshot_json, source_snapshot_hash,
                source_start_date, source_end_date, display_start_date,
                display_end_date, selected_storyline_json,
                storyline_candidates_json, narrative_text, stage_updated_at,
                created_at, updated_at
            )
            SELECT
                owner_user_id, source_diary_id, title, medium, narrative_mode,
                style, selected_segments_json, forbidden_content, ?, kind, ?,
                source_snapshot_json, source_snapshot_hash, source_start_date,
                source_end_date, display_start_date, display_end_date,
                selected_storyline_json, storyline_candidates_json, narrative_text,
                ?, ?, ?
            FROM story_works
            WHERE id = ?
              AND owner_user_id = ?
              AND status IN (?, ?)
            """,
            (
                DRAFT,
                duplicate_stage,
                now,
                now,
                now,
                work_id,
                owner_user_id,
                READY,
                PUBLISHED,
            ),
        )
        if cursor.rowcount == 0:
            raise StoryWorkflowConflict("story work changed state")
        duplicate_id = cursor.lastrowid
        await db.execute(
            """
            INSERT INTO story_work_diaries (work_id, diary_id, ordinal)
            SELECT ?, diary_id, ordinal
            FROM story_work_diaries
            WHERE work_id = ?
            ORDER BY ordinal ASC
            """,
            (duplicate_id, work_id),
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    return await get_story_work_resume(
        db,
        owner_user_id=owner_user_id,
        work_id=duplicate_id,
    )


async def _current_character_signature(db: Any, owner_user_id: int) -> str:
    character = await load_character_reference(db, owner_user_id)
    if character is None:
        return ""
    character = await ensure_visual_profile(db, owner_user_id, character)
    return character.signature


async def _source_diary_rows(
    db: Any,
    *,
    owner_user_id: int,
    work: Mapping[str, Any],
) -> list[dict]:
    cursor = await db.execute(
        """
        SELECT diary.id, diary.text, diary.emotion_mode, link.ordinal
        FROM story_work_diaries AS link
        JOIN diaries AS diary
          ON diary.id = link.diary_id
         AND diary.user_id = ?
        WHERE link.work_id = ?
        ORDER BY link.ordinal ASC
        """,
        (owner_user_id, work["id"]),
    )
    rows = [dict(row) for row in await cursor.fetchall()]
    if rows:
        return rows
    source_diary_id = work.get("source_diary_id")
    if source_diary_id is None:
        return []
    cursor = await db.execute(
        """
        SELECT id, text, emotion_mode, 0 AS ordinal
        FROM diaries
        WHERE id = ? AND user_id = ?
        """,
        (source_diary_id, owner_user_id),
    )
    row = await cursor.fetchone()
    return [dict(row)] if row else []


async def _work_picturebook_source(
    db: Any,
    *,
    owner_user_id: int,
    work: Mapping[str, Any],
    character_signature: str,
) -> tuple[str, str, list[int], bool]:
    if work.get("kind") == TIME_STORY:
        source_text = (work.get("narrative_text") or "").strip()
        if not source_text:
            raise StoryWorkflowConflict("confirmed narrative is required")
        diary_rows = await _source_diary_rows(
            db,
            owner_user_id=owner_user_id,
            work=work,
        )
        source_diary_ids = [row["id"] for row in diary_rows]
        signature_work = {
            **dict(work),
            "source_diary_ids": source_diary_ids,
            "character_signature": character_signature,
        }
        return (
            source_text,
            picturebook_source_signature(signature_work, source_text, False),
            source_diary_ids,
            False,
        )

    selected = _load_json(work.get("selected_segments_json"), [])
    if not isinstance(selected, list):
        raise StoryWorkflowConflict("selected segments are invalid")
    selected_segments = [str(item).strip() for item in selected if str(item).strip()]
    if not selected_segments:
        raise StoryWorkflowConflict("selected segments are required")

    diary_rows = await _source_diary_rows(
        db,
        owner_user_id=owner_user_id,
        work=work,
    )
    source_diary_ids = [row["id"] for row in diary_rows]
    allow_imaginative = bool(
        diary_rows and diary_rows[0].get("emotion_mode") == "imagery"
    )
    selected_set = set(selected_segments)
    missing = set(selected_segments)
    ordered_segments: list[str] = []
    for row in diary_rows:
        for paragraph in _paragraphs(row["text"] or ""):
            if paragraph in selected_set:
                ordered_segments.append(paragraph)
                missing.discard(paragraph)
    if missing:
        raise StoryWorkflowConflict("selected segment no longer exists")
    if not ordered_segments:
        raise StoryWorkflowConflict("selected segments are required")

    source_text = "\n\n".join(ordered_segments)
    signature_work = {
        **dict(work),
        "source_diary_ids": source_diary_ids,
        "character_signature": character_signature,
    }
    return (
        source_text,
        picturebook_source_signature(
            signature_work,
            source_text,
            allow_imaginative,
        ),
        source_diary_ids,
        allow_imaginative,
    )


async def _load_work_picturebook_job(
    db: Any,
    *,
    owner_user_id: int,
    work_id: int,
    job_id: int,
) -> Optional[dict]:
    cursor = await db.execute(
        """
        SELECT *
        FROM picturebook_jobs
        WHERE id = ?
          AND user_id = ?
          AND work_id = ?
        """,
        (job_id, owner_user_id, work_id),
    )
    row = await cursor.fetchone()
    return dict(row) if row else None


def _terminal_or_stale(job: Mapping[str, Any]) -> bool:
    return job.get("stage") == STALE or job.get("status") in {"failed", "done"}


def _job_is_stale(
    job: Mapping[str, Any],
    *,
    source_signature: str,
    character_signature: str,
) -> bool:
    return (
        job.get("stage") == STALE
        or job.get("source_signature") != source_signature
        or (job.get("character_signature") or "") != character_signature
    )


async def _row_to_job_dict(
    db: Any,
    job_id: int,
    *,
    user_id: Optional[int] = None,
) -> dict:
    if user_id is None:
        cursor = await db.execute("SELECT * FROM picturebook_jobs WHERE id = ?", (job_id,))
    else:
        cursor = await db.execute(
            "SELECT * FROM picturebook_jobs WHERE id = ? AND user_id = ?",
            (job_id, user_id),
        )
    row = await cursor.fetchone()
    if not row:
        raise StoryWorkflowNotFound("picturebook job not found")
    return dict(row)


async def mark_work_picturebook_failed(
    db: Any,
    *,
    user_id: int,
    job_id: int,
    message: Optional[str],
    stale: bool = False,
) -> bool:
    job = await _row_to_job_dict(db, job_id, user_id=user_id)
    work_id = job.get("work_id")
    if work_id is None or job["user_id"] != user_id:
        return False
    safe_message = sanitize_generation_error(message, stale=stale)
    job_stage = STALE if stale else "failed"
    now = utc_timestamp()

    await db.execute("BEGIN IMMEDIATE")
    try:
        await db.execute(
            """
            UPDATE picturebook_jobs
            SET status = 'failed',
                stage = ?,
                error = ?,
                updated_at = ?
            WHERE id = ?
              AND user_id = ?
              AND work_id = ?
            """,
            (job_stage, safe_message, now, job_id, user_id, work_id),
        )
        await db.execute(
            """
            UPDATE story_works
            SET status = ?,
                stage = ?,
                generation_error = ?,
                stage_updated_at = ?,
                updated_at = ?
            WHERE id = ?
              AND owner_user_id = ?
              AND status = ?
              AND active_picturebook_job_id = ?
            """,
            (
                DRAFT,
                RENDER_FAILED,
                safe_message,
                now,
                now,
                work_id,
                user_id,
                DRAFT,
                job_id,
            ),
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    return True


async def start_work_picturebook_generation(
    db: Any,
    *,
    owner_user_id: int,
    work_id: int,
    replace: bool = False,
) -> dict:
    work = await _require_owned_work(db, owner_user_id, work_id)
    if work.get("kind") not in {DAILY, TIME_STORY}:
        raise StoryWorkflowConflict("story work cannot start rendering")
    if work["status"] != DRAFT:
        raise StoryWorkflowConflict("story work cannot start rendering")
    if work["stage"] not in EDITABLE_STAGES:
        raise StoryWorkflowConflict("story work cannot start rendering")

    character_signature = await _current_character_signature(db, owner_user_id)
    (
        source_text,
        source_signature,
        _source_diary_ids,
        allow_imaginative,
    ) = await _work_picturebook_source(
        db,
        owner_user_id=owner_user_id,
        work=work,
        character_signature=character_signature,
    )
    active_job = None
    if work.get("active_picturebook_job_id") is not None:
        active_job = await _load_work_picturebook_job(
            db,
            owner_user_id=owner_user_id,
            work_id=work_id,
            job_id=work["active_picturebook_job_id"],
        )
        if active_job is None:
            raise StoryWorkflowConflict("active picturebook job is missing")
        if _job_is_stale(
            active_job,
            source_signature=source_signature,
            character_signature=character_signature,
        ):
            await mark_work_picturebook_failed(
                db,
                user_id=owner_user_id,
                job_id=active_job["id"],
                message=STALE_GENERATION_ERROR,
                stale=True,
            )
            active_job = await _load_work_picturebook_job(
                db,
                owner_user_id=owner_user_id,
                work_id=work_id,
                job_id=work["active_picturebook_job_id"],
            )

    if replace:
        if active_job is None or not _terminal_or_stale(active_job):
            raise StoryWorkflowConflict("replace requires a terminal attempt")
    elif (
        active_job is None
        and work["stage"] == RENDER_FAILED
    ):
        # 指针被迁移清空的失败作品:只在最近一次失败尝试仍与当前
        # 来源/角色签名一致时原样重绑,保留已完成的页;否则走新建。
        cursor = await db.execute(
            """
            SELECT *
            FROM picturebook_jobs
            WHERE user_id = ?
              AND work_id = ?
              AND status = 'failed'
            ORDER BY updated_at DESC, id DESC
            LIMIT 1
            """,
            (owner_user_id, work_id),
        )
        latest_failed_row = await cursor.fetchone()
        if latest_failed_row is not None:
            latest_failed = dict(latest_failed_row)
            if not _job_is_stale(
                latest_failed,
                source_signature=source_signature,
                character_signature=character_signature,
            ):
                now = utc_timestamp()
                await db.execute("BEGIN IMMEDIATE")
                try:
                    # 重绑也要先占分区槽位,自身任务除外。
                    await require_available_slot(
                        db,
                        user_id=owner_user_id,
                        category=CATEGORY_PICTUREBOOK,
                        current_job_id=latest_failed["id"],
                    )
                    await db.execute(
                        """
                        UPDATE picturebook_jobs
                        SET status = 'running',
                            error = NULL,
                            updated_at = ?
                        WHERE id = ?
                          AND user_id = ?
                          AND work_id = ?
                          AND status = 'failed'
                        """,
                        (now, latest_failed["id"], owner_user_id, work_id),
                    )
                    update = await db.execute(
                        """
                        UPDATE story_works
                        SET stage = ?,
                            active_picturebook_job_id = ?,
                            generation_error = NULL,
                            stage_updated_at = ?,
                            updated_at = ?
                        WHERE id = ?
                          AND owner_user_id = ?
                          AND kind = ?
                          AND status = ?
                          AND stage = ?
                          AND active_picturebook_job_id IS NULL
                        """,
                        (
                            RENDERING,
                            latest_failed["id"],
                            now,
                            now,
                            work_id,
                            owner_user_id,
                            work["kind"],
                            DRAFT,
                            RENDER_FAILED,
                        ),
                    )
                    if update.rowcount == 0:
                        raise StoryWorkflowConflict("story work changed state")
                    await db.commit()
                except Exception:
                    await db.rollback()
                    raise
                return await _row_to_job_dict(
                    db, latest_failed["id"], user_id=owner_user_id,
                )
    elif active_job is not None:
        if active_job.get("stage") == STALE:
            raise StoryWorkflowConflict("stale picturebook attempt must be replaced")
        now = utc_timestamp()
        await db.execute("BEGIN IMMEDIATE")
        try:
            # 恢复已有尝试也要先占分区槽位,自身任务除外。
            await require_available_slot(
                db,
                user_id=owner_user_id,
                category=CATEGORY_PICTUREBOOK,
                current_job_id=active_job["id"],
            )
            await db.execute(
                """
                UPDATE picturebook_jobs
                SET status = 'running',
                    error = NULL,
                    updated_at = ?
                WHERE id = ?
                  AND user_id = ?
                  AND work_id = ?
                """,
                (now, active_job["id"], owner_user_id, work_id),
            )
            cursor = await db.execute(
                """
                UPDATE story_works
                SET stage = ?,
                    generation_error = NULL,
                    stage_updated_at = ?,
                    updated_at = ?
                WHERE id = ?
                  AND owner_user_id = ?
                  AND kind = ?
                  AND status = ?
                  AND stage IN (?, ?)
                  AND active_picturebook_job_id = ?
                """,
                (
                    RENDERING,
                    now,
                    now,
                    work_id,
                    owner_user_id,
                    work["kind"],
                    DRAFT,
                    NARRATIVE_CONFIRMED,
                    RENDER_FAILED,
                    active_job["id"],
                ),
            )
            if cursor.rowcount == 0:
                raise StoryWorkflowConflict("story work changed state")
            await db.commit()
        except Exception:
            await db.rollback()
            raise
        return await _row_to_job_dict(db, active_job["id"], user_id=owner_user_id)

    now = utc_timestamp()
    style = normalize_style(work["style"])
    await db.execute("BEGIN IMMEDIATE")
    try:
        # 新尝试 insert 前在同一事务里占住分区槽位。
        await require_available_slot(
            db,
            user_id=owner_user_id,
            category=CATEGORY_PICTUREBOOK,
        )
        # 只有真正新建任务才扣体验次数;上方重绑既有失败任务的分支不扣。
        await consume_quota(db, user_id=owner_user_id, category=CATEGORY_PICTUREBOOK)
        cursor = await db.execute(
            """
            INSERT INTO picturebook_jobs (
                user_id, diary_id, work_id, source_text, source_signature,
                allow_imaginative, style, status, stage, error,
                character_signature, total_pages, created_at, updated_at
            ) VALUES (?, NULL, ?, ?, ?, ?, ?, 'running', 'queued', NULL, ?, ?, ?, ?)
            """,
            (
                owner_user_id,
                work_id,
                source_text,
                source_signature,
                int(allow_imaginative),
                style,
                character_signature,
                TOTAL_IMAGES,
                now,
                now,
            ),
        )
        job_id = cursor.lastrowid
        update = await db.execute(
            """
            UPDATE story_works
            SET stage = ?,
                active_picturebook_job_id = ?,
                generation_error = NULL,
                stage_updated_at = ?,
                updated_at = ?
            WHERE id = ?
              AND owner_user_id = ?
              AND kind = ?
              AND status = ?
              AND stage IN (?, ?)
            """,
            (
                RENDERING,
                job_id,
                now,
                now,
                work_id,
                owner_user_id,
                work["kind"],
                DRAFT,
                NARRATIVE_CONFIRMED,
                RENDER_FAILED,
            ),
        )
        if update.rowcount == 0:
            raise StoryWorkflowConflict("story work changed state")
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    return await _row_to_job_dict(db, job_id, user_id=owner_user_id)


async def promote_completed_work_picturebook(
    db: Any,
    *,
    user_id: int,
    job_id: int,
) -> bool:
    job = await _row_to_job_dict(db, job_id, user_id=user_id)
    work_id = job.get("work_id")
    if work_id is None or job["user_id"] != user_id:
        return False
    work = await _require_owned_work(db, user_id, work_id)

    cursor = await db.execute(
        """
        SELECT page_index, asset_id, image_url, caption
        FROM picturebook_pages
        WHERE job_id = ? AND status = 'ready'
        ORDER BY page_index ASC
        """,
        (job_id,),
    )
    pages = [dict(row) for row in await cursor.fetchall()]
    if [page["page_index"] for page in pages] != list(range(TOTAL_IMAGES)):
        return False

    character_signature = await _current_character_signature(db, user_id)
    source_text = (job.get("source_text") or "").strip()
    if not source_text:
        await mark_work_picturebook_failed(
            db,
            user_id=user_id,
            job_id=job_id,
            message=STALE_GENERATION_ERROR,
            stale=True,
        )
        return False
    source_diary_rows = await _source_diary_rows(
        db,
        owner_user_id=user_id,
        work=work,
    )
    source_diary_ids = [row["id"] for row in source_diary_rows]
    allow_imaginative = bool(
        work.get("kind") == DAILY
        and source_diary_rows
        and source_diary_rows[0].get("emotion_mode") == "imagery"
    )
    signature_work = {
        **dict(work),
        "source_diary_ids": source_diary_ids,
        "character_signature": character_signature,
    }
    source_signature = picturebook_source_signature(
        signature_work,
        source_text,
        allow_imaginative,
    )
    if _job_is_stale(
        job,
        source_signature=source_signature,
        character_signature=character_signature,
    ):
        await mark_work_picturebook_failed(
            db,
            user_id=user_id,
            job_id=job_id,
            message=STALE_GENERATION_ERROR,
            stale=True,
        )
        return False

    cover_asset_id = pages[0]["asset_id"]
    now = utc_timestamp()
    await db.execute("BEGIN IMMEDIATE")
    try:
        await db.execute("DELETE FROM work_assets WHERE work_id = ?", (work_id,))
        for page in pages:
            await db.execute(
                """
                INSERT INTO work_assets (
                    work_id, ordinal, asset_type, url, asset_id, text, created_at
                ) VALUES (?, ?, 'image', ?, ?, ?, ?)
                """,
                (
                    work_id,
                    page["page_index"],
                    page["image_url"],
                    page["asset_id"],
                    page["caption"] or "",
                    now,
                ),
            )
        await db.execute(
            """
            UPDATE picturebook_jobs
            SET status = 'done',
                stage = 'done',
                error = NULL,
                updated_at = ?
            WHERE id = ?
              AND user_id = ?
              AND work_id = ?
            """,
            (now, job_id, user_id, work_id),
        )
        update = await db.execute(
            """
            UPDATE story_works
            SET status = ?,
                stage = ?,
                active_picturebook_job_id = NULL,
                picturebook_job_id = ?,
                cover_asset_id = ?,
                generation_error = NULL,
                stage_updated_at = ?,
                updated_at = ?
            WHERE id = ?
              AND owner_user_id = ?
              AND status = ?
              AND active_picturebook_job_id = ?
            """,
            (
                READY,
                READY,
                job_id,
                cover_asset_id,
                now,
                now,
                work_id,
                user_id,
                DRAFT,
                job_id,
            ),
        )
        if update.rowcount == 0:
            await db.rollback()
            return False
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    return True


async def _save_safe_generation_error(
    db: Any,
    *,
    owner_user_id: int,
    work_id: int,
    source_snapshot_hash: str,
    message: Optional[str],
) -> None:
    now = utc_timestamp()
    await db.execute("BEGIN IMMEDIATE")
    try:
        await db.execute(
            """
            UPDATE story_works
            SET generation_error = ?, updated_at = ?
            WHERE id = ?
              AND owner_user_id = ?
              AND kind = ?
              AND status = ?
              AND source_snapshot_hash = ?
            """,
            (
                sanitize_generation_error(message),
                now,
                work_id,
                owner_user_id,
                TIME_STORY,
                DRAFT,
                source_snapshot_hash,
            ),
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise


def _time_story_provider_snapshot(work: Mapping[str, Any]) -> list[dict]:
    snapshot = _load_json(work.get("source_snapshot_json"), {"diaries": []})
    diaries = _snapshot_diaries(snapshot)
    if not diaries:
        raise StoryWorkflowConflict("time story sources are required")
    return diaries


async def generate_time_story_storylines(
    db: Any,
    *,
    owner_user_id: int,
    work_id: int,
    replace: bool = False,
) -> dict:
    work = await _require_owned_work(db, owner_user_id, work_id)
    _ensure_time_story_work(work)
    if work["status"] != DRAFT or work["stage"] == RENDERING:
        raise StoryWorkflowConflict("story work changed state")
    existing = _load_json(work.get("storyline_candidates_json"), None)
    if existing is not None and not replace:
        return await get_story_work_resume(
            db,
            owner_user_id=owner_user_id,
            work_id=work_id,
        )

    snapshots = _time_story_provider_snapshot(work)
    source_hash = work["source_snapshot_hash"]
    try:
        response = await time_story_agent.generate_storyline_candidates(snapshots)
    except (time_story_agent.TimeStoryAIContractError, GenerationServiceError):
        # A malformed/temporarily unavailable model response must not strand the
        # user's draft. Fall back to three strictly grounded local directions.
        response = time_story_agent.build_grounded_storyline_candidates(snapshots)
    except Exception as exc:  # noqa: BLE001 - raw provider details must not leak.
        await _save_safe_generation_error(
            db,
            owner_user_id=owner_user_id,
            work_id=work_id,
            source_snapshot_hash=source_hash,
            message=str(exc),
        )
        return await get_story_work_resume(
            db,
            owner_user_id=owner_user_id,
            work_id=work_id,
        )

    candidates_json = canonical_json(
        [candidate.to_dict() for candidate in response.items]
    )
    now = utc_timestamp()
    expected_stage = work["stage"]
    expected_candidates_json = _db_text(work.get("storyline_candidates_json"))
    expected_selected_json = _db_text(work.get("selected_storyline_json"))
    expected_narrative_text = _db_text(work.get("narrative_text"))
    await db.execute("BEGIN IMMEDIATE")
    try:
        cursor = await db.execute(
            """
            UPDATE story_works
            SET storyline_candidates_json = ?,
                selected_storyline_json = NULL,
                narrative_text = NULL,
                generation_error = NULL,
                stage = ?,
                active_picturebook_job_id = NULL,
                picturebook_job_id = NULL,
                cover_asset_id = NULL,
                stage_updated_at = ?,
                updated_at = ?
            WHERE id = ?
              AND owner_user_id = ?
              AND kind = ?
              AND status = ?
              AND stage = ?
              AND source_snapshot_hash = ?
              AND COALESCE(storyline_candidates_json, '') = ?
              AND COALESCE(selected_storyline_json, '') = ?
              AND COALESCE(narrative_text, '') = ?
            """,
            (
                candidates_json,
                STORYLINES_READY,
                now,
                now,
                work_id,
                owner_user_id,
                TIME_STORY,
                DRAFT,
                expected_stage,
                source_hash,
                expected_candidates_json,
                expected_selected_json,
                expected_narrative_text,
            ),
        )
        if cursor.rowcount == 0:
            raise StoryWorkflowConflict("story work changed state")
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    return await get_story_work_resume(db, owner_user_id=owner_user_id, work_id=work_id)


async def select_time_story_storyline(
    db: Any,
    *,
    owner_user_id: int,
    work_id: int,
    selected_storyline_id: str,
) -> dict:
    work = await _require_owned_work(db, owner_user_id, work_id)
    _ensure_time_story_work(work)
    if work["status"] != DRAFT or work["stage"] != STORYLINES_READY:
        raise StoryWorkflowConflict("story work changed state")
    candidates = _candidate_dicts(_load_json(work.get("storyline_candidates_json"), None))
    selected_id = selected_storyline_id.strip()
    selected = next((item for item in candidates if item["id"] == selected_id), None)
    if selected is None:
        raise StoryWorkflowValidationError("selected storyline is invalid")
    current = _load_json(work.get("selected_storyline_json"), None)
    if isinstance(current, Mapping) and str(current.get("id") or "") == selected_id:
        return await get_story_work_resume(
            db,
            owner_user_id=owner_user_id,
            work_id=work_id,
        )

    now = utc_timestamp()
    await db.execute("BEGIN IMMEDIATE")
    try:
        cursor = await db.execute(
            """
            UPDATE story_works
            SET selected_storyline_json = ?,
                narrative_text = NULL,
                active_picturebook_job_id = NULL,
                picturebook_job_id = NULL,
                cover_asset_id = NULL,
                generation_error = NULL,
                stage = ?,
                stage_updated_at = ?,
                updated_at = ?
            WHERE id = ?
              AND owner_user_id = ?
              AND kind = ?
              AND status = ?
              AND stage = ?
            """,
            (
                canonical_json(selected),
                STORYLINES_READY,
                now,
                now,
                work_id,
                owner_user_id,
                TIME_STORY,
                DRAFT,
                STORYLINES_READY,
            ),
        )
        if cursor.rowcount == 0:
            raise StoryWorkflowConflict("story work changed state")
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    return await get_story_work_resume(db, owner_user_id=owner_user_id, work_id=work_id)


async def generate_time_story_narrative(
    db: Any,
    *,
    owner_user_id: int,
    work_id: int,
    replace: bool = False,
) -> dict:
    work = await _require_owned_work(db, owner_user_id, work_id)
    _ensure_time_story_work(work)
    if work["status"] != DRAFT or work["stage"] != STORYLINES_READY:
        raise StoryWorkflowConflict("story work changed state")
    if (work.get("narrative_text") or "").strip() and not replace:
        return await get_story_work_resume(
            db,
            owner_user_id=owner_user_id,
            work_id=work_id,
        )
    selected_raw = _load_json(work.get("selected_storyline_json"), None)
    if selected_raw is None:
        raise StoryWorkflowConflict("selected storyline is required")
    selected = _candidate_from_dict(selected_raw)
    snapshots = _time_story_provider_snapshot(work)
    source_hash = work["source_snapshot_hash"]
    expected_stage = work["stage"]
    expected_selected_json = _db_text(work.get("selected_storyline_json"))
    expected_narrative_text = _db_text(work.get("narrative_text"))

    try:
        narrative = await time_story_agent.generate_time_story_narrative(
            snapshots,
            selected,
        )
    except Exception as exc:  # noqa: BLE001 - raw provider details must not leak.
        await _save_safe_generation_error(
            db,
            owner_user_id=owner_user_id,
            work_id=work_id,
            source_snapshot_hash=source_hash,
            message=str(exc),
        )
        return await get_story_work_resume(
            db,
            owner_user_id=owner_user_id,
            work_id=work_id,
        )
    cleaned = narrative.strip()
    if not cleaned:
        raise StoryWorkflowValidationError("narrative text is required")

    now = utc_timestamp()
    await db.execute("BEGIN IMMEDIATE")
    try:
        cursor = await db.execute(
            """
            UPDATE story_works
            SET narrative_text = ?,
                generation_error = NULL,
                stage = ?,
                active_picturebook_job_id = NULL,
                picturebook_job_id = NULL,
                cover_asset_id = NULL,
                stage_updated_at = ?,
                updated_at = ?
            WHERE id = ?
              AND owner_user_id = ?
              AND kind = ?
              AND status = ?
              AND stage = ?
              AND source_snapshot_hash = ?
              AND COALESCE(selected_storyline_json, '') = ?
              AND COALESCE(narrative_text, '') = ?
            """,
            (
                cleaned,
                NARRATIVE_EDITING,
                now,
                now,
                work_id,
                owner_user_id,
                TIME_STORY,
                DRAFT,
                expected_stage,
                source_hash,
                expected_selected_json,
                expected_narrative_text,
            ),
        )
        if cursor.rowcount == 0:
            raise StoryWorkflowConflict("story work changed state")
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    return await get_story_work_resume(db, owner_user_id=owner_user_id, work_id=work_id)


async def update_time_story_narrative(
    db: Any,
    *,
    owner_user_id: int,
    work_id: int,
    narrative_text: str,
) -> dict:
    work = await _require_owned_work(db, owner_user_id, work_id)
    _ensure_time_story_work(work)
    if work["status"] != DRAFT or work["stage"] not in {
        NARRATIVE_EDITING,
        NARRATIVE_CONFIRMED,
        RENDER_FAILED,
    }:
        raise StoryWorkflowConflict("story work changed state")
    cleaned = narrative_text.strip()
    if not cleaned:
        raise StoryWorkflowValidationError("narrative text is required")
    next_stage = NARRATIVE_EDITING
    now = utc_timestamp()

    await db.execute("BEGIN IMMEDIATE")
    try:
        cursor = await db.execute(
            """
            UPDATE story_works
            SET narrative_text = ?,
                stage = ?,
                active_picturebook_job_id = NULL,
                picturebook_job_id = NULL,
                cover_asset_id = NULL,
                generation_error = NULL,
                stage_updated_at = ?,
                updated_at = ?
            WHERE id = ?
              AND owner_user_id = ?
              AND kind = ?
              AND status = ?
              AND stage IN (?, ?, ?)
            """,
            (
                cleaned,
                next_stage,
                now,
                now,
                work_id,
                owner_user_id,
                TIME_STORY,
                DRAFT,
                NARRATIVE_EDITING,
                NARRATIVE_CONFIRMED,
                RENDER_FAILED,
            ),
        )
        if cursor.rowcount == 0:
            raise StoryWorkflowConflict("story work changed state")
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    return await get_story_work_resume(db, owner_user_id=owner_user_id, work_id=work_id)


async def confirm_time_story_narrative(
    db: Any,
    *,
    owner_user_id: int,
    work_id: int,
) -> dict:
    work = await _require_owned_work(db, owner_user_id, work_id)
    _ensure_time_story_work(work)
    if work["status"] != DRAFT or work["stage"] != NARRATIVE_EDITING:
        raise StoryWorkflowConflict("story work changed state")
    cleaned = (work.get("narrative_text") or "").strip()
    if not cleaned:
        raise StoryWorkflowValidationError("narrative text is required")
    now = utc_timestamp()

    await db.execute("BEGIN IMMEDIATE")
    try:
        cursor = await db.execute(
            """
            UPDATE story_works
            SET narrative_text = ?,
                stage = ?,
                generation_error = NULL,
                stage_updated_at = ?,
                updated_at = ?
            WHERE id = ?
              AND owner_user_id = ?
              AND kind = ?
              AND status = ?
              AND stage = ?
            """,
            (
                cleaned,
                NARRATIVE_CONFIRMED,
                now,
                now,
                work_id,
                owner_user_id,
                TIME_STORY,
                DRAFT,
                NARRATIVE_EDITING,
            ),
        )
        if cursor.rowcount == 0:
            raise StoryWorkflowConflict("story work changed state")
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    return await get_story_work_resume(db, owner_user_id=owner_user_id, work_id=work_id)


def _safe_generation_error(value: Optional[str]) -> Optional[str]:
    return SAFE_GENERATION_ERROR if value else None


def _load_json(value: Optional[str], fallback: Any) -> Any:
    if value is None:
        return fallback
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def _source_diaries_from_snapshot(snapshot: Mapping[str, Any]) -> list[dict]:
    diaries = snapshot.get("diaries") if isinstance(snapshot, Mapping) else []
    if not isinstance(diaries, list):
        return []
    result = []
    for diary in diaries:
        if not isinstance(diary, Mapping):
            continue
        result.append(
            {
                "id": diary.get("id"),
                "date": diary.get("date"),
                "status": diary.get("status"),
                "text": diary.get("body") or "",
            }
        )
    return result


async def _job_summary(
    db: Any,
    *,
    owner_user_id: int,
    work_id: int,
    job_id: Optional[int],
) -> Optional[dict]:
    if job_id is None:
        return None
    cursor = await db.execute(
        """
        SELECT id, status, stage, total_pages
        FROM picturebook_jobs
        WHERE id = ?
          AND user_id = ?
          AND work_id = ?
        """,
        (job_id, owner_user_id, work_id),
    )
    row = await cursor.fetchone()
    if not row:
        return None
    cursor = await db.execute(
        """
        SELECT COUNT(*) AS ready_pages
        FROM picturebook_pages
        WHERE job_id = ? AND status = 'ready'
        """,
        (job_id,),
    )
    ready_row = await cursor.fetchone()
    return {
        "id": row["id"],
        "status": row["status"],
        "stage": row["stage"],
        "total_pages": row["total_pages"],
        "ready_pages": ready_row["ready_pages"] if ready_row else 0,
    }


async def _asset_is_owned(db: Any, owner_user_id: int, asset_id: str) -> bool:
    cursor = await db.execute(
        "SELECT 1 FROM media_assets WHERE id = ? AND owner_user_id = ?",
        (asset_id, owner_user_id),
    )
    return await cursor.fetchone() is not None


async def _safe_asset_url(
    db: Any,
    *,
    owner_user_id: int,
    asset_id: Optional[str],
    url: Optional[str],
) -> Optional[str]:
    if asset_id:
        if await _asset_is_owned(db, owner_user_id, asset_id):
            return canonical_media_url(asset_id)
        return None
    url_asset_id = parse_canonical_media_url(url)
    if url_asset_id and await _asset_is_owned(db, owner_user_id, url_asset_id):
        return canonical_media_url(url_asset_id)
    return None


async def _formal_pages(db: Any, *, owner_user_id: int, work_id: int) -> list[dict]:
    cursor = await db.execute(
        """
        SELECT ordinal, asset_id, url, text
        FROM work_assets
        WHERE work_id = ? AND asset_type = 'image'
        ORDER BY ordinal ASC
        """,
        (work_id,),
    )
    pages = []
    for row in await cursor.fetchall():
        image_url = await _safe_asset_url(
            db,
            owner_user_id=owner_user_id,
            asset_id=row["asset_id"],
            url=row["url"],
        )
        if image_url is None:
            continue
        pages.append(
            {
                "page_index": row["ordinal"],
                "image_url": image_url,
                "caption": row["text"] or "",
            }
        )
    return pages


async def get_story_work_resume(
    db: Any,
    *,
    owner_user_id: int,
    work_id: int,
) -> dict:
    work = await _require_owned_work(db, owner_user_id, work_id)
    snapshot = _load_json(work.get("source_snapshot_json"), {"diaries": []})
    selected_segments = _load_json(work.get("selected_segments_json"), [])
    storyline_candidates = _load_json(work.get("storyline_candidates_json"), None)
    selected_storyline = _load_json(work.get("selected_storyline_json"), None)
    show_formal_pages = (
        work["status"] in {READY, PUBLISHED}
        and work["stage"] == READY
        and work["picturebook_job_id"] is not None
    )

    return {
        "id": work["id"],
        "owner_user_id": work["owner_user_id"],
        "kind": work["kind"],
        "status": work["status"],
        "stage": work["stage"],
        "title": work["title"],
        "style": work["style"],
        "selected_segments": selected_segments,
        "source_diary_ids": [
            diary["id"]
            for diary in _source_diaries_from_snapshot(snapshot)
            if diary.get("id") is not None
        ],
        "source_diaries": _source_diaries_from_snapshot(snapshot),
        "source_snapshot": snapshot,
        "source_snapshot_hash": work["source_snapshot_hash"],
        "storyline_candidates": storyline_candidates,
        "selected_storyline": selected_storyline,
        "narrative_text": work["narrative_text"],
        "source_start_date": work["source_start_date"],
        "source_end_date": work["source_end_date"],
        "display_start_date": work["display_start_date"],
        "display_end_date": work["display_end_date"],
        "generation_error": _safe_generation_error(work["generation_error"]),
        "active_picturebook_job": await _job_summary(
            db,
            owner_user_id=owner_user_id,
            work_id=work_id,
            job_id=work["active_picturebook_job_id"],
        ),
        "picturebook_job": await _job_summary(
            db,
            owner_user_id=owner_user_id,
            work_id=work_id,
            job_id=work["picturebook_job_id"],
        ),
        "pages": await _formal_pages(
            db,
            owner_user_id=owner_user_id,
            work_id=work_id,
        ) if show_formal_pages else [],
        "created_at": work["created_at"],
        "updated_at": work["updated_at"],
    }


async def list_draft_story_works(db: Any, *, owner_user_id: int) -> list[dict]:
    cursor = await db.execute(
        """
        SELECT id
        FROM story_works
        WHERE owner_user_id = ? AND status = ?
        ORDER BY created_at DESC, id DESC
        """,
        (owner_user_id, DRAFT),
    )
    return [
        await get_story_work_resume(db, owner_user_id=owner_user_id, work_id=row["id"])
        for row in await cursor.fetchall()
    ]
