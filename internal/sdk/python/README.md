# Mindclade internal Python SDK

This private, unpublished package is the ergonomic Python façade over the
authoritative generated `mindclade.*` Protobuf and gRPC bindings. It is for
Mindclade services, workers, training code, tools, and internal applications.
It is not the future public API and is not published to a package registry.

The dependency direction is strict:

```text
protocols/proto -> protocols/generated/python -> internal/sdk/python -> consumers
```

The SDK owns secure channel setup, workload-identity token injection, bounded
safe-call retries, deadlines, correlation metadata, typed errors, operation
helpers, artifact alias resolution, and training conveniences. Generated
messages remain the only request, response, resource, and event models.
PostgreSQL durable state and Pub/Sub event delivery stay behind the control
plane and are never accessed directly by this SDK.

## Synchronous use

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

All declared internal services remain reachable through `client.generated`
using their generated request and response messages and fully qualified gRPC
method paths. This advanced surface applies the same authentication, deadline,
correlation, observation, and retry policy as the ergonomic helpers. A generic
mutation is retried only when its fully qualified method is allowlisted and its
generated `CommandContext` contains the same explicit idempotency key, scope,
and canonical request digest. A boolean flag cannot promote arbitrary raw RPCs.

The sole intentional raw-only RPC is `RunService.ExpireAttemptLeases`, a
control-plane reconciler primitive. Application code should use the fenced
run/attempt lifecycle helpers. Calling this method through `generated` is
conspicuous and never enables implicit retry or an ergonomic compatibility
promise.

The descriptor-bound coverage gate fixes the current surface at 15 services
and 132 RPCs: 127 unary and five server-streaming, with 131 ergonomic methods
and one reviewed raw-only method. Synchronous and asynchronous artifact facades
both expose verified iteration, writer download, and atomic file download.

## Pagination

Every ergonomic list method returns a `Page` (or an `AsyncPage` on
`AsyncClient`) instead of the bare generated `List*Response`:

```python
for job in client.jobs.list():          # iterates every page transparently
    handle(job)

page = client.jobs.list()               # page-level access is still available
page.items                              # this page's items
page.has_next_page                      # whether a further cursor exists
page.next_page()                        # the following page, same validations
page.pages()                            # this page and every following page
page.page.next_page_token               # the generated response, delegated
```

A page delegates unknown attribute reads to the generated `List*Response` it
was built from, so `page.jobs`, `page.page.next_page_token`, and `page.read_time`
keep working and the generated message stays the only wire model. Traversal
preserves opaque tokens exactly, forwards them verbatim, rejects cursor loops
and non-text cursors with `ProtocolError`, and re-runs each page's identity and
scope checks. Budgets are explicit: `PaginationLimits` defaults to 100 items per
page, 100 pages, and 10,000 items per traversal, with hard caps of 1,000 and
1,000,000; passing them is `client.jobs.list(limits=PaginationLimits(max_items=500))`.
Exceeding a budget raises `PaginationLimitError` rather than implying that a
bounded partial result is complete. `paginate` and `apaginate` remain for a
caller driving `client.generated` or a hand-rolled fetch loop.

## Raw responses

Every resource namespace on both clients exposes `with_raw_response`, which
runs the same ergonomic method — every identity, digest, fence, and protocol
check still executes — and returns the value beside the RPC's transport facts:

```python
raw = client.jobs.with_raw_response.get("job-1")
raw.parse()        # identical to client.jobs.get("job-1")
raw.status         # grpc.StatusCode.OK
raw.request_id     # x-request-id, from the headers or trailers
raw.trace_id       # x-trace-id
raw.metadata       # allowlisted response metadata only
```

`raw.metadata` is projected through `SAFE_RESPONSE_METADATA_KEYS`, the
allowlist shared by all four internal SDKs. Anything unlisted is dropped, and
nothing credential-bearing — `authorization`, `x-mindclade-lease-token`,
cookies, or any `*token*`/`*secret*`/`*key*` key — can ever appear. Streaming
methods have no raw response and reject the call.

`client.artifacts.download_file(artifact, path)` and its `AsyncClient` peer
stage mode-0600 content beside the destination, verify the complete immutable
digest, and atomically publish without overwriting an existing path. Successful
link creation is the commit point; corruption, cancellation, and write failure
before it leave the destination absent or unchanged.

Persist each mutation's `idempotency_key` with durable caller intent before
submission so crash/restart retries reuse the same identity. Cancellation events
are one-shot signals: set them once and do not clear them. Runtime checks cover
credentials, scope, correlation metadata, deadlines, page budgets, stream
identity, and artifact integrity; generated protobuf types and the server own
ordinary request-field constraints.

## Long-running operations and streaming

Durable operations expose one uniform verb set on both clients: `get`, `wait`,
`cancel`, `watch`, and `resume_watch`. Streaming stays native gRPC
server-streaming; there is no SSE client in this SDK, because SSE is the
gateway's public projection of `WatchOperation` alone.

```python
with client.operations.watch(name, timeout=600) as events:   # also async with
    for event in events:
        checkpoint(events.cursor)                            # durable cursor
        if event.operation.done:
            break

# Re-attach later from the cursor you recorded. ``after_sequence`` is required,
# so a resume can never silently replay from the beginning.
stream = client.operations.resume_watch(name, after_sequence=checkpointed)
```

`client.operations.watch`, `client.training.watch`, `client.inference.watch`,
and `client.workflows.watch` all run on one resumable watcher. It reconnects
only inside the caller's remaining deadline, resumes from the last acknowledged
cursor, carries the caller's lease token and idempotency key onto every attempt,
re-runs each domain's sequence and identity checks after a reconnect, and raises
the failure that actually ended the stream once the retry budget is spent. The
returned stream is an iterator, a context manager whose exit releases the live
call, and it exposes `request_id`, `trace_id`, and `cursor`. Every watcher takes
`options=CallOptions(...)`, whose timeout narrows the watch budget but never
widens it.

## Configuration and environment variables

`ClientConfig` reads nothing from the process environment. `Client.from_env()`
and `AsyncClient.from_env()` are the only environment-reading path, and they
recognise exactly `MINDCLADE_ENVIRONMENT`, `MINDCLADE_ENDPOINT`,
`MINDCLADE_TENANT_ID`, `MINDCLADE_PROJECT_ID`, `MINDCLADE_PRINCIPAL_ID`,
`MINDCLADE_AUDIENCE`, and `MINDCLADE_LOG`. **There is no credential environment
variable**: the token provider is always an explicit argument, so a stray export
can never change which identity the SDK presents. Keyword arguments to
`from_env` beat the environment.

```python
client = Client.from_env(token_provider=GoogleWorkloadIdentityProvider(audience))
```

`custom_metadata={"x-team": "platform"}` adds caller metadata to every request.
Keys are validated up front against the same credential denylist raw responses
use and may not shadow an SDK key, so nothing credential-bearing and nothing
reserved reaches the wire. `x-mindclade-sdk` carries structured, bounded
platform facts (`lang`, `os`, `arch`, `runtime`, `runtime_version`) drawn from
closed allowlists; `omit_platform_metadata=True` reduces it to the bare name and
version.

`middleware=[interceptor]` installs ordinary gRPC client interceptors on the
channel. Each is wrapped in a credential shield: it never sees the SDK's
authorization header or lease token, and any credential key it adds or removes
is discarded before the call goes out. Credential injection is not
interceptable.

## Logging

`MINDCLADE_LOG` selects a level — `off`, `error`, `warn`, `info`, or `debug` —
for clients built with `from_env`. Records go to the `mindclade_internal_sdk`
stdlib logger, which the SDK never configures, never handles, and never
attaches to the root logger. `LoggingObserver` can also be passed explicitly to
either constructor. A record carries method, attempt, status, elapsed time,
request id, trace id, retry count, cumulative backoff, and metadata *key names*;
there is no code path from a payload, a metadata value, an access token, or a
lease token into a log line.

## Safety and retry behavior

- TLS and a short-lived token provider are mandatory by default.
- Credential acquisition is bounded by the end-to-end call deadline. The
  built-in Google providers apply one deadline across ADC metadata, STS, and
  service-account exchanges, validate token audience and expiry, and singleflight
  refreshes.
- Cleartext transport exists only for the local loopback environment and
  rejects credentials.
- Automatic retries are bounded and occur only for reads or mutations carrying
  an idempotency key and canonical request digest.
- Errors preserve gRPC status, request ID, and retryability without copying
  provider details or request/response payloads.
- Observers receive method, attempt, elapsed time, status, request ID, trace ID,
  retry count, cumulative backoff, and metadata key names only. Metadata values,
  tokens, and payloads are never observed or logged.
- `FakeSyncTransport` and `FakeAsyncTransport` support hermetic consumer tests.

Run focused tests with:

```bash
PYTHONPATH=internal/sdk/python:protocols/generated/python \
  python -m unittest discover -s internal/sdk/python/tests -v
```
