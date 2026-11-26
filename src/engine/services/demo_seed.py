"""新账号示例注入:自动订阅 DEMO_PUBLISHER_USER_ID 并将其已发布作品作为只读示例置顶到新用户的底片夹。

调用时机:
- 新账号注册(`routers/auth.py` register)成功后调用 `seed_demo_publisher`。
- 离线脚本 `scripts/backfill_demo_seed.py` 给已有账号补挂示例。

实现:
- 创建单向订阅:新用户作为 subscriber 订阅 DEMO 账号。
- 将 DEMO 账号的指定已发布作品(绘本/漫剧)添加为 work_audience 授权条目。
- 这些授权使体验者能在回响 feed / 底片夹 / 媒体访问里看到示例,
  但不可删除、不可发布/编辑(前端根据 is_demo_seed / read_only 标记隐藏操作按钮)。

幂等性:INSERT ... ON CONFLICT DO UPDATE,同一个用户多次注册/重入不抛错。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

import config


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _demo_publisher_user_id(db: Any) -> Optional[int]:
    """验证 DEMO_PUBLISHER_USER_ID 后返回某个已存在的演示者 user_id。"""
    candidate = config.DEMO_PUBLISHER_USER_ID
    if candidate <= 0:
        return None
    cursor = await db.execute(
        "SELECT 1 FROM accounts WHERE user_id = ?", (candidate,)
    )
    row = await cursor.fetchone()
    return candidate if row else None


async def _seed_subscription(db: Any, *, demo_user_id: int, subscriber_user_id: int) -> int:
    """确保 subscriber 已订阅 demo 账号;返回 subscription_id。"""
    cursor = await db.execute(
        """
        INSERT INTO subscriptions (owner_user_id, subscriber_user_id, status)
        VALUES (?, ?, 'active')
        ON CONFLICT(owner_user_id, subscriber_user_id) DO UPDATE SET
            status = 'active',
            revoked_at = NULL
        RETURNING id
        """,
        (demo_user_id, subscriber_user_id),
    )
    row = await cursor.fetchone()
    if row is None:
        cursor = await db.execute(
            "SELECT id FROM subscriptions WHERE owner_user_id = ? AND subscriber_user_id = ?",
            (demo_user_id, subscriber_user_id),
        )
        row = await cursor.fetchone()
    return int(row["id"])


async def _seed_work_audience(
    db: Any, *, subscription_id: int, work_id: int, now: str
) -> None:
    """确保指定作品对目标订阅中 active 的观众授予演示授权."""
    await db.execute(
        """
        INSERT INTO work_audience (work_id, subscription_id, status, granted_at, revoked_at, created_at)
        VALUES (?, ?, 'active', ?, NULL, ?)
        ON CONFLICT(work_id, subscription_id) DO UPDATE SET
            status = 'active',
            granted_at = excluded.granted_at,
            revoked_at = NULL
        """,
        (work_id, subscription_id, now, now),
    )


async def seed_demo_publisher(
    db: Any,
    *,
    subscriber_user_id: int,
) -> None:
    """注册成功后在 BEGIN IMMEDIATE 事务外调用(一个长事务)。"""
    demo_user_id = await _demo_publisher_user_id(db)
    if demo_user_id is None:
        return

    now = _now()
    sub_id = await _seed_subscription(
        db, demo_user_id=demo_user_id, subscriber_user_id=subscriber_user_id
    )
    for work_id in config.DEMO_PICTUREBOOK_WORK_IDS:
        await _seed_work_audience(
            db, subscription_id=sub_id, work_id=work_id, now=now
        )
    await db.commit()


async def is_demo_subscriber(db: Any, *, user_id: int) -> bool:
    """快速检查当前用户是否订阅了演示发布者。"""
    demo_user_id = await _demo_publisher_user_id(db)
    if demo_user_id is None:
        return False
    cursor = await db.execute(
        "SELECT 1 FROM subscriptions WHERE owner_user_id = ? AND subscriber_user_id = ? AND status = 'active'",
        (demo_user_id, user_id),
    )
    return (await cursor.fetchone()) is not None


async def ensure_demo_work_audience(
    db: Any,
    *,
    subscriber_user_id: int,
) -> None:
    """同上,但已在事务内(使用调用方控制事务)。
    幂等,不重复创建 subscription 或 audience 记录。
    """
    demo_user_id = await _demo_publisher_user_id(db)
    if demo_user_id is None:
        return
    now = _now()
    sub_id = await _seed_subscription(
        db, demo_user_id=demo_user_id, subscriber_user_id=subscriber_user_id
    )
    for work_id in config.DEMO_PICTUREBOOK_WORK_IDS:
        await _seed_work_audience(
            db, subscription_id=sub_id, work_id=work_id, now=now
        )