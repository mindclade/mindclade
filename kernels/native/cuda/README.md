<!--
Copyright (c) 2026 Mindclade. All rights reserved.
Proprietary and confidential. Unauthorized use, copying, or distribution is prohibited.
-->

# CUDA artifact intake

Status: TARGET, lifecycle proposed, Wave 6, JIT-06.

This directory does not ship or qualify a CUDA kernel. The current native
registry contains zero qualified operations, production authority is false, and
kernel-k0 has not been achieved.

Bazel is the integration graph authority. CMake is a subordinate packaging
boundary and defaults GPU intake off. Enabling it requires all of the following:

- an immutable qualification manifest;
- a sha256 digest for that manifest;
- an externally built immutable shared library;
- a sha256 digest for that shared library;
- at least one qualified operation in the manifest;
- the exact registration contract `torch.ops.mindclade.{name}`.

CMake verifies both file digests and fails configuration if the qualification
manifest is missing, empty, malformed, or names another dispatcher namespace.
The repository's zero-operation ABI manifest therefore cannot enable GPU
linking.

Every future shipped kernel must be registered only as
`torch.ops.mindclade.{name}`. No alternate public Python or
native operator namespace is permitted. Operation semantics, readable PyTorch
reference behavior, autograd contract, fake/meta behavior, and qualification
remain in the owning operation package.

This source boundary does not qualify TileLang, CUDA, a GPU architecture, a
driver, a compiler, or a PyTorch runtime.
