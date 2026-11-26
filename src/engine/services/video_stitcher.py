"""Stitch the rendered segments into one continuous film with ffmpeg.

Two details matter for a first/last-frame chain:

* Segment k's last frame **is** segment k+1's first frame, so a naive concat
  shows every seam as a one-frame freeze. The duplicate opening frame of every
  segment after the first is dropped.
* The provider does not reproduce the anchor page pixel-for-pixel, so a seam can
  flicker slightly. An optional short cross-dissolve hides it.

ffmpeg is located from config, then PATH, then the binary bundled with
imageio-ffmpeg, so no system package manager is required.
"""

from __future__ import annotations

import asyncio
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

from config import FFMPEG_BIN
from services.generation_errors import GenerationServiceError

STITCH_TIMEOUT_SECONDS = 600
DEFAULT_FPS = 24.0


class VideoStitchError(GenerationServiceError):
    pass


@dataclass(frozen=True)
class ClipInfo:
    path: Path
    width: int
    height: int
    fps: float
    duration: float
    has_audio: bool


def resolve_ffmpeg() -> str:
    if FFMPEG_BIN:
        return FFMPEG_BIN
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        raise VideoStitchError("ffmpeg is not available") from None


async def _run(args: Sequence[str], *, expect_success: bool = True) -> tuple[int, str]:
    process = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, stderr = await asyncio.wait_for(
            process.communicate(), timeout=STITCH_TIMEOUT_SECONDS
        )
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
        raise VideoStitchError("video stitching timed out") from None
    message = (stderr or b"").decode("utf-8", errors="replace")
    if expect_success and process.returncode != 0:
        raise VideoStitchError("video stitching failed")
    return process.returncode or 0, message


async def probe_clip(path: Path) -> ClipInfo:
    """Read geometry from `ffmpeg -i`; ffprobe is not always installed."""
    ffmpeg = resolve_ffmpeg()
    # `-i` alone exits non-zero by design ("at least one output file"), so the
    # return code is ignored and only the report is parsed.
    _, report = await _run([ffmpeg, "-hide_banner", "-i", str(path)],
                           expect_success=False)
    video_line = next((line for line in report.splitlines() if "Video:" in line), "")
    if not video_line:
        raise VideoStitchError("segment has no video stream")

    duration = 0.0
    matched = re.search(r"Duration: (\d+):(\d+):([\d.]+)", report)
    if matched:
        duration = (
            int(matched.group(1)) * 3600
            + int(matched.group(2)) * 60
            + float(matched.group(3))
        )
    geometry = re.search(r"(\d{2,5})x(\d{2,5})", video_line)
    fps = re.search(r"([\d.]+) fps", video_line)
    return ClipInfo(
        path=path,
        width=int(geometry.group(1)) if geometry else 0,
        height=int(geometry.group(2)) if geometry else 0,
        fps=round(float(fps.group(1)), 4) if fps else DEFAULT_FPS,
        duration=duration,
        has_audio=any("Audio:" in line for line in report.splitlines()),
    )


def _normalize_chain(index: int, clip: ClipInfo, target: ClipInfo, trim: bool) -> str:
    frame = 1.0 / (target.fps or DEFAULT_FPS)
    prefix = f"trim=start={frame:.6f}," if trim and index > 0 else ""
    return (
        f"[{index}:v]{prefix}fps={target.fps},"
        f"scale={target.width}:{target.height}:force_original_aspect_ratio=decrease,"
        f"pad={target.width}:{target.height}:-1:-1:color=black,setsar=1,"
        f"format=yuv420p,setpts=PTS-STARTPTS[v{index}]"
    )


def _build_concat_filter(clips: Sequence[ClipInfo], trim: bool) -> str:
    target = clips[0]
    chains = [_normalize_chain(i, clip, target, trim) for i, clip in enumerate(clips)]
    labels = "".join(f"[v{i}]" for i in range(len(clips)))
    chains.append(f"{labels}concat=n={len(clips)}:v=1:a=0[vout]")
    return ";".join(chains)


def _build_xfade_filter(clips: Sequence[ClipInfo], trim: bool, xfade: float) -> str:
    target = clips[0]
    frame = 1.0 / (target.fps or DEFAULT_FPS)
    chains = [_normalize_chain(i, clip, target, trim) for i, clip in enumerate(clips)]
    current = "[v0]"
    offset_base = clips[0].duration
    for index in range(1, len(clips)):
        label = f"[vx{index}]"
        chains.append(
            f"{current}[v{index}]xfade=transition=fade:duration={xfade}:"
            f"offset={max(offset_base - xfade, 0.0):.4f}{label}"
        )
        current = label
        segment_duration = clips[index].duration - (frame if trim else 0.0)
        offset_base = offset_base + segment_duration - xfade
    chains.append(f"{current}null[vout]")
    return ";".join(chains)


async def stitch_segments(
    segment_paths: Sequence[Path],
    *,
    trim_duplicate_frame: bool = True,
    xfade_seconds: float = 0.0,
    crf: int = 18,
    preset: str = "medium",
) -> tuple[bytes, float]:
    """Return the finished MP4 bytes and its duration in seconds."""
    paths = [Path(path) for path in segment_paths]
    if not paths:
        raise VideoStitchError("no segments to stitch")
    for path in paths:
        if not path.is_file():
            raise VideoStitchError("a rendered segment is missing")
    if len(paths) == 1:
        clip = await probe_clip(paths[0])
        return paths[0].read_bytes(), clip.duration

    ffmpeg = resolve_ffmpeg()
    clips = [await probe_clip(path) for path in paths]
    if not clips[0].width or not clips[0].height:
        raise VideoStitchError("segment geometry could not be read")

    xfade = max(0.0, float(xfade_seconds or 0.0))
    if xfade > 0 and any(clip.duration <= xfade * 2 for clip in clips):
        xfade = 0.0
    if xfade > 0:
        filter_complex = _build_xfade_filter(clips, trim_duplicate_frame, xfade)
    else:
        filter_complex = _build_concat_filter(clips, trim_duplicate_frame)

    workspace = Path(tempfile.mkdtemp(prefix="pbvideo-"))
    output = workspace / "final.mp4"
    try:
        args: list[str] = [ffmpeg, "-y"]
        for path in paths:
            args += ["-i", str(path)]
        args += [
            "-filter_complex", filter_complex,
            "-map", "[vout]",
            #各段是分别生成的，音轨相位对不上，接缝会爆音；统一去声，
            # 让后期整条配一段音乐。
            "-an",
            "-c:v", "libx264",
            "-crf", str(crf),
            "-preset", preset,
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            str(output),
        ]
        await _run(args)
        if not output.is_file() or output.stat().st_size <= 0:
            raise VideoStitchError("video stitching produced no output")
        content = output.read_bytes()
        final = await probe_clip(output)
        return content, final.duration
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def estimated_duration(segment_count: int, segment_duration: int, fps: float = DEFAULT_FPS,
                       trim_duplicate_frame: bool = True) -> Optional[float]:
    if segment_count <= 0:
        return None
    total = segment_count * segment_duration
    if trim_duplicate_frame and segment_count > 1:
        total -= (segment_count - 1) / (fps or DEFAULT_FPS)
    return round(total, 3)
