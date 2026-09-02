# Mindclade internal SDK

This tree is the handwritten, repository-internal developer experience over
the authoritative generated Protobuf/gRPC clients. It is intentionally placed
under the repository-root `internal/` directory so Go enforces that it cannot
be imported outside this module; the Python, Rust, and TypeScript packages are
also private and unpublished.

The dependency direction is one way:

```text
protocols/proto
    |-> protocols/generated -> internal/sdk -> services, workers, training, tools, and internal applications
    |-> PostgreSQL normalized durable state (through service repositories)
    `-> immutable protobuf event envelopes -> transactional outbox -> Pub/Sub
```

Generated bindings own wire messages, serialization, and RPC signatures. This
layer owns endpoint and credential discovery, secure transport, retry budgets,
idempotency, deadlines, normalized errors, observability, operation helpers,
artifact resolution, and test fakes. It does not redefine persisted resources
or wire models.

SDK clients never access PostgreSQL, GCS, or Pub/Sub directly. Services enforce
tenant-scoped transactions and publish immutable protobuf envelopes only after
the corresponding state transaction commits.

The public-safe `mindclade.api.v1` descriptor and its derived OpenAPI projection
remain a separate compatibility boundary. They may be published later without
making these internal RPCs or this SDK public.

The common Go path keeps orchestration ergonomic while the request and result
cross the wire as generated protobuf messages:

```go
client, err := mindclade.New(
    mindclade.WithEnvironment(mindclade.Development),
    mindclade.WithWorkloadIdentity(),
)
if err != nil {
    return err
}
defer client.Close()

run, err := client.Training.Submit(ctx, mindclade.TrainingJob{
    Model:   mindclade.Model("nova-1"),
    Dataset: mindclade.Dataset("datasets/pdb-2026-08"),
    Recipe:  mindclade.Recipe("pretrain-v4"),
})
```

Endpoint, audience, tenant, project, and principal scope are resolved from the
selected environment and authenticated workload configuration; callers cannot
override server-authoritative identity in a command body.
