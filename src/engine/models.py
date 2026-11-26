from migrations import migrate


async def init_db(db):
    await migrate(db)
