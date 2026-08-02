from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional
import aiosqlite
from database import get_db

router = APIRouter()


class ScheduleCreate(BaseModel):
    date: str
    time: Optional[str] = None
    title: str
    feeling: Optional[str] = None
    user_id: int = 1


class ScheduleUpdate(BaseModel):
    time: Optional[str] = None
    title: Optional[str] = None
    completed: Optional[bool] = None
    feeling: Optional[str] = None


@router.post("")
async def create_schedule(data: ScheduleCreate):
    db = await get_db()
    try:
        cursor = await db.execute(
            "INSERT INTO schedules (date, time, title, feeling, user_id) VALUES (?, ?, ?, ?, ?)",
            (data.date, data.time, data.title, data.feeling, data.user_id),
        )
        new_id = cursor.lastrowid
        await _upsert_checkin(db, data.date, data.user_id, has_schedule=True)
        await db.commit()
        cursor = await db.execute("SELECT * FROM schedules WHERE id = ?", (new_id,))
        row = await cursor.fetchone()
        result = dict(row)
        result["completed"] = bool(result["completed"])
        return result
    finally:
        await db.close()


@router.get("")
async def list_schedules(date: str, user_id: int = 1):
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
async def update_schedule(schedule_id: int, data: ScheduleUpdate):
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
            return {"message": "nothing to update"}
        values.append(schedule_id)
        await db.execute(
            f"UPDATE schedules SET {', '.join(updates)} WHERE id = ?", values
        )
        await db.commit()
        return {"message": "updated"}
    finally:
        await db.close()


@router.delete("/{schedule_id}")
async def delete_schedule(schedule_id: int):
    db = await get_db()
    try:
        await db.execute("DELETE FROM schedules WHERE id = ?", (schedule_id,))
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
