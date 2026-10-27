import json
import unittest
from uuid import UUID

from app.canvas_protocol import (
    InvalidMessage,
    _merge_shape_patch,
    _parse_client_message,
    _validate_shape_properties,
)


class CanvasProtocolTests(unittest.TestCase):
    def test_rejects_oversized_json_numbers_with_normal_validation_error(self):
        operation_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
        shape = {
            "type": "shape.create",
            "operation_id": operation_id,
            "shape_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
            "kind": "rectangle",
            "properties": {
                "x": 10**400,
                "y": 0,
                "width": 1,
                "height": 1,
                "color": "#ffffff",
            },
        }
        cases = [
            ("shape coordinate", json.dumps(shape), operation_id),
            (
                "cursor coordinate",
                json.dumps({"type": "cursor", "position": {"x": 10**400, "y": 0}}),
                None,
            ),
            (
                "JSON integer limit",
                '{"type":"cursor","position":{"x":' + "9" * 5000 + ',"y":0}}',
                None,
            ),
        ]
        for label, message, expected_id in cases:
            with self.subTest(case=label):
                with self.assertRaises(InvalidMessage) as caught:
                    _parse_client_message(message)
                error = caught.exception.to_message()
                self.assertEqual(error["code"], "invalid_message")
                self.assertEqual(error.get("operation_id"), expected_id)

    def test_parses_shape_create_for_every_supported_kind(self):
        properties_by_kind = {
            "rectangle": {"x": 1, "y": 2, "width": 3, "height": 4, "color": "#aBc123"},
            "ellipse": {"x": 1, "y": 2, "width": 3, "height": 4, "color": "#aBc123"},
            "line": {"x1": 1, "y1": 2, "x2": 3, "y2": 4, "color": "#aBc123"},
            "text": {
                "x": 1,
                "y": 2,
                "width": 3,
                "height": 4,
                "text": "Hello",
                "font_size": 12,
                "color": "#aBc123",
            },
        }
        for kind, properties in properties_by_kind.items():
            with self.subTest(kind=kind):
                command = _parse_client_message(
                    {
                        "type": "shape.create",
                        "operation_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                        "shape_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
                        "kind": kind,
                        "properties": properties,
                    }
                )
                self.assertEqual(command.type, "shape.create")
                self.assertEqual(command.kind, kind)
                self.assertIsInstance(command.operation_id, UUID)
                self.assertEqual(command.properties["opacity"], 1)
                self.assertEqual(command.properties["z_index"], 0)

    def test_validates_opacity_and_layer_order(self):
        base = {"x": 1, "y": 2, "width": 3, "height": 4, "color": "#ffffff"}
        self.assertEqual(
            _validate_shape_properties(
                "rectangle", {**base, "opacity": 0.4, "z_index": 7}
            ),
            {**base, "opacity": 0.4, "z_index": 7},
        )
        for opacity in (-0.01, 1.01, True):
            with (
                self.subTest(opacity=opacity),
                self.assertRaises((TypeError, ValueError)),
            ):
                _validate_shape_properties("rectangle", {**base, "opacity": opacity})
        with self.assertRaises((TypeError, ValueError)):
            _validate_shape_properties("rectangle", {**base, "z_index": float("inf")})

    def test_line_arrow_settings_default_and_require_booleans(self):
        base = {"x1": 1, "y1": 2, "x2": 3, "y2": 4, "color": "#ffffff"}
        self.assertEqual(
            (
                _validate_shape_properties("line", base)["start_arrow"],
                _validate_shape_properties("line", base)["end_arrow"],
            ),
            (False, False),
        )
        for value in (1, "true", None):
            with self.subTest(value=value), self.assertRaises((TypeError, ValueError)):
                _validate_shape_properties("line", {**base, "start_arrow": value})
        with self.assertRaises(ValueError):
            _validate_shape_properties(
                "rectangle",
                {
                    "x": 1,
                    "y": 2,
                    "width": 3,
                    "height": 4,
                    "color": "#ffffff",
                    "start_arrow": True,
                },
            )

    def test_text_limit_counts_ascii_bmp_and_astral_code_points(self):
        base = {
            "x": 1,
            "y": 2,
            "width": 3,
            "height": 4,
            "font_size": 12,
            "color": "#ffffff",
        }
        for character in ("a", "é", "🧪"):
            with self.subTest(character=character):
                accepted = _validate_shape_properties(
                    "text", {**base, "text": character * 10_000}
                )
                self.assertEqual(accepted["text"], character * 10_000)
                with self.assertRaises(ValueError):
                    _validate_shape_properties(
                        "text", {**base, "text": character * 10_001}
                    )

    def test_parses_other_commands_and_cursor_hiding(self):
        operation_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
        shape_id = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
        samples = [
            (
                {
                    "type": "shape.update",
                    "operation_id": operation_id,
                    "shape_id": shape_id,
                    "expected_revision": 2,
                    "patch": {"x": 12},
                },
                "shape.update",
            ),
            (
                {
                    "type": "shape.delete",
                    "operation_id": operation_id,
                    "shape_id": shape_id,
                    "expected_revision": 2,
                },
                "shape.delete",
            ),
            (
                {
                    "type": "undo",
                    "operation_id": operation_id,
                    "target_operation_id": shape_id,
                },
                "undo",
            ),
            (
                {
                    "type": "redo",
                    "operation_id": operation_id,
                    "target_operation_id": shape_id,
                },
                "redo",
            ),
            ({"type": "cursor", "position": {"x": 1.5, "y": -3}}, "cursor"),
            ({"type": "cursor", "position": None}, "cursor"),
        ]
        for payload, expected_type in samples:
            with self.subTest(payload=payload):
                self.assertEqual(_parse_client_message(payload).type, expected_type)

    def test_invalid_messages_share_error_code_and_recover_safe_operation_id(self):
        bad_inputs = [
            {"type": "made.up"},
            {"type": "shape.delete", "operation_id": "not-a-uuid"},
            {
                "type": "shape.update",
                "operation_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                "shape_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
                "expected_revision": 0,
                "patch": {"x": 1},
            },
            {
                "type": "shape.create",
                "operation_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                "shape_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
                "kind": "rectangle",
                "properties": {
                    "x": float("inf"),
                    "y": 2,
                    "width": 3,
                    "height": 4,
                    "color": "#ffffff",
                },
            },
            {
                "type": "shape.create",
                "operation_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                "shape_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
                "kind": "rectangle",
                "properties": {
                    "x": 1,
                    "y": 2,
                    "width": 0,
                    "height": 4,
                    "color": "#ffffff",
                },
            },
            {"type": "cursor", "position": {"x": 1, "y": 2}, "unexpected": True},
        ]
        for payload in bad_inputs:
            with self.subTest(payload=payload):
                with self.assertRaises(InvalidMessage) as caught:
                    _parse_client_message(payload)
                self.assertEqual(caught.exception.code, "invalid_message")
                expected_id = payload.get("operation_id")
                expected_id = (
                    UUID(expected_id)
                    if expected_id == "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
                    else None
                )
                self.assertEqual(caught.exception.operation_id, expected_id)

    def test_invalid_input_error_contains_only_safely_parseable_operation_id(self):
        payload = {
            "type": "shape.update",
            "operation_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            "shape_id": "bad",
            "expected_revision": 1,
            "patch": {"x": 2},
        }
        with self.assertRaises(InvalidMessage) as caught:
            _parse_client_message(payload)
        self.assertEqual(caught.exception.operation_id, UUID(payload["operation_id"]))
        self.assertEqual(
            caught.exception.to_message()["operation_id"], payload["operation_id"]
        )

    def test_rejects_malformed_json_and_unknown_properties(self):
        with self.assertRaises(InvalidMessage):
            _parse_client_message('{"type":')
        with self.assertRaises(ValueError):
            _validate_shape_properties(
                "rectangle",
                {
                    "x": 0,
                    "y": 0,
                    "width": 2,
                    "height": 2,
                    "color": "#ffffff",
                    "text": "extra",
                },
            )

    def test_partial_update_preserves_properties_and_validates_merged_shape(self):
        old = {"x": 5, "y": 7, "width": 20, "height": 30, "color": "#ffffff"}
        merged = _merge_shape_patch("rectangle", old, {"x": 9})
        self.assertEqual(
            merged,
            {
                "x": 9,
                "y": 7,
                "width": 20,
                "height": 30,
                "color": "#ffffff",
                "opacity": 1.0,
                "z_index": 0.0,
            },
        )
        with self.assertRaises(ValueError):
            _merge_shape_patch("rectangle", old, {"width": -1})
        with self.assertRaises(ValueError):
            _merge_shape_patch("rectangle", old, {"text": "wrong kind"})


if __name__ == "__main__":
    unittest.main()
