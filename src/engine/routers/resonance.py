from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field, field_validator

from auth.dependencies import CurrentUser, get_current_user, require_same_origin
from database import get_db
from services.resonance_feed import (
    collected_story_detail,
    collected_story_owners,
    published_work_detail,
    story_feed,
)
from services.story_access import (
    audience_state,
    publish_work,
    replace_work_audience,
    require_owned_completed_work,
    require_owned_published_work,
    unpublish_work,
    utc_timestamp,
)
from services.story_interactions import (
    add_comment,
    interaction_projection,
    list_comments,
    owner_interaction_summary,
    set_like,
)


router = APIRouter(prefix="/api/story", tags=["resonance"])


class PublicationReplace(BaseModel):
    subscription_ids: list[int] = Field(default_factory=list, max_length=50)

    @field_validator("subscription_ids")
    @classmethod
    def validate_subscription_ids(cls, value: list[int]) -> list[int]:
        if any(item <= 0 for item in value):
            raise ValueError("subscription_ids must be positive")
        return value


class AudienceReplace(BaseModel):
    subscription_ids: list[int] = Field(default_factory=list, max_length=50)

    @field_validator("subscription_ids")
    @classmethod
    def validate_subscription_ids(cls, value: list[int]) -> list[int]:
        if any(item <= 0 for item in value):
            raise ValueError("subscription_ids must be positive")
        return value


@router.put("/works/{work_id}/publication")
async def put_publication(
    work_id: int,
    payload: PublicationReplace,
    _: None = Depends(require_same_origin),
    user: CurrentUser = Depends(get_current_user),
):
    db = await get_db()
    try:
        await db.execute("BEGIN IMMEDIATE")
        result = await publish_work(
            db,
            owner_user_id=user.id,
            work_id=work_id,
            subscription_ids=payload.subscription_ids,
            now=utc_timestamp(),
        )
        await db.commit()
        return result
    except Exception:
        await db.rollback()
        raise
    finally:
        await db.close()


@router.delete("/works/{work_id}/publication", status_code=204)
async def delete_publication(
    work_id: int,
    _: None = Depends(require_same_origin),
    user: CurrentUser = Depends(get_current_user),
):
    db = await get_db()
    try:
        await db.execute("BEGIN IMMEDIATE")
        await unpublish_work(
            db,
            owner_user_id=user.id,
            work_id=work_id,
            now=utc_timestamp(),
        )
        await db.commit()
        return Response(status_code=204)
    except Exception:
        await db.rollback()
        raise
    finally:
        await db.close()


@router.get("/feed")
async def get_story_feed(
    cursor: Optional[str] = None,
    page_size: int = Query(default=20, ge=1, le=50),
    user: CurrentUser = Depends(get_current_user),
):
    db = await get_db()
    try:
        return await story_feed(
            db,
            viewer_user_id=user.id,
            page_size=page_size,
            cursor=cursor,
        )
    finally:
        await db.close()


@router.get("/collections")
async def get_collections(
    cursor: Optional[str] = None,
    page_size: int = Query(default=20, ge=1, le=50),
    user: CurrentUser = Depends(get_current_user),
):
    db = await get_db()
    try:
        return await collected_story_owners(
            db, viewer_user_id=user.id, cursor=cursor, page_size=page_size
        )
    finally:
        await db.close()


@router.get("/collections/{owner_user_id}")
async def get_collection_detail(
    owner_user_id: int,
    order: Literal["asc", "desc"] = "desc",
    cursor: Optional[str] = None,
    page_size: int = Query(default=20, ge=1, le=50),
    user: CurrentUser = Depends(get_current_user),
):
    db = await get_db()
    try:
        return await collected_story_detail(
            db,
            viewer_user_id=user.id,
            owner_user_id=owner_user_id,
            order=order,
            cursor=cursor,
            page_size=page_size,
        )
    finally:
        await db.close()


@router.get("/published/{work_id}")
async def get_published_work(
    work_id: int,
    user: CurrentUser = Depends(get_current_user),
):
    db = await get_db()
    try:
        return await published_work_detail(
            db, viewer_user_id=user.id, work_id=work_id
        )
    finally:
        await db.close()


class CommentCreate(BaseModel):
    client_request_id: str = Field(min_length=1, max_length=128)
    body: str = Field(min_length=1, max_length=2000)
    viewer_user_id: Optional[int] = None

    @field_validator("body")
    @classmethod
    def validate_body(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("body is required")
        return cleaned


@router.put("/works/{work_id}/like")
async def put_like(
    work_id: int,
    _: None = Depends(require_same_origin),
    user: CurrentUser = Depends(get_current_user),
):
    db = await get_db()
    try:
        await db.execute("BEGIN IMMEDIATE")
        result = await set_like(
            db,
            work_id=work_id,
            viewer_user_id=user.id,
            liked=True,
            now=utc_timestamp(),
        )
        await db.commit()
        return result
    except Exception:
        await db.rollback()
        raise
    finally:
        await db.close()


@router.delete("/works/{work_id}/like")
async def delete_like(
    work_id: int,
    _: None = Depends(require_same_origin),
    user: CurrentUser = Depends(get_current_user),
):
    db = await get_db()
    try:
        await db.execute("BEGIN IMMEDIATE")
        result = await set_like(
            db,
            work_id=work_id,
            viewer_user_id=user.id,
            liked=False,
            now=utc_timestamp(),
        )
        await db.commit()
        return result
    except Exception:
        await db.rollback()
        raise
    finally:
        await db.close()


@router.get("/works/{work_id}/comments")
async def get_comments(
    work_id: int,
    user: CurrentUser = Depends(get_current_user),
):
    db = await get_db()
    try:
        items = await list_comments(
            db, work_id=work_id, requester_user_id=user.id
        )
        return {"items": items}
    finally:
        await db.close()


@router.post("/works/{work_id}/comments", status_code=201)
async def post_comment(
    work_id: int,
    payload: CommentCreate,
    _: None = Depends(require_same_origin),
    user: CurrentUser = Depends(get_current_user),
):
    db = await get_db()
    try:
        await db.execute("BEGIN IMMEDIATE")
        result = await add_comment(
            db,
            work_id=work_id,
            actor_user_id=user.id,
            viewer_user_id=payload.viewer_user_id,
            client_request_id=payload.client_request_id,
            body=payload.body,
            now=utc_timestamp(),
        )
        await db.commit()
        return result
    except Exception:
        await db.rollback()
        raise
    finally:
        await db.close()


@router.get("/interactions")
async def get_interactions(
    page_size: int = Query(default=20, ge=1, le=50),
    user: CurrentUser = Depends(get_current_user),
):
    db = await get_db()
    try:
        return await owner_interaction_summary(
            db, owner_user_id=user.id, page_size=page_size
        )
    finally:
        await db.close()


@router.get("/works/{work_id}/audience")
async def get_story_work_audience(
    work_id: int,
    user: CurrentUser = Depends(get_current_user),
):
    db = await get_db()
    try:
        await require_owned_completed_work(db, user.id, work_id)
        return await audience_state(db, user.id, work_id)
    finally:
        await db.close()


@router.put("/works/{work_id}/audience")
async def put_story_work_audience(
    work_id: int,
    payload: AudienceReplace,
    _: None = Depends(require_same_origin),
    user: CurrentUser = Depends(get_current_user),
):
    db = await get_db()
    try:
        await db.execute("BEGIN IMMEDIATE")
        await require_owned_published_work(db, user.id, work_id)
        result = await replace_work_audience(
            db,
            owner_user_id=user.id,
            work_id=work_id,
            subscription_ids=payload.subscription_ids,
            now=utc_timestamp(),
            _skip_ownership_check=True,
        )
        await db.commit()
        return result
    except Exception:
        await db.rollback()
        raise
    finally:
        await db.close()
