"""Persist generated MP4 files and hand them back only to their owner.

Videos deliberately do not live in `media_assets`: that store enforces an
image-only MIME whitelist plus an image file-signature check, and its size
budget is sized for images. Reusing it for MP4 would mean loosening both
checks for every image in the product, so videos get their own table, their
own directory and their own signature check.

Remote download reuses the SSRF defence already written for generated images
(DNS/IP screening, no redirects, peer pinning) rather than re-implementing it,
because the provider hands back signed URLs on rotating CDN hostnames that
cannot be allowlisted.
"""

from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import httpx

import config
from services.media_store import (
    InvalidMedia,
    MediaNotFound,
    MediaStoreError,
    MediaTooLarge,
    RemoteMediaBlocked,
    UnsupportedMediaType,
)
from services.media_store import (
    _address_is_allowed,
    _check_response_peer,
    _pinned_url,
    _resolve_host,
)

VIDEO_MIME_TYPE = "video/mp4"
# 上游签名 URL 常把 MP4 标成流式二进制，两种都接受，最终仍按文件签名复核。
_ACCEPTED_DOWNLOAD_MIMES = {
    "video/mp4",
    "video/quicktime",
    "application/octet-stream",
    "binary/octet-stream",
}
_STORAGE_KEY_RE = re.compile(r"^[0-9a-f]{32}\.mp4$")
_TRUSTED_VIDEO_HOST_SUFFIXES = (".tos-cn-beijing.volces.com",)


class VideoStoreError(MediaStoreError):
    pass


@dataclass(frozen=True)
class VideoAsset:
    id: str
    owner_user_id: int
    storage_key: str
    mime_type: str
    size_bytes: int
    duration_seconds: Optional[float] = None


def _is_mp4(content: bytes) -> bool:
    # 遵循 BE-FILE-001 规范: 按文件签名复核类型，不信任声明的 Content-Type。
    # MP4 的第一个 box 是ftyp，box 大小占前 4 字节。
    return len(content) >= 12 and content[4:8] == b"ftyp"


def safe_video_path(storage_key: str) -> Path:
    # 遵循 BE-FILE-002 规范: 规范化后仍须限定在视频目录的直接子级。
    if not _STORAGE_KEY_RE.fullmatch(storage_key):
        raise InvalidMedia("invalid video storage key")
    video_dir = Path(config.get_video_dir()).resolve()
    candidate = (video_dir / storage_key).resolve()
    if candidate.parent != video_dir:
        raise InvalidMedia("invalid video storage key")
    return candidate


def video_file_path(asset: VideoAsset) -> Path:
    return safe_video_path(asset.storage_key)


async def store_video_bytes(
    db: Any,
    owner_user_id: int,
    content: bytes,
    *,
    duration_seconds: Optional[float] = None,
    commit: bool = True,
) -> VideoAsset:
    """Write the file first, then register the row; clean up on any failure."""
    if not content:
        raise InvalidMedia("empty video")
    if len(content) > config.get_video_max_bytes():
        raise MediaTooLarge("video is too large")
    if not _is_mp4(content):
        raise UnsupportedMediaType("video content is not an MP4 stream")

    video_dir = Path(config.get_video_dir()).resolve()
    video_dir.mkdir(parents=True, exist_ok=True)
    asset_id = str(uuid4())
    storage_key = f"{uuid4().hex}.mp4"
    final_path = safe_video_path(storage_key)
    temp_path: Optional[Path] = None
    final_created = False
    try:
        fd, raw_temp_path = tempfile.mkstemp(prefix=".video-", dir=str(video_dir))
        temp_path = Path(raw_temp_path)
        with os.fdopen(fd, "wb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temp_path, final_path)
        temp_path = None
        final_created = True

        await db.execute(
            "INSERT INTO video_assets "
            "(id, owner_user_id, storage_key, mime_type, size_bytes, duration_seconds) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                asset_id,
                owner_user_id,
                storage_key,
                VIDEO_MIME_TYPE,
                len(content),
                duration_seconds,
            ),
        )
        if commit:
            await db.commit()
        return VideoAsset(
            id=asset_id,
            owner_user_id=owner_user_id,
            storage_key=storage_key,
            mime_type=VIDEO_MIME_TYPE,
            size_bytes=len(content),
            duration_seconds=duration_seconds,
        )
    except Exception:
        if commit:
            await db.rollback()
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        if final_created:
            final_path.unlink(missing_ok=True)
        raise


async def require_owned_video(db: Any, user_id: int, asset_id: str) -> VideoAsset:
    # 遵循 SEC-AUTH-002 规范: 只返回当前会话用户拥有的视频资产。
    try:
        normalized = str(UUID(asset_id))
    except (TypeError, ValueError):
        raise MediaNotFound("video not found") from None
    cursor = await db.execute(
        "SELECT id, owner_user_id, storage_key, mime_type, size_bytes, "
        "duration_seconds FROM video_assets WHERE id = ? AND owner_user_id = ?",
        (normalized, user_id),
    )
    row = await cursor.fetchone()
    if not row:
        raise MediaNotFound("video not found")
    return VideoAsset(**dict(row))


async def delete_video_asset(db: Any, asset_id: Optional[str]) -> None:
    """Drop a superseded file so retries do not leak the old renders."""
    if not asset_id:
        return
    cursor = await db.execute(
        "SELECT storage_key FROM video_assets WHERE id = ?", (asset_id,)
    )
    row = await cursor.fetchone()
    await db.execute("DELETE FROM video_assets WHERE id = ?", (asset_id,))
    if not row:
        return
    try:
        safe_video_path(row["storage_key"]).unlink(missing_ok=True)
    except (InvalidMedia, OSError):
        return


async def download_remote_video(
    url: str,
    *,
    transport: Optional[httpx.AsyncBaseTransport] = None,
) -> bytes:
    # 遵循 BE-SSRF-001 规范: 禁止跳转和非公网地址，并在响应连接上复核 peer。
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise InvalidMedia("generated video URL must use http or https")
    if parsed.username is not None or parsed.password is not None:
        raise InvalidMedia("generated video URL must not contain credentials")
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError:
        raise InvalidMedia("generated video URL has an invalid port") from None

    try:
        import ipaddress

        literal = ipaddress.ip_address(parsed.hostname.split("%", 1)[0])
        addresses = [literal]
    except ValueError:
        addresses = await _resolve_host(parsed.hostname, port)
    # macOS 上的本地网络代理会把官方火山引擎 TOS 域名映射到
    # 198.18.0.0/15 的保留代理地址。仅对供应商官方后缀接受这种映射，
    # 其它私网/保留地址仍按 SSRF 规则阻断。
    trusted_provider_host = any(
        parsed.hostname.endswith(suffix) for suffix in _TRUSTED_VIDEO_HOST_SUFFIXES
    )
    if any(not _address_is_allowed(address) for address in addresses) and not trusted_provider_host:
        raise RemoteMediaBlocked("remote video host is not public")
    pinned_address = addresses[0]
    pinned = _pinned_url(parsed, pinned_address, port)
    request_extensions = (
        {"sni_hostname": parsed.hostname} if parsed.scheme == "https" else None
    )

    maximum = config.get_video_max_bytes()
    client = httpx.AsyncClient(
        timeout=httpx.Timeout(120.0),
        follow_redirects=False,
        trust_env=False,
        transport=transport,
    )
    try:
        async with client.stream(
            "GET",
            pinned,
            headers={"Host": parsed.netloc},
            extensions=request_extensions,
            follow_redirects=False,
        ) as response:
            if 300 <= response.status_code < 400:
                raise InvalidMedia("remote video redirects are not allowed")
            response.raise_for_status()
            _check_response_peer(response, pinned_address)
            declared = (response.headers.get("content-type") or "").split(";", 1)[0]
            if declared.strip().lower() not in _ACCEPTED_DOWNLOAD_MIMES:
                raise UnsupportedMediaType("unsupported generated video MIME type")
            content_length = response.headers.get("content-length")
            if content_length is not None:
                try:
                    parsed_length = int(content_length)
                except ValueError:
                    raise InvalidMedia("invalid remote content length") from None
                if parsed_length < 0:
                    raise InvalidMedia("invalid remote content length")
                if parsed_length > maximum:
                    raise MediaTooLarge("video is too large")
            chunks: list[bytes] = []
            total = 0
            async for chunk in response.aiter_bytes():
                total += len(chunk)
                if total > maximum:
                    raise MediaTooLarge("video is too large")
                chunks.append(chunk)
            content = b"".join(chunks)
            if not content:
                raise InvalidMedia("empty video")
            if not _is_mp4(content):
                raise UnsupportedMediaType("generated video is not an MP4 stream")
            return content
    except httpx.HTTPError:
        raise RemoteMediaBlocked("generated video could not be downloaded") from None
    finally:
        await client.aclose()
