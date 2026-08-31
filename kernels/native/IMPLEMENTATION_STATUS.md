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
| Torch Stable ABI metadata | 2.10 |
| Qualified operations | 0 |
| Active operations | 0 |
| kernel-k0 | not achieved |
| CUDA qualification | not qualified |
| TileLang qualification | not qualified |
| Bazel | integration authority |
| CMake | subordinate schema packaging only |

The dependency-free schema library is source-level integration work. It exports
no operator and is not evidence that PyTorch, CUDA, TileLang, a GPU artifact, or
a hardware/software envelope is supported.

Every future shipped kernel must register only as
`torch.ops.mindclade.{name}`. There is no alternate public Python
or native operator namespace. Operation semantics remain with the owning
operation package and its readable PyTorch reference.

No production dispatch is permitted until a nonempty immutable qualification
manifest, exact artifact digest, JIT-06 decision, kernel qualification evidence,
fallback, revocation, and rollback are present. Missing or inconclusive evidence
fails closed.
