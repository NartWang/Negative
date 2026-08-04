from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
import aiosqlite
from auth.dependencies import get_current_user_id, require_same_origin
from database import get_db

router = APIRouter()


class ScheduleCreate(BaseModel):
    date: str
    time: Optional[str] = None
    title: str
    feeling: Optional[str] = None


class ScheduleUpdate(BaseModel):
    time: Optional[str] = None
    title: Optional[str] = None
    completed: Optional[bool] = None
    feeling: Optional[str] = None


@router.post("")
async def create_schedule(
    data: ScheduleCreate,
    _: None = Depends(require_same_origin),
    user_id: int = Depends(get_current_user_id),
):
    db = await get_db()
    try:
        cursor = await db.execute(
            "INSERT INTO schedules (date, time, title, feeling, user_id) VALUES (?, ?, ?, ?, ?)",
            (data.date, data.time, data.title, data.feeling, user_id),
        )
        new_id = cursor.lastrowid
        await _upsert_checkin(db, data.date, user_id, has_schedule=True)
        await db.commit()
        cursor = await db.execute(
            "SELECT * FROM schedules WHERE id = ? AND user_id = ?",
            (new_id, user_id),
        )
        row = await cursor.fetchone()
        result = dict(row)
        result["completed"] = bool(result["completed"])
        return result
    finally:
        await db.close()


@router.get("")
async def list_schedules(
    date: str, user_id: int = Depends(get_current_user_id)
):
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM schedules WHERE date = ? AND user_id = ? ORDER BY time, created_at",
            (date, user_id),
        )
        rows = await cursor.fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d["completed"] = bool(d["completed"])
            result.append(d)
        return result
    finally:
        await db.close()


@router.put("/{schedule_id}")
async def update_schedule(
    schedule_id: int,
    data: ScheduleUpdate,
    _: None = Depends(require_same_origin),
    user_id: int = Depends(get_current_user_id),
):
    db = await get_db()
    try:
        updates = []
        values = []
        for field, value in data.model_dump(exclude_unset=True).items():
            if field == "completed":
                updates.append("completed = ?")
                values.append(1 if value else 0)
            else:
                updates.append(f"{field} = ?")
                values.append(value)
        if not updates:
            cursor = await db.execute(
                "SELECT 1 FROM schedules WHERE id = ? AND user_id = ?",
                (schedule_id, user_id),
            )
            if not await cursor.fetchone():
                raise HTTPException(status_code=404, detail="schedule not found")
            return {"message": "nothing to update"}
        values.extend([schedule_id, user_id])
        cursor = await db.execute(
            f"UPDATE schedules SET {', '.join(updates)} "
            "WHERE id = ? AND user_id = ?",
            values,
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="schedule not found")
        await db.commit()
        return {"message": "updated"}
    finally:
        await db.close()


@router.delete("/{schedule_id}")
async def delete_schedule(
    schedule_id: int,
    _: None = Depends(require_same_origin),
    user_id: int = Depends(get_current_user_id),
):
    db = await get_db()
    try:
        cursor = await db.execute(
            "DELETE FROM schedules WHERE id = ? AND user_id = ?",
            (schedule_id, user_id),
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="schedule not found")
        await db.commit()
        return {"message": "deleted"}
    finally:
        await db.close()


async def _upsert_checkin(
    db: aiosqlite.Connection,
    date: str,
    user_id: int = 1,
    has_schedule: bool = False,
    has_fragment: bool = False,
):
    existing = await db.execute(
        "SELECT id FROM checkins WHERE date = ? AND user_id = ?", (date, user_id)
    )
    row = await existing.fetchone()
    if row:
        sets = []
        if has_schedule:
            sets.append("has_schedule = 1")
        if has_fragment:
            sets.append("has_fragment = 1")
        if sets:
            await db.execute(
                f"UPDATE checkins SET {', '.join(sets)} WHERE date = ? AND user_id = ?",
                [date, user_id],
            )
    else:
        await db.execute(
            "INSERT INTO checkins (date, has_schedule, has_fragment, user_id) "
            "VALUES (?, ?, ?, ?)",
            (date, 1 if has_schedule else 0, 1 if has_fragment else 0, user_id),
        )
