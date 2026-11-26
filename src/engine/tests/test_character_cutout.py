"""The photo route must produce a transparent sprite, like the presets."""

import io

import pytest

from services.character_cutout import (
    cut_out_character_backdrop,
    transparent_character_png,
)

Image = pytest.importorskip("PIL.Image", reason="Pillow is optional for this backend")


def _white_plate_master(size: int = 256) -> bytes:
    """A dark blob centred on the pure white plate the prompt asks for."""
    image = Image.new("RGB", (size, size), (255, 255, 255))
    body = Image.new("RGB", (size // 3, size // 2), (40, 60, 90))
    image.paste(body, (size // 3, size // 3))
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


def _opened(content: bytes):
    return Image.open(io.BytesIO(content)).convert("RGBA")


def test_white_plate_becomes_transparent_padding():
    cut = transparent_character_png(_white_plate_master())

    assert cut is not None
    image = _opened(cut)
    assert image.size == (512, 512)
    # Corners are plate, so they must be fully transparent now.
    for corner in ((0, 0), (511, 0), (0, 511), (511, 511)):
        assert image.getpixel(corner)[3] == 0
    # The character itself stays opaque and keeps its colour.
    centre = image.getpixel((256, 300))
    assert centre[3] == 255
    assert centre[:3] != (255, 255, 255)


def test_sprite_is_bottom_aligned_inside_the_canvas():
    image = _opened(transparent_character_png(_white_plate_master()))
    rows = [
        y
        for y in range(image.height)
        if any(image.getpixel((x, y))[3] > 0 for x in range(0, image.width, 4))
    ]

    assert rows, "the sprite disappeared"
    # Bottom padding is the 4% margin, never a large empty band.
    assert image.height - 1 - rows[-1] <= round(image.height * 0.04) + 1


def test_transform_reports_png_and_keeps_bytes_when_undecodable():
    content, mime = cut_out_character_backdrop(_white_plate_master(), "image/png")
    assert mime == "image/png"
    assert content.startswith(b"\x89PNG")

    junk = b"not-an-image"
    assert cut_out_character_backdrop(junk, "image/webp") == (junk, "image/webp")


def test_already_transparent_artwork_is_not_flood_filled():
    sprite = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
    sprite.paste(Image.new("RGBA", (80, 120), (200, 90, 60, 255)), (60, 40))
    buffer = io.BytesIO()
    sprite.save(buffer, "PNG")

    image = _opened(transparent_character_png(buffer.getvalue()))

    assert image.getpixel((0, 0))[3] == 0
    assert image.getpixel((256, 300))[3] == 255
