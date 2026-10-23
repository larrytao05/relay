"""WS-06 presence and cursor integration tests; requires an isolated database."""

import asyncio
import json
import os
import unittest
from datetime import UTC, datetime
from uuid import UUID, uuid4

import anyio
import asyncpg
from fastapi.testclient import TestClient

from app import db
from app.auth import hash_session_token
from app.main import app


@unittest.skipUnless(os.environ.get("TEST_DATABASE_URL"), "requires TEST_DATABASE_URL")
class CanvasPresencePostgresTests(unittest.TestCase):
    def test_join_cursor_hiding_latest_cursor_and_canvas_isolation(self):
        with self._seeded_board() as board, TestClient(app) as client:
            client.cookies.set("session", board["token"])
            headers = {"origin": "http://localhost:5173"}
            with client.websocket_connect(
                f"/ws/canvases/{board['canvas_id']}", headers=headers
            ) as first:
                first_snapshot = _receive_json(first)
                first_id = first_snapshot["connection_id"]

                with client.websocket_connect(
                    f"/ws/canvases/{board['canvas_id']}", headers=headers
                ) as second:
                    second_snapshot = _receive_json(second)
                    second_id = second_snapshot["connection_id"]
                    self.assertEqual(
                        second_snapshot["connections"],
                        [
                            {
                                "connection_id": first_id,
                                "user": {
                                    "id": str(board["user_id"]),
                                    "username": board["username"],
                                },
                                "cursor": None,
                            },
                            {
                                "connection_id": second_id,
                                "user": {
                                    "id": str(board["user_id"]),
                                    "username": board["username"],
                                },
                                "cursor": None,
                            },
                        ],
                    )
                    self.assertEqual(
                        _receive_json(first),
                        {
                            "type": "presence.joined",
                            "connection_id": second_id,
                            "user": {
                                "id": str(board["user_id"]),
                                "username": board["username"],
                            },
                        },
                    )

                    first.send_json({"type": "cursor", "position": {"x": 12, "y": 18}})
                    self.assertEqual(
                        _receive_json(second),
                        {
                            "type": "cursor",
                            "connection_id": first_id,
                            "user_id": str(board["user_id"]),
                            "position": {"x": 12.0, "y": 18.0},
                        },
                    )

                    with client.websocket_connect(
                        f"/ws/canvases/{board['canvas_id']}", headers=headers
                    ) as later:
                        later_snapshot = _receive_json(later)
                        later_connections = {
                            item["connection_id"]: item
                            for item in later_snapshot["connections"]
                        }
                        self.assertEqual(
                            later_connections[first_id]["cursor"],
                            {"x": 12.0, "y": 18.0},
                        )
                        first_joined = _receive_json(first)
                        second_joined = _receive_json(second)
                        self.assertEqual(first_joined["type"], "presence.joined")
                        self.assertEqual(second_joined["type"], "presence.joined")
                        self.assertEqual(
                            first_joined["connection_id"],
                            later_snapshot["connection_id"],
                        )
                        self.assertEqual(
                            second_joined["connection_id"],
                            later_snapshot["connection_id"],
                        )

                        first.send_json({"type": "cursor", "position": None})
                        expected_hidden = {
                            "type": "cursor",
                            "connection_id": first_id,
                            "user_id": str(board["user_id"]),
                            "position": None,
                        }
                        self.assertEqual(_receive_json(second), expected_hidden)
                        self.assertEqual(_receive_json(later), expected_hidden)

                        first.send_json(
                            {"type": "cursor", "position": {"x": 7, "y": 9}}
                        )
                        self.assertEqual(
                            _receive_json(second)["position"], {"x": 7.0, "y": 9.0}
                        )
                        self.assertEqual(
                            _receive_json(later)["position"], {"x": 7.0, "y": 9.0}
                        )

                    # The later tab's disconnect is reported to the still-active peers.
                    self.assertEqual(_receive_json(first)["type"], "presence.left")
                    self.assertEqual(_receive_json(second)["type"], "presence.left")

                    with client.websocket_connect(
                        f"/ws/canvases/{board['other_canvas_id']}", headers=headers
                    ) as other_canvas:
                        other_snapshot = _receive_json(other_canvas)
                        self.assertEqual(len(other_snapshot["connections"]), 1)
                        room = client.app.state.canvas_rooms._rooms[board["canvas_id"]]
                        before = {
                            key: item.outbound.qsize()
                            for key, item in room.connections.items()
                        }
                        other_canvas.send_json(
                            {"type": "cursor", "position": {"x": 1, "y": 2}}
                        )
                        self.assertEqual(
                            {
                                key: item.outbound.qsize()
                                for key, item in room.connections.items()
                            },
                            before,
                        )

            self.assertEqual(
                self._database_state(board["database_url"], board),
                board["initial_state"],
            )

    def test_same_user_tabs_leave_once_and_only_remove_the_disconnected_tab(self):
        with self._seeded_board() as board, TestClient(app) as client:
            client.cookies.set("session", board["token"])
            headers = {"origin": "http://localhost:5173"}
            with client.websocket_connect(
                f"/ws/canvases/{board['canvas_id']}", headers=headers
            ) as first:
                first_snapshot = _receive_json(first)
                first_id = first_snapshot["connection_id"]
                with client.websocket_connect(
                    f"/ws/canvases/{board['canvas_id']}", headers=headers
                ) as second:
                    second_snapshot = _receive_json(second)
                    second_id = second_snapshot["connection_id"]
                    self.assertEqual(_receive_json(first)["type"], "presence.joined")
                left = _receive_json(first)
                self.assertEqual(
                    left,
                    {"type": "presence.left", "connection_id": second_id},
                )
                first.send_json({"type": "cursor", "position": {"x": 2, "y": 3}})
                first.send_text("not-json")
                self.assertEqual(_receive_json(first)["code"], "invalid_message")
                # A still-usable single tab updates its own latest cursor for a future snapshot.
                room = client.app.state.canvas_rooms._rooms[board["canvas_id"]]
                self.assertEqual(len(room.connections), 1)
                self.assertIn(UUID(first_id), room.connections)
                self.assertNotIn(UUID(second_id), room.connections)
                self.assertEqual(
                    room.connections[UUID(first_id)].cursor,
                    {"x": 2.0, "y": 3.0},
                )
                self.assertEqual(
                    second_snapshot["connections"][0]["connection_id"], first_id
                )
            self.assertEqual(
                self._database_state(board["database_url"], board),
                board["initial_state"],
            )

    def _seeded_board(self):
        database_url = os.environ["TEST_DATABASE_URL"]
        previous_database_url = db.DATABASE_URL
        db.DATABASE_URL = database_url
        suffix = uuid4().hex
        username = f"ws06_{suffix[:20]}"
        token = f"session-{suffix}"
        user_id, canvas_id, other_canvas_id = uuid4(), uuid4(), uuid4()

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
                    "INSERT INTO canvas (id, title, created_by, revision) VALUES ($1, 'WS06 presence', $2, 4)",
                    canvas_id,
                    user_id,
                )
                await conn.execute(
                    "INSERT INTO canvas_member (canvas_id, user_id) VALUES ($1, $2)",
                    canvas_id,
                    user_id,
                )
                await conn.execute(
                    "INSERT INTO canvas (id, title, created_by, revision) VALUES ($1, 'WS06 other', $2, 2)",
                    other_canvas_id,
                    user_id,
                )
                await conn.execute(
                    "INSERT INTO canvas_member (canvas_id, user_id) VALUES ($1, $2)",
                    other_canvas_id,
                    user_id,
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
        }
        board["initial_state"] = self._database_state(database_url, board)
        return _BoardContext(board)

    @staticmethod
    def _database_state(database_url, board):
        async def read():
            conn = await asyncpg.connect(database_url)
            try:
                return await conn.fetchrow(
                    """
                    SELECT
                      (SELECT count(*) FROM shape WHERE canvas_id = $1 OR canvas_id = $2) AS shapes,
                      (SELECT count(*) FROM canvas_operation WHERE canvas_id = $1 OR canvas_id = $2) AS operations,
                      (SELECT sum(revision) FROM canvas WHERE id = ANY($3::uuid[])) AS revisions
                    """,
                    board["canvas_id"],
                    board["other_canvas_id"],
                    [board["canvas_id"], board["other_canvas_id"]],
                )
            finally:
                await conn.close()

        return asyncio.run(read())


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
                "DELETE FROM app_user WHERE id = $1", self.board["user_id"]
            )
        finally:
            await conn.close()


class PresenceTransportCleanupTests(unittest.IsolatedAsyncioTestCase):
    async def test_sender_failure_detaches_once_and_notifies_healthy_peer(self):
        from app.auth import PublicUser
        from app.canvas_ws import CanvasRooms, Connection, Room, SessionIdentity

        rooms = CanvasRooms()
        canvas_id = uuid4()
        room = Room()
        rooms._rooms[canvas_id] = room
        identity = SessionIdentity(
            "digest", PublicUser(id=uuid4(), username="tester"), datetime.now(UTC)
        )
        failed_socket = _FailedSendSocket()
        healthy_socket = _RecordingSocket()
        failed = Connection(
            uuid4(), canvas_id, identity, failed_socket, asyncio.Queue()
        )
        healthy = Connection(
            uuid4(), canvas_id, identity, healthy_socket, asyncio.Queue()
        )
        room.connections = {failed.id: failed, healthy.id: healthy}
        failed.sender_task = asyncio.create_task(rooms._guarded_send_loop(failed))
        healthy.sender_task = asyncio.create_task(rooms._guarded_send_loop(healthy))
        failed.outbound.put_nowait({"type": "trigger"})
        try:
            with self.assertLogs("app.canvas_ws", level="ERROR"):
                event = await asyncio.wait_for(healthy_socket.received.get(), timeout=1)
            self.assertEqual(
                event,
                {"type": "presence.left", "connection_id": str(failed.id)},
            )
            self.assertTrue(failed.detached)
            self.assertNotIn(failed.id, room.connections)
            async with room.lock:
                self.assertFalse(rooms._detach_locked(room, failed))
            self.assertTrue(
                healthy.sender_task is not None and not healthy.sender_task.done()
            )
        finally:
            healthy.sender_task.cancel()
            await asyncio.gather(healthy.sender_task, return_exceptions=True)


class _FailedSendSocket:
    async def send_json(self, _message):
        raise OSError("transport closed")

    async def close(self, code=1000):
        pass


class _RecordingSocket:
    def __init__(self):
        self.received = asyncio.Queue()

    async def send_json(self, message):
        await self.received.put(message)

    async def close(self, _code=1000):
        pass


def _receive_json(socket, timeout=2):
    async def receive():
        with anyio.fail_after(timeout):
            return await socket._send_rx.receive()

    message = socket.portal.call(receive)
    if message["type"] == "websocket.disconnect":
        socket._raise_on_close(message)
    return json.loads(message["text"])
