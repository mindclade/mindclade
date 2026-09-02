# Mindclade internal Go SDK

`github.com/mindclade/mindclade/internal/sdk/go/mindclade` is the private
ergonomic Go facade over this repository's generated internal gRPC contracts.
It is a call-site layer, not a second wire-model layer, and it cannot be
imported from outside this repository because its path sits beneath the
repository-root `internal/` tree.

## Installation

There is nothing to install. The package is part of the repository's single Go
module, so an in-repository consumer imports it directly:

```go
import "github.com/mindclade/mindclade/internal/sdk/go/mindclade"
```

Bazel consumers depend on `//internal/sdk/go/mindclade:mindclade`. Run
`internal/sdk/go/mindclade/scripts/bootstrap` once to resolve module
dependencies and audit the pinned toolchain.

## Usage

```go
client, err := mindclade.New(
    mindclade.WithEnvironment(mindclade.Development),
    mindclade.WithTenantProject("tenants/acme", "projects/fold"),
    mindclade.WithWorkloadIdentity(),
)
if err != nil {
    return err
}
defer client.Close()

operation, err := client.Training.Submit(ctx, mindclade.TrainingJob{
    Model:          mindclade.Model("nova-1"),
    Dataset:        mindclade.Dataset("datasets/pdb-2026-08"),
    Recipe:         mindclade.Recipe("pretrain-v4"),
    IdempotencyKey: durableIntentKey,
})
```

`New` performs credential discovery but does not require the endpoint to be
reachable; the first RPC is the first network contact. `New` never reads the
process environment — see [Configuration and environment
variables](#configuration-and-environment-variables).

One `Client` is safe for concurrent use and owns one gRPC connection. The
fifteen services hang off it as fields: `Admin`, `Agents`, `Approvals`,
`Artifacts`, `Datasets`, `Evaluations`, `Experiments`, `Inference`, `Jobs`,
`Models`, `Operations`, `Policies`, `Runs`, `Training`, and `Workflows`.

## Request and response types

**The generated protobuf messages are the models.** A method that takes a
request takes the generated request message, and a method that returns a
resource returns the generated resource message. The SDK defines no parallel
wire type and never will; where it adds a type, that type carries call
mechanics (a page cursor, a watcher, a typed error) rather than field data.

A handful of small value types — `TrainingJob`, `Model`, `Dataset`, `Recipe`,
`WaitOptions`, `ArtifactUploadOptions` — exist only to name the arguments of a
composite helper. They are inputs to a call, not representations of a message.

An unrecognised enum value is never authority for an action. Code that switches
on a generated enum must treat `UNRECOGNIZED` and unknown numbers as a refusal,
not as a default-allow.

## Pagination

Every ergonomic list method returns a page object that **embeds** its generated
list response. Promoted accessors keep working unchanged —
`page.GetPage().GetNextPageToken()`, `page.GetArtifacts()` — and the page adds
cursor-scheme traversal on top:

```go
page, err := client.Operations.List(ctx, request)
if err != nil {
    return err
}

for operation, err := range page.All(ctx) { // every item, across every page
    if err != nil {
        return err
    }
    use(operation)
}
```

Page-level access is preserved rather than hidden behind the iterator:

```go
for page.HasNextPage() {
    page, err = page.NextPage(ctx)
    if err != nil {
        return err
    }
    use(page.Items())          // this page only
    use(page.PageMetadata())   // the generated common.v1.PageResponse
}
```

The cursor scheme is `page_token` in, `next_page_token` out. Tokens are opaque:
the SDK forwards them byte-for-byte and never parses, trims, or normalizes one.
A server that repeats a cursor terminates the traversal with `data_loss` rather
than looping forever.

`All` walks the collection under an explicit budget — **100 pages and 10,000
items** by default, hard-capped at **1,000 pages and 1,000,000 items** — which
`WithPaginationLimits` narrows or widens within those caps. Exceeding the budget
ends the sequence with `resource_exhausted`. `NextPage` fetches exactly one
explicitly requested page and is bounded by the caller instead; it returns a nil
page and a nil error at the end of a collection.

Each fetched page re-invokes the owning list method with the caller's original
request and options, so per-page scope, page-size, and cross-project validation
runs again on every page. Retraversal is not a validation bypass.

`Paginate` remains exported for traversing a collection the SDK does not yet
model as a list method. It is the same engine `All` runs on.

## Long-running operations

Durable work returns a `jobv1.Operation`. `OperationService` exposes one uniform
verb set, and every verb accepts `RequestOption`s:

| Verb | Purpose |
| --- | --- |
| `Get` | read current durable state once |
| `Wait` | poll to a terminal state |
| `Watch` | stream transitions from a sequence |
| `Cancel` | request cancellation with an etag and a reason |
| `ResumeWatch` | stream transitions from a persisted cursor |

```go
operation, err := client.Operations.Wait(ctx, name, mindclade.WaitOptions{})
var failure *mindclade.OperationError
if errors.As(err, &failure) {
    // failure.Operation is the generated terminal operation, with its own
    // authoritative state, result, and error.
}
```

Options are applied **once** per logical call, so every poll of a `Wait` and
every reconnect of a `Watch` share one request identity. `Inference`,
`Training`, and `Workflows` expose `ResumeWatch` on the same contract.

## Streaming

Server streaming stays native gRPC. There is no SSE client here; SSE is the
gateway's public projection of exactly one RPC and is out of scope for the
internal SDKs.

Every streaming reader in the package is the same generic `StreamWatcher`.
`Watcher`, `InferenceWatcher`, `TrainingWatcher`, and `WorkflowWatcher` are
aliases of it, so their message and cursor types are unchanged.

`Operations.Watch` opens a stream from a sequence number; `Operations.ResumeWatch`
opens the same stream from a cursor persisted by an earlier reader. Both return
the same watcher:

```go
watcher, err := client.Operations.ResumeWatch(ctx, name, persistedCursor)
if err != nil {
    return err
}
defer watcher.Close()

for watcher.Next() {
    use(watcher.Current())
}
if err := watcher.Err(); err != nil { // nil at a clean end of stream
    return err
}
persist(watcher.Cursor())
```

`Recv` remains available and returns `io.EOF` at a clean end of stream. A
watcher reconnects **only inside the caller's remaining deadline** — it never
sleeps past the budget it was given — and always resumes from the last
*acknowledged* cursor, so no message is replayed or skipped. Per-domain sequence
and identity checks survive the unification: operations require a strictly
increasing sequence, while inference, training, and workflow runs require a
strictly contiguous successor.

`Next` and `Recv` are not safe to call concurrently on one watcher. `Close` is
idempotent.

## Errors

Every failure is a `MindcladeError`. `*Error` is the base carrier and eleven
concrete types wrap it, so `errors.As` reaches whichever form the caller wants:

| Type | Raised for |
| --- | --- |
| `*AuthenticationError` | `unauthenticated`, credential acquisition failure |
| `*AuthorizationError` | `permission_denied`, policy denial |
| `*ValidationError` | `invalid_argument`, `out_of_range` |
| `*ConflictError` | `aborted`, `already_exists`, `failed_precondition` |
| `*NotFoundError` | `not_found` |
| `*RateLimitError` | `resource_exhausted` **with** a retry hint |
| `*QuotaError` | `resource_exhausted` **without** a retry hint |
| `*RetryableServiceError` | `unavailable`, and `internal` classified retry-safe |
| `*OperationFailedError` | a terminal long-running failure |
| `*CancelledError` | `canceled` |
| `*TransportError` | everything else: `unknown`, `data_loss`, `unimplemented`, `deadline_exceeded`, and `internal` that is not retry-safe |

```go
var conflict *mindclade.ConflictError
if errors.As(err, &conflict) {
    log.Info("stale revision", "revision", conflict.Revision())
}

var base mindclade.MindcladeError // matches every SDK error
if errors.As(err, &base) {
    requestID, traceID := base.RequestIdentity()
    attempts, cumulativeDelay := base.RetryOutcome()
}
```

Every error carries a stable code, a safe message, retryability, a retry-after
hint, request id, trace id, operation id, field violations, precondition
violations, quota state, fence state, conflict revision, and a diagnostic
reference. Violations are the generated `mindclade.common.v1` messages.

**Errors are sanitized.** Raw SQL, SQLSTATE, Pub/Sub internals, provider
strings, and stack traces never reach a caller. A structured server
`ErrorDetail` is surfaced through typed fields only; its free-text message is
discarded, and violation counts and string lengths are bounded so a broken or
hostile server cannot make one error unbounded. An unrecognised `RetryClass`,
including the generated `UNRECOGNIZED` sentinel, maps to `RetryNever` and can
never authorize a retry.

## Retries

One predicate governs every retry decision in the package: the unary
interceptor, watcher reconnects, and long-running resumption all resolve through
it. The policy is fixed at **4 attempts**, backoff **100ms to 2s**, with **full
jitter** — uniform over `[0, min(cap, base * 2^n)]` — drawn from a
cryptographically seeded source.

Eligibility is per-RPC and never inferred from the payload:

- **safe** — read RPCs; retried.
- **idempotent** — mutations whose request embeds a validated `CommandContext`;
  retried.
- **unsafe** — never retried implicitly.

`WithUnsafeRetryOfNonIdempotentRPC()` is the only way to retry an RPC the policy
calls unsafe. It is deliberately a named option rather than a bare boolean, and
it is powerless over the never-retry list.

Every attempt sends `x-mindclade-retry-count` (0-based) and
`x-mindclade-timeout-ms` (remaining budget). Two response trailers are honoured:
`x-mindclade-should-retry` overrides the decision in **both** directions, and
`retry-after-ms` replaces the computed delay, clamped to the configured maximum
backoff. A server override can suppress a retry the policy would have allowed;
it can never promote a non-idempotent or denylisted RPC.

The outcome is observable on the returned error: `Attempts`, `CumulativeDelay`,
and the final cause.

## Timeouts

`WithTimeout` sets a **total budget** for one logical call. Every attempt, every
backoff wait, and credential acquisition share it; it is not a per-attempt
deadline. It only ever narrows: it never extends a deadline the caller's context
already imposes.

```go
page, err := client.Operations.List(ctx, request,
    mindclade.WithTimeout(2*time.Second),
    mindclade.WithMaxAttempts(2),
)
```

`WithMaxAttempts` likewise only narrows. It cannot make an ineligible method
retryable. A call that exhausts its budget mid-backoff returns
`deadline_exceeded` carrying the attempt count and cumulative delay, and
`errors.Is(err, context.DeadlineExceeded)` still holds.

Client-wide defaults are `WithDefaultTimeout` (20s per RPC),
`WithOperationTimeout` (30m for long-running work), and `WithPollInterval`
(500ms).

## Raw responses

A successful call otherwise returns no transport detail at all, so
`WithResponseMetadata` is how a caller correlates one:

```go
var response mindclade.ResponseMetadata
operation, err := client.Operations.Get(ctx, name,
    mindclade.WithResponseMetadata(&response),
)
// response.Status, response.RequestID, response.TraceID, response.Metadata
```

`CaptureResponseMetadata(ctx)` and `ResponseMetadataFromContext(ctx)` do the
same through a context when threading a record through a call chain is
impractical.

`Metadata` is a **strict allowlist**, identical in all four internal SDKs:
`x-request-id`, `x-trace-id`, `x-mindclade-should-retry`, `retry-after-ms`,
`x-mindclade-retry-count`, `content-type`, `grpc-status`, `grpc-message`,
`date`, and `server`. A credential denylist is applied on top of the allowlist,
so `authorization`, `x-mindclade-lease-token`, cookies, and anything matching
`*token*`, `*secret*`, `*key*`, `*credential*`, `*password*`, or `*auth*` cannot
surface even if the allowlist were later mistaken. `grpc-message` is allowlisted
as a key, but its value is always the sanitized message, never raw server prose.
Values are bounded and stripped to printable ASCII.

The correlation header is `x-request-id`, in both directions. The former
`x-mindclade-request-id` alias is retired: it is neither read nor emitted, and
it is stripped from outgoing metadata rather than merely ignored. When a server
echoes no request id, the SDK reports the id it sent, so a successful call is
always correlatable.

## Escape hatches and interceptors

```go
client, err := mindclade.New(
    mindclade.WithInterceptor(callerUnaryInterceptor),
    mindclade.WithStreamInterceptor(callerStreamInterceptor),
    mindclade.WithDefaultMetadata(map[string][]string{"x-team": {"fold"}}),
)
```

Caller interceptors are chained **inside** the SDK's own policy interceptor, and
credential injection happens beneath the entire chain at the transport. A caller
interceptor therefore cannot observe or forge an `authorization` header — this
is a structural property of where gRPC applies per-RPC credentials, not a
convention.

`WithMetadata` (one call) and `WithDefaultMetadata` (every call) attach caller
metadata. A credential-bearing key, a reserved SDK key, a `grpc-` or `-bin` key,
an unbounded value, or a structurally invalid key is rejected with
`invalid_argument` rather than dropped silently.

`client.Transport()` exposes the generated clients for an activated RPC that has
no ergonomic helper yet. It stays inside the repository and changes no protobuf
authority. `RunService.ExpireAttemptLeases` is the one intentional raw-only RPC:
a control-plane reconciler primitive that is **never retried under any
override**. Application code should use the fenced run and attempt lifecycle
helpers instead.

## Configuration and environment variables

`New` **never reads the process environment.** `FromEnvironment()` is the only
path that does, and it must be passed explicitly:

```go
client, err := mindclade.New(
    mindclade.FromEnvironment(),
    mindclade.WithWorkloadIdentity(),
)
```

| Variable | Effect |
| --- | --- |
| `MINDCLADE_ENVIRONMENT` | `development`, `staging`, `production`, or `local` |
| `MINDCLADE_ENDPOINT` | explicit endpoint, overriding the environment default |
| `MINDCLADE_TENANT_ID` | tenant scope asserted on every call |
| `MINDCLADE_PROJECT_ID` | project scope asserted on every call |
| `MINDCLADE_PRINCIPAL_ID` | principal scope asserted on every call |
| `MINDCLADE_AUDIENCE` | workload-identity token audience |
| `MINDCLADE_LOG` | `debug`, `info`, `warn`, `error`, or `off` |

`FromEnvironment` fills only fields that are still empty, so an explicit `With*`
option wins on either side of it.

**No credential is ever read from the environment, on any path, in any
language.** Credentials come from Application Default Credentials only when
`WithWorkloadIdentity()` is explicit, and that option mints a short-lived
workload-identity ID token rather than a broad cloud-platform access token. The
audience must match the control-plane verifier; otherwise it is derived from the
secure endpoint as an HTTPS origin with a default `:443` omitted. TLS is
mandatory outside the `local` loopback testing profile.

`x-mindclade-sdk` carries structured, bounded platform metadata: `language`,
`version`, `os`, `arch`, `runtime`, and `runtime_version`.
`WithOmitPlatformMetadata()` reduces it to language and version.

## Logging

`WithObserver` receives `RPCStarted` and `RPCFinished`. An observer that also
implements `RequestObserver` receives the complete `RPCEvent` for every attempt:
method, attempt, elapsed, status, request id, trace id, retry-after, and
metadata **key names only**.

`WithLogger(logger, level)` bridges the same seam to `log/slog`, and
`MINDCLADE_LOG` selects a `slog.Default()`-backed logger through
`FromEnvironment` when the caller has not installed an observer of their own.

Payloads, bearer tokens, lease tokens, and metadata values are never emitted.
The event type carries key names rather than headers, so this is enforced by
construction rather than by discipline. An observer that panics cannot change an
RPC outcome.

## Versioning

Internal SDKs carry **no SemVer line**. `Version` in `config.go` is the single
revision source, stamped into both the gRPC user agent and `x-mindclade-sdk`;
nothing else in the package declares a version. It is a build fingerprint, not
a compatibility promise.

The unit of compatibility is a **source revision** of this monorepo. See
[`CHANGELOG.md`](CHANGELOG.md), which is keyed by revision rather than by
version.

## Status

Pre-production, maturity `internal`, activation wave 1, not connected. The
descriptor-bound coverage gate fixes the current surface at **15 services and
132 RPCs**: 127 unary and five server-streaming, with 131 ergonomic methods and
one reviewed raw-only method. `internal/sdk/go/api.md` is the generated
per-RPC reference.

---

## Package contract (appendix A08)

### Purpose and non-goals

**Purpose.** Give in-repository Go callers one governed, ergonomic call site for
the internal control plane: credential injection, tenant and project scope,
correlation metadata, retry and timeout policy, pagination, long-running
operations, streaming, and sanitized errors — implemented once, identically to
the Python, Rust, and TypeScript facades.

**Non-goals.** It does not define wire types; the generated protobuf messages
are the models. It does not validate ordinary request fields; the generated
types and the server own those. It is not a public SDK, is never published, and
is not a gateway client — there is no SSE reader here. It does not decide
authorization; it transports assertions the server verifies.

### Owner

`developer-experience` (`@mindclade/product-engineering`), with `security` as
the security reviewer. Declared in `component.yaml` as component
`internal-sdk-go`.

### Public entrypoints

- `New(...Option) (*Client, error)` and `NewWithTransportForTesting`.
- `Client` and its fifteen service fields.
- `Client.Transport()` for reviewed raw-only RPCs.
- `Option` constructors (`With*`, `FromEnvironment`) for client configuration.
- `RequestOption` constructors (`With*`) for per-call configuration.
- `MindcladeError`, `*Error`, and the eleven typed errors.
- `StreamWatcher` and its four aliases.
- `Page[T]`, `PaginationLimits`, `Paginate`, and the per-domain page types.
- `ResponseMetadata`, `Observer`, `RequestObserver`, `RPCEvent`, `Version`.

Everything else in the package is implementation and may change without notice.

### Dependency restrictions

The package depends on the generated protobuf bindings under
`protocols/generated/go/...`, on `libs/go/numconv` for checked integer
narrowing, and on gRPC, protobuf, `oauth2`, and `google.golang.org/api/idtoken`.
It takes no other third-party dependency.

It must not depend on a service, worker, application, or tool package: it sits
below all of them, and `tools-mindcladectl` consumes it rather than the other
way round. It must not hand-write a message type that the protobuf estate
already owns, and it must not read the generated packages' internals.

`component.yaml` declares no typed dependency edges, and that is a tooling
limit rather than a claim of independence. The generated protobuf estate is not
a catalogued component, so there is no identity to point an edge at; and
`tools/repo/dependency_policy.py` does not map the `internal/` path prefix in
its layer order, so it reads the forward `internal/sdk` to `libs` edge as
backward and rejects it. The restrictions stated above are the contract.

### Data classifications handled

`internal` — control-plane resource metadata, operation and run state, resource
names, and correlation identifiers. The package neither persists nor logs this
data; it transports it.

It never handles credentials as data: tokens are minted beneath the interceptor
chain and are excluded from every observable surface by an allowlist and a
denylist that both exclude credential-bearing keys.

Artifact payload bytes pass through `Artifacts.DownloadFile` and the upload
helpers without inspection, so a destination file inherits the artifact's own
classification. Classify the destination accordingly; the SDK cannot.

### Build and test commands

| Command | Runs |
| --- | --- |
| `scripts/bootstrap` | `go mod download`, `go mod verify`, then `just bootstrap` |
| `scripts/build` | `go build` and `go vet` over `./internal/sdk/go/...` |
| `scripts/format` | `golangci-lint fmt` |
| `scripts/lint` | `golangci-lint fmt --diff` and `golangci-lint run` |
| `scripts/test` | `go test -count=1 ./internal/sdk/go/...`, arguments forwarded |

Set `MINDCLADE_BAZEL=1` to additionally run the Bazel target CI treats as the
authority (`//internal/sdk/go/mindclade:mindclade` and `:mindclade_test`). The
repository-wide `just format`, `just lint`, and `just governance` recipes remain
the authority; these scripts narrow them to this package.

### Compatibility contract

Consumers are pinned to a source revision of this monorepo and build this facade
from that revision's sources together with that revision's generated contracts.
There is no released artifact, so there is no cross-revision compatibility
window to honour and no deprecation period to serve.

What is guaranteed within a revision: the generated messages are the models, so
a caller can always drop to `Client.Transport()` and keep the same types;
opaque tokens are forwarded byte-for-byte; and the metadata key vocabulary,
retry policy, response-metadata allowlist, and credential denylist are identical
across the Go, Python, Rust, and TypeScript facades. A change to any of those is
a four-language change.

Breaking changes are recorded in `CHANGELOG.md` under the revision that made
them.

### Failure modes

| Failure | Behaviour |
| --- | --- |
| Endpoint unreachable | `unavailable`, retried under policy, then `*RetryableServiceError` |
| Total budget exhausted | `deadline_exceeded` with attempts and cumulative delay; `errors.Is(err, context.DeadlineExceeded)` holds |
| Credential acquisition fails | `*AuthenticationError`; the attempt is inside the same total budget |
| Scope assertion rejected | `*AuthorizationError`; no retry |
| Stale revision or etag | `*ConflictError` carrying the conflict revision |
| Quota or rate limit | `*RateLimitError` when the server hinted a retry-after, `*QuotaError` when it did not |
| Cursor repeated by the server | traversal ends with `data_loss` rather than looping |
| Traversal budget exceeded | sequence ends with `resource_exhausted` |
| Stream drops | reconnect from the last acknowledged cursor, only inside the remaining deadline |
| Stream sequence gap or identity mismatch | `data_loss`; the watcher does not silently resynchronize |
| Artifact digest mismatch | download fails and the destination is absent or unchanged |
| Observer panics | recovered; the RPC outcome is unaffected |

Cancellation is the caller's context. Cancelling it stops polling, streaming,
and retrying; `Close` releases the watcher and the client releases its
connection and any SDK-owned token provider.

`Artifacts.DownloadFile` stages into a private same-directory file, verifies the
complete immutable digest, and publishes with an atomic no-clobber link. It
never replaces an existing path. Successful link creation is the commit point;
corruption, cancellation, or a write failure before that point leaves the
destination absent or unchanged.

Persist a command's `IdempotencyKey` with the caller's durable intent *before*
submission, so a crash and restart reuse the same identity instead of creating a
second unit of work.

### Retryable versus terminal errors

| Classification | Codes | Behaviour |
| --- | --- | --- |
| Retryable | `unavailable`, `resource_exhausted`, `aborted`, `deadline_exceeded` | retried on safe and idempotent RPCs; 4 attempts, 100ms to 2s, full jitter |
| Terminal | every other code | never retried implicitly |
| Server override | any code | the `x-mindclade-should-retry` trailer wins in both directions, within the rules below |
| Never | `RunService.ExpireAttemptLeases` | never retried, under any override |

A server override can only act on an RPC the method policy already considers
eligible. It can suppress a retry unconditionally; it can permit one only for a
safe or idempotent RPC, and never for the never-retry list.

### Graduation status

Pre-production, `internal`, activation wave 1, `connected: false`, no production
authority — the state recorded in `component.yaml`. Graduation requires a
connected control plane and a stable descriptor surface; until then the
descriptor-bound coverage gate, the four-language conformance suite under
`tests/conformance`, and this package's own tests are the qualification signal.
Nothing here is deprecated, and no entrypoint is scheduled for removal.
