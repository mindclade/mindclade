# Mindclade

`mindclade` is the canonical private monorepo at
`github.com/mindclade/mindclade`. It will contain Mindclade product source,
contracts, build definitions, and immutable release inputs.

## Current status

The repository is a greenfield **Wave 0 governance baseline**. Product, domain,
SDK, service, worker, model, data, and deployment capabilities are not yet
implemented and their target-only paths are intentionally absent.

Wave 0 establishes:

- deterministic repository drift and architecture evidence;
- path, component, owner, and dependency governance;
- foundational architecture decisions;
- pinned polyglot workspace contracts; and
- a thin GitHub bridge to the authoritative Buildkite CI graph.

Source readiness does not imply protected GitHub, signing, cloud, cluster, or
production qualification.

## Start here

Use the pinned Nix shell or devcontainer, then run:

```text
nix develop
just bootstrap
just doctor
just check
just test-affected
```

Read `AGENTS.md`, `ARCHITECTURE.md`, and `CONTRIBUTING.md` before editing. The
editable blueprint sources live under `docs/architecture/blueprint/`; the
repository-path manifest governs which paths may be populated.

## Repository boundaries

This repository does not own organization-wide GitHub policy, bootstrap trust,
cloud infrastructure, production secrets, or live Kubernetes desired state.
Those authorities remain in `.github`, `github-config`, `bootstrap`,
`infrastructure-live`, and `gitops` respectively.

Copyright (c) 2026 Mindclade. All rights reserved.
