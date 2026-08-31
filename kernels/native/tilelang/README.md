<!--
Copyright (c) 2026 Mindclade. All rights reserved.
Proprietary and confidential. Unauthorized use, copying, or distribution is prohibited.
-->

# TileLang intake boundary

Status: TARGET-only intake documentation. TileLang is not qualified, not an
active dependency, and not a production compatibility surface in this module.

The current native registry contains zero qualified operations. kernel-k0 has
not been achieved and production authority is false. No TileLang source in this
tree may be interpreted as a compiled implementation, benchmark result,
qualification record, or dispatchable artifact.

A TileLang implementation may be considered only after an operation-local
PyTorch reference exists, representative profiling identifies a Wave 6
bottleneck, and an operation-specific JIT-06 decision selects TileLang for a
measurable gap. Qualification must cover the exact source revision, compiler,
PyTorch ABI, CUDA/driver and hardware envelope, forward/backward behavior,
fake/meta and autograd contracts, determinism, performance, provenance/license,
fallback, revocation, and rollback.

Every future shipped kernel must register only as
`torch.ops.mindclade.{name}`. No TileLang-owned Python API,
alternate native namespace, or provider-specific public entry point is allowed.
Operation semantics remain in the owning operation package.
