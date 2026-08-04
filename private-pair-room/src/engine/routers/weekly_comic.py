import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from auth.dependencies import get_current_user_id, require_same_origin
from database import get_db
from agents.weekly_comic_agent import plan_weekly_comic
from agents.image_agent import generate_image
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


class GenerateRequest(BaseModel):
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
async def generate(
    req: GenerateRequest,
    _: None = Depends(require_same_origin),
    user_id: int = Depends(get_current_user_id),
):
    dates = _iter_dates(req.week_start, req.week_end)
    db = await get_db()
    try:
        # 遵循 BE-AUTH-001 规范: identity comes from the authenticated session.
        cursor = await db.execute(
            "SELECT nickname FROM profile WHERE id = ?", (user_id,)
        )
        prof_row = await cursor.fetchone()
        if not prof_row:
            raise HTTPException(status_code=404, detail="profile not found")
        nickname = prof_row["nickname"]

        days, has_any = await _collect_days(db, user_id, dates)
    finally:
        await db.close()

    if not has_any:
        raise HTTPException(
            status_code=400,
            detail="本周还没有任何记录，先去 Today 写点什么吧",
        )

    try:
        image_prompt, caption = await plan_weekly_comic(
            nickname=nickname,
            week_start=req.week_start,
            week_end=req.week_end,
            days=days,
            style=req.style,
            custom_style_prompt=req.custom_style_prompt,
        )
    except GenerationServiceError as exc:
        raise_generation_http_error(exc, service="AI")

    # Use the planner-built prompt as the diary_text input to image_agent.
    # image_agent.build_image_prompt wraps it with style + safety boilerplate.
    try:
        url = await generate_image(
            diary_text=image_prompt,
            style=req.style,
            custom_style_prompt=req.custom_style_prompt,
        )
    except GenerationServiceError as exc:
        raise_generation_http_error(exc, service="image")

    db = await get_db()
    try:
        async with staged_generated_media(db) as media_stage:
            try:
                asset = await store_generated_asset(
                    db,
                    user_id,
                    url,
                    stage=media_stage,
                )
            except MediaStoreError as exc:
                raise HTTPException(
                    status_code=400, detail="generated image is invalid"
                ) from exc
            cursor = await db.execute(
                "INSERT INTO weekly_comics "
                "(user_id, week_start, week_end, style, style_prompt, prompt, url, caption, asset_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    user_id, req.week_start, req.week_end,
                    req.style, req.custom_style_prompt,
                    image_prompt, asset.url, caption, asset.id,
                ),
            )
            new_id = cursor.lastrowid
        cursor = await db.execute(
            "SELECT * FROM weekly_comics WHERE id = ? AND user_id = ?",
            (new_id, user_id),
        )
        row = await cursor.fetchone()
        return dict(row)
    finally:
        await db.close()


@router.get("/list")
async def list_comics(
    limit: int = 30,
    user_id: int = Depends(get_current_user_id),
):
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
async def delete_comic(
    comic_id: int,
    _: None = Depends(require_same_origin),
    user_id: int = Depends(get_current_user_id),
):
    db = await get_db()
    try:
        # 遵循 SEC-AUTH-002 规范: delete includes the owner predicate.
        cursor = await db.execute(
            "DELETE FROM weekly_comics WHERE id = ? AND user_id = ?",
            (comic_id, user_id),
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="comic not found")
        await db.commit()
        return {"message": "deleted"}
    finally:
        await db.close()
