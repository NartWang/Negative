from __future__ import annotations

import base64
import binascii
import hashlib
import json
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from auth.dependencies import CurrentUser, get_current_user, require_same_origin
from database import get_db
from routers.thermometer import (
    compute_temperature,
    load_temperature_inputs,
    parse_temperature_date,
)
from services.room_access import (
    get_active_membership,
    get_active_paired_membership,
    get_active_published_post,
    get_active_room_data,
    get_public_room_members,
)
from services.media_store import (
    MediaStoreError,
    asset_file_path,
    canonical_media_url,
    import_owned_legacy_local,
    require_owned_asset,
)


router = APIRouter(prefix="/api", tags=["rooms"])

INVITE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
INVITE_RAW_LENGTH = 16
INVITE_TTL = timedelta(hours=24)
FEED_COMMENTS_PER_POST = 50


class PublicRoomMemberResponse(BaseModel):
    id: int
    nickname: str
    avatar_url: Optional[str]
    role: Literal["owner", "member"]
    slot: Literal[1, 2]


class RoomResponse(BaseModel):
    id: str
    status: Literal["active"]
    state: Literal["waiting", "paired"]
    waiting: bool
    created_at: str
    members: list[PublicRoomMemberResponse]
    partner: Optional[PublicRoomMemberResponse]


class InviteResponse(BaseModel):
    code: str
    expires_at: str


class JoinInviteRequest(BaseModel):
    code: str


class NotePostRequest(BaseModel):
    body: str = Field(max_length=10_000)


class DiaryPostRequest(BaseModel):
    image_ids: list[int] = Field(default_factory=list, max_length=50)


class CommentRequest(BaseModel):
    client_request_id: str = Field(min_length=1, max_length=128)
    body: str = Field(max_length=2_000)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(value: datetime) -> str:
    return value.isoformat()


def _parse_timestamp(value: str) -> Optional[datetime]:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _generate_invite_code() -> tuple[str, str]:
    # 遵循 BE-SECRET-002 规范: use a cryptographically secure random source.
    compact = "".join(secrets.choice(INVITE_ALPHABET) for _ in range(INVITE_RAW_LENGTH))
    displayed = "-".join(
        compact[index : index + 4] for index in range(0, INVITE_RAW_LENGTH, 4)
    )
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


def _room_not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="room not found",
    )


def _invite_unavailable() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="invite unavailable",
    )


def _post_not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="post not found",
    )


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _sha256_json(value: object) -> tuple[str, str]:
    encoded = _canonical_json(value)
    return encoded, hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _encode_cursor(timestamp: str, item_id: str) -> str:
    raw = _canonical_json([timestamp, item_id]).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(value: str) -> tuple[str, str]:
    if not value or len(value) > 512 or "=" in value:
        raise HTTPException(status_code=400, detail="invalid cursor")
    try:
        padding = "=" * (-len(value) % 4)
        raw = base64.b64decode(
            value + padding,
            altchars=b"-_",
            validate=True,
        )
        decoded = json.loads(raw.decode("utf-8"))
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError):
        raise HTTPException(status_code=400, detail="invalid cursor") from None
    if (
        not isinstance(decoded, list)
        or len(decoded) != 2
        or not all(isinstance(item, str) for item in decoded)
    ):
        raise HTTPException(status_code=400, detail="invalid cursor")
    timestamp_value, item_id = decoded
    try:
        parsed_id = str(UUID(item_id))
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid cursor") from None
    parsed_time = _parse_timestamp(timestamp_value)
    if (
        parsed_id != item_id
        or parsed_time is None
        or _timestamp(parsed_time) != timestamp_value
    ):
        raise HTTPException(status_code=400, detail="invalid cursor")
    if _encode_cursor(timestamp_value, item_id) != value:
        raise HTTPException(status_code=400, detail="invalid cursor")
    return timestamp_value, item_id


async def _require_paired_room(db, user_id: int, room_id: str):
    membership = await get_active_paired_membership(db, user_id, room_id)
    if membership is None:
        raise _room_not_found()
    return membership


def _public_comment(row, viewer_user_id: int) -> dict:
    return {
        "id": row["id"],
        "author": {
            "nickname": row["nickname"],
            "avatar_url": (
                canonical_media_url(row["avatar_asset_id"])
                if row["avatar_asset_id"]
                else None
            ),
        },
        "body": row["body"],
        "created_at": row["created_at"],
        "mine": row["author_user_id"] == viewer_user_id,
    }


async def _post_responses(db, post_rows, viewer_user_id: int) -> list[dict]:
    rows = list(post_rows)
    if not rows:
        return []
    post_ids = [row["id"] for row in rows]
    author_ids = list(dict.fromkeys(row["author_user_id"] for row in rows))
    post_placeholders = ",".join("?" for _ in post_ids)
    author_placeholders = ",".join("?" for _ in author_ids)

    author_cursor = await db.execute(
        f"""
        SELECT profile.id, profile.nickname, avatar.id AS avatar_asset_id
        FROM profile
        LEFT JOIN media_assets AS avatar
          ON avatar.id = profile.avatar_asset_id
         AND avatar.owner_user_id = profile.id
        WHERE profile.id IN ({author_placeholders})
        """,
        author_ids,
    )
    authors = {
        row["id"]: {
            "nickname": row["nickname"],
            "avatar_url": (
                canonical_media_url(row["avatar_asset_id"])
                if row["avatar_asset_id"]
                else None
            ),
        }
        for row in await author_cursor.fetchall()
    }
    if any(author_id not in authors for author_id in author_ids):
        raise RuntimeError("room post author is missing")

    like_cursor = await db.execute(
        "SELECT post_id, COUNT(*) AS count, "
        "MAX(CASE WHEN user_id=? THEN 1 ELSE 0 END) AS liked "
        f"FROM post_likes WHERE post_id IN ({post_placeholders}) "
        "GROUP BY post_id",
        [viewer_user_id, *post_ids],
    )
    likes = {
        row["post_id"]: (row["count"], bool(row["liked"]))
        for row in await like_cursor.fetchall()
    }

    comment_cursor = await db.execute(
        f"""
        WITH ranked_comments AS (
            SELECT comment.id, comment.post_id, comment.author_user_id,
                   comment.body, comment.created_at, profile.nickname,
                   avatar.id AS avatar_asset_id,
                   COUNT(*) OVER (PARTITION BY comment.post_id) AS comment_count,
                   ROW_NUMBER() OVER (
                       PARTITION BY comment.post_id
                       ORDER BY comment.created_at DESC, comment.id DESC
                   ) AS comment_rank
            FROM post_comments AS comment
            JOIN profile ON profile.id = comment.author_user_id
            LEFT JOIN media_assets AS avatar
              ON avatar.id = profile.avatar_asset_id
             AND avatar.owner_user_id = profile.id
            WHERE comment.post_id IN ({post_placeholders})
              AND comment.deleted_at IS NULL
        )
        SELECT * FROM ranked_comments
        WHERE comment_rank <= ?
        ORDER BY post_id, created_at, id
        """,
        [*post_ids, FEED_COMMENTS_PER_POST],
    )
    comments_by_post = {post_id: [] for post_id in post_ids}
    comment_counts = {post_id: 0 for post_id in post_ids}
    for row in await comment_cursor.fetchall():
        comment_counts[row["post_id"]] = row["comment_count"]
        comments_by_post[row["post_id"]].append(
            _public_comment(row, viewer_user_id)
        )

    media_cursor = await db.execute(
        "SELECT post_id, asset_id FROM room_post_media "
        f"WHERE post_id IN ({post_placeholders}) ORDER BY post_id, ordinal",
        post_ids,
    )
    media_by_post = {post_id: [] for post_id in post_ids}
    for row in await media_cursor.fetchall():
        media_by_post[row["post_id"]].append(canonical_media_url(row["asset_id"]))

    results = []
    for post_row in rows:
        post_id = post_row["id"]
        like_count, liked_by_me = likes.get(post_id, (0, False))
        comments = comments_by_post[post_id]
        comment_count = comment_counts[post_id]
        mine = post_row["author_user_id"] == viewer_user_id
        result = {
            "id": post_id,
            "source_type": post_row["source_type"],
            "author": authors[post_row["author_user_id"]],
            "mine": mine,
            "snapshot": json.loads(post_row["snapshot_json"]),
            "media_urls": media_by_post[post_id],
            "published_at": post_row["published_at"],
            "like_count": like_count,
            "liked_by_me": liked_by_me,
            "comment_count": comment_count,
            "comments_truncated": comment_count > len(comments),
            "comments": comments,
        }
        if mine and post_row["source_id"] is not None:
            result["source_id"] = post_row["source_id"]
        results.append(result)
    return results


async def _post_response(db, post_row, viewer_user_id: int) -> dict:
    return (await _post_responses(db, [post_row], viewer_user_id))[0]


async def _active_source_post(db, room_id: str, source_type: str, source_id: int):
    cursor = await db.execute(
        "SELECT * FROM room_posts WHERE room_id=? AND source_type=? "
        "AND source_id=? AND status='published' AND revoked_at IS NULL",
        (room_id, source_type, source_id),
    )
    return await cursor.fetchone()


async def _rollback_imports(db, imported_assets: list) -> None:
    await db.rollback()
    for asset in reversed(imported_assets):
        try:
            asset_file_path(asset).unlink(missing_ok=True)
        except OSError:
            pass


async def _publication_asset(
    db,
    user_id: int,
    asset_id: Optional[str],
    url: str,
    imported_assets: list,
) -> tuple[str, str]:
    try:
        if asset_id:
            asset = await require_owned_asset(db, user_id, asset_id)
        else:
            asset = await import_owned_legacy_local(
                db,
                user_id,
                url,
                commit=False,
            )
            imported_assets.append(asset)
    except MediaStoreError as exc:
        raise HTTPException(
            status_code=400,
            detail="selected media cannot be published",
        ) from exc
    return asset.id, canonical_media_url(asset.id)


@router.get("/rooms/current", response_model=Optional[RoomResponse])
async def current_room(user: CurrentUser = Depends(get_current_user)):
    # 遵循 BE-AUTH-001 规范: identity comes only from the authenticated session.
    db = await get_db()
    try:
        return await get_active_room_data(db, user.id)
    finally:
        await db.close()


@router.post(
    "/rooms",
    response_model=RoomResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_room(
    _: None = Depends(require_same_origin),
    user: CurrentUser = Depends(get_current_user),
):
    # 遵循 BE-AUTH-003 规范: every room mutation applies the same-origin guard.
    db = await get_db()
    try:
        await db.execute("BEGIN IMMEDIATE")
        try:
            if await get_active_membership(db, user.id) is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="active room already exists",
                )

            room_id = str(uuid4())
            now = _timestamp(_utc_now())
            await db.execute(
                """
                INSERT INTO rooms (id, creator_user_id, status, created_at)
                VALUES (?, ?, 'active', ?)
                """,
                (room_id, user.id, now),
            )
            await db.execute(
                """
                INSERT INTO room_members
                    (room_id, user_id, role, slot, joined_at)
                VALUES (?, ?, 'owner', 1, ?)
                """,
                (room_id, user.id, now),
            )
            room = await get_active_room_data(db, user.id, room_id)
            if room is None:
                raise RuntimeError("created room failed structural validation")
            await db.commit()
        except HTTPException:
            await db.rollback()
            raise
        except sqlite3.IntegrityError as exc:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="active room already exists",
            ) from exc
        except Exception:
            await db.rollback()
            raise
    finally:
        await db.close()
    return room


@router.post(
    "/rooms/{room_id}/invites",
    response_model=InviteResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_invite(
    room_id: str,
    _: None = Depends(require_same_origin),
    user: CurrentUser = Depends(get_current_user),
):
    db = await get_db()
    try:
        await db.execute("BEGIN IMMEDIATE")
        try:
            membership = await get_active_membership(db, user.id, room_id)
            if membership is None or membership.room_status != "active":
                raise _room_not_found()
            # 遵循 SEC-AUTH-002 规范: only slot-1 owner may issue room capabilities.
            if membership.role != "owner" or membership.slot != 1:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="room owner required",
                )
            members = await get_public_room_members(db, room_id)
            if (
                members is None
                or len(members) != 1
                or members[0].id != user.id
                or membership.room_creator_user_id != user.id
            ):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="room is not waiting",
                )

            now = _utc_now()
            now_text = _timestamp(now)
            await db.execute(
                """
                UPDATE room_invites SET revoked_at = ?
                WHERE room_id = ? AND consumed_at IS NULL AND revoked_at IS NULL
                """,
                (now_text, room_id),
            )
            compact, displayed = _generate_invite_code()
            expires_at = _timestamp(now + INVITE_TTL)
            await db.execute(
                """
                INSERT INTO room_invites (
                    id, room_id, creator_user_id, code_hash,
                    expires_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid4()),
                    room_id,
                    user.id,
                    _hash_invite_code(compact),
                    expires_at,
                    now_text,
                ),
            )
            await db.commit()
        except HTTPException:
            await db.rollback()
            raise
        except sqlite3.IntegrityError as exc:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="invite could not be created",
            ) from exc
        except Exception:
            await db.rollback()
            raise
    finally:
        await db.close()
    return {"code": displayed, "expires_at": expires_at}


@router.post("/room-invites/join", response_model=RoomResponse)
async def join_room(
    payload: JoinInviteRequest,
    _: None = Depends(require_same_origin),
    user: CurrentUser = Depends(get_current_user),
):
    compact = _normalize_invite_code(payload.code)
    if compact is None:
        raise _invite_unavailable()

    db = await get_db()
    try:
        await db.execute("BEGIN IMMEDIATE")
        try:
            if await get_active_membership(db, user.id) is not None:
                raise _invite_unavailable()

            cursor = await db.execute(
                """
                SELECT invite.id, invite.room_id, invite.creator_user_id,
                       invite.expires_at, invite.consumed_at, invite.revoked_at,
                       room.status AS room_status,
                       room.creator_user_id AS room_creator_user_id
                FROM room_invites AS invite
                JOIN rooms AS room ON room.id = invite.room_id
                WHERE invite.code_hash = ?
                """,
                (_hash_invite_code(compact),),
            )
            invite = await cursor.fetchone()
            now = _utc_now()
            expires_at = _parse_timestamp(invite["expires_at"]) if invite else None
            if (
                invite is None
                or invite["consumed_at"] is not None
                or invite["revoked_at"] is not None
                or invite["room_status"] != "active"
                or expires_at is None
                or expires_at <= now
                or invite["creator_user_id"] == user.id
                or invite["room_creator_user_id"] != invite["creator_user_id"]
            ):
                raise _invite_unavailable()

            members = await get_public_room_members(db, invite["room_id"])
            if (
                members is None
                or len(members) != 1
                or members[0].role != "owner"
                or members[0].slot != 1
                or members[0].id != invite["creator_user_id"]
            ):
                raise _invite_unavailable()

            now_text = _timestamp(now)
            await db.execute(
                """
                INSERT INTO room_members
                    (room_id, user_id, role, slot, joined_at)
                VALUES (?, ?, 'member', 2, ?)
                """,
                (invite["room_id"], user.id, now_text),
            )
            consumed = await db.execute(
                """
                UPDATE room_invites
                SET consumed_at = ?, consumed_by_user_id = ?
                WHERE id = ? AND consumed_at IS NULL AND revoked_at IS NULL
                """,
                (now_text, user.id, invite["id"]),
            )
            if consumed.rowcount != 1:
                raise _invite_unavailable()
            await db.execute(
                """
                UPDATE room_invites SET revoked_at = ?
                WHERE room_id = ? AND id != ?
                  AND consumed_at IS NULL AND revoked_at IS NULL
                """,
                (now_text, invite["room_id"], invite["id"]),
            )
            room = await get_active_room_data(db, user.id, invite["room_id"])
            if room is None or room["state"] != "paired":
                raise _invite_unavailable()
            await db.commit()
        except HTTPException:
            await db.rollback()
            raise
        except sqlite3.IntegrityError as exc:
            await db.rollback()
            raise _invite_unavailable() from exc
        except Exception:
            await db.rollback()
            raise
    finally:
        await db.close()
    return room


@router.post("/rooms/{room_id}/leave", status_code=status.HTTP_204_NO_CONTENT)
async def leave_room(
    room_id: str,
    _: None = Depends(require_same_origin),
    user: CurrentUser = Depends(get_current_user),
):
    db = await get_db()
    try:
        await db.execute("BEGIN IMMEDIATE")
        try:
            membership = await get_active_membership(db, user.id, room_id)
            if membership is None or membership.room_status != "active":
                raise _room_not_found()

            now = _timestamp(_utc_now())
            closed = await db.execute(
                """
                UPDATE rooms SET status = 'closed', closed_at = ?
                WHERE id = ? AND status = 'active'
                """,
                (now, room_id),
            )
            if closed.rowcount != 1:
                raise _room_not_found()
            await db.execute(
                "UPDATE room_members SET left_at = ? "
                "WHERE room_id = ? AND left_at IS NULL",
                (now, room_id),
            )
            await db.execute(
                """
                UPDATE room_invites SET revoked_at = ?
                WHERE room_id = ? AND consumed_at IS NULL AND revoked_at IS NULL
                """,
                (now, room_id),
            )
            await db.commit()
        except HTTPException:
            await db.rollback()
            raise
        except Exception:
            await db.rollback()
            raise
    finally:
        await db.close()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/rooms/{room_id}/posts/notes",
    status_code=status.HTTP_201_CREATED,
)
async def create_note_post(
    room_id: str,
    payload: NotePostRequest,
    _: None = Depends(require_same_origin),
    user: CurrentUser = Depends(get_current_user),
):
    body = payload.body.strip()
    if not body:
        raise HTTPException(status_code=400, detail="note body is required")
    snapshot_json, snapshot_hash = _sha256_json({"body": body, "type": "note"})
    db = await get_db()
    try:
        await db.execute("BEGIN IMMEDIATE")
        try:
            await _require_paired_room(db, user.id, room_id)
            post_id = str(uuid4())
            published_at = _timestamp(_utc_now())
            await db.execute(
                """
                INSERT INTO room_posts (
                    id, room_id, author_user_id, source_type,
                    source_id, source_revision, snapshot_hash,
                    snapshot_json, status, published_at
                ) VALUES (?, ?, ?, 'note', NULL, NULL, ?, ?, 'published', ?)
                """,
                (
                    post_id,
                    room_id,
                    user.id,
                    snapshot_hash,
                    snapshot_json,
                    published_at,
                ),
            )
            post = await get_active_published_post(db, room_id, post_id)
            result = await _post_response(db, post, user.id)
            await db.commit()
        except HTTPException:
            await db.rollback()
            raise
        except Exception:
            await db.rollback()
            raise
    finally:
        await db.close()
    return result


@router.put("/rooms/{room_id}/posts/diaries/{diary_id}")
async def publish_diary_post(
    room_id: str,
    diary_id: int,
    payload: DiaryPostRequest,
    _: None = Depends(require_same_origin),
    user: CurrentUser = Depends(get_current_user),
):
    if len(payload.image_ids) != len(set(payload.image_ids)):
        raise HTTPException(status_code=400, detail="duplicate selected image")
    imported_assets: list = []
    db = await get_db()
    try:
        await db.execute("BEGIN IMMEDIATE")
        try:
            await _require_paired_room(db, user.id, room_id)
            cursor = await db.execute(
                "SELECT id, date, text, emotion_mode, status, confirmed_at, source "
                "FROM diaries WHERE id=? AND user_id=?",
                (diary_id, user.id),
            )
            diary = await cursor.fetchone()
            if diary is None:
                raise HTTPException(status_code=404, detail="diary not found")
            if diary["status"] != "confirmed":
                raise HTTPException(status_code=409, detail="diary is not confirmed")

            selected = []
            for image_id in payload.image_ids:
                cursor = await db.execute(
                    """
                    SELECT image.id, image.style, image.url, image.kept,
                           image.asset_id, image.created_at
                    FROM images AS image
                    JOIN diaries AS diary ON diary.id = image.diary_id
                    WHERE image.id=? AND image.diary_id=?
                      AND diary.user_id=? AND image.kept=1
                    """,
                    (image_id, diary_id, user.id),
                )
                image = await cursor.fetchone()
                if image is None:
                    raise HTTPException(
                        status_code=400,
                        detail="selected image is not a kept diary image",
                    )
                selected.append(image)

            revision_value = {
                "date": diary["date"],
                "text": diary["text"],
                "emotion_mode": diary["emotion_mode"],
                "status": diary["status"],
                "confirmed_at": diary["confirmed_at"],
                "source": diary["source"],
                "images": [
                    {
                        "id": image["id"],
                        "style": image["style"],
                        "url": image["url"],
                        "asset_id": image["asset_id"],
                        "created_at": image["created_at"],
                    }
                    for image in selected
                ],
            }
            _, source_revision = _sha256_json(revision_value)
            active = await _active_source_post(db, room_id, "diary", diary_id)
            if active is not None and active["source_revision"] == source_revision:
                result = await _post_response(db, active, user.id)
                await db.commit()
                return result

            media = []
            snapshot_images = []
            for image in selected:
                asset_id, media_url = await _publication_asset(
                    db,
                    user.id,
                    image["asset_id"],
                    image["url"],
                    imported_assets,
                )
                media.append(asset_id)
                snapshot_images.append(
                    {"style": image["style"], "url": media_url}
                )
            snapshot = {
                "date": diary["date"],
                "emotion_mode": diary["emotion_mode"],
                "images": snapshot_images,
                "text": diary["text"],
                "type": "diary",
            }
            snapshot_json, snapshot_hash = _sha256_json(snapshot)

            now = _timestamp(_utc_now())
            if active is not None:
                await db.execute(
                    "UPDATE room_posts SET status='revoked', revoked_at=? "
                    "WHERE id=? AND status='published'",
                    (now, active["id"]),
                )
            post_id = str(uuid4())
            await db.execute(
                """
                INSERT INTO room_posts (
                    id, room_id, author_user_id, source_type, source_id,
                    source_revision, snapshot_hash, snapshot_json,
                    status, published_at
                ) VALUES (?, ?, ?, 'diary', ?, ?, ?, ?, 'published', ?)
                """,
                (
                    post_id,
                    room_id,
                    user.id,
                    diary_id,
                    source_revision,
                    snapshot_hash,
                    snapshot_json,
                    now,
                ),
            )
            for ordinal, asset_id in enumerate(media):
                await db.execute(
                    "INSERT INTO room_post_media (post_id, asset_id, ordinal) "
                    "VALUES (?, ?, ?)",
                    (post_id, asset_id, ordinal),
                )
            post = await get_active_published_post(db, room_id, post_id)
            result = await _post_response(db, post, user.id)
            await db.commit()
            imported_assets.clear()
        except HTTPException:
            await _rollback_imports(db, imported_assets)
            raise
        except Exception:
            await _rollback_imports(db, imported_assets)
            raise
    finally:
        await db.close()
    return result


@router.put("/rooms/{room_id}/posts/comics/{comic_id}")
async def publish_comic_post(
    room_id: str,
    comic_id: int,
    _: None = Depends(require_same_origin),
    user: CurrentUser = Depends(get_current_user),
):
    imported_assets: list = []
    db = await get_db()
    try:
        await db.execute("BEGIN IMMEDIATE")
        try:
            await _require_paired_room(db, user.id, room_id)
            cursor = await db.execute(
                "SELECT * FROM weekly_comics WHERE id=? AND user_id=?",
                (comic_id, user.id),
            )
            comic = await cursor.fetchone()
            if comic is None:
                raise HTTPException(status_code=404, detail="comic not found")
            revision_value = {
                "week_start": comic["week_start"],
                "week_end": comic["week_end"],
                "style": comic["style"],
                "style_prompt": comic["style_prompt"],
                "prompt": comic["prompt"],
                "url": comic["url"],
                "asset_id": comic["asset_id"],
                "caption": comic["caption"],
                "created_at": comic["created_at"],
            }
            _, source_revision = _sha256_json(revision_value)
            active = await _active_source_post(db, room_id, "weekly_comic", comic_id)
            if active is not None and active["source_revision"] == source_revision:
                result = await _post_response(db, active, user.id)
                await db.commit()
                return result

            asset_id, media_url = await _publication_asset(
                db,
                user.id,
                comic["asset_id"],
                comic["url"],
                imported_assets,
            )
            snapshot = {
                "caption": comic["caption"],
                "image_url": media_url,
                "style": comic["style"],
                "type": "weekly_comic",
                "week_end": comic["week_end"],
                "week_start": comic["week_start"],
            }
            snapshot_json, snapshot_hash = _sha256_json(snapshot)

            now = _timestamp(_utc_now())
            if active is not None:
                await db.execute(
                    "UPDATE room_posts SET status='revoked', revoked_at=? "
                    "WHERE id=? AND status='published'",
                    (now, active["id"]),
                )
            post_id = str(uuid4())
            await db.execute(
                """
                INSERT INTO room_posts (
                    id, room_id, author_user_id, source_type, source_id,
                    source_revision, snapshot_hash, snapshot_json,
                    status, published_at
                ) VALUES (?, ?, ?, 'weekly_comic', ?, ?, ?, ?, 'published', ?)
                """,
                (
                    post_id,
                    room_id,
                    user.id,
                    comic_id,
                    source_revision,
                    snapshot_hash,
                    snapshot_json,
                    now,
                ),
            )
            await db.execute(
                "INSERT INTO room_post_media (post_id, asset_id, ordinal) "
                "VALUES (?, ?, 0)",
                (post_id, asset_id),
            )
            post = await get_active_published_post(db, room_id, post_id)
            result = await _post_response(db, post, user.id)
            await db.commit()
            imported_assets.clear()
        except HTTPException:
            await _rollback_imports(db, imported_assets)
            raise
        except Exception:
            await _rollback_imports(db, imported_assets)
            raise
    finally:
        await db.close()
    return result


@router.get("/rooms/{room_id}/feed")
async def room_feed(
    room_id: str,
    cursor: Optional[str] = None,
    page_size: int = Query(default=20, ge=1, le=50),
    user: CurrentUser = Depends(get_current_user),
):
    boundary = _decode_cursor(cursor) if cursor is not None else None
    db = await get_db()
    try:
        await _require_paired_room(db, user.id, room_id)
        params: list = [room_id]
        where = "post.room_id=? AND post.status='published' AND post.revoked_at IS NULL"
        if boundary is not None:
            published_at, post_id = boundary
            where += (
                " AND (post.published_at < ? OR "
                "(post.published_at = ? AND post.id < ?))"
            )
            params.extend([published_at, published_at, post_id])
        params.append(page_size + 1)
        post_cursor = await db.execute(
            "SELECT post.* FROM room_posts AS post "
            "JOIN room_members AS author ON author.room_id=post.room_id "
            "AND author.user_id=post.author_user_id AND author.left_at IS NULL "
            f"WHERE {where} "
            "ORDER BY post.published_at DESC, post.id DESC LIMIT ?",
            params,
        )
        rows = await post_cursor.fetchall()
        visible = rows[:page_size]
        items = await _post_responses(db, visible, user.id)
        next_cursor = None
        if len(rows) > page_size and visible:
            last = visible[-1]
            next_cursor = _encode_cursor(last["published_at"], last["id"])
        return {"items": items, "next_cursor": next_cursor}
    finally:
        await db.close()


@router.delete(
    "/rooms/{room_id}/posts/{post_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def withdraw_post(
    room_id: str,
    post_id: str,
    _: None = Depends(require_same_origin),
    user: CurrentUser = Depends(get_current_user),
):
    db = await get_db()
    try:
        await db.execute("BEGIN IMMEDIATE")
        try:
            await _require_paired_room(db, user.id, room_id)
            now = _timestamp(_utc_now())
            updated = await db.execute(
                "UPDATE room_posts SET status='revoked', revoked_at=? "
                "WHERE id=? AND room_id=? AND author_user_id=? "
                "AND status='published' AND revoked_at IS NULL",
                (now, post_id, room_id, user.id),
            )
            if updated.rowcount != 1:
                raise _post_not_found()
            await db.commit()
        except HTTPException:
            await db.rollback()
            raise
        except Exception:
            await db.rollback()
            raise
    finally:
        await db.close()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _set_like(room_id: str, post_id: str, user_id: int, liked: bool) -> dict:
    db = await get_db()
    try:
        await db.execute("BEGIN IMMEDIATE")
        try:
            await _require_paired_room(db, user_id, room_id)
            if await get_active_published_post(db, room_id, post_id) is None:
                raise _post_not_found()
            if liked:
                await db.execute(
                    "INSERT OR IGNORE INTO post_likes (post_id, user_id) VALUES (?, ?)",
                    (post_id, user_id),
                )
            else:
                await db.execute(
                    "DELETE FROM post_likes WHERE post_id=? AND user_id=?",
                    (post_id, user_id),
                )
            count_cursor = await db.execute(
                "SELECT COUNT(*) AS count FROM post_likes WHERE post_id=?",
                (post_id,),
            )
            count = (await count_cursor.fetchone())["count"]
            await db.commit()
        except HTTPException:
            await db.rollback()
            raise
        except Exception:
            await db.rollback()
            raise
    finally:
        await db.close()
    return {"liked": liked, "like_count": count}


@router.put("/rooms/{room_id}/posts/{post_id}/like")
async def add_like(
    room_id: str,
    post_id: str,
    _: None = Depends(require_same_origin),
    user: CurrentUser = Depends(get_current_user),
):
    return await _set_like(room_id, post_id, user.id, True)


@router.delete("/rooms/{room_id}/posts/{post_id}/like")
async def remove_like(
    room_id: str,
    post_id: str,
    _: None = Depends(require_same_origin),
    user: CurrentUser = Depends(get_current_user),
):
    return await _set_like(room_id, post_id, user.id, False)


async def _comment_response(db, comment_id: str, viewer_user_id: int) -> dict:
    cursor = await db.execute(
        """
        SELECT comment.id, comment.author_user_id, comment.body,
               comment.created_at, profile.nickname,
               avatar.id AS avatar_asset_id
        FROM post_comments AS comment
        JOIN profile ON profile.id=comment.author_user_id
        LEFT JOIN media_assets AS avatar
          ON avatar.id=profile.avatar_asset_id
         AND avatar.owner_user_id=profile.id
        WHERE comment.id=?
        """,
        (comment_id,),
    )
    row = await cursor.fetchone()
    if row is None:
        raise RuntimeError("created comment is missing")
    return _public_comment(row, viewer_user_id)


@router.get("/rooms/{room_id}/posts/{post_id}/comments")
async def list_post_comments(
    room_id: str,
    post_id: str,
    cursor: Optional[str] = None,
    page_size: int = Query(default=50, ge=1, le=100),
    user: CurrentUser = Depends(get_current_user),
):
    """List active comments oldest-first using an exclusive stable cursor."""
    boundary = _decode_cursor(cursor) if cursor is not None else None
    db = await get_db()
    try:
        await _require_paired_room(db, user.id, room_id)
        if await get_active_published_post(db, room_id, post_id) is None:
            raise _post_not_found()

        count_cursor = await db.execute(
            "SELECT COUNT(*) AS count FROM post_comments "
            "WHERE post_id=? AND deleted_at IS NULL",
            (post_id,),
        )
        total_count = (await count_cursor.fetchone())["count"]

        params: list = [post_id]
        where = "comment.post_id=? AND comment.deleted_at IS NULL"
        if boundary is not None:
            created_at, comment_id = boundary
            where += (
                " AND (comment.created_at > ? OR "
                "(comment.created_at = ? AND comment.id > ?))"
            )
            params.extend([created_at, created_at, comment_id])
        params.append(page_size + 1)
        comment_cursor = await db.execute(
            "SELECT comment.id, comment.author_user_id, comment.body, "
            "comment.created_at, profile.nickname, "
            "avatar.id AS avatar_asset_id "
            "FROM post_comments AS comment "
            "JOIN profile ON profile.id=comment.author_user_id "
            "LEFT JOIN media_assets AS avatar "
            "ON avatar.id=profile.avatar_asset_id "
            "AND avatar.owner_user_id=profile.id "
            f"WHERE {where} "
            "ORDER BY comment.created_at, comment.id LIMIT ?",
            params,
        )
        rows = await comment_cursor.fetchall()
        visible = rows[:page_size]
        items = [_public_comment(row, user.id) for row in visible]
        next_cursor = None
        if len(rows) > page_size and visible:
            last = visible[-1]
            next_cursor = _encode_cursor(last["created_at"], last["id"])
        return {
            "items": items,
            "next_cursor": next_cursor,
            "total_count": total_count,
        }
    finally:
        await db.close()


@router.post("/rooms/{room_id}/posts/{post_id}/comments")
async def create_comment(
    room_id: str,
    post_id: str,
    payload: CommentRequest,
    _: None = Depends(require_same_origin),
    user: CurrentUser = Depends(get_current_user),
):
    request_id = payload.client_request_id.strip()
    body = payload.body.strip()
    if not request_id or not body:
        raise HTTPException(status_code=400, detail="comment fields are required")
    db = await get_db()
    try:
        await db.execute("BEGIN IMMEDIATE")
        try:
            await _require_paired_room(db, user.id, room_id)
            if await get_active_published_post(db, room_id, post_id) is None:
                raise _post_not_found()
            cursor = await db.execute(
                "SELECT id, deleted_at FROM post_comments "
                "WHERE post_id=? AND author_user_id=? AND client_request_id=?",
                (post_id, user.id, request_id),
            )
            existing = await cursor.fetchone()
            if existing is not None:
                if existing["deleted_at"] is not None:
                    raise HTTPException(status_code=409, detail="comment was deleted")
                result = await _comment_response(db, existing["id"], user.id)
                await db.commit()
                return JSONResponse(status_code=200, content=result)
            comment_id = str(uuid4())
            await db.execute(
                "INSERT INTO post_comments "
                "(id, post_id, author_user_id, client_request_id, body, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    comment_id,
                    post_id,
                    user.id,
                    request_id,
                    body,
                    _timestamp(_utc_now()),
                ),
            )
            result = await _comment_response(db, comment_id, user.id)
            await db.commit()
        except HTTPException:
            await db.rollback()
            raise
        except Exception:
            await db.rollback()
            raise
    finally:
        await db.close()
    return JSONResponse(status_code=201, content=result)


@router.delete(
    "/rooms/{room_id}/comments/{comment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_comment(
    room_id: str,
    comment_id: str,
    _: None = Depends(require_same_origin),
    user: CurrentUser = Depends(get_current_user),
):
    db = await get_db()
    try:
        await db.execute("BEGIN IMMEDIATE")
        try:
            await _require_paired_room(db, user.id, room_id)
            cursor = await db.execute(
                """
                SELECT comment.id, post.id AS post_id
                FROM post_comments AS comment
                JOIN room_posts AS post ON post.id=comment.post_id
                WHERE comment.id=? AND comment.author_user_id=?
                  AND post.room_id=?
                """,
                (comment_id, user.id, room_id),
            )
            comment = await cursor.fetchone()
            if comment is None or await get_active_published_post(
                db, room_id, comment["post_id"]
            ) is None:
                raise HTTPException(status_code=404, detail="comment not found")
            await db.execute(
                "UPDATE post_comments SET deleted_at=COALESCE(deleted_at, ?) "
                "WHERE id=? AND author_user_id=?",
                (_timestamp(_utc_now()), comment_id, user.id),
            )
            await db.commit()
        except HTTPException:
            await db.rollback()
            raise
        except Exception:
            await db.rollback()
            raise
    finally:
        await db.close()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _public_temperature_snapshot(row) -> dict:
    return {
        "date": row["snapshot_date"],
        "score": row["score"],
        "label": row["label"],
        "color": row["color"],
        "nickname": row["subject_nickname"],
    }


def _temperature_subject(row) -> dict:
    if row is None:
        return {"status": "unavailable"}
    return {
        "status": "available",
        "snapshot": _public_temperature_snapshot(row),
    }


@router.get("/rooms/{room_id}/temperatures")
async def room_temperatures(
    room_id: str,
    date: str = Query(...),
    user: CurrentUser = Depends(get_current_user),
):
    parse_temperature_date(date)
    db = await get_db()
    try:
        await _require_paired_room(db, user.id, room_id)
        members = await get_public_room_members(db, room_id)
        if members is None or len(members) != 2:
            raise _room_not_found()
        partner = next((member for member in members if member.id != user.id), None)
        if partner is None:
            raise _room_not_found()

        cursor = await db.execute(
            """
            SELECT room_id, user_id, snapshot_date, score, label, color,
                   subject_nickname
            FROM room_temperature_snapshots
            WHERE room_id=? AND snapshot_date=? AND revoked_at IS NULL
              AND user_id IN (?, ?)
            """,
            (room_id, date, user.id, partner.id),
        )
        snapshots = {row["user_id"]: row for row in await cursor.fetchall()}
        return {
            "own": _temperature_subject(snapshots.get(user.id)),
            "partner": _temperature_subject(snapshots.get(partner.id)),
        }
    finally:
        await db.close()


@router.put("/rooms/{room_id}/temperatures/{date}")
async def publish_room_temperature(
    room_id: str,
    date: str,
    _: None = Depends(require_same_origin),
    user: CurrentUser = Depends(get_current_user),
):
    anchor = parse_temperature_date(date)

    # Check room access with a short connection before loading private inputs.
    db = await get_db()
    try:
        await _require_paired_room(db, user.id, room_id)
    finally:
        await db.close()

    # Compute only from authenticated owner-scoped data. Both the membership
    # connection and the input connection are closed before the external AI
    # await. The API has no request model for score, subject, or user ID.
    inputs = await load_temperature_inputs(user.id, date, anchor)
    computed = await compute_temperature(inputs)

    db = await get_db()
    try:
        await db.execute("BEGIN IMMEDIATE")
        try:
            # Membership can change while an AI-backed computation is running.
            # Revalidate inside the write transaction before publishing.
            await _require_paired_room(db, user.id, room_id)
            now = _timestamp(_utc_now())
            await db.execute(
                """
                INSERT INTO room_temperature_snapshots (
                    room_id, user_id, snapshot_date, score, label, color,
                    subject_nickname, published_at, revoked_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)
                ON CONFLICT(room_id, user_id, snapshot_date) DO UPDATE SET
                    score=excluded.score,
                    label=excluded.label,
                    color=excluded.color,
                    subject_nickname=excluded.subject_nickname,
                    published_at=excluded.published_at,
                    revoked_at=NULL
                """,
                (
                    room_id,
                    user.id,
                    date,
                    computed["score"],
                    computed["label"],
                    computed["color"],
                    computed["nickname"],
                    now,
                ),
            )
            cursor = await db.execute(
                """
                SELECT room_id, user_id, snapshot_date, score, label, color,
                       subject_nickname
                FROM room_temperature_snapshots
                WHERE room_id=? AND user_id=? AND snapshot_date=?
                  AND revoked_at IS NULL
                """,
                (room_id, user.id, date),
            )
            snapshot = await cursor.fetchone()
            if snapshot is None:
                raise RuntimeError("published temperature snapshot is missing")
            result = _public_temperature_snapshot(snapshot)
            await db.commit()
        except HTTPException:
            await db.rollback()
            raise
        except Exception:
            await db.rollback()
            raise
    finally:
        await db.close()
    return result


@router.delete(
    "/rooms/{room_id}/temperatures/{date}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def revoke_room_temperature(
    room_id: str,
    date: str,
    _: None = Depends(require_same_origin),
    user: CurrentUser = Depends(get_current_user),
):
    parse_temperature_date(date)
    db = await get_db()
    try:
        await db.execute("BEGIN IMMEDIATE")
        try:
            await _require_paired_room(db, user.id, room_id)
            await db.execute(
                """
                UPDATE room_temperature_snapshots
                SET revoked_at=COALESCE(revoked_at, ?)
                WHERE room_id=? AND user_id=? AND snapshot_date=?
                """,
                (_timestamp(_utc_now()), room_id, user.id, date),
            )
            await db.commit()
        except HTTPException:
            await db.rollback()
            raise
        except Exception:
            await db.rollback()
            raise
    finally:
        await db.close()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
