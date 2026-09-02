# mindcladectl

`mindcladectl` is a private administrative CLI over the Go internal SDK. It
supports bounded operation inspection/wait/cancellation and generation-pinned,
digest-verified artifact downloads. Existing destination files are never
overwritten.

The CLI obtains short-lived workload identity through the SDK and never talks
to PostgreSQL, Pub/Sub, or GCS directly. Configure the SDK with
`MINDCLADE_TENANT_ID`, `MINDCLADE_PROJECT_ID`, `MINDCLADE_PRINCIPAL_ID`, and
optionally `MINDCLADE_ENDPOINT`, `MINDCLADE_AUDIENCE`,
`MINDCLADE_ENVIRONMENT`, and `MINDCLADE_CLI_TIMEOUT`.

Examples:

```text
mindcladectl operation wait operations/op-123
mindcladectl operation cancel operations/op-123 --etag e1 --reason operator-request --idempotency-key cancel-op-123
mindcladectl artifact download recipes/current ./recipe.json
```
