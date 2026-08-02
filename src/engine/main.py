from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from database import get_db, init_db
from routers import (
    schedules, fragments, streaks, diary, image, upload,
    profile, stats, export, users,
    thermometer, weekly_comic, dual_timeline,
    letter, transform, share, email_send,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db = await get_db()
    await init_db(db)
    await db.close()
    yield


app = FastAPI(title="知己 Engine", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

import os

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "data", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

app.include_router(schedules.router, prefix="/api/schedules", tags=["schedules"])
app.include_router(fragments.router, prefix="/api/fragments", tags=["fragments"])
app.include_router(streaks.router, prefix="/api/streaks", tags=["streaks"])
app.include_router(diary.router, prefix="/api/diary", tags=["diary"])
app.include_router(image.router, prefix="/api/image", tags=["image"])
app.include_router(upload.router, prefix="/api/upload", tags=["upload"])
app.include_router(profile.router, prefix="/api/profile", tags=["profile"])
app.include_router(stats.router, prefix="/api/stats", tags=["stats"])
app.include_router(export.router, prefix="/api/export", tags=["export"])
app.include_router(users.router, prefix="/api/users", tags=["users"])
app.include_router(thermometer.router, prefix="/api/thermometer", tags=["thermometer"])
app.include_router(weekly_comic.router, prefix="/api/weekly-comic", tags=["weekly-comic"])
app.include_router(dual_timeline.router, prefix="/api/dual-timeline", tags=["dual-timeline"])
app.include_router(letter.router, prefix="/api/letter", tags=["letter"])
app.include_router(transform.router, prefix="/api/transform", tags=["transform"])
app.include_router(share.router, prefix="/api/share", tags=["share"])
app.include_router(share.router, prefix="/api", tags=["share-public"])
app.include_router(email_send.router, prefix="/api/email", tags=["email"])


@app.get("/api/health")
async def health():
    return {"status": "ok"}
