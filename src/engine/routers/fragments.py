import re
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth.dependencies import get_current_user_id, require_same_origin
from database import get_db
from services.media_store import (
    InvalidMedia,
    MediaNotFound,
    resolve_owned_attachment,
)

router = APIRouter()

RECORD_TIME_PATTERN = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


def _current_record_time() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%H:%M")


def _validate_record_time(value: Optional[str]) -> str:
    if value is None or not RECORD_TIME_PATTERN.fullmatch(value):
        raise HTTPException(status_code=422, detail="record_time must be HH:mm")
    return value


def _validate_nonempty_fragment(
    content: Optional[str],
    photo_asset_id: Optional[str],
    photo_url: Optional[str],
) -> None:
    has_text = bool((content or "").strip())
    has_photo = bool(photo_asset_id or photo_url)
    if not has_text and not has_photo:
        raise HTTPException(
            status_code=422, detail="fragment requires content or photo"
        )


class FragmentCreate(BaseModel):
    date: str
    content: Optional[str] = None
    photo_url: Optional[str] = None
    photo_asset_id: Optional[str] = None
    photo_description: Optional[str] = None
    mood_tag: Optional[str] = None
    record_time: Optional[str] = None


async def _resolve_photo_update(db, user_id: int, payload: dict) -> None:
    asset_is_set = "photo_asset_id" in payload
    url_is_set = "photo_url" in payload
    if not asset_is_set and not url_is_set:
        return
    asset_id = payload.get("photo_asset_id")
    url = payload.get("photo_url")
    if (asset_is_set and asset_id is None) or (url_is_set and url is None):
        if asset_id is not None or url is not None:
            raise HTTPException(status_code=400, detail="conflicting photo fields")
        payload["photo_asset_id"] = None
        payload["photo_url"] = None
        return
    try:
        asset_id, url = await resolve_owned_attachment(
            db,
            user_id,
            asset_id=asset_id,
            url=url,
        )
    except MediaNotFound as exc:
        raise HTTPException(status_code=404, detail="media not found") from exc
    except InvalidMedia as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    payload["photo_asset_id"] = asset_id
    payload["photo_url"] = url


@router.post("")
async def create_fragment(
    data: FragmentCreate,
    _: None = Depends(require_same_origin),
    user_id: int = Depends(get_current_user_id),
):
    from routers.schedules import _upsert_checkin
    db = await get_db()
    try:
        payload = data.model_dump(exclude_unset=True)
        await _resolve_photo_update(db, user_id, payload)
        if "record_time" in data.model_fields_set:
            payload["record_time"] = _validate_record_time(data.record_time)
        else:
            payload["record_time"] = _current_record_time()
        _validate_nonempty_fragment(
            payload.get("content"),
            payload.get("photo_asset_id"),
            payload.get("photo_url"),
        )
        cursor = await db.execute(
            "INSERT INTO fragments "
            "(date, content, photo_url, photo_asset_id, photo_description, "
            "mood_tag, user_id, record_time) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                payload["date"],
                payload.get("content"),
                payload.get("photo_url"),
                payload.get("photo_asset_id"),
                payload.get("photo_description"),
                payload.get("mood_tag"),
                user_id,
                payload["record_time"],
            ),
        )
        new_id = cursor.lastrowid
        await _upsert_checkin(db, data.date, user_id, has_fragment=True)
        await db.commit()
        cursor = await db.execute(
            "SELECT * FROM fragments WHERE id = ? AND user_id = ?",
            (new_id, user_id),
        )
        row = await cursor.fetchone()
        return dict(row)
    finally:
        await db.close()


class FragmentUpdate(BaseModel):
    content: Optional[str] = None
    photo_url: Optional[str] = None
    photo_asset_id: Optional[str] = None
    photo_description: Optional[str] = None
    mood_tag: Optional[str] = None
    record_time: Optional[str] = None


@router.put("/{fragment_id}")
async def update_fragment(
    fragment_id: int,
    data: FragmentUpdate,
    _: None = Depends(require_same_origin),
    user_id: int = Depends(get_current_user_id),
):
    db = await get_db()
    try:
        payload = data.model_dump(exclude_unset=True)
        await _resolve_photo_update(db, user_id, payload)
        if "record_time" in data.model_fields_set:
            payload["record_time"] = _validate_record_time(data.record_time)
        cursor = await db.execute(
            "SELECT * FROM fragments WHERE id = ? AND user_id = ?",
            (fragment_id, user_id),
        )
        current = await cursor.fetchone()
        if not current:
            raise HTTPException(status_code=404, detail="fragment not found")
        if not payload:
            return {"message": "nothing to update"}
        prospective_content = (
            payload["content"] if "content" in payload else current["content"]
        )
        prospective_photo_asset_id = (
            payload["photo_asset_id"]
            if "photo_asset_id" in payload
            else current["photo_asset_id"]
        )
        prospective_photo_url = (
            payload["photo_url"] if "photo_url" in payload else current["photo_url"]
        )
        _validate_nonempty_fragment(
            prospective_content,
            prospective_photo_asset_id,
            prospective_photo_url,
        )
        updates = [f"{k} = ?" for k in payload.keys()]
        values = list(payload.values())
        values.extend([fragment_id, user_id])
        cursor = await db.execute(
            f"UPDATE fragments SET {', '.join(updates)} "
            "WHERE id = ? AND user_id = ?",
            values,
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="fragment not found")
        await db.commit()
        cursor = await db.execute(
            "SELECT * FROM fragments WHERE id = ? AND user_id = ?",
            (fragment_id, user_id),
        )
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="fragment not found")
        return dict(row)
    finally:
        await db.close()


@router.get("")
async def list_fragments(
    date: str, user_id: int = Depends(get_current_user_id)
):
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM fragments WHERE date = ? AND user_id = ? "
            "ORDER BY record_time DESC, created_at DESC, id DESC",
            (date, user_id),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        await db.close()


@router.delete("/{fragment_id}")
async def delete_fragment(
    fragment_id: int,
    _: None = Depends(require_same_origin),
    user_id: int = Depends(get_current_user_id),
):
    db = await get_db()
    try:
        cursor = await db.execute(
            "DELETE FROM fragments WHERE id = ? AND user_id = ?",
            (fragment_id, user_id),
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="fragment not found")
        await db.commit()
        return {"message": "deleted"}
    finally:
        await db.close()
