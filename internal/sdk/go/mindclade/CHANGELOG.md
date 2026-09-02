# Changelog — `internal/sdk/go/mindclade`

This package lives beneath the repository-root `internal/` tree, so no Go module
outside this repository can import it. It is never published to a proxy and it
carries **no SemVer line**. `Version` in `config.go` is an identity string
stamped into the gRPC user agent and into `x-mindclade-sdk`; it is a build
fingerprint, not a compatibility promise, and it does not move when behaviour
changes.

The compatibility promise is the one stated in `README.md`: a consumer is pinned
to a **source revision** of this monorepo and builds the facade from that
revision's sources together with that revision's generated contracts.

Entries below are therefore keyed by **source revision**, newest first. A
revision heading names the commit in which the change landed. Work that has not
yet been committed is headed `Unmerged` and records the revision it was authored
against, so a reader can always reproduce the tree an entry describes.

Every entry states an SDK-visible behaviour or surface change. Changes confined
to tests, comments, or formatting are not recorded here.

---

## Unmerged — authored against `adc4b22`

Documentation (WS2.9), completing the packaging work begun at `688bb40`. No
runtime behaviour changes.

### Added

- `CHANGELOG.md` (this file).
- The appendix-A08 package contract in `README.md`: purpose and non-goals,
  owner, public entrypoints, dependency restrictions, data classifications
  handled, build and test commands, compatibility contract, failure modes, the
  retryable-versus-terminal error table, and graduation status.
- `TestSDKVersionIsSingleSourced`. `Version` is consumed in two places — the
  default gRPC user agent and the structured `x-mindclade-sdk` value — and the
  test asserts both are *derived* from it rather than merely containing it, so
  the single version source cannot fork into two hard-coded revisions.

### Changed

- `README.md` rewritten into the standard SDK section order (Installation,
  Usage, Request and response types, Pagination, Long-running operations,
  Streaming, Errors, Retries, Timeouts, Raw responses, Escape hatches and
  interceptors, Configuration and environment variables, Logging, Versioning,
  Status) ahead of the A08 contract.
- `BUILD.bazel`'s `governed_sources` filegroup now also carries `CHANGELOG.md`,
  `component.yaml`, and `scripts/*`, so the packaging evidence sits inside the
  governed source closure rather than beside it.
- `scripts/bootstrap` runs the package-local module resolution before the
  repository toolchain audit, so a contributor whose toolchain audit fails can
  still build and test this package while fixing it, and reports which of the
  two steps failed.

---

## `688bb40` — 2026-09-02

Packaging (WS2.8). No runtime behaviour changes.

### Added

- `component.yaml` registering component `internal-sdk-go`, owner
  `developer-experience`, data classification `internal`. `tools-mindcladectl`
  already declared a `compile-api` dependency on this component name; the
  metadata now exists for that edge to resolve against.
- `scripts/bootstrap`, `scripts/build`, `scripts/format`, `scripts/lint`, and
  `scripts/test`, with `scripts/common.sh` as their shared preamble. Each is a
  thin wrapper that narrows an existing `just` recipe or native command to this
  one package; none of them reimplements build, lint, or test policy. The native
  Go toolchain runs by default and `MINDCLADE_BAZEL=1` additionally runs the
  Bazel target that CI treats as the authority.

---

## `eb87821` — 2026-09-02

### Changed

- `README.md` documents the post-`5d3e1a2` surface: `FromEnvironment` as the
  only environment-reading path, the uniform long-running-operation verbs, the
  generic watcher, metadata pass-through, the interceptor seam, structured
  `x-mindclade-sdk`, and the observer and logging contract.

---

## `5d3e1a2` — 2026-09-02

Resumable watchers, explicit environment configuration, interceptor and observer
seams (WS2.5, WS2.6, WS2.7).

### Added

- `StreamWatcher[Message, Cursor]` — one generic resumable server-streaming
  reader with `Recv`, `Next`, `Current`, `Err`, `Cursor`, and `Close`, replacing
  four near-duplicate per-domain reconnect loops. It reconnects only inside the
  caller's remaining deadline and always resumes from the last *acknowledged*
  cursor, so no message is replayed or skipped. `Watcher`, `InferenceWatcher`,
  `TrainingWatcher`, and `WorkflowWatcher` are generic aliases of it, so every
  previous name, message type, and cursor type is preserved.
- `ResumeWatch` on `OperationService`, `InferenceService`, `TrainingService`,
  and `WorkflowService`, completing the uniform verb set `Get`, `Wait`, `Watch`,
  `Cancel`, `ResumeWatch`. Every verb accepts `RequestOption`s.
- `FromEnvironment()` — the only path in the package that reads the process
  environment. It recognises exactly `MINDCLADE_ENVIRONMENT`,
  `MINDCLADE_ENDPOINT`, `MINDCLADE_TENANT_ID`, `MINDCLADE_PROJECT_ID`,
  `MINDCLADE_PRINCIPAL_ID`, `MINDCLADE_AUDIENCE`, and `MINDCLADE_LOG`. **No
  credential variable is read, and none ever will be.**
- `WithMetadata` (one call) and `WithDefaultMetadata` (every call) for caller
  metadata pass-through, validated against the credential denylist introduced at
  `339d47c`. A rejected key is an invalid-argument error, never a silent drop.
- `WithInterceptor` and `WithStreamInterceptor` — caller gRPC interceptor seams.
- `WithOmitPlatformMetadata`, `WithLogger`, `RPCEvent`, and `RequestObserver`.
- `Version`, the single SDK revision source stamped into both the gRPC user
  agent and `x-mindclade-sdk`.

### Changed

- **Breaking:** `New` no longer reads `MINDCLADE_*` variables. Configuration
  that previously arrived implicitly through the environment must now pass
  `FromEnvironment()` explicitly. `tools/mindcladectl` relies on this and needs
  the option added to its `New(...)` call.
- Caller interceptors are chained *inside* the SDK's own policy interceptor and
  credential injection happens beneath the whole chain at the transport, so a
  caller interceptor structurally cannot observe or forge an `authorization`
  header.
- `x-mindclade-sdk` carries structured, bounded platform facts —
  `language`, `version`, `os`, `arch`, `runtime`, `runtime_version` — collapsing
  to language and version under `WithOmitPlatformMetadata`.
- Every watcher retries its *initial* connect within budget; previously only the
  workflow watcher did.
- Observer callbacks carry method, attempt, elapsed, status, request id, trace
  id, retry-after, and metadata **key names only** — never payloads,
  credentials, lease tokens, or header values.

### Removed

- The `isRetryable` shim and `workflows.retryableFailure`. `retryableStatus` is
  the only retry predicate left.
- Three duplicate `longRunningContext` helpers, collapsed into one on `Client`.

---

## `339d47c` — 2026-09-02

Retry policy, error hierarchy, raw responses, and auto-pagination (WS2.1–WS2.4).

### Added

- `MindcladeError`, an interface implemented by `*Error` and by eleven concrete
  types: `*AuthenticationError`, `*AuthorizationError`, `*ValidationError`,
  `*ConflictError`, `*NotFoundError`, `*RateLimitError`, `*QuotaError`,
  `*RetryableServiceError`, `*OperationFailedError`, `*CancelledError`, and
  `*TransportError`. Every error carries a stable code, a safe message,
  retryability, retry-after, request id, trace id, operation id, field
  violations, precondition violations, quota state, fence state, conflict
  revision, and a diagnostic reference. The violation types are the generated
  `mindclade.common.v1` messages; the SDK declares no parallel wire model.
- `retryableStatus` — the single retryable-status predicate for the whole SDK,
  replacing four call sites that disagreed about `DEADLINE_EXCEEDED`.
- `WithTimeout` (a **total budget** across every attempt, every backoff wait,
  and credential acquisition), `WithMaxAttempts`, and
  `WithUnsafeRetryOfNonIdempotentRPC` — deliberately not a bare boolean, and
  deliberately powerless over the never-retry denylist.
- `neverRetryMethods`, pinning `RunService.ExpireAttemptLeases` as never
  retryable: not by policy, not by a server trailer, not by a caller override.
- `ResponseMetadata`, `WithResponseMetadata`, `CaptureResponseMetadata`, and
  `ResponseMetadataFromContext`, plus `safeResponseMetadataKeys` — the response
  metadata allowlist that is identical in all four internal SDKs — and
  `credentialBearingKey`, the shared credential denylist applied on top of it.
- Cursor traversal on `Page[T]` (`Items`, `HasNextPage`, `NextPage`, `All`,
  `PageMetadata`) and `WithPaginationLimits`.

### Changed

- **Breaking:** all 26 list methods return a page object instead of the bare
  generated list response. Each page embeds its generated response, so
  `page.GetPage().GetNextPageToken()` and every promoted repeated-field getter
  keep working unchanged. A server response that is nil now yields an empty page
  rather than a nil pointer.
- Retry backoff uses full jitter over `[0, min(cap, base * 2^n)]` drawn from a
  cryptographically seeded, injectable source, so tests can script it.
- Every attempt sends `x-mindclade-retry-count` (0-based) and
  `x-mindclade-timeout-ms` (remaining budget).
- The response trailers `x-mindclade-should-retry` (server override, honoured in
  both directions) and `retry-after-ms` (clamped to the configured maximum
  backoff) are honoured.
- A terminal error exposes `Attempts` and `CumulativeDelay`.
- An unrecognised `RetryClass`, including `UNRECOGNIZED`, maps to `RetryNever`
  and never authorizes a retry.
- `README.md` no longer claims that list methods paginate through the free
  `Paginate` helper. They did not; now they paginate for real, and the claim is
  true in the same revision that made it so.

### Removed

- The `x-mindclade-request-id` alias. Only `x-request-id` is read and emitted,
  and the alias is actively stripped from outgoing metadata.
