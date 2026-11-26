"""单分区单活跃生成任务守卫。

规格第六节:每个用户同一时间最多一个 running 绘本任务和一个 running 漫剧任务;
两者可以并行。所有能把任务转为 running 的入口(直接日记创建/重试、作品绘本
开始/替换/重试、漫剧开始/重试)都必须在同一个 BEGIN IMMEDIATE 写事务里先调
require_available_slot,再执行插入或状态翻转,这样快速双击、多标签页、多设备
并发都无法绕过。

表名只允许来自下面的字面量映射,绝不接受请求输入——调用方传内部常量。
"""

from __future__ import annotations

from typing import Any, Optional

CATEGORY_PICTUREBOOK = "picturebook"
CATEGORY_MOTION_COMIC = "motion_comic"

_TABLES = {
    CATEGORY_PICTUREBOOK: "picturebook_jobs",
    CATEGORY_MOTION_COMIC: "picturebook_video_jobs",
}


class GenerationSlotConflict(Exception):
    """同分区已存在运行任务;携带其 id 供 409 响应恢复前端进度条。"""

    def __init__(self, category: str, active_job_id: int):
        super().__init__(f"an active {category} generation already exists")
        self.category = category
        self.active_job_id = active_job_id


def conflict_detail(exc: GenerationSlotConflict) -> dict:
    """409 响应体:只暴露任务 id 与分区,不泄漏任何生成内容。"""
    return {
        "detail": "generation slot is occupied",
        "category": exc.category,
        "active_job_id": exc.active_job_id,
    }


async def require_available_slot(
    db: Any,
    *,
    user_id: int,
    category: str,
    current_job_id: Optional[int] = None,
) -> None:
    """占用检查;必须在 BEGIN IMMEDIATE 事务内、转 running 写入之前调用。

    current_job_id 仅在重试/恢复同一个任务时传入,用于把自身排除在冲突之外。
    """
    table = _TABLES[category]
    if current_job_id is None:
        cursor = await db.execute(
            f"SELECT id FROM {table} WHERE user_id = ? AND status = 'running' "
            "ORDER BY updated_at DESC, id DESC LIMIT 1",
            (user_id,),
        )
    else:
        cursor = await db.execute(
            f"SELECT id FROM {table} WHERE user_id = ? AND status = 'running' "
            "AND id != ? ORDER BY updated_at DESC, id DESC LIMIT 1",
            (user_id, current_job_id),
        )
    row = await cursor.fetchone()
    if row:
        raise GenerationSlotConflict(category, int(row["id"]))
