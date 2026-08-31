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
  basePackage = pythonPackages.deep-ep.override {
    inherit cudaCapabilities;
  };
  package = basePackage.overrideAttrs (previous: {
    version = record.build_authority.version;

    src = pkgs.fetchFromGitHub {
      owner = "deepseek-ai";
      repo = "DeepEP";
      rev = record.upstream.revision;
      fetchSubmodules = true;
      hash = record.build_authority.source_nar_hash;
    };

    env = previous.env // {
      CUDA_HOME = pkgs.lib.getBin cudaPackages.cuda_nvcc;
      EP_NCCL_ROOT_DIR = ncclRoot;
      NVSHMEM_DIR = nvshmemRoot;
      TORCH_CUDA_ARCH_LIST = builtins.concatStringsSep " " cudaCapabilities;
    };

    buildInputs = (previous.buildInputs or [ ]) ++ [ ncclRoot ];
    dependencies = (previous.dependencies or [ ]) ++ [ pythonPackages.torch ];

    # These are Nix layout adaptations, not patches to DeepEP or NVSHMEM behavior.
    postPatch = (previous.postPatch or "") + ''
      substituteInPlace setup.py \
        --replace-fail "'/usr/local/cuda/include/cccl'" "'${pkgs.lib.getInclude cudaPackages.cccl}/include/cccl'" \
        --replace-fail "revision = '+local'" "revision = '+${
          builtins.substring 0 7 record.upstream.revision
        }'"
    '';

    meta = previous.meta // {
      changelog = "https://github.com/deepseek-ai/DeepEP/commit/${record.upstream.revision}";
      description = "Modern DeepEP v2 expert-parallel communication library";
    };
  });
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
assert record.build_authority.runtime_profile.nvshmem == cudaPackages.libnvshmem.version;
assert record.build_authority.runtime_profile.python == pkgs.python312.version;
assert record.build_authority.runtime_profile.torch == pythonPackages.torch.version;
assert pkgs.lib.versionAtLeast cudaPackages.nccl.version record.vllm_compatibility.minimum_nccl;
assert pkgs.lib.versionAtLeast cudaPackages.libnvshmem.version "3.3.9";
{
  inherit package record;
  runtime = {
    cudaHome = pkgs.lib.getBin cudaPackages.cuda_nvcc;
    jitNvcc = "${pkgs.lib.getBin cudaPackages.cuda_nvcc}/bin/nvcc";
    inherit ncclRoot nvshmemRoot;
  };
}
