# Private SDK examples

These examples are client-side compositions over the Mindclade private SDK.
They do not import generated package paths or access PostgreSQL, Pub/Sub, or GCS
directly:

- `submit_operation.py` builds generated artifact/resource values through SDK
  factories and submits idempotent training intent.
- `follow_operation.ts` resumes the generated operation stream from a durable
  sequence cursor while the SDK owns reconnection, deadline, and cancellation.
- `download_artifact.py` resolves immutable identity and delegates verified,
  mode-0600, atomic no-clobber publication to the SDK file helper. It never
  replaces an existing destination, including under a racing writer.

Applications must construct a configured SDK client with workload identity and
TLS; tests inject SDK-shaped fakes and make no network calls. Source readiness
does not grant connected or production authority.
