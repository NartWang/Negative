"""体验配额:限制每个用户可新建绘本/漫剧任务的次数。

对外 Demo 场景:把产品交给他人体验时,体验账号默认没有额度(数据库无行即 0),
任何"新建一条生成任务"的动作都会被拒绝,从而避免被无限刷取消耗 token。
次数由离线脚本 scripts/set_generation_quota.py 按需充值,不在产品内暴露。

计数次区与 generation_slots 一致:picturebook 与 motion_comic 各自独立。
扣减时机是"真正 INSERT 一条新 job";同一任务的重试/恢复(复用已有 job)
不重复扣减,所以用户失败重试不会被额外收费。

所有扣减都必须在调用方已有的 BEGIN IMMEDIATE 写事务里执行——先占分区槽位、
再扣次数、最后插入任务,任一失败整体回滚,不会出现"扣了次数但没建成任务"。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from services.generation_slots import CATEGORY_MOTION_COMIC, CATEGORY_PICTUREBOOK

_VALID_CATEGORIES = (CATEGORY_PICTUREBOOK, CATEGORY_MOTION_COMIC)


class GenerationQuotaExceeded(Exception):
    """该分区可新建次数已用尽;携带分区供 403 响应给出可读的剩余提示。"""

    def __init__(self, category: str):
        super().__init__(f"no remaining {category} generation quota")
        self.category = category


def quota_detail(exc: GenerationQuotaExceeded) -> dict:
    """403 响应体:只暴露分区,不泄漏任何账号或额度数字细节。"""
    label = "绘本" if exc.category == CATEGORY_PICTUREBOOK else "漫剧"
    return {
        "detail": f"可生成的{label}次数已用完",
        "category": exc.category,
        "code": "generation_quota_exceeded",
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def remaining_quota(db: Any, *, user_id: int, category: str) -> int:
    """查询剩余次数;无行视为 0。仅供脚本/只读展示,不做并发保证。"""
    cursor = await db.execute(
        "SELECT remaining FROM generation_quotas WHERE user_id = ? AND category = ?",
        (user_id, category),
    )
    row = await cursor.fetchone()
    return int(row["remaining"]) if row else 0


async def consume_quota(db: Any, *, user_id: int, category: str) -> None:
    """在新建任务的写事务里原子扣 1 次;余额不足抛 GenerationQuotaExceeded。

    用一条带条件 UPDATE 完成"检查 + 扣减",避免先查后改的竞态:
    只有 remaining > 0 才会命中并减 1,否则 rowcount 为 0。
    """
    if category not in _VALID_CATEGORIES:
        raise ValueError(f"unknown generation category: {category}")
    cursor = await db.execute(
        "UPDATE generation_quotas SET remaining = remaining - 1, updated_at = ? "
        "WHERE user_id = ? AND category = ? AND remaining > 0",
        (_now(), user_id, category),
    )
    if cursor.rowcount == 0:
        raise GenerationQuotaExceeded(category)


async def set_quota(
    db: Any, *, user_id: int, category: str, remaining: int
) -> None:
    """充值/覆盖某账号在某分区的可用次数(离线脚用)。"""
    if category not in _VALID_CATEGORIES:
        raise ValueError(f"unknown generation category: {category}")
    if remaining < 0:
        raise ValueError("remaining must be >= 0")
    await db.execute(
        "INSERT INTO generation_quotas (user_id, category, remaining, updated_at) "
        "VALUES (?, ?, ?, ?) "
        "ON CONFLICT (user_id, category) "
        "DO UPDATE SET remaining = excluded.remaining, updated_at = excluded.updated_at",
        (user_id, category, int(remaining), _now()),
    )


async def add_quota(
    db: Any, *, user_id: int, category: str, delta: int
) -> int:
    """在现有余额上累加(可为负做扣减,但不低于 0);返回最新余额。"""
    if category not in _VALID_CATEGORIES:
        raise ValueError(f"unknown generation category: {category}")
    current = await remaining_quota(db, user_id=user_id, category=category)
    new_value: Optional[int] = max(0, current + int(delta))
    await set_quota(db, user_id=user_id, category=category, remaining=new_value)
    return new_value
