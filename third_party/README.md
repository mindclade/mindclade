# Third-Party Source Authority

This directory records the reviewable state of third-party material that is
vendored, patched, or mirrored by Mindclade. Build registries and lockfiles
remain their own declared authorities; this inventory does not create a
second, mutable dependency source.

The current repository vendors no upstream source and operates no controlled
mirror. It records modern DeepEP 2.x and its `fmt` submodule as intake-only
sources, resolved by the standalone Nix package and exposed to Bazel through an
explicit artifact repository. Four reviewed patches provide deterministic
versioning, immutable toolchain paths, positive NCCL Gin attestation, and a
fail-closed read-only JIT mode. No NVSHMEM behavioral patch is applied; the
package consumes upstream NVSHMEM 3.3.9 or later. Source and patch records carry
immutable revisions, hashes, licenses, removal conditions, and ADR-0013 review
authority, but they create no production runtime authority.
