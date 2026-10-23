"""Room lifecycle and durable canvas command orchestration."""

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4

import asyncpg
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder

from app.auth import PublicUser, hash_session_token
from app.canvas_history import Navigation, apply_history_command
from app.canvas_protocol import (
    InvalidMessage,
    _CreateCommand,
    _CursorCommand,
    _DeleteCommand,
    _merge_shape_patch,
    _parse_client_message,
    _RedoCommand,
    _UndoCommand,
    _UpdateCommand,
)
from app.db import get_pool

logger = logging.getLogger(__name__)


class _ShapeIdConflict(Exception):
    """A create attempted to reuse an existing shape identifier."""


def _operation_error(operation_id: UUID, code: str, message: str) -> dict[str, object]:
    return {
        "type": "error",
        "operation_id": str(operation_id),
        "code": code,
        "message": message,
    }


def _json_value(value: object) -> object:
    if isinstance(value, str):
        return json.loads(value)
    return value


_DEFAULT_ALLOWED_ORIGINS = frozenset({"http://localhost:5173", "http://127.0.0.1:5173"})
_SOCKET_CLOSE_TIMEOUT = 1.0


def _allowed_origins() -> frozenset[str]:
    configured = os.environ.get("WEBSOCKET_ALLOWED_ORIGINS")
    if configured is None:
        return _DEFAULT_ALLOWED_ORIGINS
    return frozenset(
        origin.strip() for origin in configured.split(",") if origin.strip()
    )


@dataclass(frozen=True)
class SessionIdentity:
    token_hash: str
    user: PublicUser
    expires_at: datetime


@dataclass
class Connection:
    id: UUID
    canvas_id: UUID
    identity: SessionIdentity
    socket: WebSocket
    outbound: asyncio.Queue[dict[str, object]]
    cursor: dict[str, float] | None = None
    history: Navigation = field(default_factory=Navigation)
    sender_task: asyncio.Task[None] | None = None
    expiry_task: asyncio.Task[None] | None = None
    detached: bool = False


@dataclass
class Room:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    connections: dict[UUID, Connection] = field(default_factory=dict)
    leases: int = 0
    operation_origins: dict[UUID, UUID] = field(default_factory=dict)


class CanvasRooms:
    """Own canvas rooms and their connection sender tasks for one app worker."""

    def __init__(
        self,
        pool: object | None = None,
        allowed_origins: frozenset[str] | None = None,
        queue_capacity: int = 32,
        expiry_check_interval: float = 1.0,
    ) -> None:
        self.pool = pool
        self.allowed_origins = (
            allowed_origins if allowed_origins is not None else _allowed_origins()
        )
        self.queue_capacity = queue_capacity
        self.expiry_check_interval = expiry_check_interval
        self._rooms: dict[UUID, Room] = {}
        self._connections: dict[UUID, tuple[Room, Connection]] = {}
        self._rooms_lock = asyncio.Lock()
        self._closing = False
        self._serving: set[asyncio.Task[None]] = set()
        self._shutdown_task: asyncio.Task[None] | None = None

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC)

    async def _db_pool(self):
        return self.pool if self.pool is not None else await get_pool()

    async def _connection_access_valid(self, connection: Connection) -> bool:
        if self._now() >= connection.identity.expires_at:
            return False
        pool = await self._db_pool()
        async with pool.acquire() as conn:
            return bool(
                await conn.fetchval(
                    """
                    SELECT EXISTS (
                        SELECT 1
                        FROM auth_session
                        JOIN canvas_member
                          ON canvas_member.user_id = auth_session.user_id
                        WHERE auth_session.token_hash = $1
                          AND auth_session.expires_at > now()
                          AND canvas_member.canvas_id = $2
                    )
                    """,
                    connection.identity.token_hash,
                    connection.canvas_id,
                )
            )

    async def _expire_when_needed(self, connection: Connection, room: Room) -> None:
        while not connection.detached:
            await asyncio.sleep(self.expiry_check_interval)
            if self._now() < connection.identity.expires_at:
                continue
            async with room.lock:
                if not connection.detached:
                    self._detach_locked(room, connection)
            await self._stop_delivery(connection)
            await self._close_socket(connection.socket, 1008)
            return

    async def _stop_delivery(self, connection: Connection) -> None:
        current = asyncio.current_task()
        sender = connection.sender_task
        if sender is not None and sender is not current and not sender.done():
            sender.cancel()
            await asyncio.gather(sender, return_exceptions=True)
        while True:
            try:
                connection.outbound.get_nowait()
            except asyncio.QueueEmpty:
                break
        expiry = connection.expiry_task
        if expiry is not None and expiry is not current and not expiry.done():
            expiry.cancel()
            await asyncio.gather(expiry, return_exceptions=True)

    async def revoke_session(self, token_hash: str) -> None:
        """Detach all live tabs for one credential, then stop their delivery."""
        async with self._rooms_lock:
            rooms = tuple(self._rooms.values())
        revoked: dict[UUID, Connection] = {}
        for room in rooms:
            async with room.lock:
                for connection in tuple(room.connections.values()):
                    if connection.identity.token_hash == token_hash:
                        self._detach_locked(room, connection)
                        revoked[connection.id] = connection
        async with self._rooms_lock:
            tracked = tuple(self._connections.values())
        revoked.update(
            {
                connection.id: connection
                for _, connection in tracked
                if connection.identity.token_hash == token_hash
            }
        )
        for connection in revoked.values():
            await self._stop_delivery(connection)
            await self._close_socket(connection.socket, 1008)

    async def _authenticate(
        self, socket: WebSocket, canvas_id: UUID
    ) -> SessionIdentity | None:
        if socket.headers.get("origin") not in self.allowed_origins:
            return None
        token = socket.cookies.get("session")
        if not token:
            return None
        pool = await self._db_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT app_user.id, app_user.username, auth_session.expires_at
                FROM auth_session
                JOIN app_user ON app_user.id = auth_session.user_id
                JOIN canvas_member ON canvas_member.user_id = app_user.id
                WHERE auth_session.token_hash = $1
                  AND auth_session.expires_at > now()
                  AND canvas_member.canvas_id = $2
                """,
                hash_session_token(token),
                canvas_id,
            )
        if row is None:
            return None
        return SessionIdentity(
            token_hash=hash_session_token(token),
            user=PublicUser(id=row["id"], username=row["username"]),
            expires_at=row["expires_at"],
        )

    async def _acquire_room(self, canvas_id: UUID) -> Room | None:
        async with self._rooms_lock:
            if self._closing:
                return None
            room = self._rooms.setdefault(canvas_id, Room())
            room.leases += 1
            return room

    async def _release_room(self, canvas_id: UUID, room: Room) -> None:
        async with self._rooms_lock:
            room.leases -= 1
            if (
                room.leases == 0
                and not room.connections
                and self._rooms.get(canvas_id) is room
            ):
                del self._rooms[canvas_id]

    async def _snapshot(
        self, conn: object, canvas_id: UUID
    ) -> dict[str, object] | None:
        canvas = await conn.fetchrow(
            """
            SELECT id, title, created_by, revision, created_at, updated_at
            FROM canvas WHERE id = $1
            """,
            canvas_id,
        )
        if canvas is None:
            return None
        shape_rows = await conn.fetch(
            """
            SELECT id, kind, properties, revision, (deleted_at IS NOT NULL) AS deleted
            FROM shape WHERE canvas_id = $1 AND deleted_at IS NULL ORDER BY id
            """,
            canvas_id,
        )
        shapes = []
        for row in shape_rows:
            properties = row["properties"]
            if isinstance(properties, str):
                properties = json.loads(properties)
            shapes.append(
                {
                    "id": row["id"],
                    "kind": row["kind"],
                    "properties": properties,
                    "revision": row["revision"],
                    "deleted": row["deleted"],
                }
            )
        return {
            "canvas": dict(canvas),
            "canvas_revision": canvas["revision"],
            "shapes": shapes,
        }

    @staticmethod
    def _public_connection(connection: Connection) -> dict[str, object]:
        return {
            "connection_id": connection.id,
            "user": {
                "id": connection.identity.user.id,
                "username": connection.identity.user.username,
            },
            "cursor": connection.cursor,
        }

    async def serve(self, socket: WebSocket, canvas_id: UUID) -> None:
        if self._closing:
            await self._close_socket(socket, 1001)
            return
        task = asyncio.current_task()
        assert task is not None
        self._serving.add(task)
        try:
            await self._serve(socket, canvas_id)
        except asyncio.CancelledError:
            await self._close_socket(socket, 1001)
            raise
        finally:
            self._serving.discard(task)

    async def _serve(self, socket: WebSocket, canvas_id: UUID) -> None:
        identity = await self._authenticate(socket, canvas_id)
        if identity is None:
            await self._close_socket(socket, 1008)
            return
        room = await self._acquire_room(canvas_id)
        if room is None:
            await self._close_socket(socket, 1001)
            return
        connection = Connection(
            id=uuid4(),
            canvas_id=canvas_id,
            identity=identity,
            socket=socket,
            outbound=asyncio.Queue(maxsize=self.queue_capacity),
        )
        registered = False
        sender: asyncio.Task[None] | None = None
        close_code: int | None = None
        try:
            await socket.accept()
            async with room.lock:
                if self._closing:
                    close_code = 1001
                    return
                if not await self._connection_access_valid(connection):
                    close_code = 1008
                    return
                pool = await self._db_pool()
                async with pool.acquire() as conn:
                    snapshot = await self._snapshot(conn, canvas_id)
                if snapshot is None:
                    close_code = 1008
                    return
                room.connections[connection.id] = connection
                registered = True
                async with self._rooms_lock:
                    self._connections[connection.id] = (room, connection)
                snapshot.update(
                    {
                        "type": "snapshot",
                        "connection_id": connection.id,
                        "connections": [
                            self._public_connection(item)
                            for item in room.connections.values()
                        ],
                    }
                )
                connection.outbound.put_nowait(jsonable_encoder(snapshot))
                self._broadcast_locked(
                    room,
                    {
                        "type": "presence.joined",
                        "connection_id": str(connection.id),
                        "user": {
                            "id": str(connection.identity.user.id),
                            "username": connection.identity.user.username,
                        },
                    },
                    exclude=connection.id,
                )
                sender = asyncio.create_task(
                    self._guarded_send_loop(connection),
                    name=f"canvas-sender-{connection.id}",
                )
                connection.sender_task = sender
                connection.expiry_task = asyncio.create_task(
                    self._expire_when_needed(connection, room),
                    name=f"canvas-expiry-{connection.id}",
                )

            await self._receive_loop(connection, room)
        except WebSocketDisconnect:
            pass
        finally:
            cleanup = asyncio.create_task(
                self._finish_connection(
                    room, connection, registered, sender, close_code
                )
            )
            cancelled = False
            # Shutdown must await lease release even if disconnect cleanup has begun.
            while not cleanup.done():
                try:
                    await asyncio.shield(cleanup)
                except asyncio.CancelledError:
                    cancelled = True
            await cleanup
            if cancelled:
                raise asyncio.CancelledError

    async def _finish_connection(
        self,
        room: Room,
        connection: Connection,
        registered: bool,
        sender: asyncio.Task[None] | None,
        close_code: int | None,
    ) -> None:
        if sender is not None and not sender.done():
            sender.cancel()
        if sender is not None:
            await asyncio.gather(sender, return_exceptions=True)
        if registered:
            async with room.lock:
                self._detach_locked(room, connection)
        async with self._rooms_lock:
            self._connections.pop(connection.id, None)
        expiry = connection.expiry_task
        if expiry is not None and expiry is not asyncio.current_task():
            expiry.cancel()
            await asyncio.gather(expiry, return_exceptions=True)
        await self._release_room(connection.canvas_id, room)
        if close_code is not None:
            await self._close_socket(connection.socket, close_code)

    async def _send_loop(self, connection: Connection) -> None:
        while True:
            message = await connection.outbound.get()
            await connection.socket.send_json(message)

    async def _guarded_send_loop(self, connection: Connection) -> None:
        try:
            await self._send_loop(connection)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Canvas sender failed for connection %s", connection.id)
            room = self._rooms.get(connection.canvas_id)
            if room is not None:
                async with room.lock:
                    self._detach_locked(room, connection)
            await self._close_socket(connection.socket, 1011)

    async def _receive_loop(self, connection: Connection, room: Room) -> None:
        while True:
            raw = await connection.socket.receive_text()
            try:
                command = _parse_client_message(raw)
            except InvalidMessage as error:
                message = error.to_message()
                applied = False
            else:
                if isinstance(command, _CursorCommand):
                    async with room.lock:
                        if connection.detached:
                            return
                        if not await self._connection_access_valid(connection):
                            self._detach_locked(room, connection)
                            revoked = True
                        else:
                            revoked = False
                        if revoked:
                            close_code = 1008
                        else:
                            close_code = None
                        if revoked:
                            pass
                        else:
                            connection.cursor = (
                                None
                                if command.position is None
                                else command.position.model_dump()
                            )
                            self._broadcast_locked(
                                room,
                                {
                                    "type": "cursor",
                                    "connection_id": str(connection.id),
                                    "user_id": str(connection.identity.user.id),
                                    "position": connection.cursor,
                                },
                                exclude=connection.id,
                            )
                    if revoked:
                        await self._stop_delivery(connection)
                        await self._close_socket(connection.socket, close_code)
                        return
                    continue
                if isinstance(
                    command, (_CreateCommand, _UpdateCommand, _DeleteCommand)
                ):
                    async with room.lock:
                        if connection.detached:
                            return
                        if not await self._connection_access_valid(connection):
                            self._detach_locked(room, connection)
                            revoked = True
                            message, applied = {}, False
                        else:
                            revoked = False
                            message, applied = await self._apply_shape_command(
                                connection, command
                            )
                        if revoked:
                            slow = []
                        elif applied:
                            connection.history.record_edit(command.operation_id)
                            room.operation_origins[command.operation_id] = connection.id
                            slow = [
                                peer
                                for peer in list(room.connections.values())
                                if not self._enqueue_locked(room, peer, message)
                            ]
                        elif not revoked:
                            slow = (
                                [connection]
                                if not self._enqueue_locked(room, connection, message)
                                else []
                            )
                    if revoked:
                        await self._stop_delivery(connection)
                        await self._close_socket(connection.socket, 1008)
                        return
                    for peer in slow:
                        await self._close_slow_connection(peer)
                    continue
                if isinstance(command, (_UndoCommand, _RedoCommand)):
                    async with room.lock:
                        if connection.detached:
                            return
                        if not await self._connection_access_valid(connection):
                            self._detach_locked(room, connection)
                            revoked = True
                            message, applied = {}, False
                        else:
                            revoked = False
                            message, applied = await self._apply_history_command(
                                connection, room, command
                            )
                        if revoked:
                            slow = []
                        elif applied:
                            if isinstance(command, _UndoCommand):
                                connection.history.record_undo(
                                    command.target_operation_id, command.operation_id
                                )
                            else:
                                connection.history.record_redo(
                                    command.target_operation_id, command.operation_id
                                )
                            room.operation_origins[command.operation_id] = connection.id
                            slow = [
                                peer
                                for peer in list(room.connections.values())
                                if not self._enqueue_locked(room, peer, message)
                            ]
                        elif not revoked:
                            slow = (
                                [connection]
                                if not self._enqueue_locked(room, connection, message)
                                else []
                            )
                    if revoked:
                        await self._stop_delivery(connection)
                        await self._close_socket(connection.socket, 1008)
                        return
                    for peer in slow:
                        await self._close_slow_connection(peer)
                    continue
                message = {
                    "type": "error",
                    "code": "feature_not_available",
                    "message": "This command is not available yet.",
                }
            async with room.lock:
                if connection.detached:
                    return
                if not await self._connection_access_valid(connection):
                    self._detach_locked(room, connection)
                    revoked = True
                    close_slow = False
                else:
                    revoked = False
                    if not self._enqueue_locked(room, connection, message):
                        close_slow = True
                    else:
                        close_slow = False
            if revoked:
                await self._stop_delivery(connection)
                await self._close_socket(connection.socket, 1008)
                return
            if close_slow:
                await self._close_slow_connection(connection)
                return

    async def _apply_shape_command(
        self,
        connection: Connection,
        command: _CreateCommand | _UpdateCommand | _DeleteCommand,
    ) -> tuple[dict[str, object], bool]:
        request = command.model_dump(mode="json")
        pool = await self._db_pool()
        try:
            async with pool.acquire() as conn:  # noqa: SIM117
                async with conn.transaction():
                    access = await conn.fetchrow(
                        """
                        SELECT canvas.revision
                        FROM canvas
                        JOIN canvas_member ON canvas_member.canvas_id = canvas.id
                        JOIN auth_session ON auth_session.user_id = canvas_member.user_id
                        WHERE canvas.id = $1
                          AND canvas_member.user_id = $2
                          AND auth_session.token_hash = $3
                          AND auth_session.expires_at > now()
                        FOR UPDATE OF canvas
                        """,
                        connection.canvas_id,
                        connection.identity.user.id,
                        connection.identity.token_hash,
                    )
                    if access is None:
                        return _operation_error(
                            command.operation_id,
                            "access_revoked",
                            "Canvas access is no longer available.",
                        ), False

                    replay = await self._operation_replay(
                        conn, connection, command.operation_id, request
                    )
                    if replay is not None:
                        return replay, False

                    before_patch: dict[str, object]
                    after_patch: dict[str, object]
                    operation_kind: str
                    if isinstance(command, _CreateCommand):
                        operation_kind = "create"
                        before_patch = {}
                        after_patch = {
                            "kind": command.kind,
                            "properties": command.properties,
                        }
                        await conn.execute(
                            """INSERT INTO shape (id, canvas_id, kind, properties)
                               VALUES ($1, $2, $3, $4::jsonb)""",
                            command.shape_id,
                            connection.canvas_id,
                            command.kind,
                            json.dumps(command.properties),
                        )
                        shape = {
                            "id": str(command.shape_id),
                            "kind": command.kind,
                            "properties": command.properties,
                            "revision": 1,
                            "deleted": False,
                        }
                    else:
                        row = await conn.fetchrow(
                            """SELECT id, kind, properties, revision,
                                      (deleted_at IS NOT NULL) AS deleted
                               FROM shape WHERE id = $1 AND canvas_id = $2
                               FOR UPDATE""",
                            command.shape_id,
                            connection.canvas_id,
                        )
                        if row is None:
                            return _operation_error(
                                command.operation_id,
                                "shape_unavailable",
                                "Shape is not available in this canvas.",
                            ), False
                        properties = _json_value(row["properties"])
                        current_shape = {
                            "id": str(row["id"]),
                            "kind": row["kind"],
                            "properties": properties,
                            "revision": row["revision"],
                            "deleted": row["deleted"],
                        }
                        if row["revision"] != command.expected_revision:
                            return {
                                **_operation_error(
                                    command.operation_id,
                                    "conflict",
                                    "Shape revision is stale.",
                                ),
                                "shape": current_shape,
                            }, False
                        if row["deleted"]:
                            return _operation_error(
                                command.operation_id,
                                "shape_deleted",
                                "Shape has already been deleted.",
                            ), False
                        operation_kind = (
                            "update"
                            if isinstance(command, _UpdateCommand)
                            else "delete"
                        )
                        if isinstance(command, _UpdateCommand):
                            try:
                                merged = _merge_shape_patch(
                                    row["kind"], properties, command.patch
                                )
                            except (TypeError, ValueError) as exc:
                                return _operation_error(
                                    command.operation_id, "invalid_patch", str(exc)
                                ), False
                            before_patch = {
                                key: properties[key] for key in command.patch
                            }
                            after_patch = dict(command.patch)
                            await conn.execute(
                                """UPDATE shape SET properties = $2::jsonb,
                                          revision = revision + 1, updated_at = now()
                                   WHERE id = $1""",
                                command.shape_id,
                                json.dumps(merged),
                            )
                            properties = merged
                        else:
                            before_patch = {"deleted": False}
                            after_patch = {"deleted": True}
                            await conn.execute(
                                """UPDATE shape SET deleted_at = now(),
                                          revision = revision + 1, updated_at = now()
                                   WHERE id = $1""",
                                command.shape_id,
                            )
                        shape = {
                            **current_shape,
                            "properties": properties,
                            "revision": row["revision"] + 1,
                            "deleted": operation_kind == "delete",
                        }

                    revision = access["revision"] + 1
                    result: dict[str, object] = {
                        "type": "operation.applied",
                        "operation_id": str(command.operation_id),
                        "actor_id": str(connection.identity.user.id),
                        "kind": operation_kind,
                        "target_operation_id": None,
                        "canvas_revision": revision,
                        "shape": shape,
                    }
                    await conn.execute(
                        """UPDATE canvas SET revision = $2, updated_at = now()
                           WHERE id = $1""",
                        connection.canvas_id,
                        revision,
                    )
                    await conn.execute(
                        """INSERT INTO canvas_operation
                           (id, canvas_id, shape_id, actor_id, canvas_revision, kind,
                            before_patch, after_patch, request, result)
                           VALUES ($1, $2, $3, $4, $5, $6,
                                   $7::jsonb, $8::jsonb, $9::jsonb, $10::jsonb)""",
                        command.operation_id,
                        connection.canvas_id,
                        command.shape_id,
                        connection.identity.user.id,
                        revision,
                        operation_kind,
                        json.dumps(before_patch),
                        json.dumps(after_patch),
                        json.dumps(request),
                        json.dumps(result),
                    )
                    return result, True
        except asyncpg.UniqueViolationError:
            # A different canvas lock cannot serialize a globally unique operation ID.
            collision = await self._operation_collision(
                pool, connection, command.operation_id, request
            )
            if collision is not None:
                return collision, False
            if isinstance(command, _CreateCommand):
                return _operation_error(
                    command.operation_id,
                    "shape_unavailable",
                    "Shape ID is already in use.",
                ), False
            return _operation_error(
                command.operation_id,
                "operation_failed",
                "Operation could not be saved.",
            ), False
        except asyncpg.PostgresError:
            logger.exception("Canvas shape command transaction failed")
            return _operation_error(
                command.operation_id,
                "operation_failed",
                "Operation could not be saved.",
            ), False

    async def _apply_history_command(
        self,
        connection: Connection,
        room: Room,
        command: _UndoCommand | _RedoCommand,
    ) -> tuple[dict[str, object], bool]:
        pool = await self._db_pool()

        async def collision(operation_id, request):
            return await self._operation_collision(
                pool, connection, operation_id, request
            )

        return await apply_history_command(
            pool=pool,
            connection=connection,
            room=room,
            command=command,
            replay=self._operation_replay,
            collision=collision,
        )

    async def _operation_replay(
        self,
        conn: object,
        connection: Connection,
        operation_id: UUID,
        request: dict[str, object],
    ) -> dict[str, object] | None:
        previous = await conn.fetchrow(
            """SELECT canvas_id, actor_id, request, result
               FROM canvas_operation WHERE id = $1""",
            operation_id,
        )
        if previous is None:
            return None
        saved_result = _json_value(previous["result"])
        if (
            previous["canvas_id"] == connection.canvas_id
            and previous["actor_id"] == connection.identity.user.id
            and _json_value(previous["request"]) == request
            and isinstance(saved_result, dict)
        ):
            return saved_result
        return _operation_error(
            operation_id,
            "operation_id_reused",
            "Operation ID was already used for another request.",
        )

    async def _operation_collision(
        self,
        pool: object,
        connection: Connection,
        operation_id: UUID,
        request: dict[str, object],
    ) -> dict[str, object] | None:
        try:
            async with pool.acquire() as conn:
                winner = await conn.fetchrow(
                    """SELECT canvas_id, actor_id, request, result
                       FROM canvas_operation WHERE id = $1""",
                    operation_id,
                )
        except asyncpg.PostgresError:
            logger.exception("Could not inspect operation ID collision")
            return _operation_error(
                operation_id,
                "operation_failed",
                "Operation could not be saved.",
            )
        if winner is None:
            return None
        saved_result = _json_value(winner["result"])
        if (
            winner["canvas_id"] == connection.canvas_id
            and winner["actor_id"] == connection.identity.user.id
            and _json_value(winner["request"]) == request
            and isinstance(saved_result, dict)
        ):
            return saved_result
        return _operation_error(
            operation_id,
            "operation_id_reused",
            "Operation ID was already used for another request.",
        )

    def _enqueue_locked(
        self, room: Room, connection: Connection, message: dict[str, object]
    ) -> bool:
        if connection.detached:
            return False
        try:
            connection.outbound.put_nowait(message)
            return True
        except asyncio.QueueFull:
            self._detach_locked(room, connection)
            return False

    def _broadcast_locked(
        self,
        room: Room,
        message: dict[str, object],
        exclude: UUID | None = None,
    ) -> None:
        for recipient in tuple(room.connections.values()):
            if recipient.id != exclude:
                self._enqueue_locked(room, recipient, message)

    def _detach_locked(self, room: Room, connection: Connection) -> bool:
        if connection.detached:
            return False
        connection.detached = True
        removed = room.connections.pop(connection.id, None)
        if removed is not None:
            self._broadcast_locked(
                room,
                {"type": "presence.left", "connection_id": str(connection.id)},
            )
        return True

    async def _close_slow_connection(self, connection: Connection) -> None:
        if connection.sender_task is not None:
            connection.sender_task.cancel()
            await asyncio.gather(connection.sender_task, return_exceptions=True)
        await self._close_socket(connection.socket, 1013)

    @staticmethod
    async def _close_socket(socket: WebSocket, code: int) -> None:
        try:
            await asyncio.wait_for(
                socket.close(code=code), timeout=_SOCKET_CLOSE_TIMEOUT
            )
        except (TimeoutError, OSError, RuntimeError, WebSocketDisconnect):
            logger.debug("Socket close did not complete normally", exc_info=True)

    async def close(self) -> None:
        if self._shutdown_task is None:
            self._closing = True
            self._shutdown_task = asyncio.create_task(self._shutdown())
        await asyncio.shield(self._shutdown_task)

    async def _shutdown(self) -> None:
        serving = list(self._serving)
        for task in serving:
            task.cancel()
        await asyncio.gather(*serving, return_exceptions=True)
        async with self._rooms_lock:
            rooms = list(self._rooms.items())
        connections: list[Connection] = []
        for _, room in rooms:
            async with room.lock:
                for connection in list(room.connections.values()):
                    self._detach_locked(room, connection)
                    connections.append(connection)
        for connection in connections:
            if connection.sender_task is not None:
                connection.sender_task.cancel()
        await asyncio.gather(
            *(c.sender_task for c in connections if c.sender_task is not None),
            return_exceptions=True,
        )
        await asyncio.gather(*(self._close_socket(c.socket, 1001) for c in connections))
        async with self._rooms_lock:
            for canvas_id, room in rooms:
                if not room.leases and not room.connections:
                    self._rooms.pop(canvas_id, None)


router = APIRouter()


@router.websocket("/ws/canvases/{canvas_id}")
async def websocket_endpoint(socket: WebSocket, canvas_id: UUID) -> None:
    rooms: CanvasRooms = socket.app.state.canvas_rooms
    await rooms.serve(socket, canvas_id)
