from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from app.auth import router as auth_router
from app.canvases import router as canvases_router
from app.db import close_pool, get_pool


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    await get_pool()
    yield
    await close_pool()


app = FastAPI(lifespan=lifespan)
app.include_router(auth_router)
app.include_router(canvases_router)


@app.get("/health")
async def health() -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.fetchval("SELECT 1")
    return {"ok": True}


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    try:
        while True:
            await ws.receive_text()
            # Handle incoming messages
    except WebSocketDisconnect:
        pass
