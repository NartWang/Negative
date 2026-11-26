from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from typing import Literal, Optional
from datetime import datetime
from auth.dependencies import get_current_user_id, require_same_origin
from database import get_db
from agents.diary_agent import (
    DIARY_SOURCE_CHAR_LIMIT,
    diary_source_char_count,
    generate_diary,
    rewrite_paragraph,
)
from services.generation_errors import (
    GenerationServiceError,
    raise_generation_http_error,
)

router = APIRouter()


class DiaryCreateRequest(BaseModel):
    date: str


class DiaryUpdateRequest(BaseModel):
    text: Optional[str] = None
    draft_text: Optional[str] = None
    status: Optional[str] = None
    source: Optional[str] = None


class AiFillRequest(BaseModel):
    emotion_mode: Literal["real", "imagery"] = "real"
    schedule_ids: Optional[list[int]] = Field(default=None, max_length=50)
    fragment_ids: Optional[list[int]] = Field(default=None, max_length=50)


class AiRewriteRequest(BaseModel):
    paragraph: str
    direction: str = "warmer"
    custom_prompt: Optional[str] = None


async def _fetch_diary_with_images(
    db, diary_id: int, user_id: int
) -> Optional[dict]:
    cursor = await db.execute(
        "SELECT * FROM diaries WHERE id = ? AND user_id = ?",
        (diary_id, user_id),
    )
    row = await cursor.fetchone()
    if not row:
        return None
    diary = dict(row)
    cursor = await db.execute(
        "SELECT id, diary_id, style, style_prompt, url, created_at, kept, "
        "asset_id FROM images WHERE diary_id = ? AND kept = 1 ORDER BY created_at",
        (diary_id,),
    )
    diary["images"] = [dict(r) for r in await cursor.fetchall()]
    return diary


async def _fetch_selected_fragments(
    db,
    *,
    date: str,
    user_id: int,
    requested_ids: Optional[list[int]],
) -> list[dict]:
    if requested_ids is None:
        cursor = await db.execute(
            "SELECT * FROM fragments WHERE date = ? AND user_id = ? "
            "ORDER BY record_time ASC, created_at ASC, id ASC",
            (date, user_id),
        )
        return [dict(row) for row in await cursor.fetchall()]
    if not requested_ids:
        return []

    unique_ids = list(dict.fromkeys(requested_ids))
    placeholders = ", ".join("?" for _ in unique_ids)
    cursor = await db.execute(
        "SELECT * FROM fragments WHERE date = ? AND user_id = ? "
        f"AND id IN ({placeholders}) "
        "ORDER BY record_time ASC, created_at ASC, id ASC",
        (date, user_id, *unique_ids),
    )
    rows = [dict(row) for row in await cursor.fetchall()]
    if {row["id"] for row in rows} != set(unique_ids):
        raise HTTPException(status_code=404, detail="source records not found")
    return rows


async def _fetch_notebook_index(db, user_id: int) -> list[dict]:
    cursor = await db.execute(
        """
        WITH ranked AS (
          SELECT
            id,
            date,
            ROW_NUMBER() OVER (
              PARTITION BY date
              ORDER BY
                CASE WHEN confirmed_at IS NULL THEN 1 ELSE 0 END,
                confirmed_at DESC,
                created_at DESC,
                id DESC
            ) AS day_rank
          FROM diaries
          WHERE user_id = ? AND status = 'confirmed'
        )
        SELECT id AS diary_id, date
        FROM ranked
        WHERE day_rank = 1
        ORDER BY date ASC, diary_id ASC
        """,
        (user_id,),
    )
    return [dict(row) for row in await cursor.fetchall()]


@router.get("/notebook/index")
async def notebook_index(user_id: int = Depends(get_current_user_id)):
    db = await get_db()
    try:
        items = await _fetch_notebook_index(db, user_id)
        return {"items": items, "total": len(items)}
    finally:
        await db.close()


@router.get("/notebook/{diary_id}")
async def notebook_detail(
    diary_id: int, user_id: int = Depends(get_current_user_id)
):
    db = await get_db()
    try:
        items = await _fetch_notebook_index(db, user_id)
        canonical_ids = {item["diary_id"] for item in items}
        if diary_id not in canonical_ids:
            raise HTTPException(status_code=404, detail="diary not found")
        diary = await _fetch_diary_with_images(db, diary_id, user_id)
        if diary is None or diary.get("status") != "confirmed":
            raise HTTPException(status_code=404, detail="diary not found")
        return diary
    finally:
        await db.close()


@router.post("")
async def create_blank(
    req: DiaryCreateRequest,
    _: None = Depends(require_same_origin),
    user_id: int = Depends(get_current_user_id),
):
    """Create a blank manual diary for the given date+user (or return existing)."""
    db = await get_db()
    try:
        await db.execute("BEGIN IMMEDIATE")
        cursor = await db.execute(
            "SELECT id FROM diaries WHERE date = ? AND user_id = ?",
            (req.date, user_id),
        )
        row = await cursor.fetchone()
        if row:
            diary_id = row["id"]
        else:
            cursor = await db.execute(
                "INSERT INTO diaries (date, text, status, source, user_id) "
                "VALUES (?, '', 'draft', 'manual', ?)",
                (req.date, user_id),
            )
            diary_id = cursor.lastrowid
        await db.commit()
        return await _fetch_diary_with_images(db, diary_id, user_id)
    except Exception:
        await db.rollback()
        raise
    finally:
        await db.close()


@router.post("/{diary_id}/ai-fill")
async def ai_fill(
    diary_id: int,
    req: AiFillRequest,
    _: None = Depends(require_same_origin),
    user_id: int = Depends(get_current_user_id),
):
    """Fill a diary from its saved text and selected daily source records."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM diaries WHERE id = ? AND user_id = ?",
            (diary_id, user_id),
        )
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="diary not found")
        diary = dict(row)
        date = diary["date"]
        draft_text = diary.get("draft_text") or ""
        saved_text = diary.get("text") or ""
        text = draft_text if draft_text.strip() else saved_text

        fragments = await _fetch_selected_fragments(
            db,
            date=date,
            user_id=user_id,
            requested_ids=req.fragment_ids,
        )
        fragments = [
            fragment
            for fragment in fragments
            if (fragment.get("content") or "").strip()
            or (fragment.get("photo_description") or "").strip()
        ]

        if not text.strip() and not fragments:
            raise HTTPException(status_code=400, detail="当天没有任何记录，无法用 AI 填充")
        # 遵循 SEC-INPUT-001 规范: 限制聚合来源长度，拒绝超限输入。
        if diary_source_char_count(text, fragments) > DIARY_SOURCE_CHAR_LIMIT:
            raise HTTPException(
                status_code=400,
                detail=(
                    "AI 填充内容总长度不能超过 "
                    f"{DIARY_SOURCE_CHAR_LIMIT} 字符"
                ),
            )

        try:
            diary_text = await generate_diary(
                text=text,
                fragments=fragments,
                allow_imaginative=req.emotion_mode == "imagery",
            )
        except GenerationServiceError as exc:
            raise_generation_http_error(exc, service="AI")

        # If user had manual text → mark as hybrid; otherwise ai
        new_source = "hybrid" if text.strip() else "ai"

        await db.execute(
            "UPDATE diaries SET text = ?, draft_text = ?, emotion_mode = ?, "
            "source = ? WHERE id = ? AND user_id = ?",
            (
                diary_text,
                diary_text,
                req.emotion_mode,
                new_source,
                diary_id,
                user_id,
            ),
        )
        await db.commit()
        return await _fetch_diary_with_images(db, diary_id, user_id)
    finally:
        await db.close()


@router.post("/{diary_id}/ai-rewrite")
async def ai_rewrite(
    diary_id: int,
    req: AiRewriteRequest,
    _: None = Depends(require_same_origin),
    user_id: int = Depends(get_current_user_id),
):
    """Rewrite a single paragraph. Does not touch DB — returns the rewritten text for the frontend to splice in."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT id FROM diaries WHERE id = ? AND user_id = ?",
            (diary_id, user_id),
        )
        if not await cursor.fetchone():
            raise HTTPException(status_code=404, detail="diary not found")
    finally:
        await db.close()

    try:
        rewritten = await rewrite_paragraph(
            req.paragraph, req.direction, req.custom_prompt
        )
    except GenerationServiceError as exc:
        raise_generation_http_error(exc, service="AI")
    return {"original": req.paragraph, "rewritten": rewritten, "direction": req.direction}


@router.get("")
async def get_diary(date: str, user_id: int = Depends(get_current_user_id)):
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT id FROM diaries WHERE date = ? AND user_id = ?",
            (date, user_id),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        return await _fetch_diary_with_images(db, row["id"], user_id)
    finally:
        await db.close()


@router.get("/list")
async def list_diaries(
    page: int = 1,
    page_size: int = 50,
    status: str = "all",
    user_id: int = Depends(get_current_user_id),
):
    db = await get_db()
    try:
        offset = (page - 1) * page_size
        clauses = ["user_id = ?"]
        params: list = [user_id]
        if status != "all":
            clauses.append("status = ?")
            params.append(status)
        where = "WHERE " + " AND ".join(clauses)
        params.extend([page_size, offset])
        cursor = await db.execute(
            f"SELECT id FROM diaries {where} ORDER BY date DESC LIMIT ? OFFSET ?",
            params,
        )
        ids = [r["id"] for r in await cursor.fetchall()]
        result = []
        for diary_id in ids:
            diary = await _fetch_diary_with_images(db, diary_id, user_id)
            if diary:
                result.append(diary)
        return result
    finally:
        await db.close()


@router.put("/{diary_id}")
async def update_diary(
    diary_id: int,
    req: DiaryUpdateRequest,
    _: None = Depends(require_same_origin),
    user_id: int = Depends(get_current_user_id),
):
    db = await get_db()
    try:
        payload = req.model_dump(exclude_unset=True)
        if not payload:
            cursor = await db.execute(
                "SELECT 1 FROM diaries WHERE id = ? AND user_id = ?",
                (diary_id, user_id),
            )
            if not await cursor.fetchone():
                raise HTTPException(status_code=404, detail="diary not found")
            return {"message": "nothing to update"}

        updates = []
        values = []
        for field, value in payload.items():
            updates.append(f"{field} = ?")
            values.append(value)

        if payload.get("status") == "confirmed":
            updates.append("confirmed_at = ?")
            values.append(datetime.utcnow().isoformat())

        values.extend([diary_id, user_id])
        cursor = await db.execute(
            f"UPDATE diaries SET {', '.join(updates)} "
            "WHERE id = ? AND user_id = ?",
            values,
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="diary not found")
        await db.commit()
        return await _fetch_diary_with_images(db, diary_id, user_id)
    finally:
        await db.close()


@router.delete("/{diary_id}", status_code=204)
async def delete_diary(
    diary_id: int,
    _: None = Depends(require_same_origin),
    user_id: int = Depends(get_current_user_id),
):
    db = await get_db()
    try:
        await db.execute("BEGIN IMMEDIATE")
        cursor = await db.execute(
            "SELECT id FROM diaries WHERE id = ? AND user_id = ?",
            (diary_id, user_id),
        )
        if not await cursor.fetchone():
            await db.rollback()
            raise HTTPException(status_code=404, detail="diary not found")

        await db.execute("DELETE FROM images WHERE diary_id = ?", (diary_id,))
        await db.execute(
            "DELETE FROM diaries WHERE id = ? AND user_id = ?",
            (diary_id, user_id),
        )
        await db.commit()
        return Response(status_code=204)
    except HTTPException:
        raise
    except Exception:
        await db.rollback()
        raise
    finally:
        await db.close()
