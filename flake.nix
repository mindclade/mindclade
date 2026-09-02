{
  description = "Pinned Wave 0 development environment for github.com/mindclade/mindclade";

  nixConfig = {
    substituters = [ "https://cache.nixos.org/" ];
    trusted-public-keys = [ "cache.nixos.org-1:6NCHdD59X431o0gWypbMrAURkbJ16ZPMQFGspcDShjY=" ];
    require-sigs = true;
  };

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/83199d0d373dd3ac2b9a1996b1d0263f76ab7a4c";

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
      basePackageSet =
        pkgs:
        let
          system = pkgs.stdenv.hostPlatform.system;
          locale = if pkgs.stdenv.hostPlatform.isDarwin then "en_US.UTF-8" else "C.UTF-8";
          pythonEnv = pkgs.python312.withPackages (
            pythonPackages: with pythonPackages; [
              cryptography
              jsonschema
              pyyaml
            ]
          );
          pnpmNode26 = pkgs.pnpm.override { nodejs-slim = pkgs.nodejs_26; };
          bazelRuntimeInputs =
            with pkgs;
            [
              bash
              bazel_9
              bzip2
              cacert
              coreutils
              curl
              diffutils
              file
              findutils
              gawk
              git
              gnugrep
              gnumake
              gnused
              gnutar
              gzip
              jdk21_headless
              jq
              openssl.bin
              openssh
              patch
              stdenv.cc
              unzip
              which
              xz
              zip
            ]
            ++ lib.optionals stdenv.hostPlatform.isDarwin [
              darwin.cctools
              darwin.cctools.libtool
            ];
          bazel = pkgs.writeShellApplication {
            name = "bazel";
            runtimeInputs = bazelRuntimeInputs;
            text = ''
              export PATH=${pkgs.lib.makeBinPath bazelRuntimeInputs}
              export JAVA_HOME=${pkgs.jdk21_headless}
              export CC=${pkgs.stdenv.cc}/bin/cc
              export CXX=${pkgs.stdenv.cc}/bin/c++
              export BAZEL_LINKOPTS=${pkgs.lib.escapeShellArg (pkgs.lib.optionalString pkgs.stdenv.hostPlatform.isDarwin "-L${pkgs.darwin.libresolv}/lib")}
              export LANG=C
              export LC_ALL=C
              export TZ=UTC
              export MINDCLADE_NIX_BIN=${pkgs.nix}/bin/nix
              if [[ "''${1:-}" == "--version" ]]; then
                printf 'bazel %s\n' '${pkgs.bazel_9.version}'
                exit 0
              fi
              startup_flags=(--nosystem_rc --nohome_rc --server_javabase=${pkgs.jdk21_headless})
              if [[ -n "''${BAZEL_OUTPUT_USER_ROOT:-}" ]]; then
                startup_flags+=(--output_user_root="''${BAZEL_OUTPUT_USER_ROOT}")
              fi
              exec ${pkgs.bazel_9}/bin/bazel "''${startup_flags[@]}" "$@"
            '';
          };
          toolchainManifest = pkgs.writeTextDir "share/mindclade/toolchain-manifest.json" (
            builtins.toJSON {
              schema_version = "mindclade-toolchain.v1";
              repository = "mindclade/mindclade";
              inherit system;
              nixpkgs = {
                revision = nixpkgs.rev;
                nar_hash = nixpkgs.narHash;
              };
              flake_lock_sha256 = builtins.hashFile "sha256" "${self}/flake.lock";
              module_lock_sha256 = builtins.hashFile "sha256" "${self}/MODULE.bazel.lock";
              bazel = {
                version = pkgs.bazel_9.version;
                store_path = "${pkgs.bazel_9}";
              };
              startup_jdk = {
                version = pkgs.jdk21_headless.version;
                store_path = "${pkgs.jdk21_headless}";
              };
              native_cc_store_path = "${pkgs.stdenv.cc}";
              rust = {
                version = pkgs.rustc.version;
                store_path = "${pkgs.rustc}";
              };
            }
          );
          toolchainPackages = with pkgs; [
            actionlint
            bazel
            buf
            buildifier
            cargo
            clippy
            gitleaks
            git
            go_1_26
            golangci-lint
            jdk21_headless
            jq
            just
            markdownlint-cli2
            nixfmt
            nodejs_26
            pnpmNode26
            pre-commit
            pyright
            pythonEnv
            ruff
            rustc
            rustfmt
            shellcheck
            shfmt
            stdenv.cc
            toolchainManifest
            uv
            yamllint
          ];
          toolchain = pkgs.buildEnv {
            name = "mindclade-toolchain";
            paths = toolchainPackages;
            pathsToLink = [
              "/bin"
              "/share/mindclade"
            ];
            ignoreCollisions = false;
          };
        in
        {
          inherit
            locale
            pythonEnv
            toolchain
            toolchainManifest
            toolchainPackages
            ;
        };
      baseShells = forAllSystems (
        pkgs:
        let
          current = basePackageSet pkgs;
          common = {
            packages = [ current.toolchain ];
            JAVA_HOME = "${pkgs.jdk21_headless}";
            CC = "${pkgs.stdenv.cc}/bin/cc";
            CXX = "${pkgs.stdenv.cc}/bin/c++";
            LANG = current.locale;
            LC_ALL = current.locale;
            TZ = "UTC";
            UV_PROJECT_ENVIRONMENT = ".venv";
            shellHook = ''
              # mkShell preserves parts of the invoking PATH on some hosts.
              # Reassert the repository closure first so Homebrew/rustup cannot
              # silently replace a pinned compiler or package manager.
              export PATH="${current.toolchain}/bin:${current.pythonEnv}/bin:$PATH"
              export MINDCLADE_REPOSITORY_ROOT="$PWD"
              echo "Mindclade Wave 0 shell — run: just bootstrap && just doctor"
            '';
          };
        in
        {
          default = pkgs.mkShell common;
          ci = pkgs.mkShell (common // { CI = "true"; });
        }
      );
      gpuShells = forGpuSystems (
        pkgs:
        let
          base = basePackageSet pkgs;
          deepEp = deepEpPackageSet pkgs;
          deepEpPackage = deepEp.package;
          deepEpJitFingerprint = deepEp.runtime.fingerprint;
          deepEpJitFingerprintId = pkgs.lib.removePrefix "sha256:" deepEpJitFingerprint;
          pythonEnv = pkgs.python312.withPackages (pythonPackages: [
            pythonPackages.cryptography
            deepEpPackage
            pythonPackages.jsonschema
            pythonPackages.pyyaml
            pythonPackages.torch
          ]);
          deepEpShell = pkgs.mkShell {
            packages = with pkgs; [
              base.toolchain
              cmake
              cudaPackages.cuda_cuobjdump
              cudaPackages.cuda_nvcc
              cudaPackages.libnvshmem
              ninja
              patchelf
              pythonEnv
              rdma-core
            ];

            CUDA_HOME = deepEp.runtime.cudaHome;
            CUDA_PATH = deepEp.runtime.cudaHome;
            EP_JIT_NVCC_COMPILER = deepEp.runtime.jitNvcc;
            EP_NCCL_ROOT_DIR = deepEp.runtime.ncclRoot;
            MINDCLADE_DEEPEP_JIT_FINGERPRINT = deepEpJitFingerprint;
            MINDCLADE_DEEPEP_PACKAGE_ROOT = deepEpPackage;
            MINDCLADE_DEEPEP_RUNTIME_MANIFEST = deepEp.runtimeManifest;
            NVSHMEM_DIR = deepEp.runtime.nvshmemRoot;
            TORCH_CUDA_ARCH_LIST = builtins.concatStringsSep " " deepEp.record.build_authority.cuda_capabilities;
            LANG = base.locale;
            LC_ALL = base.locale;
            PYTHONNOUSERSITE = "1";
            SOURCE_DATE_EPOCH = "1";
            TZ = "UTC";
            UV_PROJECT_ENVIRONMENT = ".venv";

            shellHook = ''
              export PATH="${base.toolchain}/bin:${pythonEnv}/bin:$PATH"
              export MINDCLADE_REPOSITORY_ROOT="$PWD"
              export EP_JIT_CACHE_DIR="$PWD/.cache/deepep/jit/${deepEpJitFingerprintId}"
              echo "Mindclade SM90 GPU intake shell — modern DeepEP 2.x; no production authority"
            '';
          };
        in
        {
          deepep = deepEpShell;
          gpu = deepEpShell;
        }
      );
      gpuPackages = forGpuSystems (
        pkgs:
        let
          deepEp = deepEpPackageSet pkgs;
        in
        {
          deep-ep = deepEp.runtimeEnvironment;
          deep-ep-python-package = deepEp.package;
          deep-ep-runtime-manifest = deepEp.runtimeManifest;
        }
        // pkgs.lib.optionalAttrs (deepEp.closureWheel != null) {
          deep-ep-artifacts = deepEp.artifactBundle;
          deep-ep-wheel = deepEp.closureWheel;
          deep-ep-wheel-runtime-manifest = deepEp.wheelRuntimeManifest;
        }
      );
      gpuChecks = forGpuSystems (
        pkgs:
        let
          deepEp = deepEpPackageSet pkgs;
        in
        {
          deep-ep-standalone-import = deepEp.standaloneImportTest;
        }
        // pkgs.lib.optionalAttrs (deepEp.artifactBundle != null) {
          deep-ep-artifact-bundle = deepEp.artifactBundle;
        }
      );
    in
    {
      devShells = builtins.mapAttrs (system: shells: shells // (gpuShells.${system} or { })) baseShells;

      packages =
        builtins.mapAttrs (system: basePackages: basePackages // (gpuPackages.${system} or { }))
          (
            forAllSystems (
              pkgs:
              let
                current = basePackageSet pkgs;
              in
              {
                default = current.toolchain;
                toolchain = current.toolchain;
                "toolchain-manifest" = current.toolchainManifest;
              }
            )
          );

      checks = builtins.mapAttrs (system: baseChecks: baseChecks // (gpuChecks.${system} or { })) (
        forAllSystems (
          pkgs:
          let
            current = basePackageSet pkgs;
          in
          {
            toolchain =
              pkgs.runCommand "mindclade-toolchain-check"
                {
                  nativeBuildInputs = [ current.toolchain ];
                }
                ''
                  set -euo pipefail
                  command -v bazel buildifier buf cargo go jq just nixfmt node pnpm python3 rustc uv >/dev/null
                  test "$(bazel --version)" = "bazel 9.1.1"
                  test "$(rustc --version | cut -d' ' -f2)" = '${pkgs.rustc.version}'
                  jq -e '.schema_version == "mindclade-toolchain.v1" and .bazel.version == "9.1.1" and .rust.version == "${pkgs.rustc.version}"' \
                    ${current.toolchain}/share/mindclade/toolchain-manifest.json >/dev/null
                  mkdir -p "$out"
                  cp ${current.toolchain}/share/mindclade/toolchain-manifest.json "$out/"
                '';
            source =
              pkgs.runCommand "mindclade-source-check"
                {
                  nativeBuildInputs = [ current.toolchain ];
                }
                ''
                  set -euo pipefail
                  export HOME="$TMPDIR/home"
                  mkdir -p "$HOME" "$out"
                  cd ${self}
                  python3 ${self}/tools/docs/validate_blueprint_sources.py \
                    --manifest ${self}/docs/architecture/blueprint/manifest.yaml
                  python3 ${self}/tools/docs/render_architecture_blueprint.py \
                    --manifest ${self}/docs/architecture/blueprint/manifest.yaml --check
                  python3 -m unittest discover -s ${self}/tools/repo/tests -p 'test_*.py'
                  touch "$out/passed"
                '';
          }
        )
      );

      formatter = forAllSystems (pkgs: pkgs.nixfmt);
    };
}
