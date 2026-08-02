"""Idempotent seed of mock data for user_id=2 (妈妈). Covers the 7 days
ending today: 12 schedules, 10 fragments, 3 confirmed diaries, plus 7 checkin rows.
Safe to call on every startup — checks for existing rows first.
"""
import datetime
from typing import Any


FAMILY_USER_ID = 2


def _recent_dates(n: int = 7) -> list[str]:
    today = datetime.date.today()
    return [(today - datetime.timedelta(days=i)).isoformat() for i in range(n - 1, -1, -1)]


def _build_schedules(dates: list[str]) -> list[tuple]:
    # (date, time, title, completed, feeling)
    rows: list[tuple] = []
    plans = [
        [("07:00", "晨练公园", 1, "今天太极打得特别顺")],
        [("06:30", "早市买菜", 1, "买到刚摘的芹菜"),
         ("10:00", "浇花", 1, None)],
        [("08:00", "和邻居跳广场舞", 1, "李姨腰好了，回来跳了"),
         ("14:00", "看孙女的照片", 1, "小家伙又胖了")],
        [("07:30", "去医院取药", 1, "降压药这次开了一个月")],
        [("09:00", "包饺子", 1, "想着你小时候爱吃韭菜的"),
         ("19:00", "给你打电话没接", 0, None)],
        [("06:00", "晨练", 1, None),
         ("11:00", "做你爱吃的红烧肉", 1, "拍了照存着，等你回来吃")],
        [("08:30", "去菜场", 1, None),
         ("15:00", "织毛衣", 0, "给小孙女织的，快好了")],
    ]
    for date, day_plan in zip(dates, plans):
        for (time, title, completed, feeling) in day_plan:
            rows.append((date, time, title, completed, feeling))
    return rows


def _build_fragments(dates: list[str]) -> list[tuple]:
    # (date, content, mood_tag)
    rows: list[tuple] = []
    fragments_per_day = [
        [("今天看到楼下的猫又生了一窝", "warm"),
         ("你说过最爱的桂花开了", "happy")],
        [("电视里在放你小时候看的动画片", "warm")],
        [("做梦梦见你回来了，醒来还笑着", "happy")],
        [("血压有点高，没告诉你", "calm")],
        [("视频没接，是不是又加班了", "sad"),
         ("饺子放冰箱了，下次你回来煮", "warm")],
        [("阳台的茉莉开了，香得很", "happy")],
        [("毛衣再织两天就好了", "calm"),
         ("听邻居说你单位最近忙，别太累", "warm")],
    ]
    for date, day_fragments in zip(dates, fragments_per_day):
        for (content, mood) in day_fragments:
            rows.append((date, content, mood))
    return rows


def _build_diaries(dates: list[str]) -> list[tuple]:
    # (date, text, source, status)
    # Three confirmed diaries on day -5, -3, -1
    return [
        (dates[1],
         "今天天气好，一早就去早市挑了把刚摘的芹菜。阳台的花浇完水，看着花骨朵又开了一朵，心里就盼着你也能看到。中午想着你小时候不爱吃菜，老想给你包顿饺子。日子慢慢的，盼你常回来。",
         "ai", "confirmed"),
        (dates[3],
         "去医院取药，护士还记得我，说每次都准点。回来路上想着你最近肯定忙，没敢打电话扰你。降压药这次开够了一个月，你别担心。家里一切都好。",
         "ai", "confirmed"),
        (dates[5],
         "今天起了个大早，做了你最爱的红烧肉。拍了照存着，等你回来一起吃。下午跟邻居说起你，她家儿子也常加班，说现在的年轻人都不容易。我说，能听到你电话里那一声妈，就比什么都强。",
         "ai", "confirmed"),
    ]


async def seed_family_data(db: Any) -> None:
    """Idempotent: only runs if user_id=2 has zero schedules."""
    cursor = await db.execute(
        "SELECT COUNT(*) as c FROM schedules WHERE user_id = ?", (FAMILY_USER_ID,)
    )
    if (await cursor.fetchone())["c"] > 0:
        return

    dates = _recent_dates(7)

    for (date, time, title, completed, feeling) in _build_schedules(dates):
        await db.execute(
            "INSERT INTO schedules (date, time, title, completed, feeling, user_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (date, time, title, completed, feeling, FAMILY_USER_ID),
        )

    for (date, content, mood) in _build_fragments(dates):
        await db.execute(
            "INSERT INTO fragments (date, content, mood_tag, user_id) VALUES (?, ?, ?, ?)",
            (date, content, mood, FAMILY_USER_ID),
        )

    for (date, text, source, status) in _build_diaries(dates):
        await db.execute(
            "INSERT INTO diaries (date, text, draft_text, source, status, user_id, confirmed_at) "
            "VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)",
            (date, text, text, source, status, FAMILY_USER_ID),
        )

    # Checkin rows for every seeded day
    for date in dates:
        await db.execute(
            "INSERT INTO checkins (date, has_schedule, has_fragment, user_id) VALUES (?, 1, 1, ?)",
            (date, FAMILY_USER_ID),
        )

    await db.commit()
