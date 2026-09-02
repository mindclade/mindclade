# Mindclade internal Go SDK

This private module façade wraps the generated gRPC clients. It is not a second
wire-model layer and cannot be imported by Go modules outside the Mindclade
repository because its path is beneath the repository-root `internal/` tree.

```go
client, err := mindclade.New(
    mindclade.WithEnvironment(mindclade.Development),
    mindclade.WithWorkloadIdentity(),
)
if err != nil {
    return err
}
defer client.Close()

operation, err := client.Training.Submit(ctx, mindclade.TrainingJob{
    Model:   mindclade.Model("nova-1"),
    Dataset: mindclade.Dataset("datasets/pdb-2026-08"),
    Recipe:  mindclade.Recipe("pretrain-v4"),
})
```

`MINDCLADE_TENANT_ID`, `MINDCLADE_PROJECT_ID`, and
`MINDCLADE_PRINCIPAL_ID` provide the expected scope and correlation identity;
callers may instead use `WithTenantProject`. Credentials are discovered through
Application Default Credentials only when `WithWorkloadIdentity` is explicit.
That option mints a short-lived Google workload-identity ID token, not a broad
cloud-platform access token. `MINDCLADE_AUDIENCE` or `WithAudience` must match
the control-plane verifier; otherwise the audience is derived from the secure
endpoint as an HTTPS origin with the default `:443` port omitted. TLS is
mandatory outside the local loopback test profile.

Generated clients remain available through `client.Transport()` for activated
RPCs that do not yet have an ergonomic helper. This escape hatch remains inside
the repository; it does not change Protobuf authority.

The descriptor-bound coverage gate fixes the current surface at 15 services
and 132 RPCs: 127 unary and five server-streaming, with 131 ergonomic methods
and one reviewed raw-only method.

Every ergonomic list method returns a page object that embeds its generated
response, so `page.GetPage().GetNextPageToken()` and the generated repeated
field keep working unchanged, and adds cursor-scheme traversal on top:

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

for page.HasNextPage() { // or walk one page at a time
    page, err = page.NextPage(ctx)
    if err != nil {
        return err
    }
}
```

`All` traverses lazily, preserves opaque tokens byte-for-byte, rejects cursor
loops, and re-runs the owning list method's scope validation on every fetched
page. It stops at the traversal budget: 100 pages and 10,000 items by default,
`WithPaginationLimits` to change it, and hard caps of 1,000 pages and 1,000,000
items. `NextPage` returns a nil page and a nil error at the end of a
collection. The lower-level `Paginate` helper remains available for traversing
a collection the SDK does not yet model as a list method.

`WithResponseMetadata(&metadata)` captures the transport response of one call —
status, request id, trace id, and an allowlisted safe metadata subset that
excludes every credential-bearing key. It is the only way to obtain a request
id for a call that succeeded. `CaptureResponseMetadata`/
`ResponseMetadataFromContext` do the same through a context when threading a
record is impractical.

The sole intentional raw-only RPC is `RunService.ExpireAttemptLeases`, a
control-plane reconciler primitive. Application code should use the fenced
run/attempt lifecycle helpers and must not treat this raw method as a retryable
or stable ergonomic SDK operation.

`client.Artifacts.DownloadFile(ctx, artifact, path)` downloads to a private
same-directory staging file, verifies the complete immutable digest, and
publishes with an atomic no-clobber link. It never replaces an existing path.
Successful link creation is the commit point; corruption, cancellation, and
write failure before that point leave the destination absent or unchanged.

Persist a command's `IdempotencyKey` with the caller's durable intent before
submission so crash/restart retries reuse the same identity. Use
`Operations.Watch` for bounded resumable iteration and propagate its context
cancellation. Runtime checks cover credentials, scope, correlation metadata,
deadlines, page budgets, stream identity, and artifact integrity; generated
protobuf types and the server own ordinary request-field constraints.

Run focused tests with `go test ./internal/sdk/go/mindclade`.
