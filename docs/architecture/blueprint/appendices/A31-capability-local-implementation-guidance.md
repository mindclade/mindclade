## Appendix A31 — Capability-local implementation guidance

> **Sequencing authority:** Section 15 is the sole dependency-ordered production program. This appendix preserves detailed workstream and qualification guidance from the earlier blueprint; its milestone numbers are local capability stages, not an independent schedule. If its ordering or scope differs from Section 15, Section 15 controls.

### A31.1 Repository evidence first

The first implementation artifact is the repository drift baseline defined by Section 15.1. Before moving or creating production code, inventory:

- actual and target trees;
- compile-time and runtime dependencies;
- ownerless or multiply-owned components;
- current contract and database authorities;
- deployables, artifacts, packages, and release units;
- duplicate systems of record;
- compatibility-aware moves and rollback.

The baseline is generated from real repository facts, reviewed, signed by CI, and retained as migration evidence. Target directories are not created merely because they appear in Appendix A6.

### A31.2 Minimal contract kernel

Wave 1 stabilizes only:

```text
identifiers and ResourceRef
CommandContext and EventEnvelope
Operation, Job, Run, and Attempt
ArtifactRef and EvidenceRef
idempotency, revision, and LeaseEpoch
configuration resolution and redacted digest
ReleaseManifest
```

Domain schemas activate with the first real consumer and owning wave. Generated clients contain only activated stable contracts. This prevents early compatibility promises for datasets, models, checkpoints, evaluations, inference, agents, kits, providers, or environments.

### A31.3 Scientific slice

Wave 2S is the local, network-independent scientific path:

```text
PDB snapshot
→ immutable raw objects
→ normalized protein chains and deterministic features
→ CladeFold-Q0 reference model
→ local CPU/one-H100 training
→ committed checkpoint and recovery
→ immutable evaluation evidence
→ local inference artifact
```

It implements the exact SQP-001 profile in Section 15.3.1. It does not wait for the Go control plane, SDK, console, Kubernetes, GKE, Kueue/JobSet, agents, or development kits.

Exit evidence includes the exact 20k/2k/2k release, 30%-identity split isolation, the at-most-75M-parameter model, overfit-128, deterministic input receipts, numerical update health, checkpoint-resume tolerance, same-seed evaluation/inference parity, and complete artifact lineage.

### A31.4 Platform slice

Wave 2P is the CPU/local platform path:

```text
Python SDK
→ authenticated API
→ transaction: resource + idempotency + audit + outbox
→ at-least-once dispatch
→ CPU inference worker using immutable fixture artifacts
→ fenced completion
→ reconciled operation
→ verified result artifact
```

It uses the signed `CladeFold-Q0-fixture` bundle and 16 synthetic inputs. It does not train a model and does not depend on Wave 2S, Kubernetes, the console, TypeScript SDK, agents, or kits.

Exit evidence includes transaction rollback, duplicate/reordered delivery, stale fencing, cancellation/deadline, worker crash, artifact corruption, tenant isolation, SDK conformance, and proof that the worker cannot mutate business tables.

### A31.5 Slice integration and contract graduation

After both slices pass independently, Wave 3 joins them through the exact released scientific digests. It promotes only fields exercised by the integrated path into stable dataset, feature, model, checkpoint, evaluation, and inference contracts.

The integrated proof submits a real SQP-001 test example through the Python SDK, executes inference in a scientific worker, publishes a verified result, and demonstrates model-release rollback/revocation. Failure in integration does not erase either slice's independent evidence.

### A31.6 Native distributed correctness

Only after both local slices pass independently, Wave 3 integration succeeds, and Wave 4 durable control-plane qualification passes should Wave 5 add:

- DeviceMesh/DTensor;
- FSDP2 and required native distributed strategies;
- NCCL collectives;
- meta initialization and activation checkpointing;
- DCP resharding;
- data-parallel topology-changing restart;
- Kueue/JobSet admission;
- multi-node failure injection and long-horizon telemetry.

No advanced provider is needed to pass this milestone.

### A31.7 Measured optimization intake

Wave 6 begins with profiling, not a named provider. For the largest measured bottleneck:

1. freeze operation/capability and reference behavior;
2. state the performance or memory threshold;
3. evaluate the smallest candidate set;
4. map logical state, checkpoint, recovery, precision, and artifacts;
5. qualify numerical/scientific parity;
6. canary with fallback and revocation;
7. promote only the exact hardware/software envelope.

Megatron Core, DeepSpeed, Transformer Engine, TorchAO, Lightning/Fabric, TorchForge, Monarch, TileLang, and custom CUDA remain intake candidates until this process selects one. No provider package or compatibility surface exists before selection.

### A31.8 Agent and development-kit timing

Agent/MADK work begins in Wave 7 only after stable data, inference, operation, artifact, authorization, and evaluation capabilities exist and Wave 6 has exited or been explicitly deferred. Its ADR is ratified immediately before Wave 7 with the threat model and biological-safety policy.

MCDK–MADK façades are implemented only when their canonical domain has a real supported workflow and a named developer consumer. The initial scientific and platform slices use direct CLIs/contracts and the Python SDK, not kits.

### A31.9 Parallel workstreams

After Wave 1, work proceeds as:

```text
                           ┌─ Wave 2S: scientific slice ─┐
Wave 0 → Wave 1 kernel ────┤                             ├─ Wave 3 integration
                           └─ Wave 2P: platform slice ───┘
                                                     ↓
                           Wave 4 control-plane hardening
                                                     ↓
                           Wave 5 native distributed correctness
                                                     ↓
                           Wave 6 measured optimization
                                                     ↓
                           Wave 7 agent/MADK
                                                     ↓
                           Wave 8 product and production qualification
```

Wave 2S and Wave 2P may share the Wave 1 contract libraries and artifact store, but neither may introduce a dependency on the other's implementation. Scientific engineers can complete the model path without service infrastructure; platform engineers can complete durability/SDK behavior with prebuilt fixture artifacts.

### A31.10 Program evidence

Every wave publishes:

```text
approved input contracts and decision gates
source revision and affected targets
test and qualification evidence
artifact and release digests
security/data classification review
observed versus planned resource/cost profile
migration and rollback result
exit decision and deferred register
```

A screenshot, dashboard, or prose assertion alone is not exit evidence.

### A31.11 First scientific workload

SQP-001 in Section 15.3.1 is the sole first scientific workload. “A diffusion or supervised task,” arbitrary small datasets, alternate Pairformer dimensions, MSA/template features, ligands, or unbounded GPU experiments are not substitutes. Scientific Leadership must approve the frozen profile before implementation; changes create a new profile version.

### A31.12 Two-slice acceptance

The initial program passes only when:

- Wave 2S completes dataset-to-inference locally with no platform dependency;
- Wave 2P completes SDK-to-operation-to-artifact locally with no training/GPU dependency;
- each has independent build, test, failure, and rollback evidence;
- Wave 3 joins their immutable artifacts without importing private implementations or changing their semantic owners.

Console, Kubernetes, agents, kits, optimized kernels, and production-scale training are explicitly outside this acceptance gate.

### A31.13 Required ADR set

Wave 0 approves exactly seven ADRs:

1. repository identity and ownership;
2. dependency and build law;
3. artifact identity and CAS;
4. contract and code-generation authority;
5. biological identity and schema evolution;
6. durable work, outbox, idempotency, and fencing;
7. training state, progress, checkpoint, and recovery.

All other accepted decisions use the just-in-time register in Section 14.2 and are ratified immediately before their first dependent implementation wave.

### A31.14 Staffing and ownership minimum

Even when individuals cover multiple roles, assign named ownership for:

```text
repository/build/CI
protocols/SDK
artifact/config foundation
bio/data
models/kernels
training/runtime/checkpoint
control plane/database/workers
evaluation/inference
agents/development kits
security/safety
cloud/Kubernetes/operations
product/design/docs
```

No critical workstream starts without an owner and review counterpart for its highest-risk contracts.

### A31.15 Program artifacts

Track the program through immutable or reviewed artifacts:

- milestone definition and owner;
- requirement/ADR links;
- component and target list;
- qualification matrix;
- demo/vertical-slice scenario;
- known risks/deferred scope;
- exit report with evidence digests;
- next-milestone dependency decision.

Status is based on exit evidence, not percentage-complete estimates.

### A31.16 Milestone exit review

At each exit, review:

```text
contract correctness and bypasses
test/qualification completeness
security/data classifications
artifact/run lineage
clean-checkout reproducibility
operational failure/recovery
performance/resource envelope
documentation and ownership
scope deferred or removed
```

A milestone can be accepted with bounded known gaps only through explicit exceptions that do not violate core correctness/security invariants.

### A31.17 Initial implementation shape governed by Section 15

A practical initial sequence is dependency-ordered rather than calendar-promised:

**Phase 1 — Wave 0:** repository evidence, ownership, foundational ADRs, deterministic architecture/path generation, build graph, and clean CPU CI. No domain production paths activate.

**Phase 2 — Wave 1:** minimal contracts, artifacts/configuration, local durability primitives, and the transaction/outbox/worker proof. Domain contracts remain activation-gated.

**Phase 3 — Waves 2S and 2P:** complete the scientific and platform slices independently, sharing only the Wave 1 contract and artifact foundations.

**Phase 4 — Waves 3 and 4:** integrate through immutable released digests, graduate exercised contracts, and harden the durable control plane. Distributed execution, optimized providers, agents/kits, and product surfaces remain governed by Waves 5–8.

This is a sequencing template, not a calendar promise; staffing and scientific complexity determine actual cadence.

### A31.18 Risk controls during implementation

Highest early risks and controls:

| Risk | Control |
|---|---|
| broad empty scaffold | require one real target/owner/consumer per directory |
| provider-first architecture | finish native contracts/vertical slice before promotion |
| unstable biological semantics | conformance schemas/fixtures before dataset scale |
| artifact/path sprawl | one `ArtifactRef` and catalog from the first workflow |
| checkpoint/progress defects | commit/restore drills in first slice |
| premature microservices | one modular control-plane deployment |
| CI cost explosion | affected graph and tiered tests from foundation |
| secret/restricted-data leakage | classification, safe fixtures, workload identity, log controls early |
| product/API drift | generated clients plus stable SDK boundary |
| owner overload | explicit workstream ownership and deferred scope |

### A31.19 Definition of done for the implementation program

The immediate program is correctly structured when:

1. work is sequenced by contract and vertical-slice dependencies rather than directory order;
2. every workstream has an owner, real consumer, exit evidence, and defined non-goals;
3. the two independent Wave 2 slices jointly cover data, model, training, evaluation, inference, control plane, worker, SDK, and artifact boundaries without either slice depending on the other's private implementation;
4. the Wave 7 agent slice composes qualified public boundaries only after the preceding wave gates, with explicit policy, approval, budget, replay, and tool-receipt evidence;
5. native correctness precedes advanced provider promotion;
6. security, lineage, checkpoint recovery, and CI are present in the first slice rather than postponed;
7. milestone status is evidence-based and clean-checkout reproducible;
8. ADRs freeze the highest-cost-to-change ownership and identity decisions;
9. deferred capabilities cannot leak into the critical path through speculative abstractions;
10. each milestone removes bypasses and duplicate sources of truth;
11. the first production release satisfies the domain definitions of done, not merely a demo.
