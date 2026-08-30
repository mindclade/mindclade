## Appendix A21 — CI architecture

### A21.1 GitHub Actions

Use GitHub Actions for fast, organization-integrated checks:

- PR metadata and policy;
- CODEOWNERS/approval validation;
- lightweight formatting and configuration validation;
- docs links/build smoke test;
- Protobuf breaking-change signal;
- dependency review;
- required-check aggregation;
- Buildkite trigger/status bridge;
- mirror verification and repository administration.

Do not run expensive GPU or large distributed qualification on shared GitHub-hosted runners.

### A21.2 Buildkite

Buildkite is authoritative for:

- Bazel affected-target planning;
- CPU builds and tests;
- remote cache/execution;
- GPU tests and kernel qualification;
- distributed training/inference smoke tests;
- training contract, logical-state, phase-graph, BatchReceipt, executable-plan, and provider compatibility validation;
- loss-normalization, microbatch-invariance, snapshot-fencing, resharding, checkpoint-corruption, and failure-injection suites;
- compiled-region graph-break, AOT/cache, and step-capsule reproduction suites;
- model-family long-horizon convergence qualification on scheduled lanes;
- large integration suites;
- nightly data/model validation;
- clean-checkout release qualification;
- OCI/wheel/npm/binary/model-bundle publication;
- provenance, SBOM, signing, and attestations.

Generate a dynamic pipeline from:

- changed files;
- reverse dependency graph;
- component metadata;
- trust context;
- target tags;
- release intent.

Persist the generated pipeline as an artifact so every build can be audited.

### A21.3 Pipeline stages

```text
1. repository metadata, repository-path manifest, architecture-source manifest, generated A6/full-blueprint drift, and trust validation
2. protocol/schema compatibility
3. affected target calculation
4. formatting, linting, type checks, unit tests
5. builds and package tests
6. domain contract/conformance tests, including feature-plan lowering, transform profiles, semantic/execution identity, fit-state/leakage, and lineage-map reconstruction when affected
7. integration and service tests
8. numerical/kernel/GPU qualification when affected
9. training contracts, logical state, loss normalization, and executable-plan qualification when affected
10. provider, precision, kernel, and compiled-region qualification when affected
11. distributed checkpoint, snapshot fencing, reshard, recovery, and failure tests when affected
12. step-capsule reproduction and asynchronous-evaluation tests when affected
13. scheduled long-horizon model/convergence qualification
14. release packaging
15. SBOM, signing, provenance, policy verification
16. publish immutable artifacts
```

### A21.4 Test tags

Standard Bazel tags:

```text
small
medium
large
network
integration
gpu
gpu-h100
gpu-h200
gpu-b200
distributed
exclusive
flaky-quarantine
numerical
kernel
performance
release
training
checkpoint
recovery
state-schema
batch-receipt
normalization
compiled-region
step-capsule
provider
long-horizon
rl
```

A quarantined flaky test still runs on a visible lane and has an owner and expiry. It is never silently removed from CI.

### A21.5 Trusted and untrusted builds

Untrusted pull requests:

- receive no production secrets;
- cannot write shared release caches;
- cannot publish artifacts;
- use isolated workers and cache namespaces;
- have restricted network access;
- cannot execute arbitrary privileged deployment logic.

Trusted protected-branch and release builds use OIDC/workload identity rather than long-lived cloud keys.

### A21.6 CI control planes and trust model

CI has separate control planes:

```text
GitHub event and policy plane
→ Buildkite authoritative execution plane
→ artifact/provenance plane
→ release/promotion eligibility plane
```

GitHub determines repository event context and required-check presentation. Buildkite plans and executes authoritative workloads. Artifact registries store immutable outputs. GitOps consumes promoted digests. No pull-request workflow directly deploys to production.

### A21.7 Build identity

Every CI build has a canonical identity containing:

```text
source repository and revision
merge/base revision and changed-file set
trigger type and actor
trusted/untrusted context
pipeline generator revision and digest
lockfile/toolchain/image digests
Buildkite/GitHub execution identifiers
release intent and target channel
```

The identity is attached to test reports, caches, artifacts, attestations, and annotations. A rerun preserves source identity but receives a distinct execution attempt.

### A21.8 Dynamic pipeline model

The pipeline generator is a tested program that consumes:

```text
source diff and base
Bazel reverse dependency graph
component.yaml catalog
target tags and execution requirements
protocol/schema ownership
trust context
historical timing and shard metadata
release intent
```

It emits a deterministic pipeline model and serialized audit artifact. The generator has unit/property tests for path mappings, deletions, renames, generated files, top-level build changes, and unknown components. Ambiguity expands coverage; it never silently drops tests.

### A21.9 Affected-target correctness

Affected-target analysis includes:

- direct changed targets;
- reverse dependencies;
- code-generated consumers;
- compatibility baselines;
- deployment/package/release consumers;
- tests selected by tags and component metadata;
- global invalidators such as lockfiles, toolchains, Bazel rules, schemas, and CI code.

CI continuously audits selection with scheduled full or sampled full runs. A missed dependency is treated as a correctness defect in the planner and produces regression fixtures.

### A21.10 Pipeline trust classes

| Class | Source | Credentials/network/cache/publish policy |
|---|---|---|
| untrusted PR | fork or untrusted author/context | no secrets, isolated workers/cache, restricted network, no publish |
| trusted PR | approved internal context | limited test credentials, no release publish |
| protected branch | merged protected revision | workload identity, shared read/write build cache, internal artifacts |
| release | protected tag/approval | isolated signing/publishing identity and policy gates |
| scheduled qualification | protected revision | dedicated CPU/GPU/distributed capacity, bounded privileged access |

A pull-request approval does not automatically make arbitrary workflow code trusted. Trusted execution uses a protected pipeline definition or explicit safe handoff.

### A21.11 GitHub Actions responsibilities

GitHub workflows are minimal and pinned. They validate event metadata, ownership, approvals, commit/PR policy, docs smoke checks, dependency review, and trigger/status exchange. They use least-privilege permissions and OIDC only where a narrowly scoped action requires it.

Required-check aggregation verifies that the expected Buildkite plan completed for the exact revision and trust context. A green bridge cannot point to an older build or different commit.

### A21.12 Buildkite bootstrap and hooks

Hooks establish a clean, attestable environment:

```text
verify agent/pool identity
sanitize inherited environment
establish source checkout and revision
configure trust-scoped cache/network/credentials
load pinned toolchains and build image
emit build metadata
run command
collect reports and clean workspace
```

Hooks contain no domain logic. Shared logic lives in tested libraries. Secrets are short-lived and injected only into steps that declare them.

### A21.13 CPU test and build lanes

CPU lanes cover formatting, static analysis, protocol/schema compatibility, unit/property/fuzz tests, service/database integration, parser/data fixtures, model CPU or reduced references, documentation, package builds, and architecture policy.

Tests are sharded by measured duration while preserving deterministic membership and report aggregation. A shard failure identifies exact tests. Retry is test-policy aware, not a blanket rerun that hides flakiness.

### A21.14 GPU and distributed lanes

GPU lanes are scheduled by explicit tags and capability requirements:

```text
accelerator architecture and count
memory class
single-node or multi-node
driver/CUDA/runtime image
RDMA/network topology
exclusive/shared policy
expected duration and preemption class
```

A test receives the smallest qualifying resource profile. H100 evidence does not imply H200/B200 evidence. Distributed tests verify topology manifests and fail when allocated hardware differs materially from the requested profile.

### A21.15 Numerical and long-horizon lanes

Numerical lanes compare exact operation, model, provider, precision, and plan identities. Long-horizon lanes are scheduled, budgeted qualifications with immutable datasets, checkpoints, and reports. Their failure blocks only the maturity/release scopes they protect, but cannot be dismissed as ordinary flaky tests.

Baseline updates require a reviewed evidence artifact, owner, rationale, tolerances/statistical method, and expiry/review date.

### A21.16 Data and network tests

Presubmit defaults to offline fixtures. Network tests are explicit, sandboxed, rate-limited, and normally scheduled or trusted. They never rely on mutable live data for deterministic correctness.

Connector qualification separates:

- offline protocol/fixture correctness;
- controlled source compatibility checks;
- full ingestion validation on immutable source revisions.

Downloaded material is scanned/classified and is never written to an untrusted shared cache.

### A21.17 Cache architecture

Caches are accelerators, never sources of release truth. Cache keys include all relevant source, flags, toolchains, platform, environment, and trust identity.

Rules:

- untrusted builds cannot poison trusted write namespaces;
- release steps verify outputs and provenance independent of cache hit;
- secret-bearing or tenant data is not cacheable in shared build caches;
- cache servers use access control, encryption, quotas, and eviction;
- hit/miss/corruption rates are monitored;
- suspected poisoning triggers namespace revocation and clean rebuild.

### A21.18 Remote execution

Remote execution workers are immutable, capability-labeled, isolated, and observable. Actions declare CPU, memory, disk, network, OS, architecture, GPU, and privileged requirements. Undeclared network access is denied where feasible.

Remote workers clean between actions and do not retain credentials or source beyond policy. Reproducibility audits compare local/remote or cache-disabled builds for selected targets.

### A21.19 Test result and evidence model

Every test emits structured status plus optional artifacts:

```text
target/test identity
source and execution environment
attempt and shard
start/end/duration
pass/fail/skip/quarantine
failure classification
log and report references
numerical/performance evidence digests
resource usage summary
```

JUnit alone is insufficient for numerical, qualification, or security evidence; domain reports are linked. Logs are redacted and retention/classification aware.

### A21.20 Flaky-test governance

A flaky test is quarantined only with:

- owner;
- issue and root-cause hypothesis;
- first-seen evidence;
- quarantine scope;
- continued visible execution;
- expiry;
- release impact.

Retries distinguish infrastructure flake from deterministic failure and record all attempts. A test that passes on retry still reports flakiness. Chronic quarantine blocks component maturity.

### A21.21 Failure classification and reruns

CI failures are classified:

```text
source/test failure
known quarantine
agent/infrastructure failure
capacity/preemption
external dependency
cache corruption
security/policy failure
unknown
```

Only infrastructure/capacity classes receive automatic step reruns, within budget. Source failures require a new commit or explicit operator rerun that remains visible. Release steps are idempotent and never duplicate publication after an unknown outcome.

### A21.22 Secrets and sensitive data

CI uses workload identity and secret brokers, not repository or agent-static keys. Steps declare required secret scopes. Masking supplements but does not replace prevention.

Untrusted builds cannot access:

- production/cloud credentials;
- signing identities;
- protected package/OCI write paths;
- restricted biological fixtures;
- shared mutable release caches;
- internal network destinations beyond allowlist.

Artifacts and logs are scanned before publication where appropriate.

### A21.23 Release pipeline

The release lane performs:

```text
verify protected source and approvals
→ clean checkout and locked dependency resolution
→ complete required qualification matrix
→ build once
→ generate SBOM/provenance/manifest
→ sign immutable artifacts
→ verify installation/runtime smoke
→ publish to staging channel
→ policy approval and promotion eligibility
```

Promotion moves or references the exact digest. A failed publication is reconciled by registry query and manifest identity before retry.

### A21.24 Pipeline performance and cost

CI tracks:

- queue and execution time by lane;
- critical-path duration;
- cache hit and remote-execution efficiency;
- test shard imbalance;
- GPU utilization and idle allocation;
- flaky/retry rate;
- affected-target selectivity and missed-target audits;
- cost by component/change class;
- release frequency and failure rate.

Optimization may not reduce required evidence. Expensive lanes are made more selective through correct dependency metadata, not by deleting qualification.

### A21.25 CI resilience and disaster recovery

Runbooks cover Buildkite/GitHub outage, agent-pool compromise, cache corruption, registry outage, signing failure, queue saturation, and lost test artifacts. The repository contains enough pipeline source to recreate execution in a clean environment. Critical configuration and credentials are recoverable through the separate bootstrap/governance repositories.

A mirror verification lane proves source portability and disaster-recovery assumptions without becoming a second authoritative CI control plane.

### A21.26 CI qualification levels

| Level | Required evidence |
|---|---|
| `ci-c0` | deterministic pipeline generation, policy checks, local/CPU presubmit |
| `ci-c1` | affected-target graph, cache isolation, service/parser/model package lanes |
| `ci-c2` | GPU/distributed scheduling, numerical evidence, flaky governance, failure classification |
| `ci-c3` | clean release, signing/SBOM/provenance, untrusted/trusted isolation, DR exercises |
| `ci-c4` | sustained SLO/cost/selectivity, full-run audit, agent/cache compromise drills |

### A21.27 Capability-local qualification progression

**Milestone 0 — trusted skeleton:** minimal GitHub workflows, Buildkite trigger/bridge, deterministic dynamic planner, protected agent pools, and structured reports.

**Milestone 1 — affected CPU monorepo:** Bazel reverse dependency analysis, component metadata, language lanes, cache isolation, and scheduled full validation.

**Milestone 2 — GPU/training qualification:** hardware-labeled pools, kernel/model/training matrices, multi-node failure tests, and long-horizon scheduled lanes.

**Milestone 3 — release and resilience:** build-once publication, signing/SBOM/provenance, promotion manifest, pipeline/agent/cache incident drills, and cost/SLO dashboards.

### A21.28 Definition of done

CI is production-ready when:

1. every required check maps to a deterministic, auditable plan for the exact source revision;
2. affected-target selection accounts for reverse, generated, compatibility, and release dependencies and is audited against fuller runs;
3. untrusted code cannot access secrets, trusted caches, privileged networks, or publication identities;
4. GPU/distributed evidence names exact hardware and software topology;
5. flaky tests remain visible, owned, expiring, and maturity-limiting;
6. retries cannot hide source failures or duplicate release publication;
7. release artifacts are built once from a clean checkout and include signed manifest, SBOM, provenance, and qualification evidence;
8. cache or remote execution compromise can be isolated and recovered;
9. logs/artifacts obey data-classification and retention policy;
10. CI performance and cost improve without weakening evidence.
11. repository-path and architecture source manifests regenerate Appendix A6 and the combined blueprint exactly from a clean checkout; generated/render drift cannot merge.
12. feature planning lowers into the generic transform substrate and transform/fitted-state contract changes trigger their conformance, leakage, lineage, and backend-equivalence suites.

### A21.29 Final CI invariants

- GitHub presents policy; Buildkite performs authoritative heavy execution;
- pipeline generation is production code with tests and artifacts;
- ambiguity broadens the test plan rather than narrowing it;
- trust context controls credentials, networks, caches, and publication;
- cached outputs are verified accelerations, not release truth;
- every release is tied to one source revision, one qualification set, and immutable artifacts.
