# ADR-0020: JIT-06 triangle-attention qualification on SM90a and SM100a

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

Triangle attention has multiple semantic modes and numerical edge cases. Its
accelerator support must be explicit and evidence-bound.

## Decision

Authorize `triangle_attention` qualification on `sm90a` and `sm100a` as
independent lanes. Starting-node and ending-node semantics, all declared bias
and mask behavior, named gradients, streams, capture, determinism, and boundary
cases must be covered by the exact K0-K5 root. REQUIRED FWD/BWD artifacts are an
atomic capability. No current artifact is promoted or selectable.

## Consequences

The operation may be built and measured, but production dispatch remains fail
closed until exact signed evidence exists for the requested architecture and
mode.

## Rejected alternatives

Treating all attention modes as qualified from one smoke test, transferring
SM90a evidence to SM100a, and silent reference fallback were rejected.

## Qualification and rollback

Promotion, revocation, and rollback operate on immutable exact capability
records. A revoked lane cannot fall through to an unsigned or incompatible one.

## Decision record metadata

- Affected invariants: JIT-06 per operation/architecture; K0-K5 promotion; FWD/BWD atomicity; exact semantic-mode coverage
- Affected paths: `kernels/pairformer/triangle_attention/`
- Affected contracts: `mindclade::triangle_attention`; starting/ending-node modes; provider and numerical contracts
- Security and safety impact: exact signature, digest, compatibility, and revocation checks are mandatory before load
- Migration: qualify `sm90a` and `sm100a` independently across every advertised mode
- Rollback: revoke the exact capability and restore only a prior signed compatible release root
- Required evidence: exact K0-K5 receipts for each operation/architecture pair and advertised mode
