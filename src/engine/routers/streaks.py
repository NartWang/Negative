from fastapi import APIRouter
from database import get_db

router = APIRouter()


@router.get("")
async def get_streaks(user_id: int = 1):
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT date, has_schedule, has_fragment FROM checkins WHERE user_id = ? ORDER BY date DESC",
            (user_id,),
        )
        rows = await cursor.fetchall()

        calendar_data = {}
        for row in rows:
            calendar_data[row["date"]] = {
                "has_schedule": bool(row["has_schedule"]),
                "has_fragment": bool(row["has_fragment"]),
            }

        import datetime
        current_streak = 0
        today = datetime.date.today()
        check_date = today

        while True:
            date_str = check_date.strftime("%Y-%m-%d")
            if date_str in calendar_data:
                entry = calendar_data[date_str]
                if entry["has_schedule"] or entry["has_fragment"]:
                    current_streak += 1
                    check_date -= datetime.timedelta(days=1)
                else:
                    break
            else:
                if check_date == today:
                    check_date -= datetime.timedelta(days=1)
                    continue
                break

        return {
            "current_streak": current_streak,
            "calendar_data": calendar_data,
        }
    finally:
        await db.close()
