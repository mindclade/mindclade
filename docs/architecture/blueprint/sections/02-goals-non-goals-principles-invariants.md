## 2. Goals, non-goals, principles, and system invariants

### 2.1 Goals

The monorepo SHALL:

1. permit atomic changes from biological semantics through models, execution, contracts, clients, and release evidence;
2. make every production capability discoverable, owned, buildable, testable, and releasable from a clean checkout;
3. preserve correctness and lineage across duplicate delivery, retry, preemption, process failure, and topology-changing restart;
4. support proteins, RNA, DNA, small molecules, and complexes without creating separate platform stacks;
5. keep scientific and numerical semantics independent of control-plane, scheduler, cloud, and provider implementations;
6. deliver secure multi-tenant training, evaluation, inference, data, and agent workflows with attributable cost and auditable decisions;
7. qualify optimized implementations against transparent reference paths before use;
8. promote immutable, signed artifacts rather than rebuilding per environment; and
9. keep the simplest deployable topology that satisfies isolation, scale, and reliability evidence; and
10. reuse deterministic biological feature derivations safely across model families through explicit semantic contracts, complete derivation identities, immutable artifacts, and model-owned tensor views.

### 2.2 Non-goals

This architecture does not attempt to:

- create one programming language, package manager, database, or release version for the repository;
- make Bazel replace `uv`, Cargo, the root Go module, `pnpm`, Buf, or Nix in their authority domains;
- expose internal Protobuf APIs directly as a permanent public product API;
- allow notebooks, dashboards, Kubernetes status, caches, vector indexes, or provider metadata to become sources of truth;
- create a universal workflow engine, universal plugin framework, universal tensor IR, or cloud-portability abstraction ahead of two real implementations;
- execute arbitrary user code or unqualified customer tools inside trusted data, training, inference, or model workers;
- guarantee bitwise identity across all hardware; required tolerances are operation- and release-specific;
- pre-create public Go/Rust SDKs, live elasticity, RL/post-training, NVMe offload, Monarch orchestration, or specialized schedulers without activation evidence; or
- treat research output as production code without graduation and qualification;
- create a separate feature-store, model-named cache hierarchy, or mutable tensor directory that competes with `bio/`, `data/`, the artifact catalog, or model feature contracts; or
- persist ordinary training-time crops, masks, diffusion noise, augmentations, device casts, or other runtime stochastic views as if they were reusable semantic features.
- make the monorepo, internal SDKs, models, datasets, or generated artifacts open-source or publicly distributable by default.

### 2.3 Principles

- **One semantic owner.** A concept may have adapters and representations, but only one package owns its meaning.
- **One durable truth.** Each mutable lifecycle has one transactional authority; everything else is a projection, cache, lease, or evidence record.
- **Contract before coupling.** Cross-process and cross-language communication uses versioned contracts, not shared database tables or source structs.
- **Reference before optimization.** Scientific and numerical paths obtain correctness evidence before accelerated implementations are eligible.
- **Observed state is not desired state.** Workers and Kubernetes report observations; the Go control plane commits business transitions.
- **Artifacts cross trust boundaries.** Large or durable payloads move by immutable digest with integrity and provenance, not through queue bodies.
- **Build once, qualify once, promote by digest.** Environment promotion never rebuilds a release.
- **Subtraction before abstraction.** A new shared package, plugin seam, provider interface, or service requires two real consumers or a security/process boundary.
- **Fail closed at policy boundaries.** Missing identity, tenant, policy, qualification, or evidence denies the action.
- **Reconstruct from evidence.** A terminal scientific result must be explainable from immutable inputs, plans, versions, observations, and approvals.
- **Derive by semantic identity.** A feature cache hit is valid only when the complete declared derivation identity matches; path, sample name, model alias, and “latest” are never sufficient identities.
- **Views are not meaning.** Shared semantic feature values are independent of model tensor layout; model-specific tensorization and packing remain with the model/runtime consumer.
- **Proprietary by default.** Mindclade-authored source and internal distributions use the repository's proprietary internal-use license; any public distribution is a separate reviewed release decision with all third-party, data, safety, privacy, and export obligations satisfied.

### 2.4 System invariants

1. Every request carries an authenticated principal, `TenantId`, `ProjectId`, request ID, and trace context before domain processing.
2. Every state-changing API accepts an idempotency key scoped to tenant, principal, method, and canonical request hash.
3. A worker cannot transition a durable `Job`, `Run`, `AgentRun`, dataset release, or model release directly; it emits a fenced completion event that reconciliation validates.
4. A queue message is a delivery hint, never the record of work. The relational database and immutable plan/artifact references are authoritative.
5. A mutable alias never identifies a production input. Production inputs are immutable IDs and digests.
6. A committed checkpoint refers only to complete, integrity-verified objects and a committed progress frontier. Uncommitted objects are garbage-collectable.
7. Training commits input progress only with the corresponding optimizer update or with a replay-safe receipt protocol.
8. An optimized kernel or provider is selectable only for a qualified hardware/software envelope and MUST fall back safely or reject explicitly.
9. Agent model output and tool output are untrusted data. They cannot grant permissions, change budgets, select an unapproved capability, or bypass schema validation.
10. Tenant isolation is enforced in authorization, database row policy/query guards, queues, object prefixes or buckets, encryption context, cache keys, logs, and cost labels.
11. Raw restricted biological payloads and secrets MUST NOT appear in logs, traces, queue metadata, prompts, or audit diffs.
12. Generated code is never hand-edited. Generation is hermetic and drift-checked.
13. Production packages MUST NOT import `research/`; `libs/python` MUST remain torch-free.
14. Source packages MUST NOT import deploy or live-environment state. Deployment consumes release metadata, never the reverse.
15. A directory exists only with a named owner, a real target, tests appropriate to maturity, and machine-readable component metadata.
16. Cancellation is cooperative and deadline-bound; it never discards a committed artifact or fabricates success.
17. Deletes of durable scientific evidence are retention state transitions with audit and tombstones, not immediate opaque erasure.
18. No release is promoted without the exact evidence policy named by the release manifest.
19. Every durable reusable feature value is described by a versioned `FeatureContract`, complete provenance, and an immutable artifact/manifest digest; physical cache location is not semantic identity.
20. A deterministic derivation requested with the same `FeatureKeyDigest` MUST produce the same canonical output digest. Divergent output is a determinism violation and is quarantined rather than accepted as an ordinary race.
21. Cache lookup isolation is at least tenant/policy/security-domain aware even when identical authorized content may deduplicate in CAS; cache existence MUST NOT disclose a cross-tenant artifact.
22. Runtime-stochastic feature views are derived from explicit logical RNG identities and are not durable shared cache entries unless a contract explicitly classifies them as seeded, cacheable artifacts.
23. `FeaturePlan` is the feature-domain requirement/cache-resolution artifact, but every executable feature miss MUST lower to the single generic `TransformGraph` substrate; a second feature-specific graph planner, partition engine, or executor is prohibited.
24. Any learned or fitted preprocessing state is an immutable `TransformStateArtifact` produced by an explicit `FitSemanticKey`/`FitReceipt`; ambient mutable estimator state and fit-on-evaluation behavior are prohibited.
25. `TransformSemanticKey` identifies transform meaning and immutable semantic inputs, while `TransformExecutionPlanDigest` identifies backend, partitioning, fusion, spill, and materialization choices. Execution-plan changes MUST NOT alter semantics unless the affected choice is promoted into the semantic contract and creates a new semantic identity.
26. `docs/architecture/repository-path-manifest.yaml` and `docs/architecture/blueprint/manifest.yaml` are machine-readable authorities for repository paths and architecture composition respectively; Appendix A6 and the combined blueprint are deterministic generated views and drift is a presubmit failure.
