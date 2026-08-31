"""Governed Rust component macro without a second dependency authority."""

load("//tools:bazel/rules/component_rule.bzl", "component_metadata")

def rust_component(name, component, owner, srcs, visibility = None):
    """Declare Rust source closure; Cargo remains dependency authority."""
    native.filegroup(name = name, srcs = srcs, visibility = visibility)
    component_metadata(
        name = name + "_component",
        component_name = component,
        metadata = "component.yaml",
        owner = owner,
        visibility = visibility,
    )
