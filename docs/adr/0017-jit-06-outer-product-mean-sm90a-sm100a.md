# ADR-0017: JIT-06 outer-product-mean qualification on SM90a and SM100a

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

Outer-product mean is the first differentiable Pairformer vertical slice. A
JIT-06 decision must name exact architecture lanes without converting planned
qualification into production support.

## Decision

Authorize qualification lanes for `outer_product_mean` on `sm90a` and `sm100a`.
The lanes are independent. Neither architecture is selectable until an exact
K0-K5 release root binds the semantic contract, REQUIRED FWD/BWD artifacts,
numerical envelope, hardware and software fingerprints, performance evidence,
SBOM, provenance, signature, runtime compatibility, and revocation/rollback
records. Promotion of FWD without BWD is forbidden.

## Consequences

Compilation or CPU/schema validation alone remains unqualified evidence.
Failure or absence of either architecture lane has no effect on the other and
must produce an explicit unavailable status rather than fallback selection.

## Rejected alternatives

Architecture-family inference, cross-promoting SM90a evidence to SM100a, and a
forward-only training capability were rejected.

## Qualification and rollback

Promotion requires a separately reviewed immutable release receipt for each
architecture. Revocation removes only the affected capability; rollback points
to a prior signed capability with the same exact compatibility envelope.

## Decision record metadata

- Affected invariants: JIT-06 per operation/architecture; K0-K5 promotion; REQUIRED FWD/BWD atomicity; fail-closed dispatch
- Affected paths: `kernels/pairformer/outer_product_mean/`
- Affected contracts: `mindclade::outer_product_mean`; provider FWD/BWD contracts; capability and numerical envelopes
- Security and safety impact: unsigned, incomplete, revoked, or incompatible artifacts remain ineligible
- Migration: qualify `sm90a` and `sm100a` independently; do not infer compatibility
- Rollback: revoke the exact capability and select only a prior signed compatible release root
- Required evidence: exact K0-K5 receipts for each operation/architecture pair
