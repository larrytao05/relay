import os

import asyncpg

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    os.environ.get(
        "STORAGE_DATABASE_URL",
        "postgres://whiteboard:whiteboard@localhost:5432/whiteboard",
    ),
)


def get_listener_database_url() -> str:
    return (
        os.environ.get("DATABASE_LISTENER_URL")
        or os.environ.get("DATABASE_URL_UNPOOLED")
        or os.environ.get("STORAGE_DATABASE_URL_UNPOOLED")
        or os.environ.get("STORAGE_POSTGRES_URL_NON_POOLING")
        or DATABASE_URL
    )


pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    global pool
    if pool is None:
        pool = await asyncpg.create_pool(DATABASE_URL)
    return pool


async def close_pool() -> None:
    global pool
    if pool is not None:
        await pool.close()
        pool = None
