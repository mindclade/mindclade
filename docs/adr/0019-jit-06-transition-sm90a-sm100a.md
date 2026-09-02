# ADR-0019: JIT-06 transition qualification on SM90a and SM100a

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

The Pairformer transition operation needs exact accelerator qualification and
must not inherit support from the presence of operation-local source.

## Decision

Authorize independent `transition` qualification on `sm90a` and `sm100a`.
Selection remains denied until an immutable K0-K5 release root covers the
semantic contract, all differentiation obligations, exact artifacts and
environment, reviewed numerics, performance, integrity, compatibility,
revocation, and rollback. A REQUIRED capability promotes FWD and BWD atomically.

## Consequences

Schema, build, and compiler success remain pre-promotion evidence. An
unqualified architecture returns an explicit unavailable result.

## Rejected alternatives

Cross-architecture evidence reuse, implicit compatible-SM selection, and
partial training-artifact promotion were rejected.

## Qualification and rollback

Promotion and rollback are per exact architecture capability and require signed
immutable records.

## Decision record metadata

- Affected invariants: JIT-06 per operation/architecture; K0-K5 promotion; differentiation completeness; fail-closed dispatch
- Affected paths: `kernels/pairformer/transition/`
- Affected contracts: `mindclade::transition`; provider contracts; capability and numerical envelopes
- Security and safety impact: incomplete or integrity-invalid capabilities remain ineligible
- Migration: qualify `sm90a` and `sm100a` as separate lanes
- Rollback: revoke the exact capability and restore only a prior signed compatible release root
- Required evidence: exact K0-K5 receipts for each operation/architecture pair
