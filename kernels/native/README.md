<!--
Copyright (c) 2026 Mindclade. All rights reserved.
Proprietary and confidential. Unauthorized use, copying, or distribution is prohibited.
-->

# Mindclade native operator integration

Status: TARGET. Lifecycle: proposed. Activation: Wave 6 through JIT-06.
Production authority: false.

The operation source inventory contains four declared, unqualified TileLang
CUDA implementations: `outer_product_mean`, `pair_weighted_average`,
`triangle_attention`, and `triangle_multiplication`. The ABI qualification
registry still has zero qualified and zero active operations. This module has
not achieved kernel-k0 and is not a production kernel bundle. The sources and
profiles are build inputs only; they do not establish CUDA, TileLang, PyTorch,
performance, or hardware qualification.

## Non-negotiable operator namespace

Every future shipped kernel must be registered only as
`torch.ops.mindclade.{name}`. No alternate public Python package,
Python operator namespace, C extension namespace, or native dispatcher
namespace may expose kernel behavior.

The readable PyTorch reference, operation schema, fake/meta behavior, autograd
contract, shape/dtype/layout rules, numerical tolerances, and benchmark meaning
remain operation-local. This integration directory may package a qualified
implementation; it never becomes the semantic owner.

## Build authority

Bazel is the repository integration, visibility, affected-test, and release
closure authority. The `//kernels/native:native_schema` target has no
undeclared external dependency.

CMake is subordinate packaging support for the same schema sources. It does not
resolve or pin repository dependencies and does not mutate the source tree
during configuration. The schema target records Torch Stable ABI 2.10 as the
requested contract, but this metadata is not PyTorch compatibility or production
qualification evidence.

A local non-promotional schema build is:

    cmake -S kernels/native -B out/native-schema
    cmake --build out/native-schema --target mindclade_native_schema
    cmake --install out/native-schema --prefix out/native-install

The build creates an installable shared schema target with hidden symbols and
strict compiler warnings. It neither imports PyTorch nor registers an operator.

The deterministic offline specialization inventory is
`manifests/tilelang_profiles.sm90.json`. It covers all four declared operations,
including both incoming and outgoing triangle multiplication and the four
bounded profiles declared by triangle attention. The owning offline compiler
receives this file with target `cuda`; `sm90` identifies the intended future
qualification environment, not an architecture-specific artifact or evidence.
TileLang 0.1.13, CUDA compilation, parity, performance, and SM90 execution have
not been qualified by this repository state.

## GPU intake

`MINDCLADE_NATIVE_ENABLE_GPU` defaults to false. When enabled, CMake
requires immutable qualification and binary files plus their
`sha256:{64 lowercase hex}` digests. It verifies the digests, the
dispatcher namespace, the registration contract, and a nonempty qualified
operation list before linking. The checked-in manifest intentionally fails this
gate because its qualified operation list is empty.

## Qualification boundary

A future operation requires its owning reference contract, a measured Wave 6
bottleneck, a JIT-06 decision, forward/backward and fake/meta coverage,
numerical and determinism evidence, exact hardware/software qualification,
performance threshold, provenance/license review, fallback, revocation, and
rollback. None of that evidence is asserted here.

Generated files are edited through their owning source and generator only.
Source checks, local compilation, and local benchmarks are non-promotional.
