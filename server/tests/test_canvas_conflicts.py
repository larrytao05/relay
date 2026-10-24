import asyncio
import json
import unittest
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from app.auth import PublicUser
from app.canvas_conflicts import can_merge_update
from app.canvas_protocol import _DeleteCommand, _UpdateCommand
from app.canvas_ws import CanvasRooms, Connection, SessionIdentity


def operation(revision, patch=None, deleted=False):
    return {
        "after_patch": json.dumps(patch or {}),
        "result": json.dumps({"shape": {"revision": revision, "deleted": deleted}}),
    }


class PropertyConflictTests(unittest.TestCase):
    def test_unrelated_properties_merge_across_multiple_revisions(self):
        history = [
            operation(1),
            operation(2, {"color": "#abcdef"}),
            operation(3, {"opacity": 0.5}),
        ]
        self.assertTrue(can_merge_update(1, 3, {"x": 20}, history))
        self.assertTrue(can_merge_update(1, 3, {"text": "draft"}, history))

    def test_same_properties_and_geometry_group_conflict(self):
        for changes, intervening in [
            ({"color": "#ffffff"}, {"color": "#000000"}),
            ({"text": "mine"}, {"text": "theirs"}),
            ({"x": 20}, {"y": 40}),
            ({"width": 20}, {"x": 40}),
            ({"x1": 20}, {"y2": 40}),
        ]:
            with self.subTest(patch=changes, intervening=intervening):
                self.assertFalse(
                    can_merge_update(
                        1, 2, changes, [operation(1), operation(2, intervening)]
                    )
                )

    def test_a_change_then_undo_still_conflicts_with_the_same_property(self):
        history = [
            operation(1),
            operation(2, {"color": "#000000"}),
            operation(3, {"color": "#ffffff"}),
        ]
        self.assertFalse(can_merge_update(1, 3, {"color": "#aaaaaa"}, history))
        self.assertTrue(can_merge_update(1, 3, {"text": "draft"}, history))

    def test_delete_and_restore_are_barriers(self):
        history = [
            operation(1),
            operation(2, {"deleted": True}, True),
            operation(3, {"deleted": False}),
        ]
        self.assertFalse(can_merge_update(1, 3, {"color": "#aaaaaa"}, history))

    def test_missing_legacy_or_incomplete_history_cannot_merge(self):
        for history in (
            [],
            [operation(2)],
            [operation(1), operation(3)],
            [operation(1), {"after_patch": "{}", "result": None}],
        ):
            with self.subTest(history=history):
                self.assertFalse(can_merge_update(1, 3, {"color": "#aaaaaa"}, history))

    def test_future_revision_cannot_merge(self):
        self.assertFalse(can_merge_update(9, 1, {"color": "#aaaaaa"}, [operation(1)]))


class PropertyMergeHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_handler_merges_latest_properties_and_records_actual_inverse(self):
        result, committed, conn = await self._apply({"x": 77})
        self.assertTrue(committed)
        self.assertEqual(result["shape"]["revision"], 3)
        self.assertEqual(result["shape"]["properties"]["color"], "#abcdef")
        self.assertEqual(result["shape"]["properties"]["x"], 77)
        journal = next(
            call.args
            for call in conn.execute.await_args_list
            if "INSERT INTO canvas_operation" in call.args[0]
        )
        self.assertEqual(json.loads(journal[7]), {"x": 10})
        self.assertEqual(json.loads(journal[8]), {"x": 77})
        self.assertEqual(json.loads(journal[10]), result)

    async def test_handler_rejects_overlap_and_stale_delete_without_writes(self):
        for changes in ({"color": "#ffffff"}, None):
            result, committed, conn = await self._apply(changes)
            self.assertFalse(committed)
            self.assertEqual(result["code"], "conflict")
            self.assertEqual(result["shape"]["revision"], 2)
            conn.execute.assert_not_awaited()

    async def _apply(self, changes):
        # Replace the database boundary and run the actual command handler.
        shape_id, canvas_id = uuid4(), uuid4()
        current = {
            "id": shape_id,
            "kind": "rectangle",
            "properties": json.dumps(
                {
                    "x": 10,
                    "y": 10,
                    "width": 50,
                    "height": 30,
                    "color": "#abcdef",
                    "opacity": 1,
                    "z_index": 0,
                }
            ),
            "revision": 2,
            "deleted": False,
        }

        @asynccontextmanager
        async def transaction():
            yield

        conn = AsyncMock()
        conn.transaction = transaction
        user_id = uuid4()
        conn.fetchrow.side_effect = [{"user_id": user_id}, {"revision": 2}, current]
        conn.fetch.return_value = [operation(1), operation(2, {"color": "#abcdef"})]

        @asynccontextmanager
        async def acquire():
            yield conn

        class Pool:
            pass

        pool = Pool()
        pool.acquire = acquire
        rooms = CanvasRooms(pool=pool)
        connection = Connection(
            uuid4(),
            canvas_id,
            SessionIdentity(
                "digest",
                PublicUser(id=user_id, username="tester"),
                datetime.now(UTC) + timedelta(hours=1),
            ),
            None,
            asyncio.Queue(),
        )
        fields = {"operation_id": uuid4(), "shape_id": shape_id, "expected_revision": 1}
        command = (
            _DeleteCommand(type="shape.delete", **fields)
            if changes is None
            else _UpdateCommand(type="shape.update", patch=changes, **fields)
        )
        with patch.object(rooms, "_operation_replay", AsyncMock(return_value=None)):
            result, committed = await rooms._apply_shape_command(connection, command)
        return result, committed, conn
