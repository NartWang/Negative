"""AI helpers for dual-timeline:
  - summarize(): one neutral 12-30 char Chinese line about how the two days resonate
  - plan_comic(): single english qwen-image prompt + chinese caption for a dual-perspective image
Both call GLM. summarize falls back to a fixed line; plan_comic raises on hard failure.
"""
import json
import re
import httpx
from typing import Optional
from config import DIARY_API_BASE_URL, DIARY_API_KEY, DIARY_MODEL
from agents.image_agent import STYLE_PROMPTS

_THINK_RE = re.compile(r"<think>[\s\S]*?</think>", re.IGNORECASE)
_UNTERMINATED_THINK_RE = re.compile(r"<think>[\s\S]*$", re.IGNORECASE)
_JSON_RE = re.compile(r"\{[\s\S]*\}")


def _strip(text: str) -> str:
    if not text:
        return text
    cleaned = _THINK_RE.sub("", text)
    cleaned = _UNTERMINATED_THINK_RE.sub("", cleaned)
    return cleaned.strip()


def _events_to_lines(events: list) -> str:
    if not events:
        return "（无记录）"
    out = []
    for e in events:
        kind = "日程" if e.get("type") == "schedule" else "碎片"
        time = e.get("time") or ""
        title = e.get("title") or e.get("content") or "(空)"
        mood = f" [{e['mood_tag']}]" if e.get("mood_tag") else ""
        feeling = f"，感受：{e['feeling']}" if e.get("feeling") else ""
        out.append(f"- {time} {kind}: {title}{mood}{feeling}")
    return "\n".join(out)


def _style_prompt(style: str, custom: Optional[str]) -> str:
    if style == "custom" and custom:
        return custom
    return STYLE_PROMPTS.get(style) or STYLE_PROMPTS["ghibli"]


async def summarize(
    date: str,
    user_a_name: str, events_a: list,
    user_b_name: str, events_b: list,
) -> str:
    """Return a 12-30 char Chinese line. Never raises."""
    if not events_a and not events_b:
        return "这天，你们都很安静"

    system_prompt = (
        "你是一位温柔的家庭观察者。基于两个家人在同一天里的真实记录，"
        "写一句 12-30 字的中文中性观察，不评判、不煽情。"
        "只输出 JSON：{\"summary\": str}。禁止 markdown、禁止解释。"
    )
    user_message = (
        f"日期：{date}\n\n"
        f"【{user_a_name} 的一天】\n{_events_to_lines(events_a)}\n\n"
        f"【{user_b_name} 的一天】\n{_events_to_lines(events_b)}"
    )

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                f"{DIARY_API_BASE_URL}/chat/completions",
                headers={"Authorization": f"Bearer {DIARY_API_KEY}"},
                json={
                    "model": DIARY_MODEL,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_message},
                    ],
                    "temperature": 0.6,
                    "max_tokens": 800,
                },
            )
            response.raise_for_status()
            raw = response.json()["choices"][0]["message"]["content"]
        cleaned = _strip(raw)
        match = _JSON_RE.search(cleaned)
        if not match:
            return "这天，你们都在各自的时区里走着"
        payload = json.loads(match.group(0))
        summary = str(payload.get("summary", "")).strip()
        if not (4 <= len(summary) <= 40):
            return "这天，你们都在各自的时区里走着"
        return summary
    except Exception:
        return "这天，你们都在各自的时区里走着"


async def plan_comic(
    date: str,
    user_a_name: str, selected_a: list,
    user_b_name: str, selected_b: list,
    style: str, custom_style_prompt: Optional[str],
) -> tuple:
    """Return (english_image_prompt, chinese_caption). Raises on hard failure."""
    style_basis = _style_prompt(style, custom_style_prompt)
    system_prompt = (
        "你是漫画分镜导演。请把两个家人在同一天里选中的真实时刻，画成一张"
        " 2x2 或 1x4 的漫画。\n硬约束：\n"
        "1. **不能编造没列出的事件**。\n"
        "2. 两个主角形象**前后一致**（同一张脸/同一身穿搭）。\n"
        "3. 画面构图必须体现**同一天里两个生活**的意象 — 分屏 / 平行剪辑 / 错位时空。\n"
        "4. 4 个分镜里**藏一条情感线索**（如某条碎片里反复出现的牵挂）。\n"
        "5. 输出英文 qwen-image 提示词上限 800 字符。\n"
        "6. 输出**纯 JSON**：{\"prompt\": str, \"caption\": str}（caption 8-15 字中文）。"
        "禁止 markdown、禁止解释、禁止前后缀。"
    )
    user_message = (
        f"日期：{date}\n\n"
        f"【{user_a_name} 选中的时刻】\n{_events_to_lines(selected_a)}\n\n"
        f"【{user_b_name} 选中的时刻】\n{_events_to_lines(selected_b)}\n\n"
        f"风格基调（请写进英文 prompt 里）：{style_basis}\n\n"
        "请输出 JSON。"
    )

    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(
            f"{DIARY_API_BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {DIARY_API_KEY}"},
            json={
                "model": DIARY_MODEL,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                "temperature": 0.7,
                "max_tokens": 1200,
            },
        )
        response.raise_for_status()
        raw = response.json()["choices"][0]["message"]["content"]

    cleaned = _strip(raw)
    match = _JSON_RE.search(cleaned)
    if not match:
        return cleaned[:780], "同一天的两面"
    try:
        payload = json.loads(match.group(0))
        prompt = str(payload.get("prompt", "")).strip()[:800]
        caption = str(payload.get("caption", "")).strip()[:30] or "同一天的两面"
        if not prompt:
            raise ValueError("empty prompt")
        return prompt, caption
    except Exception:
        return cleaned[:780], "同一天的两面"
