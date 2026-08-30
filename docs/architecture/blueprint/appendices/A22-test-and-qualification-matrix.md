## Appendix A22 — Test and qualification matrix

| Layer | Required evidence |
|---|---|
| Library | Unit, property, error-path, API compatibility, static analysis |
| Parser | Golden, malformed input, streaming, fuzz, round-trip where meaningful, cross-language conformance |
| Data connector | Offline fixtures, pagination, retry, resume, checksum, idempotency, source-change handling |
| Feature pipeline | Schema, invariants, deterministic output, Python/Rust parity, leakage and quality checks |
| Training dataset | Stable sample identities, ordering, packing, BatchReceipts, duplicate/skip detection, work-unit distribution |
| Kernel | Reference parity, gradients, determinism, shapes, dtype/layout, hardware, compilation, performance |
| Model component | Forward/backward, logical state schema, initialization, migration, numerical regression |
| Model family | End-to-end smoke, checkpoint load, distributed consistency, phase compatibility, evaluation regression |
| Training contracts | Task, loss normalization, phase graph, update graph, state registry, callback ordering |
| Executable plan | Pass ordering, placements, process-group inventory, collectives, memory model, plan digest stability |
| Training execution | Microbatch equivalence, schedule correctness, optimizer/update receipts, data-progress commit |
| Checkpoint/recovery | Snapshot fencing, atomic commit, restore, reshard, corruption/mixed-epoch rejection, preemption |
| Provider/precision | Capability compatibility, state translation, forward/gradient/update parity, reproducibility, failure behavior |
| Compiled region | Guards, graph-break budget, binary/toolchain identity, numerical parity, cache/AOT reproducibility |
| Phase transition | Parameter ownership rebuild, state migration, optimizer compatibility, lineage, evaluation gate |
| Post-training/RL | Policy version, rollout lineage, bounded staleness, replay recovery, independent-role restart |
| Inference | Batching equivalence, cancellation, artifact correctness, performance, memory bounds |
| Service | Contract, authorization, migration, idempotency, outbox, failure injection |
| Worker | Duplicate delivery, lease loss, cancellation, restart, partial artifact cleanup |
| SDK | Generated drift, public API, transport errors, pagination/streaming, conformance |
| Deployment | Schema, policy, server-side validation, rollout/rollback, health |
| Release | Clean checkout, artifact digest, SBOM, signature, provenance, install/run smoke |

### A22.1 Numerical baselines

Numerical baselines include:

- input generation and seed;
- BatchReceipt or reproducible fixture identity;
- exact package, provider, compiler, and toolchain versions;
- hardware topology class;
- precision and quantization policy;
- executable-plan and compiled-region digests;
- tolerance rationale;
- expected statistical distribution when exact equality is inappropriate;
- owner and review date.

Never update a numerical golden merely because a test failed. The change requires evidence and review.

### A22.2 Training qualification levels

Training targets declare the smallest applicable level:

| Level | Required evidence |
|---|---|
| `training-q0` | Contract, CPU/single-process state, recipe, RNG, BatchReceipt, and checkpoint-unit evidence |
| `training-q1` | Single-GPU forward/gradient/update, normalization, step-capsule, and recovery-point evidence |
| `training-q2` | Single-node distributed plan, schedule, collective, accumulation, and reshard evidence |
| `training-q3` | Multi-node failure, preemption, snapshot fencing, async checkpoint, and duplicate/skip evidence |
| `training-q4` | Provider, precision, kernel, compiled-region, and state-translation evidence |
| `training-q5` | Long-horizon model-family, phase-transition, convergence, and evaluation evidence |
| `training-q6` | Production-scale utilization, recovery drill, asynchronous evaluation, operations, security, and provenance evidence |

A provider, recipe, or execution profile cannot claim maturity above the lowest level passed by every required component. Hardware-specific evidence is not automatically portable across accelerator families.

### A22.3 Qualification as a governed evidence system

Qualification is not a collection of tests. It is a typed evidence graph connecting a capability claim to exact code, inputs, environment, procedure, result, owner, and validity scope.

```text
CapabilityClaim
+ QualificationRequirementSet
+ immutable TestEvidence
+ reviewed exceptions
= QualificationDecision
```

A component may pass unit tests while remaining unqualified for production. Maturity and release eligibility use the lowest valid evidence level across every required dependency and composition.

### A22.4 Test taxonomy

Mindclade distinguishes:

| Type | Purpose |
|---|---|
| unit | local behavior and edge cases |
| property | invariants over generated inputs |
| golden | stable expected representation or numerical result |
| conformance | multiple implementations satisfy one contract |
| integration | real adjacent components/adapters work together |
| end-to-end | user-visible workflow across composition roots |
| failure injection | recovery and invariants under faults |
| fuzz | parser, protocol, native-boundary, and state-machine robustness |
| numerical | forward/gradient/update/statistical equivalence |
| performance | latency/throughput/memory/cost regression |
| long-horizon | convergence, stability, drift, operational endurance |
| security | authorization, isolation, supply chain, abuse and policy |
| compatibility | old/new schemas, artifacts, clients, and migrations |

Each test states which claim it supports. Duplicate tests without distinct risk coverage are avoided.

### A22.5 Evidence schema

A qualification evidence artifact contains:

```text
claim and requirement identifiers
target/component/capability identity
source, dependencies, toolchain, image, and environment
hardware topology and runtime
input fixture/dataset/artifact digests
configuration/recipe/plan/provider/kernel digests
procedure implementation and version
raw result and structured summary
pass/fail/indeterminate outcome
statistical/tolerance rationale
owner, reviewer, timestamp, and expiry/review condition
```

Evidence is immutable. A new run creates a new artifact and may supersede, but never edits, an old result.

### A22.6 Risk-based requirement sets

Qualification depth depends on:

- safety/data classification;
- numerical criticality;
- blast radius and availability tier;
- state and recovery implications;
- external compatibility promise;
- hardware/provider specificity;
- frequency of change;
- novelty and historical defect rate.

A pure formatting library does not need long-horizon GPU evidence. A checkpoint format, kernel, parser, authorization module, or training provider requires deeper gates even when code volume is small.

### A22.7 Fixture governance

Fixtures are:

- legally distributable or access-controlled;
- minimal but representative;
- immutable and digest-addressed;
- schema-versioned;
- documented with origin and expected invariants;
- free of secrets and unnecessary restricted payloads;
- generated reproducibly when synthetic;
- retained long enough to reproduce release evidence.

Large fixtures live in artifact storage. Repository fixtures remain small. Updating a fixture requires reviewing whether expected behavior or only representation changed.

### A22.8 Property and metamorphic testing

Properties are preferred where exact outputs are brittle. Examples include:

```text
parse → serialize → parse semantic equivalence
shard → gather equals unsharded value
pack → unpack preserves sample content and masks
batch permutation does not change per-sample result
checkpoint save → resharded load preserves logical state
coordinate rigid transform preserves invariant metrics
microbatch partition preserves update
retry/duplicate delivery preserves one durable outcome
```

Generators cover boundary dimensions, empty/uneven shards, malformed records, optional fields, unknown schema values, and policy classifications.

### A22.9 Golden-test policy

Goldens are appropriate for stable external representation, canonical serialization, protocol fixtures, and carefully governed numerical references. Every golden includes generator/procedure identity and rationale.

Goldens are not bulk-updated. Review distinguishes:

- intended semantic change;
- harmless canonical representation change;
- nondeterministic output;
- toolchain drift;
- defect.

An approval script may regenerate candidate goldens, but a human or governed automation approves each baseline change with evidence.

### A22.10 Numerical test design

Numerical qualification compares at several levels:

```text
operation output
intermediate/module output
gradients
optimizer update
checkpoint round trip
multi-step drift
long-horizon training/evaluation distribution
```

Tests define reference precision, tolerance profiles, norm/cosine/ULP criteria, tail behavior, NaN/Inf equivalence, and statistical treatment. Passing elementwise output alone does not qualify a fused backward or optimizer-visible behavior.

### A22.11 Randomness and statistical tests

Stochastic tests use controlled sample-keyed randomness and report seeds. Statistical tests declare hypotheses, effect-size threshold, confidence/error rates, repeat count, and handling of multiple comparisons.

A test is not made reliable by fixing one favorable seed. Use deterministic invariants where possible and distributions/repeated trials where stochastic behavior is the subject. Rare-event tests use targeted generation or importance strategies rather than impractical blind repetition.

### A22.12 Distributed test matrix

Distributed tests cover:

- one and multiple processes per node;
- supported mesh dimensions and uneven/empty partitions;
- process-group inventory and ordering;
- rank-local and collective failures;
- rendezvous timeout/restart;
- topology-changing checkpoint restore;
- delayed or duplicated messages at service boundaries;
- preemption and node replacement;
- network degradation where safely reproducible;
- deterministic ownership and finalization.

A mock collective validates planning logic but does not substitute for real NCCL/device qualification.

### A22.13 Failure-injection methodology

Faults are injected at named boundaries:

```text
before durable mutation
after mutation before response
after staging before commit
mid-transfer or mid-checkpoint
after lease expiry
rank/node termination
storage/queue/database timeout
corrupt/incomplete artifact
telemetry outage
clock skew within supported envelope
```

Tests assert safety invariants, not only that the process restarts. They verify no duplicate/skip, stale publication, mixed epoch, unauthorized access, orphaned committed state, or unbounded retry.

### A22.14 Performance qualification

Performance evidence defines workload, warmup, repetitions, concurrency, topology, environment, and statistical comparison. It reports:

- latency distribution and tail;
- throughput/useful work;
- peak/steady memory and disk/network I/O;
- compile/load/startup cost;
- utilization and bottleneck attribution;
- cost estimate;
- accepted baseline and regression budget.

Benchmarks execute on controlled pools. Performance failures do not invite relaxed numerical or safety tests. Improvements must hold end to end or be explicitly scoped to a micro-operation.

### A22.15 Security testing

Security evidence includes:

```text
authentication and authorization matrix
tenant isolation and confused-deputy cases
secret/log redaction
untrusted CI and supply-chain controls
artifact signature/admission verification
network and egress policy
input size/parser/fuzz abuse
rate/quota/backpressure
privileged admin audit
restricted biological data/output policy
backup/restore access controls
```

Penetration and threat-model exercises supplement automated tests. A generic dependency scanner is not sufficient security qualification.

### A22.16 Compatibility testing

Compatibility matrices cover:

- current writers to supported old readers and vice versa where promised;
- Protobuf/API breaking checks plus semantic fixtures;
- JSON Schema manifest migrations;
- checkpoint logical state migrations and resharding;
- dataset/feature/model compatibility;
- SDK against supported API versions;
- database expand/migrate/contract deployments;
- deployment package and CRD upgrades;
- provider/kernel/toolchain upgrades.

Unsupported combinations fail clearly. Compatibility evidence has a time/version window and expires when support ends.

### A22.17 Test hermeticity and environment control

Tests declare network, clock, randomness, filesystem, process, GPU, and external-service needs. Defaults are isolated and deterministic. Time and identifiers use injectable providers. Temporary resources are attempt-scoped and cleaned even on failure.

A test that depends on developer machine state, mutable `latest`, ambient credentials, source-site availability, or execution order is invalid for release evidence.

### A22.18 Coverage model

Coverage is measured as risk/contract coverage rather than line percentage alone. Maintain a matrix from architecture invariants and component contracts to tests and qualification evidence. Code coverage identifies unexercised paths, but does not prove semantic, failure, distributed, security, or numerical coverage.

Critical invariants must have at least one negative test that demonstrates the gate rejects an invalid state.

### A22.19 Qualification dependencies

A qualification decision recursively verifies:

```text
component evidence
+ dependency maturity/evidence
+ exact composition evidence
+ target hardware/software scope
+ unresolved exceptions
```

Two individually qualified providers are not automatically qualified together. Composition evidence is required for interactions such as FSDP plus provider sharding, compiler plus custom kernel, low precision plus checkpoint migration, or dynamic batching plus stochastic sampling.

### A22.20 Evidence validity and expiry

Evidence remains valid only while relevant identities and assumptions match. It is invalidated by changes to:

- source or transitive dependency within the claim scope;
- compiler/toolchain/runtime;
- hardware architecture or topology class;
- schema/fixture/dataset;
- provider/kernel/precision/plan;
- policy or threat model;
- tolerance/statistical method;
- known defect affecting the result.

The qualification engine computes affected evidence and required reruns. Manual “still okay” claims require a time-bounded waiver.

### A22.21 Exceptions and waivers

A waiver includes claim, missing/failed evidence, risk, scope, owner, approver, compensating controls, release/channel limitation, and expiry. Waivers never redefine the test result as passing. Critical security, mixed-state, data-loss, or unauthorized-publication invariants are non-waivable for production.

### A22.22 Quarantine and indeterminate outcomes

Qualification outcomes are:

```text
PASS
FAIL
INDETERMINATE
NOT_APPLICABLE with rationale
WAIVED for bounded scope
```

Infrastructure loss may yield indeterminate, never pass. Quarantined tests remain requirements with unresolved evidence. Promotion uses policy over these outcomes and cannot ignore missing reports.

### A22.23 Release evidence bundle

A release evidence bundle links:

- all required qualification decisions;
- exact artifacts and manifest;
- test reports and environment identities;
- security/supply-chain evidence;
- known issues and waivers;
- compatibility matrix;
- operator/runbook readiness;
- signer and approval identities.

The bundle is immutable and verifiable offline from trusted metadata and artifact digests.

### A22.24 Qualification service/tooling boundary

Initially implement qualification as repository libraries, schemas, CI steps, and artifact reports—not a premature standalone service. Tools provide:

```text
requirement resolution
execution-plan generation
evidence ingestion and validation
claim-to-evidence graph
maturity/release decision
human-readable report
```

The durable control plane may catalog decisions and references. It does not need to schedule every test itself.

### A22.25 Qualification maturity levels

| Level | Meaning |
|---|---|
| `q0-contract` | schemas, invariants, static/unit/property evidence |
| `q1-local` | complete local/single-device behavior and failure evidence |
| `q2-integrated` | real adjacent dependencies and distributed/service composition |
| `q3-resilient` | failure injection, recovery, migration, compatibility, security |
| `q4-optimized` | provider/kernel/compiler/performance composition evidence |
| `q5-long-horizon` | scientific/statistical stability and sustained behavior |
| `q6-production` | scale, SLO, operations, provenance, incident and recovery drills |

Domain-specific levels refine this common ladder but do not weaken it.

### A22.26 Capability-local qualification progression

**Milestone 0 — evidence schema and matrix:** map existing architecture invariants to requirement IDs and structured test reports.

**Milestone 1 — core conformance:** parsers, protocols, artifacts, model state, training normalization/checkpoints, jobs/fencing, and SDKs.

**Milestone 2 — distributed and failure evidence:** real GPU, multi-node, service dependency, migration, corruption, and recovery suites.

**Milestone 3 — production qualification graph:** automated invalidation, composition matrix, signed evidence bundles, waivers, and release decision tooling.

### A22.27 Definition of done

The test and qualification system is production-ready when:

1. every production claim maps to explicit immutable evidence requirements;
2. fixtures, environments, procedures, tolerances, and statistical methods are versioned and attributable;
3. tests cover negative, failure, distributed, compatibility, security, and performance behavior—not only happy paths;
4. stochastic and numerical tests use scientifically defensible methods;
5. qualification is composition- and hardware-specific where interactions matter;
6. evidence invalidates automatically when relevant identities change;
7. failed, indeterminate, quarantined, and waived outcomes remain visible and cannot masquerade as pass;
8. release bundles are complete, signed/provenanced, and independently verifiable;
9. numerical goldens and tolerance changes require evidence and review;
10. the lowest required dependency/composition level bounds release maturity.

### A22.28 Final qualification invariants

- tests produce evidence; policy grants qualification;
- qualification claims are exact in scope and expire when assumptions change;
- passing components do not imply a passing composition;
- infrastructure failure never becomes a pass;
- baseline changes are governed decisions;
- release eligibility is computed from immutable evidence, not dashboard confidence.
