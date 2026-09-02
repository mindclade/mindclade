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
Set `ConfigBuilder::audience` to the verifier's exact configured OIDC audience.
If omitted, the SDK derives the endpoint's canonical HTTPS origin: the host is
lowercase, IPv6 remains bracketed, default `:443` is omitted, and a non-default
port is retained.

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

`Client::generated_clients().await` exposes all fifteen internal generated
Tonic service clients for uncommon workflows. Those clients are wrapped in a
policy interceptor, so even a bare generated request receives short-lived
workload identity, a bounded default deadline, tenant/project/principal
expectations, request identity, and trace metadata. Reacquire the client set
when its credential enters the refresh window. `Client::authorized_request`
adds explicit per-call behavior when needed. The ergonomic Training,
Operations, and Artifacts APIs remain preferred because they also own bounded
retry and response-invariant checks.

The descriptor-bound coverage gate fixes the current surface at 15 services
and 132 RPCs: 127 unary and five server-streaming, with 131 ergonomic methods
and one reviewed raw-only method. Every generated Tonic client uses an 8 MiB
encode/decode ceiling, which admits a valid 4 MiB artifact chunk plus protobuf
framing while remaining bounded.

Every list method returns `Pages<T>`, a lazy cursor rather than a single
detached page. `Pages::try_next` walks items transparently across pages,
`Pages::next_page` returns a whole `Page<T>` with its opaque
`next_page_token`, `has_next_page`, server read time, and request identity,
and `Pages::try_collect` drains the remainder. Scope and page-size validation
stays eager, so an invalid request still fails before any RPC is issued, and
every per-page response invariant is re-checked on every page rather than only
the first. Cursors preserve opaque tokens exactly, reject cursor loops as a
protocol error, and report page or item budget exhaustion as a typed
non-retryable error. The defaults are 100 items per page and budgets of 100
pages and 10,000 items, with hard caps of 1,000 items per page, 1,000 pages,
and 1,000,000 items; `Pages::with_limits` narrows the budgets per traversal.
The lower-level `paginate`/`Paginator::try_next` helpers remain for callers
paginating something the facade does not own.

`Client::send_with_metadata` sends any generated unary request that has a
transport seam under the same identity, deadline, retry-safety, and
sanitization policy as the ergonomic facades, and returns `Response<T>`. That
wrapper exposes `into_inner`, `status`, `request_id`, `trace_id`, and
`safe_metadata`. `SafeMetadata` is a fixed, cross-language allowlist —
`content-type`, `date`, `grpc-status`, `retry-after-ms`, `x-mindclade-sdk`,
`x-mindclade-should-retry`, `x-request-id`, and `x-trace-id` — filtered again
through the credential denylist, so `authorization`, `x-mindclade-lease-token`,
cookies, and any `*token*`/`*secret*`/`*key*`/`*auth*`/`*credential*`/
`*password*` header can never surface through it.

`RecordingTransport` wraps the generated-type-only `RpcTransport` seam and
records method names plus metadata keys without retaining payloads or header
values. Unknown ergonomic methods default to unsafe (one attempt); raw
generated methods are never implicitly retried. The SDK has no PostgreSQL,
Pub/Sub, or GCS client dependency—durability, event publication, and artifact
storage remain server responsibilities behind generated RPC contracts.

The sole intentional raw-only RPC is `RunService.ExpireAttemptLeases`, a
control-plane reconciler primitive. Application code should use the fenced
run/attempt lifecycle helpers and must not infer an ergonomic compatibility or
retry promise from the generated escape hatch.

`client.artifacts().download_file(&artifact, path, options)` stages a private
mode-0600 file beside the destination, verifies the complete immutable digest,
and atomically publishes without overwriting an existing path. Successful link
creation is the commit point; corruption, cancellation, and write failure
before it remove staging and leave the destination absent or unchanged.

Persist the key passed to `SubmitOptions::new` with durable caller intent before
submission so crash/restart retries reuse the same identity. Consume resumable
updates through `client.operations().watch` and propagate its cancellation
token. Runtime checks cover credentials, scope, correlation metadata, deadlines,
page budgets, stream identity, and artifact integrity; generated Prost types
and the server own ordinary request-field constraints.

Run focused tests with `cargo test -p mindclade-internal-sdk` using the pinned
Rust toolchain.
