# ADR-0018: JIT-06 pair-weighted-average qualification on SM90a and SM100a

- Status: Accepted in blueprint specification
- Connected ratification: Pending independent review on protected infrastructure
- Specification date: 2026-09-01
- Effective date: Pending connected ratification; qualification planning authorized 2026-09-01
- Compatibility window: Exact qualified envelopes only; no capability is currently promoted
- Supersedes: None
- Superseded by: None
- Owners: Architecture, Contract Governance
- Reviewers: Security, Numerical Qualification, Release Engineering

## Context

Pair weighted average requires an explicit operation/architecture decision
before native artifacts may be treated as production candidates.

## Decision

Authorize independent qualification lanes for `pair_weighted_average` on
`sm90a` and `sm100a`. No lane is selectable until an exact K0-K5 release root
binds semantic and integration evidence, all required FWD/BWD artifacts, the
reviewed numerical envelope, exact hardware/software evidence, performance,
SBOM, provenance, signature, runtime compatibility, and revocation/rollback.

## Consequences

Source activation and successful compilation do not imply support. Missing or
failed evidence produces an explicit unavailable result and never silent
fallback.

## Rejected alternatives

Promoting by architecture family, reusing SM90a evidence for SM100a, and
forward-only promotion for differentiable training were rejected.

## Qualification and rollback

Each architecture requires its own immutable reviewed release receipt.
Revocation and rollback operate on the exact signed capability identity.

## Decision record metadata

- Affected invariants: JIT-06 per operation/architecture; K0-K5 promotion; FWD/BWD co-promotion; fail-closed dispatch
- Affected paths: `kernels/pairformer/pair_weighted_average/`
- Affected contracts: `mindclade::pair_weighted_average`; provider contracts; capability and numerical envelopes
- Security and safety impact: no unsigned, incomplete, revoked, or mismatched artifact may load
- Migration: qualify `sm90a` and `sm100a` independently
- Rollback: revoke the affected capability and restore only a prior signed compatible release root
- Required evidence: exact K0-K5 receipts for each operation/architecture pair
