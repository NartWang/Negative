"""Two-stage picturebook writer.

Stage 1 turns the finished diary into a structured story JSON (fact ledger +
cover + exactly eight pages). Stage 2 turns that story JSON into nine
self-contained English image prompts (cover + eight pages).

The prompt bodies are the author's originals, kept verbatim as data files under
`prompts/<style>/{story,pages}.txt` so they can be edited without touching code.
Placeholders are filled, never rewritten.

The model must produce long structured JSON *and* read images (for character
visual profiles), so a reasoning-only model is unusable here: it spends its whole
budget on hidden reasoning and returns an empty body.
"""

from __future__ import annotations

import asyncio
import base64
import json
import re
from functools import lru_cache
from pathlib import Path

import httpx
from config import DIARY_API_BASE_URL, DIARY_API_KEY, STORY_MODEL
from services.generation_errors import (
    GenerationConfigurationError,
    GenerationResponseError,
    GenerationServiceError,
    GenerationUpstreamError,
)

PROMPT_ROOT = Path(__file__).resolve().parent.parent / "prompts"

# Style key -> the story-JSON placeholder its stage-2 prompt expects.
STYLES: dict[str, str] = {
    "crayon": "{{CRAYON_STORY_JSON}}",
    "watercolor": "{{WATERCOLOR_STORY_JSON}}",
    "sketch": "{{SKETCH_STORY_JSON}}",
    "pixel": "{{PIXEL_GAME_STORY_JSON}}",
}
DEFAULT_STYLE = "watercolor"
TOTAL_IMAGES = 9

STORY_TIMEOUT = 300
STORY_ATTEMPTS = 3
STORY_MAX_TOKENS = 16_000
PAGES_MAX_TOKENS = 32_000
PROFILE_MAX_TOKENS = 1_200

CHARACTER_PROFILE_INSTRUCTION = (
    "你是角色设定师。看这张角色母版，输出一份中文角色档，只描述图中可见特征，"
    "不要推测背景故事。严格按行输出：发型与发色/脸型与眼睛/年龄与性别呈现/"
    "上衣（含颜色）/下装（含颜色）/鞋/配饰/头身比与体型/主色板。"
    "看不出的写「未显示」。不要任何额外说明。"
)


class StoryConfigurationError(GenerationConfigurationError):
    pass


class StoryUpstreamError(GenerationUpstreamError):
    pass


class StoryResponseError(GenerationResponseError):
    pass


def normalize_style(style: str) -> str:
    return style if style in STYLES else DEFAULT_STYLE


@lru_cache(maxsize=None)
def load_prompt(style: str, stage: str) -> str:
    """Read a prompt body from disk once, keeping the author's text verbatim."""
    path = PROMPT_ROOT / normalize_style(style) / f"{stage}.txt"
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise StoryConfigurationError(
            f"prompt template is missing: {path.name}"
        ) from exc


def _require_configuration() -> None:
    if not DIARY_API_BASE_URL or not DIARY_API_KEY:
        raise StoryConfigurationError("story model is not configured")


def _extract_json(text: str) -> dict:
    """Parse the model's JSON, tolerating a```json fence."""
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        parsed = json.loads(cleaned)
    except (ValueError, TypeError) as exc:
        raise StoryResponseError(
            "story model returned malformed JSON"
        ) from exc
    if not isinstance(parsed, dict):
        raise StoryResponseError("story model returned malformed JSON")
    return parsed


def _upstream_message(exc: httpx.HTTPError) -> str:
    """Surface the upstream's own words: a generic message hides the real cause.

    A 401/402/403 here is almost always a key or balance problem, which stays
    broken until a human fixes it — very different from a 429/5xx blip.
    """
    response = getattr(exc, "response", None)
    if response is None:
        return "故事模型连接失败，请稍后重试"

    detail = ""
    try:
        payload = response.json()
        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict):
                detail = str(error.get("message") or "")
            elif isinstance(error, str):
                detail = error
    except ValueError:
        detail = (response.text or "")[:200]

    status = response.status_code
    if status in (401, 402, 403):
        return f"故事模型不可用（HTTP {status}）：{detail or '密钥或余额有问题'}"[:400]
    if status == 429:
        return f"故事模型被限流（HTTP 429），稍后重试：{detail}"[:400]
    return f"故事模型返回 HTTP {status}：{detail or '上游错误'}"[:400]


async def _complete(
    messages: list,
    *,
    max_tokens: int,
    as_json: bool = True,
) -> str:
    _require_configuration()
    body: dict = {
        "model": STORY_MODEL,
        "messages": messages,
        # gpt-5 style models reject `max_tokens`; both spellings are sent so a
        # swapped-in model keeps a hard output ceiling either way.
        "max_completion_tokens": max_tokens,
    }
    if as_json:
        body["response_format"] = {"type": "json_object"}

    last_error: Exception = StoryUpstreamError("故事模型连接失败，请稍后重试")
    async with httpx.AsyncClient(timeout=STORY_TIMEOUT) as client:
        for attempt in range(1, STORY_ATTEMPTS + 1):
            try:
                response = await client.post(
                    f"{DIARY_API_BASE_URL.rstrip('/')}/chat/completions",
                    headers={"Authorization": f"Bearer {DIARY_API_KEY}"},
                    json=body,
                )
                response.raise_for_status()
                data = response.json()
            except httpx.HTTPError as exc:
                message = _upstream_message(exc)
                status = getattr(getattr(exc, "response", None), "status_code", None)
                # Auth and balance failures never recover on their own: fail fast
                # instead of burning three attempts and several minutes.
                if status in (401, 402, 403):
                    raise StoryConfigurationError(message) from exc
                last_error = StoryUpstreamError(message)
                last_error.__cause__ = exc
            except (ValueError, TypeError) as exc:
                last_error = StoryResponseError("故事模型返回了无法解析的内容")
                last_error.__cause__ = exc
            else:
                try:
                    content = data["choices"][0]["message"]["content"]
                except (KeyError, IndexError, TypeError) as exc:
                    raise StoryResponseError("故事模型返回了无法解析的内容") from exc
                if not (content or "").strip():
                    # A reasoning-only model lands here: budget spent, nothing emitted.
                    raise StoryResponseError(
                        f"模型 {STORY_MODEL} 没有返回正文，请换一个非推理型模型"
                    )
                return content
            if attempt < STORY_ATTEMPTS:
                await asyncio.sleep(3 * attempt)
    raise last_error


async def describe_character(content: bytes, mime_type: str) -> str:
    """Derive a character_lock text profile from the character artwork."""
    encoded = base64.b64encode(content).decode()
    text = await _complete(
        [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": CHARACTER_PROFILE_INSTRUCTION},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime_type};base64,{encoded}"},
                    },
                ],
            }
        ],
        max_tokens=PROFILE_MAX_TOKENS,
        as_json=False,
    )
    return text.strip()


async def write_story(diary_text: str, character_profile: str, style: str) -> dict:
    """Stage 1: diary -> story JSON with a cover and exactly eight pages."""
    template = load_prompt(style, "story")
    prompt = (
        template.replace("{{FULL_DIARY}}", diary_text.strip())
        .replace("{{CHARACTER_PROFILE}}", character_profile.strip() or "未提供")
        .replace("{{OPTIONAL_FACTS}}", "无")
    )
    raw = await _complete(
        [{"role": "user", "content": prompt}],
        max_tokens=STORY_MAX_TOKENS,
    )
    story = _extract_json(raw)
    pages = story.get("pages")
    if not isinstance(pages, list) or len(pages) != 8:
        raise StoryResponseError("story JSON does not contain exactly eight pages")
    return story


async def write_page_prompts(
    story: dict,
    character_profile: str,
    style: str,
) -> dict:
    """Stage 2: story JSON -> nine self-contained image prompts."""
    key = normalize_style(style)
    template = load_prompt(key, "pages")
    prompt = (
        template.replace(STYLES[key], json.dumps(story, ensure_ascii=False))
        .replace("{{CHARACTER_PROFILE}}", character_profile.strip() or "未提供")
        .replace("{{SUPPORTING_CHARACTER_PROFILES}}", "无")
        .replace("{{STYLE_REFERENCE_NOTES}}", "无")
    )
    raw = await _complete(
        [{"role": "user", "content": prompt}],
        max_tokens=PAGES_MAX_TOKENS,
    )
    plan = _extract_json(raw)
    if not flatten_image_prompts(plan):
        raise StoryResponseError("page plan does not contain any image prompts")
    return plan


def flatten_image_prompts(plan: dict, story: dict | None = None) -> list[dict]:
    """Return [cover, page1..page8] in reading order with their prompts."""
    entries: list[dict] = []

    cover = plan.get("cover")
    story_cover = story.get("cover", {}) if isinstance(story, dict) else {}
    if isinstance(cover, dict) and cover.get("image_prompt"):
        entries.append(
            {
                "page_index": 0,
                "image_id": str(cover.get("image_id") or "cover"),
                "caption": str(
                    story_cover.get("story_summary")
                    or cover.get("real_event")
                    or ""
                ).strip(),
                "image_prompt": str(cover["image_prompt"]).strip(),
            }
        )

    pages = plan.get("pages")
    story_pages = story.get("pages", []) if isinstance(story, dict) else []
    if isinstance(pages, list):
        for order, page in enumerate(pages, start=1):
            if not isinstance(page, dict) or not page.get("image_prompt"):
                continue
            try:
                number = int(page.get("page") or order)
            except (TypeError, ValueError):
                number = order
            story_page = next(
                (
                    item for item in story_pages
                    if isinstance(item, dict) and int(item.get("page") or -1) == number
                ),
                {},
            )
            entries.append(
                {
                    "page_index": number,
                    "image_id": str(page.get("image_id") or f"page-{number}"),
                    "caption": str(
                        story_page.get("real_event")
                        or page.get("real_event")
                        or ""
                    ).strip(),
                    "image_prompt": str(page["image_prompt"]).strip(),
                }
            )

    entries.sort(key=lambda item: item["page_index"])
    return entries


__all__ = [
    "DEFAULT_STYLE",
    "GenerationServiceError",
    "STYLES",
    "TOTAL_IMAGES",
    "describe_character",
    "flatten_image_prompts",
    "normalize_style",
    "write_page_prompts",
    "write_story",
]
