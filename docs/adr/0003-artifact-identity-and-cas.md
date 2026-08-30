# ADR-0003: Artifact Identity and Content-Addressed Storage

- Status: Accepted in blueprint specification
- Connected ratification: Pending independent review on protected infrastructure
- Specification date: 2026-08-30
- Effective date: Pending connected ratification
- Compatibility window: Digest vocabulary fixed before the Wave 1 artifact kernel
- Supersedes: None
- Superseded by: None
- Owners: Architecture, Data Platform
- Reviewers: Security, ML Systems, Platform Operations

## Decision record metadata

- Affected invariants: immutable content identity, build-once promotion, locator/identity
  separation, and transactional publication after byte verification.
- Affected paths: future artifact contracts and catalog packages; Wave 0 architecture and ADR
  sources only.
- Affected contracts: typed artifact references, SHA-256 digest vocabulary, catalog receipts,
  release manifests, and retention/revocation references.
- Security and safety impact: makes substitution, corruption, mutable-tag promotion, and silent
  overwrite detectable; sensitive payload policy remains separate from identity.
- Migration: new stores must adopt prepare/write/verify/commit and backfill verified digests before
  catalog publication; path-only records cannot graduate.
- Rollback: stop publication and revert adapters while retaining immutable bytes and receipts;
  never rewrite or reuse an existing digest identity.
- Required evidence: digest/size recomputation, concurrent-finalize and corruption tests, orphan
  reconciliation, catalog transaction tests, and signed release provenance.

## Context

Datasets, features, checkpoints, model bundles, evaluation reports, execution
evidence, and release manifests outlive individual processes and paths. Mutable
object names or tags cannot support deduplication, integrity, lineage,
revocation, or build-once promotion.

## Decision

Immutable artifact identity is content-derived. The common digest vocabulary is
`sha256:<64 lowercase hexadecimal characters>`. A typed artifact reference
contains at least digest, media type, size, logical artifact kind, and integrity
metadata. Domain manifests add schema, lineage, producer, policy, and
qualification references without changing content identity.

Writers use a prepare/write/verify/commit protocol:

1. write bytes to an attempt-scoped staging location;
2. compute and verify size and digest while streaming;
3. finalize to an immutable content-addressed object without overwriting a
   different subject;
4. transactionally publish catalog metadata and an outbox event; and
5. retain enough receipt evidence to reconcile an interrupted finalize.

The artifact catalog stores metadata and references, never large payloads. A
filesystem or object-store path is a locator, not durable identity. Caches and
indexes are reconstructible projections and cannot become systems of record.

Release manifests bind immutable subjects, source revision, build identity,
toolchain and dependency closure, qualification evidence, policy decisions,
and revocation state. Environments promote the same verified digest. They never
rebuild or accept a mutable image tag as release identity.

Evidence statements use canonical serialization and bind their subject digest.
Trusted CI wraps qualifying statements in the approved signed envelope. A hash
or unsigned receipt alone is integrity information, not a signature.

## Consequences

- Duplicate content converges on one identity while logical names remain
  catalog metadata.
- Promotion, rollback, and revocation operate on exact digests.
- Garbage collection requires catalog reachability, retention policy, legal or
  safety holds, and recovery evidence; age alone is insufficient.
- Partial writes are never observable as committed artifacts.
- Encryption, tenant/policy partitioning, and authorization remain mandatory
  even when content hashes match.

## Rejected alternatives

- Mutable paths, versions, or tags were rejected because they do not bind
  bytes.
- Storing payloads in database rows or queue messages was rejected because it
  breaks transaction, size, retention, and replay boundaries.
- Rebuilding independently in each environment was rejected because it destroys
  provenance equivalence and expands trusted builders.
- Provider object metadata as the catalog was rejected because provider state
  is not a portable domain authority.

## Qualification and rollback

Qualification covers corruption, duplicate finalize, concurrent writers,
interrupted publication, cross-tenant access, catalog reconstruction, retention,
revocation, and restore. A release can roll back only to a previously qualified
digest and evidence set. A failed catalog migration preserves old references
and readers until round-trip and reachability evidence passes.
