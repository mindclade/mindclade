<!--
Copyright (c) 2026 Mindclade. All rights reserved.
Proprietary and confidential. Unauthorized use, copying, or distribution is prohibited.
-->

# Mindclade native operator integration

Status: TARGET. Lifecycle: proposed. Activation: Wave 6 through JIT-06.
Production authority: false.

This document describes the implemented manifest-v4 infrastructure. The
broader kernel-platform architecture and migration history are specified in
`MIGRATION.md`. Future behavior is not presented here as current behavior.

The source inventory contains five declared, unqualified TileLang CUDA
implementations: `outer_product_mean`, `pair_weighted_average`,
`triangle_attention`, `triangle_multiplication`, and `transition`. The ABI qualification
registry has zero qualified and zero active operations. This module has not
achieved kernel-k0 and is not a production kernel bundle.

## Authority and invariants

The readable PyTorch reference, mathematical semantics, shape and dtype rules,
mask and bias behavior, fake/meta behavior, autograd contract, tolerances, and
benchmark meaning remain in each operation package at
`kernels/<family>/<operation>/tilelang.py`.

`kernels/native` owns deterministic discovery, generated registration,
offline compilation inputs, ABI policy, verified loading, and qualification
evidence plumbing. It does not become the semantic owner of an operation.

Every shipped public or internal kernel operation must use the single dispatcher
namespace `torch.ops.mindclade.{name}`. Alternate public Python, extension, or
provider namespaces are prohibited.

Other non-negotiable properties are:

- declarations are explicit Bazel inputs rather than an implicit filesystem scan;
- source discovery parses literal AST metadata and does not import operation modules;
- production processes do not discover, compile, autotune, or regenerate kernels;
- generated outputs are changed only through their source declarations and generator;
- unqualified source and build receipts never grant production authority;
- a native bundle is verified before loading and reconciled against its manifest after loading.

## Implemented manifest-v4 flow

```text
kernels/<family>/<operation>/tilelang.py
        |
        | explicit build-declared source input
        v
codegen/discover.py
        |
        v
KernelSpec v2
        |
        v
codegen/generate.py
        |
        +--> generated/native_ops.json
        +--> generated/registration.generated.cpp
        +--> generated/operation_registry.generated.cpp
        +--> generated/python_registration_generated.py
        +--> generated/native_ops.generated.cmake
        `--> generated/native_ops.generated.bzl

separate offline TileLang build and protected qualification
        |
        v
immutable external GPU artifact plus evidence
        |
        v
verified bundle loader
        |
        v
torch.ops.mindclade.*
```

Manifest v2 describes one public schema, one CUDA launch symbol, one fake
callable, and either registered Python autograd callables or an explicit
`not_supported` policy. It supports only canonical single-`Tensor` returns.
It does not describe raw forward operators, saved auxiliary outputs, native
backward launchers, optional gradients, or double backward.

## Current build modes

Bazel is the repository integration, visibility, affected-test, and release
closure authority. CMake is subordinate packaging support.

The default CMake build produces `mindclade_native_schema`. It consumes the
committed generated schema source and neither runs code generation nor compiles
TileLang. `MINDCLADE_NATIVE_SCHEMA_ONLY` is an internal compile definition, not
a user-selectable CMake option.

```bash
cmake -S kernels/native -B out/native-schema
cmake --build out/native-schema --target mindclade_native_schema
cmake --install out/native-schema --prefix out/native-install
```

GPU artifact intake is enabled with `MINDCLADE_NATIVE_ENABLE_GPU=ON`. It
requires an external immutable artifact, qualification manifest, and both
digests. CMake validates the namespace, registration contract, digests, and a
nonempty qualified-operation set before linking. The checked-in qualification
state intentionally fails this production gate.

For AlphaFold 3, the specialized pair-plane is formed by outgoing/incoming triangle multiplication, row/column triangle attention, and the SwiGLU transition contraction. Model-owned layer normalization, up projections, residual/dropout order, sharding, 48-block orchestration, and the generic single-representation transformer remain outside this native boundary.

The profile files are bounded offline build inputs. `sm90` and `sm100` are
intended qualification environments, not proof that architecture-specific
artifacts have been compiled, run, or measured.

## File reference

The current directory contains 62 source, documentation, generated, manifest,
and test entries. The tables below describe their implemented purpose.

### Root files

| File | Implemented purpose | Normal editing policy |
|---|---|---|
| `README.md` | Architecture, authority, flow, build modes, and file reference for the subsystem. | Edit when the implemented subsystem changes. |
| `IMPLEMENTATION_STATUS.md` | Evidence ledger separating implemented source controls from unqualified or proposed behavior. | Edit with evidence-bearing changes. |
| `MIGRATION.md` | Reviewed kernel-platform contract, terminology, and migration gates through the implemented manifest-v4 boundary. | Edit when the approved target design changes. |
| `component.yaml` | Machine-readable lifecycle, ownership, activation, authority, and readiness metadata. | Edit only with matching governance changes. |
| `CMakeLists.txt` | Subordinate schema packaging and optional immutable GPU-artifact intake. | Edit carefully; it is not the dependency authority. |
| `BUILD.bazel` | Repository build graph, explicit operation source inventory, codegen targets, policy inputs, and test suites. | Edit with source-inventory or build-graph changes. |
| `__init__.py` | Import-safe `kernels.native` package marker with no registration side effects. | Rarely. |

### `cmake/`

| File | Implemented purpose |
|---|---|
| `cmake/MindcladeTorchStable.cmake` | Fixes the target Stable ABI version at 2.10 and applies C++17, PIC, hidden visibility, and strict warning policy to native targets. |

The current function applies schema-only compile definitions to every target
using it. It does not yet provide distinct schema, wrapper, and qualified GPU
target policies.

### `codegen/`

| File | Implemented purpose |
|---|---|
| `codegen/__init__.py` | Import-safe package marker. |
| `codegen/discover.py` | Validates only explicitly declared operation sources and extracts one literal `@mindclade_kernel` declaration from each source through the Python AST. |
| `codegen/schema.py` | Parses the supported semantic/provider PyTorch schema subset into deterministic named arguments and returns. |
| `codegen/generate.py` | Canonically orders discovered specs and renders the generated registration, launcher-plan, capability-table, manifest, CMake, Bazel, and Python outputs. |

Discovery neither imports operation code nor initializes CUDA or TileLang. A
declared source must be exactly
`kernels/<family>/<operation>/tilelang.py`, must not traverse symlinks, and must
contain one top-level synchronous `build_tilelang_program` declaration.

### `generated/`

Every file in this directory is derived and must not be hand-edited.

| File | Implemented purpose |
|---|---|
| `generated/__init__.py` | Package marker for committed generated Python output. |
| `generated/native_ops.json` | Canonical manifest-v4 semantic/provider inventory, callable plans, source digests, generator identity, and semantic digest. |
| `generated/registration.generated.cpp` | Defines public schemas with `STABLE_TORCH_LIBRARY(mindclade, m)`. |
| `generated/operation_registry.generated.cpp` | Declares exact C-linkage launch symbols, provides Stable ABI wrappers, and binds them to the CUDA dispatch key. |
| `generated/python_registration_generated.py` | Explicitly imports and registers operation-local fake and autograd callables. |
| `generated/native_ops.generated.cmake` | Generated operation-local source list for future CMake consumers. |
| `generated/native_ops.generated.bzl` | Generated operation-local source list for Bazel consumers. |

The C-linkage launch declarations contain C++ Stable ABI tensor types. C
linkage fixes symbol names; it is not a language-neutral C ABI.

### `manifests/`

| File | Implemented purpose |
|---|---|
| `manifests/native_ops.schema.json` | JSON Schema for the exact generated manifest-v4 format and locality, callable ABI, namespace, backend, and no-runtime-compilation invariants. |
| `manifests/benchmark.schema.json` | Contract for benchmark evidence candidates. |
| `manifests/qualification.schema.json` | Contract for qualification evidence candidates. |
| `manifests/qualification_release.schema.json` | Exact immutable K4/K5, revocation, and rollback receipt payload contract. |
| `manifests/qualified_capability_index.schema.json` | Exact detached-Ed25519 signed qualified-index contract and empty source-state contract. |
| `manifests/qualified_capability_index.json` | Empty, unsigned, unqualified source index; it cannot authorize loading. |
| `manifests/performance_policy.json` | Unmeasured baseline state and post-promotion regression policy. |
| `manifests/tilelang_profiles.sm90.json` | Bounded, unqualified SM90 specialization inputs for all five declared operations. |
| `manifests/tilelang_profiles.sm100.json` | Separate bounded, unqualified SM100 specialization inputs; separation is not independent tuning evidence. |

### `stable_abi/`

| File | Implemented purpose |
|---|---|
| `stable_abi/CMakeLists.txt` | Builds and installs the `mindclade_native_schema` shared target. |
| `stable_abi/registration.cpp` | Compile-time namespace and empty-qualified-inventory assertions. It currently exports no ABI-version function. |
| `stable_abi/tensor_bridge.cpp` | Explicit placeholder proving that the Stable ABI tensor bridge is not yet available. |
| `stable_abi/abi_manifest.json` | Machine-readable Stable ABI target metadata, declared operators, and zero qualified/active state. |

This directory does not currently provide dtype checks, device checks, output
allocation, stream bridges, or a production launcher ABI.

### `cuda/`

| File | Implemented purpose |
|---|---|
| `cuda/CMakeLists.txt` | Fail-closed validation and linkage of an externally built immutable GPU artifact when GPU intake is explicitly enabled. |
| `cuda/operation_registry.cpp` | Handwritten namespace/registration-contract anchor; the operator list remains generated. |
| `cuda/README.md` | Documents CUDA artifact-intake authority and the zero-qualification boundary. |

This directory is registration and artifact-intake glue. TileLang is the
declared optimized-math provider for the current manifest. Any future
handwritten CUDA exception requires an explicit architecture decision and its
own qualification; it is not silently prohibited or silently accepted.

### `tilelang/`

| File | Implemented purpose |
|---|---|
| `tilelang/README.md` | Documents the offline TileLang source and compilation boundary. |
| `tilelang/__init__.py` | Import-safe package marker. |
| `tilelang/model.py` | Provides the build-plane TileLang model and manifest helpers without becoming an operation-declaration authority. |
| `tilelang/decorator.py` | Validates and attaches non-authoritative developer metadata when an operation module is deliberately imported. |
| `tilelang/registry.py` | Deterministically validates a supplied set of specs; it does not discover files. |
| `tilelang/targets.py` | Defines immutable portable, SM90/SM90a, and SM100/SM100a capability contracts and generates their semantic manifest. |
| `tilelang/tma.py` | Emits managed/manual TMA, cluster, gather/scatter, and explicit portable-fallback transfer lanes. |
| `tilelang/swizzle.py` | Selects consumer-driven shared layouts and CTA raster policies without runtime discovery. |
| `tilelang/manifest.py` | Loads and validates the committed generated manifest and its source/semantic digests. |
| `tilelang/build.py` | Performs bounded, explicit offline specialization compilation and emits build receipts; it fails if TileLang is unavailable. |

The decorator is ergonomic metadata, not runtime registration authority.
Production discovery reads its literal arguments from the AST.

### `python/`

| File | Implemented purpose |
|---|---|
| `python/__init__.py` | Exposes the verified bundle descriptor, trust/error types, and `load_native_library`; it exposes no operator aliases. |
| `python/loader.py` | Validates bounded bundle paths, digests, revision and plan identity, external signature/trust/revocation decision, then loads once and reconciles exact dispatcher state. |
| `python/capability_index.py` | Verifies explicit Ed25519 trust roots, immutable qualified indexes, revocations, rollbacks, and exact deterministic pre-load selection. It cannot authorize a nonempty native table by itself. |
| `python/registration.py` | Imports only the packaged generated registrar and runs it idempotently. |
| `python/qualification.py` | Preserves unsigned CUDA evidence candidates and defines immutable K4/K5/revocation/rollback receipts plus protected-lane signing helpers. CPU tests use test-only evidence and never establish K4/K5. |
| `python/reference_runtime.py` | Explicit environment-gated, process-isolated development runtime that registers the four PyTorch references in the same dispatcher namespace. |

The loader accepts an explicit `NativeBundleDescriptor`. The environment
variable `MINDCLADE_NATIVE_LIBRARY` is intentionally not a trusted override.
The reference runtime and a native bundle cannot coexist in one process.

### `tests/`

| File | Implemented purpose |
|---|---|
| `tests/pytest_runner.py` | Stable Bazel entry point for individual pytest files. |
| `tests/test_abi_compatibility.py` | Enforces approved Stable ABI headers, macros, symbols, and generated C++ policy. |
| `tests/test_autograd.py` | Verifies explicit generated autograd registration and operation-local callable behavior. |
| `tests/test_build_policy.py` | Verifies bounded offline profiles, receipt identity, and fail-closed TileLang compilation behavior. |
| `tests/test_cmake_policy.py` | Verifies schema-only defaults and fail-closed immutable GPU-artifact intake. |
| `tests/test_codegen.py` | Verifies deterministic generator output and Stable ABI/CMake/Bazel inventories. |
| `tests/test_codegen_drift.py` | Regenerates into a temporary directory and rejects committed generated drift. |
| `tests/test_discovery.py` | Enforces explicit, operation-local, literal AST declarations and rejects duplicates or escaped paths. |
| `tests/test_export.py` | Exercises export integration through explicit generated Python registration. |
| `tests/test_fake_tensor.py` | Verifies operation-local fake implementations and compiler shape propagation. |
| `tests/test_loader_policy.py` | Verifies pre-load trust ordering, path/digest checks, exact bundle identity, and poisoned-state behavior after partial load. |
| `tests/test_manifest.py` | Verifies manifest constants, canonical ordering, and semantic/source digests. |
| `tests/test_namespace.py` | Verifies the declared operator surface remains exclusively in the Mindclade dispatcher namespace. |
| `tests/test_opcheck.py` | Verifies declared inventory and dispatcher reconciliation requirements; it does not claim actual GPU `opcheck` qualification. |
| `tests/test_policy.py` | Enforces lifecycle, namespace, build/test authority, profile coverage, and zero-production claims. |
| `tests/test_qualification.py` | Verifies qualification configuration, exact profile/artifact selection, evidence shape, and fail-closed hardware requirements. |
| `tests/test_capability_index.py` | Verifies content identity, explicit Ed25519 trust, exact envelope selection, atomic REQUIRED artifacts, revocation/rollback, schemas, and test-only non-promotion. |
| `tests/test_reference_runtime.py` | Verifies explicit reference-runtime gating, operation behavior, and process isolation. |
| `tests/test_schema_manifest.py` | Validates the generated operator manifest against its JSON Schema. |

Actual CUDA `torch.library.opcheck`, numerical parity, compilation, non-default
stream, graph-capture, determinism, and latency evidence are produced only by
the qualification path on the intended GPU. Source tests do not substitute for
that evidence.

## Adding an operation under manifest v4

An operation declaration alone is necessary but not sufficient for a shipped
kernel. The complete source workflow is:

1. Establish operation-local reference, schema, fake behavior, autograd policy,
   shape/dtype/layout contract, and bounded qualification profiles.
2. Add the canonical operation source to the repository-path manifest and the
   explicit Bazel authoring-source inventory.
3. Add one literal `@mindclade_kernel` declaration to
   `kernels/<family>/<operation>/tilelang.py`.
4. Regenerate and review every generated output.
5. Reconcile Bazel, subordinate packaging, dependency locks, provenance, and
   affected tests.
6. Compile and qualify the exact artifact outside the request path.
7. Promote only through an independently reviewed, signed, non-revoked
   qualification record and executable plan.

The engineering invariant is:

> Add semantic and optimized behavior to the canonical operation package. Do
> not hand-maintain a native operator registry. Native registration is derived,
> but repository activation and production qualification are still explicit.

## Qualification boundary

A future operation requires an owning reference contract, measured bottleneck,
JIT-06 decision, forward/backward and fake/meta coverage, numerical and
determinism evidence, exact hardware/software qualification, performance
threshold, provenance/license review, fallback, revocation, and rollback.
None of that evidence is asserted by this document.

### TMA and swizzle intake

TMA and shared-layout selection is an offline build input. The portable CUDA
lane never forces TMA; SM90a and SM100a have separate capability contracts,
toolchain floors, layouts, and qualification evidence. Manual mbarrier, cluster
multicast, remote shared-memory, and gather/scatter helpers fail closed when
the selected target cannot preserve their semantics. These source contracts are
unqualified and do not establish production performance.

## Kernel Platform Constitution

The approved target architecture is defined by the **Kernel Platform v3
constitution** in [MIGRATION.md](MIGRATION.md). The current declaration boundary
is the manifest-v4, operation-local `spec.py` system; optimized mathematics and
builders remain in `tilelang.py`. Capability status is recorded separately in
[IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md).

The final terminology is:

| Legacy term | Final term |
| --- | --- |
| public schema | operator schema |
| public operation | semantic operator |
| raw operations | provider operators |
| model-facing API | Python facade |

The target declaration authority is
`kernels/<family>/<operation>/spec.py`. `tilelang.py` owns builders and
optimized mathematics only. Production runtime code consumes generated compact
capability data and precompiled launchers; it never discovers source files,
imports TileLang authoring modules, compiles, tunes, or benchmarks.
