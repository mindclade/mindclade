# Private SDK examples

These examples are client-side compositions over the Mindclade private SDK.
They do not import generated package paths or access PostgreSQL, Pub/Sub, or GCS
directly:

- `submit_operation.py` builds generated artifact/resource values through SDK
  factories and submits idempotent training intent.
- `follow_operation.ts` resumes the generated operation stream from a durable
  sequence cursor while the SDK owns reconnection, deadline, and cancellation.
- `download_artifact.py` resolves immutable identity, delegates chunk and full
  digest verification to the SDK, re-verifies the staged file, and publishes it
  with an atomic same-directory rename.

Applications must construct a configured SDK client with workload identity and
TLS; tests inject SDK-shaped fakes and make no network calls. Source readiness
does not grant connected or production authority.
