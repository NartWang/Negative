import os
import uuid
from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import FileResponse
from database import get_db

router = APIRouter()

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

ALLOWED_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MiB cap to bound memory


@router.post("")
async def upload_photo(file: UploadFile = File(...)):
    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="file too large")

    raw_ext = os.path.splitext(file.filename or "")[1].lower()
    ext = raw_ext if raw_ext in ALLOWED_EXTS else ".jpg"
    filename = f"{uuid.uuid4().hex}{ext}"
    filepath = os.path.join(UPLOAD_DIR, filename)

    with open(filepath, "wb") as f:
        f.write(content)

    url = f"/api/upload/{filename}"

    # Best-effort vision description for diary writing context
    photo_description = None
    try:
        from agents.diary_agent import describe_photo
        photo_description = await describe_photo(content, ext)
    except Exception:
        pass

    return {"url": url, "photo_description": photo_description}


@router.get("/{filename}")
async def get_uploaded_file(filename: str):
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=404, detail="file not found")
    filepath = os.path.join(UPLOAD_DIR, filename)
    real = os.path.realpath(filepath)
    if not real.startswith(os.path.realpath(UPLOAD_DIR) + os.sep):
        raise HTTPException(status_code=404, detail="file not found")
    if not os.path.exists(real):
        raise HTTPException(status_code=404, detail="file not found")
    return FileResponse(real)
