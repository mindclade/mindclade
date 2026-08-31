# DeepEP v2 Nix package

This directory owns Mindclade's reproducible, development-intake package for
modern DeepEP 2.x. `package.nix` consumes the immutable DeepEP and `fmt`
submodule identities in `../../source_mirrors/sources.lock.json`; no upstream
source is vendored here.

The package builds DeepEP's install-time CUDA extension and supplies NVCC for
its runtime JIT kernels. It uses NCCL Gin for the v2 expert-parallel path and
vanilla upstream NVSHMEM 3.3.9 or later for the legacy objects that DeepEP's
current `setup.py` still compiles. No DeepEP-specific NVSHMEM patch is applied.

## Installation and verification

On a supported Linux GPU host:

```text
nix develop .#deepep
python -c "import deep_ep; print(deep_ep.__version__)"
nvshmem-info -a
```

After entering the GPU shell, an operator with at least two visible SM90 GPUs
can run the intra-node communication probe:

```text
just test-deep-ep-gpu-intranode
```

The probe imports the installed package, requires `nvshmem-info -a` to succeed,
routes BF16 tensors to the next rank through `ElasticBuffer`, combines them
back, and checks exact identity. It writes canonical unsigned evidence to
`build/evidence/gpu-deepep-intranode.json`; this remains a development result,
not production qualification.

Nix sets `NVSHMEM_DIR`, `EP_NCCL_ROOT_DIR`, `CUDA_HOME`, and
`EP_JIT_NVCC_COMPILER`. The `.#deepep` shell is also available as `.#gpu` for
compatibility. It derives `EP_JIT_CACHE_DIR` from the DeepEP commit, patch-lock
digest, Torch, CUDA, NCCL, NVCC, GPU architecture, and v2 build variant, so
incompatible runtimes cannot share JIT output. It also puts the NVSHMEM tools
on `PATH`. A global `LD_LIBRARY_PATH` override is intentionally unnecessary:
the DeepEP extension links immutable Nix store libraries with runtime paths
retained in its closure.

`nvshmem-info -a` validates the installed user-space library and reports its
capabilities. It does not prove that every required GPU, NVLink, RDMA, driver,
firmware, or network path is qualified.

## Host boundary

This package never edits `/etc/modprobe.d/nvidia.conf`, rebuilds initramfs,
loads `gdrdrv`, or reboots a machine. Multi-node operation requires an
independently qualified host configuration using one of the upstream-supported
IBGDA modes:

- NVIDIA driver StreamMemOps and peer-mapping options followed by an initramfs
  rebuild and reboot; or
- GDRCopy with the `gdrdrv` kernel module, accepting its CPU-assisted
  performance tradeoff.

Those privileged operations belong to the host-image or infrastructure owner
and require the protected approval path. A successful Nix build or
`nvshmem-info` run grants no production, GPU, RDMA, or network qualification.

The multi-node variant is deliberately separate. `just
test-deep-ep-gpu-multinode` requires the protected GPU pipeline context, two or
more nodes, a shared rendezvous endpoint, and an explicit node rank. The
local rank-zero process on each node writes a node-specific copy of the
aggregate evidence, so every protected Buildkite job has an artifact to upload.
Each Buildkite run uses its build ID as a distinct rendezvous identity. The
Buildkite definition keeps both probes behind `just require-activation gpu`,
which continues to fail until the architecture activation and connected
protected-runner evidence exist.

## Supported intake profile

- Linux `x86_64` and `aarch64`
- Hopper/SM90
- DeepEP 2.x at the locked upstream commit
- CUDA, PyTorch, NCCL, and NVSHMEM versions locked by `flake.lock` and the
  source inventory

Use `nix build .#packages.x86_64-linux.deep-ep --dry-run` to inspect the build
plan. A real package build and distributed DeepEP tests require a compatible
Linux GPU builder and qualified fabric.
