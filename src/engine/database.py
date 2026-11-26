import aiosqlite
from config import get_db_path
from models import init_db  # re-export for main.py

BUSY_TIMEOUT_MS = 5_000


async def get_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(get_db_path())
    try:
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
        return db
    except Exception:
        await db.close()
        raise


__all__ = ["get_db", "init_db"]
