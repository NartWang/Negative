from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field, field_validator, model_validator

from auth.dependencies import CurrentUser, get_current_user, require_same_origin
from database import get_db
from agents.image_agent import generate_character_master
from services.media_store import (
    SUPPORTED_UPLOAD_EXTENSIONS,
    MediaAsset,
    MediaNotFound,
    MediaStoreError,
    asset_file_path,
    canonical_media_url,
    legacy_file_path,
    legacy_url_is_owned,
    parse_canonical_media_url,
    require_owned_asset,
    staged_generated_media,
    store_generated_asset,
    store_generated_asset_preserving_source,
)
from services.generation_errors import (
    GenerationServiceError,
    raise_generation_http_error,
)
from services.character_cutout import cut_out_character_backdrop
from services.story_access import (
    revoke_subscription_access,
    utc_timestamp,
)


router = APIRouter(prefix="/api", tags=["story"])

INVITE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
INVITE_RAW_LENGTH = 16
INVITE_TTL = timedelta(days=7)


class CharacterProfileUpdate(BaseModel):
    source_photo_url: Optional[str] = Field(default=None, max_length=2_000)
    reference_image_url: Optional[str] = Field(default=None, max_length=2_000)
    character_description: Optional[str] = Field(default=None, max_length=2_000)
    nickname: Optional[str] = Field(default=None, max_length=24)
    display_action: Optional[str] = Field(default=None, max_length=32)
    source_type: Optional[str] = Field(default=None, max_length=32)


class CharacterMasterRequest(BaseModel):
    """Turn one authorized photo into a Q-version pixel character master."""

    source_photo_asset_id: Optional[str] = Field(default=None, max_length=64)
    source_photo_url: Optional[str] = Field(default=None, max_length=2_000)
    character_description: Optional[str] = Field(default=None, max_length=2_000)
    nickname: Optional[str] = Field(default=None, max_length=24)

    @model_validator(mode="after")
    def _require_a_photo(self):
        if not (self.source_photo_asset_id or self.source_photo_url):
            raise ValueError("a source photo is required")
        return self


class StoryWorkCreate(BaseModel):
    source_diary_id: Optional[int] = None
    source_fragment_ids: list[int] = Field(default_factory=list, max_length=50)
    source_image_asset_ids: list[str] = Field(default_factory=list, max_length=50)
    source_weekly_comic_ids: list[int] = Field(default_factory=list, max_length=50)
    selected_segments: list[str] = Field(default_factory=list, max_length=20)
    medium: Literal["picture_book", "comic", "motion_comic", "weekly"]
    narrative_mode: str = Field(min_length=1, max_length=80)
    style: str = Field(min_length=1, max_length=80)
    forbidden_content: Optional[str] = Field(default=None, max_length=2_000)
    title: Optional[str] = Field(default=None, max_length=120)

    @field_validator("selected_segments")
    @classmethod
    def validate_segments(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value if item and item.strip()]
        if not cleaned:
            raise ValueError("selected_segments is required")
        return cleaned


class SubscriptionInviteJoin(BaseModel):
    code: str


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(value: datetime) -> str:
    return value.isoformat()


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _generate_invite_code() -> tuple[str, str]:
    # 遵循 BE-SECRET-002 规范: use cryptographically secure randomness for invite tokens.
    compact = "".join(secrets.choice(INVITE_ALPHABET) for _ in range(INVITE_RAW_LENGTH))
    displayed = "-".join(compact[index : index + 4] for index in range(0, INVITE_RAW_LENGTH, 4))
    return compact, displayed


def _normalize_invite_code(value: str) -> Optional[str]:
    compact = value.strip().replace("-", "").upper()
    if len(compact) != INVITE_RAW_LENGTH:
        return None
    if any(character not in INVITE_ALPHABET for character in compact):
        return None
    return compact


def _hash_invite_code(compact: str) -> str:
    return hashlib.sha256(compact.encode("ascii")).hexdigest()


async def _profile_public(db, user_id: int) -> dict:
    cursor = await db.execute(
        """
        SELECT profile.id, profile.nickname, avatar.id AS avatar_asset_id
        FROM profile
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
    return {
        "id": row["id"],
        "nickname": row["nickname"],
        "avatar_url": canonical_media_url(row["avatar_asset_id"])
        if row["avatar_asset_id"]
        else None,
    }


async def _work_response(db, work_id: int, owner_user_id: int) -> dict:
    cursor = await db.execute(
        "SELECT * FROM story_works WHERE id = ? AND owner_user_id = ?",
        (work_id, owner_user_id),
    )
    work = await cursor.fetchone()
    if not work:
        raise HTTPException(status_code=404, detail="story work not found")
    cursor = await db.execute(
        "SELECT * FROM work_assets WHERE work_id = ? ORDER BY ordinal ASC",
        (work_id,),
    )
    result = dict(work)
    result["selected_segments"] = json.loads(result.pop("selected_segments_json"))
    result["assets"] = [dict(row) for row in await cursor.fetchall()]
    return result


def _unique_ordered(values: list) -> list:
    return list(dict.fromkeys(values))


async def _materialize_owned_source(
    db,
    user_id: int,
    *,
    asset_id: Optional[str],
    url: Optional[str],
    stage,
) -> MediaAsset:
    try:
        if asset_id:
            return await require_owned_asset(db, user_id, asset_id)
        if not url:
            raise HTTPException(status_code=409, detail="source media unavailable")
        return await store_generated_asset_preserving_source(
            db,
            user_id,
            url,
            stage=stage,
        )
    except (MediaStoreError, ValueError) as exc:
        raise HTTPException(
            status_code=409,
            detail="source media unavailable",
        ) from exc


async def _selected_fragment_assets(
    db,
    user_id: int,
    fragment_ids: list[int],
    stage,
    *,
    source_diary_date: Optional[str],
):
    ids = _unique_ordered(fragment_ids)
    if not ids:
        return []
    if source_diary_date is None:
        raise HTTPException(status_code=404, detail="source records not found")
    placeholders = ", ".join("?" for _ in ids)
    cursor = await db.execute(
        "SELECT id, photo_url, photo_asset_id FROM fragments "
        f"WHERE user_id = ? AND date = ? AND id IN ({placeholders})",
        (user_id, source_diary_date, *ids),
    )
    rows = {row["id"]: row for row in await cursor.fetchall()}
    if set(rows) != set(ids):
        raise HTTPException(status_code=404, detail="source records not found")

    assets: list[MediaAsset] = []
    for fragment_id in ids:
        row = rows[fragment_id]
        if row["photo_asset_id"] is None and row["photo_url"] is None:
            continue
        asset = await _materialize_owned_source(
            db,
            user_id,
            asset_id=row["photo_asset_id"],
            url=row["photo_url"],
            stage=stage,
        )
        if row["photo_asset_id"] is None:
            await db.execute(
                "UPDATE fragments SET photo_asset_id = ?, photo_url = ? "
                "WHERE id = ? AND user_id = ?",
                (asset.id, asset.url, fragment_id, user_id),
            )
        assets.append(asset)
    return assets


async def _selected_diary_image_assets(
    db,
    user_id: int,
    source_diary_id: Optional[int],
    asset_ids: list[str],
):
    ids = _unique_ordered(asset_ids)
    if not ids:
        return []
    if source_diary_id is None:
        raise HTTPException(status_code=404, detail="source records not found")
    placeholders = ", ".join("?" for _ in ids)
    cursor = await db.execute(
        "SELECT image.asset_id FROM images AS image "
        "JOIN diaries AS diary ON diary.id = image.diary_id "
        "WHERE diary.id = ? AND diary.user_id = ? AND image.kept = 1 "
        f"AND image.asset_id IN ({placeholders})",
        (source_diary_id, user_id, *ids),
    )
    rows = {row["asset_id"] for row in await cursor.fetchall()}
    if rows != set(ids):
        raise HTTPException(status_code=404, detail="source records not found")
    assets = []
    for asset_id in ids:
        try:
            assets.append(await require_owned_asset(db, user_id, asset_id))
        except MediaStoreError as exc:
            raise HTTPException(
                status_code=409,
                detail="source media unavailable",
            ) from exc
    return assets


async def _selected_weekly_assets(db, user_id: int, comic_ids: list[int], stage):
    ids = _unique_ordered(comic_ids)
    if not ids:
        return []
    placeholders = ", ".join("?" for _ in ids)
    cursor = await db.execute(
        "SELECT id, url, asset_id FROM weekly_comics "
        f"WHERE user_id = ? AND id IN ({placeholders})",
        (user_id, *ids),
    )
    rows = {row["id"]: row for row in await cursor.fetchall()}
    if set(rows) != set(ids):
        raise HTTPException(status_code=404, detail="source records not found")

    assets: list[MediaAsset] = []
    for comic_id in ids:
        row = rows[comic_id]
        asset = await _materialize_owned_source(
            db,
            user_id,
            asset_id=row["asset_id"],
            url=row["url"],
            stage=stage,
        )
        if row["asset_id"] is None:
            await db.execute(
                "UPDATE weekly_comics SET asset_id = ?, url = ? "
                "WHERE id = ? AND user_id = ?",
                (asset.id, asset.url, comic_id, user_id),
            )
        assets.append(asset)
    return assets


EMPTY_CHARACTER_PROFILE: dict[str, Any] = {
    "source_photo_url": None,
    "reference_image_url": None,
    "character_description": "",
    "nickname": "",
    "display_action": None,
    "source_type": "",
    "version": 0,
    "created_at": None,
    "updated_at": None,
}


@router.get("/character-profile")
async def get_character_profile(user: CurrentUser = Depends(get_current_user)):
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM character_profiles WHERE user_id = ?",
            (user.id,),
        )
        row = await cursor.fetchone()
        if row:
            return dict(row)
        return {"user_id": user.id, **EMPTY_CHARACTER_PROFILE}
    finally:
        await db.close()


async def _save_character_profile(
    db: Any,
    user_id: int,
    data: dict[str, Any],
    *,
    commit: bool = True,
) -> dict[str, Any]:
    """Merge `data` into the stored character and return the saved row.

    Partial updates must not wipe the rest of the character: renaming the
    character keeps its artwork, switching artwork keeps its name.
    """
    current = await db.execute(
        "SELECT * FROM character_profiles WHERE user_id = ?",
        (user_id,),
    )
    row = await current.fetchone()
    stored = dict(row) if row else dict(EMPTY_CHARACTER_PROFILE)
    merged = {
        field: data[field] if field in data else stored.get(field)
        for field in (
            "source_photo_url",
            "reference_image_url",
            "character_description",
            "nickname",
            "display_action",
            "source_type",
        )
    }
    for field in ("character_description", "nickname", "source_type"):
        merged[field] = merged[field] or ""
    next_version = (row["version"] + 1) if row else 1
    now = _timestamp(_utc_now())
    await db.execute(
        """
        INSERT INTO character_profiles (
            user_id, source_photo_url, reference_image_url,
            character_description, nickname, display_action, source_type,
            version, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            source_photo_url = excluded.source_photo_url,
            reference_image_url = excluded.reference_image_url,
            character_description = excluded.character_description,
            nickname = excluded.nickname,
            display_action = excluded.display_action,
            source_type = excluded.source_type,
            version = excluded.version,
            updated_at = excluded.updated_at
        """,
        (
            user_id,
            merged["source_photo_url"],
            merged["reference_image_url"],
            merged["character_description"],
            merged["nickname"],
            merged["display_action"],
            merged["source_type"],
            next_version,
            now,
            now,
        ),
    )
    if commit:
        await db.commit()
    cursor = await db.execute(
        "SELECT * FROM character_profiles WHERE user_id = ?",
        (user_id,),
    )
    return dict(await cursor.fetchone())


@router.put("/character-profile")
async def update_character_profile(
    payload: CharacterProfileUpdate,
    _: None = Depends(require_same_origin),
    user: CurrentUser = Depends(get_current_user),
):
    db = await get_db()
    try:
        return await _save_character_profile(
            db, user.id, payload.model_dump(exclude_unset=True)
        )
    finally:
        await db.close()


async def _read_owned_photo(db: Any, user_id: int, payload: CharacterMasterRequest):
    """Resolve the request's photo to owned bytes, never trusting a raw path."""
    asset_id = payload.source_photo_asset_id or parse_canonical_media_url(
        payload.source_photo_url
    )
    if asset_id:
        asset = await require_owned_asset(db, user_id, asset_id)
        return asset_file_path(asset).read_bytes(), asset.mime_type, asset.url

    url = (payload.source_photo_url or "").strip()
    path = legacy_file_path(url)
    if not await legacy_url_is_owned(db, user_id, url):
        raise MediaNotFound("media not found")
    mime_type = SUPPORTED_UPLOAD_EXTENSIONS.get(path.suffix.lower(), "image/png")
    return path.read_bytes(), mime_type, url


@router.post("/character-profile/generate")
async def generate_character_master_asset(
    payload: CharacterMasterRequest,
    _: None = Depends(require_same_origin),
    user: CurrentUser = Depends(get_current_user),
):
    """Translate the user's authorized photo into a pixel character master.

    The photo is read from the caller's own media, sent once to the image
    service, and the returned artwork is stored as a new owned asset that
    becomes the character's `reference_image_url`.
    """
    db = await get_db()
    try:
        try:
            photo, mime_type, photo_url = await _read_owned_photo(db, user.id, payload)
        except MediaStoreError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        try:
            source = await generate_character_master(
                photo, mime_type, payload.character_description
            )
        except GenerationServiceError as exc:
            raise_generation_http_error(exc, service="image")

        async with staged_generated_media(db) as media_stage:
            try:
                # The upstream returns the sprite on a flat white plate; presets
                # are transparent, so cut the plate out before it is stored.
                asset = await store_generated_asset(
                    db,
                    user.id,
                    source,
                    stage=media_stage,
                    transform=cut_out_character_backdrop,
                )
            except MediaStoreError as exc:
                raise HTTPException(status_code=502, detail=str(exc)) from exc
            saved = await _save_character_profile(
                db,
                user.id,
                {
                    "reference_image_url": asset.url,
                    "source_photo_url": photo_url,
                    "character_description": payload.character_description or "",
                    "nickname": payload.nickname or "",
                    "display_action": None,
                    "source_type": "photo_generated",
                },
                commit=False,
            )
        return saved
    finally:
        await db.close()


@router.get("/story/works")
async def list_story_works(user: CurrentUser = Depends(get_current_user)):
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT id FROM story_works WHERE owner_user_id = ? ORDER BY created_at DESC, id DESC",
            (user.id,),
        )
        rows = await cursor.fetchall()
        return [await _work_response(db, row["id"], user.id) for row in rows]
    finally:
        await db.close()


@router.post("/story/works", status_code=201)
async def create_story_work(
    payload: StoryWorkCreate,
    _: None = Depends(require_same_origin),
    user: CurrentUser = Depends(get_current_user),
):
    db = await get_db()
    try:
        async with staged_generated_media(db) as media_stage:
            diary = None
            if payload.source_diary_id is not None:
                cursor = await db.execute(
                    "SELECT id, date, text, draft_text FROM diaries "
                    "WHERE id = ? AND user_id = ?",
                    (payload.source_diary_id, user.id),
                )
                diary = await cursor.fetchone()
                if not diary:
                    raise HTTPException(status_code=404, detail="diary not found")

            fragment_assets = await _selected_fragment_assets(
                db,
                user.id,
                payload.source_fragment_ids,
                media_stage,
                source_diary_date=diary["date"] if diary else None,
            )
            diary_assets = await _selected_diary_image_assets(
                db,
                user.id,
                payload.source_diary_id,
                payload.source_image_asset_ids,
            )
            weekly_assets = await _selected_weekly_assets(
                db,
                user.id,
                payload.source_weekly_comic_ids,
                media_stage,
            )

            diary_text = (
                (diary["text"] or diary["draft_text"] or "").strip()
                if diary
                else ""
            )
            selected = payload.selected_segments
            title = payload.title or (
                f"{diary['date']} 的故事" if diary else "未命名故事"
            )
            render_prompt = (
                f"medium={payload.medium}; narrative_mode={payload.narrative_mode}; "
                f"style={payload.style}; forbidden={payload.forbidden_content or ''}"
            )
            cursor = await db.execute(
                """
                INSERT INTO story_works (
                    owner_user_id, source_diary_id, title, medium, narrative_mode,
                    style, selected_segments_json, forbidden_content,
                    render_prompt, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'ready')
                """,
                (
                    user.id,
                    payload.source_diary_id,
                    title,
                    payload.medium,
                    payload.narrative_mode,
                    payload.style,
                    _canonical_json(selected),
                    payload.forbidden_content,
                    render_prompt,
                ),
            )
            work_id = cursor.lastrowid
            await db.execute(
                """
                INSERT INTO work_assets (work_id, ordinal, asset_type, text, prompt)
                VALUES (?, 0, 'text', ?, ?)
                """,
                (work_id, "\n".join(selected) or diary_text, render_prompt),
            )
            ordinal = 1
            for asset in [*fragment_assets, *diary_assets, *weekly_assets]:
                await db.execute(
                    """
                    INSERT INTO work_assets (
                        work_id, ordinal, asset_type, url, asset_id, prompt
                    ) VALUES (?, ?, 'image', ?, ?, ?)
                    """,
                    (work_id, ordinal, asset.url, asset.id, render_prompt),
                )
                ordinal += 1
        return await _work_response(db, work_id, user.id)
    finally:
        await db.close()


@router.delete("/story/works/{work_id}", status_code=204)
async def delete_story_work(
    work_id: int,
    _: None = Depends(require_same_origin),
    user: CurrentUser = Depends(get_current_user),
):
    db = await get_db()
    try:
        cursor = await db.execute(
            "DELETE FROM story_works WHERE id = ? AND owner_user_id = ?",
            (work_id, user.id),
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="story work not found")
        await db.commit()
        return Response(status_code=204)
    finally:
        await db.close()


@router.post("/subscription-invites", status_code=201)
async def create_subscription_invite(
    _: None = Depends(require_same_origin),
    user: CurrentUser = Depends(get_current_user),
):
    compact, displayed = _generate_invite_code()
    invite_id = str(uuid4())
    expires_at = _timestamp(_utc_now() + INVITE_TTL)
    db = await get_db()
    try:
        await db.execute(
            """
            INSERT INTO subscription_invites (id, owner_user_id, token_hash, expires_at)
            VALUES (?, ?, ?, ?)
            """,
            (invite_id, user.id, _hash_invite_code(compact), expires_at),
        )
        await db.commit()
        return {"id": invite_id, "code": displayed, "expires_at": expires_at}
    finally:
        await db.close()


@router.post("/subscription-invites/join", status_code=201)
async def join_subscription_invite(
    payload: SubscriptionInviteJoin,
    _: None = Depends(require_same_origin),
    user: CurrentUser = Depends(get_current_user),
):
    compact = _normalize_invite_code(payload.code)
    if compact is None:
        raise HTTPException(status_code=409, detail="invite unavailable")
    token_hash = _hash_invite_code(compact)
    db = await get_db()
    try:
        await db.execute("BEGIN IMMEDIATE")
        cursor = await db.execute(
            """
            SELECT * FROM subscription_invites
            WHERE token_hash = ?
              AND revoked_at IS NULL
              AND accepted_at IS NULL
            """,
            (token_hash,),
        )
        invite = await cursor.fetchone()
        if not invite:
            await db.rollback()
            raise HTTPException(status_code=409, detail="invite unavailable")
        if _parse_timestamp(invite["expires_at"]) <= _utc_now():
            await db.rollback()
            raise HTTPException(status_code=409, detail="invite unavailable")
        if invite["owner_user_id"] == user.id:
            await db.rollback()
            raise HTTPException(status_code=409, detail="cannot subscribe to self")

        now = _timestamp(_utc_now())
        await db.execute(
            "UPDATE subscription_invites SET accepted_by_user_id = ?, accepted_at = ? WHERE id = ?",
            (user.id, now, invite["id"]),
        )
        cursor = await db.execute(
            """
            INSERT INTO subscriptions (owner_user_id, subscriber_user_id, status)
            VALUES (?, ?, 'active')
            ON CONFLICT(owner_user_id, subscriber_user_id) DO UPDATE SET
                status = 'active',
                revoked_at = NULL
            RETURNING *
            """,
            (invite["owner_user_id"], user.id),
        )
        subscription = dict(await cursor.fetchone())
        await db.commit()
        subscription["owner"] = await _profile_public(db, subscription["owner_user_id"])
        subscription["subscriber"] = await _profile_public(db, subscription["subscriber_user_id"])
        return subscription
    except HTTPException:
        raise
    except Exception:
        await db.rollback()
        raise
    finally:
        await db.close()


@router.get("/subscriptions/following")
async def list_following(user: CurrentUser = Depends(get_current_user)):
    db = await get_db()
    try:
        cursor = await db.execute(
            """
            SELECT * FROM subscriptions
            WHERE subscriber_user_id = ? AND status = 'active'
            ORDER BY created_at DESC
            """,
            (user.id,),
        )
        rows = []
        for row in await cursor.fetchall():
            item = dict(row)
            item["owner"] = await _profile_public(db, item["owner_user_id"])
            rows.append(item)
        return rows
    finally:
        await db.close()


@router.get("/subscriptions/audience")
async def list_audience(user: CurrentUser = Depends(get_current_user)):
    db = await get_db()
    try:
        cursor = await db.execute(
            """
            SELECT * FROM subscriptions
            WHERE owner_user_id = ? AND status = 'active'
            ORDER BY created_at DESC
            """,
            (user.id,),
        )
        rows = []
        for row in await cursor.fetchall():
            item = dict(row)
            item["subscriber"] = await _profile_public(db, item["subscriber_user_id"])
            rows.append(item)
        return rows
    finally:
        await db.close()


@router.delete("/subscriptions/{subscription_id}", status_code=204)
async def delete_subscription(
    subscription_id: int,
    _: None = Depends(require_same_origin),
    user: CurrentUser = Depends(get_current_user),
):
    db = await get_db()
    try:
        await db.execute("BEGIN IMMEDIATE")
        await revoke_subscription_access(
            db,
            subscription_id=subscription_id,
            requester_user_id=user.id,
            now=utc_timestamp(),
        )
        await db.commit()
        return Response(status_code=204)
    except HTTPException:
        await db.rollback()
        raise
    except Exception:
        await db.rollback()
        raise
    finally:
        await db.close()
