## 15. Phased implementation plan

Section 15 is the sole authoritative dependency order. Appendix “milestones” describe local qualification progression and MUST NOT be read as permission to implement a later capability early. The critical path is Waves 0–5; Waves 6–8 raise scale, agent coverage, and production maturity. A later wave may begin discovery but cannot merge production dependencies on an unmet earlier contract.

**Per-wave cost approval.** Before any wave activates paid cloud, accelerator, external-service, or reserved-capacity resources—or merges a commitment that creates material incremental spend—the accountable wave owner and Finance/Operations MUST approve a versioned cost envelope for that wave's exact scope. Approval does not carry forward between waves. A scope change or forecast overrun requires renewed approval before further paid activation. Local source work that creates no incremental external spend may proceed, but it does not prove this connected gate.

### 15.1 Wave 0 — Repository evidence and governance baseline

**Objective and scope.** Establish the evidence baseline before moving code. Bind the target design to the canonical repository, freeze the eight foundational decisions in Section 14.1, and make ownership/dependency/build policy executable.

**Prerequisites.** The greenfield canonical repository and module identity are fixed as `github.com/mindclade/mindclade`; repository instructions and the five operational source repositories are present. Wave 0 records their exact immutable revisions before deriving evidence. No product implementation prerequisite exists.

**First concrete deliverable — repository drift baseline.** `tools/repo/build_repository_drift_report.py` (or an equivalent real target discovered in the repository) MUST produce a machine-readable `repository_drift.v1.json` CI artifact and reviewed `docs/architecture/repository-drift-baseline.md` containing:

```text
actual versus target tree
actual compile-time and runtime dependency graph
ownerless and multiply-owned components
current Protobuf, schema, database, and public API authorities
current deployables, packages, artifacts, and release units
duplicate or conflicting systems of record
generated/vendored/research/production boundary violations
proposed moves in dependency order with affected imports, persisted identities,
compatibility shims, migrations, rollback, and owning wave
```

The report records facts before proposing moves. It MUST NOT create missing target directories, rename imports, or classify planned capabilities as current implementation. Architecture owners approve the baseline; its migration backlog, not the target tree alone, determines subsequent changes.

**Packages/files.** Root native workspace files and locks; `MODULE.bazel`, `BUILD.bazel`, `.bazelrc`, Nix/devcontainer files; `AGENTS.md`; `ARCHITECTURE.md`; `mindclade/.github/`; `CODEOWNERS`; `tools/repo/`, `tools/bazel/`, `tools/ci/`, `tools/generators/stub_catalog.yaml`; `tools/docs/`; `docs/architecture/repository-path-manifest.yaml`; `docs/architecture/blueprint/manifest.yaml` plus its section/appendix source files and generated full render; the eight `docs/adr/0001`–`0008` files in Section 14.1; `FounderBootstrapException/v1` and FBE-0001; package `component.yaml` schema; `CONTRIBUTING.md`; `SECURITY.md`. The estate inventory also resolves the organization `.github`, `github-config`, `bootstrap`, `infrastructure-live`, and `gitops` repositories against Appendix A3 without applying live changes.

**Contracts stabilized.** Canonical repository/module identity; owner/component identity; dependency classes and visibility; artifact-digest vocabulary sufficient to identify evidence; readiness labels; approved top-level namespace. Domain protocols are not stabilized in Wave 0.

**Execution proof.** From a clean checkout, the repository inspector discovers existing targets, owners, dependencies, tests, contract sources, release units, and systems of record. CI compares the resulting graph with the approved baseline and fails only on newly introduced unapproved drift; migrations are handled through explicit backlog items. The repository-path manifest deterministically regenerates the complete A6 tree, and the blueprint source manifest deterministically regenerates the combined architecture document; any drift among editable sources, generated render, or populated repository paths fails validation.

**Tests and evidence.** Deterministic drift report; native/Bazel graph agreement; cycle/visibility/import rules; generated-file inventory; clean CPU bootstrap/build; secret/license/dependency scan; Markdown/ADR validation; report golden/schema tests. Trusted CI signs the baseline after merge.

**Security/operations/migration.** Quarantine committed secrets and revoke credentials immediately; preserve unrelated work; record existing ownership before correcting it; use compatibility shims only when the drift report shows a real caller. CI reports report-diff, graph exceptions, owner gaps, build duration, flake, and cache behavior.

**Exit gate.** The canonical commit and repository/module identity are fixed; the drift baseline is approved and reproducible; every populated component has a known owner or a time-bounded owner-assignment action; the actual graph has no unknown cycle; clean CPU CI passes; ADR-0001 through ADR-0008 exist or are explicitly superseded; every observed capability is evidence-labeled; repo-local and organization `.github` authority is disjoint; and every operational repository has a named owner, protected default branch, recovery tier, and observed-versus-target inventory. Wave 0 does **not** require the target tree migration, later ADRs, Kubernetes, SDKs, domain schemas, or cloud/GitOps apply. **Rollback:** revert enforcement independently while retaining the signed baseline and backlog. **Deferred:** all product/domain implementation and live estate mutation.

The ordinary Wave 0 exit state is `CONNECTED_QUALIFIED`. ADR-0008 and an unexpired, unused FBE-0001 authorize the intermediate `FOUNDER_BOOTSTRAPPED` state solely to establish the public GitHub Free repository-level foundation and proceed with Wave 1 source work. This does not waive independent review or connected evidence, and `production_authority` remains `false`.

### 15.2 Wave 1 — Minimal contract and durability kernel

**Objective.** Implement only the cross-system primitives required by both initial slices: identifiers/references, command/event envelopes, durable work identity, artifact/evidence references, idempotency/fencing, configuration resolution, and release manifest.

**Prerequisites.** Wave 0 `CONNECTED_QUALIFIED`, or `FOUNDER_BOOTSTRAPPED` under the exact unexpired and unconsumed FBE-0001 source exception; module/remote identity and initial identity-provider choice resolved. The exception permits source implementation only and cannot satisfy a connected or production gate.

**Packages/files.** Only the needed packages under `protocols/proto/mindclade/{common,artifact,job}/v1/`, `protocols/events/mindclade/{artifact,job,audit}/v1/`, `protocols/schemas/{artifact_manifest,evidence_manifest,release_manifest,configuration}/`, generated clients and compatibility baselines for those sources; foundational `libs/*/{identifiers,config,artifacts,observability,retry,testing}`; Go transaction/idempotency/audit/outbox/lease primitives; `tools/{codegen,release,qualification}`; initial migrations; local integration profile.

**Contracts stabilized.** Exactly the Section 6.8 kernel: identifiers and `ResourceRef`; `CommandContext`; `EventEnvelope`; `Operation`, `Job`, `Run`, `Attempt`; `ArtifactRef`; `EvidenceRef`; idempotency, resource version and `LeaseEpoch`; deterministic configuration resolution/redacted digest; `ReleaseManifest`. Error, deadline/cancel, pagination, and compatibility conventions necessary to use those types are included. No dataset, model, checkpoint, evaluation, inference, agent, kit, kernel-provider, or environment schema receives a stable compatibility promise yet.

**Kernel proof.** An authenticated test client creates an idempotent operation; one database transaction writes resource, idempotency, audit, and outbox; dispatcher redelivery reaches a test worker; the worker finalizes an artifact and emits a fenced completion; reconciliation commits terminal state; release tooling signs and verifies the fixture subject. This proves the kernel without creating a fake production domain.

**Tests/gates.** Cross-language round trips; Buf/schema compatibility; DB rollback/outbox crash/duplicate/reorder/stale-lease tests; tenant isolation; artifact concurrent finalize/corruption/orphan recovery; config/secret redaction; SBOM/provenance/signature verification; clean checkout. CPU only.

**Exit gate.** Every field in the minimal kernel has one authority and cross-language conformance; the proof survives injected process/queue/database/object failures without double transition or lost acknowledged command; artifact/evidence lineage reaches source/build; access/audit tests pass; no future-domain placeholder is generated. **Rollback:** expand-only schema and feature-disabled dispatcher. **Deferred:** all domain schemas and public API breadth.

The v3.4.3 Wave 1 manifest closure contains 386 target-only paths. It reclassifies 36 existing control-plane durability and integration paths from Wave 2P, adds eight missing operation, audit, inbox, configuration-resolution, release-signing, and conformance paths, and adds five native package authorities required to compile reviewed-generated Go/Python/Rust/TypeScript bindings under native and Bazel authorities. Every Wave 1 entry remains absent and `target`; an incremental subset may be reviewed only as a coherent manifest-governed source patch and MUST NOT claim Wave 1 exit until all Wave 1 exit evidence passes. `FOUNDER_BOOTSTRAPPED` authorizes this source work but no release, promotion, deployment, connected mutation outside FBE-0001, or production authority. Wave 2P consumes this kernel rather than redefining it.

### 15.3 Wave 2 — Two independent initial vertical slices

**Objective.** Run a scientific slice and a platform slice in parallel after the minimal kernel. Each MUST build, test, and qualify independently. Their shared dependency is Wave 1—not each other.

#### 15.3.1 Wave 2S — Local scientific slice

**Flow.** `PDB snapshot -> immutable raw objects -> protein features -> reduced Pairformer -> local training -> committed checkpoint -> evaluation report -> inference artifact`.

**Prerequisites.** Wave 1; JIT-02 ratified by Scientific Leadership, Data Governance, and ML Systems; PDB use/license policy approved. The slice requires neither the Go control plane, Kubernetes, Kueue/JobSet, console, SDK, agents, nor development kits.

**Packages/files.** The minimum real targets in `bio/{schemas,entities,formats,featurization}`, `data/{contracts,connectors,ingestion,normalization,curation,validation,leakage,splits,featurization,catalog}`, `models/`, `kernels/` reference implementations, `runtime/{precision,rng,testing}`, `training/{api,core,execution/single_process,providers/pytorch,checkpointing,tasks,recipes,qualification}`, `evaluation/`, `inference/`, and local CLIs. Development-kit façades and network worker composition are excluded.

**Feature/transform proof.** Wave 2S implements only the reusable semantic contracts and local derivations needed by SQP-001: sequence token identity, residue mask/index, relative positional pair features, and supervised coordinate/atom-mask inputs. Feature requirement resolution produces `FeaturePlan` and lowers cache misses into the common `TransformGraph`; there is no second feature DAG executor. These features use `FeatureKeyDigest`, immutable manifests, local CAS/index adapters, semantic validation, and model-owned CladeFold tensor views. Wave 2S also freezes the minimal `TransformSemanticKey`/`TransformExecutionPlanDigest`/typed-profile/receipt contracts required by its normalization, split, sampling, and feature operations. MSA, template, ligand, external-embedding, fitted transforms not required by SQP-001, and speculative feature families remain absent. The local feature index may use filesystem/SQLite mechanics but must obey the same canonical key and artifact contracts as later distributed execution.

##### SQP-001 — CladeFold-Q0 frozen qualification profile

| Dimension | Frozen value |
|---|---|
| Source cutoff | PDB entries released on or before `2025-12-31T23:59:59Z`; the acquired source snapshot is additionally pinned by manifest digest |
| Biological scope | one protein polypeptide chain; 20 canonical amino acids; length 64–512 residues; experimental resolution at most 3.5 Å; at least 90% complete backbone atoms; exclude nucleic acids, covalently bound non-polymer components, and ambiguous polymer identity |
| Identity and leakage | stable sample identity from normalized chain content/provenance; pinned clustering implementation; no cluster crosses splits at greater than 30% sequence identity |
| Release size | exactly 20,000 training, 2,000 validation, and 2,000 test examples, selected deterministically by cluster then stable sample hash; insufficient eligible examples fails rather than relaxing filters |
| Features | sequence tokens, residue mask/index, relative positional pair features, atom/backbone masks; coordinates/frames are supervised targets only; no MSA, template, ligand, or external embedding dependency |
| Model trunk | `CladeFold-Q0`; at most 75 million trainable parameters; `c_s=256`, `c_z=128`, four Pairformer blocks, eight attention heads; sequence/pair embeddings only |
| Supervised head | four invariant rigid-frame update blocks producing per-residue backbone frame and N/CA/C/O coordinates; masked FAPE plus backbone-coordinate and 64-bin distogram losses |
| Diffusion head | four coordinate-denoiser blocks conditioned on trunk outputs; centered backbone coordinates; cosine noise schedule; velocity prediction; 20 deterministic DDIM sampling steps for qualification |
| Objective weights | supervised FAPE `1.0`, masked backbone coordinate loss `1.0`, distogram cross-entropy `0.3`, diffusion velocity loss `1.0`; normalization is by valid residues/atoms rather than batch count |
| Optimization | AdamW (`beta1=0.9`, `beta2=0.95`, `eps=1e-8`, weight decay `0.1`); peak learning rate `3e-4`; 500-update linear warmup then cosine decay to `3e-5`; global batch 64 chains through accumulation; gradient norm clip `1.0`; qualification seed `20260829`; 10,000-update bounded training run |
| Execution | native PyTorch and PyTorch reference operations only; FP32 reference and BF16 qualified path; AdamW; no compile, provider, TileLang, custom CUDA, or distributed framework dependency |
| Hardware | CPU contract/unit tests; one NVIDIA H100 80 GB functional qualification; maximum eight H100 80 GB GPUs in one node for any pre-Wave-5 run; no multi-node or Kubernetes dependency |
| Required gates | overfit-128, deterministic input receipts, forward/backward/update health, committed checkpoint crash/resume, same-seed evaluation/inference parity, lineage closure, safe model load, artifact integrity |
| Overfit criterion | at least 90% reduction in normalized total training loss from the median of the first ten updates within 2,000 optimizer updates on the fixed 128-example subset |
| Resume criterion | identical logical state/input frontier after restore; FP32 next-update values within `rtol=1e-5, atol=1e-6`; BF16 loss and parameter deltas within `rtol=5e-3, atol=5e-4` under the same hardware/software envelope |
| Product status | internal qualification model only; it makes no frontier-quality, therapeutic, or experimental-validity claim |

Any change to a frozen field after JIT-02 approval creates `SQP-002` or a new profile version and records migration/comparability; implementers cannot silently resize or simplify the workload.

**Scientific slice exit.** From a clean checkout and local CLI, the exact 24,000-example release is reproducible and lineage-complete; `CladeFold-Q0` passes every SQP-001 gate; checkpoint recovery and same-seed inference parity pass; the final inference artifact is immutable and inspectable. **Rollback:** retain raw/evidence, revoke the candidate dataset/model, and revert only local aliases. **Deferred:** control plane, SDK, console, GKE, kits, agents, extra modalities/sources, MSA/templates/ligands, and optimized kernels/providers.

#### 15.3.2 Wave 2P — Local platform slice

**Flow.** `Python SDK -> API -> authorization -> transaction/idempotency/audit/outbox -> dispatcher -> CPU inference worker -> immutable result artifact -> fenced completion -> operation result`.

**Prerequisites.** Wave 1; JIT-01 and JIT-03 ratified. This slice uses a signed, CPU-only `CladeFold-Q0-fixture` bundle and 16 synthetic protein sequences checked into test fixtures or published as immutable test artifacts. It does not train a model or depend on Wave 2S.

**Packages/files.** Minimal `services/control_plane/` API/transaction/outbox/reconciler composition; one Python `workers/inference_worker/` CPU composition root; local PostgreSQL-compatible database, queue transport/emulator, and CAS integration; `sdk/python/`; only the inference request/result fields required by the fixture journey. TypeScript SDK, console, Kubernetes, GKE, runtime gateway extraction, kits, and agents are excluded.

**Platform slice proof.** Python SDK submits one idempotent inference job and returns an `Operation`. The create transaction persists job/run, audit, idempotency, and outbox atomically. At-least-once dispatch reaches the CPU worker; it verifies the fixture input/model digests, publishes the result artifact, and emits a completion with `AttemptId`/`LeaseEpoch`. Reconciliation commits the terminal operation; the SDK downloads and verifies the artifact.

**Tests/gates.** Request/response and Python SDK conformance; authorization/tenant checks; transaction rollback; idempotency hash conflict; duplicate/reordered/poison events; dispatcher/worker crash; stale lease; cancellation/deadline; artifact corruption/orphan handling; current/previous kernel-contract compatibility where applicable; clean CPU integration. The fixture result is deterministic and small enough for presubmit.

**Platform slice exit.** The CPU-only journey passes without scientific training or GPU allocation; no worker can mutate business tables; accepted intent is not lost; duplicates and stale completions do not double-commit; the SDK verifies the returned digest; all state and evidence are reconstructible from the database/outbox/artifacts. **Rollback:** disable the fixture inference route and revert expand-only migrations. **Deferred:** Kubernetes, console, TypeScript SDK, production SLO/capacity, data/training job kinds, and agents.

### 15.4 Wave 3 — Slice integration and domain-contract graduation

**Objective.** Join the independently qualified slices once, then stabilize only the domain contracts proven by the integrated path.

**Prerequisites.** Both Wave 2S and Wave 2P exit independently. A delay or failure in one slice MUST NOT invalidate evidence from the other.

**Packages/files.** Scientific worker composition roots; control-plane inference resource/handler; `sdk/python/`; `protocols/` sources for dataset, feature, model, training, checkpoint, evaluation, and inference documents/messages actually used; compatibility baselines; release tooling. No console, GKE, agent, or development-kit dependency.

**Contracts graduated.** Source/dataset contracts; `FeatureContract`, `FeatureManifest`, `FeatureBundle`, `FeatureKeyDigest` canonicalization and lineage; the exercised `TransformSpec` profiles, `TransformGraph`, `TransformSemanticKey`, `TransformExecutionPlanDigest`, `TransformReceipt`, and `LineageMapArtifact`; model bundle/logical state plus `FeatureRequirementSetRef` and model feature-view contract; `TrainingTask`; progress/`BatchReceipt`; checkpoint manifest/commit; evaluation snapshot/report/gate; inference request/result. Fitted-state contracts graduate only when a real fitted transform is exercised. Fields not exercised by the integrated slice remain experimental or absent.

**Integrated proof.** Publish the Wave 2S dataset/model/checkpoint/evaluation subjects; configure the Wave 2P service to accept the exact `CladeFold-Q0` model release digest; submit one real SQP-001 test example through the Python SDK; execute CPU or one-H100 inference outside the control-plane process; publish/verify the scientific result; revoke or roll back the model release and prove new requests cannot resolve it.

**Tests/gates.** Domain schema compatibility and migrations; SDK current/previous tests; scientific result parity with local inference; authorization/tenant/artifact lineage; promotion fail-closed; release signature/provenance; cancellation and retry across the real worker; no platform package imports scientific private code.

**Exit gate.** Local scientific and platform behavior agree on identifiers, artifacts, errors, cancellation, and results; domain contracts reflect only demonstrated fields; a digest can trace request to dataset/model/checkpoint/evaluation/build; rollback/revocation is timed and successful. **Rollback:** return the platform route to fixture bundle and keep the scientific CLI usable. **Deferred:** production scheduling, multi-node, console, kits, agents, optimized providers.

### 15.5 Wave 4 — Production control plane and worker reconciliation

**Objective.** Harden the minimal platform slice into the supported Go modular control plane and add real data, training, evaluation, and batch-inference worker lifecycles without Kubernetes coupling.

**Prerequisites.** Wave 3 integration; JIT security/tenant and release decisions ratified; domain contracts proven by a real caller.

**Packages/files.** `services/control_plane/`, `services/runtime_gateway/`, `services/artifact_proxy/` as justified; production migrations; worker composition roots including `workers/feature_worker/` when remote materialization is first required; `mindclade.feature.v1` and `mindclade.transform.v1` bounded command/event Protobuf plus generated clients; service-image and local-integration packages; Python SDK operation APIs. TypeScript SDK work is optional after the external API stabilizes.

Feature/data-transform materialization uses the ordinary `Job`/`Run`/`Attempt`/fencing and artifact publication contracts. `ExecuteTransformCommand` and `MaterializeFeaturesCommand` reference immutable plan artifacts and bounded capability/deadline metadata; graph/payload/lineage values remain artifact-plane data. Wave 4 does not create a separate feature-cache service, generic transform service, or business-state database; the data/artifact catalogs store durable metadata/lineage while cache lookup tables remain reconstructible projections.

**Contracts.** Job/run/attempt/workload/operation resources; validation/planning/admission/completion events; bounded feature/transform remote command/event envelopes; quotas, leases, cancellation; external operations/artifact API; reconciliation conditions/reasons.

**Vertical slice.** Python SDK submits data, training, evaluation, and batch-inference jobs; the control plane validates, plans, queues, dispatches, fences, observes, cancels/retries, reconciles, and returns durable results across rolling deployments. TypeScript and console integration may begin after the external API stabilizes but cannot block this gate.

**Tests/gates.** DB failover, outbox backlog, duplicate/reordered/poison events, worker crash, stale completion, lost worker observation/lease, rolling schema/version skew, auth/tenant/quotas, API/SDK compatibility, SLO/load and chaos. CPU plus bounded single-GPU integration; no Kubernetes dependency.

**Exit gate.** No worker has business-table credentials; accepted intent survives all injected failures; reconciliation converges within target; cancellation/retry never double-commits; current/previous service and SDK versions interoperate. **Rollback:** feature-gated resources, expand/migrate schema, previous signed image. **Deferred:** multi-node scale and agent system.

### 15.6 Wave 5 — Native distributed correctness on GKE

**Objective.** Qualify native PyTorch multi-GPU/multi-node execution, Kueue/JobSet admission, committed checkpoint recovery, and topology replanning.

**Prerequisites.** Wave 4 control plane, development/staging GCP environment capability in the fixed regional profile, independently approved accelerator quota/capacity, and the reference vertical.

**Packages/files.** `runtime/distributed/`; `training/execution/{ir,planning,passes,schedules,native}`; distributed checkpointing/resilience/telemetry/qualification; monorepo `deploy/` GKE package defaults and runbooks; activated `bootstrap`, `infrastructure-live`, and `gitops` trees from Appendix A3; plan-only `github-config` updates required for protected apply/promotion environments; distributed tests. JIT-05 ratification binds implementation details to the owner-selected development/staging/production topology, `us-central1` primary, `us-east4` recovery, Google Identity Platform user authentication, exact workload-identity claims, state-root partitioning, and recovery targets before any live apply.

**Contracts.** Hardware topology, placements, collectives, resource request, executable plan, progress frontier/batch receipts, distributed checkpoint membership, recovery guarantee, hardware qualification.

**Vertical slice.** Submit a representative job; Kueue gang-admits JobSet; native engine executes; planned preemption commits/drains; unplanned rank/node failure recovers from last committed checkpoint, optionally under a supported new topology; evaluation verifies equivalence.

**Tests/gates.** multi-rank/node math and normalization; collective timeout; rank kill, node drain, preemption, network/storage fault; checkpoint reshard; RNG/data progress; mixed precision; long-horizon soak; cost/utilization and SLO alerts.

**Exit gate.** Declared recovery point is demonstrated under each supported failure; no silent sample/update duplication; plan/hardware evidence matches execution; performance meets the initial capacity target without correctness exceptions. Bootstrap recovery, infrastructure plan/apply/drift, GitOps render/promotion/rollback, cross-repository identity, and digest-only handoff tests pass for the non-production qualification environment before production authority is enabled. **Rollback:** single-node/reference profile, prior distributed plan digest, last-known-good infrastructure plan, and previous qualified GitOps digest. **Deferred:** live elasticity, Monarch, RL, NVMe offload, and production environment enablement.

### 15.7 Wave 6 — Optimized providers and qualified kernels

**Objective.** Improve cost/performance only behind stable, proven contracts.

**Prerequisites.** Wave 5 correctness and representative profiling identify bottlenecks.

**Packages/files.** Only the implementation selected by the Wave 6 bottleneck study and JIT-06 ADR; operation-specific dispatch/qualification records; activated provider package if the selected gap cannot be solved natively; conversion/qualification tooling. No candidate receives an activatable provider package in advance. ADR-0009 is the sole bounded exception: through 2026-11-30 it permits `kernels/native/` to exist as a TARGET/proposed, empty-operator source-incubation boundary for schema registration, deterministic build-time projections, offline TileLang intake, fail-closed loading policy, build definitions, tests, and documentation. It grants no dispatch, publication, production, connected-qualification, or operator-activation authority and does not satisfy Wave 5 or JIT-06.

**Contracts.** Operation signature/capability, kernel artifact/qualification, provider capability/compatibility, dispatch/autotune record, fallback/revocation.

**Vertical slice.** Qualify one measured bottleneck implementation on a specific hardware/software envelope; deploy in shadow/canary; compare numerical/scientific/operational evidence; promote with automatic reference fallback.

**Tests/gates.** forward/backward/gradient/boundary parity; sanitizer/fuzz; deterministic modes; checkpoint/provider replacement and recovery; hardware matrix; statistically sound benchmark and soak; binary SBOM/signature.

**Exit gate.** Measured cost/throughput improvement clears the predeclared threshold, parity remains within tolerance, fallback/revocation works, and model/task APIs do not change. **Rollback:** revoke implementation digest and dispatch to reference. **Deferred:** providers without measured need and global plugin registry.

### 15.8 Wave 7 — Agent and MADK vertical

**Objective.** Deliver one bounded, scientifically useful, recoverable biological agent workflow.

**Prerequisites.** Waves 1, 2, 4, and relevant inference/evaluation capabilities; approved agent threat model and biological-safety policy.

**Packages/files.** agent protocols/schemas; `agents/{contracts,tools,policies,workflows,state,biological,runtime,evaluation}`; `workers/agent_worker/`; control-plane agent/session/run/step/approval/budget entities; MADK; Python/TS SDK agent sessions; console audit/approval/replay views; sandbox deployment profile.

**Contracts.** Agent definition/release, tool contract/receipt, workflow graph, policy, memory reference, budget, approval, run/step/events, sandbox profile, evaluation/replay report.

**Vertical slice.** Authenticated request resolves and freezes a released agent plan; creates run; executes one read-only biological data tool and one released inference capability; pauses for a high-risk simulated approval; records receipts/memory references; resumes after worker failure; evaluates and publishes a final artifact.

**Tests/gates.** schema/workflow state properties; duplicate side effect and compensation; token/lease replay; budget/deadline/cancel; approval expiry; sandbox filesystem/network/credential escape; prompt/tool injection; cross-tenant memory/cache; biological safety/adversarial simulations; deterministic receipt replay; SDK/app E2E.

**Exit gate.** Every step is authorized, fenced, budgeted, evidenced, replayable, and tenant-isolated; model output cannot broaden authority; crash resumes without repeating a side effect; unsafe/unknown actions fail closed; MADK creates no alternate truth. **Rollback:** disable agent/tool release by policy digest and cancel at safe boundaries. **Deferred:** customer code, open-ended tool marketplace, autonomous irreversible actions.

### 15.9 Wave 8 — SDK, console, release, and production-scale qualification

**Objective.** Complete supported product surfaces and demonstrate production acceptance at representative scale.

**Prerequisites.** All capabilities selected for launch have passed their earlier wave exits; owner decisions in Section 17 are resolved.

**Packages/files.** supported Python/TS SDKs; console/admin/docs; final deployment packages; GitOps handoff; on-call/runbooks/dashboards; DR/security/load/soak suites; release/revocation automation.

**Contracts.** External API/SDK compatibility, usage/cost, support/maturity, operational SLO, environment capability, incident and release evidence.

**Vertical slice.** A supported user performs data publication, training, evaluation/promotion, online/batch inference, and bounded agent workflow through SDK/console; release is built once, promoted by digest, canaried, rolled back, and revoked; region/failure-domain drill restores durable state and resumes work.

**Tests/gates.** current/previous SDK/service compatibility; accessibility and browser security; representative concurrency/capacity; tenant fairness; GPU soak; DR restore/failover; signing-key compromise; incident game day; cost attribution; documentation fresh-install; compliance/safety sign-off.

**Exit gate.** Section 16 production rows have passing immutable evidence, launch SLOs and capacity are met through soak, on-call accepts runbooks, restore meets RPO/RTO, no critical security/safety issue remains, and rollback/revocation are timed successfully. **Rollback:** prior GitOps digests and controlled feature disable. **Deferred:** public Go/Rust SDKs, extra clouds, activated research optimizations not required for launch.
