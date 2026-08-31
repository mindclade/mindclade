# Third-Party Source Authority

This directory records the reviewable state of third-party material that is
vendored, patched, or mirrored by Mindclade. Build registries and lockfiles
remain their own declared authorities; this inventory does not create a
second, mutable dependency source.

The current repository contains no vendored upstream source, local patches, or
controlled source mirrors. It records modern DeepEP 2.x and its `fmt`
submodule as intake-only sources, resolved through the pinned nixpkgs input in
the opt-in Linux SM90 GPU shell. The package uses NCCL Gin and unpatched
upstream NVSHMEM. The record carries immutable revisions, source hashes,
license digests, and a review reference, but it creates no production
dependency or authority.
