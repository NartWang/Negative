from __future__ import annotations

from datetime import date as date_type
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from auth.dependencies import get_current_user_id, require_same_origin
from database import get_db
from services.pdf_export import (
    DayPdfSelection,
    build_legacy_day_pdf,
    build_picturebook_pdf,
    build_selected_day_pdf,
    build_time_story_pdf,
    day_export_availability,
)

# 兼容:既有测试与外部调用方曾 monkeypatch routers.export 的构造符号。
# 真正的构造已下沉到 services/pdf_export.py,这里只做再导出。
from services import pdf_export as _pdf_export_impl

DayCover = _pdf_export_impl.DayCover
SimpleDocTemplate = _pdf_export_impl.SimpleDocTemplate
RLImage = _pdf_export_impl.RLImage

router = APIRouter()


@router.post("/picturebook/{source_kind}/{source_id}/pdf")
async def export_picturebook_pdf(
    source_kind: str,
    source_id: int,
    _: None = Depends(require_same_origin),
    user_id: int = Depends(get_current_user_id),
):
    if source_kind not in ("canonical_work", "historical_job"):
        raise HTTPException(status_code=404, detail="picturebook not found")
    db = await get_db()
    try:
        buf = await build_picturebook_pdf(db, user_id, source_kind, source_id)
    finally:
        await db.close()
    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f'attachment; filename="zhiji-picturebook-{source_kind}-{source_id}.pdf"'
            )
        },
    )


@router.post("/pdf")
async def export_pdf(
    _: None = Depends(require_same_origin),
    user_id: int = Depends(get_current_user_id),
):
    # 全量日记导出保持原实现;与底片夹按日/时光故事导出互不干扰。
    import io
    from xml.sax.saxutils import escape

    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        PageBreak,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
    )
    from reportlab.platypus import Image as RLImage

    from services.pdf_export import _register_cjk_font, _resolve_image_path

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
    # 构造类在调用时解析,保持测试对 routers.export 打补丁的能力。
    doc_class = globals()["SimpleDocTemplate"]
    doc = doc_class(
        buf,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("Title", parent=styles["Title"], fontName=font_name, fontSize=22, leading=28)
    date_style = ParagraphStyle("Date", parent=styles["Normal"], fontName=font_name, fontSize=14, textColor="#9585A8", spaceAfter=12)
    body_style = ParagraphStyle("Body", parent=styles["Normal"], fontName=font_name, fontSize=12, leading=20, alignment=TA_LEFT, spaceAfter=8)

    flow = [Paragraph("底片 · 日记本", title_style), Spacer(1, 12 * mm)]

    for i, d in enumerate(diaries):
        flow.append(Paragraph(escape(str(d["date"])), date_style))
        text = (d.get("text") or "").strip()
        for para in text.split("\n\n"):
            if para.strip():
                flow.append(
                    Paragraph(escape(para).replace("\n", "<br/>"), body_style)
                )
        image_class = globals()["RLImage"]
        for path in d["image_paths"]:
            try:
                flow.append(Spacer(1, 4 * mm))
                flow.append(
                    image_class(
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


def _parse_day(date: str) -> str:
    # 遵循 SEC-INPUT-001 规范: 路径日期参数必须先按 ISO date 格式校验。
    try:
        return date_type.fromisoformat(date).isoformat()
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid date") from None


@router.get("/day/{date}/availability")
async def get_day_export_availability(
    date: str,
    user_id: int = Depends(get_current_user_id),
):
    day = _parse_day(date)
    db = await get_db()
    try:
        return await day_export_availability(db, user_id, day)
    finally:
        await db.close()


@router.post("/day/{date}/pdf")
async def export_day_pdf(
    date: str,
    payload: Optional[DayPdfSelection] = None,
    _: None = Depends(require_same_origin),
    user_id: int = Depends(get_current_user_id),
):
    day = _parse_day(date)
    db = await get_db()
    try:
        if payload is None:
            buf = await build_legacy_day_pdf(db, user_id, day)
        else:
            buf = await build_selected_day_pdf(db, user_id, day, payload)
    finally:
        await db.close()
    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="zhiji-{day}.pdf"'},
    )


@router.post("/time-story/{work_id}/pdf")
async def export_time_story_pdf(
    work_id: int,
    _: None = Depends(require_same_origin),
    user_id: int = Depends(get_current_user_id),
):
    db = await get_db()
    try:
        buf = await build_time_story_pdf(db, user_id, work_id)
    finally:
        await db.close()
    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f'attachment; filename="zhiji-time-story-{work_id}.pdf"'
            )
        },
    )
