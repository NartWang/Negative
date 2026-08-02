from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from database import get_db

router = APIRouter()


class ProfileUpdate(BaseModel):
    nickname: Optional[str] = None
    avatar_url: Optional[str] = None
    signature: Optional[str] = None


@router.get("")
async def get_profile(user_id: int = 1):
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
async def update_profile(data: ProfileUpdate, user_id: int = 1):
    db = await get_db()
    try:
        payload = data.model_dump(exclude_unset=True)
        if not payload:
            cursor = await db.execute("SELECT * FROM profile WHERE id = ?", (user_id,))
            row = await cursor.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="profile not found")
            return dict(row)
        updates = [f"{k} = ?" for k in payload.keys()]
        values = list(payload.values())
        values.append(user_id)
        await db.execute(f"UPDATE profile SET {', '.join(updates)} WHERE id = ?", values)
        await db.commit()
        cursor = await db.execute("SELECT * FROM profile WHERE id = ?", (user_id,))
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="profile not found")
        return dict(row)
    finally:
        await db.close()
