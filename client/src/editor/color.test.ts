import assert from "node:assert/strict";
import test from "node:test";
import { colorToRgb, parseColorCode } from "./color.ts";

test("RGB input and comma-separated channel codes normalize to six-digit hex", () => {
  assert.equal(parseColorCode("rgb(73, 104, 215)"), "#4968d7");
  assert.equal(parseColorCode(" 0, 15, 255 "), "#000fff");
});

test("hex color codes normalize and convert to RGB for display", () => {
  assert.equal(parseColorCode("#ABCDEF"), "#abcdef");
  assert.equal(colorToRgb("#4968d7"), "rgb(73, 104, 215)");
});

test("invalid RGB channels and malformed color codes are rejected", () => {
  assert.equal(parseColorCode("rgb(256, 0, 0)"), null);
  assert.equal(parseColorCode("rgb(-1, 0, 0)"), null);
  assert.equal(parseColorCode("red"), null);
});
