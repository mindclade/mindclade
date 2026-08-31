# Mindclade

`mindclade` is the canonical public product-source monorepo at
`github.com/mindclade/mindclade`. It contains Mindclade product source,
contracts, build definitions, and immutable release inputs.

## Current status

The repository is **FOUNDER_BOOTSTRAPPED** and Wave 1 source implementation is
active. Wave 1 is limited to the common contract and durability kernel,
cross-language generated projections, foundational libraries, local PostgreSQL
integration, and offline release/qualification evidence.

The active source boundary provides:

- deterministic repository and architecture evidence;
- common, artifact, job, audit, configuration, and release contracts;
- pinned Go, Python, Rust, and TypeScript projections;
- tenant-scoped idempotency, outbox/inbox, lease fencing, and reconciliation;
- immutable artifact finalization and offline qualification tooling; and
- a local CPU-only integration profile with no production authority.

Dataset, model, training, inference, SDK, Kubernetes, cloud, and production
capabilities remain absent. Source implementation does not imply connected
GitHub, trusted signing, cloud, cluster, release, or production qualification.

## Start here

Use the pinned Nix shell or devcontainer, then run:

```text
nix develop
just bootstrap
just doctor
just check
just test-affected
```

The opt-in Linux SM90/Hopper GPU intake shell includes pinned modern DeepEP
2.x, PyTorch, CUDA compiler, NCCL, vanilla NVSHMEM, and RDMA development
inputs:

```text
nix develop .#gpu
python -c "import deep_ep; print(deep_ep.__file__)"
```

DeepEP v2 uses NCCL Gin for expert parallelism; NVSHMEM remains present for
the legacy objects upstream still compiles. Multi-node use additionally
requires qualified host IBGDA or GDRCopy configuration. This shell is
development intake only and does not mutate host drivers or grant GPU, kernel,
network, or production qualification.

Read `AGENTS.md`, `ARCHITECTURE.md`, and `CONTRIBUTING.md` before editing. The
editable blueprint sources live under `docs/architecture/blueprint/`; the
repository-path manifest governs which paths may be populated.

## Repository boundaries

This repository does not own organization-wide GitHub policy, bootstrap trust,
cloud infrastructure, production secrets, or live Kubernetes desired state.
Those authorities remain in `.github`, `github-config`, `bootstrap`,
`infrastructure-live`, and `gitops` respectively.

Copyright (c) 2026 Mindclade. All rights reserved.
