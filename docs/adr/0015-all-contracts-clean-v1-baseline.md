# ADR-0015: All-Contracts Candidate v1 Estate and Ratification Gate

- Status: Accepted in blueprint specification
- Connected ratification: Pending independent review on protected infrastructure
- Specification date: 2026-08-31
- Effective date: 2026-08-31 for unratified repository candidate implementation only
- Compatibility window: The complete descriptor set remains a candidate; additive v1 compatibility begins only after explicit evidence-gated ratification
- Supersedes: The contract-scheduling and deferment portions of ADR-0004, ADR-0011, ADR-0012, blueprint wave timing, and ADR-0012's one-way OpenAPI derivation direction
- Superseded by: None
- Owners: Architecture, Contract Governance
- Reviewers: Developer Platform, Security, Domain Owners, Developer Experience

## Decision record metadata

- Affected invariants: one editable authority per contract, generated-code authority, stable resource identity, explicit compatibility, relational business-state authority, worker isolation, and no handwritten/generated dual ownership.
- Affected paths: versioned Protobuf and event sources, generated Go/Python/Rust/TypeScript projections, private internal SDK facades, durable JSON Schemas and fixtures, the curated public-safe OpenAPI projection, compatibility candidates, generators, and their real build/test labels.
- Affected contracts: all predeclared v1 domain resources, commands, events, internal services, durable documents, and supported public operations.
- Security and safety impact: contract activation grants no data-use, accelerator-spend, deployment, production, clinical, therapeutic, experimental-validity, or publication authority. Sensitive fields retain classification and redaction requirements.
- Migration: establish one coherent candidate v1 estate, regenerate every projection atomically, replace handwritten wire duplicates with generated types or explicit adapters, pass the training vertical end to end, then explicitly ratify and freeze the compatibility baseline before any supported release.
- Rollback: restore the prior complete source-and-generator closure and regenerate every language together; do not selectively retain hand-edited generated files or a partially migrated consumer.
- Required evidence: lint, deterministic clean regeneration, generated inventory, cross-language round trips, gRPC conformance, schema positive/negative fixtures, candidate descriptor/HTTP/ProtoJSON parity, internal SDK conformance, persistence/queue consumer tests, and no handwritten duplicate-authority findings.

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

Mindclade establishes the complete contract catalog now as an unratified v1
candidate, not as an enforceable compatibility baseline. The original
`activation_wave` values remain design-sequencing
provenance; for contract implementation, manifest status and this ADR govern
whether a path may exist. Blueprint wave timing is guidance, not a prohibition
on implementing a contract with a concrete generator, test, and consumer.

The exact 22-source predecessor from Git revision
`9b5fbea8a44b15c291c6fd6247a57ad350487544` (`7e9ebf1^`) is archived as
`protocols/compatibility/baselines/protobuf.predecessor.lock.json` with artifact
digest `sha256:07d7ee37e68211870861b7fc1ec5118c423447319603523bd9589c1c5dea6aaf`.
It is historical evidence, not the compatibility target for the intentional
one-time reset. Ordinary generation deterministically refreshes
`protobuf.candidate.json`; compatibility tests verify its sources, descriptor,
wire fixture, unratified state, and predecessor binding without running normal
Buf breaking enforcement against the candidate.

The authority split remains unchanged:

- Protobuf owns internal RPC requests/responses, durable commands, events, and lifecycle resources.
- JSON Schema owns durable manifests, evidence documents, release metadata, and human-authored configuration.
- `mindclade.api.v1` and the checked-in curated OpenAPI document form an unratified public-safe candidate projection for a possible future HTTP API. They establish no supported public SDK or release authority. Exact operation, binding, and model mappings enforce semantic parity without exposing internal packages. Internal Protobuf layout, database rows, queue metadata, and provider objects are not candidate HTTP authority.

Domain resources and events use `mindclade.<domain>.v1`. Internal gRPC services
use `mindclade.internal.<domain>.v1`; the candidate public-safe gRPC facade uses
`mindclade.api.v1`, and every candidate OpenAPI operation maps to that facade.
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

Every gRPC service and RPC in the existing and future estate is defined in a
versioned Protobuf source. Runtime implementations register the generated
server interfaces and clients invoke generated stubs or descriptors; a
handwritten parallel network-service definition is not permitted.

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

Buf plus pinned language-native plugins generate the internal Go, Python,
Rust, and TypeScript Protobuf/gRPC/Connect transport. Mindclade-owned facades
under `internal/sdk` own authentication metadata, deadlines, retries,
pagination, operation lifecycle helpers, artifact verification, and stable
error mapping while intentionally exporting generated wire types. Client-side
services, workers, training code, tools, and internal applications consume the
facades. Generated bindings remain directly importable only by those facade
implementations, server transport adapters/registrations, persistence
protobuf mappers, and contract tests.

The native pipeline keeps `ProtoContractValidator`, `BufNativeGenerator`,
`GeneratedBindingCompiler`, `InternalFacadeBuilder`,
`InternalSdkConformanceVerifier`, and `LayeringPolicyVerifier` as separate
testable boundaries. The curated OpenAPI document is an optional HTTP/JSON
projection, not the internal SDK input. Fern may be evaluated for optional
internal REST generation and Speakeasy as a specialized comparison, but
neither is foundational, required, authoritative, or eligible to publish from
source policy.

Compatibility does not begin merely because the candidate is committed. The
first `protobuf.lock.json` and the immutable form of `openapi.lock.json` may be
created only together by the generator's explicit `--ratify-v1-baseline`
action, bound to the exact reviewed descriptor and published-OpenAPI digests.
The protected input is assembled from independently DSSE/Ed25519-attested
cross-language, database, event, gateway, gRPC, and SDK receipts, a separately
attested approval, and an authenticated trusted context. Producer, reviewer,
context, aggregate-evidence, and connected-ADR trust remain source-owned and
fail closed until exact signer key IDs are activated. The connected ADR
decision is independently signed and its subject revision must be the candidate
revision or an ancestor.

Until that action, `protobuf.lock.json` is the sole optional missing generated
path; the OpenAPI lock remains a deterministic candidate inventory. The
generated-file manifest inventories both protected artifacts by their exact
descriptor/OpenAPI subject digests rather than their artifact digests, avoiding
a cryptographic cycle because both immutable baselines bind that manifest. The
repository-path manifest governs both paths as generated and the ratifier
revalidates the complete staged path set before committing either baseline.

After co-ratification, ordinary generation runs Buf breaking enforcement
against the immutable descriptor and the governed additive-v1 OpenAPI
comparison against the immutable published document. Field numbers and enum
values are not reused, HTTP paths/operations/parameters/response headers and
schemas cannot break in place, semantic meaning is stable, and incompatible
changes require a versioned migration and consumer evidence. The clean reset
does not authorize repeated resets or replacement of either ratified baseline.

ADR-0004 continues to govern source authority, deterministic generation, and
compatibility. ADR-0011's exact SQP-001 profile and all PDB source-use,
biological-safety, cost, hardware, and scientific-claim gates remain intact;
only its prohibition on creating the scheduled protocol/schema contracts is
superseded. ADR-0012's curated asynchronous public operation model, deadlines,
idempotency, ETags, errors, and artifact verification remain intact; only its
language/provider deferments are superseded or supplemented here.

## Consequences

- Contract work can precede broader runtime qualification without claiming that the candidate is ratified, compatible, complete, or production-ready.
- Every supported process and language can converge on generated types instead of accumulating handwritten duplicates.
- Internal gRPC evolution, durable document evolution, and any future HTTP projection evolution remain distinct but traceable concerns.
- Mindclade owns internal SDK behavior over Buf-generated native clients; optional Fern or Speakeasy REST output cannot become authority or block native delivery when unused.
- The repository path manifest, candidate descriptor, generators, consumers, and eventual compatibility baseline must advance through their explicit lifecycle; an unconsumed or untested active contract is a governance failure.

## Rejected alternatives

- Retain wave timing as a hard contract-creation gate. This would force active code to define temporary local types and make the eventual migration riskier.
- Make OpenAPI an authority for internal domain state, or make internal Protobuf layout the external HTTP contract. Transport-specific authority with enforced mappings avoids both forms of coupling and drift.
- Use Protobuf blobs as the primary database model. This would weaken relational constraints, tenant isolation, queries, migrations, and operational repair.
- Make a hosted or third-party OpenAPI generator foundational. Internal clients require native Protobuf/gRPC/Connect semantics and a hermetic repository-owned facade.
- Treat optional-provider parity as permission to publish an SDK. Provider comparison is evidence only; a future public API and release policy require separate ratification.

## Qualification and rollback

Candidate source qualification proves the exact manifest inventory, real Bazel
labels, locked generator closure, clean regeneration, lint, cross-language and
gRPC round trips, schema fixtures, candidate descriptor/HTTP/ProtoJSON parity,
internal SDK conformance, and migrated consumers. It does not ratify v1.
Ratification additionally requires the
descriptor-bound training-vertical evidence enumerated above and the explicit
generator action; no ordinary generation or compatibility test can perform it.
Connected service, hosted SDK publication, cloud, cluster, GPU, data-use, and
production qualification remain separate protected actions.

If the candidate cannot be made coherent, stop admission of new contract
consumers, retain the immutable 22-source predecessor, restore the previous
complete source/generator closure if needed, regenerate all languages, and
retain incompatibility evidence for repair. Never roll back only one generated
language, rewrite durable subjects, replace a ratified baseline, or infer
production authority from passing source tests.
