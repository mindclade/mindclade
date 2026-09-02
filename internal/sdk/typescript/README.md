# Mindclade internal TypeScript SDK

`@mindclade/internal-sdk` is the private, hand-written TypeScript developer
experience over the authoritative generated Protobuf-ES contracts; Connect
clients are created at runtime from the generated service descriptors:

```text
protocols/proto
    -> protocols/generated/typescript    (protobuf-ES descriptors, *_pb.ts)
    -> internal/sdk/typescript           (this package)
    -> internal services, tools, workers, and applications
```

There is **no connect-es code generation** in this repository.
`protocols/generated/typescript` contains protobuf-ES descriptors and message
types only; the Connect clients are built at runtime by `createClient` against
those descriptors. Generated descriptors and messages remain the only wire
models — this package never declares a parallel hand-written one.

What the facade adds on top: secure endpoint configuration, injectable
short-lived workload identity, correlation and tenancy metadata, total deadline
budgets, bounded retries with a single eligibility predicate, a sanitized error
hierarchy, transparent pagination, one resumable watcher, uniform long-running
operation verbs, raw-response access, and verified artifact download.

---

## Installation

The package is private and is never published to a registry. It is consumed from
the workspace, pinned to a source revision of this monorepo:

```jsonc
// package.json of a consuming workspace package
{
  "dependencies": {
    "@mindclade/internal-sdk": "workspace:*"
  }
}
```

```bash
internal/sdk/typescript/scripts/bootstrap   # pnpm install --frozen-lockfile
internal/sdk/typescript/scripts/build       # tsc -> dist/native
```

Node 26 or newer, ESM only (`"type": "module"`).

## Usage

```ts
import {
  ClientConfig,
  Environment,
  GcpWorkloadIdentityProvider,
  MindcladeClient,
} from "@mindclade/internal-sdk";

const client = MindcladeClient.connect(
  ClientConfig.create({
    environment: Environment.Production,
    identity: {
      tenantId: "tenants/acme",
      projectId: "projects/folding",
      principalId: "principals/ingestion-worker",
    },
    tokenProvider: new GcpWorkloadIdentityProvider(),
  }),
);

const operation = await client.operations.get("operations/op-1041");
```

Every namespace hangs off the client: `admin`, `agents`, `approvals`,
`artifacts`, `datasets`, `evaluations`, `experiments`, `inference`, `jobs`,
`models`, `operations`, `policies`, `runs`, `training`, `workflows`, plus
`raw` (below).

Plaintext is rejected except for an explicitly enabled Local loopback test
endpoint; that mode rejects a token provider and emits no authorization
metadata. Secure clients require a provider.

`GcpWorkloadIdentityProvider` uses the fixed GCE/GKE metadata identity endpoint
with an audience-bound, bounded exchange, refresh skew, a per-audience cache,
concurrency-safe singleflight, caller cancellation, and redacted failures. Set
`ClientConfigInput.audience` to the verifier's exact configured OIDC audience.
If omitted, the SDK derives the endpoint's canonical HTTPS origin: the host is
lowercased, IPv6 stays bracketed, a default `:443` is dropped, and a non-default
port is kept.

## Request and response types

The generated protobuf-ES types **are** the models. A facade method takes a
generated request (or its `MessageInitShape`) and returns the generated message
the RPC produced, after validating the invariants the SDK owns — scope, identity,
correlation, digests, sequence contiguity.

```ts
const dataset = await client.datasets.get({ name: "datasets/hgt-2024" });
//    ^? Dataset — mindclade.dataset.v1.Dataset, unchanged
```

The SDK adds no parallel wire model, no re-shaped DTO, and no ad-hoc JSON. It
owns exactly one family of hand-written value types, and they are all *derived,
sanitized projections* rather than wire types: `SdkPageInfo` (page provenance),
`RawResponse` (transport envelope), `QuotaState`, `FenceState`, and `RetryState`
on errors. Where a name would have collided with a real contract message the SDK
type is renamed, not the message — `SdkPageInfo` exists because protobuf already
owns `mindclade.api.v1.PageMetadata`.

Unknown or `UNRECOGNIZED` enum values never authorize an action.

## Pagination

Every ergonomic list method returns a `Page`. Iterating it with `for await`
yields items transparently across page boundaries; the page-level view stays
available for callers that need the cursor.

```ts
const page = await client.datasets.list({ page: { pageSize: 50 } });

for await (const dataset of page) {   // crosses page boundaries
  console.log(dataset.name);
}

page.items;                 // this page only
page.response;              // ListDatasetsResponse, exactly as received
page.metadata;              // SdkPageInfo: requestId, pageToken, nextPageToken,
                            //   pageIndex, pageSize
page.hasNextPage;           // boolean
await page.nextPage();      // Page | undefined, memoized
for await (const p of page.pages()) { /* page at a time */ }
```

Traversal preserves opaque tokens byte-for-byte, rejects a repeated cursor as a
protocol violation, observes cancellation between pages, and re-runs the
facade's per-page response validation for **every** page — a page-two item
outside the client's project still fails.

Budgets are enforced, and a bounded partial traversal is never presented as
complete: exceeding one raises a `pagination_limit` error.

| Budget | Default | Hard cap |
|---|---:|---:|
| pages per traversal | 100 | 1,000 |
| items per traversal | 10,000 | 1,000,000 |

```ts
await client.datasets.list({}, { limits: { maxItems: 500, maxPages: 10 } });
```

Per-list page-size ceilings (100, 200, or 1,000 depending on the RPC) are
validated before the first request. `paginate`, the lower-level async generator,
remains exported for callers that drive a page-fetching closure themselves.

## Long-running operations

`operations` carries the uniform LRO verbs; the domain facades mirror them.

| Verb | Behaviour |
|---|---|
| `get(name)` | One read of the current `Operation`. |
| `wait(name, options)` | Polls to a terminal state within one total budget. |
| `watch(name, afterSequence?)` | Server-streaming updates from a cursor. |
| `resumeWatch(name, afterSequence)` | Same, cursor mandatory and positive. |
| `cancel(name, etag, reason, options)` | Fenced, idempotent cancellation. |
| `list(request, options)` | Auto-paginating `Page<Operation, …>`. |

```ts
const done = await client.operations.wait("operations/op-1041", {
  waitTimeoutMs: 120_000,
  pollIntervalMs: 1_000,
});
```

`wait` and the deprecated `watchUntilDone` raise a typed `OperationFailedError`
(exported also as `OperationFailure`) for a failed or cancelled remote
operation. The generated `Operation` is deliberately attached but
**non-enumerable**, so its structured server error is not serialized alongside
the SDK error.

`workflows`, `training`, and `inference` publish the same `watch` /
`resumeWatch` pair, and `workflows.wait` / `training.wait` return the terminal
domain resource or raise `WorkflowRunFailure` / `TrainingRunFailure`.

## Streaming

Server streaming stays native gRPC/Connect. **There is no SSE client here**; SSE
is the gateway's public projection of exactly one RPC (`WatchOperation`) and is
out of scope for the internal SDKs.

All four watchers are one generic implementation (`watchStream`):

```ts
const abort = new AbortController();

for await (const update of client.operations.watch("operations/op-1041", 0n, {
  signal: abort.signal,
  timeoutMs: 300_000,
})) {
  await acknowledge(update.sequence);
}
```

- Reconnection happens **only** inside the caller's remaining deadline, and
  **only** from the last cursor the caller actually consumed.
- A redelivered prefix is never yielded twice. `operations` skips it; the
  strictly contiguous streams (`inference`, `workflows`, `training`) reject it
  as a terminal `protocol` failure instead, because for them a replay after a
  cursor-positioned resume is a server contract violation.
- A delivered update resets the consecutive-failure count, and the reconnect
  burst that finally fails is reported on the error as `retry.attempts` /
  `retry.cumulativeDelayMs` / `retry.cause`, counted since that update.
- Reconnect eligibility, the attempt ceiling (including a per-request
  `maxAttempts`), and the backoff are exactly the unary path's.
- Every reconnect advertises `x-mindclade-retry-count` and
  `x-mindclade-timeout-ms`.
- Domain contracts are preserved per stream: operations reject a zero sequence
  and an identity drift; inference binds heartbeats to the stream cursor and
  requires contiguity; workflows require `transitionSequence == cursor + 1`;
  training requires `sequence == cursor + 1`. Any violation is a terminal
  `protocol` failure, never a silent resync.
- The `AbortSignal` is honoured between messages and between reconnects, and is
  propagated into the stream.

## Errors

Every failure the SDK raises is a `MindcladeError` or one of its subclasses.
Messages are **sanitized**: raw SQL, SQLSTATE, Pub/Sub internals, provider
errors, and stack traces never reach the caller. Structured server detail is
surfaced through typed fields only, extracted from
`mindclade.common.v1.ErrorDetail`.

```ts
import { MindcladeError, ValidationError } from "@mindclade/internal-sdk";

try {
  await client.datasets.get({ name });
} catch (error) {
  if (error instanceof ValidationError) {
    for (const violation of error.fieldViolations) {
      console.error(violation.field, violation.description);
    }
  } else if (error instanceof MindcladeError) {
    console.error(error.stableCode, error.requestId, error.retry?.attempts);
  }
  throw error;
}
```

| Class | Raised for |
|---|---|
| `AuthenticationError` | `UNAUTHENTICATED`; credential acquisition failure. |
| `AuthorizationError` | `PERMISSION_DENIED`; a policy denial. |
| `ValidationError` | `INVALID_ARGUMENT`, `OUT_OF_RANGE`, local argument checks. |
| `ConflictError` | `ABORTED`, `ALREADY_EXISTS`, revision conflict. |
| `NotFoundError` | `NOT_FOUND`. |
| `RateLimitError` | `RESOURCE_EXHAUSTED` carrying a retry-after. |
| `QuotaError` | `RESOURCE_EXHAUSTED` without one; pagination budgets. |
| `RetryableServiceError` | `UNAVAILABLE`, `INTERNAL`, `DATA_LOSS`, remote deadline. |
| `OperationFailedError` | A terminal failed or cancelled operation. |
| `CancelledError` | Caller abort; `CANCELLED`. |
| `TransportError` | Transport and protocol failures. |
| `MindcladeError` | Local configuration mistakes and anything unclassified. |

Every error carries: `stableCode`, `safeMessage`, `kind`, `code`, `retryable`,
`retryAfterMs`, `requestId`, `traceId`, `operationId`, `fieldViolations`,
`preconditionViolations`, `quota`, `fence`, `conflictRevision`,
`diagnosticReference`, and — after a retried call — `retry`.

## Retries

One predicate (`shouldRetry`) decides eligibility for the whole SDK, unary and
streaming alike. One hand-maintained table (`src/safety.ts`) classifies all 132
descriptor routes; `REGISTERED_ROUTES` exports its coverage so the table cannot
drift from the descriptor unnoticed.

| Safety class | Meaning | Retried implicitly |
|---|---|---|
| `safe` | Read RPC. | yes |
| `idempotent` | Mutation whose request embeds a `CommandContext`. | yes |
| `unsafe` | Anything else, and every unknown route. | no |
| `never` | `RunService.ExpireAttemptLeases`. | never, under any override |

Policy, fixed across all four Mindclade SDKs:

- **4 attempts** maximum; backoff **100 ms → 2 s**; **full jitter**, uniform in
  `[0, min(cap, base * 2^n)]`, from a cryptographically seeded source that tests
  can inject deterministically.
- The response trailer `x-mindclade-should-retry` (`"true"` / `"false"`) is a
  server override **in both directions** and wins over the status.
- The response trailer `retry-after-ms` pins the delay exactly, clamped to
  `maxBackoffMs`, and does not consume jitter.
- Every attempt sends `x-mindclade-retry-count` (0-based) and
  `x-mindclade-timeout-ms` (remaining budget).
- The terminal error carries `retry.attempts`, `retry.cumulativeDelayMs`, and
  `retry.cause`.

Raw generated calls (`client.raw`) are authenticated and deadline-bounded but
are **never** retried implicitly, because the SDK cannot infer the mutation
semantics of an arbitrary RPC.

Retrying a route the table calls `unsafe` requires an explicitly named token —
never a bare boolean — and the caller must record why duplicate execution is
acceptable:

```ts
import { withUnsafeRetryOfNonIdempotent } from "@mindclade/internal-sdk";

await someCall(request, {
  maxAttempts: 3,
  unsafeRetryOfNonIdempotent: withUnsafeRetryOfNonIdempotent(
    "this operation is convergent for this caller; duplicates are discarded",
  ),
});
```

Because the table now classifies all 132 descriptor routes, no shipped ergonomic
method is currently `unsafe`; the class is what an unclassified route falls back
to, and the token is the only way to opt such a route into retries.

`RunService.ExpireAttemptLeases` ignores the token entirely: a duplicated
lease-expiry sweep can revoke a lease a healthy worker still holds.

## Timeouts

`options.timeoutMs` is a **total budget**, not a per-attempt one. It covers
every attempt, every backoff sleep, and credential acquisition. It defaults to
`ClientConfig.defaultTimeoutMs` (20 s).

```ts
await client.operations.get(name, { timeoutMs: 5_000, maxAttempts: 2 });
```

When the budget is exhausted the call raises a `deadline_exceeded`
`MindcladeError` and no further attempt is issued — including a stream reconnect
that would not fit in the remaining time. `maxAttempts` (1–8) narrows the client
policy for one call; it can never widen an `unsafe` or `never` route.

## Raw responses

`client.withResponse()` re-projects every ergonomic namespace so each
promise-returning method resolves to the value **plus** its sanitized transport
envelope.

```ts
const raw = await client.withResponse().operations.get("operations/op-1041");

raw.value;        // the Operation the plain method would have returned
raw.status.ok;    // true
raw.requestId;    // x-request-id
raw.traceId;      // x-trace-id
raw.metadata;     // ReadonlyMap<string, string>, allowlisted only
```

The allowlist `SAFE_RESPONSE_METADATA` is normative and identical in the Go,
Python, Rust, and TypeScript SDKs:

```text
x-request-id  x-trace-id  x-mindclade-sdk
x-mindclade-should-retry  retry-after-ms  x-mindclade-retry-count
```

It is an allowlist so a new server header can never become visible by accident,
and each entry is additionally screened by a credential denylist —
`authorization`, `proxy-authorization`, cookies, `x-api-key`, `x-goog-api-key`,
`x-mindclade-lease-token`, and any name matching `token`, `secret`, `key`,
`credential`, or `password`. `grpc-message` is deliberately excluded: it carries
remote free text. `status.code` is only populated for a failure; success carries
no code because the Connect status enumeration has no `OK` member. `client.raw`
is not projected.

## Escape hatches and interceptors

**`client.raw`** exposes every generated internal service client plus a generic
descriptor escape hatch. Raw calls are authenticated, metadata-stamped, and
deadline-bounded, but unretried and unvalidated.

The sole intentional raw-only RPC is `RunService.ExpireAttemptLeases`, a
control-plane reconciler primitive. Application code should use the fenced
run/attempt lifecycle helpers and must not infer an ergonomic compatibility or
retry promise from `client.raw`.

**Custom metadata** is applied to every call and screened by the same credential
denylist as raw responses, plus a reserved-name list (`x-request-id`,
`x-trace-id`, `x-mindclade-sdk`, `x-mindclade-expected-*`,
`x-mindclade-retry-count`, `x-mindclade-timeout-ms`, `idempotency-key`,
`x-mindclade-worker-id`). A violation fails at `ClientConfig.create`.

**Connect interceptors** wrap every call:

```ts
ClientConfig.create({
  /* … */
  metadata: { "x-deployment": "us-central1-b" },
  interceptors: [next => async request => {
    request.header.set("x-experiment", "cache-v2");
    return next(request);
  }],
});
```

The transport layering is deliberate:

```text
client -> metadata (ids, expected-*, sdk identity, deadline)
       -> caller interceptors
       -> credential injection            <-- not interceptable
       -> Connect / node transport
```

An interceptor can observe `x-request-id` and decorate a request, but can
neither read nor forge `authorization`: credential injection sits below the
chain, and an interceptor that sets the header has it stripped and overwritten
at the wire.

**Transport injection.** `MindcladeClient.withTransport(config, transport,
runtime)` accepts any Connect transport and a deterministic runtime for hermetic
tests or in-process service adapters; auth and metadata policy still apply.
`RecordingTransport` wraps any router or transport across the full generated
service estate and records only method names, streaming mode, timeout, and
header **key names**.

Both directions are capped at `MAX_MESSAGE_BYTES` = 8 MiB, the same ceiling as
every other Mindclade SDK.

## Configuration and environment variables

`ClientConfig.create` is environment-free: an ambient variable never silently
reconfigures a client. Reading the environment is one explicit factory.

```ts
const client = MindcladeClient.fromEnvironment({
  tokenProvider: new GcpWorkloadIdentityProvider(),
});
```

| Variable | Meaning |
|---|---|
| `MINDCLADE_ENVIRONMENT` | `development`, `staging`, `production`, or `local`. Required. |
| `MINDCLADE_TENANT_ID` | Tenant resource name. Required. |
| `MINDCLADE_PROJECT_ID` | Project resource name. Required. |
| `MINDCLADE_PRINCIPAL_ID` | Principal resource name. Required. |
| `MINDCLADE_ENDPOINT` | Overrides the environment's default endpoint. |
| `MINDCLADE_AUDIENCE` | OIDC audience; defaults to the endpoint's canonical origin. |
| `MINDCLADE_LOG` | `error`, `warn`, `info`, or `debug`. |

That list is exhaustive — `RECOGNISED_ENVIRONMENT_VARIABLES` exports it. **There
is no credential environment variable and there never will be.** A credential
reaches the SDK only through a `TokenProvider` constructed in code and passed
through `EnvironmentOverrides`. Anything else in the process environment is
ignored, including variables that merely look credential-shaped.

Client policy defaults: `defaultTimeoutMs` 20,000; `pollIntervalMs` 500; retry
`{ maxAttempts: 4, initialBackoffMs: 100, maxBackoffMs: 2_000 }`.

`x-mindclade-sdk` carries bounded structured platform facts from a single
version source (`SDK_NAME`, `SDK_VERSION`, kept equal to `package.json`):

```text
mindclade-internal-typescript-sdk/0.1.0;lang=typescript;os=linux;arch=x64;runtime=node;runtime_version=26.0.0
```

`omitPlatformMetadata: true` collapses that to
`mindclade-internal-typescript-sdk/0.1.0;lang=typescript`. Semicolons separate
the fields because the SDK's own metadata rule forbids spaces.

## Logging

Two seams, both injectable, both advisory — a throwing observer or logger can
never change the outcome of the call it observes.

```ts
ClientConfig.create({
  /* … */
  observer: { onCall: (event) => metrics.record(event) },
  logger: consoleLogger("info"),
  logLevel: "info",
});
```

`ObservedCall` carries `method`, `attempt`, `elapsedMs`, `status`, `code`,
`requestId`, and `metadataKeys`. **Metadata key names only** — never values,
never payloads, never credentials, never lease tokens. Observation fires from
the retry loop (per attempt) and the watcher (per reconnect), never from the
transport, which is the only layer that ever sees a credential.

`consoleLogger(level)` writes JSON lines to standard error so records cannot
contaminate a program's data output. `MINDCLADE_LOG` selects the level, but only
through `fromEnvironment` / `clientConfigFromEnvironment`; an unrecognised value
enables nothing rather than defaulting to everything.

## Versioning

This package is private and is never published, so it carries **no SemVer
line**. The `0.1.0` in `package.json` exists because the workspace tooling
requires a version field; it is not a compatibility promise and it does not move
when behaviour changes.

The unit of versioning is the **source revision** of this monorepo. A consumer
pins a revision and builds the facade from that revision's sources together with
that revision's generated contracts. `CHANGELOG.md` is keyed by source revision
for the same reason.

## Status

Pre-production, internal maturity, activation wave 1, no production authority.
See `component.yaml` and the appendix below.

---

## Package contract (appendix A08)

### Purpose

Give internal TypeScript callers a safe, ergonomic, uniformly-behaved client for
the generated internal service estate, so that correlation, tenancy, deadlines,
retries, pagination, streaming resumption, error sanitization, and artifact
integrity are implemented once instead of once per caller.

### Non-goals

- **Not** the future public HTTP SDK: that remains a separate package with a
  separate compatibility surface.
- **Not** a wire model. Generated protobuf-ES types are the models.
- **Not** an SSE client. SSE is the gateway's public projection of
  `WatchOperation`.
- **Not** a persistence, messaging, or storage layer. Those stay server-side.
- **Not** a validator of ordinary request-field constraints: generated types and
  the server own those.

### Owner

`developer-experience` (component `internal-sdk-typescript`; CODEOWNERS routes
`/internal/sdk/` to `@mindclade/product-engineering`, `@mindclade/architecture`,
and `@mindclade/security`). Security reviewer: `security`.

### Public entrypoints

`src/index.ts` is the only supported import surface — deep imports are not
supported. It re-exports the generated contract types the facade traffics in,
plus: `MindcladeClient`, `ClientConfig` / `ClientConfigInput` / `Environment` /
`Identity` / `RetryPolicy`, `clientConfigFromEnvironment`, the fifteen
ergonomic namespaces and `raw`, `Page` / `listPage` / `paginate` / `SdkPageInfo`, `RawResponse` /
`SAFE_RESPONSE_METADATA`, the twelve error classes, `shouldRetry` /
`withUnsafeRetryOfNonIdempotent` / `registeredMethodSafety` /
`REGISTERED_ROUTES` / `isNeverRetryable`, `watchStream`, `Observer` / `Logger` /
`consoleLogger`, `platformMetadata` / `SDK_NAME` / `SDK_VERSION`,
`AccessToken` / `TokenProvider` / `GcpWorkloadIdentityProvider`, and the
test-only `FakeRuntime` / `RecordingTransport`.

Anything under `src/` that `index.ts` does not export is package-private.

### Data classifications handled

Component classification `internal`. In transit the SDK handles internal
control-plane metadata, tenant and project resource names, principal
identifiers, and — as opaque transport metadata only — short-lived workload
identity tokens and lease capabilities. It persists nothing except the artifact
bytes a caller explicitly downloads.

Credentials and lease tokens are write-only from the caller's perspective: they
are never logged, never observed, never returned in a `RawResponse`, and never
serialized into an error.

### Dependency restrictions

Runtime dependencies are exactly `@bufbuild/protobuf`, `@connectrpc/connect`,
`@connectrpc/connect-node`, and the generated contracts. The SDK has **no**
PostgreSQL, Pub/Sub, or GCS client dependency: persistence, event delivery, and
artifact storage remain server-side concerns behind generated RPCs. It reads no
ambient configuration on import, opens no connection on import, starts no
background work, and resolves no credential outside an explicit call.

### Build and test commands

```bash
internal/sdk/typescript/scripts/bootstrap   # pinned workspace install
internal/sdk/typescript/scripts/build       # tsc
internal/sdk/typescript/scripts/lint        # biome check + tsc --noEmit
internal/sdk/typescript/scripts/format      # biome format --write
internal/sdk/typescript/scripts/test        # node:test suite

bazel test //internal/sdk/typescript:tests  # the same suite under Bazel
```

`just format` and `just lint` remain the repository-wide authority; these
wrappers only narrow the same tools to this package.

### Compatibility contract

- Consumers pin a **source revision**, not a version range.
- The generated contracts and this facade are upgraded together; a facade built
  against one revision's descriptors is not supported against another's.
- `src/index.ts` is the compatibility surface. Deep imports and re-export chains
  that obscure ownership are rejected.
- Adding an SDK-owned metadata key, a response-allowlist entry, or an error
  class is a cross-language change: the four internal SDKs must agree.
- The descriptor-bound coverage gate fixes the current surface at **15 services
  and 132 RPCs** — 127 unary and five server-streaming, with 131 ergonomic
  methods and one reviewed raw-only method.

### Failure modes

| Mode | Behaviour |
|---|---|
| Credential acquisition fails or is slow | Redacted `AuthenticationError`; the wait is charged to the caller's total budget. |
| Endpoint unreachable / server unavailable | Retried within budget, then `RetryableServiceError` carrying `retry` state. |
| Total budget exhausted | `deadline_exceeded`; no further attempt, no reconnect. |
| Caller aborts | `CancelledError`; the signal is propagated into the stream. |
| Stream sequence gap, identity drift, bad heartbeat | Terminal `protocol` failure — never a silent resync. |
| Cursor repeats during pagination | Terminal `protocol` failure. |
| Pagination budget exceeded | `pagination_limit`; a partial traversal is never presented as complete. |
| Response omits a required message | `protocol` failure rather than a synthesized default. |
| Artifact digest mismatch, or write failure before commit | Download fails; the destination is left absent or unchanged. |
| Observer or logger throws | Swallowed; the call's outcome is unaffected. |

### Retryable versus terminal errors

| Terminal — never retried | Retryable — retried within budget |
|---|---|
| `AuthenticationError`, `AuthorizationError` | `RetryableServiceError` (`UNAVAILABLE`, `INTERNAL`, `DATA_LOSS`, remote `DEADLINE_EXCEEDED`) |
| `ValidationError`, `NotFoundError` | `RateLimitError` (`RESOURCE_EXHAUSTED`, honouring `retry-after-ms`) |
| `QuotaError`, `OperationFailedError` | `ConflictError` from `ABORTED` |
| `CancelledError`, local `deadline_exceeded` | Anything a `x-mindclade-should-retry: true` trailer marks retryable |
| `protocol`, `configuration`, `pagination_limit` | — |
| Any `unsafe` route, and always `ExpireAttemptLeases` | — |

`error.retryable` reports the decision the SDK actually made, and
`x-mindclade-should-retry: false` can veto a normally-retryable status.

### Operational considerations

This is a library, not a deployable, so it has no SLO, runbook, or on-call
rotation of its own; failures surface in the consuming service. Callers own two
durable invariants:

- **Persist each mutation's `idempotencyKey` with durable caller intent before
  submission**, so a crash/restart retry reuses the same identity.
- **Acknowledge stream cursors durably** before relying on `resumeWatch`; the
  watcher resumes from the last cursor the caller consumed, not from the last
  the server sent.

`client.artifacts.downloadFile(artifact, path)` stages a private mode-0600 file
beside the destination, verifies the complete immutable digest, and atomically
publishes without overwriting an existing path. Successful link creation is the
commit point; corruption, cancellation, and write failure before it leave the
destination absent or unchanged. Cleanup is idempotent.

### Graduation and deprecation status

Pre-production, internal maturity, activation wave 1, `production_authority:
false`. Nothing here is deprecated. Retirement of this facade would require
proving no internal service, worker, tool, or application still consumes it;
`apps-console` and `examples/sdk` do today.
