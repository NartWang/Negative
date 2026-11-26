"""PDF 导出服务:持有全部 ReportLab 构造细节,路由只做鉴权与流式响应。

规格第八节:
- 按日导出支持可选正文(日记含照片 / 当天绘本),至少一项;
- 旧调用方不传请求体时保持旧版固定流;
- 时光故事单独导出,只含封面与完整绘本页;
- 媒体一律先做当前用户所有权校验;缺失/损坏图片跳过,不中断整份导出;
- 所选内容最终为空时返回 400。
"""

from __future__ import annotations

import io
import os
from datetime import date as date_type
from pathlib import Path
from typing import Any, Optional
from xml.sax.saxutils import escape

from fastapi import HTTPException
from pydantic import BaseModel, model_validator
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Flowable,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
)
from reportlab.platypus import Image as RLImage
from PIL import Image as PILImage

from services.media_store import (
    MediaStoreError,
    asset_file_path,
    get_authorized_asset,
    legacy_file_path,
    legacy_url_is_owned,
    parse_canonical_media_url,
    require_owned_asset,
)
from services.story_days import get_story_day, list_completed_picturebooks
from services.film_folder import get_picturebook_detail, is_demo_subscriber
import config


class DayPdfSelection(BaseModel):
    include_diary: bool = False
    include_picturebooks: bool = False

    @model_validator(mode="after")
    def require_content(self):
        if not self.include_diary and not self.include_picturebooks:
            raise ValueError("at least one export section is required")
        return self


class DayCover(Flowable):
    """Full-bleed day image with date and summary drawn over the lower edge."""

    def __init__(
        self,
        cover_path: Path | None,
        date_text: str,
        summary: str,
        font_name: str,
    ):
        super().__init__()
        self.cover_path = cover_path
        self.date_text = date_text
        self.summary = summary
        self.font_name = font_name
        self.width = 174 * mm
        self.height = 245 * mm

    def wrap(self, available_width, available_height):
        self.width = min(self.width, available_width)
        self.height = min(self.height, available_height)
        return self.width, self.height

    def getPlainText(self):
        return "|".join(value for value in (self.date_text, self.summary) if value)

    def _draw_background(self):
        canvas = self.canv
        canvas.setFillColor(colors.HexColor("#70637F"))
        canvas.rect(0, 0, self.width, self.height, stroke=0, fill=1)
        if self.cover_path is None:
            return
        try:
            image = ImageReader(str(self.cover_path))
            image_width, image_height = image.getSize()
            scale = max(self.width / image_width, self.height / image_height)
            draw_width = image_width * scale
            draw_height = image_height * scale
            clip = canvas.beginPath()
            clip.rect(0, 0, self.width, self.height)
            canvas.clipPath(clip, stroke=0, fill=0)
            canvas.drawImage(
                image,
                (self.width - draw_width) / 2,
                (self.height - draw_height) / 2,
                width=draw_width,
                height=draw_height,
                mask="auto",
            )
        except Exception:
            # An unreadable owned file falls back to the solid cover above.
            return

    def draw(self):
        canvas = self.canv
        canvas.saveState()
        self._draw_background()
        overlay_height = 78 * mm
        if hasattr(canvas, "setFillAlpha"):
            canvas.setFillAlpha(0.68)
        canvas.setFillColor(colors.black)
        canvas.rect(0, 0, self.width, overlay_height, stroke=0, fill=1)
        if hasattr(canvas, "setFillAlpha"):
            canvas.setFillAlpha(1)

        content_width = self.width - 24 * mm
        summary_style = ParagraphStyle(
            "DayCoverSummary",
            fontName=self.font_name,
            fontSize=13,
            leading=19,
            textColor=colors.white,
        )
        date_style = ParagraphStyle(
            "DayCoverDate",
            fontName=self.font_name,
            fontSize=21,
            leading=27,
            textColor=colors.white,
        )
        summary = Paragraph(escape(self.summary), summary_style) if self.summary else None
        summary_height = 0
        if summary is not None:
            _, summary_height = summary.wrap(content_width, 38 * mm)
            summary.drawOn(canvas, 12 * mm, 12 * mm)
        date = Paragraph(escape(self.date_text), date_style)
        _, date_height = date.wrap(content_width, 30 * mm)
        date.drawOn(canvas, 12 * mm, 18 * mm + summary_height, _sW=0)
        canvas.restoreState()


class PicturebookExportPage(Flowable):
    """One landscape PDF page that keeps an illustration and caption together."""

    def __init__(self, image_path, caption, font_name, page_number, *, cover=False, title="", date_text=""):
        super().__init__()
        self.image_path = image_path
        self.image_source = self._optimized_image(image_path)
        self.caption = caption
        self.font_name = font_name
        self.page_number = page_number
        self.cover = cover
        self.title = title
        self.date_text = date_text
        self.width = 267 * mm
        self.height = 180 * mm

    @staticmethod
    def _optimized_image(image_path):
        """Downsample only the PDF copy; original story assets stay untouched."""
        if image_path is None:
            return None
        try:
            with PILImage.open(image_path) as image:
                image.thumbnail((1800, 1200), PILImage.Resampling.LANCZOS)
                if image.mode != "RGB":
                    background = PILImage.new("RGB", image.size, "white")
                    if "A" in image.getbands():
                        background.paste(image, mask=image.getchannel("A"))
                    else:
                        background.paste(image)
                    image = background
                output = io.BytesIO()
                image.save(output, format="JPEG", quality=88, optimize=True)
                output.seek(0)
                return output
        except Exception:
            return image_path

    def wrap(self, available_width, available_height):
        self.width = available_width
        self.height = available_height
        return self.width, self.height

    def _draw_contained_image(self, x, y, width, height):
        if self.image_source is None:
            self.canv.setFillColor(colors.HexColor("#EEDFD1"))
            self.canv.roundRect(x, y, width, height, 5 * mm, stroke=0, fill=1)
            return
        try:
            image = ImageReader(self.image_source)
            image_width, image_height = image.getSize()
            scale = min(width / image_width, height / image_height)
            draw_width = image_width * scale
            draw_height = image_height * scale
            self.canv.drawImage(
                image,
                x + (width - draw_width) / 2,
                y + (height - draw_height) / 2,
                width=draw_width,
                height=draw_height,
                preserveAspectRatio=True,
                mask="auto",
            )
        except Exception:
            self.canv.setFillColor(colors.HexColor("#EEDFD1"))
            self.canv.roundRect(x, y, width, height, 5 * mm, stroke=0, fill=1)

    def draw(self):
        canvas = self.canv
        canvas.saveState()
        canvas.setFillColor(colors.HexColor("#FFF9F1"))
        canvas.rect(0, 0, self.width, self.height, stroke=0, fill=1)

        if self.cover:
            self._draw_contained_image(0, 34 * mm, self.width, self.height - 34 * mm)
            canvas.setFillColor(colors.HexColor("#F6E8DB"))
            canvas.roundRect(10 * mm, 6 * mm, self.width - 20 * mm, 25 * mm, 5 * mm, stroke=0, fill=1)
            title_style = ParagraphStyle(
                "PicturebookCoverTitle", fontName=self.font_name, fontSize=20,
                leading=25, textColor=colors.HexColor("#593725"), alignment=1,
            )
            meta_style = ParagraphStyle(
                "PicturebookCoverMeta", fontName=self.font_name, fontSize=10,
                leading=14, textColor=colors.HexColor("#9B6D55"), alignment=1,
            )
            title = Paragraph(escape(self.title), title_style)
            _, title_height = title.wrap(self.width - 28 * mm, 13 * mm)
            title.drawOn(canvas, 14 * mm, 17 * mm - title_height / 2)
            meta = Paragraph(escape(self.date_text), meta_style)
            _, meta_height = meta.wrap(self.width - 28 * mm, 7 * mm)
            meta.drawOn(canvas, 14 * mm, 9 * mm - meta_height / 2)
        else:
            caption_height = 34 * mm
            self._draw_contained_image(0, caption_height, self.width, self.height - caption_height)
            canvas.setFillColor(colors.HexColor("#F6E8DB"))
            canvas.roundRect(8 * mm, 5 * mm, self.width - 16 * mm, 24 * mm, 5 * mm, stroke=0, fill=1)
            caption_style = ParagraphStyle(
                "PicturebookPageCaption", fontName=self.font_name, fontSize=13,
                leading=19, textColor=colors.HexColor("#593725"), alignment=1,
            )
            caption = Paragraph(escape(self.caption).replace("\n", "<br/>"), caption_style)
            _, caption_draw_height = caption.wrap(self.width - 30 * mm, 19 * mm)
            caption.drawOn(canvas, 15 * mm, 17 * mm - caption_draw_height / 2)
            canvas.setFillColor(colors.HexColor("#B27A5C"))
            canvas.setFont(self.font_name, 9)
            canvas.drawRightString(self.width - 11 * mm, 8 * mm, str(self.page_number))
        canvas.restoreState()


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
        resolved_asset_id = asset_id or parse_canonical_media_url(url)
        if resolved_asset_id:
            asset = await require_owned_asset(db, user_id, resolved_asset_id)
            path = asset_file_path(asset)
            return path if path.is_file() else None
        if url and url.startswith("/api/upload/"):
            if not await legacy_url_is_owned(db, user_id, url):
                return None
            return legacy_file_path(url)
    except MediaStoreError:
        return None
    return None


async def _resolve_authorized_image_path(
    db, user_id: int, url: str, asset_id: str | None
):
    """与 `_resolve_image_path` 等价的解析,但鉴权放宽到 audience-aware:
    先试当前用户所有权;不归属自己时,允许通过订阅 + work_audience 授权读取
    (用于底片示例 demo seed —— 作品资产属于 DEMO 发布者,体验者只持观众授权)。
    """
    resolved_asset_id = asset_id or parse_canonical_media_url(url)
    if resolved_asset_id:
        asset = await get_authorized_asset(db, resolved_asset_id, user_id)
        if asset is None:
            return None
        path = asset_file_path(asset)
        return path if path.is_file() else None
    if url and url.startswith("/api/upload/"):
        if not await legacy_url_is_owned(db, user_id, url):
            return None
        return legacy_file_path(url)
    return None


def _format_day(value: str) -> str:
    parsed = date_type.fromisoformat(value)
    return f"{parsed.year}年{parsed.month}月{parsed.day}日"


def _paragraph(text: object, style: ParagraphStyle, *, preserve_lines: bool = False):
    escaped = escape(str(text))
    if preserve_lines:
        escaped = escaped.replace("\n", "<br/>")
    return Paragraph(escaped, style)


def _text_asset(assets: list[dict]) -> dict | None:
    for asset in assets:
        if asset.get("asset_type") == "text" and (asset.get("text") or "").strip():
            return asset
    return None


def _first_image_asset(assets: list[dict]) -> dict | None:
    for asset in assets:
        if asset.get("asset_type") == "image" and (
            asset.get("asset_id") or asset.get("url")
        ):
            return asset
    return None


def _day_has_content(detail: dict) -> bool:
    return any(
        [
            detail.get("timeline"),
            detail.get("diaries"),
            detail.get("picturebooks"),
            detail.get("story_works"),
        ]
    )


def _ready_page_count(book: dict) -> int:
    if book.get("ready_pages") is not None:
        return int(book.get("ready_pages") or 0)
    pages = book.get("pages") or []
    if pages and all("status" not in page for page in pages):
        return len(pages)
    return len([page for page in pages if page.get("status") == "ready"])


def _image_class():
    """构造类在调用时解析,允许测试经 routers.export 打补丁。"""
    import sys

    compat = sys.modules.get("routers.export")
    return getattr(compat, "RLImage", None) or RLImage


async def _append_owned_image(flow: list, db, user_id: int, item: dict):
    path = await _resolve_image_path(
        db,
        user_id,
        item.get("url") or item.get("photo_url") or item.get("image_url") or "",
        item.get("asset_id") or item.get("photo_asset_id"),
    )
    if path is None:
        return
    try:
        # Force decoding before the flow is built so a corrupt owned file can be
        # skipped here instead of aborting the entire document during draw().
        ImageReader(str(path)).getRGBData()
        flow.append(Spacer(1, 3 * mm))
        flow.append(
            _image_class()(
                path,
                width=130 * mm,
                height=130 * mm,
                kind="proportional",
            )
        )
    except Exception:
        pass


async def _resolve_day_cover_path(db, user_id: int, detail: dict) -> Path | None:
    candidates: list[dict] = []
    if detail.get("cover_url"):
        candidates.append({"url": detail["cover_url"]})
    for book in detail.get("picturebooks") or []:
        pages = book.get("pages") or []
        if pages:
            candidates.append(pages[0])
    candidates.extend(
        item
        for item in detail.get("timeline") or []
        if item.get("kind") == "fragment" and item.get("photo_url")
    )
    for work in detail.get("story_works") or []:
        image = _first_image_asset(work.get("assets") or [])
        if image:
            candidates.append(image)
    for diary in detail.get("diaries") or []:
        candidates.extend(diary.get("images") or [])

    seen: set[tuple[str, str]] = set()
    for item in candidates:
        url = (
            item.get("url")
            or item.get("photo_url")
            or item.get("image_url")
            or ""
        )
        asset_id = item.get("asset_id") or item.get("photo_asset_id") or ""
        key = (url, asset_id)
        if key in seen:
            continue
        seen.add(key)
        path = await _resolve_image_path(db, user_id, url, asset_id or None)
        if path is not None:
            return path
    return None


def _day_styles(font_name: str):
    styles = getSampleStyleSheet()
    heading_style = ParagraphStyle(
        "DayHeading",
        parent=styles["Heading2"],
        fontName=font_name,
        fontSize=15,
        leading=20,
        spaceBefore=10,
        spaceAfter=6,
    )
    body_style = ParagraphStyle(
        "DayBody",
        parent=styles["Normal"],
        fontName=font_name,
        fontSize=12,
        leading=20,
        alignment=TA_LEFT,
        spaceAfter=7,
    )
    meta_style = ParagraphStyle(
        "DayMeta",
        parent=body_style,
        textColor="#6F6280",
    )
    return heading_style, body_style, meta_style


async def _build_day_pdf_flow(db, user_id: int, detail: dict) -> list:
    font_name = _register_cjk_font()
    heading_style, body_style, meta_style = _day_styles(font_name)

    summary = (detail.get("summary") or "").strip()
    cover_path = await _resolve_day_cover_path(db, user_id, detail)
    flow = [
        DayCover(
            cover_path,
            _format_day(detail["date"]),
            summary,
            font_name,
        ),
        PageBreak(),
    ]

    timeline = detail.get("timeline") or []
    if timeline:
        flow.append(_paragraph("当天时间线", heading_style))
        for item in timeline:
            clock = item.get("clock") or "未定"
            if item.get("kind") == "schedule":
                status = "已完成" if item.get("completed") else "未完成"
                feeling = item.get("feeling")
                suffix = f" · {feeling}" if feeling else ""
                flow.append(_paragraph(f"{clock} · 日程 · {item.get('title') or ''}", body_style))
                flow.append(_paragraph(f"{status}{suffix}", meta_style))
            else:
                flow.append(_paragraph(f"{clock} · 片段", body_style))
                content = (item.get("content") or "").strip()
                if content:
                    flow.append(_paragraph(content, body_style, preserve_lines=True))
                await _append_owned_image(flow, db, user_id, item)
                mood = (item.get("mood_tag") or "").strip()
                if mood:
                    flow.append(_paragraph(mood, meta_style))

    diaries = detail.get("diaries") or []
    if diaries:
        flow.append(_paragraph("日记", heading_style))
        for diary in diaries:
            if diary.get("status") != "confirmed":
                continue
            text = (diary.get("text") or "").strip()
            if text:
                flow.append(_paragraph(text, body_style, preserve_lines=True))

    await _append_picturebook_section(
        flow, db, user_id, detail.get("picturebooks") or [], heading_style, body_style, meta_style
    )

    story_works = detail.get("story_works") or []
    if story_works:
        flow.append(_paragraph("故事作品", heading_style))
        for work in story_works:
            flow.append(_paragraph(work.get("title") or "未命名作品", body_style))
            text = _text_asset(work.get("assets") or [])
            if text:
                flow.append(_paragraph(text.get("text") or "", body_style, preserve_lines=True))
            image = _first_image_asset(work.get("assets") or [])
            if image:
                await _append_owned_image(flow, db, user_id, image)
    return flow


async def _append_picturebook_section(
    flow: list,
    db,
    user_id: int,
    books: list[dict],
    heading_style: ParagraphStyle,
    body_style: ParagraphStyle,
    meta_style: ParagraphStyle,
) -> None:
    if not books:
        return
    flow.append(_paragraph("绘本", heading_style))
    for book in books:
        flow.append(
            _paragraph(
                f"{book.get('style') or '绘本'} · {_ready_page_count(book)}/{book.get('total_pages') or 0} 页",
                meta_style,
            )
        )
        for page in book.get("pages") or []:
            await _append_owned_image(flow, db, user_id, page)
            caption = (page.get("caption") or "").strip()
            if caption:
                flow.append(_paragraph(caption, body_style, preserve_lines=True))


def _render_pdf(flow: list) -> io.BytesIO:
    """渲染;构造类在调用时解析,允许测试经 routers.export 打补丁。"""
    import sys

    compat = sys.modules.get("routers.export")
    doc_class = (
        getattr(compat, "SimpleDocTemplate", None)
        or SimpleDocTemplate
    )
    buf = io.BytesIO()
    doc = doc_class(
        buf,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
    )
    doc.build(flow)
    buf.seek(0)
    return buf


# --------------------------------------------------------------------- public API


async def day_export_availability(db, user_id: int, day: str) -> dict:
    """只返回布尔可用性,不返回内容。"""
    detail = await get_story_day(db, user_id, day)
    has_diary = any(
        diary.get("status") == "confirmed" and (diary.get("text") or "").strip()
        for diary in detail.get("diaries") or []
    )
    has_picturebooks = bool(detail.get("picturebooks"))
    return {"has_diary": has_diary, "has_picturebooks": has_picturebooks}


async def build_legacy_day_pdf(db, user_id: int, day: str) -> io.BytesIO:
    detail = await get_story_day(db, user_id, day)
    if not _day_has_content(detail):
        raise HTTPException(status_code=404, detail="story day not found")
    flow = await _build_day_pdf_flow(db, user_id, detail)
    return _render_pdf(flow)


async def build_selected_day_pdf(
    db, user_id: int, day: str, selection: DayPdfSelection
) -> io.BytesIO:
    """按日组合导出:日期页 → 日记与照片 → 当天绘本。"""
    detail = await get_story_day(db, user_id, day)
    font_name = _register_cjk_font()
    heading_style, body_style, meta_style = _day_styles(font_name)

    summary = (detail.get("summary") or "").strip()
    cover_path = await _resolve_day_cover_path(db, user_id, detail)
    flow: list = [
        DayCover(cover_path, _format_day(day), summary, font_name),
        PageBreak(),
    ]
    produced = False

    if selection.include_diary:
        diaries = detail.get("diaries") or []
        confirmed = [
            diary
            for diary in diaries
            if diary.get("status") == "confirmed" and (diary.get("text") or "").strip()
        ]
        if confirmed:
            flow.append(_paragraph("日记", heading_style))
            for diary in confirmed:
                flow.append(
                    _paragraph(diary["text"].strip(), body_style, preserve_lines=True)
                )
                # diaries 表不携带图片;kept 照片按 diary_id 从 images 表补读。
                cursor = await db.execute(
                    "SELECT url, asset_id FROM images "
                    "WHERE diary_id = ? AND kept = 1 ORDER BY created_at",
                    (diary["id"],),
                )
                for row in await cursor.fetchall():
                    await _append_owned_image(flow, db, user_id, dict(row))
            produced = True

    if selection.include_picturebooks:
        books = detail.get("picturebooks") or []
        if books:
            await _append_picturebook_section(
                flow, db, user_id, books, heading_style, body_style, meta_style
            )
            produced = True

    if not produced:
        raise HTTPException(status_code=400, detail="所选内容为空,无法导出")
    return _render_pdf(flow)


async def build_time_story_pdf(db, user_id: int, work_id: int) -> io.BytesIO:
    """时光故事导出:只含封面与完整绘本页,不附带来源日记。"""
    books = await list_completed_picturebooks(db, user_id)
    book = next(
        (
            item
            for item in books
            if item["source_kind"] == "canonical_work"
            and item["source_id"] == work_id
            and item["work_kind"] == "time_story"
        ),
        None,
    )
    if book is None:
        raise HTTPException(status_code=404, detail="time story not found")

    font_name = _register_cjk_font()
    heading_style, body_style, meta_style = _day_styles(font_name)
    flow: list = [
        _paragraph(book["title"], heading_style),
        _paragraph(
            f"{book['start_date']} ~ {book['end_date']}", meta_style
        ),
    ]
    produced = False
    for page in book.get("pages") or []:
        await _append_owned_image(flow, db, user_id, page)
        caption = (page.get("caption") or "").strip()
        if caption:
            flow.append(_paragraph(caption, body_style, preserve_lines=True))
        produced = True
    if not produced:
        raise HTTPException(status_code=400, detail="所选内容为空,无法导出")
    return _render_pdf(flow)


async def build_picturebook_pdf(
    db, user_id: int, source_kind: str, source_id: int
) -> io.BytesIO:
    """Export one completed picturebook as a cover plus one landscape page per scene."""
    detail = await get_picturebook_detail(db, user_id, source_kind, source_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="picturebook not found")

    pages = detail.get("pages") or []
    if not pages:
        raise HTTPException(status_code=400, detail="绘本没有可导出的页面")
    # 底片示例(demo seed)的资产属于 DEMO 发布者而非当前用户,普通所有权校验
    # 会把它们全部判为无权 → PDF 无图。这里对示例作品改用 audience-aware 解析,
    # 体验者凭订阅授权读取,与阅读器/媒体路由的鉴权口径一致。
    is_demo_seed = (
        source_kind == "canonical_work"
        and source_id in config.DEMO_PICTUREBOOK_WORK_IDS
        and await is_demo_subscriber(db, user_id=user_id)
    )
    resolver = _resolve_authorized_image_path if is_demo_seed else _resolve_image_path
    resolved_pages = []
    for page in pages:
        path = await resolver(
            db,
            user_id,
            page.get("image_url") or page.get("url") or "",
            page.get("asset_id"),
        )
        resolved_pages.append((path, (page.get("caption") or "").strip()))

    font_name = _register_cjk_font()
    date_text = detail.get("display_start_date") or ""
    if detail.get("display_end_date") and detail.get("display_end_date") != date_text:
        date_text = f"{date_text} ~ {detail['display_end_date']}"
    flow = [
        PicturebookExportPage(
            resolved_pages[0][0], "", font_name, 0, cover=True,
            title=detail.get("title") or "未命名绘本", date_text=date_text,
        ),
        PageBreak(),
    ]
    for index, (path, caption) in enumerate(resolved_pages, start=1):
        flow.append(PicturebookExportPage(path, caption, font_name, index))
        if index < len(resolved_pages):
            flow.append(PageBreak())

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=landscape(A4),
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
    )
    doc.build(flow)
    buf.seek(0)
    return buf
