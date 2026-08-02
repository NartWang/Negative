import datetime
import logging
import httpx
from typing import Literal, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from database import get_db

router = APIRouter()
log = logging.getLogger(__name__)

SIGNATURE = "\n\n— 数字实习生 · 知己 ✨"

TABLE_FOR_TYPE = {"diary": "diaries", "comic": "weekly_comics"}


class SendLetterRequest(BaseModel):
    webhook: str = Field(..., min_length=1)
    type: Literal["diary", "comic", "test"]
    id: Optional[int] = None  # required for diary / comic, ignored for test
    title: str = Field(..., min_length=1, max_length=120)
    body: str = Field(..., min_length=1, max_length=4000)


class SendLetterResponse(BaseModel):
    ok: bool
    sent_at: str


@router.post("/send", response_model=SendLetterResponse)
async def send_letter(payload: SendLetterRequest):
    """Send a markdown letter to a DingTalk webhook.

    The signature is auto-appended so the message always contains the keyword
    "数字实习生" — this matches the keyword-validation mode of DingTalk custom
    robots and the convention from the dingtalk-notify skill.
    """
    if payload.type in ("diary", "comic") and payload.id is None:
        raise HTTPException(status_code=400, detail="id is required for diary/comic")

    text = payload.body.rstrip() + SIGNATURE
    dingtalk_payload = {
        "msgtype": "markdown",
        "markdown": {"title": payload.title, "text": text},
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(payload.webhook, json=dingtalk_payload)
    except httpx.HTTPError as e:
        log.warning("dingtalk webhook network error: %s", e)
        raise HTTPException(status_code=502, detail=f"网络错误：{e}")

    try:
        data = r.json()
    except Exception:
        raise HTTPException(status_code=502, detail=f"钉钉返回非 JSON：HTTP {r.status_code}")

    errcode = data.get("errcode", -1)
    if errcode != 0:
        errmsg = data.get("errmsg", "unknown")
        log.warning("dingtalk webhook rejected: errcode=%s errmsg=%s", errcode, errmsg)
        raise HTTPException(status_code=502, detail=f"钉钉拒收：{errmsg}")

    sent_at = datetime.datetime.now().isoformat(timespec="seconds")

    if payload.type in ("diary", "comic"):
        table = TABLE_FOR_TYPE[payload.type]
        db = await get_db()
        try:
            cursor = await db.execute(f"SELECT id FROM {table} WHERE id = ?", (payload.id,))
            if not await cursor.fetchone():
                raise HTTPException(status_code=400, detail=f"{payload.type} #{payload.id} not found")
            await db.execute(
                f"UPDATE {table} SET last_sent_at = ? WHERE id = ?",
                (sent_at, payload.id),
            )
            await db.commit()
        finally:
            await db.close()

    log.info("letter sent: type=%s id=%s title=%s", payload.type, payload.id, payload.title)
    return SendLetterResponse(ok=True, sent_at=sent_at)
