from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Mapping

from agents.diary_agent import request_chat_completion


class TimeStoryAIContractError(Exception):
    """Raised when the model output cannot be safely persisted."""

    def __init__(self) -> None:
        super().__init__("time story AI response failed contract")


@dataclass(frozen=True)
class StorylineCandidate:
    id: str
    title: str
    summary: str
    source_dates: list[str]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "summary": self.summary,
            "source_dates": list(self.source_dates),
        }


@dataclass(frozen=True)
class StorylineResponse:
    items: list[StorylineCandidate]

    @property
    def storylines(self) -> list[StorylineCandidate]:
        return self.items

    def to_dict(self) -> dict:
        return {"items": [item.to_dict() for item in self.items]}


def build_grounded_storyline_candidates(
    snapshots: list[Mapping[str, Any]],
) -> StorylineResponse:
    """Build a safe local fallback when the AI response is unavailable/invalid.

    The summaries only quote the user's saved diary text, so this path keeps the
    workflow usable without inventing people, events, or causes.
    """
    dates = [str(item["date"]) for item in snapshots]
    bodies = [str(item.get("body") or "").strip() for item in snapshots]
    joined = " ".join(body for body in bodies if body).strip()
    excerpt = joined[:180] or "按所选日期整理当天留下的记录。"
    first_date = dates[:1]
    last_date = dates[-1:]
    return StorylineResponse(
        items=[
            StorylineCandidate(
                id="timeline",
                title="沿着时间慢慢回看",
                summary=excerpt,
                source_dates=dates,
            ),
            StorylineCandidate(
                id="daily-details",
                title="被记住的日常细节",
                summary=(bodies[0][:180] if bodies else excerpt),
                source_dates=first_date,
            ),
            StorylineCandidate(
                id="closing-moment",
                title="停在此刻的一天",
                summary=(bodies[-1][:180] if bodies else excerpt),
                source_dates=last_date,
            ),
        ]
    )


_THINK_BLOCK_RE = re.compile(r"<think>[\s\S]*?</think>", re.IGNORECASE)
_UNTERMINATED_THINK_RE = re.compile(r"<think>[\s\S]*$", re.IGNORECASE)
_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*([\s\S]*?)\s*```$", re.IGNORECASE)
MAX_STORYLINE_ID_LENGTH = 40
MAX_STORYLINE_TITLE_LENGTH = 80
MAX_STORYLINE_SUMMARY_LENGTH = 240
MAX_NARRATIVE_LENGTH = 12000


def _strip_model_wrappers(text: str) -> str:
    cleaned = _THINK_BLOCK_RE.sub("", text or "")
    cleaned = _UNTERMINATED_THINK_RE.sub("", cleaned).strip()
    match = _JSON_FENCE_RE.match(cleaned)
    if match:
        cleaned = match.group(1).strip()
    return cleaned


def _snapshot_lines(snapshots: list[Mapping[str, Any]]) -> str:
    lines = []
    for item in snapshots:
        lines.append(
            f"{item['date']} | {item['status']} | {item['body']}"
        )
    return "\n".join(lines)


def _parse_storylines(raw: str, allowed_dates: set[str]) -> StorylineResponse:
    try:
        data = json.loads(_strip_model_wrappers(raw))
    except (TypeError, json.JSONDecodeError) as exc:
        raise TimeStoryAIContractError() from exc
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list) or len(items) != 3:
        raise TimeStoryAIContractError()

    storylines: list[StorylineCandidate] = []
    seen_ids: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            raise TimeStoryAIContractError()
        candidate_id = str(item.get("id") or "").strip()
        title = str(item.get("title") or "").strip()
        summary = str(item.get("summary") or "").strip()
        source_dates = item.get("source_dates")
        if (
            not candidate_id
            or candidate_id in seen_ids
            or len(candidate_id) > MAX_STORYLINE_ID_LENGTH
            or not title
            or len(title) > MAX_STORYLINE_TITLE_LENGTH
            or not summary
            or len(summary) > MAX_STORYLINE_SUMMARY_LENGTH
            or not isinstance(source_dates, list)
        ):
            raise TimeStoryAIContractError()
        cleaned_dates = [
            str(value).strip() for value in source_dates if str(value).strip()
        ]
        if not cleaned_dates or any(date not in allowed_dates for date in cleaned_dates):
            raise TimeStoryAIContractError()
        seen_ids.add(candidate_id)
        storylines.append(
            StorylineCandidate(
                id=candidate_id,
                title=title,
                summary=summary,
                source_dates=cleaned_dates,
            )
        )
    return StorylineResponse(items=storylines)


async def generate_storyline_candidates(
    snapshots: list[Mapping[str, Any]],
) -> StorylineResponse:
    allowed_dates = {str(item["date"]) for item in snapshots}
    system_prompt = (
        "You are a grounded story editor. JSON only. "
        "不得虚构事实，不得加入输入之外的人物、对话、因果或结局。"
    )
    user_message = f"""从下面按时间顺序排列的日记中，提炼 3 条可供用户选择的时光故事线。

输入格式是 date | status | body：
{_snapshot_lines(snapshots)}

只输出 JSON，结构必须是：
{{"items":[{{"id":"stable-slug","title":"标题","summary":"摘要","source_dates":["YYYY-MM-DD"]}}]}}

硬要求：
- items 恰好 3 条
- id 必须唯一且稳定，最多 40 字符
- title 最多 80 字符，summary 最多 240 字符
- source_dates 只能从输入日记日期中选择
- 不得虚构事实"""

    raw = await request_chat_completion(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        temperature=0.3,
        max_tokens=1200,
        timeout=45,
    )
    return _parse_storylines(raw, allowed_dates)


async def generate_time_story_narrative(
    snapshots: list[Mapping[str, Any]],
    storyline: StorylineCandidate,
) -> str:
    system_prompt = (
        "你是一位严格尊重事实的长故事编辑。只使用输入材料，"
        "不虚构事实，不输出解释。"
    )
    selected = json.dumps(storyline.to_dict(), ensure_ascii=False)
    user_message = f"""请根据用户选中的故事线，把同一批日记 snapshots 改写为一篇连贯长文本。

【选中的故事线】
{selected}

【同一批 snapshots，格式 date | status | body】
{_snapshot_lines(snapshots)}

要求：
- 只围绕选中的故事线组织叙事
- 不添加输入之外的人物、对话、地点、动机、因果或结局
- 输出长文本本身，不要 Markdown 标题或 JSON"""

    text = await request_chat_completion(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        temperature=0.5,
        max_tokens=2400,
        timeout=60,
    )
    cleaned = _strip_model_wrappers(text).strip()
    if not cleaned:
        raise TimeStoryAIContractError()
    return cleaned[:MAX_NARRATIVE_LENGTH]
