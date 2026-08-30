## 7. Detailed system designs

The rules in Sections 2, 5, 6, 9, and 10 apply to every system and are not repeated in each contract card. The appendix references are normative elaborations. “Owner” means semantic owner; a service or worker that hosts the code does not acquire its meaning.

### 7.1 Repository architecture and dependency law

**Owner and location.** Developer Platform owns root build files, `tools/repo/`, `tools/bazel/`, the component catalog, and dependency-policy enforcement. Domain teams own their packages and metadata. Architecture Council owns top-level namespace and exceptions. Detailed contract: Appendices A3–A9, A29, A33, and A34.

**Responsibilities.** The repository integration graph MUST make ownership, public surfaces, test closure, release closure, data classification, and dependency direction queryable. Native workspaces retain dependency-resolution authority; Bazel integrates them without inventing a second version graph. A clean checkout with pinned Nix/toolchain inputs MUST reproduce declared source artifacts without undeclared network reads.

**Non-responsibilities.** Repository automation does not contain product behavior, live environment state, or scientific semantics. `libs/` does not absorb domain code. A source directory is not a deployable unless it has a composition root.

**Lifecycle and failure.** A component progresses `PROPOSED -> EXPERIMENTAL -> INTERNAL -> SUPPORTED -> DEPRECATED -> RETIRED`. Creation and promotion are PR-reviewed metadata transitions. Missing owner, cycle, undeclared generator, visibility escape, stale exception, or irreproducible output fails presubmit. Tooling failure may fall back to native local commands for development, but never for release evidence.

**Security, operations, extension, qualification.** Protected branches, signed CI identity, least-privilege registries, dependency review, secret scanning, license policy, and artifact provenance protect the build boundary. Graph size, cache hit rate, build latency, flaky targets, exception age, and orphaned components are operational signals. New language lanes or top-level domains require an ADR, toolchain owner, hermetic build/test/release support, and an acyclic placement. Qualification requires clean-checkout builds on Linux CPU and the relevant GPU profile, native/Bazel lock agreement, zero graph cycles, and exact generated-code drift checks.

### 7.2 Protocols, schemas, generated code, SDKs, and compatibility

**Owner and location.** Contract Governance owns `protocols/` and the compatibility baseline. A domain owner owns semantic fields in its package. Developer Experience owns `sdk/python/` and `sdk/typescript/`; service owners own the curated external API projection. Detailed contract: Appendix A10 and A19.

**Responsibilities and boundaries.** Contract source defines identifiers, commands, resources, events, manifests, errors, pagination, deadlines, and cancellation. SDKs expose stable resource-oriented APIs, typed long-running operations, artifact helpers, and agent sessions. They MUST hide transport retries and generated transport layout without hiding terminal error detail or idempotency semantics. SDKs do not own policy, lifecycle, or scientific meaning.

**Flows and persistence.** Compatibility is checked before generation. Generated internal clients are linked by domain libraries and services. External OpenAPI is projected from an explicit API surface, then SDK transports are generated and wrapped. Compatibility baselines and schema fixtures are versioned in Git; released descriptors, SDK packages, and attestations are immutable artifacts. Breakage produces a new major or migration, never an in-place reinterpretation.

**Failure, security, observability, extension, qualification.** Unknown fields are preserved where the implementation permits; unknown enum values are handled as `UNRECOGNIZED` and cannot authorize action. Invalid or over-limit payloads fail before business processing. Contract metrics include decode failures, unsupported versions, client-version distribution, and deprecated-field use without recording sensitive bodies. A new schema type needs an owner, canonical examples, size limits, data classification, compatibility rules, fuzz/cross-language conformance, and one real consumer. Release gates are Buf lint/breaking checks, JSON Schema meta-validation, golden round trips across all generated languages, OpenAPI diff, SDK integration tests, and clean generation.

### 7.3 Identity, authentication, authorization, tenancy, and audit

**Owner and location.** Security Platform owns identity and authorization foundations in `libs/go/auth/`, `services/control_plane/internal/policies/`, common policy contracts, and audit primitives. Each domain owns its action/resource vocabulary. The control-plane database owns durable grants, memberships, service principals, policy versions, and audit index; Google Identity Platform owns initial human authentication for development, staging, and production. Detailed contract: Appendices A18, A26, A28, A37, and A38.

**Authentication.** Human users authenticate through Google Identity Platform OIDC with phishing-resistant MFA for privileged actions. Local and hermetic tests use a Mindclade-controlled fake issuer with the same validation contract. Workloads use short-lived workload identity; CI uses federated OIDC. Static cloud keys are prohibited. The ingress verifies issuer, audience, signature, expiry, nonce where applicable, and token binding/context before producing an internal `PrincipalContext`. Tenant and project are resolved server-side from authorized membership, never trusted from a client claim alone.

**Authorization.** Services evaluate `Authorize(principal, action, resource, context, policy_version)` before reading sensitive metadata, issuing artifact access, or creating work. Deny overrides allow. High-risk dataset publication, model promotion, agent tool activation, policy change, secret access, and destructive retention transitions require step-up or dual approval according to policy. Workers receive narrow delegated capability tokens bound to tenant, job/run/step, artifact prefixes, actions, deadline, and lease epoch. They cannot mint or broaden capabilities.

```go
type AuthorizationRequest struct {
    Principal PrincipalContext
    TenantID  TenantID
    Action    Action
    Resource  ResourceRef
    Context   DecisionContext
    Policy    PolicyVersion
}

type AuthorizationDecision struct {
    Allowed       bool
    ReasonCode    string
    Obligations   []Obligation
    DecisionID    string
    PolicyDigest  string
}
```

**Tenancy and audit.** Every row and artifact reference is tenant-scoped; globally shared scientific assets use an explicit platform tenant and grant model. Tenant context is mandatory in transaction helpers and cache keys. Cross-tenant aggregation requires a separately authorized, privacy-reviewed path. Audit records are append-only, tamper-evident, time-synchronized, and include actor, tenant, action, resource, request, decision ID, policy digest, result, and safe diff metadata—not secrets or biological payload. Authentication failure, deny rate, cross-tenant guard rejection, privileged action, grant change, and audit-delivery lag are monitored.

**Failure and qualification.** Identity-provider outage fails new privileged operations closed; safe validation of already-admitted bounded workloads may continue until delegated tokens expire. Policy-engine timeout denies. Revocation propagates within the configured maximum of five minutes for interactive access and at the next safe boundary for long workloads, with immediate cancellation for critical revocation. Qualification includes confused-deputy, horizontal/vertical privilege escalation, tenant-crossing property tests, token replay, key rotation, policy rollback, audit completeness, and red-team tool abuse.

### 7.4 Control plane, durable state machines, reconciliation, and outbox

**Owner and location.** Control Plane owns `services/control_plane/`, resource tables, migrations, transaction helpers, reconcilers, outbox, idempotency, leases, quotas, and Kubernetes adapters. Scientific domains own work semantics; workers own execution observations. Detailed contract: Appendices A18, A24, and A28.

**Transaction model.** PostgreSQL-compatible relational storage is the sole durable business-state authority. Each mutating command runs one transaction that: locks or version-checks the resource; inserts/validates the idempotency record; authorizes; writes the desired-state transition; appends audit metadata; and writes one or more outbox rows. Publishing occurs after commit. The dispatcher uses `FOR UPDATE SKIP LOCKED` or an equivalent lease, publishes at least once, and marks delivery with compare-and-swap. Consumers deduplicate.

```go
type UnitOfWork interface {
    WithTx(ctx context.Context, fn func(Tx) error) error
}

func AcceptJob(ctx context.Context, tx Tx, cmd AcceptJobCommand) (Job, error) {
    key, err := tx.Idempotency().Claim(ctx, cmd.Scope(), cmd.RequestHash())
    if err != nil { return Job{}, err }
    job, err := tx.Jobs().InsertAccepted(ctx, cmd.Job())
    if err != nil { return Job{}, err }
    if err = tx.Audit().Append(ctx, JobAcceptedAudit(job, cmd)); err != nil { return Job{}, err }
    if err = tx.Outbox().Append(ctx, ValidateJobEvent(job)); err != nil { return Job{}, err }
    return job, tx.Idempotency().Complete(ctx, key, job.Ref())
}
```

**Reconciliation and fencing.** A reconciler compares desired durable state, latest fenced worker observation, scheduler observation, and deadlines. It issues idempotent actions and records a condition/reason rather than overwriting facts. Each dispatch obtains monotonically increasing `LeaseEpoch`; completion with a stale epoch is retained as evidence but cannot advance state. Kubernetes objects include resource/attempt IDs and plan digest; deletion/recreation is safe because workload state is reconstructible.

**Failures and recovery.** Transaction rollback emits nothing. Commit-before-publish is recovered by outbox scan. Publish-before-ack causes duplicate delivery and is handled by consumer idempotency. Lost heartbeat expires the lease and enters reconciliation; retry policy chooses new attempt, checkpoint resume, failure, or manual intervention. Poison events enter a tenant-scoped dead-letter/quarantine store with alert and replay tool. Cancellation updates desired state first, then signals the scheduler/worker. Control-plane SLOs cover API availability/latency, transaction conflict rate, outbox age, queue age, reconciliation convergence, lease expiry, and stuck state.

**Scaling and qualification.** Stateless API replicas scale horizontally; transaction isolation and advisory/row locks serialize a resource, not the whole service. Reconcilers shard by stable resource hash and use leader election only where external APIs require it. Qualification injects duplicate/reordered events, dispatcher crashes, database failover, scheduler loss, stale leases, partial artifact publication, cancellation races, and rolling-version skew.

### 7.5 Data ingestion, biological parsing, curation, lineage, and publication

**Owner and location.** Data Platform owns `data/` lifecycle and dataset catalog. Computational Biology owns `bio/` meanings, Rust parsers, normalized entity/feature schemas, and conformance. Ingestion/feature workers host execution. Object storage holds immutable objects; the catalog transaction owns release state. Detailed contract: Appendices A11 and A12.

**Responsibilities and non-responsibilities.** Connectors detect source releases and record license/usage metadata; ingestion retrieves bytes resumably; Rust parsers preserve source fidelity; normalization maps to canonical biological entities; curation, deduplication, leakage controls, split assignment, validation, and feature construction produce versioned derived artifacts. Data does not define model architecture or silently correct biological semantics. `bio/` does not schedule acquisition or publish datasets.

```rust
pub trait SourceConnector {
    fn discover(&self, cursor: SourceCursor) -> Result<Vec<SourceRelease>, ConnectorError>;
    fn fetch(&self, object: &SourceObject, sink: &mut dyn ResumableSink)
        -> Result<FetchReceipt, ConnectorError>;
}

pub trait BiologicalParser<I, O> {
    fn parse(&self, input: I, policy: ParsePolicy) -> Result<Parsed<O>, ParseError>;
}
```

**Lifecycle and consistency.** A source snapshot moves `DISCOVERED -> ACQUIRING -> ACQUIRED -> PARSED -> NORMALIZED -> CURATED -> QUALIFIED -> PUBLISHED`, with `REJECTED`, `QUARANTINED`, and `REVOKED` terminal/exception states. Each stage writes immutable outputs and a manifest that references input digests, code revision, schema, policy, and receipts. Publication atomically inserts the released dataset version and its manifest digest after verifying all referenced objects, qualification evidence, licenses, leakage policy, and approvals. Split membership is deterministic from stable biological identity plus split-policy version.

**Failure and recovery.** Fetches resume by byte range/chunk receipt; checksum mismatch quarantines bytes. Parser errors are typed and preserve source location without logging restricted payload. A failed stage retries from immutable inputs; successful outputs may be reused only when the complete cache key, policy, code, and schema match. Source correction creates a new snapshot/version; published artifacts are not mutated. Revocation blocks new use, identifies dependent releases through lineage, and triggers policy-defined quarantine/requalification rather than deleting evidence.

**Security, signals, extension, qualification, scaling.** Connectors use egress allowlists and scoped credentials. Data classification/license/use policy propagates through every manifest. Metrics cover source lag, bytes, checksum failure, parse error taxonomy, quarantine rate, duplicate/leakage rate, stage age, cost, and publication latency without payload labels. A connector extension implements discovery/fetch contracts, rate limits, provenance, fixtures, license review, and sandboxed parsing. Qualification uses golden biological corpora, fuzz/property tests, cross-language entity parity, reproducibility, leakage adversarial tests, lineage closure, and publication rollback. Rust stages scale by object/shard; global dedupe/split stages use deterministic partitioning and explicit merge manifests.

### 7.6 Model architecture, packaging, registry, and release lifecycle

**Owner and location.** Model Architecture owns `models/api/`, components, families, logical state mapping, packaging, and conversion. Artifact/Release owns registry metadata; Evaluation owns promotion evidence. Detailed contract: Appendix A13.

**Responsibilities.** A model family defines configuration, architecture, input/feature contract, outputs, capabilities, logical state schema, initialization, loss-relevant outputs, and conversion. It MUST be executable under the reference single-process path and packageable as a self-describing bundle. Models do not own training loops, data acquisition, scheduling, service APIs, or release approval.

A model bundle separates **semantic requirements** from **model representation**. `FeatureRequirementSetRef` names the reusable semantic information the released model accepts; `ModelFeatureViewRef` names the model-owned deterministic mapping from those semantic features into logical model inputs. The `input_contract` describes the resulting model input surface. This separation permits model tensor views to evolve without mutating biological feature meaning or forcing `data/` to import model implementation.

```python
@dataclass(frozen=True)
class ModelBundleSpec:
    family: str
    model_config: ArtifactRef
    logical_state_schema: ArtifactRef
    weights: tuple[ArtifactRef, ...]
    feature_requirements: FeatureRequirementSetRef
    model_feature_view: ModelFeatureViewRef
    input_contract: SchemaRef
    output_contract: SchemaRef
    code_digest: str
    compatibility: CompatibilityRange

class MindcladeModel(Protocol):
    def capabilities(self) -> frozenset[str]: ...
    def forward(self, batch: ModelBatch) -> ModelOutputs: ...
    def logical_state(self) -> LogicalStateView: ...
```

**Lifecycle and consistency.** A definition progresses `EXPERIMENTAL -> QUALIFIED -> RELEASE_CANDIDATE -> RELEASED -> DEPRECATED -> REVOKED`. Bundle publication is an atomic catalog transaction over an immutable manifest, weight shards, schema references, code/environment closure, evaluation evidence, model card, safety statement, and signature. Aliases such as `stable` are database pointers with audited compare-and-swap and are never persisted as run inputs.

**Failure, security, operations, extension, qualification.** Unknown state key, shape/dtype mismatch, missing artifact, incompatible `FeatureRequirementSetRef`, `ModelFeatureViewRef`, model input contract, or unqualified custom code fails loading before device allocation. Safe tensor formats are required; arbitrary pickle/code execution is prohibited for external artifacts. Metrics include load failures, conversion parity, memory, numerical health, capability use, and deprecation. A new component stays in its family until two real families share an identical stable contract. Qualification covers reference forward/backward, serialization round trip, conversion parity, determinism envelope, checkpoint compatibility, inference/evaluation regression, safety, resource envelope, and rollback to the previous digest.

### 7.7 Training tasks, phase graphs, execution, checkpointing, and recovery

**Owner and location.** Training Systems owns `training/`; Model teams own model/task implementations under the published training contracts; Control Plane owns durable jobs/admission; Runtime/Kernel owners supply qualified capabilities. Detailed contract: Appendix A14.

**Semantic contracts.** `TrainingTask` owns objective-specific runtime batch interpretation, model invocation, objective terms, normalization units, and metrics. Semantic feature resolution and the released model's `ModelFeatureView` run before the task-owned runtime `BatchRecipe`; a task may crop/mask/augment/pack a `ModelInputSample`, but it MUST NOT rediscover shared features, reinterpret `FeatureContract`s, or implement model tensorization. `CompiledStepProgram` is the frozen executable mapping selected from a recipe, task, model bundle, dataset, topology, precision, providers, schedules, and qualification database. The engine owns lifecycle and execution but cannot change task meaning.

```python
class TrainingTask(Protocol):
    def prepare_batch(self, sample: ModelInputSample, context: TaskContext) -> ModelBatch: ...
    def compute(self, model: MindcladeModel, batch: ModelBatch,
                context: StepContext) -> TaskResult: ...
    def normalization(self, result: TaskResult) -> NormalizationUnits: ...

@dataclass(frozen=True)
class CompiledStepProgram:
    plan_id: str
    phase_id: str
    topology: HardwareTopology
    placements: tuple[Placement, ...]
    precision: PrecisionPolicy
    providers: tuple[QualifiedCapability, ...]
    schedule: ScheduleSpec
    checkpoint_contract: CheckpointContract
```

**Planning and execution.** Submission freezes immutable recipe, dataset, model, environment, and policy references. Validation proves contract compatibility and resource bounds. Planning emits an executable plan and resource request; admission binds it to available qualified hardware without mutating semantics. Native PyTorch materializes DeviceMesh/DTensor/FSDP/tensor/pipeline/expert strategies, executes the phase graph, and records actual capabilities. All ranks agree on plan digest, run/attempt/lease, state registry, precision, and checkpoint generation before stepping.

**Progress and checkpoint consistency.** The committed progress frontier advances only when the corresponding optimizer update is accepted. A checkpoint uses prepare/write/verify/commit: each rank writes immutable shards; a coordinator verifies expected membership, sizes, digests, logical-state keys, optimizer/scaler/RNG/data progress, topology metadata, and parent; then atomically publishes the manifest and checkpoint record. Resume reads only committed checkpoints, migrates schema explicitly, replans allowed topology changes, restores logical state, and proves the first resumed update against the recovery contract.

**Failures, security, observability, extension, qualification, scaling.** Non-finite loss/gradient, collective timeout, rank loss, preemption, storage error, corrupt shard, plan mismatch, or data-receipt conflict triggers the declared fault policy: retry safe operation, checkpoint-and-drain, recover from last committed checkpoint, or fail. A stale lease cannot commit. Training workers have no service DB credentials and receive read/write capability only for declared artifacts. Signals include samples/tokens/effective units, update step, loss/gradient health, utilization, memory, collective time, pipeline bubbles, checkpoint duration/backpressure, retries, recovery gap, and cost. Provider extensions map only declared capabilities and require reference/update/checkpoint/recovery parity. Qualification ascends CPU smoke, single GPU, multi-GPU, multi-node, preemption, topology-changing restart, numerical/statistical equivalence, performance, and long-horizon soak. Live elasticity, RL, NVMe offload, Monarch, and non-native trainer control planes are activation-gated.

### 7.8 Evaluation suites, evidence, regression gates, and promotion

**Owner and location.** Evaluation Science owns `evaluation/`; safety/domain reviewers co-own protected suites and thresholds. Release services store decisions but do not define metric meaning. Detailed contract: Appendix A16.

**Responsibilities and flow.** A suite pins dataset snapshot, cohort/split, metric implementations, uncertainty method, resource profile, safety policy, and acceptance rules. An evaluation request resolves immutable model/dataset/suite digests, creates a snapshot and run, executes isolated shards, reduces deterministically where defined, publishes report/evidence, and supplies a promotion decision input. Evaluation does not mutate a model, select training hyperparameters mid-run, or accept self-reported trainer metrics as release evidence.

```python
class EvaluationSuite(Protocol):
    def snapshot(self) -> EvaluationSnapshot: ...
    def evaluate(self, subject: ModelBundle, batch: EvaluationBatch) -> MetricBatch: ...
    def reduce(self, parts: Sequence[MetricBatch]) -> EvaluationReport: ...
    def decide(self, report: EvaluationReport, baseline: ReleaseRef) -> GateDecision: ...
```

**Lifecycle, failure, security, scaling.** Runs move `CREATED -> SNAPSHOTTED -> RUNNING -> REDUCING -> PUBLISHED` or fail/cancel. Partial shard outputs are immutable but not publishable until completeness and reduction checks pass. Retrying a shard is idempotent by suite/model/dataset/shard digest. Hidden or safety sets use restricted service identities; model workers cannot read labels beyond the required shard. Signals include queue/run age, metric distributions and uncertainty, baseline deltas, missingness, invalid output, cohort coverage, cost, and policy failures. Suites scale by deterministic shard and associative reduction when mathematically valid. Qualification includes metric unit/property tests, goldens, leakage checks, repeated-run stability, cross-version baseline replay, adversarial/safety cases, and gate fail-closed tests.

### 7.9 Online and batch inference

**Owner and location.** Inference Systems owns `inference/` semantics and inference worker composition. Runtime Gateway owns authorization, admission, streaming, quotas, and routing. Detailed contract: Appendix A17.

**Responsibilities and boundaries.** Inference defines input validation, request-to-feature resolution orchestration, model feature-view application, batching compatibility, model execution, candidate generation, confidence, ranking, postprocessing, and scientific artifact schema. Shared semantic `FeatureKeyDigest` construction and materialization obey `bio/`/`data/` authority; inference owns only request/model-view and runtime cache policy above that boundary. The gateway does not implement model math. Inference code does not authenticate users or mutate durable job state. Online calls use a bounded request/stream; batch inference uses the generic `Job/Run/Attempt` lifecycle.

**Flow and state.** Authorization resolves tenant and released model policy. Preprocessing validates schemas and data policy, then resolves shared semantic features through an authorized tenant/policy/security-partitioned `FeatureKeyDigest` projection and applies model-release/view identity only to model-specific derived views. All caches contain only reconstructible state. Admission chooses a qualified deployment and bounded batch class. Execution records model/kernel/environment digests. Candidate artifacts are written before a durable result manifest is committed. Streaming frames include monotonically increasing sequence, request ID, terminal status, and resumable artifact reference where supported.

**Failure, recovery, isolation, signals, extension, qualification.** Overload rejects with retry-after; it does not create unbounded queues. Deadline/cancel propagates to batch scheduler and GPU safe points. Worker failure retries only if no externally committed terminal frame or with an explicit resume token. Cache corruption evicts and recomputes. Tenant fairness uses weighted quotas and per-tenant concurrency; cache and batching never cross incompatible policy/tenant classes. Signals include admission latency, queue time, batch fill, pre/postprocess time, first/last token or candidate latency, GPU utilization, cache hit/corruption, invalid output, fallback, cost, and error class. New samplers/rankers are versioned capabilities. Qualification covers reference parity, request/stream conformance, load/shedding, cancellation, cache isolation, deterministic modes, batch/online agreement, safety, and rollback.

### 7.10 Agents, tools, policy, state, workflows, and sandboxing

**Owner and location.** Agent Platform owns `agents/` contracts/runtime and `workers/agent_worker/`; Security/Safety own policy floors; scientific domains own tool results. Go Control Plane owns durable sessions/runs/steps/approvals/budgets. MADK owns authoring façade only. Detailed contract: Appendix A36.

**Responsibilities and boundaries.** An `AgentDefinition` pins a model capability, workflow, allowed tool-set constraints, memory policy, budgets, approval gates, evaluation policy, and release compatibility. A `ToolContract` declares typed input/output schemas, permissions, data classification, egress, idempotency, side effects, timeout, compensation, sandbox profile, and qualification. Agents orchestrate capabilities; they do not own biological truth, service authorization, inference state, or artifact lineage. Tool adapters never bypass service APIs or artifact controls.

```proto
message AgentRun {
  string agent_run_id = 1;
  string tenant_id = 2;
  string agent_definition_digest = 3;
  string workflow_digest = 4;
  repeated string tool_contract_digests = 5;
  string policy_digest = 6;
  string budget_id = 7;
  AgentRunState state = 8;
  int64 resource_version = 9;
}

message AgentStepCommand {
  string agent_run_id = 1;
  string agent_step_id = 2;
  uint64 lease_epoch = 3;
  string capability_token = 4;
  string input_artifact_digest = 5;
  google.protobuf.Timestamp deadline = 6;
}
```

**Lifecycle and consistency.** An agent release independently versions definition, workflow, tool set, and policy constraints. Run creation freezes their exact digests. `AgentRun` moves `CREATED -> RESOLVING -> READY -> RUNNING -> EVALUATING -> FINALIZING -> COMPLETED`, with `WAITING_APPROVAL`, `PAUSED`, `RECOVERING`, `FAILED`, and `CANCELLED`. Each step is created and budget-reserved transactionally with its outbox command. A fenced worker publishes immutable input/output observation and invocation receipt; reconciliation validates schema, capability, policy, budget, and epoch before committing the step transition and next edge. Memory stores references to governed artifacts/events with provenance, ACL, purpose, retention, and tenant; a vector index is reconstructible and never authoritative.

**Sandbox and safety.** Tools run outside trusted model/data/training processes in a sandbox profile with non-root identity, read-only base image, ephemeral filesystem, seccomp/AppArmor or equivalent, CPU/memory/time limits, explicit egress allowlist, no ambient cloud credential, and delegated artifact/API capabilities. Customer code and arbitrary binaries require a higher-isolation runtime and are deferred until a threat model and qualification exist. Model/tool output cannot select permissions or policy. Biological safety policy evaluates request, plan, each high-risk tool action, output publication, and release. Irreversible or high-risk action pauses for human approval with exact planned effect and expiry.

**Failure, replay, observability, extension, qualification, scaling.** Duplicate step execution is handled by step idempotency and tool side-effect keys. Timeout, policy denial, budget exhaustion, invalid output, tool crash, approval expiry, or sandbox violation follows a typed transition and compensation/recovery policy. Replay reuses frozen inputs/observations without reissuing side effects unless explicitly authorized. Signals include run/step latency, policy decisions, approval wait, tool error/timeout, budget and token/cost use, sandbox denial, replay divergence, artifact lineage, and safety alerts. New tools require schemas, permissions, threat model, receipts, mocks/simulator, idempotency classification, compensation, adversarial tests, and release owner. Agent workers scale by sandbox and model/tool class; one tenant cannot consume another tenant's quota.

### 7.11 GPU kernels, reference implementations, qualification, and fallback

**Owner and location.** Kernel Engineering owns `kernels/`; the model/domain owner approves operation semantics; Runtime owns dispatch infrastructure. Detailed contract: Appendix A15.

**Contract.** Every operation has a readable PyTorch reference, signature including layouts/dtypes/shapes/semantics, forward/backward/autograd contract, numerical tolerance policy, deterministic policy, memory/aliasing rules, capability predicate, and benchmark definition. TileLang/CUDA/C++ implementations register an artifact digest and qualification envelope; model code invokes the operation, never a vendor kernel directly.

```python
class KernelImplementation(Protocol):
    def supports(self, sig: OperationSignature, hw: HardwareProfile) -> SupportResult: ...
    def execute(self, inputs: tuple[Tensor, ...], *, workspace: Workspace) -> KernelResult: ...
    def qualification(self) -> KernelQualificationRef: ...
```

**Dispatch and failure.** Dispatch uses operation version, exact signature, hardware/software profile, determinism/precision policy, and current non-revoked qualification. It selects a qualified implementation or the reference fallback. If no permitted implementation meets resource bounds, it fails explicitly. Runtime autotuning may choose only among prequalified candidates and stores an immutable record keyed by full envelope; it cannot alter math. Illegal memory access, NaN/Inf deviation, timeout, compilation failure, or revocation quarantines the candidate and falls back where safe.

**Security, observability, extension, qualification, scaling.** Kernel sources and binaries are signed; runtime compilation is disabled in restricted production profiles unless sandboxed and attested. Signals include selection/fallback, compile/cache time, latency/throughput, workspace, numerical anomalies, and qualification age. Qualification covers property/golden tests, gradient/second-order behavior where supported, boundary shapes, dtypes, layouts, determinism, sanitizers, fuzzing, multi-GPU interaction, target hardware matrix, performance guardrails, and long-run stability. Performance alone never overrides parity.

### 7.12 Artifact storage, metadata, integrity, provenance, retention, and recovery

**Owner and location.** Artifact Platform owns shared artifact contracts/client libraries and catalog integration; domain owners own manifest semantics. Cloud Operations owns bucket lifecycle/replication. Detailed contract: Appendix A23 and A38.

**Storage and consistency.** Bytes are written to a staging key while a streaming digest and size are computed. Finalization verifies integrity, writes or deduplicates the content-addressed object, then atomically creates catalog metadata and references. A manifest is itself an immutable artifact. The database stores digest, media type, size, tenant/classification, encryption context, state, provenance edges, retention/legal-hold state, and object locations; it does not store large payloads.

```json
{
  "schema_version": "1.0.0",
  "artifact": {"digest": "sha256:<hex>", "size_bytes": 0, "media_type": "application/vnd.mindclade+json"},
  "producer": {"source_revision": "<git-digest>", "build_provenance": "sha256:<hex>"},
  "inputs": [{"digest": "sha256:<hex>", "role": "source"}],
  "policy": {"tenant_id": "ten_...", "classification": "restricted", "retention_class": "scientific-evidence"},
  "integrity": {"algorithm": "sha256", "signature": "<sig-ref>"}
}
```

**Failure and recovery.** Interrupted uploads resume by verified chunks or expire. Catalog rows never point to unverified final objects. Orphan staging objects are swept after a safety window. Missing/corrupt objects trigger quarantine and lineage impact analysis; replicas restore only after digest verification. Deletion marks eligibility, checks references/holds/revocation policy, records a tombstone, and asynchronously removes replicas. Security uses per-environment service identity, tenant/classification authorization, KMS encryption, malware/content validation for untrusted inputs, and short-lived signed access. Signals include integrity failure, finalize latency, orphan bytes, replication age, restore tests, access denies, egress, retention backlog, and cost. Qualification includes concurrent finalize, partial upload, corruption, catalog/object split-brain simulation, cross-region restore, key rotation, legal hold, and provenance closure.

### 7.13 Observability, SLOs, profiling, cost, and incident response

**Owner and location.** Observability Platform owns `libs/*/observability/`, collectors, semantic conventions, and telemetry backend; each component owner owns its instrumentation, SLO, dashboards, alerts, and runbook. Detailed contract: Appendix A25 and A38.

Telemetry uses OpenTelemetry-compatible traces, metrics, and structured logs with stable resource attributes: service/component version, environment, region/cluster, tenant hash or approved tenant label, project, job/run/attempt/step, model/dataset/release digest prefixes where cardinality policy permits, hardware profile, and cost attribution. Trace context propagates through RPC and events. Metrics—not log parsing—drive SLOs. Raw sequences, structures, prompts, tool outputs, credentials, access tokens, signed URLs, and unrestricted manifest bodies are prohibited telemetry fields.

Each service defines availability/latency, each queue defines age/convergence, and each scientific workload defines correctness/throughput/freshness signals. Profiling is opt-in, bounded, redacted, and attributable. Cost is allocated by tenant/project/workload/release/hardware and compared with useful scientific work units. Incident severity, command ownership, communication, evidence preservation, rollback, and post-incident action tracking are in runbooks. New components cannot reach supported maturity without alerts for exhausted error budget, durable backlog, failed reconciliation, integrity/security violations, and resource saturation.

### 7.14 Infrastructure, GCP/GKE, multicloud, and on-premises

**Owner and location.** Security and Cloud Platform own minimum root trust in `bootstrap`; Cloud Platform owns normal cloud desired state in `infrastructure-live`; Platform Operations owns Kubernetes desired state in `gitops`; Developer Platform owns GitHub governance in `github-config`; the monorepo owns service deployment packages in `deploy/` and MCDK contract/tooling in `kits/mcdk/`. Detailed repository contracts and trees: Appendix A3.8–A3.17. GCP runtime profile: Appendix A37.

The primary target is GCP/GKE. The governed environments are development, staging, and production; `us-central1` is the primary region and `us-east4` is the recovery region. Production uses separate projects/accounts and workload identities by environment and trust class, private GKE control/data paths, regional control-plane database, GCS artifact buckets, Artifact Registry, Secret Manager/KMS, a managed queue/event service, and centralized observability export. CPU services, general workers, GPU inference, GPU training, and untrusted/sandboxed agent tools use distinct node pools and service accounts. Kueue owns quota/admission; JobSet/Jobs own batch topology; the Go control plane owns business state. Accelerator quota/capacity and live environment qualification remain evidence gates rather than consequences of this placement decision.

MCDK is a Go implementation that validates an environment assembly and emits a signed, immutable `EnvironmentPlan` with target-neutral logical requirements and a provider binding. It can plan local/integration resources from this monorepo. Production apply occurs only in `infrastructure-live` using reviewed OpenTofu modules, bootstrap-provided state/identity roots, and federated apply identity. Kubernetes desired-state promotion occurs only in `gitops` using monorepo-built chart/image/config digests. The monorepo has no production apply credential.

Multicloud and on-premises extensions implement bounded ports for workload identity, object store, queue, relational database, scheduler/admission, secret/KMS, image registry, and telemetry export. They MUST pass the same artifact, tenant, cancellation, fencing, checkpoint/recovery, security, and evidence conformance suite. On-prem is not “GCP emulation”: it supplies a signed `EnvironmentCapability` manifest, approved storage durability profile, identity federation, offline artifact import/export, accelerator qualification, observability buffering, and recovery procedure. Provider-neutral abstractions are added only at these boundaries, not around every cloud API.

### 7.15 CI/CD, supply-chain security, and release qualification

**Owner and location.** Developer Platform owns CI/build orchestration; Security owns supply-chain policy and signing roots; component owners own qualification; Release Engineering owns promotion tooling. Monorepo locations: `.buildkite/`, `mindclade/.github/`, `tools/ci/`, `tools/release/`, `tools/qualification/`, and `deploy/`. Shared workflows and governance live in the organization `.github` and `github-config` repositories. Detailed contract: Appendices A3, A21–A24, A26, and A38.

Presubmit computes affected targets plus reverse dependency/risk expansion, then runs formatting, lint, type checks, schema compatibility, unit/property/fuzz tests, architecture policy, license/security scanning, and appropriate CPU/GPU/integration suites. Trusted post-merge builds run hermetically with pinned dependencies and isolated workers, emit SBOMs in SPDX or CycloneDX, provenance linking source and builder, vulnerability/license results, test evidence, and signed artifacts. Pull-request code never receives release signing or production credentials.

Release candidates are immutable subject digests. Qualification policy resolves required evidence from artifact class, data classification, hardware, and maturity. Promotion verifies subject digest, evidence digests, signatures, approval, revocation status, and environment policy, then updates `gitops` by digest. Rollback re-points desired state to a previously qualified digest; revocation blocks future admission and may trigger active rollback. No environment rebuild occurs.

### 7.16 Developer experience, local environments, testing, and contribution

**Owner and location.** Developer Platform owns Nix/devcontainer/toolchain setup, `just` workflows, generators, and repository documentation. Domain teams own focused guides, fixtures, and examples. Detailed contract: Appendices A8, A9, A22, and A30.

A new contributor runs one bootstrap command, one repository doctor, and domain-specific `just` commands that delegate to Bazel/native tools without hiding exact commands or evidence. Profiles are `cpu`, `gpu-dev`, and `cluster-client`; CPU work MUST not download CUDA/PyTorch GPU stacks. Local integration uses ephemeral database/object/queue emulators or containers through `deploy/local/`, synthetic biological fixtures, and fake identity. Production secrets and data are prohibited locally.

Generators create a real package/component from an approved type and require owner, dependency class, public surface, tests, and metadata; they do not create empty trees. Code generation is explicit and reproducible. Contribution flow is branch/PR, affected checks, CODEOWNER/security/scientific review by risk, merge queue, trusted build, and optional release qualification. Documentation examples are compiled/tested. Flake ownership, quarantine expiry, build latency, bootstrap success, editor diagnostics, and developer feedback are tracked as product signals.

---

### 7.17 Feature contracts, plan lowering, cache projection, and model views

**Owner and location.** Computational Biology owns reusable feature meaning in `bio/featurization/`; Data Platform owns feature requirement resolution, feature-specific identity/cache projection, materialization, coverage, and publication in `data/featurization/`; generic graph validation/planning/execution is owned once in `data/transforms/`. A `FeaturePlan` lowers to a constrained `TransformGraph` rather than creating a parallel DAG engine. Model families own their feature requirements, deterministic model views, tensorization, and packing in `models/families/*/*/features/`; `workers/feature_worker/` is the execution composition root. Artifact Platform owns generic CAS/finalization primitives. No separate feature-store service or top-level feature domain is introduced. Detailed contract: Appendix A39, with supporting rules in Appendices A7, A11–A14, A17, A18, A23, and A40.

**Semantic layers.** Feature processing is split into canonical records, reusable semantic features, optional deterministic model-specific derived features, model tensor views, and runtime stochastic transforms. Shared feature identity describes scientific meaning rather than tensor layout. A model declares `FeatureRequirement`s against versioned biological feature contracts; it does not name cache paths or import data-pipeline internals. Model-specific layout, embedding indices, bucketization, PyTorch tensorization, packing, and device conversion remain model/runtime concerns.

**Derivation and cache identity.** `FeatureKeyDigest` is the canonical digest of the output feature contract, immutable input artifacts/canonical records, upstream feature manifests, derivation semantic operator/version, exact implementation digest or approved equivalence-class qualification, semantic parameters, relevant database/tool snapshots, cutoff/leakage policy, and any declared seeded randomness. A cache lookup additionally carries tenant/policy/security partition. Path, PDB/UniProt ID alone, row number, mutable model alias, worker identity, wall clock, and unordered serialization are prohibited key material.

**Storage and consistency.** A resolved cache hit returns a verified immutable `FeatureManifest`/artifact reference, never a trusted filesystem path. The feature resolver expands requirements, prunes verified hits, emits a `FeaturePlan`, and lowers remaining work to the generic typed `TransformGraph`; only missing feature-producing nodes execute. Publication uses stage → validate → canonical encode → hash → CAS finalize → immutable manifest → compare-and-swap index publication. The derivation index is a reconstructible projection and may be rebuilt from manifests/catalog state. If two valid attempts for one deterministic `FeatureKeyDigest` produce different output digests, the system records `DETERMINISM_VIOLATION`, quarantines the results, and fails closed.

**Training, evaluation, and inference.** Training `BatchReceipt`s identify feature bundle/manifests plus packing and logical RNG derivations; stochastic crops, masks, augmentation, diffusion noise, and device casts are generated after durable feature resolution. Evaluation verifies external database snapshots, source cutoffs, and leakage-sensitive feature provenance before accepting a feature bundle. Inference uses the same shared resolution contract and then applies model-owned tensor views; online caches remain tenant/policy partitioned and reconstructible. Qualification covers cross-model reuse, key stability, implementation parity, race/fencing, corruption, snapshot/cutoff changes, leakage denial, and model-view separation.

### 7.18 Feature and data transform architecture

**Owner and location.** Data Platform owns the transform composition contract, the single generic `TransformGraph`, graph validation, execution planning, receipts, fitted-state plumbing, compact lineage mapping, and local execution adapters in `data/transforms/`. Domain packages such as `data/normalization/`, `data/curation/`, `data/deduplication/`, `data/splits/`, and `data/sampling/` continue to own the scientific/data meaning of their operations. Computational Biology owns reusable semantic feature transforms under `bio/featurization/`. Model families own deterministic model-view transforms under `models/families/*/*/features/`. Training and inference own runtime batch/request transforms after durable feature resolution. No generic transform package may become a shadow owner for biological meaning, curation policy, model mathematics, training randomness, feature-cache truth, or workflow lifecycle. Detailed contract: Appendix A40; feature derivation/cache rules remain Appendix A39.

**Transform planes.** Mindclade distinguishes five transform classes: source/canonical data transforms, dataset transforms, reusable semantic feature transforms, model-view transforms, and runtime stochastic transforms. A `TransformSpec` declares input/output contracts, semantic operator/version, cardinality, ordering semantics, determinism class, state scope, required snapshots/resources, schema change, materialization policy, side-effect policy, and implementation/equivalence identity. A transform graph is dataflow intent; it is not a scheduler, queue, or business-state machine.

**Identity and receipts.** `TransformSemanticKey` identifies semantic behavior from the transform specification, exact immutable inputs, semantic parameters, snapshots, qualified implementation/equivalence identity, fitted-state reference when applicable, and logical RNG only when randomness is semantic. `TransformExecutionPlanDigest` separately records backend, partition count, worker parallelism, fusion, spill, physical materialization, and other replaceable execution choices. A `TransformReceipt` binds both identities to actual inputs/outputs, counts, exclusions, partitioning, validation, resource/runtime identity, and lineage. One-to-one transforms preserve a sample identity only when semantic sample identity is unchanged; one-to-many, many-to-one, joins, aggregation, splitting, and repartitioning follow explicit identity rules rather than row numbers or storage paths.

**Execution and optimization.** Production transform functions are pure with respect to declared inputs: network access, credential resolution, mutable catalog writes, and publication occur in composition roots/adapters, not hidden inside semantic operators. Rust is preferred for streaming, bounded-memory, parsing-adjacent, and CPU-intensive transforms; Python is preferred for scientific reference logic and model-adjacent transforms. Arrow-compatible batches/artifact references are the default cross-language boundary. An external execution engine such as Spark may later execute qualified `TransformGraph` fragments when corpus scale proves the need, but it cannot own transform semantics, identity, lineage, or publication and MUST preserve the same receipts and deterministic partition contract.

**Fitted state.** Transform classes that learn state use an explicit `fit → TransformStateArtifact → apply` contract. `FitSemanticKey` and `FitReceipt` identify the fitting dataset/snapshot, fitting scope, parameters, implementation/equivalence qualification, and output state artifact. Evaluation rejects state fit on disallowed cohorts or future snapshots. Normalization statistics, vocabularies, calibration parameters, learned projections, centroids, and fitted thresholds therefore cannot hide training/evaluation leakage inside an ordinary stateless transform.

**Caching, training, and evaluation.** Appendix A39 cacheability is a property of a transform result, not of the transform framework. Deterministic durable transforms may materialize content-addressed artifacts; cheap or runtime-only transforms may remain ephemeral. Transform fusion, projection pushdown, batching, vectorization, and partition coalescing are legal only when they preserve declared semantics, order/cardinality, RNG, validation, and receipt equivalence. Training batch transforms derive randomness from logical run/sample/step identity; evaluation verifies snapshot/cutoff and leakage policy before transform execution; inference keeps request-specific transforms isolated from shared semantic feature artifacts.
