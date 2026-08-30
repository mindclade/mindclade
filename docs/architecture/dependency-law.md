# Dependency law

Status: Wave 0 repository policy. Owner: Developer Platform, with Architecture approval for
exceptions.

Compile and public-API dependencies follow this partial order from higher-level consumers to
lower-level authorities:

```text
apps and examples
→ SDKs and development-kit façades
→ worker and service composition roots
→ agents, evaluation, inference, and training
→ models, data, kernels, and runtime
→ biological domain packages
→ narrow language foundations and generated clients
→ protocol and schema sources
```

This is not permission for every higher layer to import every lower layer. Services use generated
contracts and Go foundations, workers compose their owning domain libraries, and agents call other
capabilities through registered ports or services. Production source never imports `deploy/` or
`research/`. Runtime calls in either direction require a versioned protocol and authorized endpoint.

Every normalized edge records `source`, `target`, `kind`, `visibility`, `owner`, `justification`,
`scope`, and an optional approved `exception`. Kinds are `compile-api`, `runtime`, `protocol`,
`data-artifact`, `tool-codegen`, `test-only`, `deployment`, and `operational`. Compile, protocol,
artifact, code-generation, and deployment edges are acyclic. Exceptions name an owner, expiry,
consumer, rollback, and ADR; an exception cannot silently redefine the layer order.

Wave 0 intentionally has an empty product component graph. `tools/repo/dependency_policy.py`
validates typed edges, unknown targets, direction, and cycles. Later waves update component metadata,
the path manifest, CODEOWNERS, Bazel visibility, tests, and release closure atomically when activating
an edge.
