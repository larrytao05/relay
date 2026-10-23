"""Property conflict checks against a contiguous persisted shape history."""

import json
from collections.abc import Mapping, Sequence

GEOMETRY = frozenset({"x", "y", "width", "height", "x1", "y1", "x2", "y2"})


def _json(value: object) -> object:
    return json.loads(value) if isinstance(value, str) else value


def can_merge_update(
    expected_revision: int,
    current_revision: int,
    patch: Mapping[str, object],
    history: Sequence[Mapping[str, object]],
) -> bool:
    if (
        expected_revision >= current_revision
        or len(history) != current_revision - expected_revision + 1
    ):
        return False
    touched = set(patch)
    if touched & GEOMETRY:
        touched |= GEOMETRY
    for offset, operation in enumerate(history):
        result = _json(operation["result"])
        shape = result.get("shape") if isinstance(result, dict) else None
        if (
            not isinstance(shape, dict)
            or shape.get("revision") != expected_revision + offset
            or shape.get("deleted") is not False
        ):
            return False
        if offset:
            changed = _json(operation["after_patch"])
            if not isinstance(changed, dict) or set(changed) & (
                touched | {"deleted", "kind", "properties"}
            ):
                return False
    return True
