from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from database import get_db

router = APIRouter()


class FragmentCreate(BaseModel):
    date: str
    content: Optional[str] = None
    photo_url: Optional[str] = None
    photo_description: Optional[str] = None
    mood_tag: Optional[str] = None
    user_id: int = 1


@router.post("")
async def create_fragment(data: FragmentCreate):
    from routers.schedules import _upsert_checkin
    db = await get_db()
    try:
        cursor = await db.execute(
            "INSERT INTO fragments (date, content, photo_url, photo_description, mood_tag, user_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (data.date, data.content, data.photo_url, data.photo_description, data.mood_tag, data.user_id),
        )
        new_id = cursor.lastrowid
        await _upsert_checkin(db, data.date, data.user_id, has_fragment=True)
        await db.commit()
        cursor = await db.execute("SELECT * FROM fragments WHERE id = ?", (new_id,))
        row = await cursor.fetchone()
        return dict(row)
    finally:
        await db.close()


class FragmentUpdate(BaseModel):
    content: Optional[str] = None
    photo_url: Optional[str] = None
    photo_description: Optional[str] = None
    mood_tag: Optional[str] = None


@router.put("/{fragment_id}")
async def update_fragment(fragment_id: int, data: FragmentUpdate):
    db = await get_db()
    try:
        payload = data.model_dump(exclude_unset=True)
        if not payload:
            return {"message": "nothing to update"}
        updates = [f"{k} = ?" for k in payload.keys()]
        values = list(payload.values())
        values.append(fragment_id)
        await db.execute(
            f"UPDATE fragments SET {', '.join(updates)} WHERE id = ?", values
        )
        await db.commit()
        cursor = await db.execute("SELECT * FROM fragments WHERE id = ?", (fragment_id,))
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="fragment not found")
        return dict(row)
    finally:
        await db.close()


@router.get("")
async def list_fragments(date: str, user_id: int = 1):
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM fragments WHERE date = ? AND user_id = ? ORDER BY created_at",
            (date, user_id),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        await db.close()


@router.delete("/{fragment_id}")
async def delete_fragment(fragment_id: int):
    db = await get_db()
    try:
        await db.execute("DELETE FROM fragments WHERE id = ?", (fragment_id,))
        await db.commit()
        return {"message": "deleted"}
    finally:
        await db.close()
