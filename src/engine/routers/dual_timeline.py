import datetime
import json
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from database import get_db
from agents.dual_timeline_agent import summarize, plan_comic
from agents.image_agent import generate_image

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


async def _load_user_events(db, date: str, user_id: int) -> list:
    """Merge schedules + fragments into a unified time-sorted event list."""
    events = []
    cursor = await db.execute(
        "SELECT id, time, title, completed, feeling FROM schedules "
        "WHERE date = ? AND user_id = ? ORDER BY time, created_at",
        (date, user_id),
    )
    for r in await cursor.fetchall():
        d = dict(r)
        events.append({
            "type": "schedule",
            "id": d["id"],
            "time": d.get("time") or "00:00",
            "title": d["title"],
            "completed": bool(d["completed"]),
            "feeling": d.get("feeling"),
        })

    cursor = await db.execute(
        "SELECT id, content, mood_tag, photo_description, created_at FROM fragments "
        "WHERE date = ? AND user_id = ? ORDER BY created_at",
        (date, user_id),
    )
    for r in await cursor.fetchall():
        d = dict(r)
        events.append({
            "type": "fragment",
            "id": d["id"],
            "time": _fragment_time(d.get("created_at")),
            "content": d.get("content"),
            "mood_tag": d.get("mood_tag"),
            "photo_description": d.get("photo_description"),
        })

    events.sort(key=lambda e: e["time"] or "23:59")
    return events


@router.get("")
async def get_dual_timeline(date: str, user_a: int = 1, user_b: int = 2):
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT id, nickname FROM profile WHERE id IN (?, ?)",
            (user_a, user_b),
        )
        rows = {r["id"]: r["nickname"] for r in await cursor.fetchall()}
        if user_a not in rows or user_b not in rows:
            raise HTTPException(status_code=404, detail="user not found")

        events_a = await _load_user_events(db, date, user_a)
        events_b = await _load_user_events(db, date, user_b)
    finally:
        await db.close()

    name_a = rows[user_a]
    name_b = rows[user_b]
    summary = await summarize(date, name_a, events_a, name_b, events_b)

    return {
        "date": date,
        "user_a": {"id": user_a, "nickname": name_a},
        "user_b": {"id": user_b, "nickname": name_b},
        "summary": summary,
        "events_a": events_a,
        "events_b": events_b,
    }


class SelectedEvent(BaseModel):
    type: str           # 'schedule' | 'fragment'
    id: int
    time: Optional[str] = None
    title: Optional[str] = None
    content: Optional[str] = None
    completed: Optional[bool] = None
    feeling: Optional[str] = None
    mood_tag: Optional[str] = None


class GenerateComicRequest(BaseModel):
    date: str
    user_a: int = 1
    user_b: int = 2
    selected_a: list = []
    selected_b: list = []
    style: str = "ghibli"
    custom_style_prompt: Optional[str] = None


@router.post("/comic/generate")
async def generate_comic(req: GenerateComicRequest):
    total = len(req.selected_a) + len(req.selected_b)
    if total == 0:
        raise HTTPException(status_code=400, detail="至少选 1 个时刻才能生成漫画")
    if total > 6:
        raise HTTPException(status_code=400, detail="最多选 6 个时刻")

    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT id, nickname FROM profile WHERE id IN (?, ?)",
            (req.user_a, req.user_b),
        )
        rows = {r["id"]: r["nickname"] for r in await cursor.fetchall()}
        if req.user_a not in rows or req.user_b not in rows:
            raise HTTPException(status_code=404, detail="user not found")
    finally:
        await db.close()

    selected_a_dict = [e.model_dump() if hasattr(e, 'model_dump') else e for e in req.selected_a]
    selected_b_dict = [e.model_dump() if hasattr(e, 'model_dump') else e for e in req.selected_b]

    image_prompt, caption = await plan_comic(
        date=req.date,
        user_a_name=rows[req.user_a], selected_a=selected_a_dict,
        user_b_name=rows[req.user_b], selected_b=selected_b_dict,
        style=req.style, custom_style_prompt=req.custom_style_prompt,
    )

    url = await generate_image(
        diary_text=image_prompt,
        style=req.style,
        custom_style_prompt=req.custom_style_prompt,
    )

    selected_json = json.dumps(
        {"user_a_events": selected_a_dict, "user_b_events": selected_b_dict},
        ensure_ascii=False,
    )

    db = await get_db()
    try:
        cursor = await db.execute(
            "INSERT INTO dual_timeline_comics "
            "(date, user_a_id, user_b_id, selected_events_json, style, style_prompt, prompt, url, caption) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                req.date, req.user_a, req.user_b, selected_json,
                req.style, req.custom_style_prompt,
                image_prompt, url, caption,
            ),
        )
        new_id = cursor.lastrowid
        await db.commit()
        cursor = await db.execute(
            "SELECT * FROM dual_timeline_comics WHERE id = ?", (new_id,)
        )
        row = await cursor.fetchone()
        return dict(row)
    finally:
        await db.close()


@router.get("/comic/list")
async def list_comics(user_id: int = 1, limit: int = 30):
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM dual_timeline_comics WHERE user_a_id = ? "
            "ORDER BY created_at DESC LIMIT ?",
            (user_id, max(1, min(limit, 100))),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


@router.delete("/comic/{comic_id}")
async def delete_comic(comic_id: int):
    db = await get_db()
    try:
        await db.execute("DELETE FROM dual_timeline_comics WHERE id = ?", (comic_id,))
        await db.commit()
        return {"message": "deleted"}
    finally:
        await db.close()
