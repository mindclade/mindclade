import assert from "node:assert/strict";
import test from "node:test";
import { resolve } from "../src/index.js";
test("precedence and redaction", () => {
  const value = resolve([{ precedence: 0, source: "defaults", values: { token: "x", retries: 1 } }, { precedence: 1, source: "override", values: { retries: 2 } }], new Set(["token"]));
  assert.deepEqual(value.redacted, { retries: 2, token: { redacted: true } }); assert.equal(value.provenance.retries, "override");
});
