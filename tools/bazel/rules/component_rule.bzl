"""Component metadata rule used by the repository governance graph."""

ComponentInfo = provider(
    doc = "Machine-readable component identity bound to a Bazel target.",
    fields = {
        "metadata": "The component.yaml File.",
        "component_name": "Stable component identifier.",
        "owner": "Semantic owner team slug.",
    },
)

def _component_metadata_impl(ctx):
    metadata = ctx.file.metadata
    return [
        DefaultInfo(files = depset([metadata])),
        ComponentInfo(
            metadata = metadata,
            component_name = ctx.attr.component_name,
            owner = ctx.attr.owner,
        ),
    ]

component_metadata = rule(
    implementation = _component_metadata_impl,
    attrs = {
        "component_name": attr.string(mandatory = True),
        "metadata": attr.label(allow_single_file = [".yaml"], mandatory = True),
        "owner": attr.string(mandatory = True),
    },
    provides = [ComponentInfo],
)
