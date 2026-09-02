# Private SDK examples

These examples are client-side compositions over the Mindclade private SDK.
They do not import generated package paths or access PostgreSQL, Pub/Sub, or GCS
directly:

- `submit_operation.py` builds generated artifact/resource values through SDK
  factories and submits idempotent training intent.
- `list_operations.py` reads a list result through the SDK's auto-paginating
  page. Iterating it crosses page boundaries under the page and item budgets the
  example declares, and the same value still carries `next_page_token`, the
  generated `ListOperationsResponse`, and `next_page()` for a caller that
  checkpoints the cursor instead.
- `handle_errors.py` acts on the SDK error hierarchy: one typed class is caught
  because absence is actionable, every other class propagates unchanged, and any
  SDK error projects onto the bounded fields an operator reads — stable code,
  retryability, retry-after, request id, trace id, and field violations.
- `download_artifact.py` resolves immutable identity and delegates verified,
  mode-0600, atomic no-clobber publication to the SDK file helper. It never
  replaces an existing destination, including under a racing writer.
- `follow_operation.ts` resumes the generated operation stream from a durable
  sequence cursor while the SDK owns reconnection, deadline, and cancellation.
- `read_request_id.ts` reads the request id, trace id, and allowlisted response
  metadata of a *successful* call through `withResponse()`, so a success is as
  correlatable as a failure.
- `configure_client.ts` builds a client from the `MINDCLADE_*` variables through
  the SDK's own `fromEnvironment` constructor rather than re-implementing that
  parsing. The workload identity provider is still supplied in code, because no
  environment variable may carry a credential.

Retries, deadlines, idempotency, pagination, and metadata belong to the SDK: no
example writes a retry loop, a page loop, a deadline of its own, or a second
error taxonomy, and none inspects a gRPC status code.

Applications must construct a configured SDK client with workload identity and
TLS; tests inject SDK-shaped fakes and make no network calls. Source readiness
does not grant connected or production authority.
