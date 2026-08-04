import httpx
from config import IMAGE_API_BASE_URL, IMAGE_API_KEY, IMAGE_MODEL
from services.generation_errors import (
    GenerationConfigurationError,
    GenerationResponseError,
    GenerationServiceError,
    GenerationUpstreamError,
)


ImageServiceError = GenerationServiceError
ImageConfigurationError = GenerationConfigurationError
ImageUpstreamError = GenerationUpstreamError
ImageResponseError = GenerationResponseError

STYLE_PROMPTS = {
    "grid4": "四宫格手绘线条插画，像翻开一本手账本里的页面，四个温柔的格子分别捕捉一天里 4 个不同瞬间，简笔但有温度，淡彩点缀，画面边缘有手绘的不规则边框",
    "comic": "日式治愈系叙事漫画，3-4 个分镜讲述一天的小故事，人物表情生动可爱、有微妙情绪变化，节奏轻快但温暖，像看一本短篇绘本",
    "watercolor": "手绘水彩日记风，柔和的水彩晕染、明显的纸张肌理，色彩淡雅有层次，像一页从精装绘本里撕下来的日记，留白多、留白美",
    "pixel": "16-bit 像素艺术风，温暖的复古游戏调色板，柔和颗粒感，怀旧但不冷清，画面里藏着可爱的小元素",
    "ghibli": "吉卜力宫崎骏电影质感的治愈插画，柔和光影、强烈的空气感、温暖色温，自然元素融入日常（一缕阳光、一阵微风、一片树影），细腻笔触，色调饱和但不刺眼",
    "custom": None,
}


def _normalize_optional_prompt(value: str = None) -> str:
    return value.strip() if isinstance(value, str) else ""


def _require_image_configuration() -> None:
    # 遵循 BE-SECRET-001 规范: image credentials come only from environment
    # configuration and are never embedded in source or returned to clients.
    if not all(
        isinstance(value, str) and value.strip()
        for value in (IMAGE_API_BASE_URL, IMAGE_API_KEY, IMAGE_MODEL)
    ):
        raise ImageConfigurationError("image service is not configured")


def build_image_prompt(diary_text: str, style: str, custom_style_prompt: str = None) -> str:
    custom_style_prompt = _normalize_optional_prompt(custom_style_prompt)
    style_desc = STYLE_PROMPTS.get(style, STYLE_PROMPTS["ghibli"])
    if style == "custom":
        style_desc = custom_style_prompt or STYLE_PROMPTS["ghibli"]

    prompt = f"""从下面这段日记里，**挑出一个最有画面感、最能传达今天整体情绪的瞬间**（一杯还冒热气的茶 / 夕阳下的工位 / 深夜亮着的台灯 / 食堂的一勺红烧肉），把它画成一张 {style_desc} 的插画。

日记原文：
{diary_text}

画面要求（必须严格遵守）：
- **重氛围、轻情节**：用光线、色彩、构图、人物姿态传达"今天过得怎么样"，不要把日记里所有事都塞进画面
- **有烟火气**：画面要有家的味道——具体而柔软的细节胜过宏大场景
- **避免冷感**：哪怕画面里只有一个人，也要有温度——可以靠光线、色彩、姿态来托起；不要画成空旷孤独
- **画面里禁止出现任何文字**：no chinese characters, no english text, no watermark, no logo, no captions, no signs — 任何字符都会破坏画面
- **画面要让"挂念这个人的家人"看了想拨一通电话**：温暖、可亲、有可被聊起的小细节

输出一张治愈系插画。"""

    return prompt


def _response_image_source(item: object) -> str:
    """Return an upstream URL or in-memory data URL without writing files."""
    if not isinstance(item, dict):
        raise ImageResponseError("image service returned an invalid response")
    url = item.get("url")
    if isinstance(url, str) and url.strip():
        return url.strip()
    b64 = item.get("b64_json") or item.get("b64")
    if not isinstance(b64, str) or not b64.strip():
        raise ImageResponseError("image service returned an invalid response")
    return f"data:image/png;base64,{b64.strip()}"


async def _request_image(client: httpx.AsyncClient, prompt: str) -> str:
    try:
        response = await client.post(
            f"{IMAGE_API_BASE_URL.rstrip('/')}/images/generations",
            headers={"Authorization": f"Bearer {IMAGE_API_KEY}"},
            json={
                "model": IMAGE_MODEL,
                "prompt": prompt,
                "n": 1,
                "size": "1024x1024",
            },
        )
        response.raise_for_status()
        data = response.json()
    except httpx.HTTPError as exc:
        raise ImageUpstreamError(
            "image service is temporarily unavailable"
        ) from exc
    except (ValueError, TypeError) as exc:
        raise ImageResponseError(
            "image service returned an invalid response"
        ) from exc
    try:
        item = data["data"][0]
    except (KeyError, IndexError, TypeError):
        raise ImageResponseError(
            "image service returned an invalid response"
        ) from None
    return _response_image_source(item)


async def generate_image(diary_text: str, style: str, custom_style_prompt: str = None) -> str:
    """Call the image API and return an upstream URL or in-memory data URL."""
    _require_image_configuration()
    prompt = build_image_prompt(diary_text, style, custom_style_prompt)

    async with httpx.AsyncClient(timeout=180) as client:
        return await _request_image(client, prompt)


async def generate_batch(diary_text: str, paragraphs: list, style: str, n: int = 4, custom_style_prompt: str = None) -> list:
    """Generate candidate sources without writing them to the filesystem."""
    _require_image_configuration()
    target_text = "\n\n".join(paragraphs) if paragraphs else diary_text
    prompt = build_image_prompt(target_text, style, custom_style_prompt)

    urls = []
    async with httpx.AsyncClient(timeout=240) as client:
        for _ in range(max(1, min(n, 4))):
            urls.append(await _request_image(client, prompt))
    return urls
