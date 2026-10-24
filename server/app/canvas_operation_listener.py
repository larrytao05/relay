import asyncio
import json
import logging
from collections.abc import Awaitable, Callable

import asyncpg

from app.db import get_listener_database_url

logger = logging.getLogger(__name__)
_CHANNEL = "canvas_operations"
_TRANSIENT_CHANNEL = "canvas_transient"
_MAX_NOTIFY_BYTES = 7900


async def publish_canvas_operation(
    conn: asyncpg.Connection, canvas_id, revision: int
) -> None:
    payload = json.dumps(
        {"canvas_id": str(canvas_id), "revision": revision}, separators=(",", ":")
    )
    await conn.execute("SELECT pg_notify($1, $2)", _CHANNEL, payload)


async def publish_transient_event(
    conn: asyncpg.Connection, event: dict[str, object]
) -> None:
    payload = json.dumps(event, separators=(",", ":"))
    if len(payload.encode("utf-8")) > _MAX_NOTIFY_BYTES:
        raise ValueError("Transient notification exceeds the PostgreSQL payload limit")
    await conn.execute(
        "SELECT pg_notify($1, $2)",
        _TRANSIENT_CHANNEL,
        payload,
    )


class CanvasOperationListener:
    def __init__(
        self,
        on_notification: Callable[[str], Awaitable[None]],
        on_reconnect: Callable[[], Awaitable[None]],
        idle_grace: float = 5.0,
        on_transient: Callable[[str], Awaitable[None]] | None = None,
        on_periodic: Callable[[], Awaitable[None]] | None = None,
        sync_interval: float = 5.0,
    ) -> None:
        self._on_notification = on_notification
        self._on_reconnect = on_reconnect
        self._on_transient = on_transient
        self._on_periodic = on_periodic
        self._sync_interval = sync_interval
        self._idle_grace = idle_grace
        self._lock = asyncio.Lock()
        self._users = 0
        self._closed = False
        self._connected = asyncio.Event()
        self._runner: asyncio.Task[None] | None = None
        self._idle_task: asyncio.Task[None] | None = None
        self._callback_tasks: set[asyncio.Task[None]] = set()

    @property
    def active(self) -> bool:
        return self._users > 0

    async def acquire(self) -> None:
        async with self._lock:
            if self._closed:
                raise RuntimeError("Canvas operation listener is closed")
            self._users += 1
            if self._idle_task is not None:
                self._idle_task.cancel()
                self._idle_task = None
            if self._runner is None or self._runner.done():
                self._runner = asyncio.create_task(self._run())
        try:
            await self._connected.wait()
        except BaseException:
            await self.release()
            raise

    async def release(self) -> None:
        async with self._lock:
            self._users = max(0, self._users - 1)
            if self._users == 0 and self._idle_task is None and not self._closed:
                self._idle_task = asyncio.create_task(self._close_when_idle())

    async def _close_when_idle(self) -> None:
        await asyncio.sleep(self._idle_grace)
        async with self._lock:
            if self._users or self._closed:
                return
            runner = self._runner
            self._runner = None
            self._connected.clear()
            self._idle_task = None
            if runner is not None:
                runner.cancel()
                await asyncio.gather(runner, return_exceptions=True)

    async def _run(self) -> None:
        delay = 0.1
        while not self._closed and self._users:
            conn = None
            disconnected = asyncio.Event()
            try:
                conn = await asyncpg.connect(get_listener_database_url())

                def notify(_conn, _pid, _channel, payload):
                    task = asyncio.create_task(self._dispatch(payload))
                    self._callback_tasks.add(task)
                    task.add_done_callback(self._callback_tasks.discard)

                def terminated(_conn, disconnected=disconnected):
                    disconnected.set()

                conn.add_termination_listener(terminated)
                await conn.add_listener(_CHANNEL, notify)
                if self._on_transient is not None:

                    def transient_notify(_conn, _pid, _channel, payload):
                        task = asyncio.create_task(self._dispatch_transient(payload))
                        self._callback_tasks.add(task)
                        task.add_done_callback(self._callback_tasks.discard)

                    await conn.add_listener(_TRANSIENT_CHANNEL, transient_notify)
                self._connected.set()
                delay = 0.1
                await self._on_reconnect()
                while not disconnected.is_set():
                    try:
                        await asyncio.wait_for(disconnected.wait(), self._sync_interval)
                    except TimeoutError:
                        if self._on_periodic is not None:
                            await self._on_periodic()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Canvas operation listener disconnected")
            finally:
                self._connected.clear()
                if conn is not None and not conn.is_closed():
                    await conn.close()
            if not self._closed and self._users:
                await asyncio.sleep(delay)
                delay = min(delay * 2, 5.0)

    async def _dispatch(self, payload: str) -> None:
        try:
            await self._on_notification(payload)
        except Exception:
            logger.exception("Canvas operation notification handling failed")

    async def _dispatch_transient(self, payload: str) -> None:
        try:
            if self._on_transient is not None:
                await self._on_transient(payload)
        except Exception:
            logger.exception("Canvas transient notification handling failed")

    async def close(self) -> None:
        async with self._lock:
            if self._closed:
                return
            self._closed = True
            self._users = 0
            runner, idle = self._runner, self._idle_task
            self._runner = self._idle_task = None
            self._connected.clear()
        for task in (runner, idle):
            if task is not None:
                task.cancel()
        await asyncio.gather(
            *(task for task in (runner, idle) if task is not None),
            return_exceptions=True,
        )
        if self._callback_tasks:
            await asyncio.gather(*self._callback_tasks, return_exceptions=True)
