# Mindclade

`mindclade` is the canonical public product-source monorepo at
`github.com/mindclade/mindclade`. It contains Mindclade product source,
contracts, build definitions, and immutable release inputs.

## Current status

The repository is **FOUNDER_BOOTSTRAPPED**. The Wave 1 durability kernel remains
active, and ADR-0015 activates the complete contract catalog as an unratified
v1 candidate estate. Blueprint waves guide implementation order rather than
deferring authoritative contract definitions; compatibility begins only after
the evidence-gated ratification defined by ADR-0015.

The active source boundary provides:

- deterministic repository and architecture evidence;
- common, artifact, job, audit, and complete versioned domain contracts;
- pinned Protobuf and gRPC projections for Go, Python, Rust, and TypeScript;
- durable JSON Schema documents and an unratified public-safe OpenAPI candidate;
- generated-code consumption in product libraries and process boundaries;
- Buf-generated native Protobuf/gRPC/Connect clients wrapped by
  Mindclade-owned internal Go, Python, Rust, and TypeScript facades; Fern and
  Speakeasy remain optional HTTP/JSON comparison tools, never dependencies;
- generated-interface Go control-plane adapters for every candidate gRPC
  service, with normalized PostgreSQL repositories for the activated domain
  verticals;
- tenant-scoped idempotency, transactional outbox/inbox, exact-version event
  projection, lease fencing, and reconciliation;
- immutable artifact finalization and offline qualification tooling; and
- a local CPU-only integration profile with no production authority.

The checked source implements the candidate control-plane and private-SDK
verticals, but it does not by itself qualify a live environment. In
particular, source implementation does not imply connected GitHub, package
publication, trusted signing, cloud, cluster, release, GPU, scientific, or
production qualification. Those claims require the separately governed
receipts and protected promotion gates.

## Start here

Use the pinned Nix shell or devcontainer, then run:

```text
nix develop --no-accept-flake-config --no-update-lock-file
just bootstrap
just doctor
just check
just test-affected
```

The root developer-quality commands use each language's pinned native tools:

```text
just format
just format-check
just lint
```

`just format` edits only handwritten source and configuration. Generated
bindings, generated Starlark, architecture renders, and provenance remain under
their owning generators and drift checks.

The opt-in Linux SM90/Hopper GPU intake shell includes pinned modern DeepEP
2.x, PyTorch, CUDA compiler, NCCL, vanilla NVSHMEM, and RDMA development
inputs:

```text
nix develop --no-accept-flake-config --no-update-lock-file .#gpu
python -c "import deep_ep; print(deep_ep.__file__)"
```

DeepEP v2 uses NCCL Gin for expert parallelism; NVSHMEM remains present for
the legacy objects upstream still compiles. Multi-node use additionally
requires qualified host IBGDA or GDRCopy configuration. This shell is
development intake only and does not mutate host drivers or grant GPU, kernel,
network, or production qualification.

The committed `flake.lock` and `MODULE.bazel.lock` close the system-tool and
Bazel module graphs. Remote Bazel execution and remote caching remain disabled
until workers carry the exact reviewed Nix store paths or use an immutable,
digest-pinned image built from the same toolchain closure.

Read `AGENTS.md`, `ARCHITECTURE.md`, and `CONTRIBUTING.md` before editing. The
editable blueprint sources live under `docs/architecture/blueprint/`; the
repository-path manifest governs which paths may be populated.

## Repository boundaries

This repository does not own organization-wide GitHub policy, bootstrap trust,
cloud infrastructure, production secrets, or live Kubernetes desired state.
Those authorities remain in `.github`, `github-config`, `bootstrap`,
`infrastructure-live`, and `gitops` respectively.

Copyright (c) 2026 Mindclade. All rights reserved.
