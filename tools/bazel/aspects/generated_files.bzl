"""Aspect collecting files declared as generated target output."""

GeneratedFilesInfo = provider(fields = {"files": "Transitive generated files."})


def _generated_files_impl(target, ctx):
    direct = []
    if hasattr(ctx.rule.attr, "outs"):
        for output in ctx.rule.attr.outs:
            direct.append(output)
    transitive = []
    if hasattr(ctx.rule.attr, "deps"):
        for dependency in ctx.rule.attr.deps:
            if GeneratedFilesInfo in dependency:
                transitive.append(dependency[GeneratedFilesInfo].files)
    return [GeneratedFilesInfo(files = depset(direct = direct, transitive = transitive))]


generated_files_aspect = aspect(
    implementation = _generated_files_impl,
    attr_aspects = ["deps"],
)
