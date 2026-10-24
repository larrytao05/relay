import asyncio
import json
import os
import socket
import subprocess
import sys
import time
import unittest
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch
from urllib.request import Request, urlopen
from uuid import uuid4

import asyncpg
import test_canvas_create as create_helpers
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from websockets.sync.client import connect as websocket_connect

from app.auth import PublicUser
from app.canvas_operation_listener import CanvasOperationListener
from app.canvas_ws import (
    CanvasRooms,
    Connection,
    Room,
    SessionIdentity,
)
from app.canvas_ws import (
    router as canvas_ws_router,
)


class CanvasOperationListenerTests(unittest.IsolatedAsyncioTestCase):
    async def test_concurrent_sockets_share_one_listener_and_idle_grace_closes_it(self):
        connection = _ListenerConnection()
        connected = asyncio.Event()
        listener = CanvasOperationListener(
            lambda _payload: asyncio.sleep(0),
            lambda: _set(connected),
            idle_grace=0.01,
        )
        with patch(
            "app.canvas_operation_listener.asyncpg.connect", return_value=connection
        ) as connect:
            await asyncio.gather(listener.acquire(), listener.acquire())
            self.assertEqual(connect.await_count, 1)
            self.assertTrue(connected.is_set())

            await listener.release()
            await listener.release()
            await asyncio.wait_for(connection.closed.wait(), timeout=1)
            await listener.close()

    async def test_listener_reconnect_runs_journal_reconciliation_again(self):
        connections = [_ListenerConnection(), _ListenerConnection()]
        reconnects = 0
        reconnected = asyncio.Event()

        async def reconcile():
            nonlocal reconnects
            reconnects += 1
            if reconnects == 2:
                reconnected.set()

        listener = CanvasOperationListener(
            lambda _payload: asyncio.sleep(0), reconcile, idle_grace=1
        )
        with patch(
            "app.canvas_operation_listener.asyncpg.connect",
            side_effect=connections,
        ):
            await listener.acquire()
            await asyncio.wait_for(connections[0].ready.wait(), timeout=1)
            connections[0].terminate()
            await asyncio.wait_for(reconnected.wait(), timeout=2)
            await listener.close()

    async def test_notification_payload_reaches_the_process_callback(self):
        connection = _ListenerConnection()
        received = asyncio.Queue()
        listener = CanvasOperationListener(
            received.put, lambda: asyncio.sleep(0), idle_grace=1
        )
        with patch(
            "app.canvas_operation_listener.asyncpg.connect", return_value=connection
        ):
            await listener.acquire()
            connection.notify('{"canvas_id":"canvas","revision":2}')
            self.assertEqual(
                await asyncio.wait_for(received.get(), timeout=1),
                '{"canvas_id":"canvas","revision":2}',
            )
            await listener.close()

    async def test_join_receives_snapshot_then_each_journal_event_once(self):
        rooms = CanvasRooms()
        canvas_id = uuid4()
        connection = _connection(canvas_id)
        room = Room(connections={connection.id: connection})
        snapshot = {"type": "snapshot", "canvas_revision": 0}
        connection.outbound.put_nowait(snapshot)
        events = [
            {"type": "operation.applied", "canvas_revision": revision}
            for revision in (1, 2)
        ]
        rows = [
            {"canvas_revision": event["canvas_revision"], "result": event}
            for event in events
        ]

        async def journal(_canvas_id, after_revision):
            return [row for row in rows if row["canvas_revision"] > after_revision]

        with patch.object(
            rooms, "_operation_rows", side_effect=journal
        ) as operation_rows:
            await rooms._catch_up_admission(room, connection, snapshot)
            await rooms._catch_up_room(canvas_id, room)

        self.assertEqual(
            [connection.outbound.get_nowait() for _ in range(3)],
            [snapshot, *events],
        )
        self.assertEqual(operation_rows.await_args_list[0].args, (canvas_id, 0))
        self.assertEqual(operation_rows.await_args_list[1].args, (canvas_id, 2))
        await rooms.close()

    async def test_local_commit_replays_any_earlier_remote_revision_first(self):
        rooms = CanvasRooms()
        canvas_id = uuid4()
        connection = _connection(canvas_id)
        connection.socket = _SingleCommandSocket(
            {
                "type": "shape.create",
                "operation_id": str(uuid4()),
                "shape_id": str(uuid4()),
                "kind": "rectangle",
                "properties": {
                    "x": 0,
                    "y": 0,
                    "width": 20,
                    "height": 20,
                    "color": "#112233",
                    "opacity": 1,
                    "z_index": 0,
                },
            }
        )
        room = Room(connections={connection.id: connection}, revision=0)
        remote = {"type": "operation.applied", "canvas_revision": 1}
        local = {"type": "operation.applied", "canvas_revision": 2}
        rows = [
            {"canvas_revision": 1, "result": remote},
            {"canvas_revision": 2, "result": local},
        ]

        async def journal(_canvas_id, after_revision):
            return [row for row in rows if row["canvas_revision"] > after_revision]

        with (
            patch.object(
                rooms, "_connection_access_valid", AsyncMock(return_value=True)
            ),
            patch.object(
                rooms,
                "_apply_shape_command",
                AsyncMock(return_value=(local, True)),
            ),
            patch.object(rooms, "_operation_rows", side_effect=journal),
            self.assertRaises(WebSocketDisconnect),
        ):
            await rooms._receive_loop(connection, room)

        self.assertEqual(
            [connection.outbound.get_nowait(), connection.outbound.get_nowait()],
            [remote, local],
        )
        self.assertEqual(room.revision, 2)
        await rooms.close()

    async def test_duplicate_notification_does_not_redeliver_a_committed_event(self):
        rooms = CanvasRooms()
        canvas_id = uuid4()
        connection = _connection(canvas_id)
        room = Room(connections={connection.id: connection}, revision=0)
        rooms._rooms[canvas_id] = room
        event = {"type": "operation.applied", "canvas_revision": 1}

        async def journal(_canvas_id, after_revision):
            if after_revision == 0:
                return [{"canvas_revision": 1, "result": event}]
            return []

        with patch.object(rooms, "_operation_rows", side_effect=journal):
            payload = f'{{"canvas_id":"{canvas_id}","revision":1}}'
            await rooms._on_operation_notification(payload)
            await rooms._on_operation_notification(payload)

        self.assertEqual(connection.outbound.get_nowait(), event)
        self.assertTrue(connection.outbound.empty())
        await rooms.close()


async def _set(event):
    event.set()


class _ListenerConnection:
    def __init__(self):
        self.closed = asyncio.Event()
        self.ready = asyncio.Event()
        self._listener = None
        self._terminated = None
        self._closed = False

    def add_termination_listener(self, callback):
        self._terminated = callback

    async def add_listener(self, _channel, callback):
        self._listener = callback
        self.ready.set()

    def notify(self, payload):
        self._listener(self, 1, "canvas_operations", payload)

    def terminate(self):
        self._closed = True
        self.closed.set()
        self._terminated(self)

    def is_closed(self):
        return self._closed

    async def close(self):
        self.terminate()


@unittest.skipUnless(os.environ.get("TEST_DATABASE_URL"), "requires TEST_DATABASE_URL")
class CanvasCrossInstancePostgresTests(unittest.TestCase):
    def test_independent_backend_instances_deliver_committed_edits(self):
        with create_helpers.CanvasCreatePostgresTests()._board() as board:
            first = _websocket_app(board["url"])
            second = _websocket_app(board["url"])
            with (
                patch(
                    "app.canvas_operation_listener.get_listener_database_url",
                    return_value=board["url"],
                ),
                TestClient(first) as client_a,
                TestClient(second) as client_b,
                create_helpers.CanvasCreatePostgresTests()._socket(
                    client_a, board, "token_a"
                ) as socket_a,
                create_helpers.CanvasCreatePostgresTests()._socket(
                    client_b, board, "token_b"
                ) as socket_b,
            ):
                self.assertEqual(
                    create_helpers._receive_json(socket_a)["type"], "snapshot"
                )
                self.assertEqual(
                    create_helpers._receive_json(socket_b)["type"], "snapshot"
                )
                operation_id, shape_id = uuid4(), uuid4()
                socket_a.send_json(
                    create_helpers._create(
                        operation_id,
                        shape_id,
                        "rectangle",
                        create_helpers._shape_cases()[0][1],
                    )
                )
                event_a = create_helpers._receive_json(socket_a)
                event_b = create_helpers._receive_json(socket_b)
                self.assertEqual(event_a, event_b)
                self.assertEqual(event_b["canvas_revision"], 1)

    def test_two_backend_processes_deliver_committed_edits_in_order(self):
        with create_helpers.CanvasCreatePostgresTests()._board() as board:
            process_a, url_a = _start_backend(board["url"])
            process_b, url_b = _start_backend(board["url"])
            try:
                _wait_for_backend(process_a, url_a)
                _wait_for_backend(process_b, url_b)
                with (
                    websocket_connect(
                        _websocket_url(url_a, board["canvas_id"]),
                        origin="http://localhost:5173",
                        additional_headers={"Cookie": f"session={board['token_a']}"},
                    ) as socket_a,
                    websocket_connect(
                        _websocket_url(url_b, board["canvas_id"]),
                        origin="http://localhost:5173",
                        additional_headers={"Cookie": f"session={board['token_b']}"},
                    ) as socket_b,
                ):
                    self.assertEqual(
                        _receive_process_json(socket_a)["type"], "snapshot"
                    )
                    self.assertEqual(
                        _receive_process_json(socket_b)["type"], "snapshot"
                    )
                    shape_properties = create_helpers._shape_cases()[0][1]
                    for index in range(2):
                        socket_a.send(
                            json.dumps(
                                create_helpers._create(
                                    uuid4(), uuid4(), "rectangle", shape_properties
                                )
                            )
                        )
                    events_a = _receive_process_operations(socket_a, 2)
                    events_b = _receive_process_operations(socket_b, 2)
                    self.assertEqual(events_a, events_b)
                    self.assertEqual(
                        [event["canvas_revision"] for event in events_a], [1, 2]
                    )
            finally:
                _stop_backend(process_a)
                _stop_backend(process_b)

    def test_join_during_edit_gets_coherent_snapshot_then_ordered_operations(self):
        with create_helpers.CanvasCreatePostgresTests()._board() as board:
            process_a, url_a = _start_backend(board["url"])
            process_b, url_b = _start_backend(board["url"], "snapshot_probe_app:app")
            try:
                _wait_for_backend(process_a, url_a)
                _wait_for_backend(process_b, url_b)
                with websocket_connect(
                    _websocket_url(url_a, board["canvas_id"]),
                    origin="http://localhost:5173",
                    additional_headers={"Cookie": f"session={board['token_a']}"},
                ) as editor:
                    self.assertEqual(_receive_process_json(editor)["type"], "snapshot")
                    try:
                        with websocket_connect(
                            _websocket_url(url_b, board["canvas_id"]),
                            origin="http://localhost:5173",
                            additional_headers={
                                "Cookie": f"session={board['token_b']}"
                            },
                        ) as joiner:
                            with urlopen(
                                f"{url_b}/_test/snapshot-paused", timeout=15
                            ) as response:
                                self.assertEqual(response.status, 200)

                            shape_id = uuid4()
                            properties = create_helpers._shape_cases()[0][1]
                            editor.send(
                                json.dumps(
                                    create_helpers._create(
                                        uuid4(), shape_id, "rectangle", properties
                                    )
                                )
                            )
                            first_event = _receive_process_json(editor)
                            self.assertEqual(first_event["canvas_revision"], 1)

                            with urlopen(
                                Request(
                                    f"{url_b}/_test/release-snapshot", method="POST"
                                ),
                                timeout=5,
                            ) as response:
                                self.assertEqual(response.status, 200)

                            snapshot = _receive_process_json(joiner)
                            self.assertEqual(snapshot["type"], "snapshot")
                            self.assertEqual(snapshot["canvas_revision"], 0)
                            self.assertNotIn(
                                str(shape_id),
                                {shape["id"] for shape in snapshot["shapes"]},
                            )

                            editor.send(
                                json.dumps(
                                    {
                                        "type": "shape.update",
                                        "operation_id": str(uuid4()),
                                        "shape_id": str(shape_id),
                                        "expected_revision": 1,
                                        "patch": {"x": properties["x"] + 1},
                                    }
                                )
                            )
                            second_event = _receive_process_json(editor)
                            self.assertEqual(second_event["canvas_revision"], 2)
                            events = _receive_process_operations(joiner, 2)
                            self.assertEqual(events, [first_event, second_event])
                            self.assertEqual(
                                [event["canvas_revision"] for event in events], [1, 2]
                            )
                    finally:
                        _release_snapshot_probe(url_b)
            finally:
                _stop_backend(process_a)
                _stop_backend(process_b)


def _websocket_app(database_url):
    @asynccontextmanager
    async def lifespan(app):
        pool = await asyncpg.create_pool(database_url)
        rooms = CanvasRooms(pool=pool)
        app.state.canvas_rooms = rooms
        try:
            yield
        finally:
            await rooms.close()
            await pool.close()

    app = FastAPI(lifespan=lifespan)
    app.include_router(canvas_ws_router)
    return app


def _start_backend(database_url, app_module="app.main:app"):
    server_dir = os.path.dirname(os.path.dirname(__file__))
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    env = os.environ.copy()
    env["DATABASE_URL"] = database_url
    env["DATABASE_LISTENER_URL"] = database_url
    env["PYTHONPATH"] = os.pathsep.join(
        [os.path.join(server_dir, "tests"), server_dir, env.get("PYTHONPATH", "")]
    )
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            app_module,
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--workers",
            "1",
        ],
        cwd=server_dir,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return process, f"http://127.0.0.1:{port}"


def _release_snapshot_probe(base_url):
    try:
        with urlopen(
            Request(f"{base_url}/_test/release-snapshot", method="POST"), timeout=2
        ):
            pass
    except OSError:
        pass


def _wait_for_backend(process, base_url):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise AssertionError("backend process exited before becoming ready")
        try:
            with urlopen(f"{base_url}/health", timeout=0.5) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(0.05)
    raise AssertionError("backend process did not become ready")


def _websocket_url(base_url, canvas_id):
    return f"ws://{base_url.removeprefix('http://')}/ws/canvases/{canvas_id}"


def _receive_process_json(websocket):
    return json.loads(websocket.recv(timeout=5))


def _receive_process_operations(websocket, count):
    events = []
    deadline = time.monotonic() + 10
    while len(events) < count and time.monotonic() < deadline:
        event = _receive_process_json(websocket)
        if event.get("type") == "operation.applied":
            events.append(event)
    if len(events) != count:
        raise AssertionError(f"expected {count} operations, received {len(events)}")
    return events


def _stop_backend(process):
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _connection(canvas_id):
    return Connection(
        id=uuid4(),
        canvas_id=canvas_id,
        identity=SessionIdentity(
            "session",
            PublicUser(id=uuid4(), username="collaborator"),
            datetime.now(UTC) + timedelta(hours=1),
        ),
        socket=_NoopSocket(),
        outbound=asyncio.Queue(),
    )


class _NoopSocket:
    async def close(self, code=1000):
        pass


class _SingleCommandSocket(_NoopSocket):
    def __init__(self, command):
        self.command = command
        self.received = False

    async def receive_text(self):
        if self.received:
            raise WebSocketDisconnect()
        self.received = True
        return json.dumps(self.command)
