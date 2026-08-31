# ADR-0014: TileLang kernel platform source development

- Status: Accepted in blueprint specification
- Connected ratification: Pending independent review on protected infrastructure
- Specification date: 2026-08-31
- Effective date: Pending connected ratification; source-only development authorized 2026-08-31
- Compatibility window: Source development only through 2026-11-30; no runtime, operator, artifact, or production compatibility promise
- Exception expiry: 2026-11-30
- Supersedes: None
- Superseded by: None
- Owners: Architecture, ML Systems Performance
- Reviewers: Founder for source authorization; independent Architecture, Developer Platform, Security, and ML Systems review required for connected ratification

## Decision record metadata

- Affected invariants: repository-path manifest authority, activation-gated source, typed and immutable kernel contracts, import-free declarations, build-time code generation, Stable ABI ownership, explicit forward/backward co-promotion, deterministic runtime dispatch, and evidence-gated production authority
- Affected paths: the exact \`kernels/api/\` source, Bazel, and test paths declared by \`KERNEL_PLATFORM_SOURCE_PATHS\` in \`tools/repo/path_policy.py\`, this ADR, and the generated repository architecture projections
- Affected contracts: typed expression AST, semantic operator contract, provider forward/backward contract, output and named-gradient metadata, effect and launch contracts, program-group/workspace contracts, capability and numerical envelopes, implementation/workload/schedule/environment identities, and qualification identities
- Security and safety impact: permits reviewable, import-safe contract source and tests while prohibiting runtime discovery, request-time compilation or tuning, unverified native loading, artifact promotion, production dispatch, or accelerator qualification claims
- Migration: establish \`kernels/api/\` as the single typed contract authority before migrating operation declarations from legacy operation-local \`tilelang.py\` metadata to canonical import-free \`spec.py\` declarations
- Rollback: remove the early source surface and its manifest additions by expiry, or activate only the independently reviewed subset supported by completed Wave 2S evidence
- Required evidence: closed path-manifest authority, real Bazel ownership, deterministic serialization and digest tests, unsafe-expression rejection, contract consistency tests, import-free discovery, generated-code drift, Stable ABI integration, numerical qualification, immutable artifacts, explicit fallback, revocation, and rollback according to lifecycle stage

## Context

The approved TileLang platform constitution separates operation semantics, optimized mathematics, offline compilation and qualification, and runtime selection. \`kernels/api/\` is the dependency root for that architecture: it defines immutable, slotted, versioned, JSON-serializable contracts and a restricted expression language without importing TileLang, Torch, native code generation, tuning, or runtime dispatch.

The blueprint already reserves a smaller \`kernels/api/\` target surface for Wave 2S. The implementation requires a broader, concrete contract set before operation migration, import-free discovery, generated Stable ABI bindings, or qualification machinery can be implemented coherently. Repository law otherwise prohibits populating target paths before activation. Treating source presence as activation would be incorrect because contract tests cannot prove GPU correctness, numerical parity, hardware compatibility, artifact integrity, or production readiness.

ADR-0009 remains the bounded authority for the existing \`kernels/native/\` incubation and five operation-local Pairformer packages. It does not authorize this general kernel-platform contract layer. This record deliberately creates a separate closed authority rather than widening ADR-0009.

## Decision

Permit only the exact files in \`KERNEL_PLATFORM_SOURCE_PATHS\` to exist before Wave 2S as a bounded source-development exception. Every entry remains owned by \`ml-systems-performance\`, belongs to component \`kernels\`, has lifecycle status \`target\`, retains activation wave \`2S\`, and has \`production_authority\` false by implication. The source authority is hand-authored. Physical source, passing tests, generated schemas, or a loadable test library do not constitute activation.

The authorized API surface contains:

- the dependency-free typed expression AST and deterministic canonical serialization;
- output, gradient, effect, launch, forward, backward, and logical kernel contracts;
- program-group and workspace contracts;
- capability and numerical envelopes;
- implementation, workload, schedule, compile/runtime environment, and qualification identities;
- a narrow package export surface;
- one Bazel library target, \`//kernels/api:api\`; and
- focused contract and expression tests, \`//kernels/api/tests:test_contracts\` and \`//kernels/api/tests:test_expressions\`.

The expression AST may evaluate only whitelisted literal, metadata-reference, arithmetic, comparison, Boolean, set-membership, dtype/device, and statically decidable selection nodes. It may not use \`eval\`, \`exec\`, arbitrary attributes, arbitrary calls, filesystem state, environment state, imports with side effects, or runtime-dependent code execution.

The contracts must make semantic outputs, saved state, named gradients, physical program groups, workspaces, mutations, aliases, RNG, atomics, stream behavior, synchronization, hidden allocation, graph capture, determinism, capability boundaries, numerical policy, and qualification status explicit. A differentiable operation using required native autograd cannot be promoted without an atomically qualified forward and backward capability. Tensor arguments are not inferred to be differentiable merely because they are tensors.

This source exception grants no authority to discover or import operation packages at runtime, compile or tune on first use, register an alternate Torch namespace, load unsigned binaries, advertise an architecture from compilation alone, promote a capability, or weaken a numerical envelope. Production runtime may eventually consume only generated compact capability data and precompiled verified launchers after separate activation.

The exception expires on 2026-11-30 and cannot expand itself. Adding another path requires an explicit policy change. Before expiry, remove the early source surface or ratify the applicable Wave 2S activation with concrete consumers, stable contracts, complete tests, build-graph agreement, and qualification evidence.

## Consequences

Kernel declarations, code generation, planning, qualification, and dispatch can share one reviewed contract vocabulary without making \`kernels/native/\` a second semantic authority. The platform can migrate from \`public_schema\` to \`operator_schema\`, from \`tilelang.py\` discovery to import-free \`spec.py\` discovery, and from positional autograd assumptions to named gradients in independently reviewable waves.

The authorized code remains unusable as a production provider. It carries no GPU qualification, promoted capability, signed artifact, runtime compatibility, performance, or model-level evidence. Readiness reports must distinguish implemented source and local tests from hardware-qualified and promoted capabilities.

## Rejected alternatives

- Expand ADR-0009. That record has a narrower native integration and Pairformer source-incubation scope and must not become general kernel-platform authority.
- Mark \`kernels/api/\` active because it has real code and tests. Activation requires Wave 2S consumers and qualification, not source completeness.
- Put contract types under \`kernels/native/\`. Native owns generic discovery, code generation, compiler integration, Stable ABI, and loading; operation semantics and integration contracts must remain above it.
- Encode shape or capability expressions as executable Python strings. That defeats import-free discovery, deterministic serialization, generated validation, and security review.
- Maintain separate Python, native, manifest, and dispatch capability rules. One typed capability envelope must generate those consumers.
- Permit forward-only promotion for differentiable operations. Required autograd capabilities co-build, co-qualify, and co-promote forward and backward.

## Qualification and rollback

Source qualification checks the ADR and path-policy authority, exact closed path set, lifecycle metadata, Bazel labels, expression serialization and unsafe-node rejection, contract consistency, deterministic digests, and absence of runtime/compiler dependencies. Later waves add import-free discovery, generated Stable ABI schemas, FakeTensor and named autograd wiring, provider launcher linking, capability validator equivalence, numerical and gradient parity, artifact integrity, accelerator evidence, and release receipts.

Connected and production qualification remain unavailable under this ADR. Any active status, production dispatch, runtime discovery or compilation, request-time tuning, unqualified artifact load, unsupported hardware claim, silent fallback, incomplete required backward, mutable promotion record, or post-expiry source exception fails closed. Rollback removes the exact source additions and this policy exception, regenerates the architecture projections from their approved authorities, and preserves review evidence.
