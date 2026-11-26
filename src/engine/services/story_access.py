from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import HTTPException

from services.media_store import canonical_media_url


def utc_timestamp(value: Optional[datetime] = None) -> str:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).isoformat()


async def require_owned_ready_work(db: Any, owner_user_id: int, work_id: int):
    cursor = await db.execute(
        "SELECT * FROM story_works "
        "WHERE id = ? AND owner_user_id = ? AND status = 'ready'",
        (work_id, owner_user_id),
    )
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="story work not found")
    return row


async def require_owned_completed_work(db: Any, owner_user_id: int, work_id: int):
    cursor = await db.execute(
        "SELECT * FROM story_works WHERE id=? AND owner_user_id=?",
        (work_id, owner_user_id),
    )
    row = await cursor.fetchone()
    if not row or row["status"] not in {"ready", "published"}:
        raise HTTPException(status_code=404, detail="story work not found")
    return row


async def require_owned_published_work(db: Any, owner_user_id: int, work_id: int):
    cursor = await db.execute(
        "SELECT * FROM story_works "
        "WHERE id = ? AND owner_user_id = ? AND status = 'published'",
        (work_id, owner_user_id),
    )
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="story work not found")
    return row


async def validate_complete_subscription_set(
    db: Any, owner_user_id: int, subscription_ids: list[int]
) -> None:
    for subscription_id in subscription_ids:
        await require_active_subscription_for_owner(db, owner_user_id, subscription_id)


async def require_active_subscription_for_owner(
    db: Any,
    owner_user_id: int,
    subscription_id: int,
):
    cursor = await db.execute(
        "SELECT * FROM subscriptions "
        "WHERE id = ? AND owner_user_id = ? AND status = 'active'",
        (subscription_id, owner_user_id),
    )
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="subscription not found")
    return row


async def require_viewer_work_access(db: Any, viewer_user_id: int, work_id: int):
    cursor = await db.execute(
        """
        SELECT work.*, audience.id AS audience_id,
               subscription.id AS subscription_id,
               subscription.owner_user_id,
               subscription.subscriber_user_id
        FROM story_works AS work
        JOIN work_audience AS audience
          ON audience.work_id = work.id AND audience.status = 'active'
        JOIN subscriptions AS subscription
          ON subscription.id = audience.subscription_id
         AND subscription.status = 'active'
         AND subscription.owner_user_id = work.owner_user_id
        WHERE work.id = ?
          AND work.status = 'published'
          AND subscription.subscriber_user_id = ?
        """,
        (work_id, viewer_user_id),
    )
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="story work not found")
    return row


async def _subscription_rows_for_owner(db: Any, owner_user_id: int):
    cursor = await db.execute(
        """
        SELECT subscription.*, profile.nickname, avatar.id AS avatar_asset_id
        FROM subscriptions AS subscription
        JOIN profile ON profile.id = subscription.subscriber_user_id
        LEFT JOIN media_assets AS avatar
          ON avatar.id = profile.avatar_asset_id
         AND avatar.owner_user_id = profile.id
        WHERE subscription.owner_user_id = ?
          AND subscription.status = 'active'
        ORDER BY subscription.created_at DESC, subscription.id DESC
        """,
        (owner_user_id,),
    )
    return await cursor.fetchall()


def _subscription_item(row: Any, selected_ids: set[int]) -> dict:
    avatar_asset_id = row["avatar_asset_id"]
    return {
        "id": row["id"],
        "subscription_id": row["id"],
        "owner_user_id": row["owner_user_id"],
        "subscriber_user_id": row["subscriber_user_id"],
        "status": row["status"],
        "selected": row["id"] in selected_ids,
        "created_at": row["created_at"],
        "revoked_at": row["revoked_at"],
        "subscriber": {
            "id": row["subscriber_user_id"],
            "nickname": row["nickname"],
            "avatar_url": canonical_media_url(avatar_asset_id)
            if avatar_asset_id
            else None,
        },
    }


async def audience_state(db: Any, owner_user_id: int, work_id: int) -> dict:
    await require_owned_completed_work(db, owner_user_id, work_id)
    cursor = await db.execute(
        "SELECT subscription_id, status, granted_at, revoked_at "
        "FROM work_audience WHERE work_id = ?",
        (work_id,),
    )
    audience_rows = {
        row["subscription_id"]: row
        for row in await cursor.fetchall()
    }
    selected_ids = {
        subscription_id
        for subscription_id, row in audience_rows.items()
        if row["status"] == "active"
    }
    rows = await _subscription_rows_for_owner(db, owner_user_id)
    items = []
    for row in rows:
        item = _subscription_item(row, selected_ids)
        audience_row = audience_rows.get(row["id"])
        item["granted_at"] = audience_row["granted_at"] if audience_row else None
        item["audience_status"] = audience_row["status"] if audience_row else None
        item["audience_revoked_at"] = (
            audience_row["revoked_at"] if audience_row else None
        )
        items.append(item)
    return {"items": items}


async def _soft_delete_responses_for_subscriptions(
    db: Any,
    work_id: int,
    subscription_ids: list[int],
    now: str,
) -> None:
    if not subscription_ids:
        return
    placeholders = ", ".join("?" for _ in subscription_ids)
    await db.execute(
        "UPDATE work_responses "
        "SET deleted_at = ?, updated_at = ? "
        "WHERE work_id = ? "
        "AND deleted_at IS NULL "
        "AND author_user_id IN ("
        "  SELECT subscriber_user_id FROM subscriptions "
        f"  WHERE id IN ({placeholders})"
        ")",
        (now, now, work_id, *subscription_ids),
    )


async def replace_work_audience(
    db: Any,
    *,
    owner_user_id: int,
    work_id: int,
    subscription_ids: list[int],
    now: str,
    _skip_ownership_check: bool = False,
) -> dict:
    if not _skip_ownership_check:
        await require_owned_published_work(db, owner_user_id, work_id)
    target_ids = list(dict.fromkeys(subscription_ids))
    for subscription_id in target_ids:
        await require_active_subscription_for_owner(db, owner_user_id, subscription_id)

    cursor = await db.execute(
        "SELECT subscription_id, status, granted_at FROM work_audience "
        "WHERE work_id = ?",
        (work_id,),
    )
    existing = {row["subscription_id"]: row for row in await cursor.fetchall()}
    target_set = set(target_ids)
    active_existing = {
        subscription_id
        for subscription_id, row in existing.items()
        if row["status"] == "active"
    }

    revoked_ids = sorted(active_existing - target_set)
    if revoked_ids:
        placeholders = ", ".join("?" for _ in revoked_ids)
        await db.execute(
            "UPDATE work_audience "
            "SET status = 'revoked', revoked_at = ? "
            f"WHERE work_id = ? AND subscription_id IN ({placeholders}) "
            "AND status = 'active'",
            (now, work_id, *revoked_ids),
        )
        await _soft_delete_responses_for_subscriptions(db, work_id, revoked_ids, now)
        await _soft_delete_interactions_for_subscriptions(
            db, work_id, revoked_ids, now
        )

    for subscription_id in target_ids:
        row = existing.get(subscription_id)
        if row and row["status"] == "active":
            continue
        await db.execute(
            """
            INSERT INTO work_audience (
                work_id, subscription_id, status, granted_at, revoked_at, created_at
            ) VALUES (?, ?, 'active', ?, NULL, ?)
            ON CONFLICT(work_id, subscription_id) DO UPDATE SET
                status = 'active',
                granted_at = excluded.granted_at,
                revoked_at = NULL
            """,
            (work_id, subscription_id, now, now),
        )

    return await audience_state(db, owner_user_id, work_id)


async def revoke_subscription_access(
    db: Any,
    *,
    subscription_id: int,
    requester_user_id: int,
    now: str,
) -> None:
    cursor = await db.execute(
        "SELECT * FROM subscriptions "
        "WHERE id = ? AND (owner_user_id = ? OR subscriber_user_id = ?)",
        (subscription_id, requester_user_id, requester_user_id),
    )
    subscription = await cursor.fetchone()
    if not subscription:
        raise HTTPException(status_code=404, detail="subscription not found")

    cursor = await db.execute(
        "SELECT work_id FROM work_audience "
        "WHERE subscription_id = ? AND status = 'active'",
        (subscription_id,),
    )
    active_work_ids = [row["work_id"] for row in await cursor.fetchall()]
    await db.execute(
        "UPDATE subscriptions "
        "SET status = 'revoked', revoked_at = ? "
        "WHERE id = ?",
        (now, subscription_id),
    )
    await db.execute(
        "UPDATE work_audience "
        "SET status = 'revoked', revoked_at = ? "
        "WHERE subscription_id = ? AND status = 'active'",
        (now, subscription_id),
    )
    for work_id in active_work_ids:
        await db.execute(
            "UPDATE work_responses "
            "SET deleted_at = ?, updated_at = ? "
            "WHERE work_id = ? AND author_user_id = ? AND deleted_at IS NULL",
            (now, now, work_id, subscription["subscriber_user_id"]),
        )
        await db.execute(
            "UPDATE work_likes "
            "SET deleted_at = ? "
            "WHERE work_id = ? AND viewer_user_id = ? AND deleted_at IS NULL",
            (now, work_id, subscription["subscriber_user_id"]),
        )
        await db.execute(
            "UPDATE work_comments "
            "SET deleted_at = ? "
            "WHERE work_id = ? AND viewer_user_id = ? AND deleted_at IS NULL",
            (now, work_id, subscription["subscriber_user_id"]),
        )


async def publication_state(db: Any, owner_user_id: int, work_id: int) -> dict:
    """Small lifecycle patch; never a full story-work payload."""
    cursor = await db.execute(
        "SELECT id, status, published_at, unpublished_at FROM story_works "
        "WHERE id = ? AND owner_user_id = ?",
        (work_id, owner_user_id),
    )
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="story work not found")
    return {
        "work": {
            "id": row["id"],
            "status": row["status"],
            "published_at": row["published_at"],
            "unpublished_at": row["unpublished_at"],
        },
        "audience": await audience_state(db, owner_user_id, work_id),
    }


async def publish_work(
    db: Any,
    *,
    owner_user_id: int,
    work_id: int,
    subscription_ids: list[int],
    now: str,
) -> dict:
    work = await require_owned_completed_work(db, owner_user_id, work_id)
    if work["status"] == "published":
        raise HTTPException(status_code=409, detail="story work already published")
    target_ids = list(dict.fromkeys(subscription_ids))
    await validate_complete_subscription_set(db, owner_user_id, target_ids)
    await db.execute(
        "UPDATE story_works SET status='published', published_at=?, "
        "unpublished_at=NULL "
        "WHERE id=? AND owner_user_id=? AND status='ready'",
        (now, work_id, owner_user_id),
    )
    await replace_work_audience(
        db,
        owner_user_id=owner_user_id,
        work_id=work_id,
        subscription_ids=target_ids,
        now=now,
        _skip_ownership_check=True,
    )
    return await publication_state(db, owner_user_id, work_id)


async def unpublish_work(
    db: Any,
    *,
    owner_user_id: int,
    work_id: int,
    now: str,
) -> None:
    await require_owned_published_work(db, owner_user_id, work_id)
    await db.execute(
        "UPDATE story_works SET status='ready', unpublished_at=? "
        "WHERE id=? AND owner_user_id=? AND status='published'",
        (now, work_id, owner_user_id),
    )
    cursor = await db.execute(
        "SELECT subscription_id FROM work_audience "
        "WHERE work_id = ? AND status = 'active'",
        (work_id,),
    )
    active_subscription_ids = [row["subscription_id"] for row in await cursor.fetchall()]
    await db.execute(
        "UPDATE work_audience SET status='revoked', revoked_at=? "
        "WHERE work_id=? AND status='active'",
        (now, work_id),
    )
    await _soft_delete_responses_for_subscriptions(
        db, work_id, active_subscription_ids, now
    )
    await _soft_delete_interactions_for_subscriptions(
        db, work_id, active_subscription_ids, now
    )


async def _soft_delete_interactions_for_subscriptions(
    db: Any,
    work_id: int,
    subscription_ids: list[int],
    now: str,
) -> None:
    if not subscription_ids:
        return
    placeholders = ", ".join("?" for _ in subscription_ids)
    await db.execute(
        "UPDATE work_likes "
        "SET deleted_at = ? "
        "WHERE work_id = ? AND deleted_at IS NULL "
        "AND viewer_user_id IN ("
        "  SELECT subscriber_user_id FROM subscriptions "
        f"  WHERE id IN ({placeholders})"
        ")",
        (now, work_id, *subscription_ids),
    )
    await db.execute(
        "UPDATE work_comments "
        "SET deleted_at = ? "
        "WHERE work_id = ? AND deleted_at IS NULL "
        "AND viewer_user_id IN ("
        "  SELECT subscriber_user_id FROM subscriptions "
        f"  WHERE id IN ({placeholders})"
        ")",
        (now, work_id, *subscription_ids),
    )
