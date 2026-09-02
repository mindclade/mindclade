# Mindclade internal Rust SDK

This private, unpublished crate is the ergonomic Rust facade over the
authoritative generated Prost/Tonic bindings. It is for Mindclade services,
workers, training code, tools, and internal applications only.

The dependency direction is deliberately one way:

```text
protocols/proto -> protocols/generated/rust -> internal/sdk/rust -> consumers
```

Generated messages remain the only wire and resource models. This crate adds
validated environment configuration, secure transport, workload-identity
credential injection, bounded retries, deadlines, request metadata,
normalized errors, long-running-operation helpers, artifact alias resolution,
and injectable transport fakes. It does not log credentials or serialized
requests and responses.

Production callers can use `GcpWorkloadIdentityProvider`, which obtains an
audience-bound identity token from the fixed GCE/GKE metadata endpoint with a
bounded exchange, refresh skew, per-audience cache, and concurrency-safe
singleflight. Secure clients require a token provider. The only credential-free
mode is `Config::local_insecure_builder`, which is restricted to an explicit
plaintext loopback endpoint and cannot be combined with credentials.

Operation watches resume from the last accepted sequence after bounded
consecutive retryable failures, retain one total deadline, reject malformed or
cross-operation updates, and observe local cancellation while authenticating,
connecting, sleeping, and reading. `wait` and `watch_until_done` return
`OperationWaitError`; failed and cancelled remote operations are represented by
`OperationFailure`, which retains the generated `Operation` for deliberate
inspection while keeping its error payload out of automatic debug/display
output.

The future public HTTP SDK is a separate compatibility surface and must not
depend on this crate or expose internal RPC contracts.

`Client::generated_clients().await` exposes all fourteen internal generated
Tonic service clients for uncommon workflows. Those clients are wrapped in a
policy interceptor, so even a bare generated request receives short-lived
workload identity, a bounded default deadline, tenant/project/principal
expectations, request identity, and trace metadata. Reacquire the client set
when its credential enters the refresh window. `Client::authorized_request`
adds explicit per-call behavior when needed. The ergonomic Training,
Operations, and Artifacts APIs remain preferred because they also own bounded
retry and response-invariant checks.

`RecordingTransport` wraps the generated-type-only `RpcTransport` seam and
records method names plus metadata keys without retaining payloads or header
values. Unknown ergonomic methods default to unsafe (one attempt); raw
generated methods are never implicitly retried. The SDK has no PostgreSQL,
Pub/Sub, or GCS client dependency—durability, event publication, and artifact
storage remain server responsibilities behind generated RPC contracts.
