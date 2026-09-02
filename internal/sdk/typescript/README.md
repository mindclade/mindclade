# Mindclade internal TypeScript SDK

This private package is the handwritten TypeScript developer experience over
the authoritative generated Protobuf-ES and Connect contracts:

```text
protocols/proto
    -> protocols/generated/typescript
    -> internal/sdk/typescript
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
