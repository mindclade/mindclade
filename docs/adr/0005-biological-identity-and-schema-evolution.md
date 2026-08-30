# ADR-0005: Biological Identity and Schema Evolution

- Status: Accepted in blueprint specification
- Connected ratification: Pending independent review on protected infrastructure
- Specification date: 2026-08-30
- Effective date: Pending connected ratification and biological-safety review
- Compatibility window: Canonicalization versions remain readable for their retained lineage
- Supersedes: None
- Superseded by: None
- Owners: Computational Biology, Architecture
- Reviewers: Data Platform, Biological Safety, Security

## Decision record metadata

- Affected invariants: source fidelity, separation of source/entity/sample/artifact identity,
  versioned canonicalization, and immutable scientific lineage.
- Affected paths: future biological protocols, parser/normalization packages, fixtures, dataset
  manifests, and lineage contracts.
- Affected contracts: source records, canonical biological entities, samples, normalization
  receipts, schema versions, and license/use-policy references.
- Security and safety impact: prohibits silent biological reinterpretation, preserves restricted
  source/use policy, and requires quarantine/escalation for malformed or unsafe records.
- Migration: publish a new canonicalization/schema version, dual-read retained history, recompute
  derived artifacts explicitly, and preserve links to the prior source-faithful record.
- Rollback: revoke/quarantine the new version and restore selection of the last qualified version;
  historical lineage and bytes remain immutable.
- Required evidence: golden/fuzz parser tests, round-trip source fidelity, canonicalization parity,
  lineage closure, license/policy propagation, and biological-safety approval.

## Context

Biological records arrive from heterogeneous sources with source-specific
identifiers, revisions, ambiguity, coordinate systems, and parsing defects.
Conflating source identity, normalized semantic identity, samples, derived
features, and filesystem paths would corrupt lineage and make scientific
corrections indistinguishable from ordinary data movement.

## Decision

Mindclade distinguishes:

- source record identity: provider, dataset/release, record identifier, source
  revision, and original integrity digest;
- canonical biological entity identity: type plus versioned canonicalization
  rules and semantic digest;
- sample identity: an immutable observation or selected unit with provenance,
  policy scope, and lineage; and
- artifact identity: the digest of a serialized representation, which is not
  automatically the biological entity identity.

Source-faithful parsing preserves original values, ordering where meaningful,
unknown fields, warnings, and malformed-input evidence. Normalization is a
separate explicit transform with a version, configuration digest, input
references, output schema, and receipt. Parsers must not silently repair or
reinterpret biological meaning.

Canonicalization rules specify molecule/entity type, alphabet, residue and atom
naming, coordinate/reference convention, ambiguity handling, stereochemistry
where applicable, and policy-governed redaction. Canonical IDs are not derived
from repository paths, mutable catalog names, row numbers, or provider-local
surrogates alone.

Schema evolution preserves stable field identity and lineage. Scientific
meaning changes require a versioned schema or transform, migration evidence,
old/new reader tests, affected dataset/model assessment, and rollback. A new
schema does not retroactively rewrite an immutable release. Corrected material
is a new artifact and release linked to the superseded subject.

Protected biological data carries classification, permitted purpose, tenant or
project scope, residency/retention policy, and accountable approval. Biological
safety policy can prohibit processing or release regardless of technical
validity.

## Consequences

- Source replay and scientific audit remain possible after normalization rules
  change.
- Deduplication can distinguish byte equality, source-record equality, and
  semantic biological equality.
- Dataset splits, feature keys, model inputs, and evaluation lineage can bind
  stable identities rather than paths.
- Scientific corrections produce explicit new lineage instead of mutating
  history.

## Rejected alternatives

- Parser-specific canonical IDs were rejected because changing parser code
  would silently change durable identity.
- Mutable biological records were rejected because prior evidence and releases
  would become unreproducible.
- Filenames and storage paths were rejected as identity because location is an
  implementation detail.
- Silent normalization during parsing was rejected because it loses source
  fidelity and hides scientific decisions.

## Qualification and rollback

Before domain activation, owners provide golden and malformed fixtures,
property tests, canonicalization-version tests, schema compatibility, lineage
round trips, and protected-data policy evidence. A migration rolls back by
selecting the prior immutable schema/transform/release; it never overwrites
already published source or derived artifacts.
