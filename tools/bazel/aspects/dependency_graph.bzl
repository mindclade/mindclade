"""Aspect exposing direct target dependency labels for graph evidence."""

DependencyGraphInfo = provider(
    doc = "Direct and transitive dependency labels.",
    fields = {
        "direct": "Direct dependency labels.",
        "transitive": "Transitive dependency labels.",
    },
)

def _dependency_graph_impl(_target, ctx):
    direct = []
    transitive = []
    if hasattr(ctx.rule.attr, "deps"):
        for dependency in ctx.rule.attr.deps:
            direct.append(str(dependency.label))
            if DependencyGraphInfo in dependency:
                transitive.append(dependency[DependencyGraphInfo].transitive)
    return [DependencyGraphInfo(
        direct = tuple(sorted(direct)),
        transitive = depset(direct = direct, transitive = transitive),
    )]

dependency_graph_aspect = aspect(
    implementation = _dependency_graph_impl,
    attr_aspects = ["deps"],
)
