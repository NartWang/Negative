import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from auth.dependencies import get_current_user_id
from database import get_db
from agents.thermometer_agent import (
    compute_quant, label_for_score, ai_score_and_comment,
)

router = APIRouter()


def parse_temperature_date(value: str) -> datetime.date:
    """Parse only the canonical calendar-date representation used by the APIs."""
    try:
        parsed = datetime.date.fromisoformat(value)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="invalid date") from None
    if parsed.isoformat() != value:
        raise HTTPException(status_code=400, detail="invalid date")
    return parsed


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


async def load_temperature_inputs(
    user_id: int,
    snapshot_date: str,
    anchor: datetime.date,
) -> dict:
    """Load owner-scoped inputs using a short-lived database connection."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT nickname FROM profile WHERE id = ?", (user_id,)
        )
        prof_row = await cursor.fetchone()
        raw_nickname = prof_row["nickname"] if prof_row else None
        nickname = (
            raw_nickname.strip()
            if isinstance(raw_nickname, str) and raw_nickname.strip()
            else "你"
        )

        cursor = await db.execute(
            "SELECT * FROM schedules WHERE date = ? AND user_id = ?",
            (snapshot_date, user_id),
        )
        schedules = [dict(row) for row in await cursor.fetchall()]
        for schedule in schedules:
            schedule["completed"] = bool(schedule["completed"])

        cursor = await db.execute(
            "SELECT * FROM fragments WHERE date = ? AND user_id = ?",
            (snapshot_date, user_id),
        )
        fragments = [dict(row) for row in await cursor.fetchall()]

        streak = await _consecutive_checkin_days(db, user_id, anchor)
    finally:
        await db.close()

    return {
        "nickname": nickname,
        "schedules": schedules,
        "fragments": fragments,
        "streak": streak,
    }


async def compute_temperature(inputs: dict) -> dict:
    """Compute a temperature after all database resources are released.

    The returned mapping is an internal result. Callers decide which fields are
    private and which form an explicit room-safe snapshot.
    """
    nickname = inputs["nickname"]
    schedules = inputs["schedules"]
    fragments = inputs["fragments"]
    streak = inputs["streak"]
    frag_count = len(fragments)
    sched_total = len(schedules)
    sched_done = sum(1 for schedule in schedules if schedule["completed"])
    ratio = (sched_done / sched_total) if sched_total else 0.0

    quant = compute_quant(frag_count, ratio, streak)
    ai_score, comment = await ai_score_and_comment(nickname, schedules, fragments)
    score = max(0, min(100, quant + ai_score))
    label, color = label_for_score(score)
    return {
        "nickname": nickname,
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


@router.get("")
async def get_thermometer(
    date: Optional[str] = None,
    user_id: int = Depends(get_current_user_id),
):
    if date is None:
        date = datetime.date.today().isoformat()
    anchor = parse_temperature_date(date)

    # 遵循 BE-AUTH-001 规范: all inputs are scoped to the session user.
    inputs = await load_temperature_inputs(user_id, date, anchor)
    computed = await compute_temperature(inputs)
    return {
        key: computed[key]
        for key in (
            "score",
            "label",
            "color",
            "comment",
            "quant_score",
            "ai_score",
            "inputs",
        )
    }
