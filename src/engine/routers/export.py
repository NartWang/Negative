from __future__ import annotations

import io
import os
from xml.sax.saxutils import escape

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.enums import TA_LEFT
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image as RLImage, PageBreak
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from auth.dependencies import get_current_user_id, require_same_origin
from database import get_db
from services.media_store import (
    MediaStoreError,
    asset_file_path,
    legacy_file_path,
    legacy_url_is_owned,
    require_owned_asset,
)

router = APIRouter()

def _register_cjk_font() -> str:
    """Register a CJK-capable font if available on the system, return font name to use."""
    candidates = [
        ("/System/Library/Fonts/PingFang.ttc", "PingFang"),
        ("/System/Library/Fonts/STHeiti Light.ttc", "STHeiti"),
        ("/System/Library/Fonts/Hiragino Sans GB.ttc", "HiraginoSansGB"),
        ("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc", "WQYZenHei"),
    ]
    for path, name in candidates:
        if os.path.exists(path):
            try:
                pdfmetrics.registerFont(TTFont(name, path))
                return name
            except Exception:
                continue
    return "Helvetica"


async def _resolve_image_path(db, user_id: int, url: str, asset_id: str | None):
    try:
        if asset_id:
            asset = await require_owned_asset(db, user_id, asset_id)
            path = asset_file_path(asset)
            return path if path.is_file() else None
        if url and url.startswith("/api/upload/"):
            if not await legacy_url_is_owned(db, user_id, url):
                return None
            return legacy_file_path(url)
    except MediaStoreError:
        return None
    return None


@router.post("/pdf")
async def export_pdf(
    _: None = Depends(require_same_origin),
    user_id: int = Depends(get_current_user_id),
):
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT id, date, text, draft_text, source FROM diaries WHERE status = 'confirmed' AND user_id = ? ORDER BY date ASC",
            (user_id,),
        )
        diaries = [dict(r) for r in await cursor.fetchall()]
        if not diaries:
            raise HTTPException(status_code=400, detail="还没有已确认的日记，无法导出")

        for d in diaries:
            cursor = await db.execute(
                "SELECT url, asset_id FROM images "
                "WHERE diary_id = ? AND kept = 1 ORDER BY created_at",
                (d["id"],),
            )
            d["image_paths"] = [
                path
                for row in await cursor.fetchall()
                if (
                    path := await _resolve_image_path(
                        db, user_id, row["url"], row["asset_id"]
                    )
                )
                is not None
            ]
    finally:
        await db.close()

    font_name = _register_cjk_font()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm, topMargin=20 * mm, bottomMargin=20 * mm)

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("Title", parent=styles["Title"], fontName=font_name, fontSize=22, leading=28)
    date_style = ParagraphStyle("Date", parent=styles["Normal"], fontName=font_name, fontSize=14, textColor="#9585A8", spaceAfter=12)
    body_style = ParagraphStyle("Body", parent=styles["Normal"], fontName=font_name, fontSize=12, leading=20, alignment=TA_LEFT, spaceAfter=8)

    flow = [Paragraph("知己 · 日记本", title_style), Spacer(1, 12 * mm)]

    for i, d in enumerate(diaries):
        flow.append(Paragraph(escape(str(d["date"])), date_style))
        text = (d.get("text") or "").strip()
        for para in text.split("\n\n"):
            if para.strip():
                flow.append(
                    Paragraph(escape(para).replace("\n", "<br/>"), body_style)
                )
        for path in d["image_paths"]:
            try:
                flow.append(Spacer(1, 4 * mm))
                flow.append(
                    RLImage(
                        path,
                        width=150 * mm,
                        height=150 * mm,
                        kind="proportional",
                    )
                )
            except Exception:
                pass
        if i < len(diaries) - 1:
            flow.append(PageBreak())

    doc.build(flow)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="zhiji-diaries.pdf"'},
    )
