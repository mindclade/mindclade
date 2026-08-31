# ADR-0013: DeepEP package and qualification boundary

- Status: Accepted in blueprint specification
- Connected ratification: Pending independent review on protected infrastructure
- Specification date: 2026-08-31
- Effective date: Pending connected ratification; source-only development authorized 2026-08-31
- Compatibility window: No runtime or production compatibility promise
- Supersedes: None
- Superseded by: None
- Owners: Security, Developer Platform, ML Systems Performance
- Reviewers: Independent Security, Developer Platform, and ML Systems review required for connected ratification

## Decision record metadata

- Affected invariants: immutable third-party source identity, declared toolchains, hermetic builds, fail-closed runtime loading, evidence-gated promotion, and repository-path authority
- Affected paths: the exact DeepEP package and patch paths declared in `tools/repo/path_policy.py`, this ADR, and generated architecture projections
- Affected contracts: immutable source and patch inventory, repository rule, artifact contract, GPU evidence schema, runtime manifest schema, and protected promotion receipt
- Security and safety impact: permits reviewable package and patch development while prohibiting unverified external source, request-time compilation, unsigned artifact loading, or production qualification claims
- Migration: replace ad hoc DeepEP intake with the repository-owned package contract and immutable external-repository boundary
- Rollback: remove the package, patches, external repository declaration, manifest additions, and generated projections
- Required evidence: immutable source and patch digests, license and provenance review, hermetic build receipts, runtime-manifest validation, accelerator qualification, signed promotion, revocation, and rollback

## Context

DeepEP is an external native dependency with accelerator-, compiler-, and
communication-library-sensitive behavior. Treating a source checkout or a
locally built wheel as qualified would bypass repository identity, toolchain,
artifact, and production-promotion controls.

The repository therefore needs a narrow development-intake boundary before any
runtime integration. Package policy must be reviewable on non-accelerator hosts,
while artifact construction and GPU qualification remain separate connected
activities on protected infrastructure.

## Decision

Permit only the exact package and patch files declared by
`THIRD_PARTY_DEEP_EP_PACKAGE_PATHS` and `DEEP_EP_PATCH_PATHS`. These files are
active repository policy inputs; they do not activate a DeepEP runtime,
accelerator capability, or production artifact.

The repository-local `policy_inputs` target owns package metadata, schemas,
repository rules, and tests. The `artifact_bundle` target is a Linux x86_64
alias to the immutable Nix-backed external repository and is materialized only
when an artifact is explicitly requested. Repository governance must not query
that external artifact merely to prove ownership of local policy source.

The package policy must:

- resolve external source by immutable digest;
- apply only declared, digest-covered patches;
- discover compiler and CUDA tools through declared paths;
- emit immutable artifact and runtime manifests;
- prohibit request-time network access, source mutation, compilation, or tuning;
- fail closed when an artifact, signer, capability, or environment identity is missing;
- keep the closure-bound wheel and accelerator-specific runtime outputs distinct; and
- require separately signed promotion, revocation, and rollback receipts.

Local schema and source-policy tests establish only source conformance. They do
not establish GPU correctness, numerical parity, collective behavior,
performance, H100 compatibility, cost authorization, or production readiness.
Those claims require the exact protected revision, toolchain and image closure,
hardware envelope, connected evidence, and independent approvals.

## Consequences

DeepEP packaging can evolve under ordinary source review without importing an
external build graph into every governance query. Linux accelerator builds stay
explicit and protected, while local checks can verify schemas, repository rules,
patch inventory, and fail-closed artifact contracts.

No DeepEP provider may be selected by a runtime until an immutable artifact is
qualified and promoted for the exact hardware/software envelope. Missing or
inconclusive evidence is a denial, not a warning.

## Rejected alternatives

- Track an unpinned upstream checkout. This breaks reproducibility and provenance.
- Build or tune on first use. This introduces request-time mutation and network risk.
- Use the external artifact alias as local source ownership. That needlessly materializes a platform-specific dependency graph and fails on incompatible hosts.
- Treat package tests as accelerator qualification. They cannot prove GPU behavior or production readiness.

## Qualification and rollback

Source qualification covers the closed path set, Bazel ownership, immutable
source and patch contracts, schemas, deterministic manifests, and negative
tests. Connected qualification adds the exact accelerator, driver, CUDA,
communication libraries, image or Nix closure, build receipts, numerical and
collective evidence, performance thresholds, signer identity, cost authority,
and protected promotion receipt.

Rollback removes runtime eligibility first, revokes the artifact identity, and
then removes package or patch authority through a separately reviewed change.
