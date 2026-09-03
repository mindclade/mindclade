# ADR-0024: Internal SDK roots move to `sdks/<language>`

- Status: Accepted in blueprint specification
- Connected ratification: Pending independent review on protected infrastructure
- Specification date: 2026-09-02
- Effective date: 2026-09-02
- Compatibility window: None required; the SDKs are repository-internal and unpublished
- Supersedes: None
- Superseded by: None
- Owners: Developer Experience, Architecture
- Reviewers: Architecture, Security

## Context

The authoritative blueprint places the four handwritten SDK façades under a
dedicated top-level `sdks/` tree rather than beside service-private code:

```text
sdks/
└── internal/
    ├── go/
    ├── python/
    ├── rust/
    └── typescript/
```

The repository held them at `internal/sdk/<language>` instead. That location
predates the blueprint and reads as service-private implementation, which the
façades are not: they are the supported client boundary that the console, the
CLI, examples, notebooks, bounded agents, and integration tests consume.

The blueprint's literal `sdks/internal/<language>` spelling cannot be used for
Go. Go forbids importing a package beneath a directory named `internal` from
outside that directory's parent, so `sdks/internal/go/mindclade` would be
importable only by code under `sdks/`. This was verified rather than assumed:
a probe module reproduces the exact compiler rejection,

```text
use of internal package example.com/probe/sdks/internal/go/mindclade not allowed
```

and `tools/mindcladectl` is a real consumer outside that subtree. The other
three languages have no equivalent rule, but a per-language layout split would
leave the estate with two different SDK roots and no single governed prefix.

## Decision

Move the four façades and their shared coverage projection to `sdks/`:

```text
internal/sdk/go/mindclade   →  sdks/go/mindclade
internal/sdk/python         →  sdks/python
internal/sdk/rust           →  sdks/rust
internal/sdk/typescript     →  sdks/typescript
internal/sdk/README.md      →  sdks/README.md
internal/sdk/rpc-coverage.* →  sdks/rpc-coverage.*
```

The `internal` path element is dropped for every language, uniformly. The
SDKs remain internal, and internality remains enforced where this repository
already enforces it and can test it: the repository path manifest marks every
entry `public_surface: false`, `.github/CODEOWNERS` requires Architecture and
Security review, the layering conformance tests reject direct generated-binding
imports from client roots and reject persistence or event-delivery access from
the façades, and no SDK package is published. Go's directory rule is not the
mechanism that makes these packages internal, and it is not adopted as one.

Package identity does not change. The TypeScript package remains
`@mindclade/internal-sdk`, the Python distribution and import package remain
`mindclade_internal_sdk`, the Rust crate remains `mindclade_internal_sdk`, and
the four component identifiers remain `internal-sdk-{go,python,rust,typescript}`.
Only directories move, so no consumer's dependency declaration changes except
the Go import path.

The blueprint's further subdivision of the Go façade into `client/`, `auth/`,
`transport/`, `operations/`, `artifacts/`, `training/`, `datasets/`, `errors/`,
`retry/`, `telemetry/`, and `testing/` is not adopted by this decision. The Go
façade remains one `sdks/go/mindclade` package; that subdivision is a separate
change with its own review.

## Consequences

The move renames canonical paths one for one. The canonical file count is
unchanged at 3,565 and only the canonical path-set digest moves, so the
reconciliation stays a rename rather than an addition or a retirement.

Owner and component inference in `tools/repo/path_policy.py` is re-keyed from
`internal/sdk/` to `sdks/`, which keeps the four SDK components and the
`developer-experience` owner attached to the same files at their new paths.

The Go import path becomes
`github.com/mindclade/mindclade/sdks/go/mindclade`. The Rust, Python, and
TypeScript trees each sit one directory shallower, so their relative references
to the repository root and to `protocols/generated` lose one `../` segment.

`protocols/generated/generated-files.manifest.json` and
`sdks/rpc-coverage.generated.json` are regenerated, not hand-migrated, and the
generator's prior-output allowlist tracks the coverage projection to its new
path. `MODULE.bazel.lock` and `pnpm-lock.yaml` are refreshed from their sources.

No wire contract, descriptor, generated binding, public API, deployment
protocol, or release activation is changed by this decision.

## Qualification and rollback

Qualification for this move is source-level and complete when contract
generation is byte-identical across two consecutive runs with an empty working
tree between them, `just check-contract-drift` exits zero, `go build ./...` and
the four SDK test suites pass, the Bazel contract tests pass, and
`tools/repo/path_policy.py` reports `PASS` at the expected canonical count.

Rollback is a path rename in the opposite direction with the same manifest,
digest, and lock refresh. Nothing outside the repository observes either
direction, because no SDK package is published.

## Decision record metadata

- Affected invariants: internal SDKs are repository-internal and unpublished; the façade is the client boundary; generated bindings are not imported directly by client roots
- Affected paths: `sdks/`; `tools/repo/path_policy.py`; `docs/architecture/repository-path-manifest.yaml`; `.github/CODEOWNERS`; `MODULE.bazel.lock`; `pnpm-lock.yaml`; `Cargo.toml`; `pyproject.toml`; `pnpm-workspace.yaml`; `justfile`
- Affected contracts: none; no descriptor, wire, or event contract changes
- Security and safety impact: none; the review requirements and layering tests that make the SDKs internal are unchanged and still enforced at the new prefix
- Migration: move the trees, rewrite path references without touching package identities, correct relative depth, rebuild the path manifest and activation projection, refresh the language locks, regenerate contracts
- Rollback: rename back and repeat the manifest, digest, and lock refresh
- Required evidence: two-pass generation determinism; contract drift; Go build; four SDK suites; Bazel contract tests; repository path policy
