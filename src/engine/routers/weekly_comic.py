import datetime
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from database import get_db
from agents.weekly_comic_agent import plan_weekly_comic
from agents.image_agent import generate_image

router = APIRouter()


class GenerateRequest(BaseModel):
    user_id: int = 1
    week_start: str
    week_end: str
    style: str = "ghibli"
    custom_style_prompt: Optional[str] = None


def _iter_dates(start: str, end: str) -> list[str]:
    s = datetime.date.fromisoformat(start)
    e = datetime.date.fromisoformat(end)
    if e < s:
        raise HTTPException(status_code=400, detail="week_end 必须不早于 week_start")
    if (e - s).days > 30:
        raise HTTPException(status_code=400, detail="时间跨度过长（最多 31 天）")
    out = []
    cur = s
    while cur <= e:
        out.append(cur.isoformat())
        cur += datetime.timedelta(days=1)
    return out


async def _collect_days(db, user_id: int, dates: list[str]) -> tuple[list[dict], bool]:
    """Return (days, has_any_record).  days = list of {date, schedules, fragments}."""
    days: list[dict] = []
    has_any = False
    for date in dates:
        cursor = await db.execute(
            "SELECT * FROM schedules WHERE date = ? AND user_id = ?",
            (date, user_id),
        )
        schedules = [dict(r) for r in await cursor.fetchall()]
        for s in schedules:
            s["completed"] = bool(s["completed"])

        cursor = await db.execute(
            "SELECT * FROM fragments WHERE date = ? AND user_id = ?",
            (date, user_id),
        )
        fragments = [dict(r) for r in await cursor.fetchall()]

        if schedules or fragments:
            has_any = True
        days.append({"date": date, "schedules": schedules, "fragments": fragments})
    return days, has_any


@router.post("/generate")
async def generate(req: GenerateRequest):
    dates = _iter_dates(req.week_start, req.week_end)
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT nickname FROM profile WHERE id = ?", (req.user_id,)
        )
        prof_row = await cursor.fetchone()
        if not prof_row:
            raise HTTPException(status_code=404, detail="profile not found")
        nickname = prof_row["nickname"]

        days, has_any = await _collect_days(db, req.user_id, dates)
    finally:
        await db.close()

    if not has_any:
        raise HTTPException(
            status_code=400,
            detail="本周还没有任何记录，先去 Today 写点什么吧",
        )

    image_prompt, caption = await plan_weekly_comic(
        nickname=nickname,
        week_start=req.week_start,
        week_end=req.week_end,
        days=days,
        style=req.style,
        custom_style_prompt=req.custom_style_prompt,
    )

    # Use the planner-built prompt as the diary_text input to image_agent.
    # image_agent.build_image_prompt wraps it with style + safety boilerplate.
    url = await generate_image(
        diary_text=image_prompt,
        style=req.style,
        custom_style_prompt=req.custom_style_prompt,
    )

    db = await get_db()
    try:
        cursor = await db.execute(
            "INSERT INTO weekly_comics (user_id, week_start, week_end, style, style_prompt, prompt, url, caption) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                req.user_id, req.week_start, req.week_end,
                req.style, req.custom_style_prompt,
                image_prompt, url, caption,
            ),
        )
        new_id = cursor.lastrowid
        await db.commit()
        cursor = await db.execute(
            "SELECT * FROM weekly_comics WHERE id = ?", (new_id,)
        )
        row = await cursor.fetchone()
        return dict(row)
    finally:
        await db.close()


@router.get("/list")
async def list_comics(user_id: int = 1, limit: int = 30):
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM weekly_comics WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
            (user_id, max(1, min(limit, 100))),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


@router.delete("/{comic_id}")
async def delete_comic(comic_id: int):
    db = await get_db()
    try:
        await db.execute("DELETE FROM weekly_comics WHERE id = ?", (comic_id,))
        await db.commit()
        return {"message": "deleted"}
    finally:
        await db.close()
