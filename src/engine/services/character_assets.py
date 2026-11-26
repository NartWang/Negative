"""Resolve the caller's confirmed character into bytes for image generation.

A confirmed character can come from two places:

* a bundled preset sprite served by the frontend (`/characters/main/pNN.webp`)
* a generated master stored as the caller's own media asset (`/api/media/<id>`)

The picturebook generator needs the actual pixels, so this module maps either
form onto a file it is allowed to read. Preset paths are resolved inside the
bundled asset directory only, and media ids go through the ownership check.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Optional

from config import get_character_asset_dir
from services.media_store import (
    MediaStoreError,
    asset_file_path,
    parse_canonical_media_url,
    require_owned_asset,
)

PRESET_URL_PREFIX = "/characters/"

# Bundled presets must still have a usable identity lock when the optional
# vision-description call is unavailable. Keep this data beside the backend
# asset resolver so generation never depends on frontend-only metadata.
_PRESET_VISUAL_PROFILES = {
    "p02": (
        "发型与发色：及腰的蓬松棕色长卷发，中分，左右两侧自然包住脸颊；"
        "脸型与眼睛：柔和圆润脸型，深棕色大眼睛；年龄与性别呈现：年轻成年女性；"
        "上衣：白色圆领内搭与米白色针织开衫；下装：浅米色及踝长裙；"
        "鞋：深棕色低跟鞋；配饰：无明显配饰；"
        "头身比与体型：Q版约三头身，纤细，完整成人比例；"
        "主色板：暖棕、米白、浅米色。"
    ),
}

_EXTENSION_MIME = {
    ".webp": "image/webp",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}


@dataclass(frozen=True)
class CharacterReference:
    """The protagonist artwork plus the words used to describe them."""

    content: bytes
    mime_type: str
    name: str
    description: str
    visual_profile: str = ""

    @property
    def label(self) -> str:
        return self.name or self.description or "the protagonist"

    @property
    def signature(self) -> str:
        """Identity of the artwork currently in use, for cache invalidation."""
        return hashlib.sha256(self.content).hexdigest()[:32]

    def profile_text(self) -> str:
        """The character_lock text handed to the story and page prompts."""
        lines = []
        if self.name:
            lines.append(f"昵称：{self.name}")
        if self.description and self.description != self.name:
            lines.append(f"气质：{self.description}")
        if self.visual_profile:
            lines.append("可见特征（以角色母版为准，不得改动）：")
            lines.append(self.visual_profile)
        return "\n".join(lines)


def _preset_file(url: str) -> Optional[Path]:
    """Map `/characters/main/p13.webp` onto the bundled sprite, safely."""
    relative = url[len(PRESET_URL_PREFIX):].split("?", 1)[0].split("#", 1)[0]
    if not relative:
        return None
    root = Path(get_character_asset_dir()).resolve()
    try:
        candidate = (root / relative).resolve()
    except OSError:
        return None
    # 遵循 BE-PATH-001 规范: never read outside the bundled asset directory.
    if root not in candidate.parents:
        return None
    if candidate.suffix.lower() not in _EXTENSION_MIME:
        return None
    return candidate if candidate.is_file() else None


async def load_character_reference(
    db: Any,
    user_id: int,
) -> Optional[CharacterReference]:
    """Return the caller's confirmed character artwork, or None if unset."""
    cursor = await db.execute(
        "SELECT reference_image_url, nickname, character_description, visual_profile "
        "FROM character_profiles WHERE user_id = ?",
        (user_id,),
    )
    row = await cursor.fetchone()
    if not row:
        return None

    profile = dict(row)
    url = (profile.get("reference_image_url") or "").strip()
    if not url:
        return None

    name = (profile.get("nickname") or "").strip()
    description = (profile.get("character_description") or "").strip()
    visual_profile = (profile.get("visual_profile") or "").strip()

    if url.startswith(PRESET_URL_PREFIX):
        path = _preset_file(url)
        if path is None:
            return None
        return CharacterReference(
            content=path.read_bytes(),
            mime_type=_EXTENSION_MIME[path.suffix.lower()],
            name=name,
            description=description,
            visual_profile=visual_profile,
        )

    asset_id = parse_canonical_media_url(url)
    if not asset_id:
        return None
    try:
        asset = await require_owned_asset(db, user_id, asset_id)
        content = asset_file_path(asset).read_bytes()
    except (MediaStoreError, OSError):
        return None
    return CharacterReference(
        content=content,
        mime_type=asset.mime_type,
        name=name,
        description=description,
        visual_profile=visual_profile,
    )


async def ensure_visual_profile(
    db: Any,
    user_id: int,
    character: CharacterReference,
) -> CharacterReference:
    """Derive and cache the character_lock text the first time it is needed.

    The picturebook prompts repeat a textual character lock in all nine images,
    so a thin "云奶奶 ·慈爱温暖" would let the model invent a hairstyle that
    fights the reference artwork. The description is read off the artwork itself
    and cached, so it costs one call per character rather than one per book.
    """
    if character.visual_profile:
        return character

    cursor = await db.execute(
        "SELECT reference_image_url FROM character_profiles WHERE user_id = ?",
        (user_id,),
    )
    row = await cursor.fetchone()
    reference_url = (row["reference_image_url"] or "") if row else ""
    preset_id = Path(reference_url).stem if reference_url.startswith(PRESET_URL_PREFIX) else ""
    fallback_profile = _PRESET_VISUAL_PROFILES.get(preset_id, "")

    # Curated preset masters have deterministic features. Prefer their audited
    # lock over asking a vision model to reinterpret the same bundled artwork.
    if fallback_profile:
        await db.execute(
            "UPDATE character_profiles SET visual_profile = ? WHERE user_id = ?",
            (fallback_profile, user_id),
        )
        await db.commit()
        return replace(character, visual_profile=fallback_profile)

    from agents.story_agent import GenerationServiceError, describe_character

    try:
        described = await describe_character(character.content, character.mime_type)
    except GenerationServiceError:
        # A missing profile is a quality loss, never a hard failure: the
        # reference image still pins the identity on the image side.
        return character
    if not described:
        return character

    await db.execute(
        "UPDATE character_profiles SET visual_profile = ? WHERE user_id = ?",
        (described, user_id),
    )
    await db.commit()
    return replace(character, visual_profile=described)
