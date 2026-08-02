import datetime
from typing import Optional
from fastapi import APIRouter, HTTPException
from database import get_db
from agents.thermometer_agent import (
    compute_quant, label_for_score, ai_score_and_comment,
)

router = APIRouter()


async def _consecutive_checkin_days(db, user_id: int, anchor: datetime.date) -> int:
    """Walk back from anchor; count consecutive days where checkin row has any signal.
    Allow today itself to be unfilled (matches v2 streaks semantics)."""
    cursor = await db.execute(
        "SELECT date, has_schedule, has_fragment FROM checkins WHERE user_id = ?",
        (user_id,),
    )
    calendar = {
        r["date"]: bool(r["has_schedule"]) or bool(r["has_fragment"])
        for r in await cursor.fetchall()
    }
    streak = 0
    check = anchor
    today = datetime.date.today()
    while True:
        s = check.strftime("%Y-%m-%d")
        if calendar.get(s):
            streak += 1
            check -= datetime.timedelta(days=1)
        else:
            # Allow today to be empty without breaking the streak.
            if check == today and not calendar.get(s):
                check -= datetime.timedelta(days=1)
                continue
            break
    return streak


@router.get("")
async def get_thermometer(user_id: int = 1, date: Optional[str] = None):
    if date is None:
        date = datetime.date.today().isoformat()
    try:
        anchor = datetime.date.fromisoformat(date)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid date")

    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT nickname FROM profile WHERE id = ?", (user_id,)
        )
        prof_row = await cursor.fetchone()
        nickname = prof_row["nickname"] if prof_row else "你"

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

        streak = await _consecutive_checkin_days(db, user_id, anchor)
    finally:
        await db.close()

    frag_count = len(fragments)
    sched_total = len(schedules)
    sched_done = sum(1 for s in schedules if s["completed"])
    ratio = (sched_done / sched_total) if sched_total else 0.0

    quant = compute_quant(frag_count, ratio, streak)
    ai_score, comment = await ai_score_and_comment(nickname, schedules, fragments)
    score = max(0, min(100, quant + ai_score))
    label, color = label_for_score(score)
    return {
        "score": score,
        "label": label,
        "color": color,
        "comment": comment,
        "quant_score": quant,
        "ai_score": ai_score,
        "inputs": {
            "fragments_count": frag_count,
            "schedules_total": sched_total,
            "schedules_completed": sched_done,
            "consecutive_days": streak,
        },
    }
