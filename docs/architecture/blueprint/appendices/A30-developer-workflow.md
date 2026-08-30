## Appendix A30 — Developer workflow

### First checkout

```bash
nix develop
just doctor
just bootstrap
just test-affected
```

A developer without Nix may use documented native setup, but CI and release behavior are defined by pinned toolchains.

### Normal change

```bash
just format
just lint
just test-affected
just build-affected
```

### Model change

```bash
just test //models/...
just test //kernels/... --config=gpu
just train-smoke
just train-plan
just train-contracts
just train-normalization-test
just train-checkpoint-drill
just train-step-capsule
just train-qualify
just inference-smoke
just evaluation-smoke
```

### Protocol change

```bash
just proto
bazel test //protocols/...
```

### Release qualification

```bash
just release-check
```

Local commands never publish or deploy by default.

### A30.1 Developer experience objectives

A developer should move from clean checkout to a correct affected change without hidden workstation state. The workflow optimizes:

```text
fast orientation
reproducible environment
clear ownership and boundaries
small feedback loops
safe access to remote GPU/integration resources
high-fidelity preflight before CI
reproducible diagnosis and handoff
```

Local convenience cannot diverge from CI/release semantics. Fast paths are subsets of the same contracts, not alternate scripts.

### A30.2 Supported development profiles

| Profile | Purpose |
|---|---|
| `core` | repository tools, protocols, Go/Rust/libs, docs |
| `cpu` | data, model/evaluation references, training smoke without CUDA |
| `gpu` | local/single-node model, kernel, training, inference |
| `docs` | Astro/docs tooling and examples |
| `release` | packaging/signing verification without production credentials |
| `remote-gpu` | source-synchronized or remote checkout with leased accelerator |

Profiles use the same root lockfiles and pinned tools. `just doctor` reports unsupported host capabilities and remediation.

### A30.3 Bootstrap protocol

`just bootstrap` performs only deterministic setup:

1. verify required pinned tool versions or enter the Nix shell;
2. configure local caches and repository hooks;
3. install/prepare locked dependencies without mutation;
4. generate only required local artifacts;
5. verify source tree and toolchain health;
6. run a minimal smoke target.

It does not request production credentials, alter global system packages without consent, download large model/data artifacts, or hide failures.

### A30.4 Developer doctor

`just doctor` checks:

```text
OS/architecture and filesystem features
Nix/Bazel/uv/Cargo/Go/pnpm/Buf versions
lockfile and generated-code drift
compiler/native libraries
container/runtime setup
GPU/driver/CUDA and device health when requested
remote cache/exec connectivity
credential providers without printing secrets
Git hooks, branch, and working-tree state
available disk/memory
```

Output separates required errors, optional degraded capabilities, and actionable commands.

### A30.5 Repository orientation

A new contributor can discover:

- top-level domain map and dependency laws;
- component owners and maturity;
- common commands;
- local/remote execution profiles;
- data/security restrictions;
- how to add each package/component type;
- how release and deployment boundaries work;
- where architecture, ADRs, runbooks, and examples live.

`README.md`, `docs/developer/`, component metadata, and `just --list` agree. Generated tree/catalog pages reduce stale manual inventories.

### A30.6 Normal edit-test loop

The local loop is:

```text
edit
→ targeted native formatter/linter/type check
→ Bazel/native unit target
→ affected-target plan
→ higher-cost integration/GPU test only when affected
→ inspect diff and generated changes
→ commit/push
```

Editor integrations call the same formatters/type systems. Save-time tooling never rewrites unrelated files or changes lockfiles implicitly.

### A30.7 Affected-target inspection

Developers can run:

```bash
just affected
just test-affected --explain
just build-affected --explain
```

The explanation names changed targets, reverse dependencies, global invalidators, selected tests, excluded expensive lanes, and expected CI additions. This makes CI planning understandable and helps catch missing metadata before push.

### A30.8 Code generation workflow

Code generation is one command per source-of-truth family and is hermetic. Developers can preview generated diffs and verify drift. Generated outputs identify source and generator digest.

Adding a generator requires an owner, deterministic inputs, formatting, collision policy, Bazel/native integration, clean-checkout test, and documentation. Generation never depends on a network service or local IDE plugin for release.

### A30.9 Protocol development

A protocol change workflow includes:

```text
edit source schema
→ lint and compile
→ breaking check against protected baseline
→ regenerate required clients/docs
→ run service and SDK conformance fixtures
→ document migration/deprecation
```

Local tools explain field-number/name reservations and affected consumers. Experimental protocols are visibly namespaced and cannot accidentally enter stable SDKs.

### A30.10 Biological/data development

Parser and data changes use small legal fixtures locally and artifact-backed representative corpora remotely. The developer can:

- run strict/permissive parser diagnostics;
- compare Rust/Python conformance;
- replay a source object or bad-record reference;
- inspect lineage and validation reports;
- generate deterministic synthetic fixtures;
- test connector offline mode;
- run sample identity/dedup/leakage/split checks;
- estimate feature/work-unit distributions.

Raw restricted data is never copied into repository fixtures or chat/issue attachments.

### A30.11 Model development

Model changes start with typed configuration and reduced reference fixtures. The workflow covers:

```text
CPU/reference forward and schema
initialization/state identity
forward/backward and numerical fixtures
feature compatibility
checkpoint save/load/migration
single-GPU smoke
kernel/provider optional comparison
training and inference vertical smoke
evaluation regression
```

A model developer does not need to write a worker, queue consumer, or provider-specific launcher.

### A30.12 Kernel development

Kernel tooling provides:

- operation/reference scaffold;
- shape/dtype/layout fixture generation;
- local compile and cache inspection;
- forward/gradient/finite-difference comparison;
- deterministic replay from a failure artifact;
- benchmark protocol with environment capture;
- autotune record generation;
- shadow qualification;
- bundle/dispatch validation.

Local benchmark results are labeled non-promotional unless produced on controlled qualified hardware.

### A30.13 Training development

The training developer interface uses one trainer and layered profiles:

```bash
mindclade train plan ...
mindclade train run ... --profile deterministic_reference
mindclade train run ... --profile single_optimizer_step
mindclade train reproduce-step ...
mindclade train qualify ...
```

Developers can inspect resolved recipes, state registry, parameter update graph, executable plan, process groups, memory estimates, BatchReceipts, and checkpoint contents without starting a frontier run.

### A30.14 Service development

A local service stack provides database, queue emulator/adapter, artifact store, control plane, and selected workers through reproducible containers or test harnesses. It supports:

- migrations from empty and historical fixtures;
- deterministic identity/auth test principals;
- outbox/queue delivery;
- duplicate/lease/cancel/failure injection;
- API/SDK conformance;
- traces/logs/metrics;
- cleanup/reset.

Local emulation is clearly distinguished from production cloud/Kubernetes behavior, with integration lanes covering real managed dependencies.

### A30.15 Remote GPU and workstation workflow

Long-lived remote development uses a persistent home/cache and `tmux` or equivalent, but source and results remain reproducible. Recommended flow:

```text
create/lease approved workstation or GPU session
→ checkout exact branch/revision
→ enter pinned environment
→ authenticate with developer-scoped identity
→ fetch only authorized artifacts
→ run targeted commands
→ publish useful results as artifacts/reports
→ release capacity and clean sensitive scratch
```

Long jobs run through durable Buildkite/control-plane workloads, not an interactive shell that depends on a browser or laptop connection.

### A30.16 Debugging and reproduction

Debug tools resolve stable identities:

```text
request/job/run/attempt
artifact/checkpoint/snapshot
BatchReceipt/StepCapsule
executable plan/provider/kernel
source revision/image/toolchain
```

A developer can materialize an approved minimal reproduction without copying raw payloads into logs. Debug profiles support anomaly detection, flight recorders, memory snapshots, compile explanation, and controlled reference comparisons.

### A30.17 Tests and local resource budgets

Tests declare expected time/resource class. Default local commands avoid unbounded downloads, high GPU counts, and multi-hour suites. Expensive targets print how to run them remotely/through CI and what evidence they generate.

A test exceeding its declared budget is reclassified or optimized. Developers can filter by tag but cannot mark required evidence as passed without executing it.

### A30.18 Dependency changes

Adding/upgrading a dependency follows:

1. justify owner/use and preferred existing alternative;
2. update the native authoritative manifest/lock;
3. reconcile Bazel/Nix integration;
4. run license/security/supply-chain checks;
5. test affected targets and optional provider groups;
6. record significant compatibility/qualification impact;
7. remove abandoned dependency paths.

No command performs broad uncontrolled upgrades as a side effect of bootstrap.

### A30.19 Change review checklist

A pull request states:

```text
problem/outcome
scope and non-goals
architecture/contracts affected
source and generated changes
tests/qualification run
security/data implications
migration/rollout/rollback
known limitations/follow-up
```

Reviewers focus on ownership, semantics, failure behavior, compatibility, and evidence—not only style. Large generated or lockfile diffs are separated/explained where possible.

### A30.20 Commit and branch hygiene

Changes are reviewable, bisectable, and pass required checks. Do not mix unrelated formatting, dependency upgrades, generated churn, and architecture changes. Temporary branches may be rebased/squashed according to team policy, but protected history/release identities remain immutable.

Secrets or restricted data discovered in Git trigger incident/removal procedures; deleting the latest commit is insufficient.

### A30.21 Documentation as part of change

A change updates the nearest authoritative docs:

- package README for API/usage/failure changes;
- domain architecture for contract changes;
- ADR for durable decisions;
- runbook for operational changes;
- model/data card for released scientific changes;
- SDK/API reference and examples for public changes;
- migration/deprecation notes.

Docs snippets and commands are tested where practical.

#### A30.21.1 Architecture source and render workflow

The 20,000+ line combined architecture document is a generated review/distribution artifact, not the preferred human edit surface. Architecture authors edit the ordered sources declared by `docs/architecture/blueprint/manifest.yaml`:

```text
docs/architecture/blueprint/
├── manifest.yaml
├── sections/01-... through 18-...
├── appendices/A01-... through A40-...
└── generated/MINDCLADE_MONOREPO_BLUEPRINT_FULL.md
```

`manifest.yaml` records document ID/version, ordering, heading/anchor expectations, source paths, generated destination, and the repository-path manifest reference. `tools/docs/render_architecture_blueprint.py` concatenates and normalizes the sources deterministically; `validate_blueprint_sources.py` checks section/appendix numbering, duplicate anchors, placeholder markers, source inclusion, link targets, generated-tree synchronization, and document-control consistency.

The required authoring flow is:

```text
edit smallest owning section/appendix or machine-readable manifest
→ run architecture source validation
→ render combined blueprint
→ render A6 from repository-path-manifest.yaml
→ compare generated outputs
→ run Markdown/anchor/contract checks
→ review generated diff together with source diff
```

The combined render carries the same approved normative content, but no engineer manually patches its generated body. A change that modifies the generated full blueprint without the owning source file fails CI. This preserves the user's required complete blueprint and explicit repository tree while reducing merge conflict and reader-maintenance cost.

### A30.22 Developer security

Developer access is least privilege and environment-separated. Requirements include secure credential storage, MFA, no production data on unmanaged devices, restricted artifact access, safe support bundle handling, dependency/script review, and rapid revocation.

Local tools default to non-production endpoints and require explicit context for destructive or privileged operations. Commands print the active environment/tenant before dangerous actions.

### A30.23 Developer support and feedback

The repository provides one discoverable issue/support path for broken bootstrap, CI, tooling, and architecture questions. Tool failures emit diagnostic bundles that redact secrets and include versions/commands. Recurring friction becomes tooling/docs work rather than tribal knowledge.

### A30.24 Developer workflow qualification

| Level | Required evidence |
|---|---|
| `dev-d0` | clean bootstrap/doctor, docs, format/lint/unit loop |
| `dev-d1` | affected targets, codegen, protocol/data/model/service local workflows |
| `dev-d2` | remote GPU, reproducible diagnostics, dependency and migration workflows |
| `dev-d3` | onboarding study, clean-checkout parity, access/security, sustained CI feedback SLO |

### A30.25 Capability-local qualification progression

**Milestone 0 — clean checkout:** Nix/native setup, `just` command index, doctor/bootstrap, root docs, formatting/lint/test-affected.

**Milestone 1 — domain workflows:** protocol, data, model, kernel, training, service, and SDK scaffolds/examples tied to real targets.

**Milestone 2 — remote and diagnosis:** workstation/remote GPU profile, artifact-based reproduction, step capsules, service failure injection, CI explanations.

**Milestone 3 — scale and support:** onboarding metrics, developer portal/catalog, fast feedback SLOs, secure access lifecycle, and recurring-friction governance.

### A30.26 Definition of done

Developer workflow is production-ready when:

1. a clean checkout can enter a pinned supported environment and pass a smoke target without undocumented manual state;
2. local commands delegate to the same build/test contracts used by CI and release;
3. affected-target plans are inspectable and conservative under ambiguity;
4. every major domain has a focused reference workflow and real example;
5. developers can inspect immutable configuration/state/plan/artifact identities before expensive execution;
6. remote GPU work and long jobs survive local connectivity loss through persistent/durable systems;
7. debugging uses sanitized reproducible artifacts rather than payload dumps or workstation archaeology;
8. dependency/codegen/migration changes are deterministic and reviewable;
9. security defaults prevent accidental production, secret, or restricted-data exposure;
10. onboarding and feedback-loop health are measured and recurring friction is repaired.

### A30.27 Final developer invariants

- local convenience is a faithful subset of production behavior;
- clean checkout is the baseline, not a senior engineer's workstation;
- long work has a durable remote execution identity;
- every expensive action can be planned/inspected before allocation;
- reproduction uses immutable artifacts and manifests;
- documentation and tooling replace tribal setup knowledge.
