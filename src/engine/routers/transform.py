"""v3.6 Nagging Transformer router.

- GET  /api/transform/nagging/inbox       → mock 妈妈最近的 5 条唠叨
- POST /api/transform/nagging/transform   → 一条唠叨 → 3 张回应卡片
"""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from agents.nagging_transformer_agent import transform_nagging
from auth.dependencies import get_current_user_id, require_same_origin
from services.generation_errors import (
    GenerationServiceError,
    raise_generation_http_error,
)


router = APIRouter()


# ---- mock data ------------------------------------------------------------

MOCK_NAGGING_INBOX = [
    {
        "id": 1,
        "from": "妈妈",
        "received_at": "2026-05-23T07:42:00",
        "kind": "health_article",
        "text": "孩子转发给你看看 👉 每天熬夜的人，肝脏在经历这8个变化（必看！）。别再熬了，妈妈天天看你朋友圈那么晚还在线，心疼。",
    },
    {
        "id": 2,
        "from": "妈妈",
        "received_at": "2026-05-23T12:05:00",
        "kind": "checkin",
        "text": "吃饭了没？工作累不累？降温了多穿点。",
    },
    {
        "id": 3,
        "from": "妈妈",
        "received_at": "2026-05-22T20:18:00",
        "kind": "matchmaking",
        "text": "你王阿姨家闺女今年也回来了，在你们公司隔壁那栋楼上班，听说也单着，要不妈帮你们牵个线？",
    },
    {
        "id": 4,
        "from": "妈妈",
        "received_at": "2026-05-22T08:30:00",
        "kind": "anti_fraud",
        "text": "注意防诈骗‼️ 这种短信链接千万别点！妈妈昨天看新闻有个小伙子被骗了 30 多万，你一定要小心！",
    },
    {
        "id": 5,
        "from": "妈妈",
        "received_at": "2026-05-21T23:11:00",
        "kind": "sleep_nag",
        "text": "早点睡，别再熬夜了。年轻的时候不爱惜，老了什么病都出来。",
    },
]


# ---- schemas --------------------------------------------------------------

class NaggingItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: int
    from_: str = Field(alias="from")
    received_at: str
    kind: str
    text: str

class TransformRequest(BaseModel):
    nag_id: Optional[int] = None  # if given, look up in inbox
    nag_text: Optional[str] = None  # otherwise use this directly
    relation: str = "妈妈"


class TransformResponse(BaseModel):
    nag_text: str
    cards: dict  # {help_request, co_challenge, warm_echo}


# ---- endpoints ------------------------------------------------------------

@router.get("/nagging/inbox")
async def list_nagging(
    _user_id: int = Depends(get_current_user_id),
):
    """Return the mock inbox of 妈妈的唠叨."""
    return MOCK_NAGGING_INBOX


@router.post("/nagging/transform", response_model=TransformResponse)
async def transform_endpoint(
    req: TransformRequest,
    _: None = Depends(require_same_origin),
    _user_id: int = Depends(get_current_user_id),
):
    """Turn one 唠叨 into 3 response cards via AI."""
    nag_text: str
    if req.nag_id is not None:
        match = next((n for n in MOCK_NAGGING_INBOX if n["id"] == req.nag_id), None)
        if not match:
            raise HTTPException(status_code=404, detail=f"nag #{req.nag_id} not found")
        nag_text = match["text"]
    elif req.nag_text:
        nag_text = req.nag_text
    else:
        raise HTTPException(status_code=400, detail="nag_id 或 nag_text 至少给一个")

    try:
        cards = await transform_nagging(nag_text, relation=req.relation)
    except GenerationServiceError as exc:
        raise_generation_http_error(exc, service="AI")

    return TransformResponse(nag_text=nag_text, cards=cards)
