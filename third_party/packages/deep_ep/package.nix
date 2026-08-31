{
  pkgs,
  nixpkgsRevision,
}:
let
  lib = pkgs.lib;
  sourceLockPath = ../../source_mirrors/sources.lock.json;
  patchLockPath = ../../patches/patches.lock.json;
  sourceLock = builtins.fromJSON (builtins.readFile sourceLockPath);
  patchLock = builtins.fromJSON (builtins.readFile patchLockPath);
  records = builtins.filter (entry: entry.name == "deep-ep") sourceLock.entries;
  record =
    assert builtins.length records == 1;
    builtins.head records;
  patchEntries = builtins.filter (entry: entry.applies_to.name == "deep-ep") patchLock.entries;
  cudaCapabilities = record.build_authority.cuda_capabilities;
  cudaPackages = pkgs.cudaPackages;
  pythonPackages = pkgs.python312Packages;
  digestFile = path: "sha256:${builtins.hashFile "sha256" path}";
  derivationIdentity = value: builtins.unsafeDiscardStringContext value.drvPath;
  patchPaths = [
    ../../patches/deep_ep/declared-toolchain-paths.patch
    ../../patches/deep_ep/deterministic-version.patch
    ../../patches/deep_ep/gin-attestation.patch
    ../../patches/deep_ep/runtime-jit-cache.patch
  ];
  lockedPatchPaths = map (entry: entry.path) patchEntries;
  repositoryPatchPath = path: "third_party/patches/deep_ep/${builtins.baseNameOf path}";
  matchingPatchEntry =
    path:
    let
      matches = builtins.filter (entry: entry.path == repositoryPatchPath path) patchEntries;
    in
    assert builtins.length matches == 1;
    builtins.head matches;
  patchDigestsValid = builtins.all (
    path: (matchingPatchEntry path).sha256 == digestFile path
  ) patchPaths;
  cudaToolkitRoot = pkgs.symlinkJoin {
    name = "deepep-cuda-toolkit-${cudaPackages.cuda_nvcc.version}";
    paths = [
      cudaPackages.cuda_nvcc
      cudaPackages.cuda_cuobjdump
      cudaPackages.cuda_cudart
      cudaPackages.cccl
    ]
    ++ lib.optionals cudaPackages.cuda_crt.meta.available [ cudaPackages.cuda_crt ];
  };
  nvshmemRoot = pkgs.symlinkJoin {
    name = "deepep-nvshmem-${cudaPackages.libnvshmem.version}";
    paths = [
      (lib.getBin cudaPackages.libnvshmem)
      (lib.getDev cudaPackages.libnvshmem)
      (lib.getLib cudaPackages.libnvshmem)
    ];
  };
  ncclRoot = pkgs.symlinkJoin {
    name = "deepep-nccl-${cudaPackages.nccl.version}";
    paths = [
      (lib.getDev cudaPackages.nccl)
      (lib.getLib cudaPackages.nccl)
    ];
  };
  storeOutputs = {
    cuda_home = "${cudaToolkitRoot}";
    nccl = "${ncclRoot}";
    nvcc = "${cudaPackages.cuda_nvcc}";
    nvshmem = "${nvshmemRoot}";
    python = "${pkgs.python312}";
    torch = "${pythonPackages.torch}";
  };
  locks = {
    flake = digestFile ../../../flake.lock;
    package_definition = digestFile ./package.nix;
    patches = digestFile patchLockPath;
    python = digestFile ../../../uv.lock;
    sources = digestFile sourceLockPath;
  };
  sourceComponents = map (component: {
    name = builtins.baseNameOf component.path;
    inherit (component) revision;
    license = component.license.spdx;
  }) record.submodules;
  mkRuntimeManifest =
    mode: requirements:
    let
      fingerprintInputs = {
        schema_version = "mindclade.deepep-runtime-fingerprint/v2";
        artifact = {
          archive_sha256 = record.archive.sha256;
          source_nar_hash = record.build_authority.source_nar_hash;
          upstream_commit = record.upstream.revision;
          version = record.build_authority.version;
          components = sourceComponents;
        };
        build = {
          cuda_capabilities = cudaCapabilities;
          target_system = pkgs.stdenv.hostPlatform.system;
          variant = "v2-nccl-gin";
        };
        distribution = {
          inherit mode requirements;
        };
        inherit locks;
        nix = {
          nixpkgs_revision = nixpkgsRevision;
          derivations = {
            cuda = derivationIdentity cudaToolkitRoot;
            nccl = derivationIdentity ncclRoot;
            nvcc = derivationIdentity cudaPackages.cuda_nvcc;
            nvshmem = derivationIdentity nvshmemRoot;
            python = derivationIdentity pkgs.python312;
            torch = derivationIdentity pythonPackages.torch;
          };
          store_outputs = storeOutputs;
        };
        patches = map (entry: {
          inherit (entry) name path sha256;
        }) patchEntries;
        runtime_profile = record.build_authority.runtime_profile;
      };
      fingerprint = "sha256:${builtins.hashString "sha256" (builtins.toJSON fingerprintInputs)}";
      value = {
        schema_version = "mindclade.deepep-runtime-manifest/v2";
        production_authority = false;
        artifact = {
          name = "deep-ep";
          archive_sha256 = record.archive.sha256;
          source_nar_hash = record.build_authority.source_nar_hash;
          upstream_commit = record.upstream.revision;
          version = record.build_authority.version;
          components = sourceComponents;
        };
        build = fingerprintInputs.build;
        distribution = fingerprintInputs.distribution;
        fingerprint = {
          algorithm = "sha256";
          value = fingerprint;
        };
        fingerprint_inputs = fingerprintInputs;
        inherit locks;
        runtime_profile = record.build_authority.runtime_profile;
        toolchain = {
          cuda_home = "${cudaToolkitRoot}";
          nccl_root = "${ncclRoot}";
          nvcc = "${cudaToolkitRoot}/bin/nvcc";
          nvshmem_root = "${nvshmemRoot}";
          store_outputs = storeOutputs;
        };
      };
    in
    {
      inherit fingerprint value;
      file = pkgs.writeText "deep-ep-runtime-manifest-${mode}.json" (builtins.toJSON value + "\n");
    };
  nixRuntime = mkRuntimeManifest "hermetic-nix" [ ];
  wheelRuntime = mkRuntimeManifest "nix-closure" [ ];
  wheelRequirementLock = pkgs.writeText "deep-ep-wheel-requirements.json" (
    builtins.toJSON {
      requirements = [ ];
      schema_version = "mindclade.deepep-wheel-requirements/v1";
    }
    + "\n"
  );
  source = pkgs.fetchFromGitHub {
    owner = "deepseek-ai";
    repo = "DeepEP";
    rev = record.upstream.revision;
    fetchSubmodules = true;
    hash = record.build_authority.source_nar_hash;
  };
  mkDeepEp =
    {
      persistToolchainPaths,
      runtimeManifest,
      importsCheck,
    }:
    pythonPackages.buildPythonPackage.override
      {
        inherit (pythonPackages.torch) stdenv;
      }
      {
        pname = "deep-ep";
        version = record.build_authority.version;
        pyproject = true;
        strictDeps = true;

        src = source;
        patches = patchPaths;

        build-system = [
          pythonPackages.setuptools
          pythonPackages.torch
        ];

        nativeBuildInputs = [
          cudaPackages.cuda_nvcc
          pkgs.ninja
          pkgs.patchelf
        ];

        buildInputs = [
          pythonPackages.pybind11
          pkgs.rdma-core
          ncclRoot
          nvshmemRoot
          cudaPackages.cccl
          cudaPackages.cuda_cudart
          cudaPackages.libcublas
          cudaPackages.libcusolver
          cudaPackages.libcusparse
        ]
        ++ lib.optionals cudaPackages.cuda_crt.meta.available [ cudaPackages.cuda_crt ];

        dependencies = [ pythonPackages.torch ];
        propagatedBuildInputs = [
          cudaToolkitRoot
          ncclRoot
          nvshmemRoot
        ];

        env = {
          CUDA_HOME = cudaToolkitRoot;
          CUDA_PATH = cudaToolkitRoot;
          EP_JIT_NVCC_COMPILER = "${cudaToolkitRoot}/bin/nvcc";
          EP_NCCL_ROOT_DIR = ncclRoot;
          EP_NVSHMEM_ROOT_DIR = nvshmemRoot;
          MINDCLADE_DEEPEP_PERSIST_TOOLCHAIN_PATHS = if persistToolchainPaths then "1" else "0";
          MINDCLADE_DEEPEP_SOURCE_REVISION = record.upstream.revision;
          NVSHMEM_DIR = nvshmemRoot;
          TORCH_CUDA_ARCH_LIST = builtins.concatStringsSep " " cudaCapabilities;
        };

        postPatch = ''
          substituteInPlace setup.py \
            --replace-fail "'/usr/local/cuda/include/cccl'" "'${lib.getInclude cudaPackages.cccl}/include/cccl'"
        '';

        postInstall = ''
          install -Dm0444 ${runtimeManifest} \
            "$out/${pythonPackages.python.sitePackages}/deep_ep/mindclade-runtime.json"
        '';

        doCheck = false;
        pythonImportsCheck = lib.optionals importsCheck [ "deep_ep" ];

        meta = {
          changelog = "https://github.com/deepseek-ai/DeepEP/commit/${record.upstream.revision}";
          description = "Modern DeepEP v2 expert-parallel communication library";
          homepage = record.upstream.repository;
          license = lib.licenses.mit;
          platforms = lib.platforms.linux;
          broken = !pkgs.config.cudaSupport;
        };
      };
  package = mkDeepEp {
    persistToolchainPaths = true;
    runtimeManifest = nixRuntime.file;
    importsCheck = true;
  };
  pythonRuntime = pkgs.python312.withPackages (_: [ package ]);
  runtimeEnvironment = pkgs.buildEnv {
    name = "deep-ep-runtime-${package.version}";
    paths = [
      pythonRuntime
      cudaToolkitRoot
      ncclRoot
      nvshmemRoot
    ];
  };
  closureWheel =
    if pkgs.stdenv.hostPlatform.system == "x86_64-linux" then
      pkgs.runCommand "deep-ep-closure-wheel-${record.build_authority.version}"
        {
          nativeBuildInputs = [
            pkgs.binutils
            pkgs.patchelf
            pkgs.python312
          ];
        }
        ''
          raw_wheel="$(find ${package.dist} -maxdepth 1 -type f -name '*.whl' -print -quit)"
          test -n "$raw_wheel"
          mkdir -p "$out"
          ${pkgs.python312}/bin/python ${./artifact_contract.py} normalize-wheel \
            --input "$raw_wheel" \
            --output "$out/$(basename "$raw_wheel")" \
            --runtime-manifest ${wheelRuntime.file} \
            --requirements ${wheelRequirementLock} \
            --patchelf ${pkgs.patchelf}/bin/patchelf \
            --strip ${pkgs.binutils}/bin/strip \
            --elf-manifest "$out/elf-dependencies.json"
        ''
    else
      null;
  closure = pkgs.closureInfo { rootPaths = [ runtimeEnvironment ]; };
  artifactBundle =
    if closureWheel == null then
      null
    else
      pkgs.runCommand "deep-ep-artifacts-${record.build_authority.version}"
        { nativeBuildInputs = [ pkgs.python312 ]; }
        ''
          wheel="$(find ${closureWheel} -maxdepth 1 -type f -name '*.whl' -print -quit)"
          test -n "$wheel"
          ${pkgs.python312}/bin/python ${./artifact_contract.py} bundle \
            --wheel "$wheel" \
            --runtime-manifest ${wheelRuntime.file} \
            --elf-manifest ${closureWheel}/elf-dependencies.json \
            --package ${runtimeEnvironment} \
            --package-drv ${derivationIdentity runtimeEnvironment} \
            --closure-paths ${closure}/store-paths \
            --output "$out"
        '';
  standaloneImportTest =
    pkgs.runCommand "deep-ep-standalone-import-${package.version}"
      {
        nativeBuildInputs = [ runtimeEnvironment ];
      }
      ''
        export HOME="$TMPDIR/home"
        mkdir -p "$HOME"
        export PYTHONNOUSERSITE=1
        python -c 'import json, os, pathlib, deep_ep; manifest=json.loads((pathlib.Path(deep_ep.__file__).parent / "mindclade-runtime.json").read_text()); assert deep_ep.__version__ == manifest["artifact"]["version"]; assert pathlib.Path(os.environ["EP_JIT_NVCC_COMPILER"]).is_file()'
        touch "$out"
      '';
in
assert sourceLock.schema_version == "mindclade.third-party-source-mirrors/v2";
assert patchLock.schema_version == "mindclade.third-party-patches/v2";
assert record.status == "intake-only";
assert record.review_reference == "docs/adr/0013-deepep-package-and-qualification-boundary.md";
assert record.upstream.version_line == "2.x";
assert record.build_authority.definition == "third_party/packages/deep_ep/package.nix";
assert record.build_authority.flake_input == "nixpkgs";
assert record.build_authority.nixpkgs_revision == nixpkgsRevision;
assert record.build_authority.package == "packages.deep-ep";
assert record.build_authority.artifact_bundle == "packages.deep-ep-artifacts";
assert record.build_authority.version == package.version;
assert record.build_authority.source_nar_hash == source.outputHash;
assert builtins.length patchEntries == builtins.length patchPaths;
assert builtins.all (path: builtins.elem (repositoryPatchPath path) lockedPatchPaths) patchPaths;
assert patchDigestsValid;
assert record.build_authority.runtime_profile.cuda == cudaPackages.cudaMajorMinorVersion;
assert record.build_authority.runtime_profile.nccl == cudaPackages.nccl.version;
assert record.build_authority.runtime_profile.nvcc == cudaPackages.cuda_nvcc.version;
assert record.build_authority.runtime_profile.nvshmem == cudaPackages.libnvshmem.version;
assert record.build_authority.runtime_profile.python == pkgs.python312.version;
assert record.build_authority.runtime_profile.torch == pythonPackages.torch.version;
assert lib.versionAtLeast cudaPackages.nccl.version record.vllm_compatibility.minimum_nccl;
assert lib.versionAtLeast cudaPackages.libnvshmem.version "3.3.9";
assert builtins.all (capability: lib.versionAtLeast capability "9.0") cudaCapabilities;
{
  inherit
    artifactBundle
    closureWheel
    package
    record
    runtimeEnvironment
    standaloneImportTest
    ;
  runtimeManifest = nixRuntime.file;
  wheelRuntimeManifest = wheelRuntime.file;
  runtime = {
    cudaHome = cudaToolkitRoot;
    fingerprint = nixRuntime.fingerprint;
    jitNvcc = "${cudaToolkitRoot}/bin/nvcc";
    inherit ncclRoot nvshmemRoot;
  };
}
