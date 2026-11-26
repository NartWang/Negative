from __future__ import annotations

import json
from datetime import date as date_type
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Optional
from zoneinfo import ZoneInfo


SHANGHAI = ZoneInfo("Asia/Shanghai")
COMPLETE_PICTUREBOOK_PAGE_INDEXES = list(range(9))


def _require_iso_date(value: str) -> str:
    return date_type.fromisoformat(value).isoformat()


def _row_dict(row: Any) -> dict:
    return dict(row)


def _content_types(values: Iterable[str]) -> list[str]:
    order = ["photo", "text", "diary", "picturebook", "story"]
    present = set(values)
    return [item for item in order if item in present]


def _first_sentence(text: Optional[str]) -> Optional[str]:
    cleaned = (text or "").strip()
    if not cleaned:
        return None
    terminators = ("。", "！", "？", ".", "!", "?")
    indexes = [cleaned.find(punctuation) for punctuation in terminators]
    found = [index for index in indexes if index >= 0]
    if found:
        return cleaned[: min(found) + 1]
    return cleaned


def _selected_title(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    try:
        selected = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return None
    if isinstance(selected, list):
        for item in selected:
            if isinstance(item, str) and item.strip():
                return item.strip()
            if isinstance(item, dict):
                title = item.get("title") or item.get("text")
                if isinstance(title, str) and title.strip():
                    return title.strip()
    if isinstance(selected, dict):
        title = selected.get("title") or selected.get("text")
        if isinstance(title, str) and title.strip():
            return title.strip()
    return None


def _parse_utc_timestamp(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    elif "T" not in normalized and " " in normalized:
        normalized = normalized.replace(" ", "T")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _fragment_clock(value: Optional[str]) -> str:
    parsed = _parse_utc_timestamp(value)
    if parsed is None:
        return ""
    return parsed.astimezone(SHANGHAI).strftime("%H:%M")


def _schedule_clock(value: Optional[str]) -> str:
    clock = (value or "").strip()
    try:
        parsed = datetime.strptime(clock, "%H:%M")
    except ValueError:
        return ""
    return parsed.strftime("%H:%M") if parsed.strftime("%H:%M") == clock else ""


def _timeline_sort_key(item: dict) -> tuple[int, str, int, int]:
    clock = item["clock"]
    has_clock = 0 if clock else 1
    type_order = 0 if item["kind"] == "schedule" else 1
    return (has_clock, clock, type_order, item["id"])


def _schedule_sort_key(item: dict) -> tuple[int, str, int]:
    clock = _schedule_clock(item.get("time"))
    return (0 if clock else 1, clock, item["id"])


async def _draft_count(db: Any, user_id: int) -> int:
    # 遵循 SEC-AUTH-002 规范: draft queries are scoped to the authenticated owner.
    cursor = await db.execute(
        """
        SELECT COUNT(*) AS count
        FROM diaries
        WHERE user_id = ?
          AND status = 'draft'
          AND (
            TRIM(COALESCE(draft_text, '')) <> ''
            OR TRIM(COALESCE(text, '')) <> ''
          )
        """,
        (user_id,),
    )
    diary_count = (await cursor.fetchone())["count"]
    cursor = await db.execute(
        """
        SELECT COUNT(*) AS count
        FROM story_works
        WHERE owner_user_id = ? AND status = 'draft'
        """,
        (user_id,),
    )
    work_count = (await cursor.fetchone())["count"]
    return int(diary_count or 0) + int(work_count or 0)


async def _ready_work_rows(db: Any, user_id: int, day: Optional[str] = None) -> list[dict]:
    if day is None:
        cursor = await db.execute(
            """
            SELECT work.*, diary.date AS date
            FROM story_works AS work
            JOIN diaries AS diary
              ON diary.id = work.source_diary_id
             AND diary.user_id = work.owner_user_id
            WHERE work.owner_user_id = ?
              AND work.status IN ('ready', 'published')
            ORDER BY diary.date DESC, work.updated_at DESC, work.id DESC
            """,
            (user_id,),
        )
    else:
        cursor = await db.execute(
            """
            SELECT work.*, diary.date AS date
            FROM story_works AS work
            JOIN diaries AS diary
              ON diary.id = work.source_diary_id
             AND diary.user_id = work.owner_user_id
            WHERE work.owner_user_id = ?
              AND diary.date = ?
              AND work.status IN ('ready', 'published')
            ORDER BY work.updated_at DESC, work.id DESC
            """,
            (user_id, day),
        )
    return [_row_dict(row) for row in await cursor.fetchall()]


async def _ready_story_rows(db: Any, user_id: int, day: Optional[str] = None) -> list[dict]:
    rows = await _ready_work_rows(db, user_id, day)
    return [row for row in rows if row.get("picturebook_job_id") is None]


async def _confirmed_diary_rows(db: Any, user_id: int, day: Optional[str] = None) -> list[dict]:
    if day is None:
        cursor = await db.execute(
            """
            SELECT *
            FROM diaries
            WHERE user_id = ?
              AND status = 'confirmed'
              AND TRIM(COALESCE(text, '')) <> ''
            ORDER BY date DESC, confirmed_at DESC, id DESC
            """,
            (user_id,),
        )
    else:
        cursor = await db.execute(
            """
            SELECT *
            FROM diaries
            WHERE user_id = ?
              AND date = ?
              AND status = 'confirmed'
              AND TRIM(COALESCE(text, '')) <> ''
            ORDER BY confirmed_at DESC, id DESC
            """,
            (user_id, day),
        )
    return [_row_dict(row) for row in await cursor.fetchall()]


async def _fragment_rows(db: Any, user_id: int, day: Optional[str] = None) -> list[dict]:
    if day is None:
        cursor = await db.execute(
            """
            SELECT *
            FROM fragments
            WHERE user_id = ?
              AND (
                TRIM(COALESCE(content, '')) <> ''
                OR photo_url IS NOT NULL
                OR photo_asset_id IS NOT NULL
              )
            ORDER BY date DESC, created_at ASC, id ASC
            """,
            (user_id,),
        )
    else:
        cursor = await db.execute(
            """
            SELECT *
            FROM fragments
            WHERE user_id = ?
              AND date = ?
              AND (
                TRIM(COALESCE(content, '')) <> ''
                OR photo_url IS NOT NULL
                OR photo_asset_id IS NOT NULL
              )
            ORDER BY date DESC, created_at ASC, id ASC
            """,
            (user_id, day),
        )
    return [_row_dict(row) for row in await cursor.fetchall()]


def _asset_image_url(row: dict) -> Optional[str]:
    url = (row.get("image_url") or row.get("url") or "").strip()
    if url:
        return url
    asset_id = (row.get("asset_id") or "").strip()
    if asset_id:
        return f"/api/media/{asset_id}"
    return None


def _complete_picturebook_pages(rows: list[dict]) -> Optional[list[dict]]:
    pages = []
    for row in rows:
        image_url = _asset_image_url(row)
        if not image_url:
            return None
        page = {
            "page_index": int(row["page_index"]),
            "image_url": image_url,
            "caption": row.get("caption") or "",
        }
        asset_id = (row.get("asset_id") or "").strip()
        if asset_id:
            page["asset_id"] = asset_id
        pages.append(page)
    pages.sort(key=lambda page: page["page_index"])
    if [page["page_index"] for page in pages] != COMPLETE_PICTUREBOOK_PAGE_INDEXES:
        return None
    return pages


async def _canonical_picturebook_pages(
    db: Any,
    user_id: int,
    work_id: int,
) -> Optional[list[dict]]:
    cursor = await db.execute(
        """
        SELECT asset.ordinal AS page_index, asset.url, asset.asset_id,
               asset.text AS caption
        FROM work_assets AS asset
        JOIN story_works AS work
          ON work.id = asset.work_id
         AND work.owner_user_id = ?
        WHERE asset.work_id = ?
          AND asset.asset_type = 'image'
        ORDER BY asset.ordinal ASC
        """,
        (user_id, work_id),
    )
    return _complete_picturebook_pages(
        [_row_dict(row) for row in await cursor.fetchall()]
    )


async def _historical_picturebook_pages(
    db: Any,
    user_id: int,
    job_id: int,
) -> Optional[list[dict]]:
    cursor = await db.execute(
        """
        SELECT page.page_index, page.image_url, page.asset_id, page.caption
        FROM picturebook_pages AS page
        JOIN picturebook_jobs AS job
          ON job.id = page.job_id
         AND job.user_id = ?
        WHERE page.job_id = ?
          AND page.status = 'ready'
        ORDER BY page.page_index ASC
        """,
        (user_id, job_id),
    )
    return _complete_picturebook_pages(
        [_row_dict(row) for row in await cursor.fetchall()]
    )


def _normalized_book(
    *,
    source_kind: str,
    source_id: int,
    job_id: int,
    title: str,
    source_start_date: str,
    source_end_date: str,
    style: str,
    pages: list[dict],
    date: str,
    updated_at: Optional[str],
    work_kind: Optional[str] = None,
    published: bool = False,
) -> dict:
    return {
        "source_kind": source_kind,
        "source_id": source_id,
        # 历史绘本没有正式作品类型,保持 None;绝不按日期范围猜测。
        "work_kind": work_kind if source_kind == "canonical_work" else None,
        "published": published if source_kind == "canonical_work" else False,
        "completed_at": updated_at,
        "title": title,
        "source_start_date": source_start_date,
        "source_end_date": source_end_date,
        "start_date": source_start_date,
        "end_date": source_end_date,
        "date": date,
        "style": style,
        "cover_url": pages[0]["image_url"],
        "total_pages": len(COMPLETE_PICTUREBOOK_PAGE_INDEXES),
        "ready_pages": len(pages),
        "pages": pages,
        "_job_id": job_id,
        "_sort_date": source_start_date,
        "_updated_at": updated_at or "",
    }


async def _canonical_picturebook_rows(
    db: Any,
    user_id: int,
    day: Optional[str] = None,
    *,
    include_range_works: bool = True,
) -> list[dict]:
    params: list[Any] = [user_id]
    day_filter = ""
    if day is not None:
        day_filter = """
              AND COALESCE(
                    work.display_start_date,
                    work.source_start_date,
                    diary.date
                  ) = ?
        """
        params.append(day)
    range_filter = "" if include_range_works else "AND work.kind != 'time_story'"
    cursor = await db.execute(
        f"""
        SELECT
            work.id AS work_id,
            work.picturebook_job_id AS job_id,
            work.kind AS kind,
            work.status AS work_status,
            work.title,
            work.style,
            work.updated_at,
            job.updated_at AS job_updated_at,
            COALESCE(work.source_start_date, work.display_start_date, diary.date) AS source_start_date,
            COALESCE(work.source_end_date, work.display_end_date, diary.date) AS source_end_date,
            COALESCE(work.display_start_date, work.source_start_date, diary.date) AS date
        FROM story_works AS work
        JOIN picturebook_jobs AS job
          ON job.id = work.picturebook_job_id
         AND job.user_id = work.owner_user_id
         AND job.work_id = work.id
         AND job.status = 'done'
        LEFT JOIN diaries AS diary
          ON diary.id = work.source_diary_id
         AND diary.user_id = work.owner_user_id
        WHERE work.owner_user_id = ?
          AND work.picturebook_job_id IS NOT NULL
          AND work.status IN ('ready', 'published')
          {range_filter}
          {day_filter}
        ORDER BY date DESC, work.updated_at DESC, work.id DESC
        """,
        tuple(params),
    )
    return [_row_dict(row) for row in await cursor.fetchall()]


async def _historical_picturebook_rows(
    db: Any,
    user_id: int,
    day: Optional[str] = None,
) -> list[dict]:
    params: list[Any] = [user_id]
    day_filter = ""
    if day is not None:
        day_filter = "AND diary.date = ?"
        params.append(day)
    cursor = await db.execute(
        f"""
        SELECT
            job.id AS job_id,
            job.style,
            job.updated_at,
            diary.date,
            diary.text AS diary_text
        FROM picturebook_jobs AS job
        JOIN diaries AS diary
          ON diary.id = job.diary_id
         AND diary.user_id = job.user_id
        WHERE job.user_id = ?
          AND job.work_id IS NULL
          AND job.status = 'done'
          {day_filter}
        ORDER BY diary.date DESC, job.updated_at DESC, job.id DESC
        """,
        tuple(params),
    )
    return [_row_dict(row) for row in await cursor.fetchall()]


async def list_completed_picturebooks(
    db: Any,
    user_id: int,
    day: Optional[str] = None,
    *,
    include_range_works: bool = True,
) -> list[dict]:
    normalized: list[dict] = []
    seen_job_ids: set[int] = set()

    for row in await _canonical_picturebook_rows(
        db,
        user_id,
        day,
        include_range_works=include_range_works,
    ):
        job_id = int(row["job_id"])
        if job_id in seen_job_ids:
            continue
        pages = await _canonical_picturebook_pages(db, user_id, int(row["work_id"]))
        if pages is None:
            continue
        seen_job_ids.add(job_id)
        source_start_date = row["source_start_date"] or row["date"]
        source_end_date = row["source_end_date"] or source_start_date
        normalized.append(
            _normalized_book(
                source_kind="canonical_work",
                source_id=int(row["work_id"]),
                job_id=job_id,
                title=(row["title"] or "").strip() or f"{source_start_date} 绘本",
                source_start_date=source_start_date,
                source_end_date=source_end_date,
                style=row["style"] or "",
                pages=pages,
                date=row["date"] or source_start_date,
                # completed_at 取正式绘本任务完成的更新时间,缺失回退作品自身。
                updated_at=row["job_updated_at"] or row["updated_at"],
                work_kind=row["kind"],
                published=row["work_status"] == "published",
            )
        )

    for row in await _historical_picturebook_rows(db, user_id, day):
        job_id = int(row["job_id"])
        if job_id in seen_job_ids:
            continue
        pages = await _historical_picturebook_pages(db, user_id, job_id)
        if pages is None:
            continue
        seen_job_ids.add(job_id)
        title = _first_sentence(row["diary_text"]) or f"{row['date']} 绘本"
        normalized.append(
            _normalized_book(
                source_kind="historical_job",
                source_id=job_id,
                job_id=job_id,
                title=title,
                source_start_date=row["date"],
                source_end_date=row["date"],
                style=row["style"] or "",
                pages=pages,
                date=row["date"],
                updated_at=row["updated_at"],
            )
        )

    normalized.sort(
        key=lambda item: (
            item["_sort_date"],
            item["_updated_at"],
            1 if item["source_kind"] == "canonical_work" else 0,
            item["source_id"],
        ),
        reverse=True,
    )
    for item in normalized:
        item.pop("_job_id", None)
        item.pop("_sort_date", None)
        item.pop("_updated_at", None)
    return normalized


async def _cover_url(
    db: Any,
    user_id: int,
    day: str,
    *,
    completed_books: Optional[list[dict]] = None,
) -> Optional[str]:
    if completed_books is None:
        completed_books = await list_completed_picturebooks(
            db,
            user_id,
            day,
            include_range_works=False,
        )
    if completed_books:
        return completed_books[0]["cover_url"]

    cursor = await db.execute(
        """
        SELECT asset.url
        FROM story_works AS work
        JOIN diaries AS diary
          ON diary.id = work.source_diary_id
         AND diary.user_id = work.owner_user_id
        JOIN work_assets AS asset
          ON asset.work_id = work.id
         AND asset.asset_type = 'image'
        WHERE work.owner_user_id = ?
          AND diary.date = ?
          AND work.status IN ('ready', 'published')
          AND asset.url IS NOT NULL
        ORDER BY work.updated_at DESC, work.id DESC, asset.ordinal ASC
        LIMIT 1
        """,
        (user_id, day),
    )
    row = await cursor.fetchone()
    if row:
        return row["url"]
    cursor = await db.execute(
        """
        SELECT photo_url
        FROM fragments
        WHERE user_id = ?
          AND date = ?
          AND photo_url IS NOT NULL
        ORDER BY created_at ASC, id ASC
        LIMIT 1
        """,
        (user_id, day),
    )
    row = await cursor.fetchone()
    return row["photo_url"] if row else None


async def _time_story_cover_url(db: Any, user_id: int, work: Mapping[str, Any]) -> Optional[str]:
    cursor = await db.execute(
        """
        SELECT asset.url
        FROM work_assets AS asset
        JOIN story_works AS work
          ON work.id = asset.work_id
         AND work.owner_user_id = ?
        WHERE asset.work_id = ?
          AND asset.asset_type = 'image'
          AND asset.ordinal = 0
          AND TRIM(COALESCE(asset.url, '')) <> ''
        LIMIT 1
        """,
        (user_id, work["id"]),
    )
    row = await cursor.fetchone()
    if row:
        return row["url"]

    cursor = await db.execute(
        """
        SELECT fragment.photo_url
        FROM story_work_diaries AS link
        JOIN diaries AS diary
          ON diary.id = link.diary_id
         AND diary.user_id = ?
        JOIN fragments AS fragment
          ON fragment.user_id = diary.user_id
         AND fragment.date = diary.date
        LEFT JOIN media_assets AS asset
          ON asset.id = fragment.photo_asset_id
         AND asset.owner_user_id = fragment.user_id
        WHERE link.work_id = ?
          AND fragment.photo_url IS NOT NULL
          AND (
            fragment.photo_asset_id IS NULL
            OR asset.id IS NOT NULL
          )
        ORDER BY diary.date ASC, fragment.created_at ASC, fragment.id ASC
        LIMIT 1
        """,
        (user_id, work["id"]),
    )
    row = await cursor.fetchone()
    if row:
        return row["photo_url"]
    return None


async def _completed_time_story_range_items(db: Any, user_id: int) -> list[dict]:
    cursor = await db.execute(
        """
        SELECT work.*
        FROM story_works AS work
        WHERE work.owner_user_id = ?
          AND work.kind = 'time_story'
          AND work.status IN ('ready', 'published')
        ORDER BY work.source_end_date DESC, work.updated_at DESC, work.id DESC
        """,
        (user_id,),
    )
    items = []
    for row in await cursor.fetchall():
        work = _row_dict(row)
        source_end = work["source_end_date"] or work["display_end_date"]
        source_start = work["source_start_date"] or work["display_start_date"] or source_end
        if not source_start or not source_end:
            continue
        title = (work.get("title") or "").strip() or f"{source_start} 至 {source_end}"
        items.append(
            {
                "kind": "range_work",
                "source_kind": "time_story",
                "source_id": work["id"],
                "title": title,
                "summary": title,
                "date": source_end,
                "month": source_end[:7],
                "start_date": source_start,
                "end_date": source_end,
                "source_start_date": source_start,
                "source_end_date": source_end,
                "cover_url": await _time_story_cover_url(db, user_id, work),
                "content_types": ["picturebook"],
                "_updated_at": work.get("updated_at") or "",
            }
        )
    return items


async def _legacy_weekly_range_items(db: Any, user_id: int) -> list[dict]:
    cursor = await db.execute(
        """
        SELECT id, week_start, week_end, url, caption, created_at
        FROM weekly_comics
        WHERE user_id = ?
        ORDER BY week_end DESC, created_at DESC, id DESC
        """,
        (user_id,),
    )
    items = []
    for row in await cursor.fetchall():
        title = (row["caption"] or "").strip() or f"{row['week_start']} 至 {row['week_end']}"
        items.append(
            {
                "kind": "range_work",
                "source_kind": "legacy_weekly",
                "source_id": row["id"],
                "title": title,
                "summary": title,
                "date": row["week_end"],
                "month": row["week_end"][:7],
                "start_date": row["week_start"],
                "end_date": row["week_end"],
                "source_start_date": row["week_start"],
                "source_end_date": row["week_end"],
                "cover_url": row["url"],
                "content_types": ["picturebook"],
                "_updated_at": row["created_at"] or "",
            }
        )
    return items


async def _summary(db: Any, user_id: int, day: str) -> str:
    cursor = await db.execute(
        """
        SELECT work.title, work.selected_segments_json
        FROM story_works AS work
        JOIN diaries AS diary
          ON diary.id = work.source_diary_id
         AND diary.user_id = work.owner_user_id
        WHERE work.owner_user_id = ?
          AND diary.date = ?
          AND work.status IN ('ready', 'published')
        ORDER BY work.updated_at DESC, work.id DESC
        LIMIT 1
        """,
        (user_id, day),
    )
    row = await cursor.fetchone()
    if row:
        title = (row["title"] or "").strip() or _selected_title(row["selected_segments_json"])
        if title:
            return title
    cursor = await db.execute(
        """
        SELECT text
        FROM diaries
        WHERE user_id = ?
          AND date = ?
          AND status = 'confirmed'
          AND TRIM(COALESCE(text, '')) <> ''
        ORDER BY confirmed_at DESC, id DESC
        LIMIT 1
        """,
        (user_id, day),
    )
    row = await cursor.fetchone()
    sentence = _first_sentence(row["text"] if row else None)
    return sentence or "这一天的记录"


async def _chapter_item(
    db: Any,
    user_id: int,
    day: str,
    types: Iterable[str],
    *,
    completed_books_by_day: Optional[dict[str, list[dict]]] = None,
) -> dict:
    summary = await _summary(db, user_id, day)
    completed_books = (
        completed_books_by_day.get(day)
        if completed_books_by_day is not None
        else None
    )
    return {
        "kind": "day",
        "date": day,
        "start_date": day,
        "end_date": day,
        "title": day,
        "summary": summary,
        "cover_url": await _cover_url(
            db,
            user_id,
            day,
            completed_books=completed_books,
        ),
        "content_types": _content_types(types),
    }


async def list_story_chapters(db: Any, user_id: int) -> dict:
    day_types: dict[str, set[str]] = {}
    completed_books_by_day: dict[str, list[dict]] = {}

    for row in await _fragment_rows(db, user_id):
        types = day_types.setdefault(row["date"], set())
        if row["photo_url"] or row["photo_asset_id"]:
            types.add("photo")
        else:
            types.add("text")
    for row in await _confirmed_diary_rows(db, user_id):
        day_types.setdefault(row["date"], set()).add("diary")
    for row in await _ready_story_rows(db, user_id):
        day_types.setdefault(row["date"], set()).add("story")
    for row in await list_completed_picturebooks(db, user_id, include_range_works=False):
        completed_books_by_day.setdefault(row["date"], []).append(row)
        day_types.setdefault(row["date"], set()).add("picturebook")

    day_items = [
        await _chapter_item(
            db,
            user_id,
            day,
            day_types[day],
            completed_books_by_day=completed_books_by_day,
        )
        for day in sorted(day_types.keys(), reverse=True)
    ]
    for item in day_items:
        item["_updated_at"] = ""

    range_items = await _completed_time_story_range_items(db, user_id)
    range_items.extend(await _legacy_weekly_range_items(db, user_id))
    items = [*day_items, *range_items]
    items.sort(
        key=lambda item: (
            item["date"],
            1 if item["kind"] == "range_work" else 0,
            item.get("_updated_at") or "",
            item.get("source_id") or 0,
        ),
        reverse=True,
    )
    for item in items:
        item.pop("_updated_at", None)
    return {"items": items, "draft_count": await _draft_count(db, user_id)}


async def _timeline(db: Any, user_id: int, day: str) -> tuple[list[dict], list[dict]]:
    cursor = await db.execute(
        """
        SELECT *
        FROM schedules
        WHERE user_id = ? AND date = ?
        ORDER BY time ASC, created_at ASC, id ASC
        """,
        (user_id, day),
    )
    schedules = [_row_dict(row) for row in await cursor.fetchall()]
    schedules.sort(key=_schedule_sort_key)

    cursor = await db.execute(
        """
        SELECT *
        FROM fragments
        WHERE user_id = ? AND date = ?
        ORDER BY created_at ASC, id ASC
        """,
        (user_id, day),
    )
    fragments = [_row_dict(row) for row in await cursor.fetchall()]

    entries = []
    for row in schedules:
        clock = _schedule_clock(row.get("time"))
        entries.append(
            {
                "kind": "schedule",
                "id": row["id"],
                "clock": clock,
                "sort_key": clock or None,
                "date": row["date"],
                "title": row["title"],
                "content": None,
                "completed": bool(row["completed"]),
                "feeling": row["feeling"],
            }
        )
    for row in fragments:
        clock = _fragment_clock(row.get("created_at"))
        entries.append(
            {
                "kind": "fragment",
                "id": row["id"],
                "clock": clock,
                "sort_key": clock or None,
                "date": row["date"],
                "title": None,
                "content": row["content"],
                "photo_url": row["photo_url"],
                "photo_asset_id": row["photo_asset_id"],
                "photo_description": row["photo_description"],
                "mood_tag": row["mood_tag"],
                "created_at": row["created_at"],
            }
        )
    entries.sort(key=_timeline_sort_key)
    return entries, schedules


async def _story_work_details(db: Any, user_id: int, day: str) -> list[dict]:
    works = await _ready_story_rows(db, user_id, day)
    results = []
    for work in works:
        cursor = await db.execute(
            """
            SELECT asset.*
            FROM work_assets AS asset
            JOIN story_works AS work
              ON work.id = asset.work_id
             AND work.owner_user_id = ?
            WHERE asset.work_id = ?
            ORDER BY asset.ordinal ASC
            """,
            (user_id, work["id"]),
        )
        item = dict(work)
        item["selected_segments"] = []
        try:
            item["selected_segments"] = json.loads(item.pop("selected_segments_json"))
        except (TypeError, json.JSONDecodeError):
            item.pop("selected_segments_json", None)
        item["assets"] = [_row_dict(row) for row in await cursor.fetchall()]
        results.append(item)
    return results


async def _picturebook_details(db: Any, user_id: int, day: str) -> list[dict]:
    return await list_completed_picturebooks(
        db,
        user_id,
        day,
        include_range_works=False,
    )


async def get_story_day(db: Any, user_id: int, date: str) -> dict:
    day = _require_iso_date(date)
    fragments = await _fragment_rows(db, user_id, day)
    diaries = await _confirmed_diary_rows(db, user_id, day)
    story_works = await _story_work_details(db, user_id, day)
    picturebooks = await _picturebook_details(db, user_id, day)
    timeline, schedules = await _timeline(db, user_id, day)

    types: set[str] = set()
    for row in fragments:
        types.add("photo" if row["photo_url"] or row["photo_asset_id"] else "text")
    if diaries:
        types.add("diary")
    if picturebooks:
        types.add("picturebook")
    if story_works:
        types.add("story")

    chapter = await _chapter_item(
        db,
        user_id,
        day,
        types or {"text"},
        completed_books_by_day={day: picturebooks},
    )
    chapter.update(
        {
            "timeline": timeline,
            "schedules": schedules,
            "fragments": fragments,
            "diaries": diaries,
            "picturebooks": picturebooks,
            "story_works": story_works,
            "draft_count": await _draft_count(db, user_id),
        }
    )
    return chapter
