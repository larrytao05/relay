import assert from "node:assert/strict";
import test from "node:test";
import { isTextWithinLimit, MAX_TEXT_CODE_POINTS } from "./text.ts";

test("counts ASCII, BMP, and astral characters as Unicode code points", () => {
  for (const character of ["a", "é", "🧪"]) {
    assert.equal(isTextWithinLimit(character.repeat(MAX_TEXT_CODE_POINTS)), true);
    assert.equal(isTextWithinLimit(character.repeat(MAX_TEXT_CODE_POINTS + 1)), false);
  }
});
