import aiosqlite
import os
from models import init_db  # re-export for main.py

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "zhiji.db")


async def get_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    return db


__all__ = ["get_db", "init_db"]
