"""Give a photo-generated character master the same transparent backdrop as the
bundled presets.

The image service is asked for a character "centered on pure white" (see
`agents/image_agent.CHARACTER_MASTER_PROMPT`), so what comes back is an opaque
square with a flat white plate behind the sprite. Preset characters instead ship
as transparent WebP, which is what lets them stand inside the picture-book scene
backgrounds. Without this step a photo-generated star would show up as a white
card pasted over the scene.

The algorithm is the one already used offline by
`scripts/build_character_assets.py`: flood fill the flat plate inwards from the
four corners, turn the filled region into alpha, crop to the sprite and re-centre
it bottom-aligned on a transparent square canvas.

Pillow is an optional dependency for this backend, and an unexpected picture must
never cost the user their generation, so every failure path returns the original
bytes untouched.
"""

from __future__ import annotations

import io
from typing import Optional

# Magenta is never part of the flat plate, so it is safe as a fill marker.
SENTINEL = (255, 0, 255)
FLOOD_THRESHOLD = 24
CANVAS_SIZE = 512
PAD_RATIO = 0.04
# Below this the artwork is treated as already cut out, so no plate is removed.
ALPHA_CUTOFF = 8


def cut_out_character_backdrop(content: bytes, mime_type: str) -> tuple[bytes, str]:
    """Return transparent PNG bytes for `content`, or the input unchanged."""
    cut = transparent_character_png(content)
    if cut is None:
        return content, mime_type
    return cut, "image/png"


def transparent_character_png(content: bytes) -> Optional[bytes]:
    """Cut the flat backdrop out of a character master.

    Returns `None` when Pillow is unavailable or the picture cannot be handled,
    which callers must read as "keep the original artwork".
    """
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None

    try:
        with Image.open(io.BytesIO(content)) as opened:
            opened.load()
            sprite = _cutout(opened, Image, ImageDraw)
            if sprite is None:
                return None
            canvas = _square(sprite, Image, CANVAS_SIZE)
        buffer = io.BytesIO()
        canvas.save(buffer, "PNG", optimize=True)
        return buffer.getvalue()
    except Exception:
        return None


def _cutout(image, Image, ImageDraw):
    """RGBA sprite cropped to its own bounds, plate replaced by alpha."""
    if _already_transparent(image):
        rgba = image.convert("RGBA")
    else:
        base = image.convert("RGB")
        probe = base.copy()
        width, height = probe.size
        corners = ((0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1))
        for corner in corners:
            if probe.getpixel(corner) == SENTINEL:
                continue
            ImageDraw.floodfill(probe, corner, SENTINEL, thresh=FLOOD_THRESHOLD)
        rgba = base.convert("RGBA")
        alpha = Image.new("L", probe.size, 255)
        alpha.putdata([0 if pixel == SENTINEL else 255 for pixel in probe.getdata()])
        rgba.putalpha(alpha)

    box = rgba.getbbox()
    if not box:
        # The fill swallowed the whole picture: better to keep the original.
        return None
    cropped = rgba.crop(box)
    if cropped.width < 8 or cropped.height < 8:
        return None
    return cropped


def _already_transparent(image) -> bool:
    if image.mode not in ("RGBA", "LA", "PA") and "transparency" not in image.info:
        return False
    alpha = image.convert("RGBA").getchannel("A")
    minimum, _ = alpha.getextrema()
    return minimum <= ALPHA_CUTOFF


def _square(image, Image, size: int):
    """Fit the sprite inside a transparent square canvas, bottom-aligned."""
    pad = max(1, round(size * PAD_RATIO))
    inner = size - pad * 2
    scale = min(inner / image.width, inner / image.height)
    resized = image.resize(
        (max(1, round(image.width * scale)), max(1, round(image.height * scale))),
        Image.LANCZOS,
    )
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.paste(
        resized,
        ((size - resized.width) // 2, size - pad - resized.height),
        resized,
    )
    return canvas
