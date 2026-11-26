"""漫剧草稿持久化:来源绘本、页序、与视频任务的关联。

规则(规格 7.3):
- 来源必须是当前用户 9 页完整的绘本(正式作品或历史任务);
- 页序 2–24 个唯一有效页索引,且每页都属于该来源绘本;
- video_job_id 非空后页序不可再改,改页序从新建草稿开始;
- 越权访问一律 404。
"""

from __future__ import annotations

import json
from typing import Any, Optional

from services.story_days import list_completed_picturebooks

MIN_PAGES = 2
MAX_PAGES = 24
TOTAL_PICTUREBOOK_PAGES = 9


class DraftError(Exception):
    status = 400


class DraftNotFound(DraftError):
    status = 404


class DraftValidationError(DraftError):
    status = 422


class DraftConflict(DraftError):
    status = 409

    def __init__(self, message: str, *, existing_draft_id: Optional[int] = None):
        super().__init__(message)
        self.existing_draft_id = existing_draft_id


async def _now(db: Any) -> str:
    cursor = await db.execute("SELECT datetime('now')")
    return (await cursor.fetchone())[0]


def _canonical_sequence(sequence: list[int]) -> str:
    return json.dumps(list(sequence), ensure_ascii=False)


async def _resolve_owned_complete_source(
    db: Any, user_id: int, source_kind: str, source_id: int
) -> dict:
    """来源绘本必须属于当前用户且 9 页完整;返回归一化书籍。"""
    books = await list_completed_picturebooks(db, user_id)
    want = ("canonical_work" if source_kind == "work" else "historical_job",
            source_id)
    for book in books:
        if (book["source_kind"], book["source_id"]) == want:
            if book["ready_pages"] != TOTAL_PICTUREBOOK_PAGES:
                raise DraftValidationError("source picturebook is incomplete")
            return book
    raise DraftNotFound("motion comic draft source not found")


async def _validate_sequence(db: Any, user_id: int, source: dict, sequence: list[int]) -> list[int]:
    if not isinstance(sequence, list):
        raise DraftValidationError("page_sequence must be a list")
    if not all(isinstance(item, int) and item >= 0 for item in sequence):
        raise DraftValidationError("page_sequence must contain page indexes")
    if len(set(sequence)) != len(sequence):
        raise DraftValidationError("page_sequence must be unique")
    if not MIN_PAGES <= len(sequence) <= MAX_PAGES:
        raise DraftValidationError(
            f"page_sequence must contain {MIN_PAGES} to {MAX_PAGES} pages"
        )
    valid = {page["page_index"] for page in source["pages"]}
    if any(item not in valid for item in sequence):
        raise DraftValidationError("page_sequence contains pages outside the source")
    return sequence


def _draft_payload(row: dict) -> dict:
    return {
        "id": row["id"],
        "source_kind": row["source_kind"],
        "source_id": row["source_id"],
        "title": row["title"],
        "page_sequence": json.loads(row["page_sequence_json"] or "[]"),
        "video_job_id": row["video_job_id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


async def _load_owned_draft(db: Any, user_id: int, draft_id: int) -> dict:
    cursor = await db.execute(
        "SELECT * FROM motion_comic_drafts WHERE id = ? AND user_id = ?",
        (draft_id, user_id),
    )
    row = await cursor.fetchone()
    if not row:
        raise DraftNotFound("motion comic draft not found")
    return dict(row)


async def create_draft(
    db: Any,
    user_id: int,
    *,
    source_kind: str,
    source_id: int,
    title: str = "",
    page_sequence: list[int],
) -> dict:
    if source_kind not in ("work", "job"):
        raise DraftValidationError("source_kind must be 'work' or 'job'")
    source = await _resolve_owned_complete_source(db, user_id, source_kind, source_id)
    sequence = await _validate_sequence(db, user_id, source, list(page_sequence))
    now = await _now(db)
    cursor = await db.execute(
        """
        INSERT INTO motion_comic_drafts (
            user_id, source_kind, source_id, title,
            page_sequence_json, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (user_id, source_kind, source_id, title, _canonical_sequence(sequence), now, now),
    )
    await db.commit()
    return _draft_payload(await _load_owned_draft(db, user_id, cursor.lastrowid))


async def get_draft(db: Any, user_id: int, draft_id: int) -> dict:
    return _draft_payload(await _load_owned_draft(db, user_id, draft_id))


async def update_draft(
    db: Any,
    user_id: int,
    draft_id: int,
    *,
    title: Optional[str] = None,
    page_sequence: Optional[list[int]] = None,
) -> dict:
    row = await _load_owned_draft(db, user_id, draft_id)
    if row["video_job_id"] is not None and page_sequence is not None:
        raise DraftConflict(
            "draft is linked to a video job; start a new draft to change pages",
            existing_draft_id=row["id"],
        )
    if page_sequence is not None:
        source = await _resolve_owned_complete_source(
            db, user_id, row["source_kind"], row["source_id"]
        )
        sequence = await _validate_sequence(db, user_id, source, list(page_sequence))
    else:
        sequence = None
    now = await _now(db)
    await db.execute(
        """
        UPDATE motion_comic_drafts
        SET title = COALESCE(?, title),
            page_sequence_json = COALESCE(?, page_sequence_json),
            updated_at = ?
        WHERE id = ? AND user_id = ?
        """,
        (
            title,
            _canonical_sequence(sequence) if sequence is not None else None,
            now,
            draft_id,
            user_id,
        ),
    )
    await db.commit()
    return _draft_payload(await _load_owned_draft(db, user_id, draft_id))


async def delete_draft(db: Any, user_id: int, draft_id: int) -> None:
    row = await _load_owned_draft(db, user_id, draft_id)
    if row["video_job_id"] is not None:
        cursor = await db.execute(
            "SELECT status FROM picturebook_video_jobs WHERE id = ? AND user_id = ?",
            (row["video_job_id"], user_id),
        )
        job = await cursor.fetchone()
        if job and job["status"] == "running":
            raise DraftConflict("motion comic is still generating", existing_draft_id=draft_id)
    await db.execute(
        "DELETE FROM motion_comic_drafts WHERE id = ? AND user_id = ?",
        (draft_id, user_id),
    )
    await db.commit()


async def draft_for_video_job(
    db: Any, user_id: int, video_job_id: int
) -> Optional[dict]:
    cursor = await db.execute(
        "SELECT * FROM motion_comic_drafts "
        "WHERE video_job_id = ? AND user_id = ?",
        (video_job_id, user_id),
    )
    row = await cursor.fetchone()
    return dict(row) if row else None


async def link_draft_to_video_job(
    db: Any,
    user_id: int,
    *,
    draft_id: int,
    video_job_id: int,
) -> dict:
    row = await _load_owned_draft(db, user_id, draft_id)
    if row["video_job_id"] is not None and row["video_job_id"] != video_job_id:
        raise DraftConflict(
            "draft is already linked to another video job",
            existing_draft_id=row["id"],
        )
    now = await _now(db)
    await db.execute(
        "UPDATE motion_comic_drafts SET video_job_id = ?, updated_at = ? "
        "WHERE id = ? AND user_id = ?",
        (video_job_id, now, draft_id, user_id),
    )
    return _draft_payload(await _load_owned_draft(db, user_id, draft_id))
