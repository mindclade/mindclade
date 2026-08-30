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
      forAllSystems =
        function:
        builtins.listToAttrs (
          map (system: {
            name = system;
            value = function (import nixpkgs { inherit system; });
          }) systems
        );
    in
    {
      devShells = forAllSystems (
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

      formatter = forAllSystems (pkgs: pkgs.nixfmt);
    };
}
