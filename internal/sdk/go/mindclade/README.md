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
endpoint. TLS is mandatory outside the local loopback test profile.

Generated clients remain available through `client.Transport()` for activated
RPCs that do not yet have an ergonomic helper. This escape hatch remains inside
the repository; it does not change Protobuf authority.

The sole intentional raw-only RPC is `RunService.ExpireAttemptLeases`, a
control-plane reconciler primitive. Application code should use the fenced
run/attempt lifecycle helpers and must not treat this raw method as a retryable
or stable ergonomic SDK operation.

`client.Artifacts.DownloadFile(ctx, artifact, path)` downloads to a private
same-directory staging file, verifies the complete immutable digest, and
publishes with an atomic no-clobber link. It never replaces an existing path.
Successful link creation is the commit point; corruption, cancellation, and
write failure before that point leave the destination absent or unchanged.
