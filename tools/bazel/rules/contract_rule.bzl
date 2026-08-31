"""Contract source and compatibility-baseline aggregation rule."""

ContractInfo = provider(
    doc = "One authoritative contract source set and its compatibility evidence.",
    fields = {
        "authority": "Contract authority: protobuf or json-schema.",
        "baselines": "Compatibility baseline files.",
        "sources": "Authoritative source files.",
    },
)

def _contract_sources_impl(ctx):
    sources = depset(ctx.files.srcs)
    baselines = depset(ctx.files.compatibility_baselines)
    return [
        DefaultInfo(files = depset(transitive = [sources, baselines])),
        ContractInfo(
            authority = ctx.attr.authority,
            baselines = baselines,
            sources = sources,
        ),
    ]

contract_sources = rule(
    implementation = _contract_sources_impl,
    attrs = {
        "authority": attr.string(mandatory = True, values = ["protobuf", "json-schema"]),
        "compatibility_baselines": attr.label_list(allow_files = True),
        "srcs": attr.label_list(allow_files = True, mandatory = True),
    },
    provides = [ContractInfo],
)
