"""Emit provider-derived identities for the configured Bazel toolchains."""

load("@rules_cc//cc:action_names.bzl", "CPP_COMPILE_ACTION_NAME", "C_COMPILE_ACTION_NAME")
load("@rules_cc//cc:find_cc_toolchain.bzl", "CC_TOOLCHAIN_ATTRS", "find_cpp_toolchain", "use_cc_toolchain")
load("@rules_cc//cc/common:cc_common.bzl", "cc_common")

_CC_TOOLCHAIN = "@bazel_tools//tools/cpp:toolchain_type"
_GO_TOOLCHAIN = "@rules_go//go:toolchain"
_JAVA_RUNTIME_TOOLCHAIN = "@bazel_tools//tools/jdk:runtime_toolchain_type"
_NODE_TOOLCHAIN = "@rules_nodejs//nodejs:toolchain_type"
_NODE_RUNTIME_TOOLCHAIN = "@rules_nodejs//nodejs:runtime_toolchain_type"
_PYTHON_TOOLCHAIN = "@bazel_tools//tools/python:toolchain_type"
_RUST_TOOLCHAIN = "@rules_rust//rust:toolchain_type"

def _python_path(runtime):
    if runtime.interpreter:
        return runtime.interpreter.path
    return runtime.interpreter_path

def _python_version(runtime):
    version = runtime.interpreter_version_info
    if not version:
        return ""
    return "{}.{}.{}".format(version.major, version.minor, version.micro)

def _configured_toolchain_probe_impl(ctx):
    cc_toolchain = find_cpp_toolchain(ctx)
    cc_features = cc_common.configure_features(
        ctx = ctx,
        cc_toolchain = cc_toolchain,
        requested_features = ctx.features,
        unsupported_features = ctx.disabled_features,
    )
    go_toolchain = ctx.toolchains[_GO_TOOLCHAIN]
    java_runtime = ctx.toolchains[_JAVA_RUNTIME_TOOLCHAIN].java_runtime
    node_info = ctx.toolchains[_NODE_TOOLCHAIN].nodeinfo
    node_runtime_info = ctx.toolchains[_NODE_RUNTIME_TOOLCHAIN].nodeinfo
    python_runtime = ctx.toolchains[_PYTHON_TOOLCHAIN].py3_runtime
    rust_toolchain = ctx.toolchains[_RUST_TOOLCHAIN]

    node_path = node_info.node.path if node_info.node else node_info.node_path
    node_runtime_path = (
        node_runtime_info.node.path if node_runtime_info.node else node_runtime_info.node_path
    )
    output = ctx.actions.declare_file(ctx.label.name + ".json")
    ctx.actions.write(
        output = output,
        content = json.encode_indent({
            "schema_version": "bazel-configured-toolchain-probe.v1",
            "tools": {
                "cargo": {
                    "path": rust_toolchain.cargo.path,
                    "provider_version": rust_toolchain.version,
                    "toolchain_type": _RUST_TOOLCHAIN,
                },
                "cc": {
                    "path": cc_common.get_tool_for_action(
                        feature_configuration = cc_features,
                        action_name = C_COMPILE_ACTION_NAME,
                    ),
                    "provider_version": cc_toolchain.compiler,
                    "toolchain_type": _CC_TOOLCHAIN,
                },
                "cxx": {
                    "path": cc_common.get_tool_for_action(
                        feature_configuration = cc_features,
                        action_name = CPP_COMPILE_ACTION_NAME,
                    ),
                    "provider_version": cc_toolchain.compiler,
                    "toolchain_type": _CC_TOOLCHAIN,
                },
                "go": {
                    "path": go_toolchain.sdk.go.path,
                    "provider_version": go_toolchain.sdk.version,
                    "toolchain_type": _GO_TOOLCHAIN,
                },
                "java": {
                    "path": str(java_runtime.java_executable_exec_path),
                    "provider_version": str(java_runtime.version),
                    "toolchain_type": _JAVA_RUNTIME_TOOLCHAIN,
                },
                "node": {
                    "path": node_path,
                    "provider_version": "",
                    "toolchain_type": _NODE_TOOLCHAIN,
                },
                "node_runtime": {
                    "path": node_runtime_path,
                    "provider_version": "",
                    "toolchain_type": _NODE_RUNTIME_TOOLCHAIN,
                },
                "python": {
                    "path": _python_path(python_runtime),
                    "provider_version": _python_version(python_runtime),
                    "toolchain_type": _PYTHON_TOOLCHAIN,
                },
                "rustc": {
                    "path": rust_toolchain.rustc.path,
                    "provider_version": rust_toolchain.version,
                    "toolchain_type": _RUST_TOOLCHAIN,
                },
                "rustdoc": {
                    "path": rust_toolchain.rust_doc.path,
                    "provider_version": rust_toolchain.version,
                    "toolchain_type": _RUST_TOOLCHAIN,
                },
            },
        }) + "\n",
    )
    return [DefaultInfo(files = depset([output]))]

configured_toolchain_probe = rule(
    implementation = _configured_toolchain_probe_impl,
    attrs = CC_TOOLCHAIN_ATTRS,
    fragments = ["cpp"],
    toolchains = use_cc_toolchain() + [
        _GO_TOOLCHAIN,
        _JAVA_RUNTIME_TOOLCHAIN,
        _NODE_TOOLCHAIN,
        _NODE_RUNTIME_TOOLCHAIN,
        _PYTHON_TOOLCHAIN,
        _RUST_TOOLCHAIN,
    ],
)
