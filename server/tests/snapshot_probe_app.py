import asyncio
from contextlib import asynccontextmanager

import asyncpg
from fastapi import FastAPI

from app.canvas_ws import CanvasRooms
from app.canvas_ws import router as canvas_ws_router
from app.db import DATABASE_URL


class _SnapshotProbeConnection:
    def __init__(self, connection, after_metadata):
        self.connection = connection
        self.after_metadata = after_metadata

    def transaction(self, **options):
        return self.connection.transaction(**options)

    async def fetchval(self, *args):
        return await self.connection.fetchval(*args)

    async def fetchrow(self, query, *args):
        row = await self.connection.fetchrow(query, *args)
        if "FROM canvas WHERE id = $1" in query:
            await self.after_metadata()
        return row

    async def fetch(self, *args):
        return await self.connection.fetch(*args)


class _SnapshotProbeRooms(CanvasRooms):
    def __init__(self, pool, metadata_read, release_snapshot):
        super().__init__(pool=pool)
        self.metadata_read = metadata_read
        self.release_snapshot = release_snapshot

    async def _snapshot(self, conn, canvas_id, identity):
        async def after_metadata():
            self.metadata_read.set()
            await self.release_snapshot.wait()

        return await super()._snapshot(
            _SnapshotProbeConnection(conn, after_metadata), canvas_id, identity
        )


@asynccontextmanager
async def lifespan(app):
    pool = await asyncpg.create_pool(DATABASE_URL)
    metadata_read = asyncio.Event()
    release_snapshot = asyncio.Event()
    app.state.snapshot_metadata_read = metadata_read
    app.state.release_snapshot = release_snapshot
    rooms = _SnapshotProbeRooms(pool, metadata_read, release_snapshot)
    app.state.canvas_rooms = rooms
    try:
        yield
    finally:
        await rooms.close()
        await pool.close()


app = FastAPI(lifespan=lifespan)
app.include_router(canvas_ws_router)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/_test/snapshot-paused")
async def snapshot_paused():
    await asyncio.wait_for(app.state.snapshot_metadata_read.wait(), timeout=15)
    return {"paused": True}


@app.post("/_test/release-snapshot")
async def release_snapshot():
    app.state.release_snapshot.set()
    return {"released": True}
