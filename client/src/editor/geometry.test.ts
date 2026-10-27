import assert from "node:assert/strict";
import test from "node:test";
import { lineArrowheadPoints, normalizedBox, previewShape, resizeShape, shapeBounds, translateShape } from "./geometry.ts";
import type { Shape } from "./types.ts";

const box: Shape = { id: "box", kind: "rectangle", revision: 1, deleted: false, properties: { x: 10, y: 20, width: 80, height: 40, color: "#ffffff" } };
const line: Shape = { id: "line", kind: "line", revision: 1, deleted: false, properties: { x1: 20, y1: 40, x2: 80, y2: 20, color: "#ffffff", opacity: 1, z_index: 0, start_arrow: false, end_arrow: false } };

test("dragging a box normalizes reverse-direction gestures and drops tiny gestures", () => {
  assert.deepEqual(normalizedBox({ x: 70, y: 60 }, { x: 20, y: 15 }, "#ffffff"), { x: 20, y: 15, width: 50, height: 45, color: "#ffffff" });
  assert.equal(normalizedBox({ x: 4, y: 4 }, { x: 8, y: 20 }, "#ffffff"), null);
});

test("move previews preserve canonical geometry and line endpoints", () => {
  assert.deepEqual(translateShape(box, 5, -4).properties, { x: 15, y: 16, width: 80, height: 40, color: "#ffffff" });
  assert.deepEqual(previewShape(line, { x: 0, y: 0 }, { x: 10, y: 8 }, "move").properties, { ...line.properties, x1: 30, y1: 48, x2: 90, y2: 28 });
  assert.deepEqual(box.properties, { x: 10, y: 20, width: 80, height: 40, color: "#ffffff" });
});

test("resize keeps positive box dimensions and line bounds are normalized", () => {
  const resized = resizeShape(box, "nw", { x: 99, y: 99 });
  assert.deepEqual(shapeBounds(resized), { x: 82, y: 52, width: 8, height: 8 });
  assert.deepEqual(shapeBounds(line), { x: 20, y: 20, width: 60, height: 20 });
});

test("line arrowheads remain finite, bounded, and tied to their endpoints", () => {
  const short = lineArrowheadPoints(0, 0, 2, 0, true);
  assert.ok(short);
  short.forEach((value, index) => assert.ok(Math.abs(value - [2, 0, 1.3, -0.336, 1.3, 0.336][index]) < 1e-12));
  assert.equal(lineArrowheadPoints(4, 7, 4, 7, true), null);

  const reversedStart = lineArrowheadPoints(10, 0, 0, 0, false);
  assert.equal(reversedStart?.[0], 10);
  assert.ok(reversedStart?.[2] < 10);

  for (const point of [
    lineArrowheadPoints(-1e308, 0, 1e308, 0, false),
    lineArrowheadPoints(-1e308, -1e308, 1e308, 1e308, true),
  ]) {
    assert.ok(point);
    assert.ok(point.every(Number.isFinite));
  }
});
