from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from database import get_db
from agents.diary_agent import generate_diary, rewrite_paragraph

router = APIRouter()


class DiaryCreateRequest(BaseModel):
    date: str
    user_id: int = 1


class DiaryGenerateRequest(BaseModel):
    date: str
    emotion_mode: str = "warm"
    custom_emotion_prompt: Optional[str] = None
    user_id: int = 1


class DiaryUpdateRequest(BaseModel):
    text: Optional[str] = None
    draft_text: Optional[str] = None
    status: Optional[str] = None
    source: Optional[str] = None


class AiFillRequest(BaseModel):
    emotion_mode: str = "warm"
    custom_emotion_prompt: Optional[str] = None


class AiRewriteRequest(BaseModel):
    paragraph: str
    direction: str = "warmer"
    custom_prompt: Optional[str] = None


async def _fetch_diary_with_images(db, diary_id: int) -> Optional[dict]:
    cursor = await db.execute("SELECT * FROM diaries WHERE id = ?", (diary_id,))
    row = await cursor.fetchone()
    if not row:
        return None
    diary = dict(row)
    cursor = await db.execute(
        "SELECT id, diary_id, style, style_prompt, url, created_at, kept FROM images WHERE diary_id = ? AND kept = 1 ORDER BY created_at",
        (diary_id,),
    )
    diary["images"] = [dict(r) for r in await cursor.fetchall()]
    return diary


@router.post("")
async def create_blank(req: DiaryCreateRequest):
    """Create a blank manual diary for the given date+user (or return existing)."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT id FROM diaries WHERE date = ? AND user_id = ?",
            (req.date, req.user_id),
        )
        row = await cursor.fetchone()
        if row:
            return await _fetch_diary_with_images(db, row["id"])
        cursor = await db.execute(
            "INSERT INTO diaries (date, text, status, source, user_id) VALUES (?, '', 'draft', 'manual', ?)",
            (req.date, req.user_id),
        )
        diary_id = cursor.lastrowid
        await db.commit()
        return await _fetch_diary_with_images(db, diary_id)
    finally:
        await db.close()


@router.post("/generate")
async def generate(req: DiaryGenerateRequest):
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM schedules WHERE date = ? AND user_id = ?",
            (req.date, req.user_id),
        )
        schedules = [dict(row) for row in await cursor.fetchall()]
        for s in schedules:
            s["completed"] = bool(s["completed"])

        cursor = await db.execute(
            "SELECT * FROM fragments WHERE date = ? AND user_id = ?",
            (req.date, req.user_id),
        )
        fragments = [dict(row) for row in await cursor.fetchall()]

        if not schedules and not fragments:
            raise HTTPException(status_code=400, detail="当天没有任何记录，无法生成日记")

        diary_text = await generate_diary(
            date=req.date,
            schedules=schedules,
            fragments=fragments,
            emotion_mode=req.emotion_mode,
            custom_emotion_prompt=req.custom_emotion_prompt,
        )

        existing = await db.execute(
            "SELECT id FROM diaries WHERE date = ? AND user_id = ?",
            (req.date, req.user_id),
        )
        row = await existing.fetchone()

        if row:
            await db.execute(
                "UPDATE diaries SET text = ?, draft_text = ?, emotion_mode = ?, status = 'draft', source = 'ai', confirmed_at = NULL WHERE id = ?",
                (diary_text, diary_text, req.emotion_mode, row["id"]),
            )
            diary_id = row["id"]
        else:
            cursor = await db.execute(
                "INSERT INTO diaries (date, text, draft_text, emotion_mode, status, source, user_id) "
                "VALUES (?, ?, ?, ?, 'draft', 'ai', ?)",
                (req.date, diary_text, diary_text, req.emotion_mode, req.user_id),
            )
            diary_id = cursor.lastrowid

        await db.commit()
        return await _fetch_diary_with_images(db, diary_id)
    finally:
        await db.close()


@router.post("/{diary_id}/ai-fill")
async def ai_fill(diary_id: int, req: AiFillRequest):
    """Use AI to fill a diary using the day's schedules + fragments. Writes to draft_text and updates source to 'hybrid' or 'ai'."""
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM diaries WHERE id = ?", (diary_id,))
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="diary not found")
        diary = dict(row)
        date = diary["date"]

        diary_user_id = diary["user_id"]
        cursor = await db.execute(
            "SELECT * FROM schedules WHERE date = ? AND user_id = ?",
            (date, diary_user_id),
        )
        schedules = [dict(r) for r in await cursor.fetchall()]
        for s in schedules:
            s["completed"] = bool(s["completed"])
        cursor = await db.execute(
            "SELECT * FROM fragments WHERE date = ? AND user_id = ?",
            (date, diary_user_id),
        )
        fragments = [dict(r) for r in await cursor.fetchall()]

        if not schedules and not fragments:
            raise HTTPException(status_code=400, detail="当天没有任何记录，无法用 AI 填充")

        diary_text = await generate_diary(
            date=date,
            schedules=schedules,
            fragments=fragments,
            emotion_mode=req.emotion_mode,
            custom_emotion_prompt=req.custom_emotion_prompt,
        )

        # If user had manual text → mark as hybrid; otherwise ai
        new_source = "hybrid" if (diary.get("text") or "").strip() else "ai"

        await db.execute(
            "UPDATE diaries SET text = ?, draft_text = ?, emotion_mode = ?, source = ? WHERE id = ?",
            (diary_text, diary_text, req.emotion_mode, new_source, diary_id),
        )
        await db.commit()
        return await _fetch_diary_with_images(db, diary_id)
    finally:
        await db.close()


@router.post("/{diary_id}/ai-rewrite")
async def ai_rewrite(diary_id: int, req: AiRewriteRequest):
    """Rewrite a single paragraph. Does not touch DB — returns the rewritten text for the frontend to splice in."""
    db = await get_db()
    try:
        cursor = await db.execute("SELECT id FROM diaries WHERE id = ?", (diary_id,))
        if not await cursor.fetchone():
            raise HTTPException(status_code=404, detail="diary not found")
    finally:
        await db.close()

    rewritten = await rewrite_paragraph(req.paragraph, req.direction, req.custom_prompt)
    return {"original": req.paragraph, "rewritten": rewritten, "direction": req.direction}


@router.get("")
async def get_diary(date: str, user_id: int = 1):
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT id FROM diaries WHERE date = ? AND user_id = ?",
            (date, user_id),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        return await _fetch_diary_with_images(db, row["id"])
    finally:
        await db.close()


@router.get("/list")
async def list_diaries(
    page: int = 1, page_size: int = 50, status: str = "all", user_id: int = 1
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
            diary = await _fetch_diary_with_images(db, diary_id)
            if diary:
                result.append(diary)
        return result
    finally:
        await db.close()


@router.put("/{diary_id}")
async def update_diary(diary_id: int, req: DiaryUpdateRequest):
    db = await get_db()
    try:
        payload = req.model_dump(exclude_unset=True)
        if not payload:
            return {"message": "nothing to update"}

        updates = []
        values = []
        for field, value in payload.items():
            updates.append(f"{field} = ?")
            values.append(value)

        if payload.get("status") == "confirmed":
            updates.append("confirmed_at = ?")
            values.append(datetime.utcnow().isoformat())

        values.append(diary_id)
        await db.execute(f"UPDATE diaries SET {', '.join(updates)} WHERE id = ?", values)
        await db.commit()
        return await _fetch_diary_with_images(db, diary_id)
    finally:
        await db.close()
