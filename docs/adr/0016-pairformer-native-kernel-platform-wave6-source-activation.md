# ADR-0016: Pairformer native kernel platform Wave 6 source activation

- Status: Accepted in blueprint specification
- Connected ratification: Pending independent review on protected infrastructure
- Specification date: 2026-09-01
- Effective date: Pending connected ratification; source-only development authorized 2026-09-01
- Compatibility window: No production runtime compatibility is granted by this decision
- Supersedes: None
- Superseded by: None
- Owners: Architecture, Contract Governance
- Reviewers: Security, ML Systems Performance, Release Engineering

## Context

The repository contains the generic native integration substrate and five
operation-local Pairformer packages: outer-product mean, pair weighted average,
transition, triangle attention, and triangle multiplication. Their source and
tests must become governed inputs before qualification can proceed, while the
absence of K0-K5 evidence must continue to prevent production selection.

## Decision

Activate the five operation-local packages as hand-authored source, build, and
qualification inputs. Each package is closed by its `policy_inputs` Bazel
filegroup and operation test target. Keep generic `kernels/native/` source in
target status and keep its generated projections in generated status until the
native component has an independently declared policy closure.

This activation does not create a promoted capability, runtime selector,
fallback provider, signed artifact, or production support claim. The missing
registry, dispatch, qualification, benchmark, and artifact subsystems remain
deferred target work. Production execution remains fail closed.

## Consequences

Operation-local source can participate in repository governance and future
K0-K5 qualification. Every architecture and operation promotion still requires
its own immutable JIT-06 decision and exact evidence root. CPU, schema-only, or
successful compilation evidence cannot promote a GPU capability.

## Rejected alternatives

Activating all native and future kernel-platform paths was rejected because
their complete policy closures do not yet exist. Treating generated files or
`exports_files` declarations as a build/test closure was rejected because it
does not prove consumers or qualification. Promoting the five operations as a
group was rejected because promotion is per operation and architecture.

## Qualification and rollback

The operation sources may be returned to target status if their declared Bazel
closures disappear or governance validation fails. Runtime rollback is not
applicable because this ADR authorizes no promoted runtime capability.

## Decision record metadata

- Affected invariants: closed-world repository paths; derived native registration; no unqualified native execution; FWD/BWD co-promotion
- Affected paths: `kernels/pairformer/outer_product_mean/`; `kernels/pairformer/pair_weighted_average/`; `kernels/pairformer/transition/`; `kernels/pairformer/triangle_attention/`; `kernels/pairformer/triangle_multiplication/`; `kernels/native/`
- Affected contracts: repository-path manifest; Pairformer operation declarations; native generated projections
- Security and safety impact: production selection remains denied without signed exact K0-K5 evidence and runtime compatibility
- Migration: activate only operation-package files covered by exact policy and test targets; preserve native source as target and generated projections as generated
- Rollback: revert the affected manifest entries to target and supersede this ADR; no runtime artifact rollback is implied
- Required evidence: repository manifest validation; CODEOWNERS coverage; exact Bazel source/test closure; per-operation JIT-06 decisions before promotion
