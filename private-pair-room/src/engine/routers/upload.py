from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from auth.dependencies import get_current_user_id, require_same_origin
from database import get_db
from services.media_store import (
    MediaStoreError,
    MediaTooLarge,
    UnsupportedMediaType,
    asset_file_path,
    legacy_file_path,
    legacy_url_is_owned,
    store_upload,
)


router = APIRouter()


def _media_http_error(exc: MediaStoreError) -> HTTPException:
    if isinstance(exc, MediaTooLarge):
        return HTTPException(status_code=413, detail=str(exc))
    if isinstance(exc, UnsupportedMediaType):
        return HTTPException(status_code=415, detail=str(exc))
    return HTTPException(status_code=400, detail=str(exc))


@router.post("")
async def upload_photo(
    file: UploadFile = File(...),
    _: None = Depends(require_same_origin),
    user_id: int = Depends(get_current_user_id),
):
    # 遵循 BE-AUTH-003 规范: 写操作同时要求登录态和同源校验。
    db = await get_db()
    try:
        try:
            asset = await store_upload(db, user_id, file)
        except MediaStoreError as exc:
            raise _media_http_error(exc) from exc
    finally:
        await db.close()

    photo_description = None
    try:
        from agents.diary_agent import describe_photo

        content = asset_file_path(asset).read_bytes()
        extension = Path(asset.storage_key).suffix
        photo_description = await describe_photo(content, extension)
    except Exception:
        pass
    return {
        "asset_id": asset.id,
        "url": asset.url,
        "photo_description": photo_description,
    }


@router.get("/{filename}")
async def get_uploaded_file(
    filename: str,
    user_id: int = Depends(get_current_user_id),
):
    url = f"/api/upload/{filename}"
    db = await get_db()
    try:
        try:
            path = legacy_file_path(url)
            owned = await legacy_url_is_owned(db, user_id, url)
        except MediaStoreError:
            owned = False
            path = None
    finally:
        await db.close()
    if not owned or path is None or not path.is_file():
        raise HTTPException(status_code=404, detail="file not found")
    return FileResponse(
        path,
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
