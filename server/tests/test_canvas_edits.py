"""WS-05 update/delete integration tests against a dedicated PostgreSQL DB."""

import json
import os
import threading
import unittest
from uuid import uuid4

import asyncpg
import test_canvas_create as create_helpers
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.main import app


@unittest.skipUnless(os.environ.get("TEST_DATABASE_URL"), "requires TEST_DATABASE_URL")
class CanvasEditPostgresTests(unittest.TestCase):
    def setUp(self):
        self.fixtures = create_helpers.CanvasCreatePostgresTests()

    def test_partial_update_merges_and_broadcasts_then_replay_is_immutable(self):
        with self.fixtures._board() as board, TestClient(app) as client:
            shape_id = self._create_shape(client, board)
            with self.fixtures._socket(client, board, "token_a") as alice:
                create_helpers._receive_json(alice)
                with self.fixtures._socket(client, board, "token_b") as bob:
                    create_helpers._receive_json(bob)
                    op = uuid4()
                    request = _update(op, shape_id, 1, {"x": 77})
                    alice.send_json(request)
                    ack = create_helpers._receive_json(alice)
                    self.assertEqual(ack["type"], "operation.applied")
                    self.assertEqual(ack, create_helpers._receive_json(bob))
                    self.assertEqual(ack["kind"], "update")
                    self.assertEqual(ack["shape"]["revision"], 2)
                    self.assertEqual(ack["shape"]["properties"]["x"], 77)
                    self.assertEqual(ack["shape"]["properties"]["y"], 2)
                    self.assertEqual(
                        create_helpers.awaitable_result(self.fixtures._state(board)),
                        (2, 1, 2),
                    )
                    journal = create_helpers.awaitable_result(
                        self._operation(board, op)
                    )
                    self.assertEqual(json.loads(journal["request"]), request)
                    self.assertEqual(json.loads(journal["result"]), ack)
                    self.assertEqual(json.loads(journal["before_patch"]), {"x": 1.0})
                    self.assertEqual(json.loads(journal["after_patch"]), {"x": 77.0})

                    same_value = uuid4()
                    alice.send_json(_update(same_value, shape_id, 2, {"x": 77}))
                    same_ack = create_helpers._receive_json(alice)
                    self.assertEqual(same_ack, create_helpers._receive_json(bob))
                    self.assertEqual(same_ack["shape"]["revision"], 3)

                    later = uuid4()
                    alice.send_json(_update(later, shape_id, 3, {"color": "#AABBCC"}))
                    latest = create_helpers._receive_json(alice)
                    create_helpers._receive_json(bob)
                    alice.send_json(request)
                    self.assertEqual(create_helpers._receive_json(alice), ack)
                    self.assertIsNone(create_helpers._receive_nowait_json(bob))
                    self.assertEqual(
                        create_helpers.awaitable_result(self.fixtures._state(board)),
                        (4, 1, 4),
                    )
                    stored = create_helpers.awaitable_result(
                        self._shape(board, shape_id)
                    )
                    self.assertEqual(stored["revision"], 4)
                    self.assertEqual(
                        json.loads(stored["properties"])["color"], "#AABBCC"
                    )
                    self.assertEqual(latest["shape"]["revision"], 4)

    def test_delete_broadcasts_and_reconnect_hides_but_retains_journal(self):
        with self.fixtures._board() as board, TestClient(app) as client:
            shape_id = self._create_shape(client, board)
            with self.fixtures._socket(client, board, "token_a") as alice:
                create_helpers._receive_json(alice)
                with self.fixtures._socket(client, board, "token_b") as bob:
                    create_helpers._receive_json(bob)
                    op = uuid4()
                    alice.send_json(_delete(op, shape_id, 1))
                    deleted = create_helpers._receive_json(alice)
                    self.assertEqual(deleted["type"], "operation.applied")
                    self.assertEqual(deleted, create_helpers._receive_json(bob))
                    self.assertTrue(deleted["shape"]["deleted"])
                    self.assertEqual(deleted["shape"]["revision"], 2)
                    row = create_helpers.awaitable_result(self._shape(board, shape_id))
                    self.assertIsNotNone(row["deleted_at"])
                    self.assertEqual(
                        create_helpers.awaitable_result(self.fixtures._state(board)),
                        (2, 1, 2),
                    )
            with self.fixtures._socket(client, board, "token_a") as resumed:
                snapshot = create_helpers._receive_json(resumed)
                self.assertNotIn(
                    str(shape_id), {shape["id"] for shape in snapshot["shapes"]}
                )

    def test_refusals_do_not_mutate_and_socket_remains_usable(self):
        with self.fixtures._board() as board, TestClient(app) as client:
            shape_id = self._create_shape(client, board)
            foreign_id = self._create_shape(client, board, board["other_canvas_id"])
            with self.fixtures._socket(client, board, "token_a") as socket:
                create_helpers._receive_json(socket)
                failures = [
                    _update(uuid4(), shape_id, 1, {"x": -4, "width": -1}),
                    _update(uuid4(), uuid4(), 1, {"x": 7}),
                    _update(uuid4(), foreign_id, 1, {"x": 7}),
                    _update(uuid4(), shape_id, 999, {"x": 7}),
                ]
                for command in failures:
                    socket.send_json(command)
                    result = create_helpers._receive_json(socket)
                    self.assertEqual(result["type"], "error")
                    if command["patch"].get("width"):
                        self.assertEqual(result["code"], "invalid_patch")
                    elif command["expected_revision"] == 999:
                        self.assertEqual(result["code"], "conflict")
                        self.assertEqual(result["shape"]["revision"], 1)
                        self.assertFalse(result["shape"]["deleted"])
                    else:
                        self.assertEqual(result["code"], "shape_unavailable")
                    self.assertEqual(
                        create_helpers.awaitable_result(self.fixtures._state(board)),
                        (1, 1, 1),
                    )
                socket.send_json(_delete(uuid4(), shape_id, 1))
                deleted = create_helpers._receive_json(socket)
                self.assertEqual(deleted["type"], "operation.applied")
                self.assertTrue(deleted["shape"]["deleted"])
                for command in (
                    _update(uuid4(), shape_id, 2, {"x": 8}),
                    _delete(uuid4(), shape_id, 2),
                ):
                    socket.send_json(command)
                    self.assertEqual(
                        create_helpers._receive_json(socket)["code"], "shape_deleted"
                    )
                self.assertEqual(
                    create_helpers.awaitable_result(self.fixtures._state(board)),
                    (2, 1, 2),
                )
                socket.send_json(_update(uuid4(), foreign_id, 1, {"x": 9}))
                self.assertEqual(
                    create_helpers._receive_json(socket)["code"], "shape_unavailable"
                )
                socket.send_json(_update(uuid4(), uuid4(), 1, {"x": 9}))
                self.assertEqual(
                    create_helpers._receive_json(socket)["code"], "shape_unavailable"
                )

    def test_same_revision_updates_and_update_delete_races_have_one_winner(self):
        for delete_race in (False, True):
            with (
                self.subTest(delete_race=delete_race),
                self.fixtures._board() as board,
                TestClient(app) as client,
            ):
                shape_id = self._create_shape(client, board)
                with self.fixtures._socket(client, board, "token_a") as first:
                    create_helpers._receive_json(first)
                    with self.fixtures._socket(client, board, "token_b") as second:
                        create_helpers._receive_json(second)
                        gate = threading.Barrier(3)
                        outcomes = []
                        errors = []

                        def issue(socket, command, gate=gate, errors=errors):
                            try:
                                gate.wait(timeout=2)
                                socket.send_json(command)
                            except (
                                TimeoutError,
                                RuntimeError,
                                ValueError,
                                WebSocketDisconnect,
                            ) as exc:
                                errors.append(exc)

                        left = _update(uuid4(), shape_id, 1, {"x": 100})
                        right = (
                            _delete(uuid4(), shape_id, 1)
                            if delete_race
                            else _update(uuid4(), shape_id, 1, {"y": 200})
                        )
                        workers = [
                            threading.Thread(target=issue, args=(first, left)),
                            threading.Thread(target=issue, args=(second, right)),
                        ]
                        for worker in workers:
                            worker.start()
                        gate.wait(timeout=2)
                        for worker in workers:
                            worker.join(timeout=4)
                        self.assertEqual(errors, [])
                        self.assertFalse(any(worker.is_alive() for worker in workers))
                        outcomes.extend(
                            (
                                create_helpers._receive_json(first),
                                create_helpers._receive_json(second),
                            )
                        )
                        for socket in (first, second):
                            try:
                                outcomes.append(
                                    create_helpers._receive_json(socket, timeout=0.2)
                                )
                            except TimeoutError:
                                pass
                        self.assertEqual(
                            sum(
                                item["type"] == "operation.applied" for item in outcomes
                            ),
                            2,
                        )
                        self.assertEqual(
                            sum(item.get("code") == "conflict" for item in outcomes), 1
                        )
                        conflict = next(
                            item for item in outcomes if item.get("code") == "conflict"
                        )
                        self.assertEqual(conflict["shape"]["revision"], 2)
                        self.assertEqual(
                            create_helpers.awaitable_result(
                                self.fixtures._state(board)
                            ),
                            (2, 1, 2),
                        )

    def test_join_edit_boundary_delivers_snapshot_then_exactly_one_event(self):
        with self.fixtures._board() as board, TestClient(app) as client:
            shape_id = self._create_shape(client, board)
            with self.fixtures._socket(client, board, "token_a") as editor:
                create_helpers._receive_json(editor)
                ready = threading.Barrier(2)
                result = {}

                def join_and_read():
                    with self.fixtures._socket(client, board, "token_b") as joiner:
                        ready.wait(timeout=2)
                        result["snapshot"] = create_helpers._receive_json(joiner)
                        try:
                            result["next"] = create_helpers._receive_json(
                                joiner, timeout=0.3
                            )
                        except TimeoutError:
                            result["next"] = None

                worker = threading.Thread(target=join_and_read)
                worker.start()
                ready.wait(timeout=2)
                editor.send_json(_update(uuid4(), shape_id, 1, {"x": 55}))
                event = create_helpers._receive_json(editor)
                worker.join(timeout=4)
                self.assertFalse(worker.is_alive())
                self.assertEqual(event["type"], "operation.applied")
                snapshot = result["snapshot"]
                self.assertEqual(snapshot["type"], "snapshot")
                seen_in_snapshot = (
                    snapshot["canvas_revision"] == 2
                    and snapshot["shapes"][0]["properties"]["x"] == 55
                )
                seen_after = (
                    result["next"] is not None
                    and result["next"]["type"] == "operation.applied"
                )
                self.assertEqual(seen_in_snapshot + seen_after, 1)
                self.assertEqual(event["canvas_revision"], 2)

    def _create_shape(self, client, board, canvas_id=None):
        with self.fixtures._socket(client, board, "token_a", canvas_id) as socket:
            create_helpers._receive_json(socket)
            shape_id = uuid4()
            socket.send_json(
                create_helpers._create(
                    uuid4(), shape_id, "rectangle", create_helpers._shape_cases()[0][1]
                )
            )
            self.assertEqual(
                create_helpers._receive_json(socket)["type"], "operation.applied"
            )
        return shape_id

    async def _shape(self, board, shape_id):
        conn = await asyncpg.connect(board["url"])
        try:
            return await conn.fetchrow(
                "SELECT revision, properties, deleted_at FROM shape WHERE id=$1",
                shape_id,
            )
        finally:
            await conn.close()

    async def _operation(self, board, operation_id):
        conn = await asyncpg.connect(board["url"])
        try:
            return await conn.fetchrow(
                "SELECT request, result, before_patch, after_patch FROM canvas_operation WHERE id=$1",
                operation_id,
            )
        finally:
            await conn.close()


def _update(operation_id, shape_id, expected_revision, patch):
    return {
        "type": "shape.update",
        "operation_id": str(operation_id),
        "shape_id": str(shape_id),
        "expected_revision": expected_revision,
        "patch": patch,
    }


def _delete(operation_id, shape_id, expected_revision):
    return {
        "type": "shape.delete",
        "operation_id": str(operation_id),
        "shape_id": str(shape_id),
        "expected_revision": expected_revision,
    }
