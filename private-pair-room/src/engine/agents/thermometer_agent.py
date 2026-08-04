"""Compute the 0-100 emotion thermometer score.

Score = quant (0-60) + ai (0-40).
Quant is deterministic: # fragments today * 6 (capped at 30)
                      + completed_schedule_ratio * 20
                      + min(consecutive_checkin_days, 5) * 2

AI part calls GLM and returns a 0-40 score + a 5-15 char Chinese comment.
On any error it falls back to (20, "今天也辛苦了") so the API never errors.
"""
import json
import re
import httpx
from config import DIARY_API_BASE_URL, DIARY_API_KEY, DIARY_MODEL

_THINK_BLOCK_RE = re.compile(r"<think>[\s\S]*?</think>", re.IGNORECASE)
_UNTERMINATED_THINK_RE = re.compile(r"<think>[\s\S]*$", re.IGNORECASE)


def _strip_reasoning(text: str) -> str:
    if not text:
        return text
    cleaned = _THINK_BLOCK_RE.sub("", text)
    # If the response was cut off mid-thinking (max_tokens reached during <think>),
    # drop the unterminated block too — otherwise the JSON regex matches nothing
    # and we silently fall back.
    cleaned = _UNTERMINATED_THINK_RE.sub("", cleaned)
    return cleaned.strip()


def compute_quant(
    today_fragments_count: int,
    completed_schedules_ratio: float,
    consecutive_checkin_days: int,
) -> int:
    """Returns int in [0, 60]."""
    frag = min(max(today_fragments_count, 0), 5) * 6                    # 0-30
    sched = max(0.0, min(1.0, completed_schedules_ratio)) * 20          # 0-20
    streak = min(max(consecutive_checkin_days, 0), 5) * 2               # 0-10
    return int(round(frag + sched + streak))


def label_for_score(score: int) -> tuple[str, str]:
    """Returns (label, hex color)."""
    if score <= 20:   return ("凉", "#9CC5E0")
    if score <= 40:   return ("温凉", "#BFD4D6")
    if score <= 60:   return ("温热", "#E8C8A0")
    if score <= 80:   return ("温暖", "#E89D7B")
    return ("炽热", "#E67862")


def _fallback() -> tuple[int, str]:
    return 20, "今天也辛苦了"


async def ai_score_and_comment(
    nickname: str, schedules: list, fragments: list
) -> tuple[int, str]:
    """Return (ai_score 0-40, comment 5-15 chars). Never raises."""
    if not schedules and not fragments:
        return _fallback()

    schedule_lines = "\n".join(
        f"- {('✅' if s.get('completed') else '⬜')} {s.get('time') or ''} {s.get('title')}"
        + (f"（{s['feeling']}）" if s.get("feeling") else "")
        for s in schedules
    ) or "（无日程）"

    fragment_lines = "\n".join(
        f"- {f.get('content') or '(空)'}" + (f" [{f['mood_tag']}]" if f.get("mood_tag") else "")
        for f in fragments
    ) or "（无碎片）"

    system_prompt = (
        "你是一位温柔的家庭观察者。基于用户今天的真实记录，输出一个 0-40 的"
        "情绪温度分数（整数）和一句 5-15 字的温暖中文点评。"
        "只输出 JSON：{\"mood_score\": int, \"comment\": str}。"
        "禁止解释、禁止前后缀、禁止 markdown。"
    )
    user_message = (
        f"用户：{nickname}\n\n"
        f"【今日日程】\n{schedule_lines}\n\n"
        f"【今日碎片】\n{fragment_lines}"
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
            cleaned = _strip_reasoning(raw)
            # Be permissive about wrapping ```json ... ```
            match = re.search(r"\{[\s\S]*\}", cleaned)
            if not match:
                return _fallback()
            payload = json.loads(match.group(0))
            score = int(payload.get("mood_score", 20))
            comment = str(payload.get("comment", "")).strip()
            if not (0 <= score <= 40):
                score = max(0, min(40, score))
            if not (1 <= len(comment) <= 30):
                comment = "今天也辛苦了"
            return score, comment
    except Exception:
        return _fallback()
