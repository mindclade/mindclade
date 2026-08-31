{
  pkgs,
  nixpkgsRevision,
}:
let
  sourceLock = builtins.fromJSON (builtins.readFile ../../source_mirrors/sources.lock.json);
  records = builtins.filter (entry: entry.name == "deep-ep") sourceLock.entries;
  record =
    assert builtins.length records == 1;
    builtins.head records;
  cudaCapabilities = record.build_authority.cuda_capabilities;
  cudaPackages = pkgs.cudaPackages;
  pythonPackages = pkgs.python312Packages;
  nvshmemRoot = pkgs.lib.getInclude cudaPackages.libnvshmem;
  ncclRoot = pkgs.symlinkJoin {
    name = "deepep-nccl-${cudaPackages.nccl.version}";
    paths = [
      (pkgs.lib.getDev cudaPackages.nccl)
      (pkgs.lib.getLib cudaPackages.nccl)
    ];
  };
  package =
    pythonPackages.buildPythonPackage.override
      {
        inherit (pythonPackages.torch) stdenv;
      }
      {
        pname = "deep-ep";
        version = record.build_authority.version;
        pyproject = true;
        strictDeps = true;

        src = pkgs.fetchFromGitHub {
          owner = "deepseek-ai";
          repo = "DeepEP";
          rev = record.upstream.revision;
          fetchSubmodules = true;
          hash = record.build_authority.source_nar_hash;
        };

        build-system = [
          pythonPackages.setuptools
          pythonPackages.torch
        ];

        nativeBuildInputs = [
          cudaPackages.cuda_nvcc
          pkgs.ninja
        ];

        buildInputs = [
          pythonPackages.pybind11
          pkgs.rdma-core
          ncclRoot
          cudaPackages.libnvshmem
          cudaPackages.cccl
          cudaPackages.cuda_cudart
          cudaPackages.libcublas
          cudaPackages.libcusolver
          cudaPackages.libcusparse
        ]
        ++ pkgs.lib.optionals cudaPackages.cuda_crt.meta.available [ cudaPackages.cuda_crt ];

        dependencies = [ pythonPackages.torch ];

        env = {
          CUDA_HOME = pkgs.lib.getBin cudaPackages.cuda_nvcc;
          EP_NCCL_ROOT_DIR = ncclRoot;
          NVSHMEM_DIR = nvshmemRoot;
          TORCH_CUDA_ARCH_LIST = builtins.concatStringsSep " " cudaCapabilities;
        };

        # These are Nix layout adaptations, not patches to DeepEP or NVSHMEM behavior.
        postPatch = ''
          substituteInPlace setup.py \
            --replace-fail "'/usr/local/cuda/include/cccl'" "'${pkgs.lib.getInclude cudaPackages.cccl}/include/cccl'" \
            --replace-fail "revision = '+local'" "revision = '+${
              builtins.substring 0 7 record.upstream.revision
            }'"
        '';

        # Upstream tests require a distributed GPU runtime and are exercised by the
        # explicitly activated qualification commands rather than the Nix sandbox.
        doCheck = false;
        pythonImportsCheck = [ "deep_ep" ];

        meta = {
          changelog = "https://github.com/deepseek-ai/DeepEP/commit/${record.upstream.revision}";
          description = "Modern DeepEP v2 expert-parallel communication library";
          homepage = record.upstream.repository;
          license = pkgs.lib.licenses.mit;
          platforms = pkgs.lib.platforms.linux;
          broken = !pkgs.config.cudaSupport;
        };
      };
in
assert record.status == "intake-only";
assert record.upstream.version_line == "2.x";
assert record.build_authority.definition == "third_party/packages/deep_ep/package.nix";
assert record.build_authority.flake_input == "nixpkgs";
assert record.build_authority.nixpkgs_revision == nixpkgsRevision;
assert record.build_authority.package == "packages.deep-ep";
assert record.build_authority.version == package.version;
assert record.build_authority.source_nar_hash == package.src.outputHash;
assert record.build_authority.runtime_profile.cuda == cudaPackages.cudaMajorMinorVersion;
assert record.build_authority.runtime_profile.nccl == cudaPackages.nccl.version;
assert record.build_authority.runtime_profile.nvcc == cudaPackages.cuda_nvcc.version;
assert record.build_authority.runtime_profile.nvshmem == cudaPackages.libnvshmem.version;
assert record.build_authority.runtime_profile.python == pkgs.python312.version;
assert record.build_authority.runtime_profile.torch == pythonPackages.torch.version;
assert pkgs.lib.versionAtLeast cudaPackages.nccl.version record.vllm_compatibility.minimum_nccl;
assert pkgs.lib.versionAtLeast cudaPackages.libnvshmem.version "3.3.9";
assert builtins.all (capability: pkgs.lib.versionAtLeast capability "9.0") cudaCapabilities;
{
  inherit package record;
  runtime = {
    cudaHome = pkgs.lib.getBin cudaPackages.cuda_nvcc;
    jitNvcc = "${pkgs.lib.getBin cudaPackages.cuda_nvcc}/bin/nvcc";
    inherit ncclRoot nvshmemRoot;
  };
}
