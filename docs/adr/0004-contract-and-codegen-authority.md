# ADR-0004: Contract and Code-Generation Authority

> Clarified by ADR-0015: the curated OpenAPI document owns external HTTP/JSON
> and SDK behavior, while `mindclade.api.v1` owns the public gRPC facade; exact
> parity mappings replace one-way OpenAPI derivation.

- Status: Accepted in blueprint specification
- Connected ratification: Pending independent review on protected infrastructure
- Specification date: 2026-08-30
- Effective date: Pending connected ratification
- Compatibility window: Authority fixed before Wave 1 durable contracts and generated clients
- Supersedes: None
- Superseded by: ADR-0015
- Owners: Architecture, Contract Governance
- Reviewers: Developer Platform, Security, Domain Owners

## Decision record metadata

- Affected invariants: one authoritative contract per semantic surface, deterministic committed
  projections, compatibility classification, and no handwritten/generated dual authority.
- Affected paths: future `protocols/` sources and generated projections plus root `buf.yaml` and
  `buf.gen.yaml`.
- Affected contracts: Protobuf messages/services, JSON Schema manifests/evidence, curated OpenAPI
  projections, generator closures, and compatibility baselines.
- Security and safety impact: prevents schema ambiguity and malicious or stale generated clients;
  sensitive fields require classification and redaction semantics in their source contract.
- Migration: introduce versioned sources and fixtures first, generate every language projection in
  one atomic change, then migrate consumers within the declared compatibility window.
- Rollback: restore the previous source contract and regenerate its complete projection set; do not
  hand-edit or selectively roll back generated languages.
- Required evidence: Buf/schema compatibility, cross-language round trips, deterministic clean
  regeneration, negative fixtures, and generated-file inventory.

## Context

Mindclade crosses Go, Python, Rust, TypeScript, processes, durable queues, and
human-authored manifests. Allowing database structs, framework models,
handwritten clients, and generated projections to compete as contracts would
make compatibility and migration unprovable.

## Decision

Protobuf is authoritative for internal RPC messages, durable commands, events,
and lifecycle contracts. JSON Schema is authoritative for durable manifests,
evidence documents, release metadata, and human-authored configuration. A
curated OpenAPI projection may define supported external HTTP behavior after
its owning wave, but it cannot become an independently edited internal
authority.

Contract sources live under their owning `protocols/` package with versioned
namespaces, compatibility baselines, positive and negative fixtures, and
explicit owners. Database models, queue wrappers, ORM entities, SDK types, and
provider schemas are projections or adapters.

Protobuf generation is deterministic and committed under
`protocols/generated/{go,python,rust,typescript}`. Generated files identify
their source and generator closure and are never hand-edited. CI regenerates
from a locked toolchain and requires a clean diff. Build-derived validators,
documentation bundles, and external transports are reproduced on demand unless
their owning contract explicitly requires committed output.

Every contract change is classified as compatible, conditionally compatible,
or breaking. It runs lint, generation drift, baseline comparison, cross-language
round trips, current/previous reader tests, and domain semantic tests. Field
numbers, enum values, resource identities, and durable event meaning are never
silently reused. Breaking change requires a migration, bounded dual-read/write
window where necessary, rollback, and explicit consumer evidence.

Wave 0 freezes only the authority and generation law. Domain protocols are not
stabilized until their owning wave demonstrates a real end-to-end consumer.

ADR-0015 supersedes only that scheduling rule: the complete domain catalog now
forms one clean-v1 baseline with generators, tests, and consumers. All source,
generation, and post-baseline compatibility rules in this record remain in
force.

## Consequences

- Each wire or document concept has one editable source.
- Generated diffs are reviewed through source, toolchain, compatibility, and
  round-trip evidence.
- Public SDK compatibility can evolve independently from private storage
  layouts while remaining traceable to supported API contracts.
- Contract packages cannot contain business implementation.

## Rejected alternatives

- Database structs as APIs were rejected because storage evolution and wire
  compatibility have different lifecycles.
- Independently authoritative OpenAPI and Protobuf definitions were rejected
  because they inevitably drift.
- Handwritten generated-language clients were rejected because they conceal
  schema differences and generator provenance.
- Stabilizing every target schema in Wave 0 was rejected because unused
  contracts fossilize guesses.

## Qualification and rollback

The initial gate proves deterministic generation infrastructure, schema and
golden negative tests, source/output inventory, and an empty Wave 0 domain
contract set. Later migrations retain previous-version fixtures and readers
until supported consumers and durable records have passed. Rollback restores
the previous contract source, projections, and compatibility baseline as one
atomic change.
