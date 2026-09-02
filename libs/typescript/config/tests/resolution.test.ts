import assert from "node:assert/strict";
import test from "node:test";
import { resolve, validateConfigurationDocument } from "../src/index.js";
test("precedence and redaction", () => {
  const value = resolve(
    [
      { precedence: 0, source: "defaults", values: { token: "x", retries: 1 } },
      { precedence: 1, source: "override", values: { retries: 2 } },
    ],
    new Set(["token"]),
  );
  assert.deepEqual(value.redacted, { retries: 2, token: { redacted: true } });
  assert.equal(value.provenance.retries, "override");
});

const configurationDocument = (values: Readonly<Record<string, unknown>>) => ({
  schema_version: "mindclade.configuration/v1",
  kind: "Configuration",
  metadata: {
    uid: "configuration-1",
    created_at: "2026-08-30T00:00:00Z",
    owner: "platform",
  },
  spec: {
    resolved_digest: `sha256:${"a".repeat(64)}`,
    values,
    redacted_paths: [],
  },
  lineage: [],
  integrity: {
    payload_digest: `sha256:${"b".repeat(64)}`,
    signatures: [],
  },
});

test("configuration documents use the generated schema binding", () => {
  const configuration = validateConfigurationDocument(configurationDocument({ mode: "fixture" }));

  assert.equal(configuration.kind, "Configuration");
  assert.deepEqual(configuration.spec.values, { mode: "fixture" });
});

test("configuration documents reject secret-bearing keys", () => {
  assert.throws(
    () => validateConfigurationDocument(configurationDocument({ token: "plaintext-secret" })),
    /must match pattern/,
  );
});
