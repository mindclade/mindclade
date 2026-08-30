"""Aspect collecting component metadata from governed targets."""

load("//tools:bazel/rules/component_rule.bzl", "ComponentInfo")

ComponentGraphInfo = provider(fields = {"components": "Transitive component records."})


def _component_metadata_impl(target, ctx):
    direct = []
    if ComponentInfo in target:
        info = target[ComponentInfo]
        direct.append("%s|%s|%s" % (info.component_name, info.owner, info.metadata.path))
    transitive = []
    if hasattr(ctx.rule.attr, "deps"):
        for dependency in ctx.rule.attr.deps:
            if ComponentGraphInfo in dependency:
                transitive.append(dependency[ComponentGraphInfo].components)
    return [ComponentGraphInfo(components = depset(direct = direct, transitive = transitive))]


component_metadata_aspect = aspect(
    implementation = _component_metadata_impl,
    attr_aspects = ["deps"],
)
