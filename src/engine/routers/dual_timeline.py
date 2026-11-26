import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from agents.dual_timeline_agent import plan_comic, summarize
from agents.image_agent import generate_image
from auth.dependencies import CurrentUser, get_current_user, require_same_origin
from database import get_db
from services.room_access import ActivePair, get_active_pair
from services.media_store import (
    MediaStoreError,
    staged_generated_media,
    store_generated_asset,
)
from services.generation_errors import (
    GenerationServiceError,
    raise_generation_http_error,
)


router = APIRouter()


def _fragment_time(created_at: Optional[str]) -> str:
    """Extract HH:MM from a timestamp like '2026-05-22 19:34:21'."""
    if not created_at:
        return "23:59"
    try:
        if "T" in created_at:
            return created_at.split("T", 1)[1][:5]
        return created_at.split(" ", 1)[1][:5]
    except Exception:
        return "23:59"


async def _load_user_events(db, date: str, user_id: int) -> list[dict]:
    """Load only the authenticated user's private schedules and fragments."""
    events: list[dict] = []
    cursor = await db.execute(
        "SELECT id, time, title, completed, feeling FROM schedules "
        "WHERE date = ? AND user_id = ? ORDER BY time, created_at",
        (date, user_id),
    )
    for row in await cursor.fetchall():
        item = dict(row)
        events.append(
            {
                "type": "schedule",
                "id": item["id"],
                "time": item.get("time") or "00:00",
                "title": item["title"],
                "completed": bool(item["completed"]),
                "feeling": item.get("feeling"),
            }
        )

    cursor = await db.execute(
        "SELECT id, content, mood_tag, photo_description, created_at "
        "FROM fragments WHERE date = ? AND user_id = ? ORDER BY created_at",
        (date, user_id),
    )
    for row in await cursor.fetchall():
        item = dict(row)
        events.append(
            {
                "type": "fragment",
                "id": item["id"],
                "time": _fragment_time(item.get("created_at")),
                "content": item.get("content"),
                "mood_tag": item.get("mood_tag"),
                "photo_description": item.get("photo_description"),
            }
        )

    events.sort(key=lambda event: event["time"] or "23:59")
    return events


def _snapshot_content(snapshot: dict) -> str:
    for key in ("body", "text", "caption", "content", "title"):
        value = snapshot.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return "已分享一条记录"


async def _load_partner_snapshot_events(
    db, date: str, pair: ActivePair
) -> list[dict]:
    """Load immutable published snapshots, never the partner's private tables."""
    # 遵循 SEC-AUTH-002 规范: partner data is limited to active-room snapshots.
    cursor = await db.execute(
        "SELECT id, source_type, snapshot_json, published_at FROM room_posts "
        "WHERE room_id = ? AND author_user_id = ? AND status = 'published' "
        "ORDER BY published_at, id",
        (pair.room_id, pair.partner_user_id),
    )
    events: list[dict] = []
    for row in await cursor.fetchall():
        try:
            snapshot = json.loads(row["snapshot_json"])
        except (TypeError, ValueError):
            continue
        if not isinstance(snapshot, dict) or snapshot.get("date") != date:
            continue
        snapshot_time = snapshot.get("time")
        events.append(
            {
                "type": "room_post",
                "id": row["id"],
                "time": snapshot_time
                if isinstance(snapshot_time, str) and snapshot_time
                else _fragment_time(row["published_at"]),
                "source_type": row["source_type"],
                "content": _snapshot_content(snapshot),
                "snapshot": snapshot,
            }
        )
    events.sort(key=lambda event: event["time"] or "23:59")
    return events


def _authorized_selection(requested: list, allowed: list[dict]) -> list[dict]:
    allowed_by_key = {
        (str(event.get("type")), str(event.get("id"))): event for event in allowed
    }
    selected: list[dict] = []
    for item in requested:
        if not isinstance(item, dict):
            raise HTTPException(status_code=404, detail="timeline event not found")
        event = allowed_by_key.get((str(item.get("type")), str(item.get("id"))))
        if event is None:
            raise HTTPException(status_code=404, detail="timeline event not found")
        selected.append(event)
    return selected


@router.get("")
async def get_dual_timeline(
    date: str,
    current_user: CurrentUser = Depends(get_current_user),
):
    db = await get_db()
    try:
        # 遵循 BE-AUTH-001 规范: side A is always the authenticated user.
        events_a = await _load_user_events(db, date, current_user.id)
        pair = await get_active_pair(db, current_user.id)
        events_b = (
            await _load_partner_snapshot_events(db, date, pair) if pair else []
        )
    finally:
        await db.close()

    partner_name = pair.partner_nickname if pair else "家人"
    summary = await summarize(
        date,
        current_user.nickname,
        events_a,
        partner_name,
        events_b,
    )
    return {
        "date": date,
        "user_a": {"id": current_user.id, "nickname": current_user.nickname},
        "user_b": (
            {
                "id": pair.partner_user_id,
                "nickname": pair.partner_nickname,
            }
            if pair
            else None
        ),
        "summary": summary,
        "events_a": events_a,
        "events_b": events_b,
    }


class GenerateComicRequest(BaseModel):
    date: str
    selected_a: list = Field(default_factory=list)
    selected_b: list = Field(default_factory=list)
    style: str = "watercolor"
    custom_style_prompt: Optional[str] = None


@router.post("/comic/generate")
async def generate_comic(
    req: GenerateComicRequest,
    _: None = Depends(require_same_origin),
    current_user: CurrentUser = Depends(get_current_user),
):
    total = len(req.selected_a) + len(req.selected_b)
    if total == 0:
        raise HTTPException(status_code=400, detail="至少选 1 个时刻才能生成漫画")
    if total > 6:
        raise HTTPException(status_code=400, detail="最多选 6 个时刻")

    db = await get_db()
    try:
        pair = await get_active_pair(db, current_user.id)
        if not pair:
            raise HTTPException(status_code=400, detail="active partner required")
        own_events = await _load_user_events(db, req.date, current_user.id)
        partner_events = await _load_partner_snapshot_events(db, req.date, pair)
    finally:
        await db.close()

    # COSEC: replace client event bodies with server-authorized records/snapshots.
    selected_a = _authorized_selection(req.selected_a, own_events)
    selected_b = _authorized_selection(req.selected_b, partner_events)

    try:
        image_prompt, caption = await plan_comic(
            date=req.date,
            user_a_name=current_user.nickname,
            selected_a=selected_a,
            user_b_name=pair.partner_nickname,
            selected_b=selected_b,
            style=req.style,
            custom_style_prompt=req.custom_style_prompt,
        )
    except GenerationServiceError as exc:
        raise_generation_http_error(exc, service="AI")
    try:
        url = await generate_image(
            diary_text=image_prompt,
            style=req.style,
            custom_style_prompt=req.custom_style_prompt,
        )
    except GenerationServiceError as exc:
        raise_generation_http_error(exc, service="image")
    selected_json = json.dumps(
        {"user_a_events": selected_a, "user_b_events": selected_b},
        ensure_ascii=False,
    )

    db = await get_db()
    try:
        async with staged_generated_media(db) as media_stage:
            try:
                asset = await store_generated_asset(
                    db,
                    current_user.id,
                    url,
                    stage=media_stage,
                )
            except MediaStoreError as exc:
                raise HTTPException(
                    status_code=400, detail="generated image is invalid"
                ) from exc
            cursor = await db.execute(
                "INSERT INTO dual_timeline_comics "
                "(date, user_a_id, user_b_id, selected_events_json, style, "
                "style_prompt, prompt, url, caption, asset_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    req.date,
                    current_user.id,
                    pair.partner_user_id,
                    selected_json,
                    req.style,
                    req.custom_style_prompt,
                    image_prompt,
                    asset.url,
                    caption,
                    asset.id,
                ),
            )
            new_id = cursor.lastrowid
        cursor = await db.execute(
            "SELECT * FROM dual_timeline_comics "
            "WHERE id = ? AND user_a_id = ? AND user_b_id = ?",
            (new_id, current_user.id, pair.partner_user_id),
        )
        row = await cursor.fetchone()
        return dict(row)
    finally:
        await db.close()


@router.get("/comic/list")
async def list_comics(
    limit: int = 30,
    current_user: CurrentUser = Depends(get_current_user),
):
    db = await get_db()
    try:
        pair = await get_active_pair(db, current_user.id)
        if not pair:
            return []
        cursor = await db.execute(
            "SELECT * FROM dual_timeline_comics "
            "WHERE user_a_id = ? AND user_b_id = ? "
            "ORDER BY created_at DESC LIMIT ?",
            (
                current_user.id,
                pair.partner_user_id,
                max(1, min(limit, 100)),
            ),
        )
        return [dict(row) for row in await cursor.fetchall()]
    finally:
        await db.close()


@router.delete("/comic/{comic_id}")
async def delete_comic(
    comic_id: int,
    _: None = Depends(require_same_origin),
    current_user: CurrentUser = Depends(get_current_user),
):
    db = await get_db()
    try:
        pair = await get_active_pair(db, current_user.id)
        if not pair:
            raise HTTPException(status_code=404, detail="comic not found")
        # 遵循 SEC-AUTH-002 规范: current owner and active partner scope delete.
        cursor = await db.execute(
            "DELETE FROM dual_timeline_comics "
            "WHERE id = ? AND user_a_id = ? AND user_b_id = ?",
            (comic_id, current_user.id, pair.partner_user_id),
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="comic not found")
        await db.commit()
        return {"message": "deleted"}
    finally:
        await db.close()
