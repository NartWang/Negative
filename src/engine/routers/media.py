from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from auth.dependencies import get_current_user_id
from database import get_db
from services.media_store import asset_file_path, get_authorized_asset


router = APIRouter()


@router.get("/{asset_id}")
async def get_media(
    asset_id: str,
    user_id: int = Depends(get_current_user_id),
):
    # 遵循 SEC-AUTH-002 规范: 未授权与不存在统一返回 404，避免枚举资产。
    db = await get_db()
    try:
        asset = await get_authorized_asset(db, asset_id, user_id)
    finally:
        await db.close()
    if asset is None:
        raise HTTPException(status_code=404, detail="media not found")
    try:
        path = asset_file_path(asset)
    except ValueError:
        raise HTTPException(status_code=404, detail="media not found") from None
    if not path.is_file():
        raise HTTPException(status_code=404, detail="media not found")
    return FileResponse(
        path,
        media_type=asset.mime_type,
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
