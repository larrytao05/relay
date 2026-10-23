import assert from "node:assert/strict";
import test from "node:test";
import { normalizedBox, previewShape, resizeShape, shapeBounds, translateShape } from "./geometry.ts";
import type { Shape } from "./types.ts";

const box: Shape = { id: "box", kind: "rectangle", revision: 1, deleted: false, properties: { x: 10, y: 20, width: 80, height: 40, color: "#ffffff" } };
const line: Shape = { id: "line", kind: "line", revision: 1, deleted: false, properties: { x1: 20, y1: 40, x2: 80, y2: 20, color: "#ffffff" } };

test("dragging a box normalizes reverse-direction gestures and drops tiny gestures", () => {
  assert.deepEqual(normalizedBox({ x: 70, y: 60 }, { x: 20, y: 15 }, "#ffffff"), { x: 20, y: 15, width: 50, height: 45, color: "#ffffff" });
  assert.equal(normalizedBox({ x: 4, y: 4 }, { x: 8, y: 20 }, "#ffffff"), null);
});

test("move previews preserve canonical geometry and line endpoints", () => {
  assert.deepEqual(translateShape(box, 5, -4).properties, { x: 15, y: 16, width: 80, height: 40, color: "#ffffff" });
  assert.deepEqual(previewShape(line, { x: 0, y: 0 }, { x: 10, y: 8 }, "move").properties, { x1: 30, y1: 48, x2: 90, y2: 28, color: "#ffffff" });
  assert.deepEqual(box.properties, { x: 10, y: 20, width: 80, height: 40, color: "#ffffff" });
});

test("resize keeps positive box dimensions and line bounds are normalized", () => {
  const resized = resizeShape(box, "nw", { x: 99, y: 99 });
  assert.deepEqual(shapeBounds(resized), { x: 82, y: 52, width: 8, height: 8 });
  assert.deepEqual(shapeBounds(line), { x: 20, y: 20, width: 60, height: 20 });
});
