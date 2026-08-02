import secrets
import datetime
import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from database import get_db

router = APIRouter()
log = logging.getLogger(__name__)

SHARE_PAGE_TYPES = {"diary", "comic", "dual_timeline"}
REACTIONS = ["❤️", "😊", "🥹", "😂", "👍", "💪", "🌻", "🤗"]


class CreateShareRequest(BaseModel):
    type: str = Field(..., description="diary | comic | dual_timeline")
    id: int
    user_id: int = 1


class CreateShareResponse(BaseModel):
    share_code: str
    share_url: str


class ReactRequest(BaseModel):
    emoji: str


# ---- helpers ----

def _make_code() -> str:
    return secrets.token_hex(4)


async def _load_share_data(db, share_code: str) -> dict:
    cursor = await db.execute(
        "SELECT * FROM shares WHERE share_code = ?", (share_code,)
    )
    share = await cursor.fetchone()
    if not share:
        raise HTTPException(status_code=404, detail="分享不存在或已过期")
    share = dict(share)

    if share["share_type"] == "diary":
        cursor = await db.execute(
            "SELECT * FROM diaries WHERE id = ?", (share["diary_id"],)
        )
        diary = await cursor.fetchone()
        if not diary:
            raise HTTPException(status_code=404, detail="日记不存在")
        diary = dict(diary)

        cursor = await db.execute(
            "SELECT * FROM images WHERE diary_id = ? AND kept = 1", (diary["id"],)
        )
        images = [dict(r) for r in await cursor.fetchall()]

        cursor = await db.execute(
            "SELECT nickname FROM profile WHERE id = ?", (share["user_id"],)
        )
        prof = await cursor.fetchone()
        author = prof["nickname"] if prof else "我"

        return {
            "type": "diary",
            "title": f"{diary['date']} 的日记",
            "date": diary["date"],
            "author": author,
            "text": diary["text"],
            "emotion_mode": diary.get("emotion_mode"),
            "images": images,
        }

    elif share["share_type"] == "comic":
        cursor = await db.execute(
            "SELECT * FROM weekly_comics WHERE id = ?", (share["diary_id"],)
        )
        comic = await cursor.fetchone()
        if not comic:
            raise HTTPException(status_code=404, detail="漫画不存在")
        comic = dict(comic)

        cursor = await db.execute(
            "SELECT nickname FROM profile WHERE id = ?", (share["user_id"],)
        )
        prof = await cursor.fetchone()
        author = prof["nickname"] if prof else "我"

        return {
            "type": "comic",
            "title": f"{comic['week_start']} ~ {comic['week_end']} 周漫画",
            "author": author,
            "text": comic.get("caption") or "",
            "images": [{"url": comic["url"], "style": comic.get("style")}],
        }

    elif share["share_type"] == "dual_timeline":
        cursor = await db.execute(
            "SELECT * FROM dual_timeline_comics WHERE id = ?", (share["diary_id"],)
        )
        dt = await cursor.fetchone()
        if not dt:
            raise HTTPException(status_code=404, detail="双时间线不存在")
        dt = dict(dt)

        return {
            "type": "dual_timeline",
            "title": f"{dt['date']} 双人画",
            "author": "我和家人",
            "text": dt.get("caption") or "",
            "images": [{"url": dt["url"], "style": dt.get("style")}],
        }

    raise HTTPException(status_code=400, detail="未知分享类型")


# ---- endpoints ----

@router.post("/create", response_model=CreateShareResponse)
async def create_share(req: CreateShareRequest):
    if req.type not in SHARE_PAGE_TYPES:
        raise HTTPException(status_code=400, detail=f"不支持的分享类型: {req.type}")

    db = await get_db()
    try:
        share_code = _make_code()
        await db.execute(
            "INSERT INTO shares (diary_id, share_code, share_type, user_id) VALUES (?, ?, ?, ?)",
            (req.id, share_code, req.type, req.user_id),
        )
        await db.commit()
    finally:
        await db.close()

    return CreateShareResponse(
        share_code=share_code,
        share_url=f"/api/s/{share_code}",
    )


@router.get("/s/{share_code}", response_class=HTMLResponse)
async def view_share(share_code: str, request: Request):
    db = await get_db()
    try:
        data = await _load_share_data(db, share_code)

        cursor = await db.execute(
            "SELECT id FROM shares WHERE share_code = ?", (share_code,)
        )
        share_row = await cursor.fetchone()
        share_id = share_row["id"]

        cursor = await db.execute(
            "SELECT emoji, COUNT(*) as cnt FROM share_reactions "
            "WHERE share_id = ? GROUP BY emoji",
            (share_id,),
        )
        reaction_rows = await cursor.fetchall()
        reactions = {r["emoji"]: r["cnt"] for r in reaction_rows}
    finally:
        await db.close()

    # Build reactions HTML
    reaction_buttons = ""
    for emoji in REACTIONS:
        count = reactions.get(emoji, 0)
        reaction_buttons += f"""
        <button class="react-btn" onclick="react('{emoji}')" title="{emoji}">
            {emoji}{' ' if count > 0 else ''}<span class="react-count">{count if count > 0 else ''}</span>
        </button>"""

    # Build images HTML
    images_html = ""
    if data.get("images"):
        for img in data["images"]:
            style_label = img.get("style", "") or ""
            images_html += f"""
            <div class="image-card">
                <img src="{img['url']}" alt="{style_label}" loading="lazy" />
            </div>"""

    # Format diary text with paragraphs
    text_html = ""
    if data.get("text"):
        paragraphs = data["text"].strip().split("\n")
        for p in paragraphs:
            if p.strip():
                text_html += f"<p>{p.strip()}</p>"

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
    <title>{data['title']} - 知己</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
                         "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
            background: #F8F6F3;
            color: #3D3929;
            line-height: 1.8;
            min-height: 100vh;
            padding-bottom: 120px;
        }}
        .header {{
            background: linear-gradient(135deg, #B8D4C2 0%, #A8C8B2 50%, #D4C8A8 100%);
            padding: 32px 20px 28px;
            text-align: center;
            color: #2D4738;
        }}
        .header h1 {{
            font-size: 22px;
            font-weight: 700;
            margin-bottom: 6px;
        }}
        .header .meta {{
            font-size: 13px;
            opacity: 0.7;
        }}
        .content {{
            max-width: 600px;
            margin: 0 auto;
            padding: 24px 16px;
        }}
        .content p {{
            font-size: 16px;
            margin-bottom: 14px;
            text-indent: 2em;
        }}
        .image-card {{
            margin: 20px 0;
            border-radius: 16px;
            overflow: hidden;
            box-shadow: 0 4px 20px rgba(0,0,0,0.08);
        }}
        .image-card img {{
            width: 100%;
            display: block;
        }}
        .reactions {{
            position: fixed;
            bottom: 0;
            left: 0;
            right: 0;
            background: rgba(255,255,255,0.95);
            backdrop-filter: blur(10px);
            border-top: 1px solid #E8E4DC;
            padding: 16px 12px 24px;
            display: flex;
            justify-content: center;
            gap: 8px;
            flex-wrap: wrap;
        }}
        .react-btn {{
            width: 48px;
            height: 48px;
            border-radius: 50%;
            border: 1.5px solid #E0DDE3;
            background: #fff;
            font-size: 22px;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            transition: all 0.2s;
            position: relative;
        }}
        .react-btn:active {{
            transform: scale(1.15);
            border-color: #B8D4C2;
            background: #EFF7F1;
        }}
        .react-btn .react-count {{
            position: absolute;
            top: -4px;
            right: -4px;
            background: #B8D4C2;
            color: #2D4738;
            font-size: 10px;
            font-weight: 700;
            min-width: 18px;
            height: 18px;
            border-radius: 9px;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 0 4px;
        }}
        .toast {{
            position: fixed;
            top: 20px;
            left: 50%;
            transform: translateX(-50%);
            background: #3D3929;
            color: #fff;
            padding: 10px 24px;
            border-radius: 20px;
            font-size: 14px;
            z-index: 999;
            opacity: 0;
            transition: opacity 0.3s;
            pointer-events: none;
        }}
        .toast.show {{ opacity: 1; }}
        .footer {{
            text-align: center;
            padding: 20px;
            font-size: 12px;
            color: #B0ADA0;
        }}
        .footer a {{
            color: #B8D4C2;
            text-decoration: none;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>{data['title']}</h1>
        <div class="meta">来自 {data['author']} · 由知己生成</div>
    </div>
    <div class="content">
        {text_html}
        {images_html}
    </div>
    <div class="footer">
        <p>— 数字实习生 · 知己 ✨ —</p>
    </div>
    <div class="toast" id="toast"></div>
    <div class="reactions" id="reactions">
        {reaction_buttons}
    </div>
    <script>
        const SHARE_CODE = '{share_code}';
        let reacting = false;

        function showToast(msg) {{
            const t = document.getElementById('toast');
            t.textContent = msg;
            t.classList.add('show');
            setTimeout(() => t.classList.remove('show'), 2000);
        }}

        async function react(emoji) {{
            if (reacting) return;
            reacting = true;
            try {{
                const res = await fetch('/api/s/' + SHARE_CODE + '/react', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ emoji }}),
                }});
                if (!res.ok) throw new Error('fail');
                const data = await res.json();
                showToast('已回应 ' + emoji);
                // Update counts
                if (data.reactions) {{
                    const btns = document.querySelectorAll('.react-btn');
                    btns.forEach(b => {{
                        const countSpan = b.querySelector('.react-count');
                        if (countSpan) {{
                            const e = b.getAttribute('onclick').match(/'(.*?)'/)[1];
                            const cnt = data.reactions[e] || 0;
                            countSpan.textContent = cnt > 0 ? cnt : '';
                        }}
                    }});
                }}
            }} catch (e) {{
                showToast('回应失败，请重试');
            }} finally {{
                reacting = false;
            }}
        }}
    </script>
</body>
</html>"""

    return HTMLResponse(content=html)


@router.post("/s/{share_code}/react")
async def react_to_share(share_code: str, req: ReactRequest):
    if req.emoji not in REACTIONS:
        raise HTTPException(status_code=400, detail="不支持的回应")

    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT id FROM shares WHERE share_code = ?", (share_code,)
        )
        share_row = await cursor.fetchone()
        if not share_row:
            raise HTTPException(status_code=404, detail="分享不存在")
        share_id = share_row["id"]

        await db.execute(
            "INSERT INTO share_reactions (share_id, emoji) VALUES (?, ?)",
            (share_id, req.emoji),
        )
        await db.commit()

        # Return updated counts
        cursor = await db.execute(
            "SELECT emoji, COUNT(*) as cnt FROM share_reactions "
            "WHERE share_id = ? GROUP BY emoji",
            (share_id,),
        )
        reactions = {r["emoji"]: r["cnt"] for r in await cursor.fetchall()}
    finally:
        await db.close()

    return {"ok": True, "reactions": reactions}


@router.get("/reactions/unseen")
async def unseen_reactions(user_id: int = 1):
    """Get count of unseen reactions for the current user's shares."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT COUNT(*) as cnt FROM share_reactions r "
            "JOIN shares s ON r.share_id = s.id "
            "WHERE s.user_id = ? AND r.seen = 0",
            (user_id,),
        )
        row = await cursor.fetchone()
        count = row["cnt"] if row else 0
    finally:
        await db.close()

    return {"unseen_count": count}


@router.post("/reactions/mark-seen")
async def mark_reactions_seen(user_id: int = 1):
    """Mark all unseen reactions as seen for the current user."""
    db = await get_db()
    try:
        await db.execute(
            "UPDATE share_reactions SET seen = 1 "
            "WHERE seen = 0 AND share_id IN (SELECT id FROM shares WHERE user_id = ?)",
            (user_id,),
        )
        await db.commit()
    finally:
        await db.close()

    return {"ok": True}


@router.get("/list")
async def list_shares(user_id: int = 1, limit: int = 20):
    """List shares for the current user."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM shares WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
            (user_id, max(1, min(limit, 50))),
        )
        rows = [dict(r) for r in await cursor.fetchall()]
    finally:
        await db.close()

    return rows