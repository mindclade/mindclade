## Appendix A18 — Service and worker architecture

### A18.1 Start with a modular control-plane monolith

The initial Go control plane should contain clear modules for:

- tenants/projects/users;
- datasets;
- artifacts;
- experiments/runs;
- jobs;
- models/checkpoints;
- policy;
- audit.

Each module owns:

- domain types;
- application commands/queries;
- repository interfaces;
- protocol adapters;
- authorization checks;
- tests.

Modules may share platform infrastructure but not each other's database tables directly. Use explicit module APIs or events.

Split a module into a separate service only when one or more are true:

- distinct scaling profile;
- distinct trust boundary;
- independent availability requirement;
- independent release ownership;
- data sovereignty requirement;
- operational load is harming the monolith;
- team ownership makes the boundary durable.

### A18.2 Durable job state

Use an explicit state machine such as:

```text
PENDING
-> VALIDATING
-> QUEUED
-> ADMITTED
-> RUNNING
-> SUCCEEDED

Any active state
-> CANCELLING
-> CANCELLED

Any active state
-> RETRY_WAIT
-> QUEUED

Any active state
-> FAILED
```

Transitions are compare-and-swap or transactional. Each transition emits an audit record and an outbox event.

### A18.3 Queue and lease contract

Workers use:

- idempotency keys;
- visibility/lease timeout;
- heartbeat;
- bounded retry;
- poison-job handling;
- cancellation;
- attempt identity;
- progress checkpoints;
- immutable input references;
- result manifest;
- failure classification.

A worker must tolerate duplicate delivery. “Exactly once” is not assumed across distributed infrastructure.

### A18.4 Outbox before event-service proliferation

Use a transactional outbox in the control plane before introducing a separate event dispatcher. Split dispatch when throughput, delivery isolation, or ownership justifies it.

Do not create a standalone “health service.” Every deployable exposes standardized health, readiness, metrics, and diagnostics endpoints through shared service libraries.

### A18.5 Training worker composition root

`workers/training_worker/` owns operational composition, not model or trainer semantics. For each leased job it:

1. resolves immutable recipe, model, dataset/feature, checkpoint, evaluation, and provider references;
2. validates policy, data classification, hardware/resource profile, and worker-image capability;
3. acquires artifacts through the artifact library and verifies digests;
4. discovers the allocated `HardwareTopologyManifest`, compiles and validates the frozen `ExecutablePlan`, then constructs the `TrainingTask`, trainer, provider registry, and `CompiledStepProgram`;
5. joins the JobSet/rendezvous, validates the `CollectivePlan`, and fences the worker attempt;
6. drives heartbeats, cancellation, quiescing, and preemption handling;
7. streams bounded structured progress events to the control plane while preserving local durable event output;
8. uploads checkpoint, evaluation-snapshot, step-capsule, diagnostic, report, and final result manifests;
9. classifies failure and releases resources cleanly.

The worker never embeds model architecture, provider-global configuration, raw cloud credentials, or a second checkpoint implementation. It must tolerate duplicate delivery and reject a stale attempt before performing an optimizer update or publishing an artifact.

### A18.6 Control-plane domain model

The control plane is a modular monolith with a shared process and deployment unit but explicit bounded contexts. Initial modules and their canonical resources are:

| Module | Canonical resources |
|---|---|
| identity/tenancy | tenant, project, user, service principal, membership |
| policy | entitlement, data classification, execution policy, quota policy |
| artifacts | artifact metadata, generation, alias, lease, retention, access receipt |
| datasets | source, snapshot, dataset version, feature set, qualification |
| models | model family, model version/bundle, checkpoint reference, deployment eligibility |
| experiments | experiment, study, run, phase, evaluation decision |
| jobs | job, attempt, cancellation, progress, result/failure |
| audit | immutable security and administrative records |
| platform | transaction, outbox, queue adapter, storage adapter, database infrastructure |

A module owns its write model and invariants. Other modules access it through application interfaces or durable events, not table joins from arbitrary code.

### A18.7 Layered module shape

Each module follows:

```text
transport adapter
→ application command/query handler
→ domain model and policy
→ repository/port interfaces
→ infrastructure adapters
```

Transport types are converted at the boundary. Domain code does not import gRPC, HTTP, SQL driver, Kubernetes, cloud SDK, or queue implementation packages. Transactions are initiated in the application layer and remain inside the owning module unless a documented orchestration pattern coordinates multiple modules.

### A18.8 Command and query contracts

Commands are typed, authorization-aware mutations with idempotency and preconditions. Queries are side-effect free and enforce field-level/resource-level visibility.

A command handler order is:

```text
authenticate principal
→ resolve tenant/project and policy context
→ validate request syntax
→ authorize intended action
→ enforce idempotency and revision preconditions
→ load aggregate
→ apply domain invariant
→ persist state and outbox atomically
→ return stable resource/result
```

Authorization is checked against the requested transition, not only the endpoint. Repository methods cannot bypass policy by accepting unaudited arbitrary SQL filters.

### A18.9 Tenancy and authorization

Every tenant-owned resource carries immutable tenant identity and normally project identity. Cross-tenant references are rejected unless a specific platform-owned sharing construct authorizes them.

Authorization uses:

```text
principal identity
+ tenant/project membership and role
+ resource attributes and ownership
+ action
+ data classification
+ environment/workload context
+ policy version
= decision and audit context
```

The system supports deny-by-default, least privilege, service-principal scoping, temporary elevated access, and revocation. Browser claims are hints; the server remains authoritative. Background workers receive job-scoped identities and cannot enumerate unrelated tenant data.

### A18.10 Durable resource and aggregate semantics

Each resource defines:

- canonical name and immutable UID;
- aggregate boundary;
- lifecycle state machine;
- mutable versus immutable fields;
- revision/ETag behavior;
- soft-delete, tombstone, and purge policy;
- audit requirements;
- owner and authorization actions;
- emitted events;
- artifact relationships;
- compatibility and migration rules.

State transitions are methods over domain aggregates, not free-form database updates. Impossible transitions fail with typed precondition errors.

### A18.11 Job, run, and workload separation

These concepts are distinct:

| Concept | Meaning |
|---|---|
| job | durable user/platform request and business lifecycle |
| attempt | one fenced worker execution of a job |
| run | scientific execution record, potentially across attempts/recovery |
| workload | Kubernetes or other scheduler object for one allocation attempt |
| task/unit | internally retryable subset of work where the job contract permits |

A job can have multiple attempts, and a training run can resume through multiple worker attempts while preserving one scientific run lineage. Kubernetes pod phase is never copied directly as the job state without reconciliation rules.

### A18.12 Job transition protocol

A transition requires expected revision, actor, reason, and optional attempt fence. The transactional record includes:

```text
previous and next state
transition identity and time
principal/system actor
request and idempotency identity
active attempt/workload reference
progress/result/failure delta
outbox event
policy/audit metadata
```

Terminal success requires a complete verified result manifest. Cancellation intent is durable and monotonic. A late worker success cannot overwrite an already fenced cancellation or replacement attempt unless the job policy explicitly defines that race.

### A18.13 Attempt fencing

Every attempt receives an opaque monotonic fence token or generation. Mutations from a worker must include:

```text
job identity
attempt identity
fence token
observed job revision
operation idempotency key
```

The server rejects stale heartbeats, progress, checkpoints, artifacts, and terminal outcomes. Fencing is enforced at every publication path, not only queue acknowledgement.

### A18.14 Queue abstraction

The queue contract exposes:

```text
enqueue immutable work reference
lease next eligible item
renew lease/heartbeat
acknowledge terminal processing
release with retry classification and delay
mark poison/dead-letter
observe queue age and attempts
```

Payloads contain compact references and digests, not model weights, datasets, or large biological payloads. Delivery is at least once. Ordering is guaranteed only for declared keys. Queue adapters do not own job truth; they accelerate delivery of work already recorded durably.

### A18.15 Lease behavior

A lease has an attempt, owner, issue/expiry time, renewal cadence, and fence token. Workers stop authoritative publication when renewal is lost. The control plane declares a grace period and replacement policy.

Heartbeat payloads are bounded summaries. High-frequency numerical telemetry goes to the telemetry path, not transactional job rows. Progress updates are rate-limited, monotonic where possible, and resumable.

### A18.16 Retry and failure classification

Failures are classified by owner and action:

| Class | Examples | Default action |
|---|---|---|
| invalid request | schema, unsupported capability | terminal failure |
| policy | denied data/use/resource | terminal or operator review |
| transient platform | queue, storage, network, node loss | bounded retry |
| capacity/admission | quota wait, unavailable accelerator | queue/wait or timeout |
| worker defect | panic, invariant violation | fail and alert; limited retry |
| data defect | corrupt source, invalid sample | quarantine or terminal by policy |
| numerical | NaN, divergence, kernel mismatch | task health policy |
| external dependency | source/API outage | retry/circuit break |
| cancellation/preemption | user cancel, scheduler reclaim | graceful termination/recovery |

Retry budgets are per class and resource. Infinite retries and generic “internal error” loops are prohibited.

### A18.17 Transactional outbox

Every externally relevant state change writes an outbox record in the same database transaction. The dispatcher:

1. leases unsent records;
2. serializes the versioned event envelope;
3. publishes idempotently;
4. records delivery attempt and destination offset/receipt;
5. retries with backoff;
6. dead-letters with operator-visible state.

Consumers deduplicate by event ID and aggregate sequence. The outbox may later be split into a service, but module transaction semantics remain unchanged.

### A18.18 Artifact service boundary

The control plane stores artifact metadata and authorization, not artifact bytes. Artifact operations support:

```text
reserve generation/upload intent
issue narrowly scoped transfer authorization
verify upload digest/size/schema
commit immutable generation
resolve alias to digest
acquire/release retention lease
record access/promotion/audit receipt
revoke or quarantine
```

Clients and workers never construct privileged bucket paths directly. Storage locators are implementation details behind `ArtifactRef` and transfer APIs.

### A18.19 Database ownership and transactions

Each module has owned tables or schemas and repository interfaces. Cross-module read models may be built through:

- application API calls in-process;
- replicated projections from events;
- explicitly reviewed read-only views where transaction and ownership semantics are clear.

A transaction should normally update one aggregate and its outbox. Multi-aggregate workflows use sagas/process managers with compensating or convergent actions rather than hidden distributed transactions.

### A18.20 API edge and runtime gateway

The public/control API handles:

- authentication and token validation;
- request limits and abuse controls;
- tenant/project context;
- schema and size validation;
- authorization;
- idempotency and optimistic concurrency;
- durable job/resource creation;
- streaming/polling status;
- stable public errors;
- audit and trace correlation.

The runtime gateway may specialize high-throughput inference edges but consumes the same identity, policy, job, artifact, and protocol contracts. It does not create an independent job database.

### A18.21 Worker base contract

Every worker implements a common operational lifecycle:

```text
bootstrap and verify image/capabilities
→ authenticate with workload identity
→ lease work and obtain fence
→ resolve immutable inputs
→ validate policy and local capability
→ create attempt-scoped workspace
→ execute with cancellation/heartbeat
→ stage and verify outputs
→ publish through fenced APIs
→ acknowledge or classify failure
→ clean up and emit terminal diagnostics
```

Common worker libraries own signal handling, heartbeat, cancellation, retry classification, artifact transfer, telemetry context, temporary storage, and shutdown. They do not own domain execution semantics.

### A18.22 Ingestion worker requirements

The ingestion worker:

- executes connector plans with source rate limits and terms;
- resumes range/page downloads;
- verifies source bytes before publication;
- maintains source revision/tombstone semantics;
- emits raw and parsed artifact references;
- supports offline fixture mode;
- quarantines malformed or policy-restricted records;
- never embeds source credentials in artifacts/logs.

### A18.23 Feature worker requirements

The feature worker is a composition root for remote feature materialization. It resolves an immutable `FeaturePlan` artifact, verifies `FeatureContract`s and canonical `FeatureKeyDigest`s, evaluates the authorized cache partition, verifies the associated `TransformExecutionPlan`/`TransformGraph` artifact produced by feature-plan lowering, and executes only missing feature-producing transform nodes. It composes Rust streaming/CPU hot paths with Python scientific reference implementations through qualified `ImplementationRegistry` entries, validates biological/shape invariants, commits `TransformReceipt`/`FeatureDerivationReceipt` evidence, and publishes through the normal artifact staging/finalization protocol.

It may reuse a feature only when the complete derivation key and policy partition match and the referenced manifest/artifact verify. Worker local disk, in-memory caches, object prefixes, and the derivation index are reconstructible. Remote queue messages contain immutable plan/receipt references rather than embedded feature graphs or arrays. A remote attempt is fenced by `AttemptId`/`LeaseEpoch`; stale attempts cannot update the derivation projection. Competing deterministic attempts that produce different output digests emit a determinism-violation result and quarantine rather than selecting a winner. Model-specific tensor views execute in the model/inference/training ownership boundary, not inside generic shared feature semantics.

Generic `TransformGraph` execution does not imply a permanent `transform_worker` deployable. Data/normalization/curation graphs execute inside the owning data worker/composition root; feature-producing graphs execute in `feature_worker`. A separate transform worker may be introduced only after a measured trust/scaling/release boundary and the normal service/worker split criteria. This keeps the transform engine reusable without turning a source abstraction into an unnecessary process boundary.

### A18.24 Evaluation worker requirements

The evaluation worker resolves an immutable snapshot and suite, acquires retention leases, executes deterministic shards, publishes idempotent sample results, merges only through the evaluation aggregation contract, and finalizes a signed report. It cannot treat dashboard exports as result state.

### A18.25 Inference worker requirements

The inference worker verifies model bundles, compiles/loads a frozen plan, participates in model-aware batching, honors job cancellation and deadlines, and atomically publishes result manifests. Model residency and batching are worker/runtime concerns; request meaning remains in `inference/` and protocols.

### A18.26 Training worker requirements beyond composition

In addition to the existing composition steps, the training worker must:

- verify that its image advertises every selected provider/kernel capability;
- reject stale attempts before distributed rendezvous and before every publication boundary;
- ensure all ranks agree on run, attempt, plan, and checkpoint digests;
- preserve local durable events during control-plane/telemetry outages;
- coordinate rank-zero-only external side effects with distributed consensus/fencing;
- classify collective failures without allowing surviving ranks to publish success;
- perform bounded cleanup of staging artifacts and rendezvous resources.

### A18.27 Agent worker requirements

The agent worker resolves one admitted `AgentRun`, exact agent/workflow/tool/policy versions, scoped credentials, and budget reservation. It then:

- evaluates authorization and biological-safety policy before every consequential tool call;
- validates tool inputs and outputs against exact schemas;
- emits append-only decision, observation, approval, and tool-call receipts;
- submits long-running scientific work through ordinary control-plane job APIs;
- propagates cancellation, deadlines, tenant scope, classification, and correlation;
- enforces iteration, fan-out, token, compute, monetary, time, and artifact budgets;
- pauses at typed approval gates without holding scarce compute;
- fences stale attempts and makes tool side effects idempotent or explicitly reconciled;
- treats model output as untrusted data and never as authorization or proof of execution;
- publishes a terminal agent-run manifest referencing immutable domain artifacts and evaluation evidence.

The worker may host provider adapters, but provider conversation/session state is a cache. Durable replay state belongs to Mindclade events and receipts.

### A18.28 Service runtime baseline

All Go services use `servicekit` for:

```text
configuration and validation
structured logging/tracing/metrics
health/readiness/startup endpoints
HTTP/gRPC/Connect servers
request IDs and auth middleware
rate and concurrency limits
graceful drain and shutdown
database and queue lifecycle
panic containment and error mapping
build/version metadata
```

Readiness reflects dependency state required to serve safely. Liveness is conservative and must not cause restart loops during a dependency outage that the service can safely tolerate.

### A18.29 Availability and consistency classes

Each API declares:

- availability tier;
- consistency model;
- recovery point/time objectives;
- dependency timeout/retry budget;
- whether stale reads are acceptable;
- behavior during artifact, queue, database, identity, or policy outages;
- degraded-mode permissions.

Creating jobs normally requires durable database availability. Reading immutable artifact metadata may tolerate a bounded cache. Authorization never fails open.

### A18.30 Backpressure and overload

Services enforce bounded:

```text
request body and stream sizes
concurrent requests
DB connections and query time
queue enqueue rate
outbox backlog
artifact-transfer sessions
per-tenant and global quotas
```

Overload returns typed retry guidance and preserves health endpoints. Workers bound prefetch, in-flight artifacts, local disk, memory, and heartbeat work. Backpressure propagates instead of creating unbounded goroutines, tasks, or queue messages.

### A18.31 Security baseline

Services and workers use workload identity, mutual authenticated transport where required, least-privilege IAM, restricted egress, secret references, and immutable images. Administrative actions require stronger authorization and audit. Debug endpoints are disabled or separately authenticated in production.

No service logs tokens, signed URLs, raw biological payloads, database connection strings, or worker environment dumps. Error details are classified for client, operator, and restricted diagnostics.

### A18.32 Observability and audit

Every command and worker attempt correlates:

```text
request/trace
principal and tenant/project
resource/job/run
attempt/fence/workload
artifact and plan digests
source revision and image
policy decision
```

Metrics use bounded labels. Audit records cover authentication-sensitive changes, authorization decisions required by policy, administrative operations, artifact access/promotion, cancellation, retry overrides, and terminal state corrections.

### A18.33 Service splitting criteria and protocol

A module split requires evidence of a durable boundary and an ADR. Before splitting:

1. define ownership and data authority;
2. replace in-process calls with a stable application port;
3. define protocol, idempotency, consistency, failure, and migration semantics;
4. establish separate SLO/on-call capacity;
5. migrate data using expand/dual-read-or-write/cutover/contract where necessary;
6. prove rollback and event compatibility;
7. remove the old path.

A split undertaken only to mirror the source tree or team preference is rejected.

### A18.34 Service and worker qualification levels

| Level | Required evidence |
|---|---|
| `service-s0` | domain/unit tests, protocol conformance, authorization and error fixtures |
| `service-s1` | real database/queue/storage adapters, migrations, idempotency, outbox integration |
| `service-s2` | duplicate delivery, stale fence, cancellation, retry, partial-artifact and failure injection |
| `service-s3` | load/backpressure, tenancy isolation, dependency outage, backup/restore and security evidence |
| `service-s4` | production SLO, rollout/rollback, incident drill, provenance and on-call readiness |

Workers also pass domain-specific qualification for the computation they compose.

### A18.35 Capability-local qualification progression

**Milestone 0 — platform libraries and contracts:** identity context, faults, idempotency, revisions, job/attempt/fence, outbox, artifact metadata, and worker base.

**Milestone 1 — one end-to-end asynchronous slice:** create job, transactional enqueue, worker lease, immutable input resolution, heartbeat/cancel, atomic result publication, SDK status.

**Milestone 2 — modular domain coverage:** datasets, models, experiments/runs, policy, quotas, and audit, while retaining one control-plane deployment.

**Milestone 3 — production operations:** HA database, queue recovery, load/backpressure, multi-tenant security, backup/restore, rollout, SLO, and incident drills.

### A18.36 Definition of done

The service and worker architecture is production-ready when:

1. each control-plane module owns explicit aggregates, tables, commands, queries, and events;
2. all mutations enforce authentication, authorization, idempotency, and revision preconditions in a consistent order;
3. job, run, attempt, and Kubernetes workload identities cannot be confused;
4. stale attempts are fenced from every state and artifact publication path;
5. queue duplicate delivery, lease loss, cancellation, and retry cannot corrupt durable state;
6. state plus outbox events commit atomically;
7. artifacts are immutable references and bytes remain outside database/queue payloads;
8. workers are composition roots and do not duplicate domain semantics;
9. backpressure, degraded modes, SLOs, security, and audit are declared and tested;
10. a clean release can roll forward, roll back, restore data, and survive dependency/failure drills.

### A18.37 Final service invariants

- one control-plane database remains the durable business system of record;
- module ownership is enforced even inside one process;
- queues deliver work but do not define truth;
- every worker side effect is tied to a valid fenced attempt;
- success always references verified immutable output;
- Kubernetes status is reconciled evidence, not business authority;
- service extraction follows proven boundaries, not speculative microservice design.
