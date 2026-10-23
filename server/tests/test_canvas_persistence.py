"""PostgreSQL tests for durable operation replay data."""

import asyncio
import json
import os
import unittest
from pathlib import Path
from uuid import uuid4

import asyncpg

SERVER_DIR = Path(__file__).resolve().parents[1]
SCHEMA_SQL = (SERVER_DIR / "schema.sql").read_text()
MIGRATION_SQL = SERVER_DIR / "migrations" / "001_operation_replay.sql"


@unittest.skipUnless(os.environ.get("TEST_DATABASE_URL"), "requires TEST_DATABASE_URL")
class CanvasPersistencePostgresTests(unittest.TestCase):
    """Each test uses an isolated Postgres schema inside the dedicated test DB."""

    def setUp(self):
        self.database_url = os.environ["TEST_DATABASE_URL"]
        self.schema = f"ws02_{uuid4().hex}"
        asyncio.run(self._create_schema())

    def tearDown(self):
        asyncio.run(self._drop_schema())

    def test_fresh_schema_round_trips_request_and_exact_result(self):
        asyncio.run(self._install_schema(SCHEMA_SQL))
        user_id, canvas_id, shape_id = uuid4(), uuid4(), uuid4()
        operation_id = uuid4()
        request = {
            "type": "shape.delete",
            "operation_id": str(operation_id),
            "shape_id": str(shape_id),
            "expected_revision": 6,
        }
        result = {
            "type": "operation.applied",
            "operation_id": str(operation_id),
            "canvas_revision": 13,
            "shape": {
                "id": str(shape_id),
                "revision": 7,
                "deleted": True,
                "deleted_at": "2026-10-23T12:00:00+00:00",
                "kind": "rectangle",
                "properties": {
                    "x": 1,
                    "y": 2,
                    "width": 3,
                    "height": 4,
                    "color": "#123456",
                },
            },
        }
        actual = asyncio.run(
            self._insert_and_fetch_operation(
                user_id, canvas_id, shape_id, operation_id, request, result
            )
        )
        self.assertEqual(json.loads(actual["request"]), request)
        self.assertEqual(json.loads(actual["result"]), result)
        self.assertEqual(actual["kind"], "delete")
        self.assertEqual(actual["canvas_revision"], 13)

    def test_fresh_schema_rejects_non_object_json_and_unpaired_nulls(self):
        asyncio.run(self._install_schema(SCHEMA_SQL))
        asyncio.run(self._seed_parent_rows())

        with self.assertRaises(asyncpg.CheckViolationError):
            asyncio.run(self._insert_operation(uuid4(), ["not", "an", "object"], {}))
        with self.assertRaises(asyncpg.CheckViolationError):
            asyncio.run(self._insert_operation(uuid4(), {}, "not an object"))
        with self.assertRaises(asyncpg.CheckViolationError):
            asyncio.run(self._insert_operation(uuid4(), None, {}))

    def test_upgrade_preserves_existing_row_and_is_rerunnable(self):
        # Install the pre-WS-02 shape of the schema by removing only the new fields.
        asyncio.run(self._install_schema(SCHEMA_SQL))
        asyncio.run(self._remove_replay_columns())
        asyncio.run(self._seed_legacy_operation())

        migration_sql = MIGRATION_SQL.read_text()
        asyncio.run(self._execute(migration_sql))
        asyncio.run(self._execute(migration_sql))

        legacy_id = asyncio.run(self._get_legacy_operation_id())
        legacy = asyncio.run(self._fetch_operation(legacy_id))
        self.assertEqual(legacy["canvas_revision"], 9)
        self.assertIsNone(legacy["request"])
        self.assertIsNone(legacy["result"])

        operation_id = uuid4()
        request = {"type": "shape.create", "operation_id": str(operation_id)}
        result = {
            "type": "operation.applied",
            "operation_id": str(operation_id),
            "canvas_revision": 10,
        }
        actual = asyncio.run(
            self._insert_and_fetch_operation_for_seeded_parent(
                operation_id, request, result
            )
        )
        self.assertEqual(json.loads(actual["request"]), request)
        self.assertEqual(json.loads(actual["result"]), result)

    async def _create_schema(self):
        conn = await asyncpg.connect(self.database_url)
        try:
            await conn.execute(f'CREATE SCHEMA "{self.schema}"')
        finally:
            await conn.close()

    async def _drop_schema(self):
        conn = await self._connect()
        try:
            await conn.execute(f'DROP SCHEMA IF EXISTS "{self.schema}" CASCADE')
        finally:
            await conn.close()

    async def _connect(self):
        conn = await asyncpg.connect(self.database_url)
        await conn.execute(f'SET search_path TO "{self.schema}", public')
        return conn

    async def _install_schema(self, sql):
        conn = await self._connect()
        try:
            await conn.execute(sql)
        finally:
            await conn.close()

    async def _execute(self, sql):
        conn = await self._connect()
        try:
            await conn.execute(sql)
        finally:
            await conn.close()

    async def _seed_parent_rows(self):
        conn = await self._connect()
        try:
            user_id, canvas_id, shape_id = uuid4(), uuid4(), uuid4()
            await conn.execute(
                "INSERT INTO app_user (id, username, password_hash) VALUES ($1, $2, 'x')",
                user_id,
                f"u_{user_id.hex}",
            )
            await conn.execute(
                "INSERT INTO canvas (id, title, created_by) VALUES ($1, 'test', $2)",
                canvas_id,
                user_id,
            )
            await conn.execute(
                "INSERT INTO shape (id, canvas_id, kind, properties) VALUES ($1, $2, 'rectangle', '{}'::jsonb)",
                shape_id,
                canvas_id,
            )
            self.user_id, self.canvas_id, self.shape_id = user_id, canvas_id, shape_id
        finally:
            await conn.close()

    async def _insert_operation(self, operation_id, request, result):
        await self._seed_parent_rows()
        conn = await self._connect()
        try:
            return await conn.fetchrow(
                """INSERT INTO canvas_operation
                   (id, canvas_id, shape_id, actor_id, canvas_revision, kind, request, result)
                   VALUES ($1, $2, $3, $4, 1, 'create', $5::jsonb, $6::jsonb)
                   RETURNING *""",
                operation_id,
                self.canvas_id,
                self.shape_id,
                self.user_id,
                None if request is None else json.dumps(request),
                None if result is None else json.dumps(result),
            )
        finally:
            await conn.close()

    async def _insert_and_fetch_operation(
        self, user_id, canvas_id, shape_id, operation_id, request, result
    ):
        conn = await self._connect()
        try:
            await conn.execute(
                "INSERT INTO app_user (id, username, password_hash) VALUES ($1, $2, 'x')",
                user_id,
                f"u_{user_id.hex}",
            )
            await conn.execute(
                "INSERT INTO canvas (id, title, created_by) VALUES ($1, 'test', $2)",
                canvas_id,
                user_id,
            )
            await conn.execute(
                "INSERT INTO shape (id, canvas_id, kind, properties, revision, deleted_at) VALUES ($1, $2, 'rectangle', '{}'::jsonb, 7, now())",
                shape_id,
                canvas_id,
            )
            await conn.execute(
                """INSERT INTO canvas_operation
                   (id, canvas_id, shape_id, actor_id, canvas_revision, kind, request, result)
                   VALUES ($1, $2, $3, $4, 13, 'delete', $5::jsonb, $6::jsonb)""",
                operation_id,
                canvas_id,
                shape_id,
                user_id,
                json.dumps(request),
                json.dumps(result),
            )
            return await conn.fetchrow(
                "SELECT request, result, kind, canvas_revision FROM canvas_operation WHERE id = $1",
                operation_id,
            )
        finally:
            await conn.close()

    async def _remove_replay_columns(self):
        await self._execute(
            "ALTER TABLE canvas_operation DROP CONSTRAINT IF EXISTS canvas_operation_request_result_pair_check; ALTER TABLE canvas_operation DROP COLUMN IF EXISTS request; ALTER TABLE canvas_operation DROP COLUMN IF EXISTS result"
        )

    async def _seed_legacy_operation(self):
        await self._seed_parent_rows()
        conn = await self._connect()
        try:
            self.legacy_operation_id = uuid4()
            await conn.execute(
                """INSERT INTO canvas_operation (id, canvas_id, shape_id, actor_id, canvas_revision, kind)
                   VALUES ($1, $2, $3, $4, 9, 'create')""",
                self.legacy_operation_id,
                self.canvas_id,
                self.shape_id,
                self.user_id,
            )
        finally:
            await conn.close()

    async def _get_legacy_operation_id(self):
        return self.legacy_operation_id

    async def _fetch_operation(self, operation_id):
        conn = await self._connect()
        try:
            return await conn.fetchrow(
                "SELECT * FROM canvas_operation WHERE id = $1", operation_id
            )
        finally:
            await conn.close()

    async def _insert_and_fetch_operation_for_seeded_parent(
        self, operation_id, request, result
    ):
        conn = await self._connect()
        try:
            await conn.execute(
                """INSERT INTO canvas_operation
                   (id, canvas_id, shape_id, actor_id, canvas_revision, kind, request, result)
                   VALUES ($1, $2, $3, $4, 10, 'create', $5::jsonb, $6::jsonb)""",
                operation_id,
                self.canvas_id,
                self.shape_id,
                self.user_id,
                json.dumps(request),
                json.dumps(result),
            )
            return await conn.fetchrow(
                "SELECT request, result FROM canvas_operation WHERE id = $1",
                operation_id,
            )
        finally:
            await conn.close()


if __name__ == "__main__":
    unittest.main()
