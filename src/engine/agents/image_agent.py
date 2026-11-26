from __future__ import annotations

import asyncio

import httpx
from config import (
    CHARACTER_IMAGE_MODEL,
    CHARACTER_IMAGE_QUALITY,
    IMAGE_API_BASE_URL,
    IMAGE_API_KEY,
    IMAGE_API_KEYS,
    IMAGE_MODEL,
    PICTUREBOOK_IMAGE_SIZE,
    parse_image_api_keys,
)
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
    # The four picturebook styles. The full two-stage prompts live in
    # engine/prompts/<style>/; these short descriptions are for the older
    # single-image paths (weekly comic, dual timeline) that share the style key.
    "crayon": "儿童蜡笔画风，油性蜡笔叠色、笔触粗粝可见、纸张颗粒明显，颜色饱和但不刺眼，像小朋友贴在冰箱上的那张画，天真、笨拙、有手劲",
    "watercolor": "手绘水彩日记风，柔和的水彩晕染、明显的纸张肌理，色彩淡雅有层次，像一页从精装绘本里撕下来的日记，留白多、留白美",
    "sketch": "铅笔素描观察日记风，石墨线条为主、少量排线上调子，克制留白，像随身速写本里的一页，安静、诚实、不做修饰",
    "pixel": "16-bit 像素艺术风，温暖的复古游戏调色板，柔和颗粒感，怀旧但不冷清，画面里藏着可爱的小元素",
    "custom": None,
}
DEFAULT_STYLE_KEY = "watercolor"


def _normalize_optional_prompt(value: str = None) -> str:
    return value.strip() if isinstance(value, str) else ""


def configured_image_api_keys() -> tuple[str, ...]:
    """Return the imported pool, with a dynamic legacy fallback for old callers."""
    if isinstance(IMAGE_API_KEYS, str):
        raw_keys = IMAGE_API_KEYS
    else:
        try:
            raw_keys = ",".join(
                value for value in IMAGE_API_KEYS if isinstance(value, str)
            )
        except TypeError:
            raw_keys = ""
    return parse_image_api_keys(raw_keys, IMAGE_API_KEY)


def primary_image_api_key() -> str:
    keys = configured_image_api_keys()
    return keys[0] if keys else ""


def image_api_key_for_page(page_index: int) -> str:
    if not isinstance(page_index, int) or page_index < 0:
        raise ValueError("page index must be a non-negative integer")
    keys = configured_image_api_keys()
    return keys[page_index % len(keys)] if keys else ""


def _require_image_configuration(api_key: str = None) -> None:
    # 遵循 BE-SECRET-001 规范: image credentials come only from environment
    # configuration and are never embedded in source or returned to clients.
    selected_key = primary_image_api_key() if api_key is None else api_key
    if not all(
        isinstance(value, str) and value.strip()
        for value in (IMAGE_API_BASE_URL, selected_key, IMAGE_MODEL)
    ):
        raise ImageConfigurationError("image service is not configured")


def build_image_prompt(diary_text: str, style: str, custom_style_prompt: str = None) -> str:
    custom_style_prompt = _normalize_optional_prompt(custom_style_prompt)
    style_desc = STYLE_PROMPTS.get(style) or STYLE_PROMPTS[DEFAULT_STYLE_KEY]
    if style == "custom":
        style_desc = custom_style_prompt or STYLE_PROMPTS[DEFAULT_STYLE_KEY]

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


_MIME_EXTENSIONS = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
    "image/gif": "gif",
}

CHARACTER_SOURCE_MAX_EDGE = 512
CHARACTER_ATTEMPTS = 3
# The bundled sprites are webp/gif; normalize to PNG so any image backend that
# only accepts PNG for edits still works. Pillow is optional.
_EDIT_SAFE_MIME = {"image/png", "image/jpeg"}


def _as_edit_payload(content: bytes, mime_type: str) -> tuple[bytes, str]:
    """Return bytes safe to upload to /images/edits, converting when possible."""
    if mime_type in _EDIT_SAFE_MIME:
        return content, mime_type
    try:
        from io import BytesIO

        from PIL import Image
    except ImportError:
        return content, mime_type
    try:
        with Image.open(BytesIO(content)) as image:
            # Sprites are transparent; flatten onto white so the scene generator
            # never inherits an alpha fringe around the character.
            flattened = Image.new("RGBA", image.size, (255, 255, 255, 255))
            flattened.alpha_composite(image.convert("RGBA"))
            buffer = BytesIO()
            flattened.convert("RGB").save(buffer, "PNG")
            return buffer.getvalue(), "image/png"
    except Exception:
        return content, mime_type


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


async def _request_image(
    client: httpx.AsyncClient,
    prompt: str,
    *,
    api_key: str,
    size: str = "1024x1024",
) -> str:
    try:
        response = await client.post(
            f"{IMAGE_API_BASE_URL.rstrip('/')}/images/generations",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": IMAGE_MODEL,
                "prompt": prompt,
                "n": 1,
                "size": size,
            },
        )
        response.raise_for_status()
        data = response.json()
    except httpx.HTTPError:
        raise ImageUpstreamError(
            "image service is temporarily unavailable"
        ) from None
    except (ValueError, TypeError):
        raise ImageResponseError(
            "image service returned an invalid response"
        ) from None
    try:
        item = data["data"][0]
    except (KeyError, IndexError, TypeError):
        raise ImageResponseError(
            "image service returned an invalid response"
        ) from None
    return _response_image_source(item)


async def _request_reference_image(
    client: httpx.AsyncClient,
    prompt: str,
    reference: bytes,
    mime_type: str,
    *,
    api_key: str,
    size: str = "1024x1024",
) -> str:
    """Generate one illustration with the protagonist artwork as Image 1."""
    payload, upload_mime = _as_edit_payload(reference, mime_type)
    extension = _MIME_EXTENSIONS.get(upload_mime, "png")
    form = {
        "model": CHARACTER_IMAGE_MODEL or IMAGE_MODEL,
        "prompt": prompt,
        "n": "1",
        "size": size,
    }
    if CHARACTER_IMAGE_QUALITY:
        form["quality"] = CHARACTER_IMAGE_QUALITY

    last_error: Exception = ImageUpstreamError(
        "image service is temporarily unavailable"
    )
    for attempt in range(1, CHARACTER_ATTEMPTS + 1):
        try:
            response = await client.post(
                f"{IMAGE_API_BASE_URL.rstrip('/')}/images/edits",
                headers={"Authorization": f"Bearer {api_key}"},
                files={"image": (f"character.{extension}", payload, upload_mime)},
                data=form,
            )
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPError:
            last_error = ImageUpstreamError(
                "image service is temporarily unavailable"
            )
        except (ValueError, TypeError):
            last_error = ImageResponseError(
                "image service returned an invalid response"
            )
        else:
            try:
                item = data["data"][0]
            except (KeyError, IndexError, TypeError):
                raise ImageResponseError(
                    "image service returned an invalid response"
                ) from None
            return _response_image_source(item)
        if attempt < CHARACTER_ATTEMPTS:
            await asyncio.sleep(2 * attempt)
    raise last_error


async def generate_page_image(
    image_prompt: str,
    character: object = None,
    size: str = None,
    api_key: str | None = None,
) -> str:
    """Render one picturebook page from a self-contained prompt.

    The prompt already carries the style, composition and character lock, so it
    is passed through untouched. When a character is supplied its artwork goes in
    as Image 1, which pins the protagonist's identity far harder than text can.
    """
    selected_key = primary_image_api_key() if api_key is None else api_key
    _require_image_configuration(selected_key)
    prompt = (image_prompt or "").strip()
    if not prompt:
        raise ImageResponseError("page prompt is empty")

    target_size = size or PICTUREBOOK_IMAGE_SIZE
    if character is None:
        async with httpx.AsyncClient(timeout=300) as client:
            return await _request_image(
                client,
                prompt,
                api_key=selected_key,
                size=target_size,
            )

    async with httpx.AsyncClient(timeout=300) as client:
        return await _request_reference_image(
            client,
            prompt,
            character.content,
            character.mime_type,
            api_key=selected_key,
            size=target_size,
        )


async def generate_image(diary_text: str, style: str, custom_style_prompt: str = None) -> str:
    """Call the image API and return an upstream URL or in-memory data URL."""
    api_key = primary_image_api_key()
    _require_image_configuration(api_key)
    prompt = build_image_prompt(diary_text, style, custom_style_prompt)

    async with httpx.AsyncClient(timeout=180) as client:
        return await _request_image(client, prompt, api_key=api_key)


# Official prompt skeleton from 03_Prompts/05_单页绘本生成.md. Image 1 is the
# canonical protagonist; only pose, expression, camera view and scene may change.
SCENE_IDENTITY_LOCK = """Image 1 is the canonical protagonist of this picturebook. Preserve exactly the same person and fixed character design: hair silhouette, hair length, hair color, face shape, eye or glasses feature, age presentation, gender presentation, clothing category, main clothing colors, signature accessory and head-to-body ratio.

Change only the pose, expression, camera view and the scene required by this page. Keep natural everyday gestures and restrained expressions. The protagonist must remain recognizable at both face and full-body scale, and must be the only main character in the illustration.

Do not add major events, extra family members, or props that the diary does not mention. Avoid duplicated people, merged faces, extra fingers or limbs, clothing drift and style mixing."""


def build_scene_prompt(
    diary_text: str,
    style: str,
    custom_style_prompt: str = None,
    character_label: str = None,
) -> str:
    """The diary scene prompt, with the confirmed character locked as the star."""
    base = build_image_prompt(diary_text, style, custom_style_prompt)
    label = _normalize_optional_prompt(character_label)
    starring = (
        f"画面的主人公就是 Image 1 里这个角色（{label}）。"
        if label
        else "画面的主人公就是 Image 1 里这个角色。"
    )
    return f"{base}\n\n{starring}\n\n{SCENE_IDENTITY_LOCK}"


async def generate_batch(
    diary_text: str,
    paragraphs: list,
    style: str,
    custom_style_prompt: str = None,
    character: object = None,
) -> list:
    """Generate one illustration for the diary and return it as a single-item list.

    When `character` is provided (a `CharacterReference`), the confirmed
    protagonist is uploaded as Image 1 so the diary's star stays the same person.
    """
    api_key = primary_image_api_key()
    _require_image_configuration(api_key)
    target_text = "\n\n".join(paragraphs) if paragraphs else diary_text

    if character is None:
        prompt = build_image_prompt(target_text, style, custom_style_prompt)
        async with httpx.AsyncClient(timeout=240) as client:
            return [await _request_image(client, prompt, api_key=api_key)]

    prompt = build_scene_prompt(
        target_text, style, custom_style_prompt, getattr(character, "label", None)
    )
    async with httpx.AsyncClient(timeout=300) as client:
        return [
            await _request_reference_image(
                client,
                prompt,
                character.content,
                character.mime_type,
                api_key=api_key,
            )
        ]


# Official prompt from 03_Prompts/02_角色母版生成.md. The identity anchors and the
# negative constraints are kept verbatim: the model must translate the authorized
# photo into a pixel character design, never redesign or beautify the person.
CHARACTER_MASTER_PROMPT = """Use case: identity-preserving illustrated protagonist creation
Asset type: canonical master for one reusable Q-version 2D pixel picturebook character

Create exactly one original Q-version 2D pixel-art character based on the authorized person in Image 1. This is a character-design translation, not a realistic portrait and not a different person.

Preserve these visible identity anchors exactly as they appear in Image 1: hair silhouette, hair length, hair color, face-shape tendency, eye or glasses feature, age presentation, gender presentation, clothing category and main clothing colors, and any signature accessory.

Visual system: approximately 2.4 to 2.6 heads tall, oversized rounded head, tiny compact body, short limbs, simple dark pixel eyes, tiny mouth, restrained blush marks, crisp deliberate square pixel clusters, consistent dark-brown pixel outline, limited warm palette, and flat pixel shading. Warm, gentle and readable as a small picturebook protagonist. Clearly 2D pixel art, not smooth illustration.

Straight front-view relaxed standing pose with a calm friendly expression. Exactly one complete full-body character, both hands and shoes visible, centered on pure white with generous safe padding, square 1:1 canvas.

Negative constraints: no photorealism, no 3D, no plastic skin, no porcelain or BJD doll, no glass eyes, no generic anime face, no age regression into a toddler, no smooth vector edges, no scene, no text, no watermark, no extra person, no duplicated limb, no cropped feet, no invented accessory, and no change to visible hairstyle, glasses, clothing category or main colors."""


def build_character_master_prompt(description: str = None) -> str:
    """Append the user's own words as a low-priority hint, never as an override."""
    hint = _normalize_optional_prompt(description)
    if not hint:
        return CHARACTER_MASTER_PROMPT
    return (
        f"{CHARACTER_MASTER_PROMPT}\n\n"
        "Additional low-priority hint written by the person themself. Use it only "
        "where it does not contradict Image 1, and never let it change the visible "
        f"hairstyle, glasses, clothing category or main colors: {hint}"
    )


def _shrink_source_photo(photo: bytes, mime_type: str) -> tuple[bytes, str]:
    """Send a small reference: the upstream only needs visible features.

    Pillow is optional; without it the original bytes are sent unchanged.
    """
    try:
        from io import BytesIO

        from PIL import Image
    except ImportError:
        return photo, mime_type
    try:
        with Image.open(BytesIO(photo)) as image:
            if max(image.size) <= CHARACTER_SOURCE_MAX_EDGE:
                return photo, mime_type
            converted = image.convert("RGB")
            converted.thumbnail(
                (CHARACTER_SOURCE_MAX_EDGE, CHARACTER_SOURCE_MAX_EDGE),
                Image.LANCZOS,
            )
            buffer = BytesIO()
            converted.save(buffer, "PNG")
            return buffer.getvalue(), "image/png"
    except Exception:
        return photo, mime_type


async def generate_character_master(
    photo: bytes,
    mime_type: str,
    description: str = None,
) -> str:
    """Turn an authorized photo into one Q-version pixel character master.

    Returns an upstream URL or an in-memory data URL; the caller is responsible
    for materializing and storing it. The photo is only sent to the image
    service, never persisted anywhere new by this function.
    """
    api_key = primary_image_api_key()
    _require_image_configuration(api_key)
    if not isinstance(photo, bytes) or not photo:
        raise ImageResponseError("source photo is missing")

    payload, upload_mime = _shrink_source_photo(photo, mime_type)
    extension = _MIME_EXTENSIONS.get(upload_mime, "png")
    form = {
        "model": CHARACTER_IMAGE_MODEL or IMAGE_MODEL,
        "prompt": build_character_master_prompt(description),
        "n": "1",
        "size": "1024x1024",
    }
    if CHARACTER_IMAGE_QUALITY:
        form["quality"] = CHARACTER_IMAGE_QUALITY

    last_error: Exception = ImageUpstreamError(
        "image service is temporarily unavailable"
    )
    async with httpx.AsyncClient(timeout=300) as client:
        # The shared image proxy fails intermittently with499/504 when the
        # upstream is slow, so a transient failure is retried before giving up.
        for attempt in range(1, CHARACTER_ATTEMPTS + 1):
            try:
                response = await client.post(
                    f"{IMAGE_API_BASE_URL.rstrip('/')}/images/edits",
                    headers={"Authorization": f"Bearer {api_key}"},
                    files={
                        "image": (f"source.{extension}", payload, upload_mime),
                    },
                    data=form,
                )
                response.raise_for_status()
                data = response.json()
            except httpx.HTTPError:
                last_error = ImageUpstreamError(
                    "image service is temporarily unavailable"
                )
            except (ValueError, TypeError):
                last_error = ImageResponseError(
                    "image service returned an invalid response"
                )
            else:
                try:
                    item = data["data"][0]
                except (KeyError, IndexError, TypeError):
                    raise ImageResponseError(
                        "image service returned an invalid response"
                    ) from None
                return _response_image_source(item)
            if attempt < CHARACTER_ATTEMPTS:
                await asyncio.sleep(2 * attempt)
    raise last_error
