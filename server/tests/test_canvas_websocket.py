"""WS-03 websocket integration tests; requires an isolated migrated database."""

import asyncio
import json
import os
import unittest
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import asyncpg
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app import db
from app.auth import hash_session_token
from app.main import app


@unittest.skipUnless(os.environ.get("TEST_DATABASE_URL"), "requires TEST_DATABASE_URL")
class CanvasWebSocketPostgresTests(unittest.TestCase):
    def test_snapshot_is_first_frame_and_contains_only_visible_shapes(self):
        with self._seeded_board() as board, TestClient(app) as client:
            client.cookies.set("session", board["token"])
            with client.websocket_connect(
                f"/ws/canvases/{board['canvas_id']}",
                headers={"origin": "http://localhost:5173"},
            ) as socket:
                snapshot = socket.receive_json()
                self.assertEqual(snapshot["type"], "snapshot")
                self.assertEqual(snapshot["canvas"]["id"], str(board["canvas_id"]))
                self.assertEqual(snapshot["canvas"]["title"], "WS03 snapshot")
                self.assertEqual(snapshot["canvas_revision"], 7)
                self.assertTrue(snapshot["connection_id"])
                self.assertEqual(len(snapshot["connections"]), 1)
                self.assertEqual(
                    snapshot["connections"][0]["user"]["username"],
                    board["username"],
                )
                self.assertEqual(
                    snapshot["shapes"],
                    [
                        {
                            "id": str(board["shape_id"]),
                            "kind": "rectangle",
                            "properties": {
                                "x": 3,
                                "y": 4,
                                "width": 20,
                                "height": 10,
                                "color": "#112233",
                            },
                            "revision": 2,
                            "deleted": False,
                        }
                    ],
                )

    def test_access_matrix_rejects_before_snapshot(self):
        with self._seeded_board() as board:
            outsider_token = f"outsider-{uuid4().hex}"
            expired_token = f"expired-{uuid4().hex}"
            outsider_id = asyncio.run(
                self._add_session(
                    board["database_url"], outsider_token, None, expired=False
                )
            )
            board["extra_user_ids"].append(outsider_id)
            asyncio.run(
                self._add_session(
                    board["database_url"], expired_token, board["user_id"], expired=True
                )
            )
            cases = [
                (None, "http://localhost:5173"),
                (expired_token, "http://localhost:5173"),
                (outsider_token, "http://localhost:5173"),
                (board["token"], "https://evil.example"),
                (board["token"], None),
            ]
            with TestClient(app) as client:
                for token, origin in cases:
                    client.cookies.clear()
                    if token:
                        client.cookies.set("session", token)
                    headers = {"origin": origin} if origin else {}
                    with self.subTest(token=bool(token), origin=origin):
                        with (
                            self.assertRaises(WebSocketDisconnect) as raised,
                            client.websocket_connect(
                                f"/ws/canvases/{board['canvas_id']}", headers=headers
                            ) as socket,
                        ):
                            self.fail(
                                f"unauthorized socket got frame: {socket.receive_json()}"
                            )
                        self.assertEqual(raised.exception.code, 1008)

    def test_two_tabs_get_distinct_connection_ids_and_disconnect_independently(self):
        with self._seeded_board() as board, TestClient(app) as client:
            client.cookies.set("session", board["token"])
            with client.websocket_connect(
                f"/ws/canvases/{board['canvas_id']}",
                headers={"origin": "http://localhost:5173"},
            ) as first:
                first_snapshot = first.receive_json()
                with client.websocket_connect(
                    f"/ws/canvases/{board['canvas_id']}",
                    headers={"origin": "http://localhost:5173"},
                ) as second:
                    second_snapshot = second.receive_json()
                    self.assertNotEqual(
                        first_snapshot["connection_id"],
                        second_snapshot["connection_id"],
                    )
                    self.assertEqual(len(second_snapshot["connections"]), 2)
                    joined = first.receive_json()
                    self.assertEqual(joined["type"], "presence.joined")
                    self.assertEqual(
                        joined["connection_id"], second_snapshot["connection_id"]
                    )
                left = first.receive_json()
                self.assertEqual(left["type"], "presence.left")
                self.assertEqual(
                    left["connection_id"], second_snapshot["connection_id"]
                )
                # The remaining tab stays usable after its sibling disconnects.
                first.send_text("not-json")
                self.assertEqual(first.receive_json()["code"], "invalid_message")
                with client.websocket_connect(
                    f"/ws/canvases/{board['other_canvas_id']}",
                    headers={"origin": "http://localhost:5173"},
                ) as other_canvas:
                    other_snapshot = other_canvas.receive_json()
                    self.assertEqual(
                        other_snapshot["canvas"]["id"],
                        str(board["other_canvas_id"]),
                    )
                    self.assertEqual(len(other_snapshot["connections"]), 1)
                    self.assertIn(
                        board["canvas_id"], client.app.state.canvas_rooms._rooms
                    )
                    self.assertIn(
                        board["other_canvas_id"],
                        client.app.state.canvas_rooms._rooms,
                    )

    def _seeded_board(self):
        database_url = os.environ["TEST_DATABASE_URL"]
        previous_database_url = db.DATABASE_URL
        db.DATABASE_URL = database_url
        suffix = uuid4().hex
        username = f"ws03_{suffix[:20]}"
        token = f"session-{suffix}"
        user_id, canvas_id, other_canvas_id, shape_id = (
            uuid4(),
            uuid4(),
            uuid4(),
            uuid4(),
        )

        async def seed():
            conn = await asyncpg.connect(database_url)
            try:
                await conn.execute(
                    "INSERT INTO app_user (id, username, password_hash) VALUES ($1, $2, 'test')",
                    user_id,
                    username,
                )
                await conn.execute(
                    "INSERT INTO auth_session (token_hash, user_id, expires_at) VALUES ($1, $2, now() + interval '1 hour')",
                    hash_session_token(token),
                    user_id,
                )
                await conn.execute(
                    "INSERT INTO canvas (id, title, created_by, revision) VALUES ($1, 'WS03 snapshot', $2, 7)",
                    canvas_id,
                    user_id,
                )
                await conn.execute(
                    "INSERT INTO canvas_member (canvas_id, user_id) VALUES ($1, $2)",
                    canvas_id,
                    user_id,
                )
                await conn.execute(
                    "INSERT INTO canvas (id, title, created_by) VALUES ($1, 'WS03 second board', $2)",
                    other_canvas_id,
                    user_id,
                )
                await conn.execute(
                    "INSERT INTO canvas_member (canvas_id, user_id) VALUES ($1, $2)",
                    other_canvas_id,
                    user_id,
                )
                properties = {
                    "x": 3,
                    "y": 4,
                    "width": 20,
                    "height": 10,
                    "color": "#112233",
                }
                await conn.execute(
                    "INSERT INTO shape (id, canvas_id, kind, properties, revision) VALUES ($1, $2, 'rectangle', $3::jsonb, 2)",
                    shape_id,
                    canvas_id,
                    json.dumps(properties),
                )
                await conn.execute(
                    "INSERT INTO shape (canvas_id, kind, properties, deleted_at) VALUES ($1, 'rectangle', $2::jsonb, now())",
                    canvas_id,
                    json.dumps(properties),
                )
            finally:
                await conn.close()

        asyncio.run(seed())

        board = {
            "database_url": database_url,
            "previous_database_url": previous_database_url,
            "username": username,
            "token": token,
            "user_id": user_id,
            "canvas_id": canvas_id,
            "other_canvas_id": other_canvas_id,
            "shape_id": shape_id,
            "extra_user_ids": [],
        }
        return _BoardContext(board)

    @staticmethod
    async def _add_session(database_url, token, user_id, expired):
        conn = await asyncpg.connect(database_url)
        try:
            if user_id is None:
                user_id = uuid4()
                await conn.execute(
                    "INSERT INTO app_user (id, username, password_hash) VALUES ($1, $2, 'test')",
                    user_id,
                    f"out_{uuid4().hex[:20]}",
                )
            if expired:
                await conn.execute(
                    "INSERT INTO auth_session (token_hash, user_id, created_at, expires_at) VALUES ($1, $2, now() - interval '2 minutes', now() - interval '1 minute')",
                    hash_session_token(token),
                    user_id,
                )
            else:
                await conn.execute(
                    "INSERT INTO auth_session (token_hash, user_id, expires_at) VALUES ($1, $2, now() + interval '1 hour')",
                    hash_session_token(token),
                    user_id,
                )
        finally:
            await conn.close()
        return user_id


class _BoardContext:
    def __init__(self, board):
        self.board = board

    def __enter__(self):
        return self.board

    def __exit__(self, exc_type, exc, tb):
        asyncio.run(self._cleanup())
        db.DATABASE_URL = self.board["previous_database_url"]

    async def _cleanup(self):
        conn = await asyncpg.connect(self.board["database_url"])
        try:
            await conn.execute(
                "DELETE FROM canvas WHERE id = ANY($1::uuid[])",
                [self.board["canvas_id"], self.board["other_canvas_id"]],
            )
            await conn.execute(
                "DELETE FROM app_user WHERE id = ANY($1::uuid[])",
                [self.board["user_id"], *self.board["extra_user_ids"]],
            )
        finally:
            await conn.close()


class CanvasRoomLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_shutdown_finishes_cancelled_multi_peer_overflow_cleanup(self):
        from app.auth import PublicUser
        from app.canvas_ws import CanvasRooms, Connection, Room, SessionIdentity

        rooms = CanvasRooms()
        canvas_id = uuid4()
        room = Room()
        rooms._rooms[canvas_id] = room
        identity = SessionIdentity(
            "digest",
            PublicUser(id=uuid4(), username="tester"),
            datetime.now(UTC) + timedelta(hours=1),
        )
        sockets = [_ControlledSocket(), _ControlledSocket()]
        connections = [
            Connection(uuid4(), canvas_id, identity, socket, asyncio.Queue())
            for socket in sockets
        ]
        close_started = asyncio.Event()
        original_close = sockets[0].close

        async def interrupted_close(code=1000):
            if not close_started.is_set():
                close_started.set()
                await asyncio.Event().wait()
            await original_close(code)

        sockets[0].close = interrupted_close
        for connection in connections:
            connection.detached = True
            connection.sender_task = asyncio.create_task(asyncio.Event().wait())
            connection.expiry_task = asyncio.create_task(asyncio.Event().wait())
            room.broadcast_overflows[connection.id] = connection

        owner = asyncio.create_task(rooms._close_broadcast_overflows(room))
        rooms._serving.add(owner)
        try:
            await asyncio.wait_for(close_started.wait(), timeout=1)
            await asyncio.wait_for(rooms.close(), timeout=1)
            self.assertTrue(owner.cancelled())
            self.assertEqual([socket.closed for socket in sockets], [True, True])
            for connection in connections:
                self.assertTrue(connection.sender_task.done())
                self.assertTrue(connection.expiry_task.done())
            self.assertFalse(room.broadcast_overflows)
            self.assertNotIn(canvas_id, rooms._rooms)
        finally:
            owner.cancel()
            tasks = [owner]
            for connection in connections:
                tasks.extend([connection.sender_task, connection.expiry_task])
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def test_presence_join_broadcast_overflow_closes_slow_peer(self):
        from app.auth import PublicUser
        from app.canvas_ws import CanvasRooms, Connection, Room, SessionIdentity

        @asynccontextmanager
        async def acquire():
            yield None

        class SnapshotPool:
            pass

        pool = SnapshotPool()
        pool.acquire = acquire
        rooms = CanvasRooms(pool=pool, queue_capacity=1)
        canvas_id = uuid4()
        room = Room()
        rooms._rooms[canvas_id] = room
        identity = SessionIdentity(
            "digest",
            PublicUser(id=uuid4(), username="tester"),
            datetime.now(UTC) + timedelta(hours=1),
        )
        slow_socket = _ControlledSocket(block=True)
        slow = Connection(
            uuid4(), canvas_id, identity, slow_socket, asyncio.Queue(maxsize=1)
        )
        room.connections[slow.id] = slow
        slow.sender_task = asyncio.create_task(rooms._send_loop(slow))
        slow.expiry_task = asyncio.create_task(asyncio.Event().wait())
        slow.outbound.put_nowait({"type": "blocked"})
        await asyncio.wait_for(slow_socket.started.wait(), timeout=1)
        slow.outbound.put_nowait({"type": "queued"})

        joining_socket = _DisconnectingSocket()
        with (
            patch.object(rooms, "_authenticate", AsyncMock(return_value=identity)),
            patch.object(rooms, "_snapshot", AsyncMock(return_value={"shapes": []})),
            patch.object(
                rooms, "_connection_access_valid", AsyncMock(return_value=True)
            ),
        ):
            serving = asyncio.create_task(rooms.serve(joining_socket, canvas_id))
            try:
                await asyncio.wait_for(slow_socket.close_started.wait(), timeout=1)
                self.assertTrue(slow_socket.close_started.is_set())
                self.assertTrue(slow_socket.closed)
                self.assertTrue(slow.detached)
                self.assertTrue(slow.sender_task.done())
                self.assertTrue(slow.expiry_task.done())
                self.assertNotIn(slow.id, room.connections)
                self.assertEqual(room.leases, 1)
                joining_socket.disconnect.set()
                await asyncio.wait_for(serving, timeout=1)
                self.assertNotIn(canvas_id, rooms._rooms)
            finally:
                serving.cancel()
                await asyncio.gather(serving, return_exceptions=True)
                await rooms.close()

    async def test_cursor_broadcast_overflow_closes_and_stops_slow_peer(self):
        from app.auth import PublicUser
        from app.canvas_ws import CanvasRooms, Connection, Room, SessionIdentity

        rooms = CanvasRooms(queue_capacity=1)
        canvas_id = uuid4()
        room = Room()
        rooms._rooms[canvas_id] = room
        identity = SessionIdentity(
            "digest",
            PublicUser(id=uuid4(), username="tester"),
            datetime.now(UTC) + timedelta(hours=1),
        )
        slow_socket = _ControlledSocket(block=True)
        slow = Connection(
            uuid4(), canvas_id, identity, slow_socket, asyncio.Queue(maxsize=1)
        )
        slow.outbound.put_nowait({"type": "blocked"})
        room.connections[slow.id] = slow
        slow.sender_task = asyncio.create_task(rooms._send_loop(slow))
        slow.expiry_task = asyncio.create_task(asyncio.Event().wait())
        await asyncio.wait_for(slow_socket.started.wait(), timeout=1)
        slow.outbound.put_nowait({"type": "queued"})

        cascade_socket = _ControlledSocket(block=True)
        cascade = Connection(
            uuid4(), canvas_id, identity, cascade_socket, asyncio.Queue(maxsize=1)
        )
        cascade.outbound.put_nowait({"type": "blocked"})
        room.connections[cascade.id] = cascade
        cascade.sender_task = asyncio.create_task(rooms._send_loop(cascade))
        cascade.expiry_task = asyncio.create_task(asyncio.Event().wait())
        await asyncio.wait_for(cascade_socket.started.wait(), timeout=1)
        cascade.outbound.put_nowait({"type": "queued"})

        healthy_socket = _CursorDisconnectingSocket()
        healthy = Connection(
            uuid4(), canvas_id, identity, healthy_socket, asyncio.Queue(maxsize=4)
        )
        room.connections[healthy.id] = healthy
        healthy.sender_task = asyncio.create_task(rooms._send_loop(healthy))
        try:
            with (
                patch.object(
                    rooms, "_connection_access_valid", AsyncMock(return_value=True)
                ),
                self.assertRaises(WebSocketDisconnect),
            ):
                await asyncio.wait_for(rooms._receive_loop(healthy, room), timeout=1)
            self.assertTrue(slow_socket.close_started.is_set())
            self.assertTrue(slow_socket.closed)
            self.assertTrue(slow.detached)
            self.assertNotIn(slow.id, room.connections)
            self.assertTrue(cascade_socket.close_started.is_set())
            self.assertTrue(cascade_socket.closed)
            self.assertTrue(cascade.detached)
            self.assertNotIn(cascade.id, room.connections)
            self.assertTrue(slow.sender_task.done())
            self.assertTrue(slow.expiry_task.done())
            self.assertTrue(cascade.sender_task.done())
            self.assertTrue(cascade.expiry_task.done())
            for peer in (cascade, slow):
                self.assertEqual(
                    await asyncio.wait_for(healthy_socket.received.get(), timeout=1),
                    {"type": "presence.left", "connection_id": str(peer.id)},
                )
            self.assertTrue(healthy_socket.received.empty())
            self.assertIn(healthy.id, room.connections)
            self.assertFalse(healthy.detached)
            async with room.lock:
                self.assertTrue(
                    rooms._enqueue_locked(room, healthy, {"type": "health_check"})
                )
            self.assertEqual(
                await asyncio.wait_for(healthy_socket.received.get(), timeout=1),
                {"type": "health_check"},
            )
            async with room.lock:
                self.assertFalse(rooms._detach_locked(room, slow))
        finally:
            for task in (
                slow.sender_task,
                slow.expiry_task,
                cascade.sender_task,
                cascade.expiry_task,
                healthy.sender_task,
            ):
                task.cancel()
            await asyncio.gather(
                slow.sender_task,
                slow.expiry_task,
                cascade.sender_task,
                cascade.expiry_task,
                healthy.sender_task,
                return_exceptions=True,
            )

    async def test_shutdown_does_not_interrupt_disconnect_cleanup(self):
        from app.auth import PublicUser
        from app.canvas_ws import CanvasRooms, SessionIdentity

        @asynccontextmanager
        async def acquire():
            yield None

        class SnapshotPool:
            pass

        pool = SnapshotPool()
        pool.acquire = acquire
        rooms = CanvasRooms(pool=pool)
        canvas_id = uuid4()
        socket = _DisconnectingSocket()
        identity = SessionIdentity(
            "digest",
            PublicUser(id=uuid4(), username="tester"),
            datetime.now(UTC) + timedelta(hours=1),
        )
        with (
            patch.object(rooms, "_authenticate", AsyncMock(return_value=identity)),
            patch.object(rooms, "_snapshot", AsyncMock(return_value={"shapes": []})),
            patch.object(
                rooms, "_connection_access_valid", AsyncMock(return_value=True)
            ),
        ):
            serving = asyncio.create_task(rooms.serve(socket, canvas_id))
            room = None
            closing = None
            try:
                await asyncio.wait_for(socket.started.wait(), timeout=1)
                room = rooms._rooms[canvas_id]
                await room.lock.acquire()
                socket.disconnect.set()
                await asyncio.wait_for(socket.send_finished.wait(), timeout=1)
                closing = asyncio.create_task(rooms.close())
                try:
                    await asyncio.wait_for(asyncio.shield(serving), timeout=0.05)
                except (TimeoutError, asyncio.CancelledError):
                    pass
                room.lock.release()
                await asyncio.wait_for(closing, timeout=1)
                self.assertTrue(serving.done())
                self.assertEqual(rooms._rooms, {})
            finally:
                if room is not None and room.lock.locked():
                    room.lock.release()
                serving.cancel()
                await asyncio.gather(serving, return_exceptions=True)
                if closing is not None:
                    await asyncio.gather(closing, return_exceptions=True)

    async def test_cancelled_handshake_releases_its_room(self):
        from app.auth import PublicUser
        from app.canvas_ws import CanvasRooms, SessionIdentity

        rooms = CanvasRooms()
        socket = _BlockedHandshakeSocket()
        identity = SessionIdentity(
            "digest", PublicUser(id=uuid4(), username="tester"), datetime.now(UTC)
        )
        with patch.object(rooms, "_authenticate", AsyncMock(return_value=identity)):
            serving = asyncio.create_task(rooms.serve(socket, uuid4()))
            try:
                await asyncio.wait_for(socket.accept_started.wait(), timeout=1)
                serving.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await serving
                self.assertEqual(rooms._rooms, {})
            finally:
                serving.cancel()
                await asyncio.gather(serving, return_exceptions=True)
                await rooms.close()

    async def test_shutdown_finishes_an_inflight_handshake(self):
        from app.auth import PublicUser
        from app.canvas_ws import CanvasRooms, SessionIdentity

        rooms = CanvasRooms()
        socket = _BlockedHandshakeSocket()
        identity = SessionIdentity(
            "digest", PublicUser(id=uuid4(), username="tester"), datetime.now(UTC)
        )
        with patch.object(rooms, "_authenticate", AsyncMock(return_value=identity)):
            serving = asyncio.create_task(rooms.serve(socket, uuid4()))
            try:
                await asyncio.wait_for(socket.accept_started.wait(), timeout=1)
                await asyncio.wait_for(rooms.close(), timeout=1)
                self.assertTrue(serving.done())
                self.assertTrue(socket.closed)
                self.assertEqual(rooms._rooms, {})
            finally:
                serving.cancel()
                await asyncio.gather(serving, return_exceptions=True)

    async def test_shutdown_bounds_blocked_close_and_cleans_up_other_peers(self):
        from app.auth import PublicUser
        from app.canvas_ws import CanvasRooms, Connection, Room, SessionIdentity

        rooms = CanvasRooms()
        canvas_id = uuid4()
        room = Room()
        rooms._rooms[canvas_id] = room
        identity = SessionIdentity(
            "digest", PublicUser(id=uuid4(), username="tester"), datetime.now(UTC)
        )
        blocked = _ControlledSocket(block=True, block_close=True)
        healthy = _ControlledSocket(block=True)
        connections = [
            Connection(uuid4(), canvas_id, identity, socket, asyncio.Queue())
            for socket in (blocked, healthy)
        ]
        for connection in connections:
            room.connections[connection.id] = connection
            connection.sender_task = asyncio.create_task(rooms._send_loop(connection))
            connection.outbound.put_nowait({"type": "snapshot"})
        try:
            await asyncio.wait_for(blocked.started.wait(), timeout=1)
            await asyncio.wait_for(healthy.started.wait(), timeout=1)
            with patch("app.canvas_ws._SOCKET_CLOSE_TIMEOUT", 0.01, create=True):
                await asyncio.wait_for(rooms.close(), timeout=1)
            self.assertTrue(all(item.sender_task.done() for item in connections))
            self.assertTrue(blocked.close_started.is_set())
            self.assertTrue(healthy.closed)
            self.assertEqual(room.connections, {})
        finally:
            for connection in connections:
                connection.sender_task.cancel()
            await asyncio.gather(
                *(item.sender_task for item in connections), return_exceptions=True
            )

    async def test_slow_peer_overflow_isolated_and_sends_do_not_hold_room_lock(self):
        from app.auth import PublicUser
        from app.canvas_ws import CanvasRooms, Connection, Room, SessionIdentity

        rooms = CanvasRooms(allowed_origins=frozenset(), queue_capacity=1)
        room = Room()
        user = PublicUser(id=uuid4(), username="tester")
        identity = SessionIdentity("digest", user, datetime.now(UTC))
        blocked_socket, healthy_socket = (
            _ControlledSocket(block=True),
            _ControlledSocket(),
        )
        slow = Connection(
            uuid4(), uuid4(), identity, blocked_socket, asyncio.Queue(maxsize=1)
        )
        healthy = Connection(
            uuid4(), slow.canvas_id, identity, healthy_socket, asyncio.Queue(maxsize=1)
        )
        room.connections = {slow.id: slow, healthy.id: healthy}
        slow_sender = asyncio.create_task(rooms._send_loop(slow))
        slow.sender_task = slow_sender
        healthy_sender = asyncio.create_task(rooms._send_loop(healthy))
        try:
            async with room.lock:
                self.assertTrue(rooms._enqueue_locked(room, slow, {"type": "first"}))
                self.assertTrue(
                    rooms._enqueue_locked(room, healthy, {"type": "healthy"})
                )
            await asyncio.wait_for(healthy_socket.sent.wait(), timeout=1)
            await asyncio.wait_for(blocked_socket.started.wait(), timeout=1)
            # A transport blocked in send_json does not own the canvas lock.
            await asyncio.wait_for(room.lock.acquire(), timeout=1)
            room.lock.release()

            async with room.lock:
                self.assertTrue(rooms._enqueue_locked(room, slow, {"type": "queued"}))
                self.assertFalse(
                    rooms._enqueue_locked(room, slow, {"type": "overflow"})
                )
                self.assertNotIn(slow.id, room.connections)
                self.assertIn(healthy.id, room.connections)
            await rooms._close_slow_connection(slow)
            await asyncio.wait_for(
                asyncio.gather(slow_sender, return_exceptions=True), timeout=1
            )
            self.assertFalse(healthy_sender.done())
        finally:
            healthy_sender.cancel()
            await asyncio.gather(healthy_sender, return_exceptions=True)

    async def test_shutdown_closes_connections_and_awaits_sender_tasks(self):
        from app.auth import PublicUser
        from app.canvas_ws import CanvasRooms, Connection, Room, SessionIdentity

        rooms = CanvasRooms(allowed_origins=frozenset())
        canvas_id = uuid4()
        room = Room()
        rooms._rooms[canvas_id] = room
        identity = SessionIdentity(
            "digest", PublicUser(id=uuid4(), username="tester"), datetime.now(UTC)
        )
        socket = _ControlledSocket(block=True)
        connection = Connection(uuid4(), canvas_id, identity, socket, asyncio.Queue())
        room.connections[connection.id] = connection
        connection.sender_task = asyncio.create_task(rooms._send_loop(connection))
        connection.outbound.put_nowait({"type": "snapshot"})
        await asyncio.wait_for(socket.started.wait(), timeout=1)

        await asyncio.wait_for(rooms.close(), timeout=1)

        self.assertTrue(socket.closed)
        self.assertTrue(connection.sender_task.done())
        self.assertNotIn(connection.id, room.connections)
        self.assertTrue(connection.detached)


class _ControlledSocket:
    def __init__(self, block=False, block_close=False):
        self.block = block
        self.block_close = block_close
        self.started = asyncio.Event()
        self.sent = asyncio.Event()
        self.send_finished = asyncio.Event()
        self.close_started = asyncio.Event()
        self.closed = False

    async def send_json(self, message):
        self.started.set()
        try:
            if self.block:
                await asyncio.Event().wait()
            self.sent.set()
        finally:
            self.send_finished.set()

    async def close(self, code=1000):
        self.close_started.set()
        if self.block_close:
            await asyncio.Event().wait()
        self.closed = True


class _BlockedHandshakeSocket(_ControlledSocket):
    def __init__(self):
        super().__init__()
        self.accept_started = asyncio.Event()

    async def accept(self):
        self.accept_started.set()
        await asyncio.Event().wait()


class _DisconnectingSocket(_ControlledSocket):
    def __init__(self):
        super().__init__(block=True)
        self.disconnect = asyncio.Event()

    async def accept(self):
        pass

    async def receive_text(self):
        await self.disconnect.wait()
        raise WebSocketDisconnect()


class _CursorDisconnectingSocket:
    def __init__(self):
        self.received = asyncio.Queue()
        self.sent_frame = False

    async def receive_text(self):
        if self.sent_frame:
            raise WebSocketDisconnect()
        self.sent_frame = True
        return '{"type":"cursor","position":{"x":1,"y":2}}'

    async def send_json(self, message):
        await self.received.put(message)

    async def close(self, code=1000):
        pass
