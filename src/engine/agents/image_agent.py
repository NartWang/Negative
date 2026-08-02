import base64
import os
import uuid
import httpx
from config import IMAGE_API_BASE_URL, IMAGE_API_KEY, IMAGE_MODEL

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

STYLE_PROMPTS = {
    "grid4": "四宫格手绘线条插画，像翻开一本手账本里的页面，四个温柔的格子分别捕捉一天里 4 个不同瞬间，简笔但有温度，淡彩点缀，画面边缘有手绘的不规则边框",
    "comic": "日式治愈系叙事漫画，3-4 个分镜讲述一天的小故事，人物表情生动可爱、有微妙情绪变化，节奏轻快但温暖，像看一本短篇绘本",
    "watercolor": "手绘水彩日记风，柔和的水彩晕染、明显的纸张肌理，色彩淡雅有层次，像一页从精装绘本里撕下来的日记，留白多、留白美",
    "pixel": "16-bit 像素艺术风，温暖的复古游戏调色板，柔和颗粒感，怀旧但不冷清，画面里藏着可爱的小元素",
    "ghibli": "吉卜力宫崎骏电影质感的治愈插画，柔和光影、强烈的空气感、温暖色温，自然元素融入日常（一缕阳光、一阵微风、一片树影），细腻笔触，色调饱和但不刺眼",
    "custom": None,
}


def build_image_prompt(diary_text: str, style: str, custom_style_prompt: str = None) -> str:
    style_desc = STYLE_PROMPTS.get(style, STYLE_PROMPTS["ghibli"])
    if style == "custom" and custom_style_prompt:
        style_desc = custom_style_prompt

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


def _persist_response_image(item: dict) -> str:
    """Take one entry from data[i] and return a local /api/upload/<file> url.
    Supports both `url` and `b64_json` response shapes.
    """
    if item.get("url"):
        # URL returned — caller (router) downloads it; we just pass through
        return item["url"]
    b64 = item.get("b64_json") or item.get("b64")
    if not b64:
        raise RuntimeError("image generation response has neither url nor b64_json")
    filename = f"img_{uuid.uuid4().hex}.png"
    filepath = os.path.join(UPLOAD_DIR, filename)
    with open(filepath, "wb") as f:
        f.write(base64.b64decode(b64))
    return f"/api/upload/{filename}"


async def generate_image(diary_text: str, style: str, custom_style_prompt: str = None) -> str:
    """Call image API and return a URL (either upstream URL or local /api/upload/...)."""
    prompt = build_image_prompt(diary_text, style, custom_style_prompt)

    async with httpx.AsyncClient(timeout=180) as client:
        response = await client.post(
            f"{IMAGE_API_BASE_URL}/images/generations",
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
        return _persist_response_image(data["data"][0])


async def generate_batch(diary_text: str, paragraphs: list, style: str, n: int = 4, custom_style_prompt: str = None) -> list:
    """Generate N candidate images. Returns a list of URLs (upstream or local /api/upload/...)."""
    target_text = "\n\n".join(paragraphs) if paragraphs else diary_text
    prompt = build_image_prompt(target_text, style, custom_style_prompt)

    urls = []
    async with httpx.AsyncClient(timeout=240) as client:
        for _ in range(max(1, min(n, 4))):
            response = await client.post(
                f"{IMAGE_API_BASE_URL}/images/generations",
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
            urls.append(_persist_response_image(data["data"][0]))
    return urls
