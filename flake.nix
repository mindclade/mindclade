{
  description = "Pinned Wave 0 development environment for github.com/mindclade/mindclade";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs =
    { self, nixpkgs }:
    let
      systems = [
        "aarch64-darwin"
        "aarch64-linux"
        "x86_64-linux"
      ];
      gpuSystems = [
        "aarch64-linux"
        "x86_64-linux"
      ];
      forSystems =
        targetSystems: nixpkgsConfig: function:
        builtins.listToAttrs (
          map (system: {
            name = system;
            value = function (
              import nixpkgs {
                inherit system;
                config = nixpkgsConfig;
              }
            );
          }) targetSystems
        );
      forAllSystems = forSystems systems { };
      forGpuSystems = forSystems gpuSystems {
        allowUnfree = true;
        cudaSupport = true;
      };
      deepEpPackageSet =
        pkgs:
        import ./third_party/packages/deep_ep/package.nix {
          inherit pkgs;
          nixpkgsRevision = nixpkgs.rev;
        };
      baseShells = forAllSystems (
        pkgs:
        let
          pythonEnv = pkgs.python312.withPackages (
            pythonPackages: with pythonPackages; [
              cryptography
              jsonschema
            ]
          );
          pnpmNode26 = pkgs.pnpm.override { nodejs-slim = pkgs.nodejs_26; };
        in
        {
          default = pkgs.mkShell {
            packages = with pkgs; [
              actionlint
              bazel_9
              buf
              cargo
              gitleaks
              git
              go_1_26
              jq
              just
              markdownlint-cli2
              nodejs_26
              pnpmNode26
              pre-commit
              pyright
              pythonEnv
              rustc
              ruff
              uv
              yamllint
            ];

            LANG = "C";
            LC_ALL = "C";
            TZ = "UTC";
            UV_PROJECT_ENVIRONMENT = ".venv";

            shellHook = ''
              export PATH="${pythonEnv}/bin:$PATH"
              export MINDCLADE_REPOSITORY_ROOT="$PWD"
              echo "Mindclade Wave 0 shell — run: just bootstrap && just doctor"
            '';
          };
        }
      );
      gpuShells = forGpuSystems (
        pkgs:
        let
          deepEp = deepEpPackageSet pkgs;
          deepEpPackage = deepEp.package;
          pythonEnv = pkgs.python312.withPackages (pythonPackages: [
            pythonPackages.cryptography
            deepEpPackage
            pythonPackages.jsonschema
            pythonPackages.torch
          ]);
          pnpmNode26 = pkgs.pnpm.override { nodejs-slim = pkgs.nodejs_26; };
        in
        {
          gpu = pkgs.mkShell {
            packages = with pkgs; [
              actionlint
              bazel_9
              buf
              cargo
              cmake
              cudaPackages.cuda_nvcc
              cudaPackages.libnvshmem
              gitleaks
              git
              go_1_26
              jq
              just
              markdownlint-cli2
              ninja
              nodejs_26
              pnpmNode26
              pre-commit
              pyright
              pythonEnv
              rdma-core
              rustc
              ruff
              uv
              yamllint
            ];

            CUDA_HOME = deepEp.runtime.cudaHome;
            EP_JIT_NVCC_COMPILER = deepEp.runtime.jitNvcc;
            EP_NCCL_ROOT_DIR = deepEp.runtime.ncclRoot;
            NVSHMEM_DIR = deepEp.runtime.nvshmemRoot;
            TORCH_CUDA_ARCH_LIST = builtins.concatStringsSep " " deepEp.record.build_authority.cuda_capabilities;
            LANG = "C";
            LC_ALL = "C";
            TZ = "UTC";
            UV_PROJECT_ENVIRONMENT = ".venv";

            shellHook = ''
              export PATH="${pythonEnv}/bin:$PATH"
              export MINDCLADE_REPOSITORY_ROOT="$PWD"
              echo "Mindclade SM90 GPU intake shell — modern DeepEP 2.x; no production authority"
            '';
          };
        }
      );
    in
    {
      devShells = builtins.mapAttrs (system: shells: shells // (gpuShells.${system} or { })) baseShells;

      packages = forGpuSystems (
        pkgs:
        let
          deepEpPackage = (deepEpPackageSet pkgs).package;
        in
        {
          deep-ep = deepEpPackage;
        }
      );

      formatter = forAllSystems (pkgs: pkgs.nixfmt);
    };
}
