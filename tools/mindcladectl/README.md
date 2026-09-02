# mindcladectl

`mindcladectl` is a private administrative CLI over the Go internal SDK. It
supports bounded operation inspection/wait/cancellation, generation-pinned and
digest-verified artifact downloads, and bounded experiment listing. Existing
destination files are never overwritten.

The CLI obtains short-lived workload identity through the SDK and never talks
to PostgreSQL, Pub/Sub, or GCS directly. Configuration is read by the SDK's own
`FromEnvironment` option, so `MINDCLADE_TENANT_ID`, `MINDCLADE_PROJECT_ID`,
`MINDCLADE_PRINCIPAL_ID`, `MINDCLADE_ENDPOINT`, `MINDCLADE_AUDIENCE` and
`MINDCLADE_ENVIRONMENT` are parsed and validated in one place. The CLI parses no
`MINDCLADE_*` variable itself except `MINDCLADE_CLI_TIMEOUT`, which bounds the
one total command budget; per-call deadlines, retries and backoff stay with the
SDK.

Retries, pagination, idempotency and verified artifact publication belong to the
SDK. The CLI runs no retry loop and no page loop of its own.

Examples:

```text
mindcladectl operation wait operations/op-123
mindcladectl operation cancel operations/op-123 --etag e1 --reason operator-request --idempotency-key cancel-op-123
mindcladectl artifact download recipes/current ./recipe.json
mindcladectl experiment list --page-size 50
mindcladectl experiment list --all --max-pages 20 --max-items 2000
```

## Listing

`experiment list` returns one page by default and prints the SDK page's own
generated list response on stdout. When the server issued another cursor, the
resumable `--page-token` value is reported on stderr.

`--all` traverses the whole collection through the SDK page's own traversal and
prints one generated experiment per line. `--max-pages` and `--max-items` set
the SDK's `PaginationLimits`; leaving them unset selects the SDK defaults (100
pages, 10,000 items). The SDK enforces both budgets and the hard caps above
them. `--all` starts from the first page and therefore rejects `--page-token`.

Page-size validation belongs to the SDK: an out-of-range `--page-size` comes
back as a validation failure from the control plane rather than from a
duplicated bound in the CLI.

## Request identity

Every SDK-backed command reports the transport identity the SDK captured for the
call on **stderr**, so a success can be correlated with a server log line:

```text
mindcladectl: status=ok request_id=... trace_id=...
```

stdout stays purely the machine-readable generated message, so piping into `jq`
is unaffected.

## Exit codes

Failures are classified with `errors.As` against the SDK error hierarchy. The
CLI never inspects a gRPC status and adds no failure class of its own. On a
failure the SDK's safe structured detail — stable code, retryability,
retry-after, request and trace id, conflict revision, quota state, field and
precondition violations and a diagnostic reference — is printed to stderr.
Start-up failures are classified the same way, so a credential failure during
identity discovery exits 3 rather than being flattened into the generic
configuration code.

| Code | Meaning | SDK error |
|-----:|---------|-----------|
| 0 | success | — |
| 1 | local CLI failure that never reached the SDK | — |
| 2 | SDK configuration or command-budget failure at start-up | — |
| 3 | missing, expired or unverifiable credential | `AuthenticationError` |
| 4 | authenticated but denied by policy | `AuthorizationError` |
| 5 | malformed or out-of-range request | `ValidationError` |
| 6 | absent or invisible resource | `NotFoundError` |
| 7 | concurrent-state conflict | `ConflictError` |
| 8 | throttled or out of budget | `RateLimitError`, `QuotaError` |
| 9 | transient or residual transport fault | `RetryableServiceError`, `TransportError` |
| 10 | durable operation reached terminal failure | `OperationFailedError` |
| 11 | cancelled by the caller or the server | `CancelledError` |
| 12 | deadline exceeded | `TransportError` with code `deadline_exceeded` |
