# DeepEP v2 Nix package

This directory owns Mindclade's reproducible, development-intake package for
modern DeepEP 2.x. `package.nix` consumes the immutable DeepEP and `fmt`
submodule identities in `../../source_mirrors/sources.lock.json`; no upstream
source is vendored here.

The package builds DeepEP's install-time CUDA extension and supplies NVCC for
its runtime JIT kernels. It uses NCCL Gin for the v2 expert-parallel path and
vanilla upstream NVSHMEM 3.3.9 or later for the legacy objects that DeepEP's
current `setup.py` still compiles. No DeepEP-specific NVSHMEM patch is applied.

## Build, installation, and verification

Nix is the native build and toolchain authority. The default output is a
runtime-complete Python environment containing DeepEP, Python, NVCC,
`cuobjdump`, NCCL, and NVSHMEM. On a supported Linux host:

```text
nix build .#packages.x86_64-linux.deep-ep
nix shell .#packages.x86_64-linux.deep-ep --command \
  python -c "import deep_ep; print(deep_ep.__version__)"
nix shell .#packages.x86_64-linux.deep-ep --command nvshmem-info -a
```

The development shell adds repository qualification settings:

```text
nix develop .#deepep
python -c "import deep_ep; print(deep_ep.__version__)"
nvshmem-info -a
```

Bazel exposes the real Nix-produced artifact bundle rather than a source
filegroup. It must be invoked from the pinned Nix environment:

```text
nix develop .#deepep --command \
  bazel build //third_party/packages/deep_ep:artifact_bundle
```

That target emits a normalized CPython 3.12 x86_64 wheel, ELF dependency
manifest, Nix closure inventory, SPDX SBOM, unsigned SLSA provenance statement,
and canonical runtime manifest. The wheel is deliberately Nix-closure-bound:
the current PyPI Torch 2.12 wheel uses a different CUDA/NCCL ABI and cannot be
represented as a compatible standalone DeepEP runtime. These source-build
artifacts explicitly carry `production_authority: false`; publication and
promotion remain outside this repository change.

After entering the GPU shell, an operator with at least two visible SM90 GPUs
can run the intra-node communication probe:

```text
just test-deep-ep-gpu-intranode
```

The probe imports only the Nix package, recomputes its runtime identity, requires
`nvshmem-info -a` to succeed, attests that the live `ElasticBuffer` obtained NCCL
Gin resources, and exercises asynchronous BF16 and FP8 next-rank dispatch,
cached-handle dispatch, and BF16 combine. It writes canonical unsigned evidence to
`build/evidence/gpu-deepep-intranode.json`; this remains a development result,
not production qualification.

Nix sets `NVSHMEM_DIR`, `EP_NCCL_ROOT_DIR`, `CUDA_HOME`, and
`EP_JIT_NVCC_COMPILER`. The `.#deepep` shell is also available as `.#gpu` for
compatibility. It derives `EP_JIT_CACHE_DIR` from the DeepEP source and archive
digests, reviewed patches, every governing lock, the nixpkgs revision, actual
Nix derivation and output identities, runtime versions, CUDA architecture, and
v2 build variant. This prevents unchanged version strings from colliding after
a toolchain rebuild. It also puts the NVSHMEM tools on `PATH`. A global
`LD_LIBRARY_PATH` override is intentionally unnecessary:
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
protected agent pool must also inject `MINDCLADE_PHYSICAL_HOST_ID` from a trusted
cloud-instance or bare-metal authority, `MINDCLADE_TOPOLOGY_DIGEST` from the
qualified topology manifest, the exact `MINDCLADE_GPU_SKU`, canonical RDMA
device identities, and the qualified IBGDA mode. Container hostnames are never
accepted as proof of physical separation. The local rank-zero process on each
node writes a node-specific copy of the aggregate evidence, so every protected
Buildkite job has an artifact to upload.
Each Buildkite run uses its build ID as a distinct rendezvous identity. The
Buildkite definition keeps both probes behind `just require-activation gpu`,
which continues to fail until the architecture activation and connected
protected-runner evidence exist.

## Supported intake profile

- Nix package: Linux `x86_64` and `aarch64`
- closure-bound wheel and Bazel artifact bundle: Linux `x86_64`, CPython 3.12
- H100 or H200 with SM90 PTX support
- DeepEP 2.x at the locked upstream commit
- CUDA, PyTorch, NCCL, and NVSHMEM versions locked by `flake.lock` and the
  source inventory

Use `nix build .#packages.x86_64-linux.deep-ep --dry-run` to inspect the build
plan. Source policy checks can run without a GPU. A real package build requires
a Linux CUDA builder; GPU execution still requires the separately qualified
hardware and fabric described above.
