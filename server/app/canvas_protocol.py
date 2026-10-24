"""Typed canvas commands and pure message/shape validation."""

import json
import math
import re
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


_APPEARANCE_PROPERTIES = frozenset({"opacity", "z_index"})
_KIND_PROPERTIES: dict[str, frozenset[str]] = {
    "rectangle": frozenset({"x", "y", "width", "height", "color"})
    | _APPEARANCE_PROPERTIES,
    "ellipse": frozenset({"x", "y", "width", "height", "color"})
    | _APPEARANCE_PROPERTIES,
    "line": frozenset({"x1", "y1", "x2", "y2", "color"}) | _APPEARANCE_PROPERTIES,
    "text": frozenset({"x", "y", "width", "height", "text", "font_size", "color"})
    | _APPEARANCE_PROPERTIES,
}


_ALL_PROPERTIES = frozenset().union(*_KIND_PROPERTIES.values())


class InvalidMessage(Exception):
    """A client message failed JSON, command, or shape validation."""

    code = "invalid_message"

    def __init__(self, message: str, operation_id: UUID | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.operation_id = operation_id

    def to_message(self) -> dict[str, object]:
        result: dict[str, object] = {
            "type": "error",
            "code": self.code,
            "message": self.message,
        }
        if self.operation_id is not None:
            result["operation_id"] = str(self.operation_id)
        return result


class _Command(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: str


class _CreateCommand(_Command):
    type: Literal["shape.create"]
    operation_id: UUID
    shape_id: UUID
    kind: Literal["rectangle", "ellipse", "line", "text"]
    properties: dict[str, object]


class _UpdateCommand(_Command):
    type: Literal["shape.update"]
    operation_id: UUID
    shape_id: UUID
    expected_revision: Annotated[int, Field(gt=0, strict=True)]
    patch: dict[str, object]


class _DeleteCommand(_Command):
    type: Literal["shape.delete"]
    operation_id: UUID
    shape_id: UUID
    expected_revision: Annotated[int, Field(gt=0, strict=True)]


class _UndoCommand(_Command):
    type: Literal["undo"]
    operation_id: UUID
    target_operation_id: UUID


class _RedoCommand(_Command):
    type: Literal["redo"]
    operation_id: UUID
    target_operation_id: UUID


class _Point(BaseModel):
    model_config = ConfigDict(extra="forbid")
    x: float
    y: float

    @field_validator("x", "y", mode="before")
    @classmethod
    def finite_number(cls, value: object) -> float:
        return _finite_number(value, "coordinates")


class _CursorCommand(_Command):
    type: Literal["cursor"]
    position: _Point | None


_COMMAND_MODELS = {
    "shape.create": _CreateCommand,
    "shape.update": _UpdateCommand,
    "shape.delete": _DeleteCommand,
    "undo": _UndoCommand,
    "redo": _RedoCommand,
    "cursor": _CursorCommand,
}


def _finite_number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{label} must be a number.")
    try:
        number = float(value)
    except OverflowError as exc:
        raise ValueError(f"{label} must be finite.") from exc
    if not math.isfinite(number):
        raise ValueError(f"{label} must be finite.")
    return number


def _validate_shape_properties(kind: str, properties: object) -> dict[str, object]:
    """Validate and return a complete shape property object for its kind."""
    if kind not in _KIND_PROPERTIES:
        raise ValueError("Unsupported shape kind.")
    if not isinstance(properties, dict):
        raise TypeError("Shape properties must be an object.")
    allowed = _KIND_PROPERTIES[kind]
    required = allowed - _APPEARANCE_PROPERTIES
    keys = set(properties)
    missing = required - keys
    unexpected = keys - allowed
    if missing:
        raise ValueError("Shape properties are missing required fields.")
    if unexpected:
        raise ValueError("Shape properties contain unsupported fields.")

    result = {"opacity": 1, "z_index": 0, **properties}
    coordinate_keys = {"x", "y", "x1", "y1", "x2", "y2"}
    for key in coordinate_keys & required:
        result[key] = _finite_number(result[key], "Coordinates")
    for key in {"width", "height", "font_size"} & required:
        number = _finite_number(result[key], "Dimensions and font size")
        if number <= 0:
            raise ValueError("Dimensions and font size must be positive.")
        result[key] = number
    color = result["color"]
    if not isinstance(color, str) or _COLOR.fullmatch(color) is None:
        raise ValueError("Color must use #RRGGBB format.")
    opacity = _finite_number(result["opacity"], "Opacity")
    if not 0 <= opacity <= 1:
        raise ValueError("Opacity must be between 0 and 1.")
    result["opacity"] = opacity
    result["z_index"] = _finite_number(result["z_index"], "Layer order")
    if kind == "text":
        text = result["text"]
        if not isinstance(text, str):
            raise ValueError("Text must be a string.")
        if len(text) > 10_000:
            raise ValueError("Text must be at most 10000 characters.")
    return result


def _merge_shape_patch(
    kind: str, properties: dict[str, object], patch: dict[str, object]
) -> dict[str, object]:
    """Apply a nonempty patch and validate the resulting complete shape."""
    if kind not in _KIND_PROPERTIES:
        raise ValueError("Unsupported shape kind.")
    if not isinstance(properties, dict) or not isinstance(patch, dict):
        raise TypeError("Shape properties and patch must be objects.")
    if not patch:
        raise ValueError("Update patch must not be empty.")
    if set(patch) - _KIND_PROPERTIES[kind]:
        raise ValueError(
            "Update patch contains properties unsupported for this shape kind."
        )
    current = _validate_shape_properties(kind, properties)
    current.update(patch)
    return _validate_shape_properties(kind, current)


def _safe_operation_id(value: object) -> UUID | None:
    if not isinstance(value, str):
        return None
    try:
        return UUID(value)
    except (ValueError, AttributeError):
        return None


def _parse_client_message(message: str | bytes | object) -> _Command:
    """Parse an untrusted WebSocket frame into a private typed command."""
    payload: object = message
    if isinstance(message, bytes):
        try:
            message = message.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise InvalidMessage("Message must be valid UTF-8.") from exc
    if isinstance(message, str):
        try:
            payload = json.loads(message)
        except (ValueError, TypeError) as exc:
            raise InvalidMessage("Message must contain valid JSON.") from exc

    operation_id = (
        _safe_operation_id(payload.get("operation_id"))
        if isinstance(payload, dict)
        else None
    )
    try:
        if not isinstance(payload, dict):
            raise TypeError("Message must be a JSON object.")
        message_type = payload.get("type")
        model = (
            _COMMAND_MODELS.get(message_type) if isinstance(message_type, str) else None
        )
        if model is None:
            raise ValueError("Unsupported message type.")
        command = model.model_validate(payload)
        if isinstance(command, _CreateCommand):
            command.properties = _validate_shape_properties(
                command.kind, command.properties
            )
        elif isinstance(command, _UpdateCommand):
            if not command.patch:
                raise ValueError("Update patch must not be empty.")
            if set(command.patch) - _ALL_PROPERTIES:
                raise ValueError("Update patch contains unsupported properties.")
        return command
    except (ValidationError, ValueError, TypeError) as exc:
        detail = str(exc)
        if isinstance(exc, ValidationError):
            detail = "Message fields are invalid."
        raise InvalidMessage(detail, operation_id) from exc
