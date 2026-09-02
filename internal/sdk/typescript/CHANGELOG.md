# Changelog — `@mindclade/internal-sdk`

This package is private and is never published, so it carries **no SemVer
line**. `package.json` pins `0.1.0` only because the workspace tooling requires
a version field; it is not a compatibility promise and it does not move when
behaviour changes. The compatibility promise is the one in `README.md`:
consumers are pinned to a **source revision** of this monorepo and build the
facade from that revision's sources together with that revision's generated
contracts.

Entries below are therefore keyed by **source revision**, newest first. A
revision heading names the commit in which the change landed; work that has not
yet been committed is headed `Unmerged` and records the revision it was authored
against, so a reader can always reproduce the tree an entry describes.

Every entry states the SDK-visible behaviour change. Changes confined to tests,
comments, or formatting are not recorded here.

---

## Unmerged — authored against `e99e48d`

Packaging and documentation (WS2.8, WS2.9), plus two watcher corrections found
in review.

### Fixed

- `watchStream` looked its reconnect budget up under a hard-coded `safe` safety
  class instead of the watch route's own classification, which made `safety.ts`
  no longer the single classifier for the streaming path. It now resolves the
  class from `source.route`, exactly as the unary path does. No shipped watcher
  changes behaviour: all four watch routes are `safe`.
- A watcher failure escaped without the observable retry outcome the unary path
  attaches. `MindcladeError.retry` is now populated on watcher failures too,
  reporting the reconnects and cumulative backoff since the last acknowledged
  update.
- The README claimed every watcher skips a redelivered prefix. Only `operations`
  skips; `inference`, `workflows`, and `training` are strictly contiguous and
  reject a replay as a terminal `protocol` failure. The claim is corrected.

### Added

- `component.yaml` registering component `internal-sdk-typescript` (owner
  `developer-experience`). `apps-console` already declared a dependency on this
  component name; the metadata now exists for it to resolve against.
- `scripts/bootstrap`, `scripts/build`, `scripts/lint`, `scripts/format`, and
  `scripts/test` — thin wrappers over the `package.json` scripts, so the package
  presents the same five entry points as every other maintained package. `just
  format` and `just lint` remain the repository-wide authority.
- `pnpm run format` in `package.json`, scoping the repository Biome
  configuration to this package.
- `REGISTERED_ROUTES`, the sorted route list of the hand-maintained retry-safety
  table, exported so a test can prove the table still covers all 132 descriptor
  routes rather than silently falling back to the unknown-route default.
- `CHANGELOG.md` (this file).

### Changed

- `README.md` rewritten into the standard SDK section order (Installation,
  Usage, Request/response types, Pagination, Long-running operations, Streaming,
  Errors, Retries, Timeouts, Raw responses, Escape hatches and interceptors,
  Configuration and environment variables, Logging, Versioning, Status) followed
  by the appendix-A08 package contract (owner, entrypoints, data
  classifications, dependency restrictions, compatibility contract, failure
  modes, retryable-versus-terminal errors, status).

### Fixed

- The README claimed the package consumed "generated Protobuf-ES **and Connect**
  contracts". There is no connect-es code generation in this repository:
  `protocols/generated/typescript` contains protobuf-ES descriptors (`*_pb.ts`)
  only, and Connect clients are constructed at runtime by `createClient` against
  those descriptors. The claim is corrected.

---

## `e99e48d` — 2026-09-02

### Changed

- `PageMetadata` renamed to **`SdkPageInfo`**. The protobuf estate already owns
  `mindclade.api.v1.PageMetadata`, a different contract type
  (`next_page_token`, `snapshot_token`); the SDK type carries page provenance
  (request ID, page token, page index, page size). Reusing the name would have
  been a handwritten wire model. **Breaking** for anyone who imported the type
  by name; `Page.metadata` is unchanged in shape and position.

### Fixed

- The retry-safety table classified 122 of the descriptor's 132 RPCs; the
  remaining ten fell through to the unknown-route default. All 132 are now
  classified, and the classification agrees route-for-route with the Go, Python,
  and Rust tables.

---

## `5d3e1a2` — 2026-09-02

Resumable watchers, explicit environment configuration, interceptor and observer
seams (WS2.5, WS2.6, WS2.7).

### Added

- `watchStream` — one generic resumable watcher (`src/watch.ts`) replacing four
  hand-rolled per-domain reconnect loops. Reconnection happens only inside the
  caller's remaining deadline and only from the last *acknowledged* cursor; a
  redelivered prefix is skipped rather than yielded twice.
- Uniform long-running-operation verbs: `resumeWatch` on `operations`,
  `inference`, `workflows`, and `training`; `training.wait`; `TrainingRunFailure`.
- `MindcladeClient.fromEnvironment` and `clientConfigFromEnvironment` — the only
  environment-reading path in the package. It recognises exactly
  `MINDCLADE_ENVIRONMENT`, `MINDCLADE_ENDPOINT`, `MINDCLADE_TENANT_ID`,
  `MINDCLADE_PROJECT_ID`, `MINDCLADE_PRINCIPAL_ID`, `MINDCLADE_AUDIENCE`, and
  `MINDCLADE_LOG`. **No credential variable is read, and none ever will be.**
- `ClientConfigInput.metadata`, `.interceptors`, `.observer`, `.logger`,
  `.logLevel`, and `.omitPlatformMetadata`.
- `Observer`, `Logger`, `LogLevel`, `consoleLogger`, `levelFromEnvironment`
  (`src/observability.ts`). Events carry method, attempt, elapsed time, status,
  request ID, and metadata **key names only** — never payloads, credentials,
  lease tokens, or header values.
- `SDK_NAME`, `SDK_VERSION`, `platformMetadata` (`src/platform.ts`): the single
  identity source stamped into `x-mindclade-sdk`.

### Changed

- Transport layering is now `metadata -> caller interceptors -> credential
  injection -> Connect`. An interceptor can observe and decorate a request but
  can neither read nor forge `authorization`; an interceptor that sets it is
  stripped and overwritten at the wire.
- `x-mindclade-sdk` carries structured, bounded platform facts
  (`name/version;lang=;os=;arch=;runtime=;runtime_version=`), collapsing to
  name, version, and language under `omitPlatformMetadata`.
- `invokeUnary`'s third parameter is the route rather than a safety class, so
  `src/safety.ts` is the only classifier and no facade can name its own.

### Fixed

- The message-size ceiling was 16 MiB while every other Mindclade SDK used
  8 MiB. It is now `MAX_MESSAGE_BYTES = 8 MiB` in both directions.
- Stream reconnects now advertise `x-mindclade-retry-count` and
  `x-mindclade-timeout-ms`, and the remaining timeout is computed identically in
  all four watchers.

---

## `339d47c` — 2026-09-02

Retry policy, error hierarchy, raw responses, and auto-pagination (WS2.1–WS2.4).

### Added

- Eleven error classes extending `MindcladeError`: `AuthenticationError`,
  `AuthorizationError`, `ValidationError`, `ConflictError`, `NotFoundError`,
  `RateLimitError`, `QuotaError`, `RetryableServiceError`,
  `OperationFailedError`, `CancelledError`, `TransportError`. Every error
  carries a stable code, a safe message, retryability, retry-after, request ID,
  trace ID, operation ID, field violations, precondition violations, quota
  state, fence state, conflict revision, and a diagnostic reference.
- `shouldRetry` — the single retryable-status predicate for the whole SDK.
- Per-request `timeoutMs` (a **total budget** across every attempt, backoff, and
  credential acquisition) and per-request `maxAttempts`.
- `withUnsafeRetryOfNonIdempotent(justification)` — the only way to retry an
  RPC the safety table calls non-idempotent. Deliberately not a bare boolean.
- `Page` and `listPage` (`src/pagination.ts`). Every list method now returns a
  page that iterates items transparently across page boundaries while keeping
  page-level access.
- `client.withResponse()` and `RawResponse` (`src/response.ts`), plus
  `SAFE_RESPONSE_METADATA` — the response-metadata allowlist that is identical
  in all four internal SDKs.
- `isNeverRetryable`, pinning `RunService.ExpireAttemptLeases` as never
  retryable, not even under an explicit override.

### Changed

- Retry backoff uses full jitter over `[0, min(cap, base * 2^n)]` from a
  cryptographically seeded, injectable source.
- Every attempt sends `x-mindclade-retry-count` (0-based) and
  `x-mindclade-timeout-ms` (remaining budget).
- Response trailers `x-mindclade-should-retry` (server override, both
  directions) and `retry-after-ms` (clamped to `maxBackoffMs`) are honoured.
- A terminal error exposes `retry.attempts`, `retry.cumulativeDelayMs`, and
  `retry.cause`.
- **Breaking:** list methods return `Page<Item, Response>` instead of the bare
  generated list response. The generated response remains available, unchanged,
  as `page.response`.

### Removed

- The `x-mindclade-request-id` alias, and the `request-id` read fallback. Only
  `x-request-id` is read and emitted.
