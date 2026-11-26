from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from auth.dependencies import get_current_user_id, require_same_origin
from database import get_db
from services.generation_quota import GenerationQuotaExceeded, quota_detail
from services.generation_slots import GenerationSlotConflict, conflict_detail
from services.story_workflow import (
    StoryWorkflowConflict,
    StoryWorkflowNotFound,
    StoryWorkflowValidationError,
    confirm_time_story_narrative,
    create_daily_picturebook_draft,
    create_time_story_draft,
    duplicate_daily_picturebook_draft,
    generate_time_story_narrative,
    generate_time_story_storylines,
    get_story_work_resume,
    list_draft_story_works,
    replace_daily_picturebook_sources,
    replace_time_story_sources,
    start_work_picturebook_generation,
    update_daily_picturebook_draft_metadata,
)
from routers.picturebook import _job_payload, _spawn as _spawn_picturebook_job


router = APIRouter(prefix="/api/story/works", tags=["story-workflow"])


class DraftCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["daily_picturebook", "time_story"]
    source_diary_ids: Optional[list[int]] = Field(default=None, min_length=1, max_length=64)
    selected_segments: Optional[list[str]] = Field(default=None, max_length=20)
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    source_start_date: Optional[str] = None
    source_end_date: Optional[str] = None
    title: Optional[str] = Field(default=None, min_length=1, max_length=120)
    style: str = Field(min_length=1, max_length=80)

    def resolved_start_date(self) -> Optional[str]:
        return self.source_start_date or self.start_date

    def resolved_end_date(self) -> Optional[str]:
        return self.source_end_date or self.end_date

    @field_validator("source_diary_ids")
    @classmethod
    def clean_source_diary_ids(cls, value: Optional[list[int]]) -> Optional[list[int]]:
        if value is None:
            return value
        if any(item <= 0 for item in value):
            raise ValueError("source diary id is invalid")
        return value

    @field_validator("selected_segments")
    @classmethod
    def clean_selected_segments(cls, value: Optional[list[str]]) -> Optional[list[str]]:
        if value is None:
            return value
        cleaned = [item.strip() for item in value if item and item.strip()]
        return cleaned

    @field_validator("title", "style")
    @classmethod
    def clean_strings(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        return value.strip()

    @model_validator(mode="after")
    def validate_kind_sources(self):
        if self.kind == "daily_picturebook":
            if (
                self.source_diary_ids is None
                or len(self.source_diary_ids) != 1
                or not self.selected_segments
            ):
                raise ValueError("daily picturebook requires one diary and selected segments")
            if (
                self.start_date is not None
                or self.end_date is not None
                or self.source_start_date is not None
                or self.source_end_date is not None
            ):
                raise ValueError("daily picturebook does not accept a date range")
        else:
            has_ids = bool(self.source_diary_ids)
            start = self.resolved_start_date()
            end = self.resolved_end_date()
            if self.start_date and self.source_start_date and self.start_date != self.source_start_date:
                raise ValueError("time story date range is inconsistent")
            if self.end_date and self.source_end_date and self.end_date != self.source_end_date:
                raise ValueError("time story date range is inconsistent")
            has_range = start is not None or end is not None
            if has_range and (start is None or end is None):
                raise ValueError("time story date range requires start_date and end_date")
            if not has_ids and not has_range:
                raise ValueError("time story sources are required")
        return self


class SourceReplace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["daily_picturebook", "time_story"]
    source_diary_ids: Optional[list[int]] = Field(default=None, min_length=1, max_length=64)
    selected_segments: Optional[list[str]] = Field(default=None, max_length=20)
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    source_start_date: Optional[str] = None
    source_end_date: Optional[str] = None

    def resolved_start_date(self) -> Optional[str]:
        return self.source_start_date or self.start_date

    def resolved_end_date(self) -> Optional[str]:
        return self.source_end_date or self.end_date

    @field_validator("source_diary_ids")
    @classmethod
    def clean_source_diary_ids(cls, value: Optional[list[int]]) -> Optional[list[int]]:
        if value is None:
            return value
        if any(item <= 0 for item in value):
            raise ValueError("source diary id is invalid")
        return value

    @field_validator("selected_segments")
    @classmethod
    def clean_selected_segments(cls, value: Optional[list[str]]) -> Optional[list[str]]:
        if value is None:
            return value
        cleaned = [item.strip() for item in value if item and item.strip()]
        return cleaned

    @model_validator(mode="after")
    def validate_kind_sources(self):
        if self.kind == "daily_picturebook":
            if (
                self.source_diary_ids is None
                or len(self.source_diary_ids) != 1
                or not self.selected_segments
            ):
                raise ValueError("daily picturebook requires one diary and selected segments")
            if (
                self.start_date is not None
                or self.end_date is not None
                or self.source_start_date is not None
                or self.source_end_date is not None
            ):
                raise ValueError("daily picturebook does not accept a date range")
        else:
            has_ids = bool(self.source_diary_ids)
            start = self.resolved_start_date()
            end = self.resolved_end_date()
            if self.start_date and self.source_start_date and self.start_date != self.source_start_date:
                raise ValueError("time story date range is inconsistent")
            if self.end_date and self.source_end_date and self.end_date != self.source_end_date:
                raise ValueError("time story date range is inconsistent")
            has_range = start is not None or end is not None
            if has_range and (start is None or end is None):
                raise ValueError("time story date range requires start_date and end_date")
            if not has_ids and not has_range:
                raise ValueError("time story sources are required")
        return self


class DraftUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Optional[str] = Field(default=None, min_length=1, max_length=120)
    style: Optional[str] = Field(default=None, min_length=1, max_length=80)
    selected_storyline_id: Optional[str] = Field(default=None, min_length=1, max_length=120)
    narrative_text: Optional[str] = Field(default=None, min_length=1, max_length=12000)

    @field_validator("title", "style")
    @classmethod
    def clean_strings(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        return value.strip()

    @model_validator(mode="after")
    def require_one_field(self):
        if (
            self.title is None
            and self.style is None
            and self.selected_storyline_id is None
            and self.narrative_text is None
        ):
            raise ValueError("title, style, selected_storyline_id or narrative_text is required")
        return self


class PicturebookStart(BaseModel):
    model_config = ConfigDict(extra="forbid")

    replace: bool = False


class ReplaceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    replace: bool = False


def _raise_http(exc: Exception) -> None:
    if isinstance(exc, StoryWorkflowNotFound):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, GenerationSlotConflict):
        raise HTTPException(status_code=409, detail=conflict_detail(exc)) from exc
    if isinstance(exc, GenerationQuotaExceeded):
        raise HTTPException(status_code=403, detail=quota_detail(exc)) from exc
    if isinstance(exc, StoryWorkflowConflict):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, StoryWorkflowValidationError):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    raise exc


@router.post("/drafts", status_code=status.HTTP_201_CREATED)
async def create_draft(
    payload: DraftCreate,
    _: None = Depends(require_same_origin),
    user_id: int = Depends(get_current_user_id),
):
    db = await get_db()
    try:
        try:
            if payload.kind == "daily_picturebook":
                return await create_daily_picturebook_draft(
                    db,
                    owner_user_id=user_id,
                    diary_id=payload.source_diary_ids[0],
                    selected_segments=payload.selected_segments,
                    title=payload.title,
                    style=payload.style,
                )
            return await create_time_story_draft(
                db,
                owner_user_id=user_id,
                source_diary_ids=payload.source_diary_ids,
                start_date=payload.resolved_start_date(),
                end_date=payload.resolved_end_date(),
                title=payload.title,
                style=payload.style,
            )
        except Exception as exc:  # noqa: BLE001 - mapped below and still closes db.
            _raise_http(exc)
    finally:
        await db.close()


@router.get("/drafts")
async def list_drafts(user_id: int = Depends(get_current_user_id)):
    db = await get_db()
    try:
        return {"items": await list_draft_story_works(db, owner_user_id=user_id)}
    finally:
        await db.close()


@router.get("/{work_id}")
async def get_work(work_id: int, user_id: int = Depends(get_current_user_id)):
    db = await get_db()
    try:
        try:
            return await get_story_work_resume(
                db,
                owner_user_id=user_id,
                work_id=work_id,
            )
        except Exception as exc:  # noqa: BLE001 - mapped below and still closes db.
            _raise_http(exc)
    finally:
        await db.close()


@router.put("/{work_id}")
async def update_work(
    work_id: int,
    payload: DraftUpdate,
    _: None = Depends(require_same_origin),
    user_id: int = Depends(get_current_user_id),
):
    db = await get_db()
    try:
        try:
            return await update_daily_picturebook_draft_metadata(
                db,
                owner_user_id=user_id,
                work_id=work_id,
                title=payload.title,
                style=payload.style,
                selected_storyline_id=payload.selected_storyline_id,
                narrative_text=payload.narrative_text,
            )
        except Exception as exc:  # noqa: BLE001 - mapped below and still closes db.
            _raise_http(exc)
    finally:
        await db.close()


@router.put("/{work_id}/sources")
async def replace_sources(
    work_id: int,
    payload: SourceReplace,
    _: None = Depends(require_same_origin),
    user_id: int = Depends(get_current_user_id),
):
    db = await get_db()
    try:
        try:
            if payload.kind == "daily_picturebook":
                return await replace_daily_picturebook_sources(
                    db,
                    owner_user_id=user_id,
                    work_id=work_id,
                    diary_id=payload.source_diary_ids[0],
                    selected_segments=payload.selected_segments,
                )
            return await replace_time_story_sources(
                db,
                owner_user_id=user_id,
                work_id=work_id,
                source_diary_ids=payload.source_diary_ids,
                start_date=payload.resolved_start_date(),
                end_date=payload.resolved_end_date(),
            )
        except Exception as exc:  # noqa: BLE001 - mapped below and still closes db.
            _raise_http(exc)
    finally:
        await db.close()


@router.post("/{work_id}/storylines")
async def storylines(
    work_id: int,
    payload: ReplaceRequest = ReplaceRequest(),
    _: None = Depends(require_same_origin),
    user_id: int = Depends(get_current_user_id),
):
    db = await get_db()
    try:
        try:
            return await generate_time_story_storylines(
                db,
                owner_user_id=user_id,
                work_id=work_id,
                replace=payload.replace,
            )
        except Exception as exc:  # noqa: BLE001 - mapped below and still closes db.
            _raise_http(exc)
    finally:
        await db.close()


@router.post("/{work_id}/narrative")
async def narrative(
    work_id: int,
    payload: ReplaceRequest = ReplaceRequest(),
    _: None = Depends(require_same_origin),
    user_id: int = Depends(get_current_user_id),
):
    db = await get_db()
    try:
        try:
            return await generate_time_story_narrative(
                db,
                owner_user_id=user_id,
                work_id=work_id,
                replace=payload.replace,
            )
        except Exception as exc:  # noqa: BLE001 - mapped below and still closes db.
            _raise_http(exc)
    finally:
        await db.close()


@router.post("/{work_id}/confirm-narrative")
async def confirm_narrative(
    work_id: int,
    _: None = Depends(require_same_origin),
    user_id: int = Depends(get_current_user_id),
):
    db = await get_db()
    try:
        try:
            return await confirm_time_story_narrative(
                db,
                owner_user_id=user_id,
                work_id=work_id,
            )
        except Exception as exc:  # noqa: BLE001 - mapped below and still closes db.
            _raise_http(exc)
    finally:
        await db.close()


@router.post("/{work_id}/duplicate-draft", status_code=status.HTTP_201_CREATED)
async def duplicate_draft(
    work_id: int,
    _: None = Depends(require_same_origin),
    user_id: int = Depends(get_current_user_id),
):
    db = await get_db()
    try:
        try:
            return await duplicate_daily_picturebook_draft(
                db,
                owner_user_id=user_id,
                work_id=work_id,
            )
        except Exception as exc:  # noqa: BLE001 - mapped below and still closes db.
            _raise_http(exc)
    finally:
        await db.close()


@router.post("/{work_id}/picturebook")
async def start_picturebook(
    work_id: int,
    payload: PicturebookStart = PicturebookStart(),
    _: None = Depends(require_same_origin),
    user_id: int = Depends(get_current_user_id),
):
    db = await get_db()
    try:
        try:
            job = await start_work_picturebook_generation(
                db,
                owner_user_id=user_id,
                work_id=work_id,
                replace=payload.replace,
            )
            response = await _job_payload(db, job["id"], user_id)
        except Exception as exc:  # noqa: BLE001 - mapped below and still closes db.
            _raise_http(exc)
    finally:
        await db.close()

    await _spawn_picturebook_job(response["id"], user_id)
    return response
