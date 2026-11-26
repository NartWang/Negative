from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

_PRE_DOTENV_ENV = set(os.environ)
load_dotenv()

ENGINE_DIR = Path(__file__).resolve().parent


def _get_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean value")


def _get_positive_int(name: str, default: int) -> int:
    value = int(os.getenv(name, str(default)))
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return value


def parse_image_api_keys(
    raw_keys: str | None,
    legacy_key: str | None = None,
) -> tuple[str, ...]:
    """Parse a comma-separated key pool without exposing or reordering values."""
    parsed: list[str] = []
    seen: set[str] = set()
    if isinstance(raw_keys, str):
        for item in raw_keys.split(","):
            key = item.strip()
            if key and key not in seen:
                parsed.append(key)
                seen.add(key)
    if not parsed and isinstance(legacy_key, str) and legacy_key.strip():
        parsed.append(legacy_key.strip())
    return tuple(parsed)


def get_frontend_origins() -> list[str]:
    raw_origins = os.getenv(
        "FRONTEND_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000",
    )
    origins = list(
        dict.fromkeys(
            origin.strip().rstrip("/")
            for origin in raw_origins.split(",")
            if origin.strip()
        )
    )
    if "*" in origins:
        raise ValueError("FRONTEND_ORIGINS must contain explicit origins")
    return origins


def get_db_path() -> str:
    return os.getenv("ZHIJI_DB_PATH", str(ENGINE_DIR / "data" / "zhiji.db"))


def get_upload_dir() -> str:
    return os.getenv("ZHIJI_UPLOAD_DIR", str(ENGINE_DIR / "data" / "uploads"))


def get_character_asset_dir() -> str:
    """Where the bundled preset character sprites live.

    Preset characters are static frontend assets (`/characters/main/pNN.webp`),
    so the picturebook generator needs a filesystem root to read them from.
    """
    return os.getenv(
        "ZHIJI_CHARACTER_ASSET_DIR",
        str(ENGINE_DIR.parent / "app" / "frontend" / "public" / "characters"),
    )


def get_media_max_bytes() -> int:
    return _get_positive_int("MEDIA_MAX_BYTES", 10 * 1024 * 1024)


def get_media_allow_private_hosts() -> bool:
    return _get_bool("MEDIA_ALLOW_PRIVATE_HOSTS", False)


def get_video_dir() -> str:
    """Generated MP4 files live apart from images: different size class, and the
    image store enforces an image-only MIME whitelist."""
    return os.getenv("ZHIJI_VIDEO_DIR", str(ENGINE_DIR / "data" / "videos"))


def get_video_max_bytes() -> int:
    # 一段 5s / 720p 约 7~9MB，9 页的成片约 20MB，留足余量。
    return _get_positive_int("VIDEO_MAX_BYTES", 96 * 1024 * 1024)


FRONTEND_ORIGINS = get_frontend_origins()
SESSION_COOKIE_NAME = "zhiji_session"
SESSION_COOKIE_SECURE = _get_bool("SESSION_COOKIE_SECURE", True)
SESSION_TTL_SECONDS = _get_positive_int("SESSION_TTL_SECONDS", 30 * 24 * 60 * 60)

# 公开注册开关。本地开发/测试默认开启;对外 Demo 部署时在 .env 里设
# REGISTRATION_OPEN=false,只放行你预建的体验账号登录,防止陌生人注册占用资源。
REGISTRATION_OPEN = _get_bool("REGISTRATION_OPEN", True)

# 示例发布者:新账号注册后自动订阅此账号,并在底片夹里置顶其作品作为只读示例。
# 设置为此账号的 user_id;设为 0 则关闭自动示例注入。
DEMO_PUBLISHER_USER_ID = int(os.getenv("DEMO_PUBLISHER_USER_ID", "9"))
# 要作为示例的绘本 work_ids(底片夹置顶)
DEMO_PICTUREBOOK_WORK_IDS = [11, 12, 13, 14]
# 要作为示例的漫剧 video_job_id
DEMO_MOTION_COMIC_VIDEO_JOB_ID = 1

# 日记 Agent
DIARY_API_BASE_URL = os.getenv("DIARY_API_BASE_URL", "")
DIARY_API_KEY = os.getenv("DIARY_API_KEY", "")
DIARY_MODEL = os.getenv("DIARY_MODEL", "claude-opus-4-6")
# 仅用于给上传的照片自动生成一句描述；默认复用日记模型。
VISION_MODEL = os.getenv("VISION_MODEL", "").strip() or DIARY_MODEL

# 绘本流水线（日记 → 故事 JSON → 9 条生图 prompt）与角色视觉档使用的模型。
# 需要长结构化输出 + 看图能力；推理型模型（如 deepseek-v4-flash）会把 token
# 全部消耗在 reasoning 上并返回空正文，不可用。
STORY_MODEL = os.getenv("STORY_MODEL", "gpt-5-mini")
# 绘本页面尺寸。提示词要求 2:1，但 gpt-image-1 只支持 1024x1024 /
# 1536x1024 / 1024x1536，1536x1024 是最接近的横幅。
PICTUREBOOK_IMAGE_SIZE = os.getenv("PICTUREBOOK_IMAGE_SIZE", "1536x1024")

# 绘图 Agent
IMAGE_API_BASE_URL = os.getenv("IMAGE_API_BASE_URL", "")
_IMAGE_API_KEYS_RAW = os.getenv("IMAGE_API_KEYS")
if (
    _IMAGE_API_KEYS_RAW
    and "IMAGE_API_KEYS" in _PRE_DOTENV_ENV
    and "IMAGE_API_KEY" not in _PRE_DOTENV_ENV
):
    IMAGE_API_KEY = ""
else:
    IMAGE_API_KEY = os.getenv("IMAGE_API_KEY", "")
# 遵循 BE-SECRET-001 规范: credentials are loaded only from environment.
IMAGE_API_KEYS = parse_image_api_keys(_IMAGE_API_KEYS_RAW, IMAGE_API_KEY)
IMAGE_MODEL = os.getenv("IMAGE_MODEL", "qwen-image-2512-lightning")

# 角色母版生成使用的模型（需支持 /images/edits），未配置时回退到 IMAGE_MODEL。
CHARACTER_IMAGE_MODEL = os.getenv("CHARACTER_IMAGE_MODEL", "").strip() or IMAGE_MODEL
# 画质档位。部分代理有 60s 网关超时，high 档常常超时，默认用 medium。
CHARACTER_IMAGE_QUALITY = os.getenv("CHARACTER_IMAGE_QUALITY", "medium").strip()

# 绘本视频（首尾帧接力）
# 绘本的 N 页两两相邻配对：第 k 段以第 k 页为首帧、第 k+1 页为尾帧，
# 于是 N 页得到 N-1 段；每段两端都被已生成的页面图锚定，误差不会跨段累积，
# 各段之间也没有数据依赖，可以全部并行提交。
# 遵循 BE-SECRET-001 规范: credentials are loaded only from environment.
VIDEO_API_BASE_URL = os.getenv(
    "VIDEO_API_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3"
)
VIDEO_API_KEY = os.getenv("VIDEO_API_KEY", "")
VIDEO_MODEL = os.getenv("VIDEO_MODEL", "doubao-seedance-2-5-260628")
# 每段时长（秒）。各段必须一致，否则成片节奏会一顿一顿。
VIDEO_SEGMENT_DURATION = _get_positive_int("VIDEO_SEGMENT_DURATION", 5)
# adaptive 让模型沿用首帧比例，绘本页是 1536x1024，不会被裁掉两边。
VIDEO_RATIO = os.getenv("VIDEO_RATIO", "adaptive")
VIDEO_RESOLUTION = os.getenv("VIDEO_RESOLUTION", "").strip()
# 所有段共用同一seed，可以压住跨段的画风漂移；<= 0 表示交给模型随机。
VIDEO_SEED = int(os.getenv("VIDEO_SEED", "0"))
# 首尾帧场景与「多模态参考」互斥，无法传参考音频统一 BGM，
# 各段自带音频拼起来会在每个接缝爆音，因此默认不出声，交给后期配乐。
VIDEO_GENERATE_AUDIO = _get_bool("VIDEO_GENERATE_AUDIO", False)
VIDEO_WATERMARK = _get_bool("VIDEO_WATERMARK", False)
# 并发提交度。上游对视频任务有并发配额，触发限流就调小。
VIDEO_MAX_CONCURRENCY = _get_positive_int("VIDEO_MAX_CONCURRENCY", 3)
VIDEO_POLL_INTERVAL_SECONDS = _get_positive_int("VIDEO_POLL_INTERVAL_SECONDS", 10)
VIDEO_POLL_TIMEOUT_SECONDS = _get_positive_int("VIDEO_POLL_TIMEOUT_SECONDS", 1800)
# 绘本页是 3MB 级PNG，两张直接 base64 会让单个请求体接近 10MB；
# 上传前压成 JPEG，视觉无损但体积降到十分之一。需要 Pillow，缺失时原样发送。
VIDEO_FRAME_MAX_EDGE = _get_positive_int("VIDEO_FRAME_MAX_EDGE", 1536)
VIDEO_FRAME_JPEG_QUALITY = _get_positive_int("VIDEO_FRAME_JPEG_QUALITY", 90)
# 封面通常是海报式构图，和第 1 页跨度过大，接进来会出现强行变形的转场。
VIDEO_INCLUDE_COVER = _get_bool("VIDEO_INCLUDE_COVER", False)
# 第 k 段的尾帧和第 k+1 段的首帧是同一页，拼接时掐掉后一段的开头 1 帧，
# 否则每个接缝都会卡出一帧定格感。
VIDEO_TRIM_DUPLICATE_FRAME = _get_bool("VIDEO_TRIM_DUPLICATE_FRAME", True)
# 接缝交叉溶解秒数，0 表示硬接。模型还原尾帧不是像素级一致时可调到 0.15。
VIDEO_XFADE_SECONDS = float(os.getenv("VIDEO_XFADE_SECONDS", "0"))
# 留空则在 PATH 与 imageio-ffmpeg 自带的二进制里自动查找。
FFMPEG_BIN = os.getenv("FFMPEG_BIN", "").strip()

# 服务配置
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))
