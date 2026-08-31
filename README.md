# Mindclade

`mindclade` is the canonical public product-source monorepo at
`github.com/mindclade/mindclade`. It contains Mindclade product source,
contracts, build definitions, and immutable release inputs.

## Current status

The repository is **FOUNDER_BOOTSTRAPPED**. The Wave 1 durability kernel remains
active, and ADR-0015 activates the complete contract catalog as a one-time
clean-v1 source baseline. Blueprint waves guide implementation order rather
than deferring authoritative contract definitions.

The active source boundary provides:

- deterministic repository and architecture evidence;
- common, artifact, job, audit, and complete versioned domain contracts;
- pinned Protobuf and gRPC projections for Go, Python, Rust, and TypeScript;
- durable JSON Schema documents and a curated public OpenAPI facade;
- generated-code consumption in product libraries and process boundaries;
- Stainless-primary public SDK generation with an oagen parity shadow;
- tenant-scoped idempotency, outbox/inbox, lease fencing, and reconciliation;
- immutable artifact finalization and offline qualification tooling; and
- a local CPU-only integration profile with no production authority.

Contract activation does not by itself implement or qualify dataset, model,
training, inference, agent, workflow, SDK-release, Kubernetes, cloud, or
production capabilities. Source implementation does not imply connected
GitHub, hosted SDK publication, trusted signing, cloud, cluster, release, GPU,
scientific, or production qualification.

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
