"""Bazel gate for the Nix-owned DeepEP artifact bundle."""

def _quoted(values):
    return ",\n        ".join([repr(value) for value in values])

def _deep_ep_artifact_repository_impl(repository_ctx):
    if repository_ctx.os.name.lower() != "linux":
        fail("DeepEP artifacts require a Linux x86_64 Nix builder")

    nix = repository_ctx.os.environ.get("MINDCLADE_NIX_BIN")
    if nix == None or not nix.startswith("/nix/store/"):
        fail("MINDCLADE_NIX_BIN must identify the Nix-store binary; invoke Bazel through nix develop --no-accept-flake-config --no-update-lock-file .#deepep")

    # Resolving every declared label makes package, source, patch, Python, and
    # flake lock changes part of the repository rule key.
    for source_input in repository_ctx.attr.source_inputs:
        repository_ctx.path(source_input)
    repository_root = repository_ctx.path(repository_ctx.attr.flake).dirname
    result = repository_ctx.execute(
        [
            nix,
            "--extra-experimental-features",
            "nix-command flakes",
            "--no-accept-flake-config",
            "build",
            "--no-link",
            "--no-update-lock-file",
            "--print-out-paths",
            "--option",
            "substituters",
            "https://cache.nixos.org/",
            "--option",
            "trusted-public-keys",
            "cache.nixos.org-1:6NCHdD59X431o0gWypbMrAURkbJ16ZPMQFGspcDShjY=",
            "--option",
            "require-sigs",
            "true",
            "path:%s#packages.x86_64-linux.deep-ep-artifacts" % repository_root,
        ],
        quiet = False,
        timeout = 14400,
    )
    if result.return_code != 0:
        fail("Nix DeepEP artifact build failed:\n%s\n%s" % (result.stdout, result.stderr))
    output_lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if len(output_lines) != 1 or not output_lines[0].startswith("/nix/store/"):
        fail("Nix did not return exactly one immutable DeepEP artifact output")
    artifact_root = output_lines[0]

    required = [
        "artifact-manifest.json",
        "elf-dependencies.json",
        "nix-closure-paths",
        "package-drv-path",
        "package-path",
        "provenance.intoto.jsonl",
        "runtime-manifest.json",
        "sbom.spdx.json",
    ]
    manifest = json.decode(repository_ctx.read(artifact_root + "/artifact-manifest.json"))
    wheel_filename = manifest.get("artifacts", {}).get("wheel", {}).get("filename")
    if type(wheel_filename) != "string" or not wheel_filename.endswith(".whl") or "/" in wheel_filename or "\\" in wheel_filename:
        fail("DeepEP artifact manifest does not declare one safe wheel filename")
    wheels = ["wheel/" + wheel_filename]
    files = required + wheels
    for relative_path in files:
        repository_ctx.symlink(artifact_root + "/" + relative_path, relative_path)

    repository_ctx.file(
        "BUILD.bazel",
        """package(default_visibility = [\"//visibility:public\"])

filegroup(
    name = \"artifact_bundle\",
    srcs = [
        %s
    ],
)

filegroup(
    name = \"wheel\",
    srcs = [\"%s\"],
)

filegroup(
    name = \"runtime_manifest\",
    srcs = [\"runtime-manifest.json\"],
)
""" % (_quoted(files), wheels[0]),
    )

deep_ep_artifact_repository = repository_rule(
    implementation = _deep_ep_artifact_repository_impl,
    attrs = {
        "flake": attr.label(mandatory = True, allow_single_file = True),
        "source_inputs": attr.label_list(allow_files = True),
    },
    configure = True,
    environ = ["MINDCLADE_NIX_BIN"],
    local = True,
)

def _deep_ep_nix_impl(_module_ctx):
    deep_ep_artifact_repository(
        name = "mindclade_deepep_nix",
        flake = Label("//:flake.nix"),
        source_inputs = [
            Label("//:flake.lock"),
            Label("//:pyproject.toml"),
            Label("//:uv.lock"),
            Label("//third_party:patches/patches.lock.json"),
            Label("//third_party:patches/deep_ep/declared-toolchain-paths.patch"),
            Label("//third_party:patches/deep_ep/deterministic-version.patch"),
            Label("//third_party:patches/deep_ep/gin-attestation.patch"),
            Label("//third_party:patches/deep_ep/runtime-jit-cache.patch"),
            Label("//third_party:source_mirrors/sources.lock.json"),
            Label("//third_party/packages/deep_ep:artifact_contract.py"),
            Label("//third_party/packages/deep_ep:gpu-evidence.schema.json"),
            Label("//third_party/packages/deep_ep:package.nix"),
            Label("//third_party/packages/deep_ep:runtime-manifest.schema.json"),
        ],
    )

deepep_nix = module_extension(implementation = _deep_ep_nix_impl)
