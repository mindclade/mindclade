# ADR-0023: Estate Nix and Bazel hermeticity and cache preparation

- Status: Accepted in blueprint specification
- Connected ratification: Pending independent review on protected infrastructure
- Specification date: 2026-09-02
- Effective date: Pending connected ratification; source-only implementation authorized 2026-09-02
- Compatibility window: v1 evidence remains readable during the PR train; only v2 may authorize cache use
- Supersedes: None
- Superseded by: None
- Owners: Developer Platform, Security
- Reviewers: Architecture, Release Engineering

## Context

The estate shares one pinned Nixpkgs revision and Bazel 9.1.1, but its Bazel
actions still inherit host paths, its native-agreement receipt is a fixed PASS,
and its private cache and remote-execution boundaries are deliberately disabled.
Mindclade already has affected-target selection and a two-clean-output-root
reproducibility canary; those are extended rather than replaced.

## Decision

Activate source contracts for `mindclade-toolchain.v2`,
`bazel-native-agreement.v2`, `cache-boundary.v2`, `bazel-local-cache`, a
deterministic Wave 1 vendor refresh/offline verifier, and
`rbe-worker-manifest.v1`. The Nix closure is the compiler and interpreter
authority. Bzlmod continues to own rules and library resolution, but must not
download competing language toolchains.

The local disk cache is opt-in, bounded, and prohibited in CI, release,
offline, and cacheless profiles. Private cache reads and writes remain disabled
without connected IAM and activation evidence. Remote executor, remote cache,
and upload endpoints remain empty in every active configuration.

The first authoritative offline subject is `//:wave1_tests`. A committed vendor
snapshot is authoritative only after a deterministic refresh and empty-cache,
network-denied verification on its exact Linux system and Nix toolchain.
Darwin-produced snapshots are not Linux qualification evidence. RBE worker
manifests bind immutable OCI and Nix closure identities but grant no permission
to connect an executor.

No vendor snapshot is committed by this source-only decision. The first
snapshot must be generated and physically verified by the protected native
Linux qualification lane; until then, vendor drift and offline verification
fail closed on the intentionally absent snapshot.

## Consequences

Toolchain agreement is derived from executable identities and resolved Bazel
toolchains instead of asserted. Version or store-path drift fails closed. The
existing cacheless canary remains the reproducibility authority and gains
toolchain, vendor, and cache-boundary bindings.

No product API, deployment protocol, release activation, cache publication, or
remote execution is authorized by this decision.

## Qualification and rollback

Qualification covers canonical manifests, executable digests, Bazel
`cquery`/`aquery`, local-cache path confinement, deterministic vendor drift,
physical offline execution, cacheless output comparison, and container/sandbox
RBE smoke tests. Rollback disables the launcher profiles and returns consumers
to official-cache or local cacheless builds; immutable evidence remains
readable.

## Decision record metadata

- Affected invariants: pinned Nixpkgs; Bazel 9.1.1; no host toolchain inheritance; no unqualified cache or RBE activation
- Affected paths: `flake.nix`; `MODULE.bazel`; `.bazelrc`; `tools/bazel/`; `tools/ci/`; `third_party/bazel_vendor/`
- Affected contracts: `mindclade-toolchain.v2`; `bazel-native-agreement.v2`; `cache-boundary.v2`; `rbe-worker-manifest.v1`
- Security and safety impact: short-lived identity and signed-cache requirements remain external activation gates; repository code contains no credentials or private keys
- Migration: adopt generated policy, v2 toolchain evidence, vendoring, and disabled cache/RBE contracts in dependency order while retaining v1 readers during the PR train
- Rollback: disable the launcher profiles, remove internal substituters, deny publishers, and rotate the cache namespace while retaining official-cache and cacheless local builds
- Required evidence: generator drift; native platform builds; toolchain resolution; vendor/offline qualification; cache denial/tamper tests; two-root reproducibility; reviewed connected activation
