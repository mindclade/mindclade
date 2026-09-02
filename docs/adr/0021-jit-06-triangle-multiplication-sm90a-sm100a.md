# ADR-0021: JIT-06 triangle-multiplication qualification on SM90a and SM100a

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

Triangle multiplication has incoming and outgoing modes whose schedules and
qualification evidence are architecture-specific.

## Decision

Authorize independent `triangle_multiplication` qualification lanes on
`sm90a` and `sm100a`. Incoming and outgoing semantics, masking, every named
gradient, numerical policy, odd and partial tiles, streams, capture, resource
use, and performance must be bound by the exact K0-K5 root. REQUIRED FWD/BWD
artifacts promote atomically. No capability is currently selectable.

## Consequences

Build availability is not production support. Missing evidence for a mode or
architecture yields explicit unavailability without silent fallback.

## Rejected alternatives

One schedule/evidence record for both architectures, inference between incoming
and outgoing modes, and forward-only promotion were rejected.

## Qualification and rollback

Promotion, revocation, and rollback use immutable signed exact-capability
records and never mutate a promoted record in place.

## Decision record metadata

- Affected invariants: JIT-06 per operation/architecture; K0-K5 promotion; FWD/BWD atomicity; exact mode coverage
- Affected paths: `kernels/pairformer/triangle_multiplication/`
- Affected contracts: `mindclade::triangle_multiplication`; incoming/outgoing modes; provider and numerical contracts
- Security and safety impact: integrity, compatibility, and revocation checks remain mandatory
- Migration: qualify `sm90a` and `sm100a` independently across both modes
- Rollback: revoke the exact capability and restore only a prior signed compatible release root
- Required evidence: exact K0-K5 receipts for each operation/architecture pair and advertised mode
