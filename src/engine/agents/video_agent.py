"""First/last-frame video generation for a finished picturebook.

The provider takes two anchor images plus a text prompt and renders the motion
between them. Anchoring **both** ends is what makes a multi-segment film hold
together: a chain that only pins the first frame drifts by the third segment
(the protagonist's face and the palette wander), while every segment here is
boxed in by two pages that already exist, so error cannot accumulate across
cuts and all segments can be submitted in parallel.

Note the provider treats first/last-frame, single-first-frame and multimodal
reference generation as mutually exclusive modes: no reference video or
reference audio may be attached here, which is why the soundtrack is left to
post-production instead of being generated per segment.
"""

from __future__ import annotations

import asyncio
import base64
import random
from dataclasses import dataclass
from typing import Any, Optional

import httpx

from config import (
    VIDEO_API_BASE_URL,
    VIDEO_API_KEY,
    VIDEO_FRAME_JPEG_QUALITY,
    VIDEO_FRAME_MAX_EDGE,
    VIDEO_GENERATE_AUDIO,
    VIDEO_MODEL,
    VIDEO_RATIO,
    VIDEO_RESOLUTION,
    VIDEO_SEED,
    VIDEO_WATERMARK,
)
from services.generation_errors import (
    GenerationConfigurationError,
    GenerationResponseError,
    GenerationServiceError,
    GenerationUpstreamError,
)

VideoServiceError = GenerationServiceError
VideoConfigurationError = GenerationConfigurationError
VideoUpstreamError = GenerationUpstreamError
VideoResponseError = GenerationResponseError

SUBMIT_ATTEMPTS = 5
_RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}

TERMINAL_SUCCESS = "succeeded"
TERMINAL_FAILURES = {"failed", "cancelled", "canceled", "expired"}

# 每段共用的画面锁。跨段跳变的第一来源是风格描述不一致，比seed 影响大得多，
# 所以这段文字对所有段逐字相同。
SEGMENT_STYLE_LOCK = """这是一本已经画好的绘本中相邻两页之间的运动补间。图 1 是本段的首帧，图 2 是本段的尾帧，两张都已经定稿。

严格要求：
- 完整保留两张图既有的画风、笔触、纸张质感、色调与光线，不要重新上色、不要改变画风、不要写实化。
- 严格保持主角的发型、五官、体型、服装与配色不变，画面里只有这一个主角，不要新增人物。
- 从首帧自然、匀速地过渡到尾帧，动作与镜头连续平滑，不闪切、不跳帧、不忽快忽慢、不在结尾突然加速去对齐。
- 不要出现任何文字、字幕、水印、logo、边框。
- 不要添加绘本里没有的道具或事件。"""


@dataclass(frozen=True)
class VideoFrame:
    """One anchor image, already read from disk."""

    content: bytes
    mime_type: str


@dataclass(frozen=True)
class VideoTaskState:
    status: str
    video_url: Optional[str] = None
    duration_seconds: Optional[float] = None
    error: Optional[str] = None

    @property
    def is_success(self) -> bool:
        return self.status == TERMINAL_SUCCESS

    @property
    def is_failure(self) -> bool:
        return self.status in TERMINAL_FAILURES

    @property
    def is_terminal(self) -> bool:
        return self.is_success or self.is_failure


def video_generation_configured() -> bool:
    """运行时读环境,避免测试 reload config 后仍固化在导入期常量上。"""
    import os

    return all(
        isinstance(value, str) and value.strip()
        for value in (
            os.getenv("VIDEO_API_BASE_URL", VIDEO_API_BASE_URL),
            os.getenv("VIDEO_API_KEY", VIDEO_API_KEY),
            os.getenv("VIDEO_MODEL", VIDEO_MODEL),
        )
    )


def _require_video_configuration() -> None:
    # 遵循 BE-SECRET-001 规范: credentials come only from environment config
    # and are never embedded in source or returned to clients.
    if not video_generation_configured():
        raise VideoConfigurationError("video service is not configured")


def _tasks_url() -> str:
    return f"{VIDEO_API_BASE_URL.rstrip('/')}/contents/generations/tasks"


def prepare_frame(frame: VideoFrame) -> VideoFrame:
    """Shrink an anchor page before it is base64'd into the request body.

    A picturebook page is a ~3MB PNG; two of them base64'd push a single
    request close to 10MB. Re-encoding to JPEG keeps it visually identical at a
    tenth of the size. Pillow is optional, so the original bytes are a valid
    fallback.
    """
    try:
        from io import BytesIO

        from PIL import Image
    except ImportError:
        return frame
    try:
        with Image.open(BytesIO(frame.content)) as image:
            converted = image.convert("RGB")
            if max(converted.size) > VIDEO_FRAME_MAX_EDGE:
                converted.thumbnail(
                    (VIDEO_FRAME_MAX_EDGE, VIDEO_FRAME_MAX_EDGE),
                    Image.LANCZOS,
                )
            buffer = BytesIO()
            converted.save(
                buffer,
                "JPEG",
                quality=VIDEO_FRAME_JPEG_QUALITY,
                optimize=True,
            )
            return VideoFrame(content=buffer.getvalue(), mime_type="image/jpeg")
    except Exception:
        return frame


def _data_url(frame: VideoFrame) -> str:
    encoded = base64.b64encode(frame.content).decode("ascii")
    return f"data:{frame.mime_type};base64,{encoded}"


def build_segment_prompt(
    *,
    from_caption: str,
    to_caption: str,
    style_description: str = "",
    character_profile: str = "",
    segment_index: int = 0,
    total_segments: int = 0,
    story_outline: str = "",
) -> str:
    """Style lock first, then the two page captions that motivate the movement.

    每页的剧情描述就是绘本作者写下的那句话，它决定这一段该演什么；
    整本大纲只用来让模型知道自己处在故事的哪一步，并明确禁止把别页的
    内容画进本段，否则模型会顺手把后面的情节提前演出来。
    """
    blocks = [SEGMENT_STYLE_LOCK]
    if style_description.strip():
        blocks.append(f"画风：{style_description.strip()}")
    if character_profile.strip():
        blocks.append(f"主角设定（不得改动）：\n{character_profile.strip()}")

    start = (from_caption or "").strip()
    end = (to_caption or "").strip()
    position = ""
    if total_segments > 0 and segment_index > 0:
        position = f"（全片共 {total_segments} 段，这是第 {segment_index} 段）"
    blocks.append(
        f"本段要演的内容{position}：\n"
        f"- 首帧这一页的剧情：{start or '沿用图 1 的画面'}\n"
        f"- 尾帧这一页的剧情：{end or '沿用图 2 的画面'}\n"
        "请让画面从首帧那句剧情的状态，自然演变到尾帧那句剧情的状态，"
        "把两句之间的动作补全，只演这两句描述的事。"
    )
    if story_outline.strip():
        blocks.append(
            "整本绘本的剧情脉络（仅用于理解本段处在故事的哪一步，"
            "不要把其它页的情节画进本段）：\n" + story_outline.strip()
        )
    return "\n\n".join(blocks)


def build_segment_payload(
    prompt: str,
    first_frame: VideoFrame,
    last_frame: VideoFrame,
    *,
    duration: int,
    ratio: str = "",
    seed: Optional[int] = None,
) -> dict:
    payload: dict[str, Any] = {
        "model": VIDEO_MODEL,
        "content": [
            {"type": "text", "text": prompt},
            {
                "type": "image_url",
                "image_url": {"url": _data_url(first_frame)},
                "role": "first_frame",
            },
            {
                "type": "image_url",
                "image_url": {"url": _data_url(last_frame)},
                "role": "last_frame",
            },
        ],
        "duration": duration,
        "ratio": (ratio or VIDEO_RATIO),
        "generate_audio": bool(VIDEO_GENERATE_AUDIO),
        "watermark": bool(VIDEO_WATERMARK),
    }
    resolved_seed = VIDEO_SEED if seed is None else seed
    if isinstance(resolved_seed, int) and resolved_seed > 0:
        payload["seed"] = resolved_seed
    if VIDEO_RESOLUTION:
        payload["resolution"] = VIDEO_RESOLUTION
    return payload


async def _post_with_backoff(client: httpx.AsyncClient, payload: dict) -> dict:
    """Submit once, retrying only the failures that are worth retrying.

    Concurrent submissions routinely hit the provider's per-account video quota,
    and a 429 there means "come back later", not "this request is wrong".
    """
    last_error: Exception = VideoUpstreamError(
        "video service is temporarily unavailable"
    )
    for attempt in range(1, SUBMIT_ATTEMPTS + 1):
        try:
            response = await client.post(
                _tasks_url(),
                headers={"Authorization": f"Bearer {VIDEO_API_KEY}"},
                json=payload,
            )
            if response.status_code in _RETRYABLE_STATUS:
                last_error = VideoUpstreamError(
                    "video service is temporarily unavailable"
                )
            else:
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError:
            # 4xx that is not in the retryable set means the request itself is
            # wrong; retrying would just burn quota.
            raise VideoResponseError(
                "video service rejected the generation request"
            ) from None
        except httpx.HTTPError:
            last_error = VideoUpstreamError(
                "video service is temporarily unavailable"
            )
        except (ValueError, TypeError):
            raise VideoResponseError(
                "video service returned an invalid response"
            ) from None
        if attempt < SUBMIT_ATTEMPTS:
            delay = 5 * (2 ** (attempt - 1)) * (0.8 + 0.4 * random.random())
            await asyncio.sleep(min(delay, 60.0))
    raise last_error


async def submit_segment(
    client: httpx.AsyncClient,
    prompt: str,
    first_frame: VideoFrame,
    last_frame: VideoFrame,
    *,
    duration: int,
    ratio: str = "",
    seed: Optional[int] = None,
) -> str:
    """Create one segment task and return its provider task id.

    The frames are used as given: callers run `prepare_frame` once per page and
    reuse the result across the two segments that share that page, so shrinking
    again here would only re-compress an already-compressed JPEG.
    """
    _require_video_configuration()
    if not (prompt or "").strip():
        raise VideoResponseError("segment prompt is empty")
    payload = build_segment_payload(
        prompt,
        first_frame,
        last_frame,
        duration=duration,
        ratio=ratio,
        seed=seed,
    )
    data = await _post_with_backoff(client, payload)
    task_id = data.get("id") if isinstance(data, dict) else None
    if not isinstance(task_id, str) or not task_id.strip():
        raise VideoResponseError("video service returned no task id")
    return task_id.strip()


def _parse_task_state(data: object) -> VideoTaskState:
    if not isinstance(data, dict):
        raise VideoResponseError("video service returned an invalid response")
    status = data.get("status")
    if not isinstance(status, str) or not status:
        raise VideoResponseError("video service returned an invalid response")
    content = data.get("content")
    video_url = None
    if isinstance(content, dict):
        candidate = content.get("video_url")
        if isinstance(candidate, str) and candidate.strip():
            video_url = candidate.strip()
    duration = data.get("duration")
    duration_seconds = float(duration) if isinstance(duration, (int, float)) else None
    state = VideoTaskState(
        status=status,
        video_url=video_url,
        duration_seconds=duration_seconds,
        error=None if status != "failed" else "video generation failed",
    )
    if state.is_success and not state.video_url:
        raise VideoResponseError("video service returned no video URL")
    return state


async def fetch_task(client: httpx.AsyncClient, task_id: str) -> VideoTaskState:
    """Poll one task. Transport hiccups surface as a non-terminal state."""
    _require_video_configuration()
    try:
        response = await client.get(
            f"{_tasks_url()}/{task_id}",
            headers={"Authorization": f"Bearer {VIDEO_API_KEY}"},
        )
        if response.status_code in _RETRYABLE_STATUS:
            return VideoTaskState(status="running")
        response.raise_for_status()
        data = response.json()
    except httpx.HTTPStatusError:
        raise VideoResponseError("video task could not be read") from None
    except httpx.HTTPError:
        return VideoTaskState(status="running")
    except (ValueError, TypeError):
        raise VideoResponseError(
            "video service returned an invalid response"
        ) from None
    return _parse_task_state(data)
