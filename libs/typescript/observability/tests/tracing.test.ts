import assert from "node:assert/strict";
import test from "node:test";
import { traceContext } from "../src/index.js";
test("trace context validates canonical ids", () => {
  assert.deepEqual(traceContext("a".repeat(32), "b".repeat(16)), {
    traceId: "a".repeat(32),
    spanId: "b".repeat(16),
  });
  assert.throws(() => traceContext("A".repeat(32), "b".repeat(16)));
});
