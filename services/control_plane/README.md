# Control plane service and durability kernel

This component owns tenant-scoped operation acceptance, jobs, runs,
fenced attempts, immutable artifact metadata, and their transactional evidence.
Generated Protobuf service interfaces define the native gRPC transport.
PostgreSQL normalized relations define mutable durable authority, and the
transactional outbox publishes immutable protobuf event envelopes to Pub/Sub
only after commit. Object storage, Pub/Sub, and SDK clients never receive a
database transaction or row type.

The executable currently activates Training, Operation, and worker Run services
through generated gRPC interfaces, the public-safe candidate façade, explicit
SSE, and a descriptor-bound HTTP/JSON gateway. Other registered generated
internal services remain fail-closed until their vertical application adapters
are activated and therefore are absent from the candidate public service.

Workers receive queue envelopes and lease capabilities only. They never receive
a control-plane database interface. A completion must match both attempt ID and
lease epoch; stale completions are retained as audit history and cannot advance
the run.

Run the focused source checks with:

```text
go test ./services/control_plane/...
```

Runtime startup is fail-closed and requires applied migrations, a
`NOSUPERUSER NOBYPASSRLS` PostgreSQL role, Pub/Sub project/topic configuration,
the required `MINDCLADE_PUBSUB_JOB_SUBSCRIPTION` pull subscription, a bounded
`MINDCLADE_QUARANTINE_TENANT_ID`, tenant/project authorization mappings, and
an active `MINDCLADE_LEASE_TOKEN_ACTIVE_KEY_ID` present in the JSON
`MINDCLADE_LEASE_TOKEN_HMAC_KEYS_JSON` key ring. Every key must be a base64
encoding of at least 32 random bytes; retain old key IDs only for bounded
idempotency-replay and rotation windows. Raw lease capabilities are issued to
authenticated workers and are never stored in PostgreSQL or protobuf payloads.
The job subscription is dedicated and filtered on
`attributes.event_type = "mindclade.events.job.v1.JobRequested"`; unrelated
registered events use their own versioned consumers.
Startup also requires
either:

- `MINDCLADE_AUTH_MODE=google-id-token` with an exact audience and
  `MINDCLADE_AUTH_SUBJECT_MAPPINGS`, a JSON object mapping each verified Google
  token subject to its own `tenant_id`, `project_id`, `principal_id`, optional
  `worker_id`, and explicit `roles`; or
- `MINDCLADE_AUTH_MODE=static` only when `MINDCLADE_ENVIRONMENT` is `local` or
  `test` and `MINDCLADE_ALLOW_STATIC_AUTH_FOR_TESTING=true`, with a high-entropy
  test token. Static authentication is rejected in development, staging, and
  production.

The Google mapping is the authorization source; callers cannot select a tenant
or project through request fields or metadata, and human/service identities are
never implicitly promoted to workers. Supported roles are `platform`, `worker`,
`scheduler`, `auditor`, and `admin`.
Authorization is checked against the exact generated RPC method after token
verification; client expected-tenant/project/principal metadata is an
additional mismatch assertion and never grants authority.

Both listeners bind to loopback. TLS termination and external routing belong to
the authenticated workload proxy; source readiness does not authorize a
connected or production deployment.
