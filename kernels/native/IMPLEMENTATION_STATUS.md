<!--
Copyright (c) 2026 Mindclade. All rights reserved.
Proprietary and confidential. Unauthorized use, copying, or distribution is prohibited.
-->

# Native integration implementation status

Overall readiness: TARGET

| Concern | Current state |
|---|---|
| Lifecycle | proposed |
| Owner | ml-systems-performance |
| Activation | Wave 6, JIT-06 |
| Production authority | false |
| Manifest contract | v3 implemented and source-verified |
| Torch Stable ABI metadata | 2.10 target only |
| Declared operations | 5 |
| Qualified operations | 0 |
| Active operations | 0 |
| kernel-k0 | not achieved |
| CUDA qualification | not qualified |
| TileLang qualification | not qualified |
| SM90 performance | unmeasured |
| SM100 performance | unmeasured |
| Native forward/backward spec | typed contract implemented; current operations use COMPOSITE autograd |
| Stable ABI tensor bridge | unavailable placeholder |
| Bazel | integration authority |
| CMake | subordinate schema packaging and immutable artifact intake |

## Implemented source controls

- Five operation-local `spec.py` declarations are discovered from an explicit
  Bazel inventory through restricted, import-free literal AST parsing.
- Manifest v3 and six registration/build inventory outputs are generated
  deterministically from typed contracts and checked for byte drift.
- Every declared operator is constrained to
  `torch.ops.mindclade.{name}`.
- Semantic and provider-forward schemas are generated separately. Provider
  backward schemas and bindings are emitted only when declared by a validated
  `BackwardSpec`.
- Declarative FakeTensor implementations and explicit COMPOSITE autograd hooks
  are generated without mutable saved-tensor state or runtime discovery.
- The loader verifies an explicit bundle descriptor, file digests, external
  trust and revocation decision, validates the exact v3 manifest, then
  reconciles semantic and provider dispatcher state.
- Qualification code can emit unsigned evidence candidates on exact SM90 or
  SM100 hardware, but no such candidate is promoted here.
- The explicit development reference runtime is isolated from native bundle
  loading and uses the same dispatcher namespace.

## Not implemented

The following are target designs, not current capabilities:

- a REQUIRED-autograd operation with co-built native forward and backward
  TileLang artifacts;
- optimized TileLang backward launchers;
- qualified double-backward behavior;
- a production Stable ABI tensor allocation and stream bridge;
- a repository-built `libmindclade_ops.so` artifact;
- runtime selection among multiple qualified implementations;
- signed production qualification records;
- measured SM90 or independently tuned SM100 schedules.

The default CMake target is `mindclade_native_schema`. The CMake switch is
`MINDCLADE_NATIVE_ENABLE_GPU`; there is no public
`MINDCLADE_NATIVE_SCHEMA_ONLY` option. Code generation is an explicit build
action and is not run by CMake configuration.

## Evidence boundary

The checked-in library and source tests do not establish PyTorch, TileLang,
CUDA, numerical, performance, graph-capture, stream, autograd, or hardware
qualification for a production artifact.

No production dispatch is permitted until a nonempty immutable qualification
manifest, exact artifact digest, JIT-06 decision, full kernel evidence,
fallback, revocation, and rollback are present. Missing or inconclusive evidence
fails closed.

## TMA and swizzle status

The repository contains build-time capability, transfer, shared-layout, CTA
raster, barrier, cluster, and SM100a gather/scatter contracts. `transition` is
the first layout-policy consumer. No generated-instruction inspection, GPU
parity, deadlock stress, or benchmark evidence has been produced, so every TMA
and swizzle profile remains `TARGET` and unqualified.

## Kernel Platform v3 Status

The v3 constitution and implementation plan are recorded in `MIGRATION.md`.
This is an architecture milestone, not a production-readiness claim.

| Area | Readiness | Evidence / gap |
| --- | --- | --- |
| v3 terminology and authority | IMPLEMENTED | Native documentation records `spec.py`, `operator_schema`, three API surfaces, and two-plane laws. |
| Typed expression/core contracts | IMPLEMENTED | Wave 1 provides the restricted AST, immutable semantic/integration/environment contracts, 25 passing pytest cases, and two passing Bazel test targets. |
| `spec.py` restricted discovery | IMPLEMENTED | Five canonical declarations are parsed without importing operation packages; unsafe AST forms and legacy locality fail closed. |
| Generated semantic/FWD/BWD ABI | PARTIAL | v3 emits semantic and provider schemas, Stable-ABI registration, FakeTensor, and explicit autograd surfaces; the five current operations remain COMPOSITE and provide no qualified native BWD artifacts. |
| Program groups/capability validators | NOT_IMPLEMENTED | Contracts and cross-consumer equivalence tests remain. |
| Hermetic compilation/artifacts/evidence | NOT_IMPLEMENTED | Existing offline build receipts are not the final transitive evidence DAG. |
| Runtime capability dispatch | NOT_IMPLEMENTED | No promoted compact v3 capability index exists. |
| GPU qualification/promotion | BLOCKED_BY_ENVIRONMENT | Local host has no CUDA accelerator or TileLang toolchain; K4/K5 cannot be claimed. |

## Current source verification

- `python -m pytest -q -p no:cacheprovider kernels/native/tests`: 159 passed.
- `python -m pytest -q -p no:cacheprovider tools/repo/tests/test_repository_policies.py`:
  18 passed with 908 subtests.
- Selected Bazel API/native/codegen/TMA/swizzle lane: 14 targets passed.
- Direct Pairformer/API source lane: 76 passed.
- Repository-path manifest and architecture projections regenerate from their
  declared sources at 2,636 governed paths.

These results establish source, schema, and build-graph conformance only. They
do not establish CUDA execution, numerical parity, performance, or promotion.
