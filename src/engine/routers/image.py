import os
import re
import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from database import get_db
from agents.image_agent import generate_image, build_image_prompt, STYLE_PROMPTS

router = APIRouter()

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

_SAFE_STYLE_RE = re.compile(r"[^a-zA-Z0-9_-]")


def _safe_style_token(style: str) -> str:
    if style in STYLE_PROMPTS:
        return style
    return _SAFE_STYLE_RE.sub("", style)[:32] or "custom"


class ImageGenerateRequest(BaseModel):
    diary_id: int
    style: str = "ghibli"
    custom_style_prompt: Optional[str] = None


@router.post("/generate")
async def generate(req: ImageGenerateRequest):
    db = await get_db()
    try:
        # Get diary text
        cursor = await db.execute("SELECT * FROM diaries WHERE id = ?", (req.diary_id,))
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="diary not found")

        diary = dict(row)

        # Generate image
        image_url = await generate_image(
            diary_text=diary["text"],
            style=req.style,
            custom_style_prompt=req.custom_style_prompt,
        )

        # If the AI returns a URL, download and save locally
        local_url = image_url
        if image_url.startswith("http"):
            async with httpx.AsyncClient(timeout=30) as client:
                img_response = await client.get(image_url)
                img_response.raise_for_status()
                # count existing images for naming
                cursor = await db.execute("SELECT COUNT(*) as c FROM images WHERE diary_id = ?", (req.diary_id,))
                count_row = await cursor.fetchone()
                existing_count = count_row["c"] if count_row else 0
                safe_style = _safe_style_token(req.style)
                filename = f"diary_{req.diary_id}_{safe_style}_{existing_count}.png"
                filepath = os.path.join(UPLOAD_DIR, filename)
                with open(filepath, "wb") as f:
                    f.write(img_response.content)
                local_url = f"/api/upload/{filename}"

        # Save to DB
        ai_prompt = build_image_prompt(diary["text"], req.style, req.custom_style_prompt)

        cursor = await db.execute(
            "INSERT INTO images (diary_id, style, style_prompt, url, ai_prompt) VALUES (?, ?, ?, ?, ?)",
            (req.diary_id, req.style, req.custom_style_prompt, local_url, ai_prompt),
        )
        new_id = cursor.lastrowid
        await db.commit()

        cursor = await db.execute(
            "SELECT id, diary_id, style, style_prompt, url, created_at FROM images WHERE id = ?",
            (new_id,),
        )
        row = await cursor.fetchone()
        return dict(row)
    finally:
        await db.close()


@router.get("/{image_id}")
async def get_image(image_id: int):
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT id, diary_id, style, style_prompt, url, created_at FROM images WHERE id = ?",
            (image_id,),
        )
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="image not found")
        return dict(row)
    finally:
        await db.close()


class BatchGenerateRequest(BaseModel):
    style: str = "ghibli"
    custom_style_prompt: Optional[str] = None
    paragraphs: list[str] = []
    n: int = 4


class KeepImagesRequest(BaseModel):
    keep_ids: list[int]


@router.post("/diary/{diary_id}/images/batch")
async def batch_generate(diary_id: int, req: BatchGenerateRequest):
    """Generate N candidate images for the diary. All saved with kept=0 initially. Frontend later calls PUT to keep selected ones."""
    from agents.image_agent import generate_batch
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM diaries WHERE id = ?", (diary_id,))
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="diary not found")
        diary = dict(row)
        diary_text = diary.get("draft_text") or diary.get("text") or ""
        if not diary_text.strip():
            raise HTTPException(status_code=400, detail="diary has no text — write or generate text first")

        urls = await generate_batch(
            diary_text=diary_text,
            paragraphs=req.paragraphs,
            style=req.style,
            n=req.n,
            custom_style_prompt=req.custom_style_prompt,
        )

        ai_prompt = build_image_prompt(diary_text, req.style, req.custom_style_prompt)
        saved: list[dict] = []
        for url in urls:
            local_url = url
            if url.startswith("http"):
                async with httpx.AsyncClient(timeout=30) as client:
                    img_response = await client.get(url)
                    img_response.raise_for_status()
                    cursor = await db.execute(
                        "SELECT COUNT(*) as c FROM images WHERE diary_id = ?", (diary_id,)
                    )
                    count_row = await cursor.fetchone()
                    existing_count = count_row["c"] if count_row else 0
                    safe_style = _safe_style_token(req.style)
                    filename = f"diary_{diary_id}_{safe_style}_{existing_count + len(saved)}.png"
                    filepath = os.path.join(UPLOAD_DIR, filename)
                    with open(filepath, "wb") as f:
                        f.write(img_response.content)
                    local_url = f"/api/upload/{filename}"

            cursor = await db.execute(
                "INSERT INTO images (diary_id, style, style_prompt, url, ai_prompt, kept) VALUES (?, ?, ?, ?, ?, 0)",
                (diary_id, req.style, req.custom_style_prompt, local_url, ai_prompt),
            )
            new_id = cursor.lastrowid
            cursor = await db.execute(
                "SELECT id, diary_id, style, style_prompt, url, created_at, kept FROM images WHERE id = ?",
                (new_id,),
            )
            row = await cursor.fetchone()
            saved.append(dict(row))
        await db.commit()
        return {"candidates": saved}
    finally:
        await db.close()


@router.put("/diary/{diary_id}/images")
async def keep_images(diary_id: int, req: KeepImagesRequest):
    """Set kept=1 on the listed image ids belonging to this diary, kept=0 on the rest (they were candidates not chosen)."""
    db = await get_db()
    try:
        cursor = await db.execute("SELECT id FROM diaries WHERE id = ?", (diary_id,))
        if not await cursor.fetchone():
            raise HTTPException(status_code=404, detail="diary not found")
        await db.execute("UPDATE images SET kept = 0 WHERE diary_id = ? AND kept = 0", (diary_id,))
        if req.keep_ids:
            placeholders = ",".join("?" for _ in req.keep_ids)
            params = [diary_id] + req.keep_ids
            await db.execute(
                f"UPDATE images SET kept = 1 WHERE diary_id = ? AND id IN ({placeholders})",
                params,
            )
        await db.commit()
        cursor = await db.execute(
            "SELECT id, diary_id, style, style_prompt, url, created_at, kept FROM images WHERE diary_id = ? AND kept = 1 ORDER BY created_at",
            (diary_id,),
        )
        return {"images": [dict(r) for r in await cursor.fetchall()]}
    finally:
        await db.close()
