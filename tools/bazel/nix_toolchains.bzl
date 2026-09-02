"""Materialize Bazel Rust and Node toolchains from the pinned Nix manifest."""

def _require_executable(manifest, name):
    executable = manifest.get("executables", {}).get(name)
    if type(executable) != "dict":
        fail("Nix toolchain manifest lacks executable {}".format(name))
    path = executable.get("path", "")
    if not path.startswith("/nix/store/"):
        fail("Nix executable {} is not store-backed".format(name))
    return executable

def _platform(system):
    platforms = {
        "aarch64-darwin": struct(
            cpu = "@platforms//cpu:aarch64",
            dylib_ext = ".dylib",
            os = "@platforms//os:osx",
            staticlib_ext = ".a",
            stdlib_linkflags = ["-lSystem", "-lresolv"],
            triple = "aarch64-apple-darwin",
        ),
        "aarch64-linux": struct(
            cpu = "@platforms//cpu:aarch64",
            dylib_ext = ".so",
            os = "@platforms//os:linux",
            staticlib_ext = ".a",
            stdlib_linkflags = ["-ldl", "-lpthread"],
            triple = "aarch64-unknown-linux-gnu",
        ),
        "x86_64-linux": struct(
            cpu = "@platforms//cpu:x86_64",
            dylib_ext = ".so",
            os = "@platforms//os:linux",
            staticlib_ext = ".a",
            stdlib_linkflags = ["-ldl", "-lpthread"],
            triple = "x86_64-unknown-linux-gnu",
        ),
    }
    if system not in platforms:
        fail("unsupported Nix execution system {}".format(system))
    return platforms[system]

def _quoted(values):
    return ", ".join(['"{}"'.format(value) for value in values])

def _nix_toolchains_repository_impl(repository_ctx):
    manifest_path = repository_ctx.os.environ.get("MINDCLADE_TOOLCHAIN_MANIFEST", "")
    if not manifest_path.startswith("/nix/store/"):
        fail("MINDCLADE_TOOLCHAIN_MANIFEST must name a pinned Nix store path")
    manifest = json.decode(repository_ctx.read(manifest_path))
    if manifest.get("schema_version") != "mindclade-toolchain.v2":
        fail("Nix toolchain manifest must use mindclade-toolchain.v2")

    platform = _platform(manifest.get("system"))
    sdkroot = repository_ctx.os.environ.get("SDKROOT", "")
    if manifest.get("system") == "aarch64-darwin" and not sdkroot.startswith("/nix/store/"):
        fail("SDKROOT must identify the pinned Nix Apple SDK on Darwin")
    rustc = _require_executable(manifest, "rustc")
    rustdoc = _require_executable(manifest, "rustdoc")
    cargo = _require_executable(manifest, "cargo")
    node = _require_executable(manifest, "node")
    python = _require_executable(manifest, "python")
    python_version = python["version"].split(".")
    if len(python_version) != 3:
        fail("Nix Python version must contain major, minor, and micro components")

    sysroot_result = repository_ctx.execute(
        [rustc["path"], "--print", "sysroot"],
        environment = {"LANG": "C", "LC_ALL": "C", "TZ": "UTC"},
        quiet = True,
    )
    if sysroot_result.return_code != 0:
        fail("Nix rustc could not report its sysroot: {}".format(sysroot_result.stderr))
    sysroot = sysroot_result.stdout.strip()
    if not sysroot.startswith("/nix/store/"):
        fail("Nix rustc reported a non-store sysroot")

    repository_ctx.symlink(rustc["path"], "bin/rustc")
    repository_ctx.symlink(rustdoc["path"], "bin/rustdoc")
    repository_ctx.symlink(cargo["path"], "bin/cargo")
    repository_ctx.symlink(node["path"], "bin/node")
    repository_ctx.symlink(python["path"], "bin/python3")
    repository_ctx.symlink(sysroot, "rust")

    constraints = '["{}", "{}"]'.format(platform.cpu, platform.os)
    repository_ctx.file(
        "BUILD.bazel",
        """\
load("@rules_nodejs//nodejs:toolchain.bzl", "nodejs_toolchain")
load("@rules_python//python:py_runtime.bzl", "py_runtime")
load("@rules_python//python:py_runtime_pair.bzl", "py_runtime_pair")
load("@rules_rust//rust:toolchain.bzl", "rust_stdlib_filegroup", "rust_toolchain")

package(default_visibility = ["//visibility:public"])

exports_files(["bin/cargo", "bin/node", "bin/rustc", "bin/rustdoc"])

filegroup(name = "rustc", srcs = ["bin/rustc"])
filegroup(name = "rustdoc", srcs = ["bin/rustdoc"])
filegroup(name = "cargo", srcs = ["bin/cargo"])
filegroup(
    name = "rustc_lib",
    srcs = glob([
        "rust/lib/*.so*",
        "rust/lib/*.dylib*",
        "rust/lib/rustlib/{triple}/codegen-backends/**",
        "rust/lib/rustlib/{triple}/lib/*.rmeta",
        "rust/lib/rustlib/{triple}/lib/*.so*",
        "rust/lib/rustlib/{triple}/lib/*.dylib*",
    ], allow_empty = True),
)
rust_stdlib_filegroup(
    name = "rust_std",
    srcs = glob([
        "rust/lib/rustlib/{triple}/lib/*.rlib",
        "rust/lib/rustlib/{triple}/lib/*.rmeta",
        "rust/lib/rustlib/{triple}/lib/*.so*",
        "rust/lib/rustlib/{triple}/lib/*.dylib*",
        "rust/lib/rustlib/{triple}/lib/*.a",
        "rust/lib/rustlib/{triple}/lib/self-contained/**",
    ], allow_empty = True),
)
rust_toolchain(
    name = "rust_impl",
    binary_ext = "",
    cargo = ":cargo",
    channel = "stable",
    default_edition = "2024",
    dylib_ext = "{dylib_ext}",
    env = {rust_env},
    exec_triple = "{triple}",
    rust_doc = ":rustdoc",
    rust_std = ":rust_std",
    rustc = ":rustc",
    rustc_lib = ":rustc_lib",
    staticlib_ext = "{staticlib_ext}",
    stdlib_linkflags = [{stdlib_linkflags}],
    target_triple = "{triple}",
    version = "{rust_version}",
)
toolchain(
    name = "rust_toolchain",
    exec_compatible_with = {constraints},
    target_compatible_with = {constraints},
    toolchain = ":rust_impl",
    toolchain_type = "@rules_rust//rust:toolchain_type",
)

nodejs_toolchain(name = "node_impl", node = "bin/node")
toolchain(
    name = "node_toolchain",
    exec_compatible_with = {constraints},
    toolchain = ":node_impl",
    toolchain_type = "@rules_nodejs//nodejs:toolchain_type",
)
toolchain(
    name = "node_runtime_toolchain",
    target_compatible_with = {constraints},
    toolchain = ":node_impl",
    toolchain_type = "@rules_nodejs//nodejs:runtime_toolchain_type",
)

filegroup(name = "python3", srcs = ["bin/python3"])
py_runtime(
    name = "python_runtime",
    interpreter = ":python3",
    interpreter_version_info = {{
        "major": "{python_major}",
        "micro": "{python_micro}",
        "minor": "{python_minor}",
    }},
    python_version = "PY3",
)
py_runtime_pair(name = "python_runtimes", py3_runtime = ":python_runtime")
toolchain(
    name = "python_toolchain",
    exec_compatible_with = {constraints},
    target_compatible_with = {constraints},
    toolchain = ":python_runtimes",
    toolchain_type = "@rules_python//python:toolchain_type",
)

filegroup(
    name = "all",
    srcs = ["bin/cargo", "bin/node", "bin/python3", "bin/rustc", "bin/rustdoc"],
)
""".format(
            constraints = constraints,
            dylib_ext = platform.dylib_ext,
            python_major = python_version[0],
            python_micro = python_version[2],
            python_minor = python_version[1],
            rust_env = json.encode({"SDKROOT": sdkroot} if sdkroot else {}),
            rust_version = rustc["version"],
            staticlib_ext = platform.staticlib_ext,
            stdlib_linkflags = _quoted(platform.stdlib_linkflags),
            triple = platform.triple,
        ),
    )

nix_toolchains_repository = repository_rule(
    implementation = _nix_toolchains_repository_impl,
    environ = ["MINDCLADE_TOOLCHAIN_MANIFEST", "SDKROOT"],
    local = True,
)
