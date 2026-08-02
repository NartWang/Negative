"""Plan a single coherent 4-panel comic from a user's 7-day real records.

Pipeline:
  1. Build a Chinese GLM prompt that emphatically forbids fabrication.
  2. GLM returns JSON {"prompt": "<english qwen-image prompt>", "caption": "<chinese>"}
  3. Caller passes `prompt` to image_agent.generate_image() with style.

GLM is treated as a planner only — it does not draw.
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


def _strip_think(text: str) -> str:
    if not text:
        return text
    cleaned = _THINK_RE.sub("", text)
    cleaned = _UNTERMINATED_THINK_RE.sub("", cleaned)
    return cleaned.strip()


def _style_prompt(style: str, custom_style_prompt: Optional[str]) -> str:
    if style == "custom" and custom_style_prompt:
        return custom_style_prompt
    return STYLE_PROMPTS.get(style) or STYLE_PROMPTS["ghibli"]


def _format_day_block(date: str, schedules: list, fragments: list) -> str:
    if not schedules and not fragments:
        return f"【{date}】（无记录）"

    sched_lines = "\n".join(
        f"  - {('✅' if s.get('completed') else '⬜')} {s.get('time') or ''} {s.get('title')}"
        + (f"，感受：{s['feeling']}" if s.get("feeling") else "")
        for s in schedules
    ) or "  -（无日程）"

    frag_lines = "\n".join(
        f"  - {f.get('content') or '(空)'}"
        + (f" [{f['mood_tag']}]" if f.get("mood_tag") else "")
        for f in fragments
    ) or "  -（无碎片）"

    return (
        f"【{date}】\n"
        f"日程：\n{sched_lines}\n"
        f"碎片：\n{frag_lines}"
    )


def build_planner_prompt(
    nickname: str,
    week_start: str,
    week_end: str,
    days: list[dict],
    style: str,
    custom_style_prompt: Optional[str],
) -> tuple[str, str]:
    """Return (system_prompt, user_message)."""
    style_basis = _style_prompt(style, custom_style_prompt)

    system_prompt = (
        "你是漫画分镜导演。基于用户真实记录，输出一张单图 4-panel 连贯漫画的英文 qwen-image 提示词，"
        "外加一句 8-15 字的中文 caption。\n"
        "硬约束：\n"
        "1. **只能使用下面提供的真实素材，绝不编造没出现的事**。完全空白的日期直接跳过。\n"
        "2. 故事必须**有起承转合**（开场→发展→转折→收束）。\n"
        "3. 主角形象**前后一致**（同一张脸/同一身穿搭/统一标志物）。\n"
        "4. 4 个分镜里**埋一条情感线索**（例如某条碎片里反复出现的牵挂）。\n"
        "5. 输出英文提示词上限 800 字符。\n"
        "6. 输出**纯 JSON**：{\"prompt\": str, \"caption\": str}。禁止 markdown、禁止解释、禁止前后缀。"
    )

    body = "\n\n".join(_format_day_block(**d) for d in days)

    user_message = (
        f"用户：{nickname}\n"
        f"时间范围：{week_start} ~ {week_end}\n\n"
        f"【七天真实素材】\n{body}\n\n"
        f"风格基调（请写进英文 prompt 里）：{style_basis}\n\n"
        "请输出 JSON。"
    )

    return system_prompt, user_message


async def plan_weekly_comic(
    nickname: str,
    week_start: str,
    week_end: str,
    days: list[dict],
    style: str,
    custom_style_prompt: Optional[str],
) -> tuple[str, str]:
    """Returns (english_image_prompt, chinese_caption). Raises on hard failure."""
    system_prompt, user_message = build_planner_prompt(
        nickname, week_start, week_end, days, style, custom_style_prompt,
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

    cleaned = _strip_think(raw)
    match = _JSON_RE.search(cleaned)
    if not match:
        # Fallback: use the whole text as prompt + generic caption
        return cleaned[:780], "这一周的样子"

    try:
        payload = json.loads(match.group(0))
        prompt = str(payload.get("prompt", "")).strip()[:800]
        caption = str(payload.get("caption", "")).strip()[:30] or "这一周的样子"
        if not prompt:
            raise ValueError("empty prompt")
        return prompt, caption
    except Exception:
        return cleaned[:780], "这一周的样子"
