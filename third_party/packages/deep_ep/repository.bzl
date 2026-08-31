"""Bazel gate for the Nix-owned DeepEP artifact bundle."""

def _quoted(values):
    return ",\n        ".join([repr(value) for value in values])

def _deep_ep_artifact_repository_impl(repository_ctx):
    if repository_ctx.os.name.lower() != "linux":
        fail("DeepEP artifacts require a Linux x86_64 Nix builder")
    architecture = repository_ctx.execute(["uname", "-m"], quiet = True)
    if architecture.return_code != 0 or architecture.stdout.strip() != "x86_64":
        fail("DeepEP wheel artifacts currently require Linux x86_64")

    nix = repository_ctx.which("nix")
    if nix == None:
        fail("nix is required; invoke Bazel through nix develop .#deepep")

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
            "build",
            "--no-link",
            "--print-out-paths",
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

    inventory = repository_ctx.execute(
        ["find", artifact_root, "-type", "f", "-print"],
        quiet = True,
    )
    if inventory.return_code != 0:
        fail("cannot inventory the Nix DeepEP artifact bundle: %s" % inventory.stderr)
    files = sorted([
        path[len(artifact_root) + 1:]
        for path in inventory.stdout.splitlines()
        if path.startswith(artifact_root + "/")
    ])
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
    missing = [path for path in required if path not in files]
    wheels = [path for path in files if path.startswith("wheel/") and path.endswith(".whl")]
    if missing or len(wheels) != 1:
        fail("incomplete DeepEP artifact bundle; missing=%s wheels=%s" % (missing, wheels))
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
    environ = ["NIX_CONFIG", "PATH"],
    local = True,
)

def _deep_ep_nix_impl(module_ctx):
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
