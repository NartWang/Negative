from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field, SecretStr

import config
from auth.dependencies import (
    CurrentSession,
    CurrentUser,
    get_current_session,
    get_current_user,
    require_same_origin,
)
from auth.security import (
    DUMMY_PASSWORD_HASH,
    create_session_token,
    hash_password,
    hash_session_token,
    normalize_username,
    verify_password,
)
from database import get_db
from services.demo_seed import seed_demo_publisher


router = APIRouter(prefix="/api", tags=["auth"])


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: SecretStr = Field(min_length=1, max_length=1024)


class RegisterRequest(LoginRequest):
    password: SecretStr = Field(min_length=8, max_length=1024)
    nickname: str = Field(min_length=1, max_length=100)


class PublicProfile(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nickname: str
    avatar_url: Optional[str]
    signature: Optional[str]
    created_at: str


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(value: datetime) -> str:
    return value.isoformat()


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=config.SESSION_COOKIE_NAME,
        value=token,
        max_age=config.SESSION_TTL_SECONDS,
        path="/",
        secure=config.SESSION_COOKIE_SECURE,
        httponly=True,
        samesite="lax",
    )


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=config.SESSION_COOKIE_NAME,
        path="/",
        secure=config.SESSION_COOKIE_SECURE,
        httponly=True,
        samesite="lax",
    )


async def _insert_session(db, user_id: int) -> str:
    raw_token = create_session_token()
    now = _utc_now()
    await db.execute(
        """
        INSERT INTO auth_sessions (token_hash, user_id, expires_at, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (
            hash_session_token(raw_token),
            user_id,
            _timestamp(now + timedelta(seconds=config.SESSION_TTL_SECONDS)),
            _timestamp(now),
        ),
    )
    return raw_token


@router.post(
    "/auth/register",
    response_model=PublicProfile,
    status_code=status.HTTP_201_CREATED,
)
async def register(
    payload: RegisterRequest,
    response: Response,
    _: None = Depends(require_same_origin),
):
    username_norm = normalize_username(payload.username)
    if not username_norm:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="username is required",
        )

    # 对外 Demo 默认关闭注册:只放行预建体验账号登录,防止陌生人注册占用资源。
    if not config.REGISTRATION_OPEN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="registration is closed",
        )

    password_hash = hash_password(payload.password.get_secret_value())
    db = await get_db()
    try:
        await db.execute("BEGIN IMMEDIATE")
        try:
            profile_cursor = await db.execute(
                "INSERT INTO profile (nickname) VALUES (?)",
                (payload.nickname,),
            )
            user_id = profile_cursor.lastrowid
            await db.execute(
                """
                INSERT INTO accounts (user_id, username_norm, password_hash)
                VALUES (?, ?, ?)
                """,
                (user_id, username_norm, password_hash),
            )
            raw_token = await _insert_session(db, user_id)
            cursor = await db.execute(
                """
                SELECT id, nickname, avatar_url, signature, created_at
                FROM profile WHERE id = ?
                """,
                (user_id,),
            )
            profile = await cursor.fetchone()
            await db.commit()
        except sqlite3.IntegrityError as exc:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="username unavailable",
            ) from exc
        except Exception:
            await db.rollback()
            raise
    finally:
        await db.close()

    # 新账号默认关注底片示例发布者,失败不阻塞注册。
    if config.DEMO_PUBLISHER_USER_ID > 0:
        try:
            _db = await get_db()
            try:
                await seed_demo_publisher(_db, subscriber_user_id=user_id)
            finally:
                await _db.close()
        except Exception:
            pass

    _set_session_cookie(response, raw_token)
    return dict(profile)


@router.post("/auth/login", response_model=PublicProfile)
async def login(
    payload: LoginRequest,
    response: Response,
    _: None = Depends(require_same_origin),
):
    db = await get_db()
    try:
        cursor = await db.execute(
            """
            SELECT a.user_id, a.password_hash,
                   p.id, p.nickname, p.avatar_url, p.signature, p.created_at
            FROM accounts a
            JOIN profile p ON p.id = a.user_id
            WHERE a.username_norm = ?
            """,
            (normalize_username(payload.username),),
        )
        account = await cursor.fetchone()
        password_valid = verify_password(
            payload.password.get_secret_value(),
            account["password_hash"] if account else DUMMY_PASSWORD_HASH,
        )
        if account is None or not password_valid:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid credentials",
            )

        raw_token = await _insert_session(db, account["user_id"])
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    finally:
        await db.close()

    _set_session_cookie(response, raw_token)
    return dict(account)


@router.delete("/auth/session", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,
    _: None = Depends(require_same_origin),
    session: CurrentSession = Depends(get_current_session),
):
    db = await get_db()
    try:
        await db.execute(
            """
            UPDATE auth_sessions SET revoked_at = ?
            WHERE token_hash = ? AND revoked_at IS NULL
            """,
            (_timestamp(_utc_now()), session.token_hash),
        )
        await db.commit()
    finally:
        await db.close()

    _clear_session_cookie(response)


@router.get("/me", response_model=PublicProfile)
async def me(user: CurrentUser = Depends(get_current_user)):
    return user
