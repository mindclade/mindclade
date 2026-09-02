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
