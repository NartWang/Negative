from datetime import date as date_type

from fastapi import APIRouter, Depends, HTTPException

from auth.dependencies import get_current_user_id
from database import get_db
from services.story_days import (
    get_story_day,
    list_completed_picturebooks,
    list_story_chapters,
)


router = APIRouter(prefix="/api/story", tags=["story-days"])


@router.get("/chapters")
async def chapters(user_id: int = Depends(get_current_user_id)):
    db = await get_db()
    try:
        return await list_story_chapters(db, user_id)
    finally:
        await db.close()


@router.get("/picturebooks")
async def picturebooks(user_id: int = Depends(get_current_user_id)):
    db = await get_db()
    try:
        return {"items": await list_completed_picturebooks(db, user_id)}
    finally:
        await db.close()


@router.get("/days/{date}")
async def story_day(date: str, user_id: int = Depends(get_current_user_id)):
    # 遵循 SEC-INPUT-001 规范: reject malformed path dates before querying.
    try:
        normalized = date_type.fromisoformat(date).isoformat()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="invalid date") from exc

    db = await get_db()
    try:
        return await get_story_day(db, user_id, normalized)
    finally:
        await db.close()
