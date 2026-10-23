"""WS-07 connection-scoped undo/redo tests against PostgreSQL."""

import json
import os
import unittest
from uuid import uuid4

import asyncpg
import test_canvas_create as create_helpers
from fastapi.testclient import TestClient

from app.main import app


@unittest.skipUnless(os.environ.get("TEST_DATABASE_URL"), "requires TEST_DATABASE_URL")
class CanvasHistoryPostgresTests(unittest.TestCase):
    def setUp(self):
        self.fixtures = create_helpers.CanvasCreatePostgresTests()

    def test_two_moves_undo_both_and_redo_both(self):
        with self.fixtures._board() as board, TestClient(app) as client:  # noqa: SIM117
            with self.fixtures._socket(client, board, "token_a") as alice:
                create_helpers._receive_json(alice)
                shape_id = uuid4()
                create_id = uuid4()
                alice.send_json(
                    create_helpers._create(
                        create_id,
                        shape_id,
                        "rectangle",
                        create_helpers._shape_cases()[0][1],
                    )
                )
                created = create_helpers._receive_json(alice)
                self.assertEqual(created["type"], "operation.applied")
                move_a, move_b = uuid4(), uuid4()
                alice.send_json(_update(move_a, shape_id, 1, {"x": 10}))
                moved_a = create_helpers._receive_json(alice)
                alice.send_json(_update(move_b, shape_id, 2, {"x": 20}))
                moved_b = create_helpers._receive_json(alice)

                undo_b, undo_a = uuid4(), uuid4()
                alice.send_json(_history("undo", undo_b, move_b))
                state_a = create_helpers._receive_json(alice)
                self.assertEqual(state_a["type"], "operation.applied")
                alice.send_json(_history("undo", undo_a, move_a))
                state_original = create_helpers._receive_json(alice)
                self.assertEqual(state_a["shape"]["properties"]["x"], 10)
                self.assertEqual(state_original["shape"]["properties"]["x"], 1)

                redo_a, redo_b = uuid4(), uuid4()
                alice.send_json(_history("redo", redo_a, undo_a))
                state_a_again = create_helpers._receive_json(alice)
                alice.send_json(_history("redo", redo_b, undo_b))
                state_b_again = create_helpers._receive_json(alice)
                self.assertEqual(state_a_again["shape"]["properties"]["x"], 10)
                self.assertEqual(state_b_again["shape"]["properties"]["x"], 20)
                self.assertEqual(
                    [
                        created["canvas_revision"],
                        moved_a["canvas_revision"],
                        moved_b["canvas_revision"],
                        state_a["canvas_revision"],
                        state_original["canvas_revision"],
                        state_a_again["canvas_revision"],
                        state_b_again["canvas_revision"],
                    ],
                    list(range(1, 8)),
                )
                for target, op_id in ((move_b, undo_b), (move_a, undo_a)):
                    row = create_helpers.awaitable_result(self._operation(board, op_id))
                    self.assertEqual(row["target_operation_id"], target)
                    self.assertEqual(
                        row["canvas_revision"], 4 if target == move_b else 5
                    )
                    self.assertEqual(
                        json.loads(row["request"]), _history("undo", op_id, target)
                    )
                    self.assertEqual(json.loads(row["result"])["kind"], "undo")

    def test_create_delete_undo_redo_and_new_edit_clears_redo(self):
        with self.fixtures._board() as board, TestClient(app) as client:  # noqa: SIM117
            with self.fixtures._socket(client, board, "token_a") as alice:
                create_helpers._receive_json(alice)
                shape_id = uuid4()
                created_id = uuid4()
                alice.send_json(
                    create_helpers._create(
                        created_id,
                        shape_id,
                        "rectangle",
                        create_helpers._shape_cases()[0][1],
                    )
                )
                create_helpers._receive_json(alice)
                undo_create = uuid4()
                alice.send_json(_history("undo", undo_create, created_id))
                hidden = create_helpers._receive_json(alice)
                self.assertEqual(hidden["type"], "operation.applied")
                self.assertTrue(hidden["shape"]["deleted"])
                redo_create = uuid4()
                alice.send_json(_history("redo", redo_create, undo_create))
                visible = create_helpers._receive_json(alice)
                self.assertFalse(visible["shape"]["deleted"])

                delete_id = uuid4()
                alice.send_json(
                    _delete(delete_id, shape_id, visible["shape"]["revision"])
                )
                deleted = create_helpers._receive_json(alice)
                self.assertTrue(deleted["shape"]["deleted"])
                undo_delete = uuid4()
                alice.send_json(_history("undo", undo_delete, delete_id))
                restored = create_helpers._receive_json(alice)
                self.assertFalse(restored["shape"]["deleted"])
                redo_delete = uuid4()
                alice.send_json(_history("redo", redo_delete, undo_delete))
                hidden_again = create_helpers._receive_json(alice)
                self.assertTrue(hidden_again["shape"]["deleted"])

                undo_again = uuid4()
                alice.send_json(_history("undo", undo_again, redo_delete))
                create_helpers._receive_json(alice)
                alice.send_json(_update(uuid4(), shape_id, 7, {"x": 88}))
                edited = create_helpers._receive_json(alice)
                self.assertEqual(edited["type"], "operation.applied")
                alice.send_json(_history("redo", uuid4(), undo_again))
                self.assertEqual(
                    create_helpers._receive_json(alice)["code"], "history_unavailable"
                )
                self.assertEqual(edited["shape"]["properties"]["x"], 88)

    def test_other_connection_edits_and_alice_bob_alice_trace_are_protected(self):
        with self.fixtures._board() as board, TestClient(app) as client:  # noqa: SIM117
            with self.fixtures._socket(client, board, "token_a") as alice:
                create_helpers._receive_json(alice)
                shape_id = uuid4()
                create_id = uuid4()
                alice.send_json(
                    create_helpers._create(
                        create_id,
                        shape_id,
                        "rectangle",
                        create_helpers._shape_cases()[0][1],
                    )
                )
                create_helpers._receive_json(alice)
                action_a, bob_b, action_c = uuid4(), uuid4(), uuid4()
                alice.send_json(_update(action_a, shape_id, 1, {"x": 10}))
                create_helpers._receive_json(alice)
                with self.fixtures._socket(client, board, "token_b") as bob:
                    create_helpers._receive_json(bob)
                    bob.send_json(_update(bob_b, shape_id, 2, {"y": 30}))
                    create_helpers._receive_json(alice)
                    create_helpers._receive_json(bob)
                    alice.send_json(_update(action_c, shape_id, 3, {"x": 40}))
                    create_helpers._receive_json(alice)
                    create_helpers._receive_json(bob)
                    undo_c = uuid4()
                    alice.send_json(_history("undo", undo_c, action_c))
                    undone_c = create_helpers._receive_json(alice)
                    self.assertEqual(undone_c["type"], "operation.applied")
                    self.assertEqual(undone_c, create_helpers._receive_json(bob))
                    self.assertEqual(undone_c["shape"]["properties"]["x"], 10)
                    refusal = _history("undo", uuid4(), action_a)
                    alice.send_json(refusal)
                    denied = create_helpers._receive_json(alice)
                    self.assertEqual(denied["code"], "undo_conflict")
                    self.assertEqual(denied["shape"]["properties"]["y"], 30)
                    self.assertIsNone(create_helpers._receive_nowait_json(bob))
                    self.assertEqual(
                        create_helpers.awaitable_result(self.fixtures._state(board)),
                        (5, 1, 5),
                    )

    def test_other_tab_and_out_of_order_targets_are_refused(self):
        with self.fixtures._board() as board, TestClient(app) as client:  # noqa: SIM117
            with self.fixtures._socket(client, board, "token_a") as first:
                create_helpers._receive_json(first)
                shape_id = uuid4()
                create_id = uuid4()
                first.send_json(
                    create_helpers._create(
                        create_id,
                        shape_id,
                        "rectangle",
                        create_helpers._shape_cases()[0][1],
                    )
                )
                create_helpers._receive_json(first)
                a, b = uuid4(), uuid4()
                first.send_json(_update(a, shape_id, 1, {"x": 2}))
                create_helpers._receive_json(first)
                first.send_json(_update(b, shape_id, 2, {"y": 3}))
                create_helpers._receive_json(first)
                with self.fixtures._socket(client, board, "token_a") as second:
                    create_helpers._receive_json(second)
                    second.send_json(_history("undo", uuid4(), b))
                    self.assertEqual(
                        create_helpers._receive_json(second)["code"],
                        "history_unavailable",
                    )
                first.send_json(_history("undo", uuid4(), a))
                self.assertEqual(
                    create_helpers._receive_json(first)["code"], "history_unavailable"
                )
                first.send_json(_history("undo", uuid4(), b))
                self.assertEqual(
                    create_helpers._receive_json(first)["type"], "operation.applied"
                )

    def test_exact_undo_retry_has_no_second_effect_and_reconnect_has_empty_history(
        self,
    ):
        with self.fixtures._board() as board, TestClient(app) as client:
            with self.fixtures._socket(client, board, "token_a") as alice:
                create_helpers._receive_json(alice)
                shape_id = uuid4()
                create_id, move_id = uuid4(), uuid4()
                alice.send_json(
                    create_helpers._create(
                        create_id,
                        shape_id,
                        "rectangle",
                        create_helpers._shape_cases()[0][1],
                    )
                )
                create_helpers._receive_json(alice)
                alice.send_json(_update(move_id, shape_id, 1, {"x": 9}))
                create_helpers._receive_json(alice)
                with self.fixtures._socket(client, board, "token_b") as bob:
                    create_helpers._receive_json(bob)
                    undo_id = uuid4()
                    request = _history("undo", undo_id, move_id)
                    alice.send_json(request)
                    original = create_helpers._receive_json(alice)
                    self.assertEqual(original["type"], "operation.applied")
                    self.assertEqual(original, create_helpers._receive_json(bob))
                    alice.send_json(request)
                    self.assertEqual(create_helpers._receive_json(alice), original)
                    self.assertIsNone(create_helpers._receive_nowait_json(bob))
                    self.assertEqual(
                        create_helpers.awaitable_result(self.fixtures._state(board)),
                        (3, 1, 3),
                    )
            with self.fixtures._socket(client, board, "token_a") as resumed:
                snapshot = create_helpers._receive_json(resumed)
                self.assertEqual(snapshot["canvas_revision"], 3)
                resumed.send_json(_history("undo", uuid4(), move_id))
                self.assertEqual(
                    create_helpers._receive_json(resumed)["code"], "history_unavailable"
                )
                restored = next(
                    item for item in snapshot["shapes"] if item["id"] == str(shape_id)
                )
                self.assertEqual(restored["properties"]["x"], 1)

    def test_cross_user_target_and_later_edit_from_another_connection_refuse(self):
        with self.fixtures._board() as board, TestClient(app) as client:
            shape_id = self._create_shape(client, board)
            with self.fixtures._socket(client, board, "token_b") as bob:
                create_helpers._receive_json(bob)
                bob_op = uuid4()
                bob.send_json(_update(bob_op, shape_id, 1, {"x": 50}))
                create_helpers._receive_json(bob)
                with self.fixtures._socket(client, board, "token_a") as alice:
                    create_helpers._receive_json(alice)
                    alice.send_json(_history("undo", uuid4(), bob_op))
                    self.assertEqual(
                        create_helpers._receive_json(alice)["code"],
                        "history_unavailable",
                    )

    def test_another_tab_of_same_user_is_a_collaborator_for_conflicts(self):
        with self.fixtures._board() as board, TestClient(app) as client:  # noqa: SIM117
            with self.fixtures._socket(client, board, "token_a") as first:
                create_helpers._receive_json(first)
                shape_id, create_id = uuid4(), uuid4()
                first.send_json(
                    create_helpers._create(
                        create_id,
                        shape_id,
                        "rectangle",
                        create_helpers._shape_cases()[0][1],
                    )
                )
                create_helpers._receive_json(first)
                own_action = uuid4()
                first.send_json(_update(own_action, shape_id, 1, {"x": 20}))
                create_helpers._receive_json(first)
                with self.fixtures._socket(client, board, "token_a") as second:
                    create_helpers._receive_json(second)
                    other_tab_action = uuid4()
                    second.send_json(_update(other_tab_action, shape_id, 2, {"y": 40}))
                    create_helpers._receive_json(first)
                    create_helpers._receive_json(second)
                    first.send_json(_history("undo", uuid4(), own_action))
                    denied = create_helpers._receive_json(first)
                    self.assertEqual(denied["code"], "undo_conflict")
                    self.assertEqual(denied["shape"]["properties"]["y"], 40)

    def _create_shape(self, client, board):
        with self.fixtures._socket(client, board, "token_a") as socket:
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

    async def _operation(self, board, operation_id):
        conn = await asyncpg.connect(board["url"])
        try:
            return await conn.fetchrow(
                "SELECT target_operation_id, canvas_revision, request, result FROM canvas_operation WHERE id=$1",
                operation_id,
            )
        finally:
            await conn.close()


def _history(kind, operation_id, target_operation_id):
    return {
        "type": kind,
        "operation_id": str(operation_id),
        "target_operation_id": str(target_operation_id),
    }


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
