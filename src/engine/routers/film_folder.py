"""底片夹读接口:全部端点只返回当前登录用户的数据。"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from auth.dependencies import get_current_user_id, require_same_origin
from database import get_db
from services import film_folder, motion_comic_drafts
from services.motion_comic_drafts import (
    DraftConflict,
    DraftNotFound,
    DraftValidationError,
)

router = APIRouter(prefix="/api/film-folder", tags=["film-folder"])


class DraftCreateRequest(BaseModel):
    source_kind: str
    source_id: int
    title: str = ""
    page_sequence: list[int] = Field(min_length=2, max_length=24)


class DraftUpdateRequest(BaseModel):
    title: Optional[str] = None
    page_sequence: Optional[list[int]] = Field(default=None, min_length=2, max_length=24)


def _raise_draft_http(exc: DraftNotFound | DraftValidationError | DraftConflict) -> None:
    if isinstance(exc, DraftNotFound):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, DraftConflict):
        detail = {"detail": str(exc)}
        if exc.existing_draft_id is not None:
            detail["existing_draft_id"] = exc.existing_draft_id
        raise HTTPException(status_code=409, detail=detail) from exc
    raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/picturebooks")
async def get_picturebook_collection(user_id: int = Depends(get_current_user_id)):
    db = await get_db()
    try:
        return await film_folder.list_picturebook_collection(db, user_id)
    finally:
        await db.close()


@router.get("/picturebooks/unfinished")
async def get_unfinished_picturebooks(user_id: int = Depends(get_current_user_id)):
    db = await get_db()
    try:
        return await film_folder.list_unfinished_picturebooks(db, user_id)
    finally:
        await db.close()


@router.get("/picturebooks/{source_kind}/{source_id}")
async def get_picturebook_detail(
    source_kind: str,
    source_id: int,
    user_id: int = Depends(get_current_user_id),
):
    if source_kind not in ("canonical_work", "historical_job"):
        raise HTTPException(status_code=404, detail="picturebook not found")
    db = await get_db()
    try:
        detail = await film_folder.get_picturebook_detail(
            db, user_id, source_kind, source_id
        )
        if detail is None:
            raise HTTPException(status_code=404, detail="picturebook not found")
        return detail
    finally:
        await db.close()


@router.delete("/picturebooks/{source_kind}/{source_id}", status_code=204)
async def delete_picturebook(
    source_kind: str,
    source_id: int,
    _: None = Depends(require_same_origin),
    user_id: int = Depends(get_current_user_id),
):
    db = await get_db()
    try:
        try:
            await film_folder.delete_picturebook(db, user_id, source_kind, source_id)
        except film_folder.PicturebookDeleteError as exc:
            message = str(exc)
            status_code = 409 if "generating" in message else 404
            raise HTTPException(status_code=status_code, detail=message) from exc
        return Response(status_code=204)
    finally:
        await db.close()


@router.get("/motion-comics")
async def get_motion_comic_collection(user_id: int = Depends(get_current_user_id)):
    db = await get_db()
    try:
        return await film_folder.list_motion_comic_collection(db, user_id)
    finally:
        await db.close()


@router.get("/motion-comics/unfinished")
async def get_unfinished_motion_comics(user_id: int = Depends(get_current_user_id)):
    db = await get_db()
    try:
        return await film_folder.list_unfinished_motion_comics(db, user_id)
    finally:
        await db.close()


@router.get("/time-stories")
async def get_time_stories(user_id: int = Depends(get_current_user_id)):
    db = await get_db()
    try:
        return await film_folder.list_time_stories(db, user_id)
    finally:
        await db.close()


# --------------------------------------------------------------------- drafts


@router.post("/motion-comics/drafts", status_code=201)
async def create_motion_comic_draft(
    payload: DraftCreateRequest,
    _: None = Depends(require_same_origin),
    user_id: int = Depends(get_current_user_id),
):
    db = await get_db()
    try:
        try:
            return await motion_comic_drafts.create_draft(
                db,
                user_id,
                source_kind=payload.source_kind,
                source_id=payload.source_id,
                title=payload.title,
                page_sequence=payload.page_sequence,
            )
        except (DraftNotFound, DraftValidationError, DraftConflict) as exc:
            _raise_draft_http(exc)
    finally:
        await db.close()


@router.get("/motion-comics/drafts/{draft_id}")
async def get_motion_comic_draft(
    draft_id: int,
    user_id: int = Depends(get_current_user_id),
):
    db = await get_db()
    try:
        try:
            return await motion_comic_drafts.get_draft(db, user_id, draft_id)
        except DraftNotFound as exc:
            _raise_draft_http(exc)
    finally:
        await db.close()


@router.put("/motion-comics/drafts/{draft_id}")
async def update_motion_comic_draft(
    draft_id: int,
    payload: DraftUpdateRequest,
    _: None = Depends(require_same_origin),
    user_id: int = Depends(get_current_user_id),
):
    db = await get_db()
    try:
        try:
            return await motion_comic_drafts.update_draft(
                db,
                user_id,
                draft_id,
                title=payload.title,
                page_sequence=payload.page_sequence,
            )
        except (DraftNotFound, DraftValidationError, DraftConflict) as exc:
            _raise_draft_http(exc)
    finally:
        await db.close()


@router.delete("/motion-comics/drafts/{draft_id}", status_code=204)
async def delete_motion_comic_draft(
    draft_id: int,
    _: None = Depends(require_same_origin),
    user_id: int = Depends(get_current_user_id),
):
    db = await get_db()
    try:
        try:
            await motion_comic_drafts.delete_draft(db, user_id, draft_id)
        except (DraftNotFound, DraftConflict) as exc:
            _raise_draft_http(exc)
        return Response(status_code=204)
    finally:
        await db.close()


# 注意:/motion-comics/drafts 系列已声明在上方,本参数化路由必须保持在最后,
# 避免 "drafts" 被当作 {video_job_id} 解析。
@router.get("/motion-comics/{video_job_id}")
async def get_motion_comic_detail(
    video_job_id: int,
    user_id: int = Depends(get_current_user_id),
):
    db = await get_db()
    try:
        detail = await film_folder.get_motion_comic_detail(db, user_id, video_job_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="motion comic not found")
        return detail
    finally:
        await db.close()
