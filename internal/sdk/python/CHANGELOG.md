# Changelog — `mindclade-internal-sdk` (Python)

This package is private and is never published, so it carries **no SemVer
line**. `pyproject.toml` and `mindclade_internal_sdk/_version.py` pin `0.1.0`
only because the packaging tooling requires a version field and because a
support report needs a stable name for the build it came from; it is not a
compatibility promise and it does not move when behaviour changes.

Entries below are therefore keyed by **source revision**, newest first. A
revision heading names the commit in which the change landed; work that has not
yet been committed is headed `Unmerged` and records the revision it was authored
against, so a reader can always reproduce the tree an entry describes.

Every entry states the SDK-visible behaviour change. Changes confined to tests,
comments, or formatting are not recorded here.

---

## Unmerged — authored against `483574e`

Work items WS2.1 through WS2.9: retry and timeout policy, error hierarchy, raw
responses, auto-pagination, streaming and long-running-operation parity,
configuration and escape hatches, observability, packaging, and documentation.

### Added

- `.with_raw_response` on every resource namespace of both clients. It runs the
  same ergonomic method — every identity, digest, fence, and protocol check
  still executes — and returns the value beside the RPC's status, request id,
  trace id, and an allowlisted response-metadata subset. `RawResponse`,
  `SAFE_RESPONSE_METADATA_KEYS`, `CREDENTIAL_METADATA_KEYS`, and
  `is_credential_metadata_key` are exported.
- `Client.from_env()` and `AsyncClient.from_env()`, the only path by which this
  SDK reads process environment. They recognise exactly `MINDCLADE_ENVIRONMENT`,
  `MINDCLADE_ENDPOINT`, `MINDCLADE_TENANT_ID`, `MINDCLADE_PROJECT_ID`,
  `MINDCLADE_PRINCIPAL_ID`, `MINDCLADE_AUDIENCE`, and `MINDCLADE_LOG`. **There is
  no credential environment variable**: the token provider stays an explicit
  argument.
- `Operations.resume_watch` / `AsyncOperations.resume_watch`, completing the
  uniform long-running-operation verb set `get` / `wait` / `watch` / `cancel` /
  `resume_watch`. `after_sequence` is required, so a resume can never silently
  replay from the beginning.
- One generic resumable watcher (`WatchStream`, `AsyncWatchStream`, `WatchSpec`)
  behind `operations.watch`, `training.watch`, `inference.watch`, and
  `workflows.watch`. The streams are context managers, expose `request_id`,
  `trace_id`, and `cursor`, and accept per-request `CallOptions`.
- `custom_metadata=`, `omit_platform_metadata=`, and `middleware=` client
  options. Each interceptor is wrapped in a credential shield, so credential
  injection stays inside the SDK and is not interceptable.
- `MINDCLADE_LOG` level handling through the stdlib `logging` module, plus
  `LoggingObserver`, `default_observer`, and `log_level_from_env`.
- Per-request `CallOptions.max_attempts`, an injectable `RetryPolicy.jitter`
  source (`JitterSource`, `SystemJitter`, `FixedJitter`), and `RetryTrace` on
  raised errors carrying attempts, cumulative delay, and final cause.
- Contract-named error types `ValidationError`, `RetryableServiceError`, and
  `QuotaError`, and typed error state `FieldViolation`,
  `PreconditionViolation`, `QuotaState`, `FenceState`, plus `error_from_detail`
  for projecting a generated `ErrorDetail`.
- `component.yaml` registering component `internal-sdk-python` (owner
  `developer-experience`). `workers-training-worker` already declared a
  dependency on this component name; the metadata now exists to resolve against.
- `scripts/bootstrap`, `scripts/build`, `scripts/lint`, `scripts/format`, and
  `scripts/test` — thin wrappers over the `just` recipes, so the package
  presents the same five entry points as every other maintained package. `just
  format` and `just lint` remain the repository-wide authority.
- `mindclade_internal_sdk/_version.py`, the single version source, stamped into
  `x-mindclade-sdk` and asserted equal to the `pyproject.toml` version.
- `CHANGELOG.md` (this file).

### Changed

- Retry is one policy in one module: a single retryable-status predicate for the
  whole SDK, full jitter drawn from `secrets.SystemRandom`, a per-request
  timeout that is a **total budget** across every attempt *and* credential
  acquisition, and a per-request attempt cap that may narrow but never widen the
  client policy.
- Every attempt now sends `x-mindclade-retry-count` (0-based) and
  `x-mindclade-timeout-ms` (remaining budget). The SDK honours the
  `retry-after-ms` response trailer as a floor clamped to the configured maximum
  backoff, and the `x-mindclade-should-retry` trailer as a server override in
  both directions — though no trailer can promote a non-idempotent RPC, and
  `RunService.ExpireAttemptLeases` is never retried.
- Every ergonomic list method on both clients returns a `Page` / `AsyncPage`
  that iterates items transparently across pages while keeping page-level
  access, and enforces explicit item and page budgets. Generated response fields
  remain readable on the page object, so existing call sites are unaffected.
- `x-mindclade-sdk` now carries structured, bounded platform facts (`lang`,
  `os`, `arch`, `runtime`, `runtime_version`) drawn from closed allowlists, and
  its version segment moved from `0.1` to the single-source `0.1.0`.
  `omit_platform_metadata=True` reduces it to the bare name and version.
- `workflows.watch` now raises the failure that actually ended the stream once
  the retry budget is spent, instead of masking it behind a generic
  `ProtocolError`.
- Watch reconnects carry the caller's lease token and idempotency key onto every
  attempt. `operations.watch` and `training.watch` previously dropped both, and
  `inference.watch` dropped both as well.
- `README.md` rewritten into the standard SDK section order (Installation,
  Usage, Request/response types, Pagination, Long-running operations, Streaming,
  Errors, Retries, Timeouts, Raw responses, Escape hatches and interceptors,
  Configuration and environment variables, Logging, Versioning, Status) followed
  by the appendix-A08 package contract.

### Fixed

- `mindclade_internal_sdk.resources` and `mindclade_internal_sdk.testing` are
  now exported from the package `__init__`. `README.md` and consumer code
  already imported them; the attributes did not exist until an explicit
  submodule import ran.
- The README claimed `paginate` and `apaginate` made every ergonomic list method
  lazily traversable. They did not: no list method returned a paginator. The
  claim is removed in the same change that makes transparent pagination real.
- Two bare `assert` statements in the synchronous and asynchronous retry loops,
  which a `python -O` run would have removed, leaving the loop to fall off its
  end and return `None`.

### Removed

- The `x-mindclade-request-id` response-metadata alias. The SDK reads and emits
  `x-request-id` only.
