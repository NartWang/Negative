import re
import httpx
from config import DIARY_API_BASE_URL, DIARY_API_KEY, DIARY_MODEL
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

# Strip reasoning blocks emitted by thinking-capable models (e.g. GLM thinking, DeepSeek-R1, Qwen3-thinking).
_THINK_BLOCK_RE = re.compile(r"<think>[\s\S]*?</think>", re.IGNORECASE)
_UNTERMINATED_THINK_RE = re.compile(r"<think>[\s\S]*$", re.IGNORECASE)
_LEFTOVER_TAG_RE = re.compile(r"</?think>", re.IGNORECASE)


def _strip_reasoning(text: str) -> str:
    if not text:
        return text
    cleaned = _THINK_BLOCK_RE.sub("", text)
    # If max_tokens cut us off mid-thought, drop the unterminated block + its content.
    cleaned = _UNTERMINATED_THINK_RE.sub("", cleaned)
    # Remove any stray bare tags.
    cleaned = _LEFTOVER_TAG_RE.sub("", cleaned)
    return cleaned.strip()

EMOTION_MODE_PROMPTS = {
    "real": "如实呈现，柔和但不回避辛苦。不夸大欢乐、也不放大焦虑，把今天真实的样子写给挂念你的家人看",
    "warm": "把辛苦藏在身后，把暖意放在前面。让远方的家人读完能松一口气——但不能假到像表演，真实的小温暖比刻意的'我很好'动人十倍",
    "humor": "把辛苦讲成段子，让看的人会心一笑。家人不愿被推到外面，但他们愿意陪你笑今天遇到的鸡毛蒜皮",
    "poetic": "把日常升华成散文。一个关于光、关于颜色、关于一个动作的细节，胜过十句直白的'我很想你'",
    "custom": None,  # Will use custom_emotion_prompt
}

STYLE_SPECIFIC = {
    "real": "用第二人称叙述，像给最关心你的家人写一封今天的短信",
    "warm": "用第二人称叙述，语气像在饭桌上轻松分享一天",
    "humor": "用第二人称叙述，像给好朋友讲今天的笑话",
    "poetic": "用第二人称叙述，用意象和细节代替直白抒情",
    "custom": "用第二人称叙述，按照用户要求的风格来写",
}


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
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise AIResponseError("AI service returned an invalid response") from None
    if not isinstance(content, str):
        raise AIResponseError("AI service returned an invalid response")
    cleaned = _strip_reasoning(content)
    if not cleaned:
        raise AIEmptyResponseError("AI service returned empty content")
    return cleaned


async def request_chat_completion(*, messages: list, timeout: int, **options) -> str:
    _require_diary_configuration()
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                f"{DIARY_API_BASE_URL.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {DIARY_API_KEY}"},
                json={
                    "model": DIARY_MODEL,
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


def build_diary_prompt(date: str, schedules: list, fragments: list, emotion_mode: str, custom_emotion_prompt: str = None) -> tuple[str, str]:
    """Returns (system_prompt, user_message)"""

    custom_emotion_prompt = _normalize_optional_prompt(custom_emotion_prompt)
    mode_desc = EMOTION_MODE_PROMPTS.get(emotion_mode, EMOTION_MODE_PROMPTS["real"])
    if emotion_mode == "custom":
        mode_desc = custom_emotion_prompt or EMOTION_MODE_PROMPTS["real"]

    style_instruction = STYLE_SPECIFIC.get(emotion_mode, STYLE_SPECIFIC["real"])

    system_prompt = f"""你是一位"情感翻译器"。你的读者不是用户自己——是**远方挂念 ta 的家人**（父母、伴侣、孩子、好友）。
你的任务：把今天记下的零散日程和碎片，翻译成一段让家人**愿意读、读得下去、读完能接得上话**的日记。

情感模式：{mode_desc}
{f'用户额外要求："{custom_emotion_prompt}"' if emotion_mode == 'custom' and custom_emotion_prompt else ''}
{style_instruction}

硬要求（违反任何一条都算失败）：
- 篇幅 200-350 字，家人不愿意读长文
- 第二人称"你"叙述
- 写成 2-4 段连贯的散文，**禁止列清单 / 分条目 / 用 emoji 装饰**
- 必须保留至少 **2 个具体细节**（食堂阿姨多给一勺 / 夕阳像橘子 / 决定寄蜂蜜 / 同事说的某句话）——这些细节是家人电话里能"接得上话"的抓手，是产品的灵魂
- 结尾要留一个**可以被回应的钩子**：一个等会儿想做的事 / 一个小决定 / 一个发现 / 一个心里的话——让家人看完想给你回一句
- 禁止用：'今天真是充实的一天' / '感受到了温暖' / '让我学到了' / '满满的收获' / '不禁让我想到' 这类空洞总结
- 禁止：把输入里的句子原样照抄进日记，必须重新组织叙述"""

    # Build schedule items text
    schedule_items = ""
    for s in schedules:
        status = "✅" if s.get("completed") else "⬜"
        feeling = f"，感受：{s['feeling']}" if s.get("feeling") else ""
        time_str = f"{s['time']} " if s.get("time") else ""
        schedule_items += f"- {status} {time_str}{s['title']}{feeling}\n"

    # Build fragments text
    fragments_text = ""
    for f in fragments:
        mood = f" [{f['mood_tag']}]" if f.get("mood_tag") else ""
        photo = f" 📷{f['photo_description']}" if f.get("photo_description") else ""
        fragments_text += f"- {f.get('content', '')}{mood}{photo}\n"

    user_message = f"""今天是 {date}。

【日程】
{schedule_items or '（无日程）'}

【碎片记录】
{fragments_text or '（无碎片记录）'}

请把今天翻译成一封给家人看的日记。记住：读者是挂念 ta 的家人，不是用户自己。"""

    return system_prompt, user_message


async def generate_diary(date: str, schedules: list, fragments: list, emotion_mode: str, custom_emotion_prompt: str = None) -> str:
    """Call GLM-5.1 to generate diary text."""
    system_prompt, user_message = build_diary_prompt(date, schedules, fragments, emotion_mode, custom_emotion_prompt)

    return await request_chat_completion(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        temperature=0.8,
        max_tokens=800,
        timeout=60,
    )


async def describe_photo(image_bytes: bytes, ext: str) -> str:
    """Use GLM-5.1 vision to describe a photo."""
    import base64
    b64 = base64.b64encode(image_bytes).decode()

    return await request_chat_completion(
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
    "warmer": "更温暖一些，让远方挂念 ta 的家人读完安心（但不能假，不能堆叠'我很好''别担心'这类直白话）",
    "humor": "更幽默一些，把辛苦变成段子，让家人会心一笑",
    "concise": "更简洁，去掉多余形容词和废话，保留最有画面感的细节",
    "poetic": "更诗意，用一个具体意象（光、声音、动作、物件）代替直白叙述",
}


async def rewrite_paragraph(paragraph: str, direction: str, custom_prompt: str = None) -> str:
    """Use GLM-5.1 to rewrite a single paragraph in the chosen direction."""
    custom_prompt = _normalize_optional_prompt(custom_prompt)
    if direction == "custom" and custom_prompt:
        guidance = custom_prompt
    else:
        guidance = REWRITE_DIRECTIONS.get(direction, REWRITE_DIRECTIONS["warmer"])

    system_prompt = f"""你是一位文字编辑。改写用户传来的这段话，让它{guidance}。

硬要求：
- 只输出改写后的文字本身，不要任何解释、引号、前缀后缀
- 保留原段落的核心信息和事件（具体细节不要丢）
- 保留第二人称"你"叙述
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
