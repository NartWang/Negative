from __future__ import annotations

from typing import Any, Optional
from uuid import uuid4

from fastapi import HTTPException

from services.media_store import canonical_media_url
from services.story_access import (
    require_owned_published_work,
    require_viewer_work_access,
)


async def _interaction_profile(db: Any, user_id: int) -> dict:
    cursor = await db.execute(
        """
        SELECT profile.id, profile.nickname,
               character.reference_image_url,
               avatar.id AS avatar_asset_id
        FROM profile
        LEFT JOIN character_profiles AS character ON character.user_id = profile.id
        LEFT JOIN media_assets AS avatar
          ON avatar.id = profile.avatar_asset_id
         AND avatar.owner_user_id = profile.id
        WHERE profile.id = ?
        """,
        (user_id,),
    )
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="profile not found")
    avatar_url = None
    if row["reference_image_url"]:
        avatar_url = row["reference_image_url"]
    elif row["avatar_asset_id"]:
        avatar_url = canonical_media_url(row["avatar_asset_id"])
    return {
        "id": row["id"],
        "nickname": row["nickname"],
        "avatar_url": avatar_url,
    }


def _comment_item(row: Any, author: dict, viewer: dict) -> dict:
    return {
        "id": row["id"],
        "work_id": row["work_id"],
        "viewer_user_id": row["viewer_user_id"],
        "author_user_id": row["author_user_id"],
        "author": author,
        "viewer": viewer,
        "body": row["body"],
        "created_at": row["created_at"],
    }


async def set_like(
    db: Any,
    *,
    work_id: int,
    viewer_user_id: int,
    liked: bool,
    now: str,
) -> dict:
    work = await require_viewer_work_access(db, viewer_user_id, work_id)
    if work["owner_user_id"] == viewer_user_id:
        raise HTTPException(status_code=404, detail="story work not found")
    cursor = await db.execute(
        "SELECT id, deleted_at FROM work_likes WHERE work_id=? AND viewer_user_id=?",
        (work_id, viewer_user_id),
    )
    existing = await cursor.fetchone()
    if liked:
        if existing is None:
            await db.execute(
                "INSERT INTO work_likes (id, work_id, viewer_user_id, created_at) "
                "VALUES (?, ?, ?, ?)",
                (str(uuid4()), work_id, viewer_user_id, now),
            )
        elif existing["deleted_at"] is not None:
            await db.execute(
                "UPDATE work_likes SET deleted_at=NULL, created_at=? WHERE id=?",
                (now, existing["id"]),
            )
    else:
        if existing is not None and existing["deleted_at"] is None:
            await db.execute(
                "UPDATE work_likes SET deleted_at=? WHERE id=?",
                (now, existing["id"]),
            )
    return {"liked": liked}


async def add_comment(
    db: Any,
    *,
    work_id: int,
    actor_user_id: int,
    viewer_user_id: Optional[int],
    client_request_id: str,
    body: str,
    now: str,
) -> dict:
    cursor = await db.execute(
        "SELECT owner_user_id, status FROM story_works WHERE id=?", (work_id,)
    )
    work = await cursor.fetchone()
    if not work or work["status"] != "published":
        raise HTTPException(status_code=404, detail="story work not found")

    if actor_user_id == work["owner_user_id"]:
        if viewer_user_id is None:
            raise HTTPException(status_code=422, detail="viewer_user_id is required")
        await require_viewer_work_access(db, viewer_user_id, work_id)
    else:
        await require_viewer_work_access(db, actor_user_id, work_id)
        if viewer_user_id not in (None, actor_user_id):
            raise HTTPException(status_code=404, detail="story work not found")
        viewer_user_id = actor_user_id

    comment_id = str(uuid4())
    try:
        await db.execute(
            """
            INSERT INTO work_comments (
                id, work_id, viewer_user_id, author_user_id,
                client_request_id, body, created_at, deleted_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL)
            """,
            (
                comment_id,
                work_id,
                viewer_user_id,
                actor_user_id,
                client_request_id,
                body,
                now,
            ),
        )
    except Exception as exc:
        # idempotent retry: return the original row
        if "UNIQUE" not in str(exc):
            raise
        cursor = await db.execute(
            "SELECT * FROM work_comments "
            "WHERE work_id=? AND author_user_id=? AND client_request_id=?",
            (work_id, actor_user_id, client_request_id),
        )
        row = await cursor.fetchone()
        if row is None:
            raise
        return await _serialize_comment(db, row)
    cursor = await db.execute(
        "SELECT * FROM work_comments WHERE id=?", (comment_id,)
    )
    return await _serialize_comment(db, await cursor.fetchone())


async def _serialize_comment(db: Any, row: Any) -> dict:
    author = await _interaction_profile(db, row["author_user_id"])
    viewer = await _interaction_profile(db, row["viewer_user_id"])
    return _comment_item(row, author, viewer)


async def list_comments(
    db: Any, *, work_id: int, requester_user_id: int
) -> list[dict]:
    cursor = await db.execute(
        "SELECT owner_user_id, status FROM story_works WHERE id=?", (work_id,)
    )
    work = await cursor.fetchone()
    if not work or work["status"] != "published":
        raise HTTPException(status_code=404, detail="story work not found")

    if requester_user_id == work["owner_user_id"]:
        await require_owned_published_work(db, requester_user_id, work_id)
        cursor = await db.execute(
            "SELECT * FROM work_comments WHERE work_id=? AND deleted_at IS NULL "
            "ORDER BY created_at ASC, id ASC",
            (work_id,),
        )
    else:
        await require_viewer_work_access(db, requester_user_id, work_id)
        cursor = await db.execute(
            "SELECT * FROM work_comments WHERE work_id=? AND viewer_user_id=? "
            "AND deleted_at IS NULL ORDER BY created_at ASC, id ASC",
            (work_id, requester_user_id),
        )
    return [await _serialize_comment(db, row) for row in await cursor.fetchall()]


async def interaction_projection(
    db: Any, *, work_id: int, requester_user_id: int
) -> dict:
    cursor = await db.execute(
        "SELECT owner_user_id, status FROM story_works WHERE id=?", (work_id,)
    )
    work = await cursor.fetchone()
    if not work or work["status"] != "published":
        raise HTTPException(status_code=404, detail="story work not found")

    if requester_user_id == work["owner_user_id"]:
        await require_owned_published_work(db, requester_user_id, work_id)
        like_cursor = await db.execute(
            "SELECT viewer_user_id FROM work_likes "
            "WHERE work_id=? AND deleted_at IS NULL ORDER BY created_at ASC",
            (work_id,),
        )
        likes = [
            await _interaction_profile(db, row["viewer_user_id"])
            for row in await like_cursor.fetchall()
        ]
        comments = await list_comments(
            db, work_id=work_id, requester_user_id=requester_user_id
        )
        audience_cursor = await db.execute(
            "SELECT COUNT(*) AS count FROM work_audience "
            "WHERE work_id=? AND status='active'",
            (work_id,),
        )
        audience_count = (await audience_cursor.fetchone())["count"]
        return {
            "likes": likes,
            "comments": comments,
            "audience_count": audience_count,
        }

    await require_viewer_work_access(db, requester_user_id, work_id)
    like_cursor = await db.execute(
        "SELECT 1 FROM work_likes WHERE work_id=? AND viewer_user_id=? "
        "AND deleted_at IS NULL",
        (work_id, requester_user_id),
    )
    liked_by_me = await like_cursor.fetchone() is not None
    comments = await list_comments(
        db, work_id=work_id, requester_user_id=requester_user_id
    )
    return {"liked_by_me": liked_by_me, "comments": comments}


async def owner_interaction_summary(
    db: Any, *, owner_user_id: int, page_size: int
) -> dict:
    like_cursor = await db.execute(
        """
        SELECT work_likes.id AS like_id, work_likes.work_id,
               work_likes.viewer_user_id, work_likes.created_at, work.title
        FROM work_likes
        JOIN story_works AS work ON work.id = work_likes.work_id
        WHERE work.owner_user_id = ? AND work.status = 'published'
          AND work_likes.deleted_at IS NULL
        ORDER BY work_likes.created_at DESC
        LIMIT ?
        """,
        (owner_user_id, page_size),
    )
    comment_cursor = await db.execute(
        """
        SELECT work_comments.id, work_comments.work_id,
               work_comments.viewer_user_id, work_comments.author_user_id,
               work_comments.body, work_comments.created_at, work.title
        FROM work_comments
        JOIN story_works AS work ON work.id = work_comments.work_id
        WHERE work.owner_user_id = ? AND work.status = 'published'
          AND work_comments.deleted_at IS NULL
        ORDER BY work_comments.created_at DESC
        LIMIT ?
        """,
        (owner_user_id, page_size),
    )
    items = []
    for row in await like_cursor.fetchall():
        person = await _interaction_profile(db, row["viewer_user_id"])
        items.append(
            {
                "kind": "like",
                "work_id": row["work_id"],
                "work_title": row["title"],
                "actor": person,
                "body": None,
                "created_at": row["created_at"],
            }
        )
    for row in await comment_cursor.fetchall():
        actor = await _interaction_profile(db, row["author_user_id"])
        items.append(
            {
                "kind": "comment",
                "work_id": row["work_id"],
                "work_title": row["title"],
                "actor": actor,
                "body": row["body"],
                "created_at": row["created_at"],
            }
        )
    items.sort(key=lambda item: item["created_at"], reverse=True)
    return {"items": items[:page_size]}
