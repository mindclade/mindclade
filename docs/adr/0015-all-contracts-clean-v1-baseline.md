# ADR-0015: All-Contracts Clean-v1 Baseline

- Status: Accepted in blueprint specification
- Connected ratification: Pending independent review on protected infrastructure
- Specification date: 2026-08-31
- Effective date: Pending connected ratification; source implementation authorized 2026-08-31
- Compatibility window: One clean-v1 reset before the first supported external release; additive v1 compatibility applies after the baseline is committed
- Supersedes: ADR-0004
- Superseded by: None
- Owners: Architecture, Contract Governance
- Reviewers: Developer Platform, Security, Domain Owners, Developer Experience

## Decision record metadata

- Affected invariants: one editable authority per contract, generated-code authority, stable resource identity, explicit compatibility, relational business-state authority, worker isolation, and no handwritten/generated dual ownership.
- Affected paths: versioned Protobuf and event sources, generated Go/Python/Rust/TypeScript projections, durable JSON Schemas and fixtures, the curated public OpenAPI facade, public SDK configuration, compatibility baselines, generators, and their real build/test labels.
- Affected contracts: all predeclared v1 domain resources, commands, events, internal services, durable documents, and supported public operations.
- Security and safety impact: contract activation grants no data-use, accelerator-spend, deployment, production, clinical, therapeutic, experimental-validity, or publication authority. Sensitive fields retain classification and redaction requirements.
- Migration: establish one coherent v1 source baseline, regenerate every projection atomically, replace handwritten wire duplicates with generated types or explicit adapters, then freeze compatibility baselines before any supported release.
- Rollback: restore the prior complete source-and-generator closure and regenerate every language together; do not selectively retain hand-edited generated files or a partially migrated consumer.
- Required evidence: lint, deterministic clean regeneration, generated inventory, cross-language round trips, gRPC conformance, schema positive/negative fixtures, public OpenAPI/SDK parity, persistence/queue consumer tests, and no handwritten duplicate-authority findings.

## Context

The blueprint's waves were written as an implementation-risk schedule. They are
still useful for dependency order and qualification planning, but they are not a
reason to leave the contract system inert while product code invents local wire
types. The repository has no declared supported external v1 release or external
consumer baseline to preserve. This is the least costly point to establish one
coherent contract estate and make generated code authoritative.

Activating names without consumers would repeat the failure ADR-0004 sought to
prevent. This decision therefore couples source activation to generators, real
build/test labels, downstream adapters, and compatibility evidence in the same
implementation program. A path is not evidence merely because this ADR permits
it: the repository-path manifest continues to record whether that exact path is
target, active, or generated.

## Decision

Mindclade establishes the complete contract catalog now as a one-time clean v1
baseline. The original `activation_wave` values remain design-sequencing
provenance; for contract implementation, manifest status and this ADR govern
whether a path may exist. Blueprint wave timing is guidance, not a prohibition
on implementing a contract with a concrete generator, test, and consumer.

The authority split remains unchanged:

- Protobuf owns internal RPC requests/responses, durable commands, events, and lifecycle resources.
- JSON Schema owns durable manifests, evidence documents, release metadata, and human-authored configuration.
- A curated `mindclade.api.v1` service facade owns public gRPC behavior. The checked-in curated OpenAPI document owns supported external HTTP/JSON and SDK behavior. Exact operation and model mappings enforce semantic parity without exposing internal packages. Internal Protobuf layout, database rows, queue metadata, and provider objects are not public HTTP authority.

Domain resources and events use `mindclade.<domain>.v1`. Internal gRPC services
use `mindclade.internal.<domain>.v1`; the public gRPC facade uses
`mindclade.api.v1`, and every external OpenAPI operation maps to that facade.
Large scientific data, tensors, models, checkpoints, and
other bulk values cross contracts only by immutable `ArtifactRef`. Event
envelopes carry stable identity, type/version, payload bytes, and digest;
serialized bytes are durable only where an outbox, audit record, or dead-letter
boundary requires immutable wire evidence.

The pinned generator emits authoritative internal bindings and gRPC clients and
servers for all four repository languages:

- Go: Protobuf and gRPC projections;
- Python: Protobuf, gRPC, and type-stub projections;
- Rust: Prost and Tonic projections; and
- TypeScript: Protobuf-ES and Connect projections.

Generated outputs are committed, deterministic, source-attributed, and never
hand-edited. Product libraries, including `libs/python`, are consumers of these
bindings. They may provide validation, ergonomic domain behavior, or transport
adapters, but must not redefine generated resource, command, event, or service
types. Private database rows and delivery metadata may remain handwritten when
they are explicitly adapters rather than competing wire contracts.

PostgreSQL-compatible normalized relational tables remain authoritative for
durable business state. Protobuf bytes may support immutable outbox, inbox,
audit, and dead-letter evidence, but are not a substitute for queryable tenant,
project, operation, job, run, attempt, artifact, policy, and lifecycle columns.
Workers remain unable to mutate control-plane tables and communicate through
typed commands, events, and gRPC boundaries.

The public SDK program uses Mindclade SDK Forge as the long-term primary
compiler for Go, Python, and TypeScript. Forge owns SDK policy, emitters, thin
language-native runtimes, conformance, packaging, and release orchestration;
the MIT-licensed WorkOS OAGen parser and typed IR are an implementation
foundation, not a contract or release authority. Provider-native configuration
is derived from Mindclade policy. The curated OpenAPI document remains the
portable wire input, and generated source or hosted provider state cannot
become authority.

The pipeline uses independently testable `OpenApiValidator`,
`SdkPolicyCompiler`, `SdkEmitter`, `SdkSurfaceExtractor`,
`SdkBehaviorVerifier`, `SdkPackager`, `SdkPublisher`, and
`SdkReleaseOrchestrator` boundaries. Only the release orchestrator emits the
final receipt. Fern is the preferred qualified shadow but remains
non-authoritative because its documented self-hosted workflow is an Enterprise
Docker/token/outbound-verification path. Speakeasy is an additional commercial
benchmark and fallback. Stainless is retained only for comparison when an
existing legacy project is available; it is not a long-term dependency or a
publication path. All implementations prove compatibility against the same
OpenAPI fixtures and Mindclade release policy.

Compatibility begins from the committed clean-v1 baseline. After that point,
field numbers and enum values are not reused, semantic meaning is stable,
changes are classified, and breaking changes require a versioned migration and
consumer evidence. The clean reset does not authorize repeated resets.

ADR-0004 continues to govern source authority, deterministic generation, and
compatibility. ADR-0011's exact SQP-001 profile and all PDB source-use,
biological-safety, cost, hardware, and scientific-claim gates remain intact;
only its prohibition on creating the scheduled protocol/schema contracts is
superseded. ADR-0012's curated asynchronous public operation model, deadlines,
idempotency, ETags, errors, and artifact verification remain intact; only its
language/provider deferments are superseded or supplemented here.

## Consequences

- Contract work can precede broader runtime qualification without claiming that the runtime is complete or production-ready.
- Every supported process and language can converge on generated types instead of accumulating handwritten duplicates.
- Internal gRPC evolution, durable document evolution, and public HTTP/SDK evolution remain distinct but traceable authorities.
- Mindclade owns the SDK compiler and release policy; OAGen reduces parser/typed-IR reinvention while Fern, Speakeasy, and legacy Stainless comparisons provide independent substitution evidence without becoming authority.
- The repository path manifest, generators, compatibility baselines, and consumers must advance together; an unconsumed or untested active contract is a governance failure.

## Rejected alternatives

- Retain wave timing as a hard contract-creation gate. This would force active code to define temporary local types and make the eventual migration riskier.
- Make OpenAPI an authority for internal domain state, or make internal Protobuf layout the external HTTP contract. Transport-specific authority with enforced mappings avoids both forms of coupling and drift.
- Use Protobuf blobs as the primary database model. This would weaken relational constraints, tenant isolation, queries, migrations, and operational repair.
- Make Stainless or any hosted generator the primary path. Stainless has retired new hosted SDK projects, and provider state would be an unavailable or unreviewable build authority.
- Reimplement OpenAPI parsing before proving that OAGen's typed IR cannot express a required Mindclade semantic. Forge owns the policy and output while reusing a pinned, reviewed parsing foundation.
- Treat provider parity as permission to publish independently versioned SDK surfaces. One supported public contract and Mindclade release policy remains authoritative.

## Qualification and rollback

Source qualification proves the exact manifest inventory, real Bazel labels,
locked generator closure, clean regeneration, lint, cross-language and gRPC
round trips, schema fixtures, public facade/SDK parity, and migrated consumers.
Connected service, hosted SDK publication, cloud, cluster, GPU, data-use, and
production qualification remain separate protected actions.

If the baseline cannot be made coherent, stop admission of new contract
consumers, restore the previous complete source/generator closure, regenerate
all languages, and retain incompatibility evidence for repair. Never roll back
only one generated language, rewrite durable subjects, or infer production
authority from passing source tests.
