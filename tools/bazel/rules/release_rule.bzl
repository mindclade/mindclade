"""Release closure rule; it never performs publication or promotion."""

ReleaseInfo = provider(
    doc = "Immutable local release-input closure awaiting qualification.",
    fields = {
        "artifact_kind": "Declared artifact kind.",
        "inputs": "Files comprising the local release input.",
        "qualification_targets": "Labels required before release eligibility.",
    },
)

def _release_input_impl(ctx):
    direct = depset(ctx.files.srcs)
    transitive = [direct]
    for dependency in ctx.attr.deps:
        transitive.append(dependency[DefaultInfo].files)
    files = depset(transitive = transitive)
    return [
        DefaultInfo(files = files),
        ReleaseInfo(
            artifact_kind = ctx.attr.artifact_kind,
            inputs = files,
            qualification_targets = tuple(ctx.attr.qualification_targets),
        ),
    ]

release_input = rule(
    implementation = _release_input_impl,
    attrs = {
        "artifact_kind": attr.string(mandatory = True),
        "deps": attr.label_list(),
        "qualification_targets": attr.string_list(mandatory = True),
        "srcs": attr.label_list(allow_files = True),
    },
    provides = [ReleaseInfo],
)
