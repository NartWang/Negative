from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from typing import Optional
from auth.dependencies import get_current_user_id, require_same_origin
from database import get_db
from services.media_store import (
    InvalidMedia,
    MediaNotFound,
    resolve_owned_attachment,
)

router = APIRouter()


class ProfileUpdate(BaseModel):
    nickname: Optional[str] = None
    avatar_url: Optional[str] = None
    avatar_asset_id: Optional[str] = None
    signature: Optional[str] = None

    @field_validator("nickname")
    @classmethod
    def validate_nickname(cls, value: Optional[str]) -> str:
        # Omission keeps the current nickname, but an explicit null/blank value
        # would corrupt room-facing snapshots and is therefore invalid.
        if value is None:
            raise ValueError("nickname is required")
        normalized = value.strip()
        if not normalized:
            raise ValueError("nickname is required")
        if len(normalized) > 100:
            raise ValueError("nickname is too long")
        return normalized


async def _resolve_avatar_update(db, user_id: int, payload: dict) -> None:
    asset_is_set = "avatar_asset_id" in payload
    url_is_set = "avatar_url" in payload
    if not asset_is_set and not url_is_set:
        return
    asset_id = payload.get("avatar_asset_id")
    url = payload.get("avatar_url")
    if (asset_is_set and asset_id is None) or (url_is_set and url is None):
        if asset_id is not None or url is not None:
            raise HTTPException(status_code=400, detail="conflicting avatar fields")
        payload["avatar_asset_id"] = None
        payload["avatar_url"] = None
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
    payload["avatar_asset_id"] = asset_id
    payload["avatar_url"] = url


@router.get("")
async def get_profile(user_id: int = Depends(get_current_user_id)):
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM profile WHERE id = ?", (user_id,))
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="profile not found")
        return dict(row)
    finally:
        await db.close()


@router.put("")
async def update_profile(
    data: ProfileUpdate,
    _: None = Depends(require_same_origin),
    user_id: int = Depends(get_current_user_id),
):
    db = await get_db()
    try:
        payload = data.model_dump(exclude_unset=True)
        await _resolve_avatar_update(db, user_id, payload)
        if not payload:
            cursor = await db.execute("SELECT * FROM profile WHERE id = ?", (user_id,))
            row = await cursor.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="profile not found")
            return dict(row)
        updates = [f"{k} = ?" for k in payload.keys()]
        values = list(payload.values())
        values.append(user_id)
        cursor = await db.execute(
            f"UPDATE profile SET {', '.join(updates)} WHERE id = ?", values
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="profile not found")
        await db.commit()
        cursor = await db.execute("SELECT * FROM profile WHERE id = ?", (user_id,))
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="profile not found")
        return dict(row)
    finally:
        await db.close()
