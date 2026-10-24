"""Small connection-local undo/redo navigation primitives."""

import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from uuid import UUID

import asyncpg

from app.canvas_access import lock_canvas_write_access

logger = logging.getLogger(__name__)


@dataclass
class Navigation:
    """Operation IDs currently available for this connection's undo and redo."""

    undo: list[UUID] = field(default_factory=list)
    redo: list[UUID] = field(default_factory=list)

    def record_edit(self, operation_id: UUID) -> None:
        self.undo.append(operation_id)
        self.redo.clear()

    def can_undo(self, target: UUID) -> bool:
        return bool(self.undo) and self.undo[-1] == target

    def can_redo(self, target: UUID) -> bool:
        return bool(self.redo) and self.redo[-1] == target

    def record_undo(self, target: UUID, inverse_id: UUID) -> None:
        if not self.can_undo(target):
            raise ValueError("Undo target is no longer current.")
        self.undo.pop()
        self.redo.append(inverse_id)

    def record_redo(self, target: UUID, inverse_id: UUID) -> None:
        if not self.can_redo(target):
            raise ValueError("Redo target is no longer current.")
        self.redo.pop()
        self.undo.append(inverse_id)


def _json_value(value: object) -> object:
    return json.loads(value) if isinstance(value, str) else value


def _error(operation_id: UUID, code: str, message: str) -> dict[str, object]:
    return {
        "type": "error",
        "operation_id": str(operation_id),
        "code": code,
        "message": message,
    }


async def apply_history_command(
    *,
    pool: object,
    connection: object,
    room: object,
    command: object,
    replay: Callable[
        [object, object, UUID, dict[str, object]], Awaitable[dict[str, object] | None]
    ],
    collision: Callable[
        [object, UUID, dict[str, object]], Awaitable[dict[str, object] | None]
    ],
) -> tuple[dict[str, object], bool]:
    """Reverse the current stack target in one durable transaction."""
    operation_id = command.operation_id
    target_id = command.target_operation_id
    request = command.model_dump(mode="json")
    is_undo = command.type == "undo"
    navigation = connection.history

    try:
        async with pool.acquire() as conn:  # noqa: SIM117
            async with conn.transaction():
                revision = await lock_canvas_write_access(
                    conn,
                    connection.canvas_id,
                    connection.identity.user.id,
                    connection.identity.token_hash,
                )
                if revision is None:
                    return _error(
                        operation_id,
                        "access_revoked",
                        "Canvas access is no longer available.",
                    ), False

                # Retry identity is checked before stack position or document state.
                saved = await replay(conn, connection, operation_id, request)
                if saved is not None:
                    return saved, False

                eligible = (
                    navigation.can_undo(target_id)
                    if is_undo
                    else navigation.can_redo(target_id)
                )
                if not eligible:
                    return _error(
                        operation_id,
                        "history_unavailable",
                        "That operation is not the current undo or redo target.",
                    ), False

                target = await conn.fetchrow(
                    """SELECT id, shape_id, actor_id, canvas_revision, kind,
                              before_patch, after_patch
                       FROM canvas_operation WHERE id=$1 AND canvas_id=$2""",
                    target_id,
                    connection.canvas_id,
                )
                if target is None or target["actor_id"] != connection.identity.user.id:
                    return _error(
                        operation_id,
                        "history_unavailable",
                        "That operation is not available to this connection.",
                    ), False

                shape = await conn.fetchrow(
                    """SELECT id, kind, properties, revision,
                              (deleted_at IS NOT NULL) AS deleted
                       FROM shape WHERE id=$1 AND canvas_id=$2 FOR UPDATE""",
                    target["shape_id"],
                    connection.canvas_id,
                )
                if shape is None:
                    return _error(
                        operation_id,
                        "history_unavailable",
                        "The target shape is no longer available.",
                    ), False

                conflict = await _has_later_foreign_effect(
                    conn,
                    connection.canvas_id,
                    target["shape_id"],
                    target["canvas_revision"],
                    connection.id,
                    room.operation_origins,
                )
                if conflict:
                    current = {
                        "id": str(shape["id"]),
                        "kind": shape["kind"],
                        "properties": _json_value(shape["properties"]),
                        "revision": shape["revision"],
                        "deleted": shape["deleted"],
                    }
                    return {
                        **_error(
                            operation_id,
                            "undo_conflict",
                            "Another connection has a later effective edit on this shape.",
                        ),
                        "shape": current,
                    }, False

                properties = _json_value(shape["properties"])
                before_record: dict[str, object]
                after_record: dict[str, object]
                deleted = shape["deleted"]
                if target["kind"] == "create":
                    before_record = {"deleted": deleted}
                    after_record = {"deleted": True} if is_undo else {"deleted": False}
                    deleted = after_record["deleted"] is True
                else:
                    source_before = _json_value(target["before_patch"])
                    source_after = _json_value(target["after_patch"])
                    if not isinstance(source_before, dict) or not isinstance(
                        source_after, dict
                    ):
                        return _error(
                            operation_id,
                            "history_unavailable",
                            "The target operation has invalid inverse data.",
                        ), False
                    # The target itself is the inverse recipe for both undo and redo.
                    touched = set(source_before) | set(source_after)
                    before_record = {}
                    after_record = {}
                    for key in touched:
                        if key == "deleted":
                            before_record[key] = deleted
                            if key in source_before:
                                after_record[key] = source_before[key]
                            else:
                                after_record[key] = source_after.get(key, deleted)
                            deleted = after_record[key] is True
                        else:
                            before_record[key] = properties[key]
                            if key in source_before:
                                after_record[key] = source_before[key]
                            else:
                                after_record[key] = source_after[key]
                            properties[key] = after_record[key]

                revision += 1
                shape_revision = shape["revision"] + 1
                await conn.execute(
                    """UPDATE shape SET properties=$2::jsonb,
                              deleted_at=CASE WHEN $3 THEN COALESCE(deleted_at, now()) ELSE NULL END,
                              revision=$4, updated_at=now()
                       WHERE id=$1""",
                    target["shape_id"],
                    json.dumps(properties),
                    deleted,
                    shape_revision,
                )
                result = {
                    "type": "operation.applied",
                    "operation_id": str(operation_id),
                    "actor_id": str(connection.identity.user.id),
                    "kind": command.type,
                    "target_operation_id": str(target_id),
                    "canvas_revision": revision,
                    "shape": {
                        "id": str(shape["id"]),
                        "kind": shape["kind"],
                        "properties": properties,
                        "revision": shape_revision,
                        "deleted": deleted,
                    },
                }
                await conn.execute(
                    "UPDATE canvas SET revision=$2, updated_at=now() WHERE id=$1",
                    connection.canvas_id,
                    revision,
                )
                await conn.execute(
                    """INSERT INTO canvas_operation
                       (id, canvas_id, shape_id, actor_id, canvas_revision, kind,
                        before_patch, after_patch, request, result, target_operation_id)
                       VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb,$8::jsonb,$9::jsonb,$10::jsonb,$11)""",
                    operation_id,
                    connection.canvas_id,
                    target["shape_id"],
                    connection.identity.user.id,
                    revision,
                    command.type,
                    json.dumps(before_record),
                    json.dumps(after_record),
                    json.dumps(request),
                    json.dumps(result),
                    target_id,
                )
                return result, True
    except asyncpg.UniqueViolationError:
        saved = await collision(pool, operation_id, request)
        return saved or _error(
            operation_id, "operation_failed", "Operation could not be saved."
        ), False
    except asyncpg.PostgresError:
        logger.exception("Canvas history command transaction failed")
        return _error(
            operation_id, "operation_failed", "Operation could not be saved."
        ), False


async def _has_later_foreign_effect(
    conn: object,
    canvas_id: UUID,
    shape_id: UUID,
    target_revision: int,
    connection_id: UUID,
    origins: dict[UUID, UUID],
) -> bool:
    rows = await conn.fetch(
        """SELECT id, actor_id, canvas_revision, kind, target_operation_id
           FROM canvas_operation
           WHERE canvas_id=$1 AND shape_id=$2 AND canvas_revision>$3
           ORDER BY canvas_revision""",
        canvas_id,
        shape_id,
        target_revision,
    )
    effective: dict[UUID, UUID | None] = {}
    for row in rows:
        origin = origins.get(row["id"])
        if row["kind"] in {"create", "update", "delete"}:
            effective[row["id"]] = origin
        elif row["kind"] == "undo":
            effective.pop(row["target_operation_id"], None)
        elif row["kind"] == "redo":
            undone = await conn.fetchrow(
                "SELECT target_operation_id FROM canvas_operation WHERE id=$1",
                row["target_operation_id"],
            )
            if undone is not None:
                source_id = undone["target_operation_id"]
                effective[source_id] = origins.get(source_id)
            effective[row["id"]] = origin
    return any(origin != connection_id for origin in effective.values())
