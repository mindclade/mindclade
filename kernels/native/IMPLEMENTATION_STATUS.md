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
| Manifest contract | v3 / generator v7 implemented and source-verified |
| Torch Stable ABI metadata | 2.10 target only |
| Declared operations | 5 |
| Unpromoted implementation candidates | 17 across 5 operations |
| Qualified operations | 0 |
| Active operations | 0 |
| kernel-k0 | not achieved |
| CUDA qualification | not qualified |
| TileLang qualification | not qualified |
| SM90 performance | unmeasured |
| SM100 performance | unmeasured |
| Native forward/backward spec | all 5 operations declare REQUIRED named FWD/BWD contracts |
| Stable ABI tensor bridge | source-implemented and CPU-policy verified; CUDA execution unqualified |
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
- Program groups use group-scoped workspaces, explicit per-node access modes,
  deterministic topological order, and validated writer/reader dataflow. The
  generated manifest carries an exact builder-free launcher plan and private
  symbol inventory for each declared group.
- The production loader validates launcher plans as immutable data and never
  imports builders or executes a Python DAG. CMake requires an explicitly
  supplied, digest-verified bridge artifact whenever private symbols exist.
- Receipt schema v3 atomically publishes co-built REQUIRED FWD/BWD artifacts,
  compiles program-group nodes in canonical order, verifies exact PIC/exported
  symbols, and cannot silently emit a partial or capability-unbound artifact.
- Every canonical operation declares a separate literal
  `IMPLEMENTATION_SPECS` tuple. Generator v6 binds these authoring records to
  the semantic operation and emits independent implementation/envelope
  digests plus builder-free runtime projections.
- Capability envelopes now have strict canonical construction, deterministic
  evaluation/rendering, layout-aware tensor metadata, expression-reference
  inventories, and checked signed-64-bit arithmetic. Every generated candidate
  is explicitly `promoted: false` and `selectable: false`.
- Discovery validates every tensor constraint and expression reference against
  the semantic schema, including tensor-versus-scalar argument kind. Transition
  candidates bind exact `sm90a`/`sm100a` targets rather than weaker architecture
  class names.
- Declarative FakeTensor implementations and named REQUIRED autograd hooks are
  generated without mutable saved-tensor state or runtime discovery.
- The generated v7 surface includes semantic/FWD/BWD schemas, logical launcher
  plans, private-symbol inventories, and 15 `torch.ops.mindclade.*`
  registrations for the five operation contracts.
- The Stable-ABI bridge provides source-level dtype/device/shape validation,
  current-stream access, explicit workspace allocation, and deterministic
  negative-infinity initialization. The production library target fails closed
  on missing qualification digests, symbol-set mismatch, or unresolved symbols.
- The loader verifies an explicit bundle descriptor, file digests, external
  trust and revocation decision, validates the exact v3 manifest, then
  reconciles semantic and provider dispatcher state.
- Qualification code can emit unsigned evidence candidates on exact SM90 or
  SM100 hardware, but no such candidate is promoted here.
- The explicit development reference runtime is isolated from native bundle
  loading and uses the same dispatcher namespace.

## Not implemented

The following are target designs, not current capabilities:

- real TileLang 0.1.13 compilation of the declared REQUIRED FWD/BWD programs;
- a typed callable `ProgramNodeSpec` ABI describing raw tensor, scalar, output,
  workspace, and current-stream slots for executable program groups;
- a qualified native program-group bridge that invokes private nodes on the
  current stream;
- qualified double-backward behavior;
- a qualified `libmindclade_ops.so` artifact built on the pinned CUDA stack;
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
| Generated semantic/FWD/BWD ABI | IMPLEMENTED | Generator v7 emits five semantic, five provider-FWD, and five provider-BWD registrations, declarative FakeTensor metadata, and named REQUIRED autograd wiring. GPU execution remains unqualified. |
| Program groups/capability validators | PARTIAL | Group/workspace/dataflow contracts, generated launcher plans, strict capability evaluation, Stable-ABI host/workspace primitives, and 17 immutable non-selectable candidate projections are implemented. A typed callable node ABI, GPU qualification, and runtime selection remain. |
| Hermetic compilation/artifacts/evidence | PARTIAL | Receipt schema v3 provides atomic FWD/BWD co-builds, canonical group compilation, exact PIC/symbol checks, and immutable receipts. Real TileLang/CUDA execution, sandbox hardening, transitive evidence DAGs, and signatures remain. |
| Runtime capability dispatch | NOT_IMPLEMENTED | No promoted compact v3 capability index exists. |
| GPU qualification/promotion | BLOCKED_BY_ENVIRONMENT | Local host has no CUDA accelerator or TileLang toolchain; K4/K5 cannot be claimed. |

## Current source verification

- Focused API/native/codegen/manifest/build/CMake/Stable-ABI/policy lane:
  189 passed.
- Pairformer OPM/PWA/triangle reference and contract lane: 31 passed.
- Pairformer transition reference/gradcheck/contract lane: 3 passed.
- Repository policy lane: 24 passed; all 37 active Pairformer paths have exact
  Bazel policy/test closure.
- Native generator v7 `--check`: zero drift.
- `bazel query //kernels/native:all`: passed.
- Repository-path manifest and architecture projections regenerate from their
  declared sources at 2,887 governed paths.

These results establish source, schema, and build-graph conformance only. They
do not establish CUDA execution, numerical parity, performance, or promotion.
