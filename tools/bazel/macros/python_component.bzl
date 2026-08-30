"""Governed Python component macro without a second dependency authority."""

load("//tools:bazel/rules/component_rule.bzl", "component_metadata")


def python_component(name, component, owner, srcs, data = [], visibility = None):
    """Declare source closure and metadata; native packaging stays in uv."""
    native.filegroup(
        name = name,
        srcs = srcs,
        data = data,
        visibility = visibility,
    )
    component_metadata(
        name = name + "_component",
        component_name = component,
        metadata = "component.yaml",
        owner = owner,
        visibility = visibility,
    )
