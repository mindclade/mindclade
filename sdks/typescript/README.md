# Mindclade internal TypeScript SDK

This private package is the handwritten TypeScript developer experience over
the authoritative generated Protobuf-ES contracts; Connect clients are created
at runtime from the generated service descriptors:

```text
protocols/proto
    -> protocols/generated/typescript
    -> sdks/typescript
    -> internal services, tools, workers, and applications
```

Generated descriptors and messages remain the only wire models. This package
adds secure endpoint configuration, injectable short-lived workload identity,
metadata, deadlines, bounded retries, normalized errors, operation helpers,
and artifact alias resolution. `client.raw` exposes every internal generated
service client plus a generic descriptor escape hatch. Raw calls are
authenticated and deadline-bounded, but are never retried implicitly because
the SDK cannot infer arbitrary RPC mutation semantics.

Plaintext is rejected except for an explicitly enabled Local loopback test
endpoint; that mode rejects a token provider and emits no authorization
metadata. Secure clients require a provider. `GcpWorkloadIdentityProvider`
uses the fixed GCE/GKE metadata identity endpoint with an audience-bound,
bounded exchange, refresh skew, per-audience cache, concurrency-safe
singleflight, caller cancellation, and redacted failures.
Set `ClientConfigInput.audience` to the verifier's exact configured OIDC
audience. If omitted, the SDK derives the endpoint's canonical HTTPS origin:
the host is lowercase, IPv6 remains bracketed, default `:443` is omitted, and a
non-default port is retained.

Operation watches retain one total deadline, resume from `last_sequence` after
bounded consecutive retryable failures, validate generated updates, and stop
on cancellation or a terminal operation. Polling and watch-until-done raise a
typed `OperationFailure` for failed or cancelled remote operations; the
generated `Operation` is available deliberately but is non-enumerable so its
structured error is not serialized with the SDK error. `RecordingTransport`
can wrap any Connect router or transport across the full generated service
estate and records only method names, streaming mode, timeout, and header keys.

Unknown ergonomic methods default to unsafe (one attempt), and raw generated
calls are never implicitly retried. The SDK has no PostgreSQL, Pub/Sub, or GCS
client dependency: persistence, event delivery, and artifact storage remain
server-side concerns behind generated RPCs. The future public HTTP SDK remains
a separate package and compatibility surface.

The sole intentional raw-only RPC is `RunService.ExpireAttemptLeases`, a
control-plane reconciler primitive. Application code should use the fenced
run/attempt lifecycle helpers and must not infer an ergonomic compatibility or
retry promise from `client.raw`.

The descriptor-bound coverage gate fixes the current surface at 15 services
and 132 RPCs: 127 unary and five server-streaming, with 131 ergonomic methods
and one reviewed raw-only method. The exported `paginate` async generator works
with any ergonomic list method, preserves opaque tokens exactly, rejects cursor
loops, observes cancellation between pages, and raises a typed pagination-limit
error instead of presenting a bounded partial traversal as complete.

`client.artifacts.downloadFile(artifact, path)` stages a private mode-0600 file
beside the destination, verifies the complete immutable digest, and atomically
publishes without overwriting an existing path. Successful link creation is the
commit point; corruption, cancellation, and write failure before it leave the
destination absent or unchanged.

Persist each mutation's `idempotencyKey` with durable caller intent before
submission so crash/restart retries reuse the same identity. Consume resumable
updates through `client.operations.watch` and propagate its `AbortSignal`.
Runtime checks cover credentials, scope, correlation metadata, deadlines, page
budgets, stream identity, and artifact integrity; generated Protobuf-ES types
and the server own ordinary request-field constraints.

Run focused checks with `pnpm test`, `pnpm run typecheck`, and `pnpm run lint`.
