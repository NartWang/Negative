#!/usr/bin/env python3
"""Build web-ready pixel character assets from the Q-pixel character handoff package.

Source assets are 1254x1254 RGB PNGs on a white background (~800KB each). The app
needs small, transparent-background WebP files, so this script:

1. Flood-fills the connected white border region and turns it transparent.
   (Interior white areas such as a white dress are preserved because every sprite
   has a dark outline.)
2. Crops to the sprite bounding box and re-centers it on a square canvas.
3. Emits two sizes: `main/` (512px, used for the hero + preview) and
   `thumb/` (256px, used for grids and action chips).

Usage:
    python3 scripts/build_character_assets.py
    python3 scripts/build_character_assets.py --source /path/to/handoff --force
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw
except ImportError:  # pragma: no cover - tooling guard
    sys.exit("Pillow is required: pip install Pillow")

DEFAULT_SOURCE = Path.home() / "Desktop" / "Q版2D像素角色App_后端交接包"
REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_ROOT = REPO_ROOT / "src" / "app" / "frontend" / "public" / "characters"

MAIN_SIZE = 512
THUMB_SIZE = 256
SENTINEL = (255, 0, 255)
FLOOD_THRESHOLD = 24
PAD_RATIO = 0.04

# Preset id -> source PNG file name (numbers follow the handoff package, gaps kept).
PRESETS: dict[str, str] = {
    "p01": "01_冷感御姐_白衣.png",
    "p02": "02_温柔姐姐.png",
    "p03": "03_活力少女.png",
    "p04": "04_软萌妹妹.png",
    "p05": "05_酷感短发女孩.png",
    "p06": "06_学长型哥哥.png",
    "p07": "07_酷感哥哥.png",
    "p08": "08_活力弟弟.png",
    "p09": "09_电视机头虚拟人.png",
    "p10": "10_显示器头虚拟人.png",
    "p11": "11_橘猫伙伴.png",
    "p12": "12_垂耳小狗伙伴.png",
    "p13": "13_优雅银发奶奶.png",
    "p16": "16_活力银发爷爷.png",
    "p17": "17_好奇小女孩.png",
    "p18": "18_淘气小男孩.png",
    "p19": "19_摩登波波头姐姐.png",
    "p21": "21_产品经理.png",
    "p22": "22_程序员.png",
    "p23": "23_设计师艺术家.png",
    "p24": "24_教师.png",
    "p25": "25_工程师.png",
    "p26": "26_医生.png",
    "p27": "27_律师.png",
    "p28": "28_科研人员.png",
    "p29": "29_创业者.png",
    "p30": "30_月亮兔子.png",
    "p31": "31_圆头机器人.png",
    "p32": "32_云朵精灵.png",
    "p33": "33_星星旅人.png",
    "p34": "34_红发雀斑旅行女孩.png",
    "p35": "35_白发猫耳幻想少年.png",
    "p36": "36_花朵头小精灵.png",
}

# Only p02 (温柔姐姐 / "阿禾") ships a consistency-checked action set in the
# handoff package. Do not borrow another character's actions: the product spec
# requires every action image to be the same character.
ACTION_SETS: dict[str, dict[str, str]] = {
    "p02": {
        "idle": "app/public/actions/ahe/idle.png",
        "think": "app/public/actions/ahe/think.png",
        "happy": "app/public/actions/ahe/happy.png",
        "read": "app/public/actions/ahe/read.png",
    },
}


def cutout(path: Path) -> Image.Image:
    """Return an RGBA image with the white border background removed and cropped."""
    base = Image.open(path).convert("RGB")
    probe = base.copy()
    width, height = probe.size
    for corner in ((0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1)):
        if probe.getpixel(corner) == SENTINEL:
            continue
        ImageDraw.floodfill(probe, corner, SENTINEL, thresh=FLOOD_THRESHOLD)

    rgba = base.convert("RGBA")
    alpha = Image.new("L", probe.size, 255)
    alpha.putdata([0 if px == SENTINEL else 255 for px in probe.getdata()])
    rgba.putalpha(alpha)

    box = rgba.getbbox()
    if box:
        rgba = rgba.crop(box)
    return rgba


def square(image: Image.Image, size: int) -> Image.Image:
    """Fit `image` inside a transparent square canvas of `size`, bottom-aligned."""
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


def emit(image: Image.Image, target: Path, size: int, quality: int) -> int:
    target.parent.mkdir(parents=True, exist_ok=True)
    square(image, size).save(target, "WEBP", quality=quality, method=6)
    return target.stat().st_size


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--out", type=Path, default=OUT_ROOT)
    parser.add_argument("--force", action="store_true", help="rebuild existing files")
    args = parser.parse_args()

    source: Path = args.source
    if not source.is_dir():
        return print(f"source not found: {source}") or 1

    lookup: dict[str, Path] = {}
    for folder in ("07_预设角色/角色成品", "07_预设角色/新增角色成品"):
        directory = source / folder
        if directory.is_dir():
            for png in directory.glob("*.png"):
                lookup[png.name] = png

    out: Path = args.out
    if args.force and out.exists():
        shutil.rmtree(out)

    total = 0
    missing: list[str] = []
    for preset_id, filename in PRESETS.items():
        origin = lookup.get(filename)
        if origin is None:
            missing.append(filename)
            continue
        sprite = cutout(origin)
        total += emit(sprite, out / "main" / f"{preset_id}.webp", MAIN_SIZE, 82)
        total += emit(sprite, out / "thumb" / f"{preset_id}.webp", THUMB_SIZE, 78)
        print(f"  {preset_id}  {filename}")

    for preset_id, actions in ACTION_SETS.items():
        for action, relative in actions.items():
            origin = source / relative
            if not origin.is_file():
                missing.append(relative)
                continue
            sprite = cutout(origin)
            total += emit(
                sprite, out / "actions" / preset_id / f"{action}.webp", THUMB_SIZE, 80
            )
            print(f"  {preset_id}/{action}")

    print(f"\n{len(PRESETS)} presets -> {out}")
    print(f"total {total / 1024 / 1024:.2f} MB")
    if missing:
        print("missing sources:")
        for name in missing:
            print(f"  - {name}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
