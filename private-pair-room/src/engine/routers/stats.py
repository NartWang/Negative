import datetime
from fastapi import APIRouter, Depends
from auth.dependencies import get_current_user_id
from database import get_db

router = APIRouter()


def _longest_streak(dates: set[str]) -> int:
    if not dates:
        return 0
    parsed = sorted(datetime.date.fromisoformat(d) for d in dates)
    longest = 1
    current = 1
    for i in range(1, len(parsed)):
        if (parsed[i] - parsed[i - 1]).days == 1:
            current += 1
            longest = max(longest, current)
        else:
            current = 1
    return longest


@router.get("")
async def get_stats(user_id: int = Depends(get_current_user_id)):
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT COUNT(*) as c FROM diaries WHERE status = 'confirmed' AND user_id = ?",
            (user_id,),
        )
        diary_count = (await cursor.fetchone())["c"]

        cursor = await db.execute(
            "SELECT COUNT(*) as c FROM fragments WHERE user_id = ?", (user_id,)
        )
        fragment_count = (await cursor.fetchone())["c"]

        cursor = await db.execute(
            "SELECT date FROM checkins WHERE user_id = ? AND (has_schedule = 1 OR has_fragment = 1)",
            (user_id,),
        )
        dates = {r["date"] for r in await cursor.fetchall()}
        longest = _longest_streak(dates)

        today = datetime.date.today()
        month_start = today.replace(day=1).isoformat()
        cursor = await db.execute(
            "SELECT COUNT(*) as c FROM checkins WHERE user_id = ? AND date >= ? AND (has_schedule = 1 OR has_fragment = 1)",
            (user_id, month_start),
        )
        month_checkins = (await cursor.fetchone())["c"]
        if today.month == 12:
            days_in_month = 31
        else:
            days_in_month = (today.replace(month=today.month + 1, day=1) - datetime.timedelta(days=1)).day

        return {
            "diary_count": diary_count,
            "fragment_count": fragment_count,
            "longest_streak": longest,
            "month_checkins": month_checkins,
            "month_days": days_in_month,
        }
    finally:
        await db.close()
