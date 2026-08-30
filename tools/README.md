# Repository Tooling

`tools/` contains tested repository automation, not product behavior.

- `repo/` inspects paths, components, owners, dependencies, and drift.
- `docs/` validates and renders architecture sources.
- `bazel/` supplies graph metadata and activation-safe build helpers.
- `ci/` selects affected tests, binds CI plans, and validates evidence.
- `dev/` verifies the pinned local environment without connected credentials.
- `generators/` owns approved component stubs.
- `licenses/` enforces declared dependency-license policy.

The first two directories produce Wave 0 architecture evidence. Generated
output is changed only through its owning source and generator. A tool may emit
local ignored artifacts, but it cannot deploy, promote, mutate a connected
system, or claim a cryptographic signature.
