"""Governed Go component macro without a second dependency authority."""

load("//tools:bazel/rules/component_rule.bzl", "component_metadata")


def go_component(name, component, owner, srcs, visibility = None):
    """Declare Go source closure; the root Go module remains authoritative."""
    native.filegroup(name = name, srcs = srcs, visibility = visibility)
    component_metadata(
        name = name + "_component",
        component_name = component,
        metadata = "component.yaml",
        owner = owner,
        visibility = visibility,
    )
