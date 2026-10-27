"""WS-04 create command integration tests; requires a dedicated PostgreSQL DB."""

import asyncio
import json
import os
import threading
import unittest
from uuid import uuid4

import anyio
import asyncpg
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app import db
from app.auth import hash_session_token
from app.main import app


@unittest.skipUnless(os.environ.get("TEST_DATABASE_URL"), "requires TEST_DATABASE_URL")
class CanvasCreatePostgresTests(unittest.TestCase):
    def test_each_shape_kind_is_saved_and_broadcast_to_two_members_and_reconnects(self):
        for kind, properties in _shape_cases():
            with (
                self.subTest(kind=kind),
                self._board() as board,
                TestClient(app) as client,
            ):
                with self._socket(client, board, "token_a") as alice:
                    self.assertEqual(_receive_json(alice)["type"], "snapshot")
                    with self._socket(client, board, "token_b") as bob:
                        self.assertEqual(_receive_json(bob)["type"], "snapshot")
                        operation_id, shape_id = uuid4(), uuid4()
                        alice.send_json(
                            _create(operation_id, shape_id, kind, properties)
                        )
                        event_a = _receive_json(alice)
                        event_b = _receive_json(bob)
                        self.assertEqual(event_a, event_b)
                        self.assertEqual(event_a["type"], "operation.applied")
                        self.assertEqual(event_a["canvas_revision"], 1)
                        self.assertEqual(event_a["shape"]["revision"], 1)
                        self.assertEqual(event_a["shape"]["properties"], properties)
                        self.assertEqual(
                            asyncio.run(self._state(board, operation_id)),
                            (1, 1, 1),
                        )
                        durable = awaitable_result(self._operation(board, operation_id))
                        self.assertEqual(durable["canvas_revision"], 1)
                        self.assertEqual(durable["shape_id"], shape_id)
                        self.assertEqual(
                            json.loads(durable["request"]),
                            command_for(operation_id, shape_id, kind, properties),
                        )
                        self.assertEqual(json.loads(durable["result"]), event_a)
                        self.assertEqual(
                            json.loads(durable["after_patch"]),
                            {
                                "kind": kind,
                                "properties": event_a["shape"]["properties"],
                            },
                        )
                with self._socket(client, board, "token_a") as resumed:
                    snapshot = _receive_json(resumed)
                    self.assertEqual(snapshot["canvas_revision"], 1)
                    self.assertIn(
                        str(shape_id), {shape["id"] for shape in snapshot["shapes"]}
                    )

    def test_exact_retry_only_acks_requester_and_reuse_is_rejected(self):
        with self._board() as board, TestClient(app) as client:  # noqa: SIM117
            with self._socket(client, board, "token_a") as alice:
                _receive_json(alice)
                with self._socket(client, board, "token_b") as bob:
                    _receive_json(bob)
                    op_id, shape_id = uuid4(), uuid4()
                    command = _create(
                        op_id, shape_id, "rectangle", _shape_cases()[0][1]
                    )
                    alice.send_json(command)
                    original = _receive_json(alice)
                    _receive_json(bob)
                    alice.send_json(command)
                    self.assertEqual(_receive_json(alice), original)
                    self.assertEqual(
                        awaitable_result(self._state(board, op_id)), (1, 1, 1)
                    )

                    changed = dict(
                        command, properties=dict(command["properties"], x=99)
                    )
                    alice.send_json(changed)
                    self.assertEqual(
                        _receive_json(alice)["code"], "operation_id_reused"
                    )
                    self.assertIsNone(_receive_nowait_json(bob))
                    self.assertEqual(
                        awaitable_result(self._state(board, op_id)), (1, 1, 1)
                    )

                    bob.send_json(command)
                    self.assertEqual(_receive_json(bob)["code"], "operation_id_reused")
                    self.assertEqual(
                        awaitable_result(self._state(board, op_id)), (1, 1, 1)
                    )

    def test_legacy_line_create_retry_defaults_missing_arrow_flags(self):
        with (
            self._board() as board,
            TestClient(app) as client,
            self._socket(client, board, "token_a") as socket,
        ):
            _receive_json(socket)
            operation_id, shape_id = uuid4(), uuid4()
            properties = {
                "x1": 1,
                "y1": 2,
                "x2": 30,
                "y2": 40,
                "color": "#112233",
                "start_arrow": False,
                "end_arrow": False,
            }
            command = _create(operation_id, shape_id, "line", properties)
            socket.send_json(command)
            original = _receive_json(socket)
            asyncio.run(
                self._remove_line_arrows_from_saved_request(board, operation_id)
            )
            socket.send_json(command)
            self.assertEqual(_receive_json(socket), original)
            changed = {**command, "properties": {**properties, "end_arrow": True}}
            socket.send_json(changed)
            self.assertEqual(_receive_json(socket)["code"], "operation_id_reused")

    def test_shape_id_reuse_does_not_advance_canvas_or_emit(self):
        with self._board() as board, TestClient(app) as client:  # noqa: SIM117
            with self._socket(client, board, "token_a") as socket:
                _receive_json(socket)
                shape_id = board["reserved_shape_id"]
                socket.send_json(
                    _create(uuid4(), shape_id, "rectangle", _shape_cases()[0][1])
                )
                self.assertEqual(_receive_json(socket)["code"], "shape_unavailable")
                self.assertEqual(awaitable_result(self._state(board)), (0, 0, 0))

    def test_legacy_operation_id_cannot_be_replayed(self):
        with self._board() as board, TestClient(app) as client:
            operation_id = uuid4()
            asyncio.run(self._insert_legacy_operation(board, operation_id))
            with self._socket(client, board, "token_a") as socket:
                _receive_json(socket)
                socket.send_json(
                    _create(
                        operation_id,
                        uuid4(),
                        "rectangle",
                        _shape_cases()[0][1],
                    )
                )
                self.assertEqual(_receive_json(socket)["code"], "operation_id_reused")
                self.assertEqual(awaitable_result(self._state(board)), (0, 0, 1))

    def test_journal_failure_rolls_back_and_socket_accepts_following_command(self):
        with self._board() as board, TestClient(app) as client:
            asyncio.run(self._install_failing_operation_trigger(board))
            self.addCleanup(
                lambda: asyncio.run(self._remove_failing_operation_trigger(board))
            )
            with self._socket(client, board, "token_a") as socket:
                _receive_json(socket)
                with self._socket(client, board, "token_b") as peer:
                    _receive_json(peer)
                    socket.send_json(
                        _create(uuid4(), uuid4(), "rectangle", _shape_cases()[0][1])
                    )
                    self.assertEqual(_receive_json(socket)["code"], "operation_failed")
                    self.assertEqual(awaitable_result(self._state(board)), (0, 0, 0))
                    asyncio.run(self._remove_failing_operation_trigger(board))
                    op_id = uuid4()
                    socket.send_json(
                        _create(op_id, uuid4(), "rectangle", _shape_cases()[0][1])
                    )
                    self.assertEqual(_receive_json(socket)["type"], "operation.applied")
                    self.assertEqual(_receive_json(peer)["operation_id"], str(op_id))
                    self.assertIsNone(_receive_nowait_json(peer))

    def test_operation_id_collision_across_canvases_has_one_winner(self):
        with self._board() as board, TestClient(app) as client:
            command_id = uuid4()
            outcomes = []
            ready = threading.Barrier(2)
            errors = []

            def issue(canvas_id):
                try:
                    with self._socket(client, board, "token_a", canvas_id) as socket:
                        _receive_json(socket)
                        ready.wait(timeout=2)
                        socket.send_json(
                            _create(
                                command_id, uuid4(), "rectangle", _shape_cases()[0][1]
                            )
                        )
                        outcomes.append(_receive_json(socket))
                except (
                    TimeoutError,
                    RuntimeError,
                    ValueError,
                    WebSocketDisconnect,
                ) as exc:
                    errors.append(exc)

            threads = [
                threading.Thread(target=issue, args=(board["canvas_id"],)),
                threading.Thread(target=issue, args=(board["other_canvas_id"],)),
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=5)
            self.assertFalse(any(thread.is_alive() for thread in threads))
            self.assertEqual(errors, [])
            self.assertEqual(
                sorted(item.get("type") for item in outcomes),
                ["error", "operation.applied"],
            )
            self.assertEqual(
                sum(item.get("code") == "operation_id_reused" for item in outcomes),
                1,
            )
            self.assertEqual(awaitable_result(self._count_op(board, command_id)), 1)

    def test_independent_creates_arrive_in_revision_order_on_each_peer(self):
        with self._board() as board, TestClient(app) as client:  # noqa: SIM117
            with self._socket(client, board, "token_a") as alice:
                _receive_json(alice)
                with self._socket(client, board, "token_b") as bob:
                    _receive_json(bob)
                    with self._socket(
                        client, board, "token_a", board["other_canvas_id"]
                    ) as other:
                        _receive_json(other)
                        gate = threading.Barrier(3)
                        failures = []

                        def send(socket, ident):
                            try:
                                gate.wait(timeout=2)
                                socket.send_json(
                                    _create(
                                        ident,
                                        uuid4(),
                                        "rectangle",
                                        _shape_cases()[0][1],
                                    )
                                )
                            except (
                                TimeoutError,
                                RuntimeError,
                                ValueError,
                                WebSocketDisconnect,
                            ) as exc:
                                failures.append(exc)

                        commands = [
                            threading.Thread(target=send, args=(alice, uuid4())),
                            threading.Thread(target=send, args=(bob, uuid4())),
                        ]
                        for thread in commands:
                            thread.start()
                        gate.wait(timeout=2)
                        for thread in commands:
                            thread.join(timeout=2)
                        self.assertEqual(failures, [])
                        a_events = [_receive_json(alice), _receive_json(alice)]
                        b_events = [_receive_json(bob), _receive_json(bob)]
                        self.assertEqual(a_events, b_events)
                        self.assertEqual(
                            [event["canvas_revision"] for event in a_events], [1, 2]
                        )
                        self.assertEqual(
                            awaitable_result(self._state(board)), (2, 2, 2)
                        )
                        other.send_json("not-json")
                        self.assertEqual(
                            _receive_json(other)["code"], "invalid_message"
                        )
                        self.assertIsNone(_receive_nowait_json(other))

    def _board(self):
        database_url = os.environ["TEST_DATABASE_URL"]
        previous_url = db.DATABASE_URL
        db.DATABASE_URL = database_url
        ids = [uuid4() for _ in range(5)]
        user_a, user_b, canvas, other_canvas, reserved = ids
        token_a, token_b = f"ws04-{uuid4().hex}", f"ws04-{uuid4().hex}"

        async def seed():
            conn = await asyncpg.connect(database_url)
            try:
                for user_id, username in (
                    (user_a, f"a_{user_a.hex}"),
                    (user_b, f"b_{user_b.hex}"),
                ):
                    await conn.execute(
                        "INSERT INTO app_user (id, username, password_hash) VALUES ($1, $2, 'test')",
                        user_id,
                        username,
                    )
                for token, user_id in ((token_a, user_a), (token_b, user_b)):
                    await conn.execute(
                        "INSERT INTO auth_session (token_hash, user_id, expires_at) VALUES ($1, $2, now() + interval '1 hour')",
                        hash_session_token(token),
                        user_id,
                    )
                for canvas_id in (canvas, other_canvas):
                    await conn.execute(
                        "INSERT INTO canvas (id, title, created_by) VALUES ($1, 'WS04', $2)",
                        canvas_id,
                        user_a,
                    )
                    await conn.execute(
                        "INSERT INTO canvas_member (canvas_id, user_id) VALUES ($1, $2), ($1, $3)",
                        canvas_id,
                        user_a,
                        user_b,
                    )
                await conn.execute(
                    "INSERT INTO shape (id, canvas_id, kind, properties) VALUES ($1, $2, 'rectangle', '{}'::jsonb)",
                    reserved,
                    canvas,
                )
            finally:
                await conn.close()

        asyncio.run(seed())
        return _Board(
            {
                "url": database_url,
                "previous_url": previous_url,
                "user_a": user_a,
                "user_b": user_b,
                "canvas_id": canvas,
                "other_canvas_id": other_canvas,
                "reserved_shape_id": reserved,
                "token_a": token_a,
                "token_b": token_b,
            }
        )

    @staticmethod
    def _socket(client, board, token_key, canvas_id=None):
        return client.websocket_connect(
            _ws(canvas_id or board["canvas_id"]),
            headers={
                "origin": "http://localhost:5173",
                "cookie": f"session={board[token_key]}",
            },
        )

    async def _state(self, board, operation_id=None):
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
            operations = (
                await conn.fetchval(
                    "SELECT count(*) FROM canvas_operation WHERE id=$1", operation_id
                )
                if operation_id
                else await conn.fetchval(
                    "SELECT count(*) FROM canvas_operation WHERE canvas_id=$1",
                    board["canvas_id"],
                )
            )
            return revision, shapes, operations
        finally:
            await conn.close()

    async def _count_op(self, board, operation_id):
        conn = await asyncpg.connect(board["url"])
        try:
            return await conn.fetchval(
                "SELECT count(*) FROM canvas_operation WHERE id=$1", operation_id
            )
        finally:
            await conn.close()

    async def _operation(self, board, operation_id):
        conn = await asyncpg.connect(board["url"])
        try:
            return await conn.fetchrow(
                "SELECT shape_id, canvas_revision, request, result, after_patch FROM canvas_operation WHERE id=$1",
                operation_id,
            )
        finally:
            await conn.close()

    async def _insert_legacy_operation(self, board, operation_id):
        conn = await asyncpg.connect(board["url"])
        try:
            await conn.execute(
                """INSERT INTO canvas_operation
                   (id, canvas_id, shape_id, actor_id, canvas_revision, kind)
                   VALUES ($1, $2, $3, $4, 1, 'create')""",
                operation_id,
                board["canvas_id"],
                board["reserved_shape_id"],
                board["user_a"],
            )
        finally:
            await conn.close()

    async def _remove_line_arrows_from_saved_request(self, board, operation_id):
        conn = await asyncpg.connect(board["url"])
        try:
            await conn.execute(
                """UPDATE canvas_operation
                   SET request = jsonb_set(request, '{properties}',
                     (request->'properties') - 'start_arrow' - 'end_arrow')
                   WHERE id=$1""",
                operation_id,
            )
        finally:
            await conn.close()

    async def _install_failing_operation_trigger(self, board):
        conn = await asyncpg.connect(board["url"])
        try:
            await conn.execute(
                "DROP TRIGGER IF EXISTS ws04_fail_op ON canvas_operation"
            )
            await conn.execute("DROP FUNCTION IF EXISTS ws04_fail_op()")
            await conn.execute(
                "CREATE FUNCTION ws04_fail_op() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'forced journal failure'; END $$"
            )
            await conn.execute(
                "CREATE TRIGGER ws04_fail_op BEFORE INSERT ON canvas_operation FOR EACH ROW EXECUTE FUNCTION ws04_fail_op()"
            )
        finally:
            await conn.close()

    async def _remove_failing_operation_trigger(self, board):
        conn = await asyncpg.connect(board["url"])
        try:
            await conn.execute(
                "DROP TRIGGER IF EXISTS ws04_fail_op ON canvas_operation"
            )
            await conn.execute("DROP FUNCTION IF EXISTS ws04_fail_op()")
        finally:
            await conn.close()


class _Board:
    def __init__(self, values):
        self.values = values

    def __enter__(self):
        return self.values

    def __exit__(self, *exc):
        async def cleanup():
            conn = await asyncpg.connect(self.values["url"])
            try:
                await conn.execute(
                    "DELETE FROM canvas WHERE id = ANY($1::uuid[])",
                    [self.values["canvas_id"], self.values["other_canvas_id"]],
                )
                await conn.execute(
                    "DELETE FROM app_user WHERE id = ANY($1::uuid[])",
                    [self.values["user_a"], self.values["user_b"]],
                )
            finally:
                await conn.close()

        asyncio.run(cleanup())
        db.DATABASE_URL = self.values["previous_url"]


def _ws(canvas_id):
    return f"/ws/canvases/{canvas_id}"


def _shape_cases():
    return [
        (
            "rectangle",
            {
                "x": 1,
                "y": 2,
                "width": 30,
                "height": 40,
                "color": "#112233",
                "opacity": 1,
                "z_index": 0,
            },
        ),
        (
            "ellipse",
            {
                "x": 1,
                "y": 2,
                "width": 30,
                "height": 40,
                "color": "#112233",
                "opacity": 1,
                "z_index": 0,
            },
        ),
        (
            "line",
            {
                "x1": 1,
                "y1": 2,
                "x2": 30,
                "y2": 40,
                "color": "#112233",
                "opacity": 1,
                "z_index": 0,
                "start_arrow": False,
                "end_arrow": False,
            },
        ),
        (
            "text",
            {
                "x": 1,
                "y": 2,
                "width": 30,
                "height": 40,
                "text": "hello",
                "font_size": 16,
                "color": "#112233",
                "opacity": 1,
                "z_index": 0,
            },
        ),
    ]


def _create(operation_id, shape_id, kind, properties):
    return {
        "type": "shape.create",
        "operation_id": str(operation_id),
        "shape_id": str(shape_id),
        "kind": kind,
        "properties": properties,
    }


def command_for(operation_id, shape_id, kind, properties):
    command = _create(operation_id, shape_id, kind, properties)
    for key in ("x", "y", "width", "height", "x1", "y1", "x2", "y2", "font_size"):
        if key in command["properties"]:
            command["properties"][key] = float(command["properties"][key])
    return command


def _receive_json(socket, timeout=2):
    # Editing tests consume durable results; presence has its own event assertions.
    async def receive():
        with anyio.fail_after(timeout):
            while True:
                message = await socket._send_rx.receive()
                socket._raise_on_close(message)
                event = json.loads(message["text"])
                if event["type"] not in {"presence.joined", "presence.left"}:
                    return event

    return socket.portal.call(receive)


def _receive_nowait_json(socket):
    def receive_nowait():
        while True:
            try:
                message = socket._send_rx.receive_nowait()
            except anyio.WouldBlock:
                return None
            socket._raise_on_close(message)
            event = json.loads(message["text"])
            if event["type"] not in {"presence.joined", "presence.left"}:
                return event

    return socket.portal.call(receive_nowait)


def awaitable_result(awaitable):
    return asyncio.run(awaitable)
