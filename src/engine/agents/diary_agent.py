import re
from functools import lru_cache
from pathlib import Path

import httpx
from config import DIARY_API_BASE_URL, DIARY_API_KEY, DIARY_MODEL, VISION_MODEL
from services.generation_errors import (
    GenerationConfigurationError,
    GenerationEmptyResponseError,
    GenerationResponseError,
    GenerationServiceError,
    GenerationUpstreamError,
)


AIServiceError = GenerationServiceError
AIConfigurationError = GenerationConfigurationError
AIUpstreamError = GenerationUpstreamError
AIResponseError = GenerationResponseError
AIEmptyResponseError = GenerationEmptyResponseError

DIARY_SOURCE_CHAR_LIMIT = 4000
_DIARY_MIN_OUTPUT_TOKENS = 800
_DIARY_MAX_OUTPUT_TOKENS = 4096
_DIARY_OUTPUT_TOKEN_BUFFER = 256

# Strip reasoning blocks emitted by thinking-capable models.
_THINK_BLOCK_RE = re.compile(r"<think>[\s\S]*?</think>", re.IGNORECASE)
_UNTERMINATED_THINK_RE = re.compile(r"<think>[\s\S]*$", re.IGNORECASE)
_LEFTOVER_TAG_RE = re.compile(r"</?think>", re.IGNORECASE)
_PROMPT_PLACEHOLDER_RE = re.compile(
    r"\{\{(text|fragments|photos|allow_imaginative)\}\}"
)
_DIARY_PROMPT_PATH = (
    Path(__file__).resolve().parent.parent / "prompts" / "diary" / "user-visible.txt"
)
_PICTUREBOOK_SOURCE_PROMPT_PATH = (
    Path(__file__).resolve().parent.parent
    / "prompts"
    / "diary"
    / "picturebook-source.txt"
)


def _strip_reasoning(text: str) -> str:
    if not text:
        return text
    cleaned = _THINK_BLOCK_RE.sub("", text)
    # If max_tokens cut us off mid-thought, drop the unterminated block + its content.
    cleaned = _UNTERMINATED_THINK_RE.sub("", cleaned)
    # Remove any stray bare tags.
    cleaned = _LEFTOVER_TAG_RE.sub("", cleaned)
    return cleaned.strip()

def _normalize_optional_prompt(value: str = None) -> str:
    return value.strip() if isinstance(value, str) else ""


def _require_diary_configuration() -> None:
    # 遵循 BE-SECRET-001 规范: credentials are accepted only from environment
    # configuration and are never embedded in source or returned to clients.
    if not all(
        isinstance(value, str) and value.strip()
        for value in (DIARY_API_BASE_URL, DIARY_API_KEY, DIARY_MODEL)
    ):
        raise AIConfigurationError("AI service is not configured")


def _extract_completion_text(data: object) -> str:
    try:
        choice = data["choices"][0]
        content = choice["message"]["content"]
        finish_reason = choice.get("finish_reason")
    except (AttributeError, KeyError, IndexError, TypeError):
        raise AIResponseError("AI service returned an invalid response") from None
    if finish_reason == "length":
        raise AIResponseError("AI service returned truncated content")
    if not isinstance(content, str):
        raise AIResponseError("AI service returned an invalid response")
    cleaned = _strip_reasoning(content)
    if not cleaned:
        raise AIEmptyResponseError("AI service returned empty content")
    return cleaned


async def request_chat_completion(
    *, messages: list, timeout: int, model: str = None, **options
) -> str:
    _require_diary_configuration()
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                f"{DIARY_API_BASE_URL.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {DIARY_API_KEY}"},
                json={
                    "model": model or DIARY_MODEL,
                    "messages": messages,
                    **options,
                },
            )
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError as exc:
        raise AIUpstreamError(
            "AI service is temporarily unavailable"
        ) from exc
    except (ValueError, TypeError) as exc:
        raise AIResponseError(
            "AI service returned an invalid response"
        ) from exc
    return _extract_completion_text(data)


@lru_cache(maxsize=1)
def load_diary_prompt() -> str:
    """Load the user-visible diary prompt without rewriting its instructions."""
    try:
        return _DIARY_PROMPT_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        raise AIConfigurationError("diary prompt template is missing") from exc


@lru_cache(maxsize=1)
def load_picturebook_source_prompt() -> str:
    """Load the hidden Prompt 2 template used before daily story writing."""
    try:
        return _PICTUREBOOK_SOURCE_PROMPT_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        raise AIConfigurationError(
            "picturebook source prompt template is missing"
        ) from exc


def _format_items(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items) or "（无）"


def diary_source_char_count(text: str, fragments: list) -> int:
    """Count only user source characters that Prompt 1 is allowed to use."""
    total = len(_normalize_optional_prompt(text))
    for item in fragments:
        total += len(_normalize_optional_prompt(item.get("content")))
        total += len(_normalize_optional_prompt(item.get("photo_description")))
    return total


def _diary_output_token_budget(text: str, fragments: list) -> int:
    source_chars = diary_source_char_count(text, fragments)
    return min(
        _DIARY_MAX_OUTPUT_TOKENS,
        max(_DIARY_MIN_OUTPUT_TOKENS, source_chars + _DIARY_OUTPUT_TOKEN_BUFFER),
    )


def build_diary_prompt(
    text: str,
    fragments: list,
    allow_imaginative: bool,
) -> str:
    """Render Prompt 1 while keeping each source type in its own input group."""
    fragment_items = []
    photo_items = []
    for item in fragments:
        content = _normalize_optional_prompt(item.get("content"))
        if content:
            fragment_items.append(content)
        photo_description = _normalize_optional_prompt(
            item.get("photo_description")
        )
        if photo_description:
            photo_items.append(photo_description)

    values = {
        "text": _normalize_optional_prompt(text) or "（无）",
        "fragments": _format_items(fragment_items),
        "photos": _format_items(photo_items),
        "allow_imaginative": "true" if allow_imaginative else "false",
    }
    return _PROMPT_PLACEHOLDER_RE.sub(
        lambda match: values[match.group(1)],
        load_diary_prompt(),
    )


def build_picturebook_source_prompt(text: str, allow_imaginative: bool) -> str:
    """Render Prompt 2 from the immutable text selected for a daily picturebook."""
    values = {
        "text": _normalize_optional_prompt(text) or "（无）",
        "allow_imaginative": "true" if allow_imaginative else "false",
    }
    return _PROMPT_PLACEHOLDER_RE.sub(
        lambda match: values[match.group(1)],
        load_picturebook_source_prompt(),
    )


async def adapt_for_picturebook(text: str, allow_imaginative: bool) -> str:
    """Adapt selected daily text for story generation with the diary model."""
    prompt = build_picturebook_source_prompt(text, allow_imaginative)
    result = await request_chat_completion(
        model=DIARY_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
        max_tokens=1100,
        timeout=60,
    )
    if not result.strip():
        raise AIEmptyResponseError("AI service returned empty content")
    return result


async def generate_diary(
    text: str,
    fragments: list,
    allow_imaginative: bool,
) -> str:
    """Generate diary text with the configured diary model."""
    prompt = build_diary_prompt(
        text=text,
        fragments=fragments,
        allow_imaginative=allow_imaginative,
    )

    return await request_chat_completion(
        model=DIARY_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.8,
        max_tokens=_diary_output_token_budget(text, fragments),
        timeout=60,
    )


def vision_is_configured() -> bool:
    """Return whether a model is configured for photo descriptions."""
    return bool(VISION_MODEL)


async def describe_photo(image_bytes: bytes, ext: str) -> str:
    """Describe a photo with VISION_MODEL and the main diary credentials."""
    if not vision_is_configured():
        raise AIConfigurationError("vision model is not configured")

    import base64
    b64 = base64.b64encode(image_bytes).decode()

    return await request_chat_completion(
        model=VISION_MODEL,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "用一句话描述这张照片的内容和氛围，用于日记写作。"},
                    {"type": "image_url", "image_url": {"url": f"data:image/{ext.lstrip('.')};base64,{b64}"}},
                ],
            }
        ],
        max_tokens=100,
        timeout=30,
    )


REWRITE_DIRECTIONS = {
    "warmer": "更温暖一些，让未来回看的自己能接住当时的状态（但不能假，不能堆叠'我很好''别担心'这类直白话）",
    "humor": "更幽默一些，把辛苦写得轻一点，但不要改掉事实",
    "concise": "更简洁，去掉多余形容词和废话，保留最有画面感的细节",
    "poetic": "更诗意，用一个具体意象（光、声音、动作、物件）代替直白叙述",
}


async def rewrite_paragraph(paragraph: str, direction: str, custom_prompt: str = None) -> str:
    """Use the diary model to rewrite one paragraph in the chosen direction."""
    custom_prompt = _normalize_optional_prompt(custom_prompt)
    if direction == "custom" and custom_prompt:
        guidance = custom_prompt
    else:
        guidance = REWRITE_DIRECTIONS.get(direction, REWRITE_DIRECTIONS["warmer"])

    system_prompt = f"""你是一位文字编辑。改写用户传来的这段话，让它{guidance}。

硬要求：
- 只输出改写后的文字本身，不要任何解释、引号、前缀后缀
- 保留原段落的核心信息和事件（具体细节不要丢）
- 保留原有叙述人称，不要强行改成写给别人
- 字数与原文相当（误差 ±30%）
- 禁止加入"今天真是""感受到了"这类空洞模板"""

    return await request_chat_completion(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": paragraph},
        ],
        temperature=0.7,
        max_tokens=600,
        timeout=60,
    )
