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
| Manifest contract | v4 / generator v8 implemented and source-verified |
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
- Manifest v4 and the registration/build/callable-capability outputs are generated
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
- BuildReceipt schema v4 atomically publishes co-built REQUIRED FWD/BWD artifacts,
  compiles program-group nodes in canonical order, verifies exact PIC/exported
  symbols, and cannot silently emit a partial or capability-unbound artifact.
- Callable ABI v1 declares typed node parameters and bindings, current-stream
  injection, adapter symbol prefixes, and a content-addressed node DSO boundary.
- Runtime workload identity binds canonical dimensions, typed scalar attributes,
  dtype, layout, mode, specialization, and exact workload digests. Signed K5
  evidence and compact native rows reconcile these values exactly.
- Immutable Ed25519-signed K4/K5, revocation, rollback, and qualified-index
  mechanisms fail closed on obsolete receipts, untrusted signers, non-atomic
  REQUIRED FWD/BWD artifacts, or native-table identity drift.
- Every canonical operation declares a separate literal
  `IMPLEMENTATION_SPECS` tuple. Generator v8 binds these authoring records to
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
- The generated v8 surface includes semantic/FWD/BWD schemas, logical launcher
  plans, private-symbol inventories, and 15 `torch.ops.mindclade.*`
  registrations for the five operation contracts.
- The Stable-ABI bridge provides source-level dtype/device/shape validation,
  current-stream access, explicit workspace allocation, and deterministic
  negative-infinity initialization. The production library target fails closed
  on missing qualification digests, symbol-set mismatch, or unresolved symbols.
- The loader verifies an explicit bundle descriptor, file digests, external
  trust and revocation decision, validates the exact v4 manifest, reconciles
  signed K5 evidence with the generated native table and its exported C
  identity, then reconciles semantic and provider dispatcher state.
- Qualification code can emit evidence candidates on exact SM90 or SM100
  hardware and can construct signed immutable release controls, but no K4/K5
  production evidence or promoted capability exists here.
- The explicit development reference runtime is isolated from native bundle
  loading and uses the same dispatcher namespace.

## Not implemented

The following are target designs, not current capabilities:

- real TileLang 0.1.13 compilation of the declared REQUIRED FWD/BWD programs;
- a qualified TileLang artifact set exercising the callable program-group bridge
  on the current CUDA stream;
- qualified double-backward behavior;
- a qualified `libmindclade_ops.so` artifact built on the pinned CUDA stack;
- native execution from a nonempty promoted capability table; the generated
  table remains empty and the loader rejects Python-only selection authority;
- production K4/K5 records signed by protected trust roots; source implements
  the immutable receipt and verification contracts, but no such records exist;
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
| Generated semantic/FWD/BWD ABI | IMPLEMENTED | Generator v8 emits five semantic, five provider-FWD, and five provider-BWD registrations, declarative FakeTensor metadata, and named REQUIRED autograd wiring. GPU execution remains unqualified. |
| Program groups/capability validators | PARTIAL | Callable node contracts, generated launcher plans, strict capability evaluation, Stable-ABI host/workspace primitives, and immutable non-selectable candidate projections are source-implemented. GPU qualification and nonempty native selection remain. |
| Hermetic compilation/artifacts/evidence | PARTIAL | BuildReceipt v4 binds atomic FWD/BWD builds. Immutable K4/K5, Ed25519 signature, revocation, rollback, and qualified-index contracts are source-implemented and CPU-tested with unmistakably test-only keys. No production receipt or signature exists. |
| Runtime capability dispatch | PARTIAL | Exact deterministic signed-index inspection, compact native selection, signed-to-native reconciliation, and exported table identity checks are source-implemented. The generated native table and checked-in trust index remain empty, so no runtime capability is active. |
| GPU qualification/promotion | BLOCKED_BY_ENVIRONMENT | Local host has no TileLang compiler, `nvcc`, or qualifying CUDA accelerator; GPU execution and K4/K5 promotion cannot be claimed. |

## Current source verification

- Focused API/native/codegen/manifest/build/CMake/Stable-ABI/policy lane:
  189 passed.
- Pairformer OPM/PWA/triangle reference and contract lane: 31 passed.
- Pairformer transition reference/gradcheck/contract lane: 3 passed.
- Repository policy lane: 25 passed; governed Pairformer paths have exact Bazel
  policy/test closure.
- Native generator v8 `--check`: zero drift.
- `bazel query //kernels/native:all`: passed.
- Repository-path manifest and architecture projections regenerate from their
  declared sources at 2,887 governed paths.

These results establish source, schema, and build-graph conformance only. They
do not establish CUDA execution, numerical parity, performance, or promotion.
