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
| Manifest contract | v2 implemented; v3 proposed |
| Torch Stable ABI metadata | 2.10 target only |
| Declared operations | 5 |
| Qualified operations | 0 |
| Active operations | 0 |
| kernel-k0 | not achieved |
| CUDA qualification | not qualified |
| TileLang qualification | not qualified |
| SM90 performance | unmeasured |
| SM100 performance | unmeasured |
| Native forward/backward spec | not implemented |
| Stable ABI tensor bridge | unavailable placeholder |
| Bazel | integration authority |
| CMake | subordinate schema packaging and immutable artifact intake |

## Implemented source controls

- Five operation-local TileLang source declarations are discovered from an
  explicit Bazel inventory through literal AST parsing.
- Manifest v2 and six registration/build inventory outputs are generated
  deterministically and checked for drift.
- Every declared operator is constrained to
  `torch.ops.mindclade.{name}`.
- Python fake and reference-recomputation autograd callables are registered
  explicitly from generated code.
- The loader verifies an explicit bundle descriptor, file digests, external
  trust and revocation decision, then reconciles exact dispatcher state.
- Qualification code can emit unsigned evidence candidates on exact SM90 or
  SM100 hardware, but no such candidate is promoted here.
- The explicit development reference runtime is isolated from native bundle
  loading and uses the same dispatcher namespace.

## Not implemented

The following are target designs, not current capabilities:

- manifest-v3 `ForwardSpec`, `BackwardSpec`, and saved-output metadata;
- generated public-composite, raw-forward, and raw-backward operator families;
- tuple or optional-tensor schema parsing and Stable ABI boxing;
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
