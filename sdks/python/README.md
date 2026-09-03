# Mindclade internal Python SDK

`mindclade-internal-sdk` is the private, hand-written Python developer
experience over Mindclade's authoritative generated internal contracts. It is
for Mindclade services, workers, training code, tools, and internal
applications. It is not the future public API and is never published to a
package registry.

```text
protocols/proto
    -> protocols/generated/python      (protobuf messages and gRPC stubs)
    -> sdks/python             (this package)
    -> internal services, tools, workers, and applications
```

Generated messages remain the only request, response, resource, and event
models; this package never declares a parallel hand-written one. What the facade
adds on top: secure channel setup, injectable short-lived workload identity,
correlation and tenancy metadata, total deadline budgets, bounded retries behind
a single eligibility predicate, a sanitized error hierarchy, transparent
pagination, one resumable watcher, uniform long-running-operation verbs,
raw-response access, an interceptor seam, and verified artifact download.

PostgreSQL durable state and Pub/Sub event delivery stay behind the control
plane and are never accessed directly by this SDK.

---

## Installation

The package is private and is never installed from a registry. It is consumed
from the workspace, pinned to a source revision of this monorepo, by putting it
and the generated bindings on the interpreter path:

```bash
PYTHONPATH=sdks/python:protocols/generated/python python
```

Bazel consumers depend on the library target instead:

```python
deps = ["//sdks/python:mindclade_internal_sdk"]
```

The five packaging entry points wrap the repository-wide commands for this
package alone:

```bash
sdks/python/scripts/bootstrap   # uv sync --frozen + toolchain audit
sdks/python/scripts/build       # compile + import the public surface
sdks/python/scripts/lint        # ruff format --check, ruff check, pyright
sdks/python/scripts/format      # ruff format
sdks/python/scripts/test        # the unittest suite
```

## Usage

```python
from mindclade_internal_sdk import (
    Client,
    ClientConfig,
    Environment,
    GoogleWorkloadIdentityProvider,
)
from mindclade_internal_sdk.resources import artifact_reference, resource_reference


config = ClientConfig(
    environment=Environment.DEVELOPMENT,
    tenant_id="tenant-01",
    project_id="project-01",
    principal_id="training-orchestrator",
    token_provider=GoogleWorkloadIdentityProvider(
        "https://control-plane.development.mindclade.internal"
    ),
)

with Client(config) as client:
    operation = client.training.submit(
        "pretrain-v4",
        training_recipe=artifact_reference(
            digest="sha256:" + "1" * 64,
            media_type="application/vnd.mindclade.training-recipe.v1+json",
            size_bytes=1024,
        ),
        dataset_release=resource_reference(
            name="datasetReleases/pdb-2026-08", resource_type="dataset_release"
        ),
        model_release=resource_reference(
            name="modelReleases/nova-1", resource_type="model_release"
        ),
    )
    terminal = client.operations.wait(operation.operation_id)
```

`AsyncClient` has the same service layout and requires a provider with
`async get_token(*, timeout: float)`. Use
`AsyncGoogleWorkloadIdentityProvider` for ADC-backed asynchronous clients.
Custom synchronous providers implement `get_token(*, timeout: float)` and must
honor that remaining budget for every external exchange. Never wrap the
synchronous client in an event loop.

The Google provider's audience argument is explicit and must exactly match the
control-plane verifier. `ClientConfig.audience` preserves an explicit override;
when omitted it resolves to the endpoint's canonical HTTPS origin (lowercase
host, bracketed IPv6, default `:443` omitted, non-default port retained). The
built-in providers expose their bound audience, and configuration fails closed
if it differs from the client audience. Custom providers remain responsible for
minting tokens for that exact value.

Fifteen ergonomic namespaces hang off both clients — `admin`, `agents`,
`artifacts`, `datasets`, `evaluations`, `experiments`, `inference`, `jobs`,
`models`, `operations`, `policies`, `runs`, `training`, `workflows`, and
`approvals` — plus `generated`, the escape hatch described below.

## Request and response types

The generated protobuf types **are** the models. Ergonomic methods accept and
return them directly; nothing in this package re-encodes a wire value into a
hand-written shape, and no method returns a dictionary or a namedtuple standing
in for a message.

`mindclade_internal_sdk.resources` exists so a consumer builds those values
without depending on generated package locations: `artifact_reference`,
`resource_reference`, and their peers return the generated types. Ordinary
request-field constraints belong to the generated types and the server; this SDK
validates only what it owns — credentials, scope, correlation metadata,
deadlines, page budgets, stream identity, and artifact integrity.

Unknown enum values are never authorizing. An `UNRECOGNIZED` or unspecified
value maps to `"unknown"` and never widens retryability or permits an action.

## Pagination

Every ergonomic list method returns a `Page` (or an `AsyncPage` on
`AsyncClient`) instead of the bare generated `List*Response`:

```python
for job in client.jobs.list():  # iterates every page transparently
    handle(job)

page = client.jobs.list()  # page-level access is still available
page.items  # this page's items
page.has_next_page  # whether a further cursor exists
page.next_page()  # the following page, same validations
page.pages()  # this page and every following page
page.page.next_page_token  # the generated response, delegated
```

```python
async for job in client.jobs.list():  # AsyncClient
    await handle(job)
```

A page delegates unknown attribute reads to the generated `List*Response` it was
built from, so `page.jobs`, `page.page.next_page_token`, and `page.read_time`
keep working and the generated message stays the only wire model.

The cursor scheme is `page_token` -> `next_page_token`, opaque throughout.
Traversal forwards a token verbatim, never parses or rewrites one, rejects
cursor loops and non-text cursors with `ProtocolError`, and re-runs each page's
identity and scope checks — a cross-project item on page 9 fails exactly as it
would on page 1.

Budgets are explicit. `PaginationLimits` defaults to 100 items per page, 100
pages, and 10,000 items per traversal, with hard caps of 1,000 pages, 1,000
items per page, and 1,000,000 items:

```python
from mindclade_internal_sdk import PaginationLimits

page = client.jobs.list(limits=PaginationLimits(max_items=500))
```

Exceeding a budget raises `PaginationLimitError` rather than implying that a
bounded partial result is complete. `paginate` and `apaginate` remain exported
for a caller driving `client.generated` or a hand-rolled fetch loop.

## Long-running operations

Durable operations expose one uniform verb set on both clients:

| Verb | Behaviour |
|---|---|
| `client.operations.get(name)` | One read of the current operation. |
| `client.operations.wait(name)` | Poll to a terminal state inside the caller's budget. |
| `client.operations.cancel(name)` | Request cancellation; the server owns the outcome. |
| `client.operations.watch(name)` | Stream transitions from the beginning. |
| `client.operations.resume_watch(name, after_sequence=n)` | Re-attach from a cursor the caller durably recorded. |

`after_sequence` is required on `resume_watch`, so a resume can never silently
replay from the beginning.

```python
with client.operations.watch(name, timeout=600) as events:  # also `async with`
    for event in events:
        checkpoint(events.cursor)  # durable cursor
        if event.operation.done:
            break

stream = client.operations.resume_watch(name, after_sequence=checkpointed)
```

A terminal failed operation raises `OperationFailedError`, which carries the
operation id and the typed fields projected from the server's `ErrorDetail`.

## Streaming

Server streaming stays **native gRPC**. There is no SSE client in this SDK: SSE
is the gateway's public projection of `WatchOperation` alone, and it is out of
scope here.

`client.operations.watch`, `client.training.watch`, `client.inference.watch`,
and `client.workflows.watch` all run on one generic resumable watcher. It:

- reconnects **only** inside the caller's remaining deadline, never restarting a
  fresh budget;
- resumes from the **last acknowledged cursor**, not the last sequence the
  server sent;
- carries the caller's lease token, idempotency key, request id, and trace id
  onto every attempt;
- re-runs each domain's sequence and identity checks after a reconnect — a
  sequence that fails to advance, an identity that drifts, or a non-contiguous
  transition is a terminal `ProtocolError`, never a silent resync;
- raises the failure that actually ended the stream once the retry budget is
  spent.

The returned stream is an iterator, a context manager whose exit releases the
live call, and it exposes `request_id`, `trace_id`, and `cursor`. Every watcher
accepts `options=CallOptions(...)`, whose timeout narrows the watch budget but
never widens it. Cancellation events are one-shot signals: set them once and do
not clear them.

## Errors

Every failure raised by an RPC call path is a `MindcladeError`. Two
configuration- and decode-time exceptions predate that hierarchy and remain
`ValueError` subclasses, so `except MindcladeError` does **not** catch them;
they are listed below and marked. The hierarchy is:

| Class | Raised for |
|---|---|
| `AuthenticationError` | `UNAUTHENTICATED`, and credential acquisition failure. |
| `AuthorizationError` | `PERMISSION_DENIED`. |
| `ValidationError` (subclass of `InvalidRequestError`) | `INVALID_ARGUMENT`. |
| `NotFoundError` | `NOT_FOUND`. |
| `ConflictError` | `ABORTED`, `ALREADY_EXISTS`, `FAILED_PRECONDITION`. |
| `RateLimitError` | `RESOURCE_EXHAUSTED`. |
| `QuotaError` (subclass of `RateLimitError`) | `RESOURCE_EXHAUSTED` carrying durable quota state. |
| `RetryableServiceError` (subclass of `UnavailableError`) | `UNAVAILABLE`. |
| `DeadlineExceededError` | A spent budget, locally or remotely. |
| `CancelledError` | `CANCELLED`, and caller cancellation. |
| `OperationFailedError` | A durable operation that reached a failed terminal state. |
| `WorkflowRunFailedError` | A workflow run that reached a failed terminal state. |
| `OperationTimeoutError` | A bounded wait or watch that outlived its budget. |
| `ProtocolError` | A response the contract forbids: bad cursor, sequence gap, identity drift, missing required message. |
| `PaginationLimitError` | A traversal that passed its declared page or item budget. |
| `TransportError` | A status with no more specific mapping, and a channel-level failure. |
| `ConfigurationError` (a `ValueError`, **not** a `MindcladeError`) | Unsafe configuration, raised before any network activity. |
| `EventRejectedError` (a `ValueError`, **not** a `MindcladeError`) | An inbound job event that fails envelope, scope, or identity validation in `decode_job_requested_delivery`. |

Every `MindcladeError` carries the same bounded fields (the sanitized message
itself is read with `str(error)`):

`code`, `status`, `retryable`, `retry_after`, `request_id`,
`trace_id`, `operation_id`, `field_violations`, `precondition_violations`,
`quota`, `fence`, `conflict_revision`, `diagnostic_reference`,
`server_should_retry`, and `retry_trace`.

Errors are **sanitized**. Structured server detail reaches the caller through
those typed fields and nowhere else: no SQL, no SQLSTATE, no Pub/Sub or provider
internals, no stack traces, no request or response payloads, and no credential
ever appears in a message, a `repr`, or a log line. Detail text is length-bounded
and stripped of control characters. `error_from_detail` projects a generated
`ErrorDetail` onto the same typed fields for a caller reading a durable failure
off an operation or a run.

## Retries

One policy, one predicate, applied identically by every call path:

- **4 attempts** maximum, backoff **100 ms -> 2 s**, **full jitter** — the delay
  is uniform in `[0, min(cap, base * 2**n)]`, drawn from `secrets.SystemRandom`.
  `RetryPolicy(jitter=...)` injects a deterministic source for tests.
- Retryable statuses are exactly `ABORTED`, `DEADLINE_EXCEEDED`,
  `RESOURCE_EXHAUSTED`, and `UNAVAILABLE`. No other module in this package may
  define a second set.
- Eligibility is **per RPC**. Reads are safe. A mutation is retryable only when
  its request embeds a generated `CommandContext` whose idempotency key, scope,
  and canonical request digest match the call the SDK is about to make. Anything
  else is unsafe and is never retried implicitly. There is no boolean that
  promotes an arbitrary RPC: `client.generated.unary(..., idempotent=True)` is
  rejected when the request does not carry verified command intent, and the SDK
  exposes no `unsafe_retry_of_non_idempotent_*` override at all.
- `RunService.ExpireAttemptLeases` is raw-only and is **never** retried.
- The response trailer `retry-after-ms` is honoured as a floor, clamped to the
  configured maximum backoff.
- The response trailer `x-mindclade-should-retry` (`"true"` / `"false"`) is a
  server override in **both** directions — but it can never promote a call the
  SDK already decided was unsafe.
- Every attempt sends `x-mindclade-retry-count` (0-based) and
  `x-mindclade-timeout-ms` (the remaining budget in milliseconds).
- `CallOptions(max_attempts=n)` narrows the client policy for one request. It
  can never widen it.

Retry accounting is observable on every RPC failure that leaves the SDK; it is
`None` on a `MindcladeError` raised before a transport attempt was made, such
as a `ProtocolError` from argument validation or an `AuthenticationError` from
credential acquisition:

```python
try:
    client.jobs.get("job-1")
except MindcladeError as error:
    error.retry_trace.attempts  # attempts actually made
    error.retry_trace.cumulative_delay_seconds  # total time spent in backoff
    error.retry_trace.cause  # the final status name
```

## Timeouts

A timeout is a **total budget**, not a per-attempt one. `CallOptions(timeout=…)`
— or `ClientConfig.default_timeout` when a call does not set one — bounds
credential acquisition *and* every retry attempt *and* every backoff sleep
together. When the budget is spent the SDK raises `DeadlineExceededError`
without starting another attempt, and a watcher stops reconnecting.

Per-attempt deadlines are derived from what remains, so the sequence of
per-attempt timeouts is non-increasing and never exceeds the caller's number.

## Raw responses

Every resource namespace on both clients exposes `with_raw_response`, which runs
the same ergonomic method — every identity, digest, fence, and protocol check
still executes — and returns the value beside the RPC's transport facts:

```python
raw = client.jobs.with_raw_response.get("job-1")
raw.parse()  # identical to client.jobs.get("job-1")
raw.data  # the same value, as an attribute
raw.status  # grpc.StatusCode.OK
raw.request_id  # x-request-id, from the headers or the trailers
raw.trace_id  # x-trace-id
raw.metadata  # allowlisted response metadata only
```

`raw.metadata` is projected through `SAFE_RESPONSE_METADATA_KEYS`, the allowlist
shared by all four internal SDKs:

```text
x-request-id  x-trace-id  x-mindclade-sdk  x-mindclade-retry-count
x-mindclade-timeout-ms  x-mindclade-should-retry  retry-after-ms
content-type  grpc-status  grpc-message  date
```

Anything unlisted is dropped, and nothing credential-bearing — `authorization`,
`x-mindclade-lease-token`, cookies, or any `*token*` / `*secret*` / `*key*` key —
can ever appear, even if a future allowlist edit tried to add one. Binary
(`-bin`) keys, oversized values, and values carrying control characters are
dropped too. Streaming methods have no raw response and reject the call; read
`request_id` and `trace_id` off the stream object instead.

The alias `x-mindclade-request-id` is **retired**. This SDK reads and emits
`x-request-id` only.

## Escape hatches and interceptors

All declared internal services remain reachable through `client.generated` using
their generated request and response messages and fully qualified gRPC method
paths. This advanced surface applies the same authentication, deadline,
correlation, observation, and retry policy as the ergonomic helpers.

The sole intentional raw-only RPC is `RunService.ExpireAttemptLeases`, a
control-plane reconciler primitive. Application code should use the fenced
run/attempt lifecycle helpers. Calling this method through `generated` is
conspicuous and never enables implicit retry or an ergonomic compatibility
promise.

`middleware=[interceptor]` installs ordinary gRPC client interceptors on the
channel:

```python
config = ClientConfig(..., middleware=[MyTracingInterceptor()])
```

Each is wrapped in a credential shield. It never sees the SDK's authorization
header or lease token, and any credential key it adds or removes is discarded
before the call goes out. **Credential injection stays inside the SDK and is not
interceptable.**

## Configuration and environment variables

`ClientConfig` reads nothing from the process environment. `Client.from_env()`
and `AsyncClient.from_env()` are the only environment-reading path, and they
recognise exactly:

| Variable | Effect |
|---|---|
| `MINDCLADE_ENVIRONMENT` | `development`, `staging`, `production`, or the local loopback testing profile. |
| `MINDCLADE_ENDPOINT` | Overrides the environment's default endpoint. |
| `MINDCLADE_TENANT_ID` | Required; its absence is a `ConfigurationError` naming the variable. |
| `MINDCLADE_PROJECT_ID` | Required. |
| `MINDCLADE_PRINCIPAL_ID` | Required. |
| `MINDCLADE_AUDIENCE` | Explicit token audience override. |
| `MINDCLADE_LOG` | Log level; see below. |

**There is no credential environment variable.** The token provider is always an
explicit argument, so a stray export can never change which identity the SDK
presents. Keyword arguments to `from_env` beat the environment.

```python
client = Client.from_env(token_provider=GoogleWorkloadIdentityProvider(audience))
```

`custom_metadata={"x-team": "platform"}` adds caller metadata to every request.
Keys are validated up front against the same credential denylist raw responses
use, may not shadow an SDK key, and are re-checked at emit time, so nothing
credential-bearing and nothing reserved reaches the wire.

`x-mindclade-sdk` carries structured, bounded platform facts — `lang`, `os`,
`arch`, `runtime`, `runtime_version` — drawn from closed allowlists, so an exotic
host string reports `unknown` rather than leaking machine detail.
`omit_platform_metadata=True` reduces the header to the bare name and version.

TLS and a short-lived token provider are mandatory by default. Cleartext
transport exists only for the local loopback environment and rejects
credentials.

## Logging

`MINDCLADE_LOG` selects a level — `off` (or `none`), `error`, `warn` (or
`warning`), `info`, or `debug` — for clients built with `from_env`. An
unrecognised value is a `ConfigurationError`.

Records go to the `mindclade_internal_sdk` stdlib logger, which the SDK never
configures, never attaches a handler to, and never reparents. `LoggingObserver`
can also be passed explicitly to either constructor, as can any object with
`observe(event: RpcObservation)`.

A record carries method, attempt, status, elapsed time, request id, trace id,
retry count, cumulative backoff, and metadata **key names**. There is no code
path from a payload, a metadata value, an access token, or a lease token into a
log line, and an observer that raises never changes a call's outcome.

## Versioning

This package is private and is never published, so it carries **no SemVer
line**. The `0.1.0` in `pyproject.toml` and `mindclade_internal_sdk/_version.py`
exists because the packaging tooling requires a version field and because a
support report needs a stable name for a build; it is not a compatibility
promise and it does not move when behaviour changes.

The unit of versioning is the **source revision** of this monorepo. A consumer
pins a revision and builds the facade from that revision's sources together with
that revision's generated contracts. [`CHANGELOG.md`](CHANGELOG.md) is keyed by
source revision for the same reason.

## Status

Pre-production, internal maturity, activation wave 1, no production authority.
See [`component.yaml`](component.yaml) and the appendix below.

---

## Package contract (appendix A08)

### Purpose

Give internal Python callers a safe, ergonomic, uniformly-behaved client for the
generated internal service estate, so that correlation, tenancy, deadlines,
retries, pagination, streaming resumption, error sanitization, and artifact
integrity are implemented once instead of once per caller.

### Non-goals

- **Not** the future public API: that remains a separate surface with a separate
  compatibility contract.
- **Not** a wire model. Generated protobuf types are the models.
- **Not** an SSE client. SSE is the gateway's public projection of
  `WatchOperation`.
- **Not** a persistence, messaging, or storage layer. Those stay server-side.
- **Not** a validator of ordinary request-field constraints: generated types and
  the server own those.

### Owner

`developer-experience` (component `internal-sdk-python`; CODEOWNERS routes
`/sdks/` to `@mindclade/product-engineering`, `@mindclade/architecture`,
and `@mindclade/security`). Security reviewer: `security`.

### Public entrypoints

`mindclade_internal_sdk/__init__.py` is the supported import surface, together
with the two submodules it re-exports as attributes: `resources` (factories for
generated resource values) and `testing` (`FakeSyncTransport`,
`FakeAsyncTransport`, `FakeRpcError`, and the recording seams that make consumer
tests hermetic).

Everything in `__all__` is supported. A module whose name begins with `_` is
package-private, and importing one is not supported.

### Data classifications handled

Component classification `internal`. In transit the SDK handles internal
control-plane metadata, tenant and project resource names, principal
identifiers, and — as opaque transport metadata only — short-lived workload
identity tokens and lease capabilities. It persists nothing except the artifact
bytes a caller explicitly downloads.

Credentials and lease tokens are write-only from the caller's perspective: they
are never logged, never observed, never returned in a raw response, and never
serialized into an error.

### Dependency restrictions

The dependency direction is one-way and strict:

```text
protocols/proto -> protocols/generated/python -> sdks/python -> consumers
```

Runtime dependencies are exactly `grpcio`, `protobuf`, `google-auth`,
`requests`, and the generated bindings. There is **no** PostgreSQL, Pub/Sub, or
GCS client dependency: persistence, event delivery, and artifact storage remain
server-side concerns behind generated RPCs. The package reads no ambient
configuration on import, opens no connection on import, starts no background
work, and resolves no credential outside an explicit call.

### Build and test commands

```bash
sdks/python/scripts/bootstrap   # pinned environment + toolchain audit
sdks/python/scripts/build       # compile and import the public surface
sdks/python/scripts/lint        # ruff format --check, ruff check, pyright
sdks/python/scripts/format      # ruff format
sdks/python/scripts/test        # the unittest suite

bazel test //sdks/python:tests  # the same suite under Bazel
```

The suite runs directly too:

```bash
PYTHONPATH=sdks/python:protocols/generated/python \
  python -m unittest discover -s sdks/python/tests -v
```

`just format` and `just lint` remain the repository-wide authority; these
wrappers only narrow the same tools to this package.

### Compatibility contract

- Consumers pin a **source revision**, not a version range.
- The generated contracts and this facade are upgraded together; a facade built
  against one revision's bindings is not supported against another's.
- `mindclade_internal_sdk/__init__.py` is the compatibility surface. Deep
  imports of private modules are rejected.
- Adding an SDK-owned metadata key, a response-allowlist entry, or an error class
  is a cross-language change: the four internal SDKs must agree.
- The descriptor-bound coverage gate fixes the current surface at **15 services
  and 132 RPCs** — 127 unary and five server-streaming, with 131 ergonomic
  methods and one reviewed raw-only method. Synchronous and asynchronous artifact
  facades both expose verified iteration, writer download, and atomic file
  download.

### Failure modes

| Mode | Behaviour |
|---|---|
| Credential acquisition fails or is slow | Sanitized `AuthenticationError`; the wait is charged to the caller's total budget. |
| Endpoint unreachable, server unavailable | Retried within budget, then `RetryableServiceError`. |
| Total budget exhausted | `DeadlineExceededError`; no further attempt, no reconnect. |
| Caller cancels | `CancelledError`; the one-shot cancellation event propagates into the stream. |
| Stream sequence gap, identity drift | Terminal `ProtocolError` — never a silent resync. |
| Cursor repeats or is not text during pagination | Terminal `ProtocolError`. |
| Pagination budget exceeded | `PaginationLimitError`; a partial traversal is never presented as complete. |
| Response omits a required message | `ProtocolError` rather than a synthesized default. |
| Artifact digest mismatch, or write failure before commit | Download fails; the destination is left absent or unchanged. |
| Observer or logger raises | Suppressed; the call's outcome is unaffected. |

### Retryable versus terminal errors

| Terminal — never retried | Retryable — retried within budget |
|---|---|
| `AuthenticationError`, `AuthorizationError` | `RetryableServiceError` (`UNAVAILABLE`) |
| `ValidationError`, `NotFoundError` | `RateLimitError` / `QuotaError` (`RESOURCE_EXHAUSTED`, honouring `retry-after-ms`) |
| `OperationFailedError`, `WorkflowRunFailedError` | `ConflictError` from `ABORTED` |
| `CancelledError`, exhausted `DeadlineExceededError` | Remote `DEADLINE_EXCEEDED` while budget remains |
| `ProtocolError`, `ConfigurationError`, `PaginationLimitError` | Anything an `x-mindclade-should-retry: true` trailer marks retryable |
| Any unsafe RPC, and always `ExpireAttemptLeases` | — |

`error.retryable` reports the decision the SDK actually made, and an
`x-mindclade-should-retry: false` trailer vetoes a normally-retryable status.

### Operational considerations

This is a library, not a deployable, so it has no SLO, runbook, or on-call
rotation of its own; failures surface in the consuming service. Callers own two
durable invariants:

- **Persist each mutation's `idempotency_key` with durable caller intent before
  submission**, so a crash/restart retry reuses the same identity.
- **Acknowledge stream cursors durably** before relying on `resume_watch`; the
  watcher resumes from the last cursor the caller consumed, not the last the
  server sent.

`client.artifacts.download_file(artifact, path)` and its `AsyncClient` peer stage
mode-0600 content beside the destination, verify the complete immutable digest,
and atomically publish without overwriting an existing path. Successful link
creation is the commit point; corruption, cancellation, and write failure before
it leave the destination absent or unchanged. Cleanup is idempotent.

### Graduation and deprecation status

Pre-production, internal maturity, activation wave 1, `production_authority:
false`. Nothing here is deprecated. Retirement of this facade would require
proving no internal service, worker, tool, or application still consumes it;
`workers/training_worker`, `examples/sdk`, and `examples/agent_workflow` do
today.
