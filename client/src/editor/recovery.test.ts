import assert from "node:assert/strict";
import test from "node:test";
import { isRevisionGap, shouldRetrySocketClose } from "./recovery.ts";

test("a non-contiguous applied revision triggers fresh-snapshot recovery", () => {
  assert.equal(isRevisionGap(8, 10), true);
  assert.equal(isRevisionGap(8, 9), false);
  assert.equal(isRevisionGap(8, 8), false);
});

test("protocol and policy closes are terminal while transport and recovery closes reconnect", () => {
  assert.equal(shouldRetrySocketClose(1006), true);
  assert.equal(shouldRetrySocketClose(1013), true);
  assert.equal(shouldRetrySocketClose(4003), true);
  assert.equal(shouldRetrySocketClose(4004), true);
  assert.equal(shouldRetrySocketClose(4005), true);
  assert.equal(shouldRetrySocketClose(4002), false);
  assert.equal(shouldRetrySocketClose(1008), false);
});
