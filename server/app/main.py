from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.auth import router as auth_router
from app.canvas_ws import CanvasRooms
from app.canvas_ws import router as canvas_ws_router
from app.canvases import router as canvases_router
from app.db import close_pool, get_pool


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    await get_pool()
    rooms = CanvasRooms()
    app.state.canvas_rooms = rooms
    try:
        yield
    finally:
        await rooms.close()
        await close_pool()


app = FastAPI(lifespan=lifespan)
app.include_router(auth_router)
app.include_router(canvases_router)
app.include_router(canvas_ws_router)


@app.get("/health")
async def health() -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.fetchval("SELECT 1")
    return {"ok": True}
