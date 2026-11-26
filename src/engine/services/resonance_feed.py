from __future__ import annotations

import base64
import json
from datetime import datetime
from typing import Any, Optional

from fastapi import HTTPException

from services.media_store import canonical_media_url
from services.story_access import (
    require_owned_published_work,
    require_viewer_work_access,
    utc_timestamp,
)


async def _attach_interactions(db: Any, item: dict, viewer_user_id: int) -> dict:
    from services.story_interactions import interaction_projection

    projection = await interaction_projection(
        db, work_id=item["id"], requester_user_id=viewer_user_id
    )
    item.update(projection)
    return item


def encode_cursor(*, published_at: str, work_id: int, order: str = "desc") -> str:
    payload = json.dumps(
        {"v": 1, "published_at": published_at, "work_id": work_id, "order": order},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def decode_cursor(value: str, *, expected_order: str) -> tuple[str, int]:
    try:
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
        payload = json.loads(raw.decode("utf-8"))
        if payload.get("v") != 1 or payload.get("order") != expected_order:
            raise ValueError("cursor version or order mismatch")
        published_at = utc_timestamp(
            datetime.fromisoformat(str(payload["published_at"]).replace("Z", "+00:00"))
        )
        work_id = int(payload["work_id"])
        if work_id <= 0:
            raise ValueError("invalid work id")
        return published_at, work_id
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail="invalid cursor") from exc


def encode_owner_cursor(*, latest_published_at: str, owner_user_id: int) -> str:
    payload = json.dumps(
        {
            "v": 1,
            "kind": "owners",
            "latest_published_at": latest_published_at,
            "owner_user_id": owner_user_id,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def decode_owner_cursor(value: str) -> tuple[str, int]:
    try:
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
        payload = json.loads(raw.decode("utf-8"))
        if payload.get("v") != 1 or payload.get("kind") != "owners":
            raise ValueError("cursor kind mismatch")
        latest = utc_timestamp(
            datetime.fromisoformat(
                str(payload["latest_published_at"]).replace("Z", "+00:00")
            )
        )
        owner_id = int(payload["owner_user_id"])
        if owner_id <= 0:
            raise ValueError("invalid owner id")
        return latest, owner_id
    except Exception as exc:
        raise HTTPException(status_code=400, detail="invalid cursor") from exc


async def _profile_avatar(db: Any, owner_user_id: int) -> Optional[str]:
    cursor = await db.execute(
        """
        SELECT character.reference_image_url, avatar.id AS avatar_asset_id
        FROM profile
        LEFT JOIN character_profiles AS character ON character.user_id = profile.id
        LEFT JOIN media_assets AS avatar
          ON avatar.id = profile.avatar_asset_id
         AND avatar.owner_user_id = profile.id
        WHERE profile.id = ?
        """,
        (owner_user_id,),
    )
    row = await cursor.fetchone()
    if not row:
        return None
    if row["reference_image_url"]:
        return row["reference_image_url"]
    if row["avatar_asset_id"]:
        return canonical_media_url(row["avatar_asset_id"])
    return None


async def _owner_brief(db: Any, owner_user_id: int) -> dict:
    cursor = await db.execute(
        "SELECT id, nickname FROM profile WHERE id = ?", (owner_user_id,)
    )
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="profile not found")
    return {
        "id": row["id"],
        "nickname": row["nickname"],
        "avatar_url": await _profile_avatar(db, owner_user_id),
    }


async def _published_assets(db: Any, work_id: int) -> list[dict]:
    cursor = await db.execute(
        """
        SELECT id, ordinal, asset_type, url, asset_id, text
        FROM work_assets
        WHERE work_id = ?
        ORDER BY ordinal ASC
        """,
        (work_id,),
    )
    return [dict(row) for row in await cursor.fetchall()]


def _feed_item(row: Any, owner: dict, assets: list[dict]) -> dict:
    return {
        "id": row["id"],
        "title": row["title"],
        "medium": row["medium"],
        "narrative_mode": row["narrative_mode"],
        "style": row["style"],
        "published_at": row["published_at"],
        "owner": owner,
        "assets": assets,
        "mine": bool(row["mine"]),
    }


async def story_feed(
    db: Any,
    *,
    viewer_user_id: int,
    page_size: int,
    cursor: Optional[str],
) -> dict:
    cursor_clause = ""
    params: list[Any] = [viewer_user_id, viewer_user_id, viewer_user_id]
    if cursor is not None:
        cursor_published_at, cursor_work_id = decode_cursor(
            cursor, expected_order="desc"
        )
        cursor_clause = """
          AND (work.published_at < ?
               OR (work.published_at = ? AND work.id < ?))
        """
        params.extend([cursor_published_at, cursor_published_at, cursor_work_id])
    params.append(page_size + 1)
    rows_cursor = await db.execute(
        f"""
        SELECT DISTINCT work.id, work.owner_user_id, work.title,
               work.medium, work.narrative_mode, work.style, work.published_at,
               CASE WHEN work.owner_user_id = ? THEN 1 ELSE 0 END AS mine
        FROM story_works AS work
        WHERE work.status = 'published'
          AND (
            work.owner_user_id = ?
            OR EXISTS (
              SELECT 1 FROM work_audience audience
              JOIN subscriptions subscription ON subscription.id = audience.subscription_id
              WHERE audience.work_id = work.id
                AND audience.status='active'
                AND subscription.status='active'
                AND subscription.owner_user_id=work.owner_user_id
                AND subscription.subscriber_user_id=?
            )
          )
          {cursor_clause}
        ORDER BY work.published_at DESC, work.id DESC
        LIMIT ?
        """,
        tuple(params),
    )
    rows = await rows_cursor.fetchall()
    has_more = len(rows) > page_size
    page_rows = rows[:page_size]
    items = []
    for row in page_rows:
        owner = await _owner_brief(db, row["owner_user_id"])
        assets = await _published_assets(db, row["id"])
        item = _feed_item(row, owner, assets)
        items.append(await _attach_interactions(db, item, viewer_user_id))

    next_cursor = None
    if has_more and page_rows:
        last = page_rows[-1]
        next_cursor = encode_cursor(
            published_at=last["published_at"], work_id=last["id"], order="desc"
        )
    return {"items": items, "next_cursor": next_cursor}


async def collected_story_owners(
    db: Any,
    *,
    viewer_user_id: int,
    cursor: Optional[str],
    page_size: int,
) -> dict:
    cursor_clause = ""
    params: list[Any] = [viewer_user_id]
    if cursor is not None:
        latest, owner_id = decode_owner_cursor(cursor)
        cursor_clause = """
          AND (MAX(work.published_at) < ?
               OR (MAX(work.published_at) = ? AND work.owner_user_id < ?))
        """
        params.extend([latest, latest, owner_id])
    params.append(page_size + 1)
    rows_cursor = await db.execute(
        f"""
        SELECT work.owner_user_id,
               MAX(work.published_at) AS latest_published_at,
               COUNT(*) AS story_count
        FROM story_works AS work
        WHERE work.status = 'published'
          AND EXISTS (
            SELECT 1 FROM work_audience AS audience
            JOIN subscriptions AS subscription
              ON subscription.id = audience.subscription_id
            WHERE audience.work_id = work.id
              AND audience.status = 'active'
              AND subscription.status = 'active'
              AND subscription.owner_user_id = work.owner_user_id
              AND subscription.subscriber_user_id = ?
          )
        GROUP BY work.owner_user_id
        HAVING 1=1 {cursor_clause}
        ORDER BY latest_published_at DESC, work.owner_user_id DESC
        LIMIT ?
        """,
        tuple(params),
    )
    rows = await rows_cursor.fetchall()
    has_more = len(rows) > page_size
    page_rows = rows[:page_size]
    items = []
    for row in page_rows:
        owner = await _owner_brief(db, row["owner_user_id"])
        latest_cursor = await db.execute(
            """
            SELECT work.id, work.title, work.style FROM story_works AS work
            WHERE work.status = 'published'
              AND work.owner_user_id = ?
              AND work.published_at = ?
              AND EXISTS (
                SELECT 1 FROM work_audience AS audience
                JOIN subscriptions AS subscription
                  ON subscription.id = audience.subscription_id
                WHERE audience.work_id = work.id
                  AND audience.status = 'active'
                  AND subscription.status = 'active'
                  AND subscription.owner_user_id = work.owner_user_id
                  AND subscription.subscriber_user_id = ?
              )
            ORDER BY work.id DESC LIMIT 1
            """,
            (row["owner_user_id"], row["latest_published_at"], viewer_user_id),
        )
        latest_work_row = await latest_cursor.fetchone()
        latest_work = None
        if latest_work_row:
            latest_work = {
                "id": latest_work_row["id"],
                "title": latest_work_row["title"],
                "style": latest_work_row["style"],
                "assets": await _published_assets(db, latest_work_row["id"]),
            }
        items.append(
            {
                "owner": owner,
                "story_count": row["story_count"],
                "latest_published_at": row["latest_published_at"],
                "latest_work": latest_work,
            }
        )

    next_cursor = None
    if has_more and page_rows:
        last = page_rows[-1]
        next_cursor = encode_owner_cursor(
            latest_published_at=last["latest_published_at"],
            owner_user_id=last["owner_user_id"],
        )
    return {"items": items, "next_cursor": next_cursor}


async def collected_story_detail(
    db: Any,
    *,
    viewer_user_id: int,
    owner_user_id: int,
    order: str,
    cursor: Optional[str],
    page_size: int,
) -> dict:
    cursor_clause = ""
    params: list[Any] = [owner_user_id, viewer_user_id]
    if cursor is not None:
        cursor_published_at, cursor_work_id = decode_cursor(
            cursor, expected_order=order
        )
        comparator = "<" if order == "desc" else ">"
        cursor_clause = f"""
          AND (work.published_at {comparator} ?
               OR (work.published_at = ? AND work.id {comparator} ?))
        """
        params.extend([cursor_published_at, cursor_published_at, cursor_work_id])
    params.append(page_size + 1)
    sort = "DESC" if order == "desc" else "ASC"
    rows_cursor = await db.execute(
        f"""
        SELECT work.id, work.owner_user_id, work.title,
               work.medium, work.narrative_mode, work.style, work.published_at,
               0 AS mine
        FROM story_works AS work
        WHERE work.status = 'published'
          AND work.owner_user_id = ?
          AND EXISTS (
            SELECT 1 FROM work_audience AS audience
            JOIN subscriptions AS subscription
              ON subscription.id = audience.subscription_id
            WHERE audience.work_id = work.id
              AND audience.status = 'active'
              AND subscription.status = 'active'
              AND subscription.owner_user_id = work.owner_user_id
              AND subscription.subscriber_user_id = ?
          )
          {cursor_clause}
        ORDER BY work.published_at {sort}, work.id {sort}
        LIMIT ?
        """,
        tuple(params),
    )
    rows = await rows_cursor.fetchall()
    has_more = len(rows) > page_size
    page_rows = rows[:page_size]
    owner = await _owner_brief(db, owner_user_id)
    items = []
    for row in page_rows:
        assets = await _published_assets(db, row["id"])
        items.append(_feed_item(row, owner, assets))

    next_cursor = None
    if has_more and page_rows:
        last = page_rows[-1]
        next_cursor = encode_cursor(
            published_at=last["published_at"], work_id=last["id"], order=order
        )
    return {"owner": owner, "items": items, "next_cursor": next_cursor}


async def published_work_detail(
    db: Any, *, viewer_user_id: int, work_id: int
) -> dict:
    cursor = await db.execute(
        "SELECT owner_user_id, status FROM story_works WHERE id = ?", (work_id,)
    )
    work = await cursor.fetchone()
    if not work or work["status"] != "published":
        raise HTTPException(status_code=404, detail="story work not found")
    if work["owner_user_id"] == viewer_user_id:
        row = await require_owned_published_work(db, viewer_user_id, work_id)
    else:
        row = await require_viewer_work_access(db, viewer_user_id, work_id)
    owner = await _owner_brief(db, row["owner_user_id"])
    assets = await _published_assets(db, row["id"])
    item = {
        "id": row["id"],
        "title": row["title"],
        "medium": row["medium"],
        "narrative_mode": row["narrative_mode"],
        "style": row["style"],
        "published_at": row["published_at"],
        "owner": owner,
        "assets": assets,
        "mine": row["owner_user_id"] == viewer_user_id,
    }
    return await _attach_interactions(db, item, viewer_user_id)
