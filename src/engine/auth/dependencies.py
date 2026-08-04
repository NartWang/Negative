from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, HTTPException, Request, status

import config
from auth.security import hash_session_token
from database import get_db


def _authentication_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="authentication required",
    )


@dataclass(frozen=True)
class CurrentUser:
    id: int
    nickname: str
    avatar_url: Optional[str]
    signature: Optional[str]
    created_at: str


@dataclass(frozen=True)
class CurrentSession:
    token_hash: str
    user_id: int
    expires_at: datetime
    user: CurrentUser


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


async def get_current_session(request: Request) -> CurrentSession:
    raw_token = request.cookies.get(config.SESSION_COOKIE_NAME)
    if not raw_token:
        raise _authentication_error()

    token_hash = hash_session_token(raw_token)
    db = await get_db()
    try:
        cursor = await db.execute(
            """
            SELECT s.user_id, s.expires_at, s.revoked_at,
                   p.id, p.nickname, p.avatar_url, p.signature, p.created_at
            FROM auth_sessions s
            JOIN accounts a ON a.user_id = s.user_id
            JOIN profile p ON p.id = a.user_id
            WHERE s.token_hash = ?
            """,
            (token_hash,),
        )
        row = await cursor.fetchone()
    finally:
        await db.close()

    if not row or row["revoked_at"] is not None:
        raise _authentication_error()
    try:
        expires_at = _parse_timestamp(row["expires_at"])
    except (TypeError, ValueError):
        raise _authentication_error() from None
    if expires_at <= datetime.now(timezone.utc):
        raise _authentication_error()

    user = CurrentUser(
        id=row["id"],
        nickname=row["nickname"],
        avatar_url=row["avatar_url"],
        signature=row["signature"],
        created_at=row["created_at"],
    )
    return CurrentSession(
        token_hash=token_hash,
        user_id=row["user_id"],
        expires_at=expires_at,
        user=user,
    )


async def get_current_user(
    session: CurrentSession = Depends(get_current_session),
) -> CurrentUser:
    return session.user


async def get_current_user_id(
    user: CurrentUser = Depends(get_current_user),
) -> int:
    return user.id


async def require_same_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if origin is None:
        return

    request_origin = f"{request.url.scheme}://{request.url.netloc}"
    if origin != request_origin and origin not in config.FRONTEND_ORIGINS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="origin not allowed",
        )
