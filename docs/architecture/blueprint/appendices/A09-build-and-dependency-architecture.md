## Appendix A9 — Build and dependency architecture

### A9.1 Bazel is the integration graph

Bazel owns:

- repository-wide target graph;
- source visibility and dependency enforcement;
- code generation;
- tests;
- binaries and OCI packaging;
- affected-target analysis;
- clean-checkout builds;
- remote cache and remote execution where appropriate;
- release target composition;
- build metadata and provenance inputs.

Use Bzlmod through `MODULE.bazel`. Do not introduce a legacy `WORKSPACE` dependency graph.

Bazel must not become a second handwritten dependency registry that drifts from native manifests. Repository rules and module extensions should consume or validate native lock state where practical.

### A9.2 Native ecosystem managers remain authoritative

| Ecosystem | Root policy |
|---|---|
| Python | One root `uv` workspace and lockfile; a small number of workspace members aligned to real packaging/environment boundaries |
| Rust | One root Cargo workspace and `Cargo.lock`; workspace-inherited metadata, lints, and dependencies |
| Go | One root `go.mod` for internal Go code; avoid a committed `go.work` unless Mindclade intentionally adopts multiple independently released modules |
| TypeScript | One `pnpm` workspace and lockfile; internal packages use `workspace:` references |
| Protobuf | One Buf workspace/configuration; lint and breaking checks required |
| Nix | One flake and lockfile for developer tools, native libraries, and reproducible shells |
| Bazel | One `MODULE.bazel` and pinned Bazel version |

### A9.3 Python environment policy

Use one lockfile, but expose named dependency groups and execution profiles:

- `dev`: formatting, linting, type checking, unit testing;
- `cpu`: CPU-only model smoke tests and data tools;
- `gpu`: PyTorch, CUDA-integrated packages, training and inference;
- `gpu-megatron`: optional Megatron Core provider and its qualified dependencies;
- `gpu-transformer-engine`: optional Transformer Engine precision/kernel provider;
- `rl`: TorchForge/Monarch-compatible post-training and multi-role execution dependencies;
- `docs`: documentation build;
- `release`: wheel and package tooling.

Rules:

- workspace members are release or environment boundaries, not every directory;
- all production packages use `src/` layout when packaged as wheels;
- no editable-path behavior is required in CI;
- package imports must work from an installed wheel and from Bazel;
- GPU images consume a locked, exported dependency set;
- custom wheels are mirrored into a controlled package store;
- all optional GPU/provider groups resolve through the same root lockfile and are promoted only after compatibility and numerical qualification;
- production images include only the provider groups declared by their component manifest;
- `libs/python` remains torch-free.

### A9.4 Rust workspace policy

- Put shared dependency versions, package metadata, and lints at workspace root.
- Keep crates cohesive; do not create one crate per source file.
- Prefer pure Rust APIs internally.
- Put unsafe code behind narrow modules with explicit invariants and tests.
- Treat Python bindings as adapters over stable Rust libraries, not the canonical implementation.
- Run `cargo check`, tests, clippy, formatting, dependency auditing, and Bazel parity checks.

### A9.5 Go module policy

Use one internal module at the repository root. Recommended import path:

```text
github.com/mindclade/mindclade
```

This avoids a vanity-domain availability dependency for private internal builds. Public Go SDKs can later move to a dedicated public repository and a stable vanity import path if external distribution justifies it.

Rules:

- deployable binaries live under `cmd/`;
- non-public service code lives under service-local `internal/`;
- horizontal libraries live under `libs/go/`;
- do not create a `go.mod` in every library;
- service modules do not share database implementation packages;
- CI tests the repository without hidden local replacements.

### A9.6 TypeScript workspace policy

- Use scoped packages such as `@mindclade/sdk`, `@mindclade/design-system`, and `@mindclade/config`.
- Apps consume packages through declared exports, never relative paths escaping package roots.
- Generated protocol clients are wrapped by SDK layers rather than imported directly throughout UI features.
- Keep browser-safe packages separate from Node-only packages.
- Apply strict TypeScript settings and API-extractor-style public surface checks for released packages.

### A9.7 Nix responsibility

Nix pins:

- compiler and interpreter toolchains;
- Bazel, Buf, Node, pnpm, uv, Rust, Go, and native build utilities;
- system libraries needed by parsers and native extensions;
- consistent local shells for CPU, GPU-tooling, docs, and release work.

Nix does not replace `uv.lock`, `Cargo.lock`, `go.mod`, or `pnpm-lock.yaml`. It pins the tools that interpret them and the system-level dependencies they cannot express cleanly.

### A9.8 Command ergonomics

`justfile` is a discoverable command index, not a second build system.

Recommended commands:

```text
just bootstrap
just doctor
just format
just lint
just test
just test-affected
just build
just build-affected
just proto
just docs
just train-smoke
just train-plan
just train-contracts
just train-normalization-test
just train-checkpoint-drill
just train-step-capsule
just train-qualify
just inference-smoke
just kernel-qualify
just integration
just release-check
```

Each command delegates to Bazel or a native tool. Complex logic belongs in tested programs under `tools/`, not shell one-liners embedded in `justfile`.

### A9.9 Four-layer build model

Mindclade separates:

```text
native dependency resolution
→ pinned toolchain environment
→ Bazel integration and execution graph
→ release assembly and provenance
```

Native managers resolve ecosystem dependencies and preserve normal developer workflows. Nix pins interpreters, compilers, system libraries, and command-line tools. Bazel defines hermetic actions, visibility, code generation, tests, and release composition. The release system records and attests the complete input closure.

No layer may silently re-resolve or override another layer’s dependency truth.

### A9.10 Hermeticity contract

A release action must declare all source, tool, environment, and network inputs. It must not depend on:

- developer home directories;
- ambient credentials;
- untracked Git files;
- mutable package indexes without locked hashes;
- system compiler or CUDA paths not represented by the toolchain;
- network downloads during the action unless executed by a pinned repository fetch with integrity;
- current time for artifact contents;
- nondeterministic archive ordering or metadata.

Builds normalize timestamps, file order, ownership metadata, locale, and timezone where the artifact format permits.

### A9.11 Bazel module and rules policy

Bzlmod is the only external Bazel dependency mechanism. Module extensions may bridge native lockfiles into Bazel, but they must be deterministic, versioned, tested, and avoid creating an independent handwritten dependency list.

Custom rules and macros require:

```text
owner
stable provider contract
hermetic action inputs/outputs
toolchain declaration
remote-execution behavior
sandbox test
failure diagnostics
migration and compatibility policy
```

Rules should expose domain-neutral build behavior; product semantics remain in ordinary code.

### A9.12 Remote cache and remote execution

Remote cache keys include all declared action inputs and platform properties. Cache policy distinguishes:

- trusted versus untrusted namespaces;
- CPU versus GPU/toolchain platforms;
- read-only versus write authority;
- release versus development artifacts;
- sensitive output classes.

Untrusted builds cannot poison trusted caches. Release jobs may consume only cache entries produced under compatible trusted identities or recompute actions.

Bazel HTTP cache responses can expose action-cache records, CAS outputs, and captured stdout/stderr. Public-readable and private-internal entries therefore use separate GCP buckets or equivalently IAM- and cryptographically isolated namespaces. The default classification is private; only an explicit target allowlist permits public publication. Writer IAM remains denied until the producing builder identity, target class, and platform envelope are qualified.

The cache namespace/key contract binds:

```text
cache schema version
trust class
operating platform
machine architecture
complete toolchain identity
build mode
ordinary Bazel action identity
```

A public/private or other classification change revokes existing access and rotates to a new namespace. Existing objects are not relabeled in place. Noncurrent namespace versions have short lifecycle retention. Read/write access logs are exported to a separate destination outside cache-writer mutation authority.

Qualification periodically forces a cacheless canary and compares the resulting digests with compatible cached outputs. Suspected cache poison invokes namespace write denial/revocation, clean cacheless rebuild, and digest comparison before read authority is restored. Release provenance records cache consultation, namespace identity, and hit/miss state, but the cache is never evidence and does not replace provenance, SBOM, qualification, signature, or reproducibility evidence.

Repository authority is deliberately split. The monorepo owns machine-readable cache classification, key-shape, public-target allowlist, canary, and poison-recovery contracts. `bootstrap` owns foundational GCP trust and identity. `infrastructure-live` owns bucket, IAM, log-destination, and lifecycle desired state. Source policy does not claim connected GCP implementation.

Remote execution workers are immutable or regularly rebuilt, have restricted egress, no persistent credentials, bounded local state, and platform labels that accurately describe CPU, OS, accelerator, driver, and toolchain capabilities.

### A9.13 Python lock and environment architecture

The root uv workspace shares one lock universe. Dependency groups are selected at install/build time, but resolution compatibility is validated together except for explicitly declared mutually exclusive forks. Provider or hardware forks must remain visible and reproducible rather than relying on manual pip commands.

Required checks include:

- lockfile freshness against every workspace member;
- hashes and controlled indexes for production dependencies;
- CPU profile that excludes torch/CUDA where not needed;
- provider groups absent from unrelated images;
- wheel build/install tests without editable paths;
- import graph and native-library resolution checks;
- license/vulnerability inventory from the resolved lock;
- export parity between uv, Nix image construction, and Bazel.

### A9.14 Rust build architecture

Cargo remains authoritative for crate resolution and features. Bazel consumes the workspace graph and validates parity.

Policy includes:

- one root lockfile;
- resolver and edition pinned at workspace root;
- inherited dependency versions and lints;
- minimal supported feature combinations explicitly enumerated;
- reproducible native dependencies through Nix/Bazel toolchains;
- `cargo vendor` or controlled mirrors only when required by release isolation;
- symbol/size and unsafe-code reports for release crates;
- cross-language binding wheels built from the same core crate revision.

### A9.15 Go build architecture

The root module is authoritative. Build rules use the same `go.mod` and `go.sum` closure. CI rejects local `replace` directives or hidden workspace state not intended for the repository.

Release binaries are built with reproducible version metadata, minimal embedded paths, explicit build tags, and platform constraints. CGO is disabled by default unless a component declares and qualifies a native dependency.

### A9.16 TypeScript build architecture

The pnpm workspace uses locked, workspace-scoped dependencies. Policy requires:

- `workspace:` references for internal packages;
- frozen lock install in CI;
- browser/Node export separation;
- deterministic bundling and source-map policy;
- dependency graph and license checks;
- public package API extraction;
- no postinstall network or privileged scripts unless explicitly reviewed;
- generated clients built before SDK/app compilation through declared graph edges.

### A9.17 Protobuf and schema generation

Code generation is a first-class Bazel graph:

```text
source schema
→ lint and compatibility validation
→ descriptor/image
→ language generation
→ SDK adapters/docs/OpenAPI
→ drift and conformance tests
```

Generators and plugins are pinned by digest/version. Generated outputs carry source and generator identity. A generator upgrade is treated like a compatibility-affecting dependency change.

### A9.18 Native, CUDA, and kernel toolchains

GPU build platforms declare:

```text
accelerator architecture
CUDA/ROCm toolkit
compiler and linker
PyTorch ABI
TileLang/native compiler revision
driver compatibility floor
collective and math libraries
```

Fat binaries are used only when their size and qualification cost are justified. Hardware-specific artifacts remain separate when dispatch or reproducibility requires exact identity.

No release depends on an engineer’s locally installed CUDA toolkit. Critical generated kernels and compiled regions are promoted as immutable artifacts or rebuilt in an identical attested toolchain.

### A9.19 Dependency update workflow

```text
update proposal
→ resolve native lockfiles
→ regenerate Bazel integration
→ inspect transitive and license changes
→ build all affected platform profiles
→ run compatibility/security/numerical qualification
→ publish update report
→ merge and promote
```

High-risk updates include PyTorch, CUDA/ROCm, compilers, collective libraries, serialization, cryptography, databases, providers, and schema generators. They receive expanded qualification and rollback artifacts.

### A9.20 Third-party source and patch policy

Every patch records:

- upstream project and revision;
- reason upstream cannot yet be consumed directly;
- patch owner;
- applicable versions;
- upstream issue/PR where possible;
- license impact;
- tests proving necessity;
- removal condition.

A patch queue that no owner can rebase is a release blocker.

### A9.21 Build observability and evidence

Build records include:

```text
target and configuration
source revision and dirty-state rejection
native lockfile digests
Bazel module and toolchain digests
platform properties
remote-cache hit/miss and provenance
network accesses allowed during fetch
outputs and digests
reproducibility comparison when sampled
```

Build telemetry must not include credentials or private source contents.

### A9.22 Build qualification levels

| Level | Evidence |
|---|---|
| B0 | local/native build and unit tests |
| B1 | Bazel sandbox and clean checkout |
| B2 | remote cache/exec parity and platform matrix |
| B3 | release packaging, SBOM, provenance, signature |
| B4 | reproducible rebuild or declared equivalence |
| B5 | isolated trusted builder and admission verification |

Each release target declares the minimum level.

### A9.23 Capability-local qualification progression

1. Align native manifests, lockfiles, and Bazel graph.
2. Establish CPU clean-checkout and remote cache.
3. Add GPU/native toolchains and image profiles.
4. Add reproducible release assembly, SBOM, provenance, and signing.
5. Add trusted/untrusted isolation and rebuild verification.

### A9.24 Definition of done

1. Native and Bazel dependency graphs cannot drift silently.
2. A clean checkout builds every release target under pinned tools.
3. CPU contributors do not install the GPU/provider stack.
4. Untrusted builds cannot poison trusted caches or publish artifacts.
5. GPU artifacts identify exact hardware and compiler compatibility.
6. Dependency upgrades produce reviewable compatibility and qualification evidence.
7. Release manifests record the complete build input and output closure.
8. Promotion never rebuilds.
