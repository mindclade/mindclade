# ADR-0002: Dependency and Build Law

- Status: Accepted in blueprint specification
- Connected ratification: Pending independent review on protected infrastructure
- Specification date: 2026-08-30
- Effective date: Pending connected ratification
- Compatibility window: Wave 0 graph law; later edges require compatible additive declarations
- Supersedes: None
- Superseded by: None
- Owners: Architecture, Developer Platform
- Reviewers: Security, ML Systems, Data Platform

## Decision record metadata

- Affected invariants: inward dependency direction, acyclic production graphs, private-by-default
  visibility, agreement between Bazel and native lock authorities, and trust-classified remote-cache
  isolation with cache-independent release evidence.
- Affected paths: `BUILD.bazel`, `MODULE.bazel`, native workspace/lock files, `component.yaml`, and
  `tools/bazel/`.
- Affected contracts: typed dependency edges, visibility declarations, affected-target plans, and
  exception records with owners and expiry.
- Security and safety impact: bounds executable and supply-chain closure, prevents undeclared
  runtime coupling, keeps research code outside production paths, and prevents private-output
  disclosure or unqualified cache poisoning.
- Migration: add language rules only with a real target, locked native/Bazel inputs, ownership,
  license evidence, and graph-policy tests.
- Rollback: remove an additive edge/rule and its lock changes while no released consumer depends on
  it; otherwise publish a migration ADR and preserve the prior compatible surface.
- Required evidence: cycle/visibility/import tests, Bazel query membership, native lock checks,
  affected-target tests, and dependency/license inventory.

## Context

A polyglot monorepo makes atomic change possible, but without an executable
dependency law it also makes accidental cycles, oversized shared packages, and
undeclared runtime coupling easy. Bazel must describe the cross-language graph
without replacing each ecosystem's package and lock authority.

## Decision

Dependencies follow semantic layers and point inward toward contracts and
foundations. A higher-level composition may depend on a lower-level public
surface; a lower-level domain must not import a service, worker, application,
deployment, or research composition. Production code never imports `research/`.

Every normalized edge declares source, destination, kind, visibility, owner,
justification, and scope. Edge kinds are compile/API, runtime, protocol,
artifact/data, codegen/tool, test-only, deployment, and operational. Visibility
is private unless the owner intentionally declares a public surface.

Cycles are prohibited in the production compile/API graph and in the combined
runtime/deployment graph. Test-only cycles do not justify a production edge.
An exception names its owner, exact edge and scope, expiry, executable guard,
migration plan, and removal criterion.

Bazel is the repository integration graph for targets, visibility, affected
tests, and release closure. Native authorities remain:

- Python: root `pyproject.toml`, `uv.lock`, and Python version file;
- Rust: root Cargo workspace, lock, and toolchain file;
- Go: one root module and checksum file;
- TypeScript: root pnpm workspace and lock;
- Protobuf: root Buf configuration and protocol compatibility baselines; and
- system tools: locked Nix flake and pinned Bazel version.

Native and Bazel dependency graphs must agree. A clean release build fetches
declared dependencies first, then builds with network disabled, a sanitized
environment, fixed locale and timezone, controlled timestamps, and no home
directory input.

Remote cache is an optimization, never an artifact, qualification, or release
evidence authority. Bazel HTTP cache may expose action-cache records, CAS
outputs, and captured stdout/stderr, so public-readable and private-internal
objects use separate buckets or cryptographically and IAM-isolated namespaces.
Public publication is limited to an explicit target allowlist; absence from the
allowlist means private. Cache writers are denied until the producing builder,
target class, and platform envelope are qualified.

Cache identity binds schema version, trust class, operating platform,
architecture, complete toolchain identity, and build mode in addition to the
ordinary Bazel action key. A classification change revokes existing access and
rotates to a new namespace rather than relabeling old objects. Noncurrent
versions have short lifecycle retention. Access logs are written to a separate
destination outside the cache writer's mutation authority.

Qualification includes a periodic cacheless canary. Suspected poison triggers
namespace write denial/revocation, a clean cacheless rebuild, and digest
comparison before read authority is restored. Release provenance records
whether a compatible cache entry was consulted, but independently verifies the
subject and never cites a cache hit as evidence.

This repository owns the cache classification, key-shape, publication,
qualification, and recovery contracts. `bootstrap` owns only foundational GCP
trust and identities; `infrastructure-live` owns bucket, IAM, logging, and
lifecycle desired state. The product monorepo neither provisions those
resources nor treats source policy as connected implementation evidence.

`libs/python` is permanently torch-free. PyTorch semantics belong to their
model, training, evaluation, inference, runtime, or worker owner. Shared
packages are narrow foundations, never a dumping ground.

Approved target paths are activation-gated. A future namespace is not created
until a real target, owner, test, public boundary, dependency direction, and
removal condition exist. The path manifest is updated in the same change.

## Consequences

- Ecosystem tooling remains usable while release closure is inspectable in one
  graph.
- Cross-domain calls use declared contracts or immutable artifacts rather than
  private imports.
- Adding a dependency requires both the native lock change and Bazel graph
  change, with license and security evidence.
- Cache reuse cannot cross trust/classification/platform/toolchain/build-mode
  boundaries and cannot replace a cacheless qualification sample.
- Empty scaffolds, generic shared packages, and target-only paths fail CI.

## Rejected alternatives

- Bazel-only dependency resolution was rejected because it would create a
  second, divergent authority for native developers and publishers.
- Unrestricted monorepo imports were rejected because repository adjacency is
  not architectural permission.
- Broad `common`, `utils`, or `platform` packages were rejected because they
  conceal semantic ownership and create cycles.
- Pre-creating the target tree was rejected because empty directories and
  placeholder targets falsely imply implementation.
- One shared public/private cache namespace was rejected because Bazel cache
  responses can disclose outputs and logs and because access revocation cannot
  reliably reclassify already-readable objects.
- Cache hits as release evidence were rejected because a cache is mutable
  acceleration infrastructure, not an independent attestation authority.

## Qualification and rollback

Wave 0 validates component metadata, owners, typed edges, cycles, visibility,
native/Bazel agreement, path activation, and the approved drift baseline. New
enforcement may be reverted independently if it blocks recovery, but the last
approved graph and exception register remain evidence and no prohibited edge is
thereby approved.

Remote-cache qualification additionally proves namespace/IAM separation,
allowlisted public targets, denied pre-qualification writes, key separation,
noncurrent lifecycle, independent access logging, cacheless canaries, and poison
recovery by clean rebuild and digest comparison. These are source requirements
until protected bootstrap and infrastructure-live evidence proves the connected
GCP implementation.
