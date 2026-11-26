from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Optional
from auth.dependencies import get_current_user_id, require_same_origin
from database import get_db
from services.character_assets import load_character_reference
from services.media_store import (
    MediaStoreError,
    staged_generated_media,
    store_generated_asset,
)
from services.generation_errors import (
    GenerationServiceError,
    raise_generation_http_error,
)

router = APIRouter()

class BatchGenerateRequest(BaseModel):
    style: str = "watercolor"
    custom_style_prompt: Optional[str] = None
    paragraphs: list[str] = Field(default_factory=list)


class KeepImagesRequest(BaseModel):
    keep_ids: list[int]


@router.post("/diary/{diary_id}/images/batch")
async def batch_generate(
    diary_id: int,
    req: BatchGenerateRequest,
    _: None = Depends(require_same_origin),
    user_id: int = Depends(get_current_user_id),
):
    """Generate N candidate images for the diary. All saved with kept=0 initially. Frontend later calls PUT to keep selected ones."""
    from agents.image_agent import generate_batch
    db = await get_db()
    try:
        # 遵循 SEC-AUTH-002 规范: diary lookup is scoped to the session owner.
        cursor = await db.execute(
            "SELECT * FROM diaries WHERE id = ? AND user_id = ?",
            (diary_id, user_id),
        )
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="diary not found")
        diary = dict(row)
        diary_text = diary.get("draft_text") or diary.get("text") or ""
        if not diary_text.strip():
            raise HTTPException(status_code=400, detail="diary has no text — write or generate text first")

        # The confirmed character stars in the illustration, so the same person
        # shows up across every picturebook page. Without one we fall back to a
        # plain scene rather than blocking generation.
        character = await load_character_reference(db, user_id)

        try:
            urls = await generate_batch(
                diary_text=diary_text,
                paragraphs=req.paragraphs,
                style=req.style,
                custom_style_prompt=req.custom_style_prompt,
                character=character,
            )
        except GenerationServiceError as exc:
            raise_generation_http_error(exc, service="image")

        async with staged_generated_media(db) as media_stage:
            assets = []
            for url in urls:
                try:
                    assets.append(
                        await store_generated_asset(
                            db,
                            user_id,
                            url,
                            stage=media_stage,
                        )
                    )
                except MediaStoreError as exc:
                    raise HTTPException(
                        status_code=400, detail="generated image is invalid"
                    ) from exc

            saved: list[dict] = []
            for asset in assets:
                cursor = await db.execute(
                    "INSERT INTO images "
                    "(diary_id, style, style_prompt, url, kept, asset_id) "
                    "VALUES (?, ?, ?, ?, 0, ?)",
                    (
                        diary_id,
                        req.style,
                        req.custom_style_prompt,
                        asset.url,
                        asset.id,
                    ),
                )
                new_id = cursor.lastrowid
                cursor = await db.execute(
                    "SELECT i.id, i.diary_id, i.style, i.style_prompt, i.url, "
                    "i.created_at, i.kept, i.asset_id FROM images i "
                    "JOIN diaries d ON d.id = i.diary_id "
                    "WHERE i.id = ? AND d.user_id = ?",
                    (new_id, user_id),
                )
                row = await cursor.fetchone()
                saved.append(dict(row))
        return {"candidates": saved}
    finally:
        await db.close()


@router.put("/diary/{diary_id}/images")
async def keep_images(
    diary_id: int,
    req: KeepImagesRequest,
    _: None = Depends(require_same_origin),
    user_id: int = Depends(get_current_user_id),
):
    """Set kept=1 on the listed image ids belonging to this diary, kept=0 on the rest (they were candidates not chosen)."""
    db = await get_db()
    try:
        # 遵循 SEC-AUTH-002 规范: do not reveal or mutate a foreign diary.
        cursor = await db.execute(
            "SELECT id FROM diaries WHERE id = ? AND user_id = ?",
            (diary_id, user_id),
        )
        if not await cursor.fetchone():
            raise HTTPException(status_code=404, detail="diary not found")

        keep_ids = list(dict.fromkeys(req.keep_ids))
        if keep_ids:
            placeholders = ",".join("?" for _ in keep_ids)
            cursor = await db.execute(
                "SELECT i.id FROM images i "
                "JOIN diaries d ON d.id = i.diary_id "
                f"WHERE i.diary_id = ? AND d.user_id = ? "
                f"AND i.id IN ({placeholders})",
                [diary_id, user_id, *keep_ids],
            )
            owned_ids = {row["id"] for row in await cursor.fetchall()}
            if owned_ids != set(keep_ids):
                raise HTTPException(status_code=404, detail="image not found")

        await db.execute(
            "UPDATE images SET kept = 0 WHERE diary_id = ? "
            "AND EXISTS (SELECT 1 FROM diaries d "
            "WHERE d.id = images.diary_id AND d.user_id = ?)",
            (diary_id, user_id),
        )
        if keep_ids:
            placeholders = ",".join("?" for _ in keep_ids)
            await db.execute(
                f"UPDATE images SET kept = 1 WHERE diary_id = ? "
                f"AND id IN ({placeholders}) "
                "AND EXISTS (SELECT 1 FROM diaries d "
                "WHERE d.id = images.diary_id AND d.user_id = ?)",
                [diary_id, *keep_ids, user_id],
            )
        await db.commit()
        cursor = await db.execute(
            "SELECT i.id, i.diary_id, i.style, i.style_prompt, i.url, "
            "i.created_at, i.kept, i.asset_id FROM images i "
            "JOIN diaries d ON d.id = i.diary_id "
            "WHERE i.diary_id = ? AND i.kept = 1 AND d.user_id = ? "
            "ORDER BY i.created_at",
            (diary_id, user_id),
        )
        return {"images": [dict(r) for r in await cursor.fetchall()]}
    finally:
        await db.close()
