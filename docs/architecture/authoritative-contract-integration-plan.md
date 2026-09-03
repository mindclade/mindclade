# Authoritative Contract Integration Plan

Status: active implementation plan. The blueprint is architectural guidance; its historical
waves are metadata, not implementation gates. Update the stage checkboxes only when the stated
exit criteria are evidenced.

## Authority chain

```text
Protobuf resources, services, and events
  ├─> generated internal Go/Python/Rust/TypeScript clients and servers
  │    ├─> allowlisted server adapters and persistence protobuf mappers
  │    └─> sdks/{go,python,rust,typescript}
  │         └─> client-side services, workers, training, tools, console, CLI, and apps
  ├─> normalized PostgreSQL durable state through private row mappers
  ├─> transactional outbox -> immutable protobuf Pub/Sub delivery
  └─> externally safe mindclade.api.v1 -> raw -> curated -> published OpenAPI 3.1
                                           ├─> internal HTTP gateway and documentation
                                           ├─> Fern (optional internal REST SDK)
                                           └─> Speakeasy (optional specialized REST tooling)

JSON Schema 2020-12 -> large artifact documents, generated typed bindings, and validators.
PostgreSQL -> mutable durable state. OpenAPI -> checked HTTP projection, never source authority.
```

## Private SDK decision

The internal SDK is not an OpenAPI SDK-generator product. Buf and the pinned native
Protobuf, gRPC, and Connect generators are the only transport-generation foundation.
Mindclade-owned code above those bindings is a deliberately thin behavior façade:

```text
protocols/proto
  -> protocols/generated/{go,python,rust,typescript}
  -> sdks/{go,python,rust,typescript}
  -> client-side services, workers, training, tools, console, CLI, and internal apps

server request
  -> generated server adapter
  -> application service
  -> normalized PostgreSQL transaction
       + transactional protobuf outbox
  -> immutable protobuf Pub/Sub delivery
```

The generated layer owns messages, enums, serialization, RPC signatures, and low-level
clients. The handwritten layer owns endpoint selection, workload identity, TLS, bounded
deadlines and retries, idempotency, correlation and tracing metadata, normalized errors,
pagination, resumable watches, artifact-transfer orchestration, and hermetic fakes. It must
accept and return generated resource types and must not introduce a second wire or durable
domain model.

SDK clients never connect to PostgreSQL, Pub/Sub, or provider object storage. Artifact bytes
flow through generated internal transfer RPCs; the server verifies digests and sizes, records
durable staging receipts, commits content-addressed GCS objects, and publishes catalog events
through the outbox. Direct storage adapters are server-only implementation details.

The clean-room SDK-compiler proposal in `deep-research-report-3.md` remains useful as a
conformance and future-public-SDK research reference, especially for retry, pagination,
streaming, deterministic generation, and supply-chain tests. Building that compiler is not a
dependency of the private SDK. Fern and Speakeasy remain optional comparisons only if a future
HTTP-native distribution is approved; Stainless and provider configuration are not part of the
architecture.

Artifact documents remain JSON-Schema-authoritative and are referenced from protobuf through
`ArtifactRef`; their fields are not duplicated into protobuf resources. Public APIs never expose
internal leases, fences, storage locators, delivery envelopes, executable plans, secrets, or
client-supplied identity context.

`mindclade.api.v1` and its raw -> curated -> published OpenAPI projection are internally
distributed during this program but deliberately remain externally safe. No public support or
publication commitment exists yet; a future public launch may ratify and publish this boundary
without changing internal RPC, persistence, event, or SDK authority.

## Adapted execution checklist

Internal/private SDK authority is Buf-generated protobuf, gRPC, and Connect transport code plus
Mindclade-owned ergonomic facades. Normalized PostgreSQL state and immutable protobuf Pub/Sub
events remain authoritative behind service boundaries. OpenAPI and third-party provider tooling
exist only as a future-public escape hatch.

- [x] Preserve user work, archive predecessor authority, and keep v1 candidate-only.
- [ ] Resolve every review finding across Bazel, contracts, OpenAPI parity, the public-safe
  boundary, persistence, eventing, leases, schemas, namespaces, and orphan gates.
- [ ] Complete and register every declared gRPC vertical with normalized PostgreSQL repositories
  and immutable transactional-outbox/Pub/Sub events.
- [ ] Complete generated Go, Python, Rust, and TypeScript transports and comprehensive private SDK
  facades with real downstream consumers.
- [ ] Finish remaining domain and scientific consumers, retaining the future-public
  OpenAPI/provider escape hatch without making it internal authority.
- [ ] Run reproducibility, cross-language, PostgreSQL, event, transport, SDK, security,
  reliability, and production-qualification gates.
- [ ] Perform the final production-grade review, update governed manifests and evidence, commit,
  reconcile the remote safely, and push.

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
  intended. Feature and transform remote execution deliberately reuse the authoritative
  `Job`/`Run`/`Attempt` services plus the bounded `ExecuteTransformCommand` and
  `MaterializeFeaturesCommand` payloads; they do not introduce a generic transform service or a
  mutable feature-store API. Experiment metadata is normalized control-plane state and links to
  immutable manifests and domain runs rather than becoming a provider-owned experiment store.
- [ ] Stage 7 — Treat Buf plus pinned native Protobuf, gRPC, and Connect generators as the
  authoritative internal transport SDK for Go, Python, Rust, and TypeScript. Build thin
  handwritten internal facades in `sdks/{go,python,rust,typescript}` above generated
  transports for endpoints, workload identity, tracing, retries, idempotency, pagination,
  operation polling, artifact transfer, errors, and test fakes. Fern is optional only for
  internal HTTP-native clients; Speakeasy is optional for specialized hooks, CLIs, or Terraform
  generation. Neither is authority, and Stainless is not adopted.
- [ ] Stage 8 — Make console, CLI, examples, and the bounded analysis agent consume the internal
  SDK facades rather than raw service internals or database packages.
- [ ] Stage 9 — After connected-governance approvals, deploy dev, qualify staging, and use
  protected GitOps production promotion. No source completion grants connected-cloud authority.
- [ ] Stage 10 — Run reliability, security, evidence, recovery, workload, scientific, and
  production qualification drills, including PA-01 through PA-16 and SQP-001 thresholds.
- [ ] Acceptance review — Prove no orphan or duplicate contracts; deterministic generation;
  four-language wire, ProtoJSON, schema, and gRPC conformance; persistence and tenant parity;
  event replay/deduplication/fencing; SDK packaging and behavior parity; signed releasable
  artifacts; protected promotion; rollback/revocation; and required post-launch review evidence.

## Non-negotiable implementation laws

- Every gRPC service and RPC signature is declared in a versioned `.proto`
  source. Runtime adapters implement and register only the generated server
  interfaces, and SDK transports invoke only the generated client contracts;
  handwritten parallel service definitions are forbidden.
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
- Generated transport code owns wire types and RPC signatures only. Internal SDK facades own
  ergonomic behavior and may not duplicate wire models. Provider-backed REST generation remains
  optional and can never become contract, build, release, or availability authority.
- The default dependency direction is `protocols/proto -> protocols/generated -> sdks
  -> client-side services/workers/training/tools/internal applications`. Direct generated imports
  are restricted to SDK implementations, server transport adapters, persistence protobuf mappers,
  and contract tests; every other raw generated import fails architecture tests.
- Feature and transform workers consume generated bounded commands from immutable Pub/Sub
  deliveries, resolve artifact references through generated artifact RPCs, and commit outcomes
  through the generated fenced job/run protocol. Large graphs, arrays, lineage maps, and receipts
  remain JSON-Schema-authoritative artifacts; neither the SDK nor Pub/Sub payloads embed them.
- `sdks` is the physical repository path because Go's compiler reserves an `internal`
  path segment for import visibility. Placing it at the repository root makes it importable by all
  Mindclade packages while preventing external Go modules from importing it. Python, Rust, and
  TypeScript packages at the same boundary are explicitly private and unpublished.
- Schema and database evolution use expand-migrate-contract; event evolution is versioned;
  deployments retain rollback and artifact revocation at every promotion.

## Completion work queue

These items are part of the acceptance review and must be completed before the candidate can be
ratified or this program can be committed as production-ready:

1. Freeze concurrent writers after the current bounded SDK work, perform deterministic protocol
   regeneration, and run isolated `just check`, `just test-affected`, canonical Bazel, Buildifier,
   and generated-drift gates. Resolve the known Pairformer BUILD lint findings.
2. Make each event-registry entry declare owner, lifecycle state, compatibility policy, canonical
   fixture, producers, and consumers. The protocol generator validates those declarations and
   projects them into every generated registry.
3. Resolve candidate-only feature, transform, and experiment surfaces before v1 ratification:
   each receives real authority-aligned producers/consumers, or is explicitly deferred and omitted
   from the ratified descriptor rather than accepted as an orphan.
4. Replace scattered numeric-conversion suppressions with checked shared conversions such as
   positive aggregate sequences and bounded PostgreSQL/protocol integer conversions.
5. Generate SDK RPC-coverage metadata from service descriptors. Every RPC must be classified as an
   ergonomic façade, intentional raw-only escape hatch, or explicitly unsupported with a reviewed
   reason, identically across Go, Python, Rust, and TypeScript.
6. Build one reusable reliability harness for publish-before-ack crashes, duplicate/reordered/gapped
   delivery, poison events and DLQ replay, inbox rollback, expired/stale fences, and cancellation
   races.
7. Run PostgreSQL suites from empty ephemeral databases under the migration manager, validate
   constraints and transactions, and separately prove down/up sequencing.
8. Replace hard-coded path-policy activation tuples with schema-validated declarative activation
   bundles while retaining an explicit reviewed path inventory and generated counts/digests.
9. Bind the eventual ratification receipt to descriptor, OpenAPI, event-registry, migration,
   toolchain-lock, generated-manifest, SDK-package, Git-revision, and qualification-result digests.
10. Cache the Rust protobuf plugins by immutable toolchain digest so deterministic regeneration
    builds them once and reuses the exact output.
11. Close the experiment vertical before adding contract surface: checked pagination conversions,
    generated-client network coverage, identical `x-request-id` metadata behavior in all four SDKs,
    descriptor-current SDK/gRPC projections, and four-language evidence for all 132 internal RPCs.
12. Make contract generation one atomic transaction. Stage and validate the descriptor, native
    transports, OpenAPI projection, event-registry projection, SDK coverage, gRPC implementation
    coverage, and generated-file manifest before replacing any committed output. Use the candidate
    descriptor digest as the join key in every projection and refuse partial updates.
13. Make a fresh-database `integration-ci` receipt a mandatory qualification gate. It must apply
    every migration from empty state, rehearse the complete down/up sequence, exercise every domain
    repository plus reliability/DLQ/RLS/training-fence behavior, and fail rather than silently skip
    required PostgreSQL tests.
14. Produce a deliberately non-ratifying training-evidence rehearsal bound to the exact descriptor,
    OpenAPI, event registry, migration set, codegen lock, generated manifest, SDK packages, source
    revision, and cross-language/database/event/gateway/gRPC/SDK results. Protected Stage 5 remains
    the only path that can turn that rehearsal into ratification evidence.
15. Finish Stage 8 narrowly with governed SDK examples for submit, operation watch/follow, and
    verified artifact download plus one bounded analysis application. Generate a readiness report
    mapping every plan criterion to its Bazel target, test, receipt, and current evidence state;
    keep connected qualification separate and delay broad refactoring until the candidate is green.
