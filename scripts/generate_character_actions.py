#!/usr/bin/env python3
"""Generate identity-preserving action sprites for every preset character.

The handoff package only shipped a consistency-checked action set for one
character. This script fills in the rest using the official prompt from
`03_Prompts/04_单动作生成.md`, feeding the character master as Image 1 so the
model can only change pose / gesture / expression.

Pipeline per action:
    master PNG -> images/edits (gpt-image-2) -> raw PNG cache
    -> white-background cutout + square canvas -> public/characters/actions/<id>/<action>.webp

`idle` is not generated: the master artwork *is* the idle pose, so it is only
re-encoded. Raw generations are cached, so re-runs are free and a single action
can be retried without redoing the rest.

Usage:
    export IMAGE_API_KEY=...# required
    python3 scripts/generate_character_actions.py --only p03--dry-run
    python3 scripts/generate_character_actions.py --only p03,p13
    python3 scripts/generate_character_actions.py            # everything missing
    python3 scripts/generate_character_actions.py --force p09/happy
"""

from __future__ import annotations

import argparse
import base64
import concurrent.futures
import io
import os
import sys
import time
from pathlib import Path

try:
    import requests
except ImportError:  # pragma: no cover - tooling guard
    sys.exit("requests is required: pip install requests")

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_character_assets import (  # noqa: E402
    DEFAULT_SOURCE,
    OUT_ROOT,
    PRESETS,
    THUMB_SIZE,
    cutout,
    emit,
)

RAW_CACHE = Path(__file__).resolve().parent / ".cache" / "action_raw"

BASE_URL = os.getenv("IMAGE_API_BASE_URL", "https://api.chatanywhere.tech/v1")
MODEL = os.getenv("IMAGE_ACTION_MODEL", "gpt-image-2")
TIMEOUT = 300

# Action set shown in the UI reference screens (日常 / 思考 / 开心 / 阅读).
# `idle` reuses the master artwork, so only three need generating.
ACTIONS: dict[str, tuple[str, str]] = {
    "think": ("one hand lightly touching the chin, thinking", "a focused, thoughtful expression"),
    "happy": ("both hands loosely clasped in front of the body", "a bright, happy smile"),
    "read": ("holding a small closed-cover book with no text and reading it", "a calm, absorbed expression"),
}

# Official prompt from 03_Prompts/04_单动作生成.md. The identity locks are kept
# verbatim so a generated action can never redesign the character.
PROMPT = """Use case: identity-preserving 2D pixel action asset

Using Image 1 as the canonical and highest-priority reference, draw exactly the same fixed Q-version character performing {action} with {expression}. Change only the pose, hand gesture, action-required minimal prop, and facial expression.

Preserve exactly: the same hairstyle silhouette, hair colors, face shape, eye design and spacing, glasses if present, age presentation, outfit structure and colors, shoes, signature accessory, head-to-body ratio, the same oversized head, dark-brown pixel outline, limited warm palette and flat pixel shading from Image 1.

Show one complete character only, centered on a pure white 1:1 canvas with generous padding. Keep the same apparent scale as Image 1. Use crisp square pixel clusters, no smooth vector edges, no realistic strands, no gradients, and at most one shadow and one highlight tone per material.

No action label, text, frame, complex scene, floor, cast shadow, watermark, logo, extra person, duplicate character, changed outfit, changed hairstyle or cropped limb. Add only the smallest prop strictly required for the action."""


def master_path(source: Path, filename: str) -> Path | None:
    for folder in ("07_预设角色/角色成品", "07_预设角色/新增角色成品"):
        candidate = source / folder / filename
        if candidate.is_file():
            return candidate
    return None


def downscale_for_upload(path: Path, size: int = 768) -> bytes:
    """The masters are 1254px; 768px is plenty of reference and much faster."""
    from PIL import Image

    with Image.open(path) as image:
        image = image.convert("RGB")
        image.thumbnail((size, size), Image.LANCZOS)
        buffer = io.BytesIO()
        image.save(buffer, "PNG")
        return buffer.getvalue()


def generate(api_key: str, master: Path, action: str) -> bytes:
    description, expression = ACTIONS[action]
    response = requests.post(
        f"{BASE_URL}/images/edits",
        headers={"Authorization": f"Bearer {api_key}"},
        files={"image": (f"{master.stem}.png", downscale_for_upload(master), "image/png")},
        data={
            "model": MODEL,
            "prompt": PROMPT.format(action=description, expression=expression),
            "size": "1024x1024",
            "n": "1",
        },
        timeout=TIMEOUT,
    )
    if response.status_code != 200:
        raise RuntimeError(f"HTTP {response.status_code}: {response.text[:300]}")
    payload = response.json()["data"][0]
    if payload.get("b64_json"):
        return base64.b64decode(payload["b64_json"])
    image = requests.get(payload["url"], timeout=TIMEOUT)
    image.raise_for_status()
    return image.content


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--out", type=Path, default=OUT_ROOT)
    parser.add_argument("--only", help="comma separated preset ids, e.g. p03,p13")
    parser.add_argument("--force", help="comma separated <preset>/<action> to regenerate")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    api_key = os.getenv("IMAGE_API_KEY", "").strip()
    if not api_key and not args.dry_run:
        return print("IMAGE_API_KEY is not set") or 1

    wanted = set(args.only.split(",")) if args.only else set(PRESETS)
    forced = set(args.force.split(",")) if args.force else set()

    jobs: list[tuple[str, str, Path]] = []
    skipped_masters: list[str] = []
    for preset_id, filename in PRESETS.items():
        if preset_id not in wanted:
            continue
        master = master_path(args.source, filename)
        if master is None:
            skipped_masters.append(filename)
            continue
        for action in ACTIONS:
            raw = RAW_CACHE / preset_id / f"{action}.png"
            if raw.is_file() and f"{preset_id}/{action}" not in forced:
                continue
            jobs.append((preset_id, action, master))

    print(f"{len(jobs)} generation(s) queued · model={MODEL}")
    if args.dry_run:
        for preset_id, action, _ in jobs:
            print(f"  would generate {preset_id}/{action}")
        return 0

    failures: list[str] = []

    def run(job: tuple[str, str, Path]) -> None:
        preset_id, action, master = job
        target = RAW_CACHE / preset_id / f"{action}.png"
        target.parent.mkdir(parents=True, exist_ok=True)
        for attempt in (1, 2, 3):
            try:
                target.write_bytes(generate(api_key, master, action))
                print(f"  ok{preset_id}/{action}")
                return
            except Exception as error:  # noqa: BLE001 - report and continue
                if attempt == 3:
                    failures.append(f"{preset_id}/{action}: {error}")
                    print(f"  fail {preset_id}/{action} -> {error}")
                else:
                    time.sleep(3 * attempt)

    if jobs:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
            list(pool.map(run, jobs))

    # Re-encode everything that has raw art (plus idle straight from the master).
    print("\nencoding webp assets...")
    encoded = 0
    for preset_id, filename in PRESETS.items():
        if preset_id not in wanted:
            continue
        master = master_path(args.source, filename)
        if master is None:
            continue
        raws = {
            action: RAW_CACHE / preset_id / f"{action}.png"
            for action in ACTIONS
        }
        if not all(path.is_file() for path in raws.values()):
            print(f"  skip {preset_id} (incomplete action set)")
            continue
        out_dir = args.out / "actions" / preset_id
        emit(cutout(master), out_dir / "idle.webp", THUMB_SIZE, 80)
        for action, path in raws.items():
            emit(cutout(path), out_dir / f"{action}.webp", THUMB_SIZE, 80)
        encoded += 1
        print(f"  {preset_id}: idle + {' + '.join(raws)}")

    print(f"\n{encoded} character(s) now have a full action set")
    if skipped_masters:
        print("missing masters:", ", ".join(skipped_masters))
    if failures:
        print("failures:")
        for line in failures:
            print(f"  - {line}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
