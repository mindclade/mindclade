# ADR-0009: Native kernel source incubation boundary

- Status: Accepted in blueprint specification
- Connected ratification: Pending independent review on protected infrastructure
- Specification date: 2026-08-30
- Effective date: Pending connected ratification; source-only exception authorized 2026-08-30
- Compatibility window: Source incubation only through 2026-11-30; no operator or runtime compatibility promise
- Exception expiry: 2026-11-30
- Supersedes: None
- Superseded by: None
- Owners: Architecture, ML Systems Performance
- Reviewers: Founder for source authorization; independent Architecture, Developer Platform, Security, and ML Systems review required for connected ratification

## Decision record metadata

- Affected invariants: path-manifest authority, activation-gated source, Bazel/native dependency agreement, operation-local semantic ownership, immutable generated projections, strict `torch.ops.mindclade.<name>` registration, reference fallback, and evidence-gated production authority
- Affected paths: `kernels/native/`, `docs/adr/`, `docs/architecture/repository-path-manifest.yaml`, Section 14, Section 15.7, and Appendix A15
- Affected contracts: native operator manifest v2, build-time registration projections, Stable Torch ABI schema registration, offline TileLang compilation, bundle trust decisions, and Wave 6 JIT-06 activation
- Security and safety impact: permits reviewable native source and non-production tests before Wave 6 while prohibiting runtime discovery, request-time compilation, unverified loading, production dispatch, artifact publication, or qualification claims
- Migration: retain an empty operator inventory until an operation-specific JIT-06 ADR names a measured bottleneck, reference implementation, hardware/software envelope, numerical tolerances, performance threshold, fallback, and revocation path
- Rollback: remove the package and its manifest entries by expiry, or transition only selected files through a separately ratified JIT-06 activation after Wave 5 evidence exists
- Required evidence: exact path-manifest closure, real Bazel target ownership, deterministic code-generation drift, namespace/schema policy tests, native lock reconciliation, reference parity, gradients, hardware qualification, signed artifacts, fallback, and revocation according to the applicable lifecycle stage

## Context

Wave 6 intentionally delays optimized providers until Wave 5 correctness and representative profiling identify a real bottleneck. That prevents speculative kernels from becoming product dependencies or alternate semantic authorities. The native integration boundary nevertheless has cross-cutting source contracts that benefit from early review: one dispatcher namespace, deterministic build-time projections, Stable Torch ABI schema ownership, offline TileLang intake, and a fail-closed bundle loader.

Creating those contracts under the ordinary `target` lifecycle conflicts with the normal rule that target-only paths are not populated early. Treating the package as active would be worse: source presence, successful unit tests, or a loadable binary cannot prove operation correctness, scientific parity, performance, recovery, supply-chain trust, or production readiness.

## Decision

Permit the exact `kernels/native/` component to exist before Wave 6 as a bounded, source-only incubation exception. Its component lifecycle remains `proposed`, maturity remains `target`, `production_authority` remains `false`, and both qualified and active operation counts remain zero. Physical source presence under this ADR is not activation.

The incubation surface may contain:

- deterministic manifest discovery, schema validation, and build-time projection generation;
- a schema-only Stable Torch ABI registration boundary;
- offline TileLang compiler intake that requires explicit operation-local sources;
- a fail-closed Python loader and registration policy;
- CMake and Bazel definitions that expose source, schema, generation, and policy-test ownership; and
- tests and documentation that enforce the inactive boundary.

Every PyTorch operator identity is exclusively `torch.ops.mindclade.<name>` and every dispatcher identity is exclusively `mindclade::<name>`. Alternate namespaces, compatibility aliases, duplicate default-overload registrations, runtime filesystem discovery, network-backed generation, configure-time generation, and request-time compilation are prohibited.

The committed native operator inventory remains empty during incubation. Generated projections are reviewed build outputs from explicit repository inputs and must drift-check to that empty inventory. Incubation may compile schema-only code and run local policy tests, but it cannot publish a native bundle, enable product dispatch, load a bundle in production, claim Stable ABI or GPU qualification, or treat a fake compiler test as TileLang/CUDA qualification.

This ADR is not JIT-06 ratification. Each non-empty operator addition requires completed Wave 5 correctness, representative bottleneck evidence, an operation-local PyTorch reference and semantic owner, explicit forward/backward/boundary tolerances, supported hardware and toolchain locks, an operation-specific JIT-06 ADR, immutable signed bundle evidence, plan-bound dispatch, reference fallback, and tested revocation. The root Python lock and Bazel dependency graph must also gain matching Torch, pytest, TileLang, and native-toolchain authorities before their dependent targets can be called hermetic or release-qualified.

The source exception expires on 2026-11-30. It cannot renew or expand itself. Before expiry, either remove the incubated package and canonical path entries or ratify a new independently reviewed decision grounded in the evidence then available. A valid operation-specific Wave 6 activation supersedes this exception only for the selected operation and files it actually qualifies.

## Consequences

The native registration and artifact boundary can be reviewed before optimized math exists, without making operation semantics or production readiness implicit. Repository path drift becomes explicit, deterministic projections remain generator-owned, and downstream code has one required namespace contract.

The package is intentionally unusable as a production provider while its inventory is empty. Bazel labels establish repository ownership but do not manufacture missing third-party dependency locks, GPU execution evidence, signatures, or connected qualification. Readiness reports must continue to say `TARGET`, zero active operations, zero qualified operations, and kernel K0 not achieved.

## Rejected alternatives

- Mark the package active because its policy tests pass. Source tests do not satisfy Wave 5, JIT-06, numerical, recovery, hardware, or supply-chain gates.
- Register placeholder or reference operators during incubation. A non-empty dispatcher surface would create an API and activation claim without an operation-local qualification record.
- Permit multiple Torch namespaces or Python aliases. That would fragment the dispatcher contract and make export, fake-tensor, autograd, and bundle reconciliation ambiguous.
- Compile or discover kernels at import or request time. That introduces mutable toolchain, filesystem, network, latency, and trust inputs outside the release closure.
- Treat generated C++, CMake, Bazel, Python, or JSON projections as hand-authored authorities. The manifest and explicit operation-local sources remain authoritative and drift must fail closed.
- Use this exception as JIT-06. Incubation contains no measured bottleneck and cannot select or qualify an optimized implementation.

## Qualification and rollback

Source qualification checks the ADR/index, path-manifest closure, component lifecycle, exact Bazel labels, canonical empty native-operator manifest, deterministic generation, strict namespace, schema consistency, loader policy, and generated architecture drift. Tests requiring undeclared or unlocked Torch, pytest, TileLang, CUDA, or Stable ABI dependencies remain explicit dependency gaps rather than passing evidence.

Connected and production qualification remain unavailable under this ADR. Any non-empty operator inventory, production dispatch, unsigned or unverified bundle load, runtime discovery/compilation, alternate namespace, qualification claim, missing fallback, or expiry violation fails closed. Rollback removes the package and its manifest additions, regenerates Appendix A6 and the combined blueprint, preserves review evidence, and leaves operation-local PyTorch references as the only math authority.
