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
      estatePolicy = import ./generated/nix-bazel-policy.nix;
      systems = estatePolicy.spec.systems;
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
              go_1_26
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
              pythonEnv
              stdenv.cc
              unzip
              which
              xz
              zip
            ]
            ++ lib.optionals stdenv.hostPlatform.isDarwin [
              apple-sdk
              darwin.cctools
              libiconv
            ];
          bazel = pkgs.writeShellApplication {
            name = "bazel";
            runtimeInputs = bazelRuntimeInputs;
            text = ''
              export PATH=${pkgs.lib.makeBinPath bazelRuntimeInputs}
              export JAVA_HOME=${pkgs.jdk21_headless}
              export GOROOT=${pkgs.go_1_26}/share/go
              export CC=${pkgs.stdenv.cc}/bin/cc
              export CXX=${pkgs.stdenv.cc}/bin/c++
              export SDKROOT=${
                pkgs.lib.escapeShellArg (if pkgs.stdenv.hostPlatform.isDarwin then pkgs.apple-sdk.sdkroot else "")
              }
              export BAZEL_LINKOPTS=${pkgs.lib.escapeShellArg (pkgs.lib.optionalString pkgs.stdenv.hostPlatform.isDarwin "-L${pkgs.darwin.libresolv}/lib:-L${pkgs.libiconv}/lib")}
              export LANG=C
              export LC_ALL=C
              export TZ=UTC
              export MINDCLADE_NIX_BIN=${pkgs.nix}/bin/nix
              export MINDCLADE_TOOLCHAIN_MANIFEST=${toolchainManifest}/share/mindclade/toolchain-manifest.json
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
          toolchainManifest =
            pkgs.runCommand "mindclade-toolchain-manifest-v2"
              {
                nativeBuildInputs = [
                  pkgs.coreutils
                  pkgs.jq
                ];
              }
              ''
                set -euo pipefail
                mkdir -p "$out/share/mindclade"
                record() {
                  local path="$1" store_path="$2" version="$3"
                  local sha256
                  sha256="$(sha256sum "$path" | cut -d' ' -f1)"
                  jq -cn \
                    --arg path "$path" \
                    --arg sha256 "sha256:$sha256" \
                    --arg store_path "$store_path" \
                    --arg version "$version" \
                    '{path:$path,sha256:$sha256,store_path:$store_path,version:$version}'
                }
                bazel_json="$(record ${pkgs.bazel_9}/bin/bazel ${pkgs.bazel_9} ${pkgs.bazel_9.version})"
                cargo_json="$(record ${pkgs.cargo}/bin/cargo ${pkgs.cargo} ${pkgs.cargo.version})"
                cc_json="$(record ${
                  if pkgs.stdenv.hostPlatform.isDarwin then
                    "${pkgs.stdenv.cc}/bin/clang"
                  else
                    "${pkgs.stdenv.cc}/bin/cc"
                } ${pkgs.stdenv.cc} ${pkgs.stdenv.cc.version})"
                cxx_json="$cc_json"
                go_json="$(record ${pkgs.go_1_26}/share/go/bin/go ${pkgs.go_1_26} ${pkgs.go_1_26.version})"
                java_json="$(record ${pkgs.jdk21_headless}/bin/java ${pkgs.jdk21_headless} ${pkgs.jdk21_headless.version})"
                just_json="$(record ${pkgs.just}/bin/just ${pkgs.just} ${pkgs.just.version})"
                nix_json="$(record ${pkgs.nix}/bin/nix ${pkgs.nix} ${pkgs.nix.version})"
                node_json="$(record ${pkgs.nodejs_26}/bin/node ${pkgs.nodejs_26} ${pkgs.nodejs_26.version})"
                pnpm_json="$(record ${pnpmNode26}/bin/pnpm ${pnpmNode26} ${pnpmNode26.version})"
                python_json="$(record ${pythonEnv}/bin/python3 ${pythonEnv} ${pkgs.python312.version})"
                rustc_json="$(record ${pkgs.rustc}/bin/rustc ${pkgs.rustc} ${pkgs.rustc.version})"
                rustdoc_json="$(record ${pkgs.rustc}/bin/rustdoc ${pkgs.rustc} ${pkgs.rustc.version})"
                unsigned="$TMPDIR/unsigned.json"
                jq -Scn \
                  --arg repository mindclade/mindclade \
                  --arg system ${system} \
                  --arg revision ${nixpkgs.rev} \
                  --arg nar_hash ${nixpkgs.narHash} \
                  --arg flake "sha256:${builtins.hashFile "sha256" "${self}/flake.lock"}" \
                  --arg module "sha256:${builtins.hashFile "sha256" "${self}/MODULE.bazel.lock"}" \
                  --arg policy_lock "sha256:${builtins.hashFile "sha256" "${self}/generated/nix-bazel-policy.lock.json"}" \
                  --arg policy_revision ${estatePolicy.generated.authority_revision} \
                  --arg policy_digest ${estatePolicy.generated.policy_digest} \
                  --argjson bazel "$bazel_json" \
                  --argjson cargo "$cargo_json" \
                  --argjson cc "$cc_json" \
                  --argjson cxx "$cxx_json" \
                  --argjson go "$go_json" \
                  --argjson java "$java_json" \
                  --argjson just "$just_json" \
                  --argjson nix "$nix_json" \
                  --argjson node "$node_json" \
                  --argjson pnpm "$pnpm_json" \
                  --argjson python "$python_json" \
                  --argjson rustc "$rustc_json" \
                  --argjson rustdoc "$rustdoc_json" \
                  '{schema_version:"mindclade-toolchain.v2",repository:$repository,system:$system,policy:{authority_repository:"mindclade/.github",authority_revision:$policy_revision,policy_digest:$policy_digest},nixpkgs:{revision:$revision,nar_hash:$nar_hash},locks:{flake:$flake,module:$module,policy:$policy_lock},executables:{bazel:$bazel,cargo:$cargo,cc:$cc,cxx:$cxx,go:$go,java:$java,just:$just,nix:$nix,node:$node,pnpm:$pnpm,python:$python,rustc:$rustc,rustdoc:$rustdoc}}' \
                  > "$unsigned"
                digest="sha256:$(jq -jSc . "$unsigned" | sha256sum | cut -d' ' -f1)"
                jq -Sc --arg digest "$digest" '. + {toolchain_digest:$digest}' "$unsigned" \
                  > "$out/share/mindclade/toolchain-manifest.json"
              '';
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
            nix
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
          ]
          ++ lib.optionals stdenv.hostPlatform.isLinux [
            util-linux
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
            MINDCLADE_TOOLCHAIN_MANIFEST = "${current.toolchainManifest}/share/mindclade/toolchain-manifest.json";
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
                  command -v bazel buildifier buf cargo cc c++ go java jq just nix nixfmt node pnpm python3 rustc uv >/dev/null
                  test "$(bazel --version)" = "bazel 9.1.1"
                  test "$(rustc --version | cut -d' ' -f2)" = '${pkgs.rustc.version}'
                  jq -e '.schema_version == "mindclade-toolchain.v2" and .executables.bazel.version == "9.1.1" and .executables.rustc.version == "${pkgs.rustc.version}" and .executables.go.version == "1.26.7"' \
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
