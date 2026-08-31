# Authoritative Contract Integration Plan

Status: active implementation plan. The blueprint is architectural guidance; its historical
waves are metadata, not implementation gates. Update the stage checkboxes only when the stated
exit criteria are evidenced.

## Authority chain

```text
Protobuf resources, services, and events
  ├─> generated internal Go/Python/Rust/TypeScript clients and servers
  ├─> normalized PostgreSQL durable state through private row mappers
  ├─> transactional outbox -> immutable protobuf Pub/Sub delivery
  └─> public-safe mindclade.api.v1 -> raw -> curated -> published OpenAPI 3.1
                                           ├─> Mindclade SDK Forge on OAGen typed IR (primary)
                                           ├─> Fern (qualified shadow)
                                           ├─> Speakeasy (commercial benchmark/fallback)
                                           └─> Stainless (legacy comparison only)

JSON Schema 2020-12 -> large artifact documents, generated typed bindings, and validators.
PostgreSQL -> mutable durable state. OpenAPI -> checked public projection, never source authority.
```

Artifact documents remain JSON-Schema-authoritative and are referenced from protobuf through
`ArtifactRef`; their fields are not duplicated into protobuf resources. Public APIs never expose
internal leases, fences, storage locators, delivery envelopes, executable plans, secrets, or
client-supplied identity context.

## Stages and exit criteria

- [x] Stage 0 — Preserve existing work and archive predecessor contract authority.
- [ ] Stage 1 — Establish authority ADRs and a candidate contract estate. The v1 descriptor and
  OpenAPI sets remain candidates until the training vertical passes end-to-end conformance.
- [ ] Stage 2 — Pin hermetic generators and implement descriptor -> raw -> curated -> published
  OpenAPI with exact HTTP-binding and ProtoJSON parity.
- [ ] Stage 3 — Implement foundation contracts, the `mindclade.*` Python namespace,
  cross-language conformance, an event registry, schema bindings, and a hard public import
  boundary. Every generated package must have a declared real consumer.
- [ ] Stage 4 — Complete the training vertical end to end. Ownership is
  `Operation 1:1 DomainRun`, `DomainRun 1:N Job`, `Job 1:N Attempt`, and
  `Attempt 1:N Checkpoint`. Include PostgreSQL parity, transactional outbox/inbox, Pub/Sub,
  atomic lease acquire/renew/heartbeat/expiry/cancel, gRPC, HTTP gateway, explicit resumable SSE,
  and real Go/Python/Rust consumers.
- [ ] Stage 5 — Ratify the integrated candidate descriptor and published OpenAPI as v1, establish
  the new breaking baselines, and begin normal compatibility enforcement.
- [ ] Stage 6 — Add dataset, transform, feature, experiment, model, inference, evaluation,
  workflow, policy, agent, approval, audit, and administration verticals atomically with their
  first producer, consumer, fixtures, persistence mapping, events, and public projection where
  intended.
- [ ] Stage 7 — Compile provider-neutral Mindclade SDK policy through the owned SDK Forge using
  OAGen's typed IR. Qualify Go/Python/TypeScript packages, Fern shadow generation, and Speakeasy
  benchmarking with pinned inputs, surface/behavior parity, provenance, privacy, license, and
  exit/escrow controls. Stainless remains opt-in legacy comparison only.
- [ ] Stage 8 — Make console, CLI, examples, and the bounded analysis agent consume released
  public SDKs rather than service internals or database packages.
- [ ] Stage 9 — After connected-governance approvals, deploy dev, qualify staging, and use
  protected GitOps production promotion. No source completion grants connected-cloud authority.
- [ ] Stage 10 — Run reliability, security, evidence, recovery, workload, scientific, and
  production qualification drills, including PA-01 through PA-16 and SQP-001 thresholds.
- [ ] Acceptance review — Prove no orphan or duplicate contracts; deterministic generation;
  four-language wire, ProtoJSON, schema, and gRPC conformance; persistence and tenant parity;
  event replay/deduplication/fencing; SDK packaging and behavior parity; signed releasable
  artifacts; protected promotion; rollback/revocation; and required post-launch review evidence.

## Non-negotiable implementation laws

- Generated protobuf resources are repository values only when repositories clone messages,
  validate contract and aggregate invariants, require expected revision/etag, and require the
  current fence for attempt-owned writes. Private SQL rows never escape persistence packages.
- Credentials and principal/tenant identity come from authenticated transport metadata. HTTP,
  gRPC, and SSE adapters apply equivalent authentication, authorization, validation,
  idempotency, error, request-ID, trace, and audit policies before calling the same application
  service.
- gRPC server streams are not public SSE. The explicit operation-event SSE adapter defines event
  IDs, schema versions, revisions, cursors, heartbeats, reconnect/retention behavior, terminal
  events, and cursor-expired errors.
- SDK validation, policy compilation, emission, surface extraction, behavior verification,
  packaging, publishing, and release orchestration are separate interfaces. Only release
  orchestration emits a publication receipt.
- Schema and database evolution use expand-migrate-contract; event evolution is versioned;
  deployments retain rollback and artifact revocation at every promotion.
