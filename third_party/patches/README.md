# Third-party patches

This directory is the exclusive home for a reviewed, hash-pinned patch when an
immutable third-party source cannot be consumed unchanged.

## Local Patch Inventory

`deep_ep/` contains the four bounded patches authorized by ADR-0013. They cover
deterministic version metadata, declared Nix toolchain paths, positive NCCL Gin
attestation, and fail-closed read-only JIT operation. They do not modify
NVSHMEM. Every patch is bound to the exact DeepEP commit with a digest,
rationale, owner, and removal condition in `patches.lock.json`; the Nix build
asserts and consumes that closed set.
