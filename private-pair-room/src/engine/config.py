import os
from pathlib import Path

from dotenv import load_dotenv

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


def get_media_max_bytes() -> int:
    return _get_positive_int("MEDIA_MAX_BYTES", 10 * 1024 * 1024)


def get_media_allow_private_hosts() -> bool:
    return _get_bool("MEDIA_ALLOW_PRIVATE_HOSTS", False)


FRONTEND_ORIGINS = get_frontend_origins()
SESSION_COOKIE_NAME = "zhiji_session"
SESSION_COOKIE_SECURE = _get_bool("SESSION_COOKIE_SECURE", True)
SESSION_TTL_SECONDS = _get_positive_int("SESSION_TTL_SECONDS", 30 * 24 * 60 * 60)

# 日记 Agent
DIARY_API_BASE_URL = os.getenv("DIARY_API_BASE_URL", "")
DIARY_API_KEY = os.getenv("DIARY_API_KEY", "")
DIARY_MODEL = os.getenv("DIARY_MODEL", "glm-5.1")

# 绘图 Agent
IMAGE_API_BASE_URL = os.getenv("IMAGE_API_BASE_URL", "")
IMAGE_API_KEY = os.getenv("IMAGE_API_KEY", "")
IMAGE_MODEL = os.getenv("IMAGE_MODEL", "qwen-image-2512-lightning")

# 服务配置
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))
