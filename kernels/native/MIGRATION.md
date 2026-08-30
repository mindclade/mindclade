<!--
Copyright (c) 2026 Mindclade. All rights reserved.
Proprietary and confidential. Unauthorized use, copying, or distribution is prohibited.
-->

# Native kernel migration boundary

Status: TARGET. This document records constraints; it does not claim that a
kernel, provider, or user workload has been migrated.

## Current baseline

The registry contains zero qualified and zero active operations. Production
authority is false, kernel-k0 has not been achieved, and CUDA and TileLang are
not qualified. Parent architecture, repository-path manifests, generated files,
and dependency locks are intentionally outside this module-only change.

## Future migration sequence

1. Establish the operation-local readable PyTorch reference and full semantic,
   fake/meta, and autograd contracts.
2. Produce representative profiling evidence and ratify the operation-specific
   Wave 6 JIT-06 decision.
3. Add only the selected implementation and reconcile native locks, Bazel, Nix,
   license/provenance, and packaging authority.
4. Qualify the exact hardware/software envelope, numerical behavior, recovery,
   performance threshold, fallback, revocation, and rollback.
5. Add the immutable qualification record and artifact digest.
6. Enable production dispatch only for the exact non-revoked envelope.

Every future shipped kernel must register only as
<code>torch.ops.mindclade.&lt;name&gt;</code>. Migration must not introduce a
second public Python or native operator namespace, move operation semantics into
this integration layer, or interpret candidate source as qualification.

If qualification fails or is revoked, remove the candidate artifact from
dispatch and retain the operation-local PyTorch reference as the explicit
fallback.
