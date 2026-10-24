"""WS-08 live session revocation and expiry integration tests."""

import asyncio
import json
import os
import sys
import threading
import unittest
from concurrent.futures import CancelledError as FutureCancelledError
from contextlib import asynccontextmanager, contextmanager, suppress
from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import uuid4

import anyio
import asyncpg
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from test_canvas_create import (
    _create,
    _receive_json,
    _shape_cases,
    awaitable_result,
)

from app.auth import PublicUser, hash_session_token
from app.canvas_protocol import _CreateCommand, _UndoCommand
from app.canvas_ws import CanvasRooms, Connection, Room, SessionIdentity
from app.main import app


@unittest.skipUnless(os.environ.get("TEST_DATABASE_URL"), "requires TEST_DATABASE_URL")
class CanvasSessionPostgresTests(unittest.TestCase):
    def _board(self):
        from test_canvas_create import CanvasCreatePostgresTests

        return CanvasCreatePostgresTests()._board()

    @staticmethod
    def _socket(client, board, token, canvas_id=None):
        session = client.websocket_connect(
            f"/ws/canvases/{canvas_id or board['canvas_id']}",
            headers={
                "origin": "http://localhost:5173",
                "cookie": f"session={token}",
            },
        )
        return _server_closed_socket_context(session)

    def _assert_socket_closed(self, socket):
        with self.assertRaises(WebSocketDisconnect):
            _receive_json(socket, timeout=2)
        socket._server_closed = True

    def test_logout_detaches_all_tabs_for_exact_session_and_keeps_other_login(self):
        with self._board() as board, TestClient(app) as client:
            token_a2 = f"ws08-second-{uuid4().hex}"
            asyncio.run(self._add_session(board, token_a2, board["user_a"]))
            with (
                self._socket(client, board, board["token_a"]) as a_first,
                self._socket(
                    client, board, board["token_a"], board["other_canvas_id"]
                ) as a_second,
                self._socket(client, board, token_a2) as a_other_login,
                self._socket(client, board, board["token_b"]) as peer_first,
                self._socket(
                    client, board, board["token_b"], board["other_canvas_id"]
                ) as peer_second,
            ):
                snapshots = [
                    _receive_json(socket)
                    for socket in (
                        a_first,
                        a_second,
                        a_other_login,
                        peer_first,
                        peer_second,
                    )
                ]
                for snapshot in snapshots:
                    self.assertEqual(snapshot["type"], "snapshot")
                client.cookies.set("session", board["token_a"])
                response = client.post("/api/auth/logout")
                self.assertEqual(response.status_code, 204)
                self.assertIn('session=""', response.headers["set-cookie"])
                self.assertEqual(
                    _receive_presence(peer_first, "presence.left")["connection_id"],
                    snapshots[0]["connection_id"],
                )
                self.assertEqual(
                    _receive_presence(peer_second, "presence.left")["connection_id"],
                    snapshots[1]["connection_id"],
                )
                for revoked in (a_first, a_second):
                    self._assert_socket_closed(revoked)

                operation_id, shape_id = uuid4(), uuid4()
                a_other_login.send_json(
                    _create(operation_id, shape_id, *_shape_cases()[0])
                )
                event = _receive_json(a_other_login)
                self.assertEqual(event["type"], "operation.applied")
                self.assertEqual(event["actor_id"], str(board["user_a"]))

    def test_deleted_session_closes_on_next_invalid_or_cursor_frame_without_effects(
        self,
    ):
        with (
            self._board() as board,
            TestClient(app) as client,
            self._socket(client, board, board["token_a"]) as alice,
            self._socket(
                client, board, board["token_a"], board["other_canvas_id"]
            ) as alice_other,
            self._socket(client, board, board["token_b"]) as bob,
            self._socket(
                client, board, board["token_b"], board["other_canvas_id"]
            ) as bob_other,
        ):
            for socket in (alice, alice_other, bob, bob_other):
                _receive_json(socket)
            asyncio.run(self._delete_session(board, board["token_a"]))
            alice.send_text("not-json")
            alice_other.send_json({"type": "cursor", "position": {"x": 10, "y": 20}})
            for revoked in (alice, alice_other):
                self._assert_socket_closed(revoked)
            for peer in (bob, bob_other):
                self.assertEqual(
                    _receive_presence(peer, "presence.left")["type"],
                    "presence.left",
                )
                self.assertIsNone(_receive_nowait(peer))
            self.assertEqual(awaitable_result(self._state(board)), (0, 0, 0))

    def test_logout_serializes_with_an_admitted_command(self):
        with self._board() as board, TestClient(app) as client:
            rooms = client.app.state.canvas_rooms
            original_access = rooms._connection_access_valid
            original_revoke = rooms.revoke_session
            command_entered = threading.Event()
            release_command = threading.Event()
            logout_deleted = threading.Event()
            gate_command = threading.Event()

            async def gated_access(connection):
                if (
                    gate_command.is_set()
                    and connection.identity.token_hash
                    == hash_session_token(board["token_a"])
                ):
                    command_entered.set()
                    await asyncio.to_thread(release_command.wait, 3)
                return await original_access(connection)

            async def mark_revoke(token_hash):
                logout_deleted.set()
                await original_revoke(token_hash)

            rooms._connection_access_valid = gated_access
            rooms.revoke_session = mark_revoke
            with self._socket(client, board, board["token_a"]) as alice:
                _receive_json(alice)
                gate_command.set()
                command = _create(uuid4(), uuid4(), *_shape_cases()[0])
                alice.send_json(command)
                self.assertTrue(command_entered.wait(timeout=2))
                client.cookies.set("session", board["token_a"])
                responses = []
                logout = threading.Thread(
                    target=lambda: responses.append(client.post("/api/auth/logout"))
                )
                logout.start()
                self.assertTrue(logout_deleted.wait(timeout=2))
                release_command.set()
                logout.join(timeout=3)
                self.assertFalse(logout.is_alive())
                self.assertEqual(responses[0].status_code, 204)
                self._assert_socket_closed(alice)
                self.assertEqual(awaitable_result(self._state(board)), (0, 0, 0))
            rooms._connection_access_valid = original_access
            rooms.revoke_session = original_revoke

    def test_two_member_flow_persists_create_update_cursor_undo_redo_and_reconnect(
        self,
    ):
        with (
            self._board() as board,
            TestClient(app) as client,
            self._socket(client, board, board["token_a"]) as alice,
        ):
            _receive_json(alice)
            with self._socket(client, board, board["token_b"]) as bob:
                _receive_json(bob)
                _receive_presence(alice, "presence.joined")
                create_id, shape_id = uuid4(), uuid4()
                alice.send_json(_create(create_id, shape_id, *_shape_cases()[0]))
                created = _receive_json(alice)
                self.assertEqual(_receive_json(bob), created)
                update_id = uuid4()
                alice.send_json(
                    {
                        "type": "shape.update",
                        "operation_id": str(update_id),
                        "shape_id": str(shape_id),
                        "expected_revision": 1,
                        "patch": {"x": 18},
                    }
                )
                updated = _receive_json(alice)
                self.assertEqual(_receive_json(bob), updated)
                alice.send_json({"type": "cursor", "position": {"x": 18, "y": 2}})
                cursor = _receive_presence(bob, "cursor")
                self.assertEqual(cursor["position"], {"x": 18.0, "y": 2.0})
                undo_id = uuid4()
                alice.send_json(
                    {
                        "type": "undo",
                        "operation_id": str(undo_id),
                        "target_operation_id": str(update_id),
                    }
                )
                undone = _receive_json(alice)
                self.assertEqual(_receive_json(bob), undone)
                self.assertEqual(undone["shape"]["properties"]["x"], 1.0)
                redo_id = uuid4()
                alice.send_json(
                    {
                        "type": "redo",
                        "operation_id": str(redo_id),
                        "target_operation_id": str(undo_id),
                    }
                )
                redone = _receive_json(alice)
                self.assertEqual(_receive_json(bob), redone)
                self.assertEqual(redone["shape"]["properties"]["x"], 18.0)
            self.assertEqual(
                _receive_presence(alice, "presence.left")["type"],
                "presence.left",
            )
            with self._socket(client, board, board["token_b"]) as resumed:
                snapshot = _receive_json(resumed)
                shape = next(
                    item for item in snapshot["shapes"] if item["id"] == str(shape_id)
                )
                self.assertEqual(shape["properties"]["x"], 18.0)
                self.assertEqual(snapshot["canvas_revision"], 4)

    def test_idle_expiry_uses_room_clock_and_scheduler(self):

        with self._board() as board, TestClient(app) as client:
            rooms = client.app.state.canvas_rooms
            original_now = rooms._now
            now = datetime.now(UTC)
            rooms._now = lambda: now
            # Handshake captures the database expiry; the injected room clock lets
            # this test advance past it without sleeping for the session lifetime.
            with self._socket(client, board, board["token_a"]) as socket:
                self.assertEqual(_receive_json(socket)["type"], "snapshot")
                now = now + timedelta(days=2)
                self._assert_socket_closed(socket)
            rooms._now = original_now

    async def _add_session(self, board, token, user_id):
        conn = await asyncpg.connect(board["url"])
        try:
            await conn.execute(
                "INSERT INTO auth_session (token_hash, user_id, expires_at) VALUES ($1, $2, now() + interval '1 hour')",
                hash_session_token(token),
                user_id,
            )
        finally:
            await conn.close()

    async def _delete_session(self, board, token):
        conn = await asyncpg.connect(board["url"])
        try:
            await conn.execute(
                "DELETE FROM auth_session WHERE token_hash=$1",
                hash_session_token(token),
            )
        finally:
            await conn.close()

    async def _state(self, board):
        conn = await asyncpg.connect(board["url"])
        try:
            revision = await conn.fetchval(
                "SELECT revision FROM canvas WHERE id=$1", board["canvas_id"]
            )
            shapes = await conn.fetchval(
                "SELECT count(*) FROM shape WHERE canvas_id=$1 AND id <> $2",
                board["canvas_id"],
                board["reserved_shape_id"],
            )
            operations = await conn.fetchval(
                "SELECT count(*) FROM canvas_operation WHERE canvas_id=$1",
                board["canvas_id"],
            )
            return revision, shapes, operations
        finally:
            await conn.close()


@unittest.skipUnless(os.environ.get("TEST_DATABASE_URL"), "requires TEST_DATABASE_URL")
class DurableLogoutOrderingPostgresTests(unittest.TestCase):
    def setUp(self):
        from test_canvas_create import CanvasCreatePostgresTests

        self.fixtures = CanvasCreatePostgresTests()

    def test_logout_waits_for_admitted_shape_write(self):
        self._assert_admitted_write_waits_for_logout("shape")

    def test_logout_waits_for_admitted_history_write(self):
        self._assert_admitted_write_waits_for_logout("history")

    def test_deleted_session_rejects_shape_write_without_effects(self):
        self._assert_deleted_session_rejects_write("shape")

    def test_deleted_session_rejects_history_write_without_effects(self):
        self._assert_deleted_session_rejects_write("history")

    def test_uncommitted_delete_blocks_and_rejects_shape_write_without_effects(self):
        self._assert_uncommitted_delete_rejects_write("shape")

    def test_uncommitted_delete_blocks_and_rejects_history_write_without_effects(self):
        self._assert_uncommitted_delete_rejects_write("history")

    def test_logout_lock_timeout_preserves_session_and_local_state(self):
        with self.fixtures._board() as board, TestClient(app) as client:
            client.cookies.set("session", board["token_a"])
            rooms = client.app.state.canvas_rooms
            original_revoke = rooms.revoke_session
            revoked = []

            async def track_revoke(token_hash):
                revoked.append(token_hash)
                await original_revoke(token_hash)

            rooms.revoke_session = track_revoke
            try:
                status_code, set_cookie, session_exists = asyncio.run(
                    self._logout_times_out(board, client)
                )
            finally:
                rooms.revoke_session = original_revoke

            self.assertEqual(status_code, 503)
            self.assertIsNone(set_cookie)
            self.assertEqual(client.cookies.get("session"), board["token_a"])
            self.assertEqual(revoked, [])
            self.assertTrue(session_exists)

    async def _logout_times_out(self, board, client):
        conn = await asyncpg.connect(board["url"])
        try:
            async with conn.transaction():
                await conn.fetchrow(
                    "SELECT token_hash FROM auth_session WHERE token_hash = $1 FOR KEY SHARE",
                    hash_session_token(board["token_a"]),
                )
                with patch("app.auth._LOGOUT_LOCK_TIMEOUT", "50ms"):
                    response = await asyncio.to_thread(client.post, "/api/auth/logout")
                exists = await conn.fetchval(
                    "SELECT EXISTS (SELECT 1 FROM auth_session WHERE token_hash = $1)",
                    hash_session_token(board["token_a"]),
                )
                return response.status_code, response.headers.get("set-cookie"), exists
        finally:
            await conn.close()

    def _assert_admitted_write_waits_for_logout(self, kind):
        with self.fixtures._board() as board, TestClient(app) as client:
            client.cookies.set("session", board["token_a"])
            self.assertTrue(
                asyncio.run(self._admitted_write_waits(board, client, kind))
            )

    def _assert_deleted_session_rejects_write(self, kind):
        with self.fixtures._board() as board, TestClient(app) as client:
            client.cookies.set("session", board["token_a"])
            self.assertTrue(
                asyncio.run(self._deleted_session_rejects(board, client, kind))
            )

    def _assert_uncommitted_delete_rejects_write(self, kind):
        with self.fixtures._board() as board:
            self.assertTrue(asyncio.run(self._uncommitted_delete_rejects(board, kind)))

    async def _admitted_write_waits(self, board, client, kind):
        pool = await asyncpg.create_pool(board["url"], min_size=1, max_size=4)
        entered = asyncio.Event()
        release = asyncio.Event()
        rooms = CanvasRooms(pool=_GatedPool(pool, entered, release))
        connection = _connection(board)
        command, room = await self._write_command(kind, pool, connection)
        command_task = asyncio.create_task(
            self._apply(rooms, connection, command, room)
        )
        logout_task = None
        blocked = False
        state = None
        try:
            await asyncio.wait_for(entered.wait(), timeout=2)
            logout_task = asyncio.create_task(
                asyncio.to_thread(client.post, "/api/auth/logout")
            )
            blocked = await _logout_delete_is_blocked(pool)
        finally:
            release.set()
            result, committed = await command_task
            response = await logout_task if logout_task is not None else None
            state = await _canvas_state(pool, board)
            await pool.close()

        self.assertTrue(blocked, "logout DELETE did not wait on the admitted command")
        self.assertTrue(committed)
        self.assertEqual(result["type"], "operation.applied")
        self.assertEqual(response.status_code, 204)
        self.assertEqual(state, (1, 1, 1) if kind == "shape" else (2, 1, 2))
        return True

    async def _deleted_session_rejects(self, board, client, kind):
        pool = await asyncpg.create_pool(board["url"], min_size=1, max_size=3)
        try:
            connection = _connection(board)
            rooms = CanvasRooms(pool=pool)
            if kind == "history":
                create = _create_command()
                _created, committed = await rooms._apply_shape_command(
                    connection, create
                )
                self.assertTrue(committed)
                connection.history.record_edit(create.operation_id)
                room = Room()
                room.operation_origins[create.operation_id] = connection.id
                command = _UndoCommand(
                    type="undo",
                    operation_id=uuid4(),
                    target_operation_id=create.operation_id,
                )
                before = await _canvas_state(pool, board)
            else:
                command = _create_command()
                room = Room()
                before = await _canvas_state(pool, board)

            response = await asyncio.to_thread(client.post, "/api/auth/logout")
            self.assertEqual(response.status_code, 204)
            result, committed = await self._apply(rooms, connection, command, room)
            self.assertFalse(committed)
            self.assertEqual(result["code"], "access_revoked")
            self.assertEqual(await _canvas_state(pool, board), before)
            return True
        finally:
            await pool.close()

    async def _uncommitted_delete_rejects(self, board, kind):
        application_name = f"logout_delete_{uuid4().hex}"
        pool = await asyncpg.create_pool(
            board["url"],
            min_size=1,
            max_size=3,
            server_settings={"application_name": application_name},
        )
        blocker = await asyncpg.connect(board["url"])
        command_task = None
        try:
            connection = _connection(board)
            rooms = CanvasRooms(pool=pool)
            command, room = await self._write_command(kind, pool, connection)
            before = await _canvas_state(pool, board)

            async with blocker.transaction():
                await blocker.execute(
                    "DELETE FROM auth_session WHERE token_hash=$1",
                    hash_session_token(board["token_a"]),
                )
                command_task = asyncio.create_task(
                    self._apply(rooms, connection, command, room)
                )
                blocked = await _session_access_read_is_blocked(pool, application_name)

            result, committed = await asyncio.wait_for(command_task, timeout=3)
            self.assertTrue(
                blocked,
                "canvas command did not wait for the uncommitted session delete",
            )
            self.assertFalse(committed)
            self.assertEqual(result["code"], "access_revoked")
            self.assertEqual(await _canvas_state(pool, board), before)
            return True
        finally:
            if command_task is not None and not command_task.done():
                command_task.cancel()
                with suppress(asyncio.CancelledError):
                    await command_task
            await blocker.close()
            await pool.close()

    async def _write_command(self, kind, pool, connection):
        if kind == "shape":
            return _create_command(), None
        seed = _create_command()
        result, committed = await CanvasRooms(pool=pool)._apply_shape_command(
            connection, seed
        )
        self.assertTrue(committed, result)
        connection.history.record_edit(seed.operation_id)
        room = Room()
        room.operation_origins[seed.operation_id] = connection.id
        return (
            _UndoCommand(
                type="undo", operation_id=uuid4(), target_operation_id=seed.operation_id
            ),
            room,
        )

    async def _apply(self, rooms, connection, command, room):
        if isinstance(command, _UndoCommand):
            return await rooms._apply_history_command(connection, room, command)
        return await rooms._apply_shape_command(connection, command)


class _GatedPool:
    def __init__(self, pool, entered, release):
        self.pool = pool
        self.entered = entered
        self.release = release

    @asynccontextmanager
    async def acquire(self):
        async with self.pool.acquire() as connection:
            yield _GatedConnection(connection, self.entered, self.release)


class _GatedConnection:
    def __init__(self, connection, entered, release):
        self.connection = connection
        self.entered = entered
        self.release = release

    def __getattr__(self, name):
        return getattr(self.connection, name)

    async def fetchrow(self, query, *args):
        row = await self.connection.fetchrow(query, *args)
        if "auth_session.token_hash" in query:
            self.entered.set()
            await self.release.wait()
        return row


def _connection(board):
    return Connection(
        id=uuid4(),
        canvas_id=board["canvas_id"],
        identity=SessionIdentity(
            hash_session_token(board["token_a"]),
            PublicUser(id=board["user_a"], username=f"a_{board['user_a'].hex}"),
            datetime.now(UTC) + timedelta(hours=1),
        ),
        socket=None,
        outbound=asyncio.Queue(),
    )


def _create_command():
    kind, properties = _shape_cases()[0]
    return _CreateCommand(
        type="shape.create",
        operation_id=uuid4(),
        shape_id=uuid4(),
        kind=kind,
        properties=properties,
    )


async def _logout_delete_is_blocked(pool):
    async with pool.acquire() as conn:

        async def wait_for_lock():
            while True:
                blocked = await conn.fetchval(
                    """SELECT EXISTS (
                           SELECT 1 FROM pg_stat_activity
                           WHERE datname = current_database()
                             AND query LIKE 'DELETE FROM auth_session WHERE token_hash =%'
                             AND wait_event_type = 'Lock'
                             AND cardinality(pg_blocking_pids(pid)) > 0
                       )"""
                )
                if blocked:
                    return True
                await asyncio.sleep(0.01)

        try:
            return await asyncio.wait_for(wait_for_lock(), timeout=3)
        except TimeoutError:
            return False


async def _session_access_read_is_blocked(pool, application_name):
    async with pool.acquire() as conn:

        async def wait_for_lock():
            while True:
                blocked = await conn.fetchval(
                    """SELECT EXISTS (
                           SELECT 1 FROM pg_stat_activity
                           WHERE datname = current_database()
                             AND application_name = $1
                             AND query LIKE '%SELECT auth_session.user_id%'
                             AND wait_event_type = 'Lock'
                             AND cardinality(pg_blocking_pids(pid)) > 0
                       )""",
                    application_name,
                )
                if blocked:
                    return True
                await asyncio.sleep(0.01)

        try:
            return await asyncio.wait_for(wait_for_lock(), timeout=3)
        except TimeoutError:
            return False


async def _canvas_state(pool, board):
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT revision,
                      (SELECT count(*) FROM shape
                       WHERE canvas_id = $1 AND id <> $2) AS shapes,
                      (SELECT count(*) FROM canvas_operation WHERE canvas_id = $1)
                       AS operations
               FROM canvas WHERE id = $1""",
            board["canvas_id"],
            board["reserved_shape_id"],
        )
        return row["revision"], row["shapes"], row["operations"]


def _receive_presence(socket, event_type, timeout=1):
    async def receive():
        with anyio.fail_after(timeout):
            while True:
                message = await socket._send_rx.receive()
                socket._raise_on_close(message)
                event = json.loads(message["text"])
                if event["type"] == event_type:
                    return event

    return socket.portal.call(receive)


def _receive_nowait(socket):
    def receive():
        try:
            message = socket._send_rx.receive_nowait()
        except anyio.WouldBlock:
            return None
        socket._raise_on_close(message)
        return json.loads(message["text"])

    return socket.portal.call(receive)


@contextmanager
def _server_closed_socket_context(session):
    socket = session.__enter__()
    try:
        yield socket
    except BaseException:
        try:
            session.__exit__(*sys.exc_info())
        except FutureCancelledError:
            if not getattr(socket, "_server_closed", False):
                raise
        raise
    else:
        try:
            session.__exit__(None, None, None)
        except FutureCancelledError:
            # Starlette's TestClient cancels its portal runner after the ASGI app
            # already returned on a server-initiated close; no app task is left.
            if not getattr(socket, "_server_closed", False):
                raise
