from fastapi import APIRouter
from database import get_db

router = APIRouter()


@router.get("")
async def list_users():
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT id, nickname, avatar_url, signature, created_at FROM profile ORDER BY id"
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()
