## Appendix A17 — Inference architecture

Separate pure model execution from network serving.

`inference/` owns:

- request-to-feature resolution orchestration and model-view application, while shared feature derivation semantics/materialization remain in `bio/` and `data/`;
- bucketing and batching policy;
- model execution;
- diffusion/sample orchestration;
- confidence computation;
- ranking;
- postprocessing;
- artifact production;
- execution diagnostics.

`services/runtime_gateway` owns:

- authentication and authorization;
- request validation;
- tenancy and quotas;
- durable job creation;
- streaming/status protocol;
- routing;
- public error mapping.

`workers/inference_worker` owns:

- queue/lease integration;
- GPU process lifecycle;
- model bundle acquisition;
- invocation of `inference/`;
- heartbeats and cancellation;
- artifact upload;
- operational telemetry.

### Reference asynchronous request flow

```text
client
  -> runtime gateway
  -> validate and authorize
  -> durable inference job
  -> data/feature preparation
  -> feature artifact
  -> resource-aware admission
  -> inference worker
  -> model trunk and generative sampling
  -> confidence and ranking
  -> immutable output artifacts
  -> job completion event
  -> SDK presents result
```

Large results are artifact references, not embedded database rows or queue messages.

### A17.1 Inference-system planes

Inference separates five authorities:

```text
public request and durable job semantics
→ feature preparation and immutable input artifacts
→ pure model/sampling execution
→ confidence, ranking, postprocessing, and result artifacts
→ operational serving composition
```

`inference/` owns execution semantics. `runtime_gateway` owns the public edge and durable request lifecycle. `inference_worker` owns GPU-process composition. `models/` owns mathematics and bundle contracts. `data/` and `bio/` own feature and biological semantics. No worker endpoint becomes a second public API.

### A17.2 Inference request contract

A resolved inference request references:

```text
model or deployment resource and immutable resolved bundle
input payload or immutable input artifact
requested capability/task
feature/preprocessing policy
sampling/decoding policy
confidence/ranking policy
output schema and artifact options
resource/latency class
reproducibility intent
safety and data-classification context
idempotency key
```

The gateway canonicalizes the request and records a digest. Mutable model aliases are resolved before admission. Public requests never contain provider globals, Kubernetes placement, raw object-store destinations, or executable-plan internals.

### A17.3 Synchronous and asynchronous modes

Use synchronous inference only when the complete operation fits a bounded latency, payload, and reliability envelope. Otherwise return a durable job.

| Mode | Contract |
|---|---|
| synchronous | bounded request and response, cancellation tied to connection plus server deadline, no large artifacts inline |
| asynchronous | durable job, resumable status/stream, explicit cancellation, immutable results |
| streaming | resumable ordered progress or partial semantic output; final durable result remains authoritative |
| batch/offline | manifest of immutable requests, independently retryable units, aggregate result manifest |

A client disconnect does not silently cancel an asynchronous job. A synchronous operation that outgrows the contract must fail with a typed recommendation or be explicitly submitted asynchronously; it cannot disappear into background work without a durable identity.

### A17.4 Durable inference lifecycle

```text
RECEIVED
→ VALIDATING
→ RESOLVING_ARTIFACTS
→ FEATURE_PREPARATION
→ QUEUED
→ ADMITTED
→ LOADING
→ RUNNING
→ POSTPROCESSING
→ PUBLISHING
→ SUCCEEDED
```

Any active state may transition through `CANCELLING` to `CANCELLED`, through retry policy to `RETRY_WAIT`, or to a classified `FAILED` state. State transitions are fenced by job revision and worker attempt. Progress is monotonic and safe to replay.

### A17.5 Feature preparation and model-view contract

Inference resolves the released model's `FeatureRequirement`s through the shared Appendix A39 derivation contract. Request-to-feature conversion records:

- input artifact/payload and canonical-record digests;
- biological parser and normalization versions;
- semantic `FeatureContract` requirements and `FeatureKeyDigest`s;
- upstream feature manifest/artifact references;
- external database/tool snapshot, cutoff, and retrieval-policy references;
- deterministic semantic parameters and any explicitly seeded feature RNG identity;
- tenant/project/policy/security cache partition;
- output `FeatureBundle`, individual feature manifests, and validation evidence;
- model feature-view contract and deterministic model-input artifact when one is materialized.

Feature preparation may run in a distinct CPU feature worker. The GPU inference worker receives immutable verified bundle/model-input references, not a mutable shared directory. It then performs model-owned tensorization/packing and runtime-only device views. Sampling RNG, diffusion noise, runtime padding, and ephemeral batching state are not reusable semantic feature-cache entries.

Cache hits are accepted only when the complete semantic derivation key and authorized cache partition match. Cache corruption or an unverified manifest is classified and regenerated only from immutable authorized inputs; inference never broadens tenant policy to obtain a hit.

### A17.6 Pure inference API

A provider-neutral execution API may resemble:

```python
from dataclasses import dataclass
from typing import Generic, Protocol, TypeVar

InputT = TypeVar("InputT")
OutputT = TypeVar("OutputT")

@dataclass(frozen=True, slots=True)
class InferenceContext:
    request_id: str
    attempt_id: str
    rng: "RNGStreams"
    execution_plan: "InferenceExecutablePlan"
    cancellation: "CancellationToken"

class InferencePipeline(Protocol, Generic[InputT, OutputT]):
    def prepare(self, source: "FeatureArtifact") -> InputT: ...
    def execute(self, model: "MindcladeModel", value: InputT,
                context: InferenceContext) -> OutputT: ...
    def finalize(self, output: OutputT,
                 context: InferenceContext) -> "InferenceResult": ...
```

The API does not authenticate users, poll queues, resolve credentials, or write job state. Execution returns typed results and deferred artifact intents.

### A17.7 Inference executable plan

A production invocation uses a frozen plan containing:

```text
model bundle and logical-state selection
hardware topology/class
replication/sharding/parallel placement
precision and quantization policy
shape/work-unit buckets
batch and padding policy
provider and kernel selections
compiled regions and graph guards
sampling concurrency and memory limits
artifact staging budget
reproducibility and fallback policy
```

The plan may differ from the training plan but uses the same logical state and capability vocabulary. Silent provider or precision changes are prohibited after model load.

### A17.8 Model bundle loading and residency

The loader verifies manifest, digest, signature, schema, tokenizer/component versions, precision state, and provider/kernel compatibility before materialization. Loading follows:

```text
resolve immutable bundle
→ verify policy and signatures
→ select/compile executable plan
→ reserve memory
→ materialize logical state
→ validate lightweight health fixtures
→ mark replica ready
```

A replica is not ready merely because the process has started. Readiness requires a verified model and a successful bounded health invocation. Failed or partially loaded bundles are never served.

Model residency policy defines pinning, least-recently-used eviction if allowed, concurrent versions, warm pools, load deadlines, and memory fragmentation limits. Eviction cannot affect in-flight requests.

### A17.9 Batching and admission

The scheduler batches only requests with compatible:

```text
model bundle and plan
feature/output schema
shape bucket and semantic padding
precision/provider/kernel requirements
sampling/decoding policy where vectorization requires equality
safety/data-isolation constraints
latency class
```

Batching optimizes model-aware work units rather than request count alone. It enforces per-request deadlines, maximum queue delay, peak memory estimates, fairness, tenant quotas, and cancellation removal. A large request cannot indefinitely starve small requests or bypass quota through packing.

### A17.10 Dynamic batching correctness

Qualification proves that supported batched and unbatched execution are equivalent under the declared tolerance. Tests cover:

- heterogeneous lengths/shapes;
- padding and masks;
- packed versus padded representations;
- cancellation before and during batch formation;
- one failing request within a batch;
- deterministic sample-keyed RNG independent of batch neighbors;
- result demultiplexing and artifact ownership;
- no cross-tenant data exposure through reused buffers.

### A17.11 Sampling, diffusion, and candidate generation

A `SamplingPolicy` declares:

```text
algorithm/solver and version
number of candidates/samples
steps and schedules
temperature/guidance/conditioning
early-stop or convergence criteria
sample-key derivation
parallelism and memory policy
validity filters
maximum compute budget
```

Each candidate has a stable identity derived from request, policy, and sample index. Retrying a deterministic request reproduces candidates under the declared stack. Best-of-N and adaptive sampling record every attempted candidate and stopping rule.

### A17.12 Confidence and ranking

Confidence and ranking are explicit stages with versioned contracts. They define:

- required model outputs and state;
- calibration artifact/version;
- per-residue, per-atom, per-interface, or global semantics;
- candidate scoring and tie-breaking;
- invalid-candidate handling;
- ensemble aggregation;
- uncertainty interpretation;
- output calibration range.

Ranking does not overwrite raw model outputs. Result manifests preserve all retained candidates, score components, selected candidate, and selection rationale.

### A17.13 Postprocessing and biological output

Postprocessing handles coordinate transforms, chain/residue naming, chemical-component reconstruction, stereochemical checks, clash/validity diagnostics, sequence decoding, and format emission. It uses canonical `bio/` semantics and declares all lossy transformations.

Outputs may include:

```text
mmCIF or another canonical structure artifact
sequence/design artifact
confidence and ranking JSON
per-candidate diagnostics
feature/provenance manifest
request and model lineage
rendered previews as derived artifacts
```

File names are presentation only. Consumers use manifest references and schema versions.

### A17.14 Artifact publication protocol

```text
reserve result generation
→ stage artifacts under attempt-scoped paths
→ verify size, digest, schema, and policy
→ publish immutable result manifest
→ transactionally mark job succeeded with manifest reference
→ garbage-collect abandoned staging after attempt fencing
```

A stale attempt cannot publish. The job never reaches `SUCCEEDED` before the result manifest is complete and verified. Large result bytes never flow through the relational database or queue.

### A17.15 Idempotency, retries, and deduplication

The gateway deduplicates equivalent creation requests by client idempotency key and canonical request digest. Internally:

- feature transformations use content-addressed idempotency;
- worker attempts are unique and fenced;
- candidate identities are deterministic;
- artifact publication is generation-based;
- retry policy distinguishes request-invalid, policy-denied, transient infrastructure, resource, numerical, and model failures.

Retrying cannot produce two authoritative results for the same job. When stochastic best-effort behavior is requested, each attempt's randomness and result lineage remain explicit.

### A17.16 Cancellation and deadlines

Cancellation propagates:

```text
client/control-plane intent
→ durable job desired state
→ queue/lease notification
→ worker cancellation token
→ safe points in feature, batching, sampling, and publication
```

A rank-synchronous or captured GPU region is not interrupted unsafely. The worker reaches a defined safe point, stops new candidates/microbatches, releases artifacts or publishes an explicitly partial diagnostic result only when the API permits it, and acknowledges terminal cancellation. Deadlines and cancellation are separate: deadline expiration follows a typed policy and may still preserve diagnostic artifacts.

### A17.17 Failure taxonomy and health policy

Classify:

```text
request/schema invalid
feature incompatibility or external-source failure
model bundle/signature/state incompatibility
admission timeout or quota denial
OOM/resource exhaustion
kernel/provider/compiler failure
NaN/Inf or invalid geometry
sampling non-convergence
cancellation/deadline
artifact publication failure
worker/node/lease failure
policy or safety denial
```

The plan names permitted fallbacks. Production scientific results do not silently switch model version, precision, sampling budget, ranker, or provider after a failure.

### A17.18 Online serving versus asynchronous scientific jobs

Use separate deployment profiles:

| Profile | Priorities |
|---|---|
| interactive online | bounded latency, warm models, conservative sample counts, cancellation, autoscaling |
| asynchronous scientific | throughput, large variable shapes, durable artifacts, longer sampling, queue admission |
| batch campaign | manifest-driven work, reproducible shard assignment, large-scale aggregation |
| qualification | deterministic plans, reference comparisons, extensive diagnostics, fail-closed behavior |

They may share `inference/` semantics and kernel/model artifacts but have separate SLOs, queues, resource profiles, and qualification.

### A17.19 Multi-tenancy and isolation

Inference enforces tenant/project authorization at the gateway and again on artifact resolution. Worker credentials are scoped to the leased job. Isolation includes:

- no cross-tenant batching unless a reviewed policy proves buffer and metadata isolation;
- tenant-aware quotas and fairness;
- restricted-data worker pools and egress rules;
- attempt-scoped working directories and encryption;
- buffer clearing or allocator isolation where required;
- result references authorized independently of job visibility;
- no customer payloads in metrics or unbounded logs.

### A17.20 Safety and biological governance

Before execution and publication, policy may evaluate:

```text
input classification and allowed use
restricted sequence/structure controls
model capability and deployment entitlement
external data/tool egress
sampling/design risk class
output handling and release restrictions
human-derived data requirements
```

Safety decisions are durable and versioned. The inference pipeline returns policy-safe diagnostics without exposing rule internals that would aid bypass. Generated biological artifacts inherit or elevate classification according to policy.

### A17.21 Observability and SLOs

Core metrics include:

```text
request/job rate and terminal outcomes
validation and feature latency
queue/admission delay
model load and readiness time
batch size, work units, padding efficiency
first-result and total latency
sampling throughput and candidate validity
GPU utilization, memory, fragmentation
kernel/compiler cache state
artifact publication latency
cancellation and retry effectiveness
```

SLOs are profile-specific and measured at the public contract boundary. Traces link gateway, feature worker, admission, inference worker, and artifact publication using request/job/attempt identities. Payloads are omitted by default.

### A17.22 Capacity and autoscaling

Capacity models account for:

- model residency memory;
- shape/work-unit distributions;
- sampling multiplicity;
- load/unload frequency;
- compilation cache warmness;
- latency and queue targets;
- accelerator fragmentation and topology;
- tenant reservations and priority.

Autoscaling uses queue/work estimates and readiness, not CPU alone. Scale-to-zero is allowed only where model-load latency fits the service contract. Admission rejects work that cannot meet hard memory or deadline constraints rather than causing repeated OOM loops.

### A17.23 Inference qualification levels

| Level | Required evidence |
|---|---|
| `inference-i0` | pure API, CPU/reference fixtures, request/output schemas, deterministic local result |
| `inference-i1` | one-GPU model load, sampling, confidence/ranking, artifact round trip, cancellation |
| `inference-i2` | dynamic batching equivalence, memory bounds, compilation/kernel qualification, retries |
| `inference-i3` | distributed/large-shape execution, worker lease failure, multi-tenant isolation, load testing |
| `inference-i4` | safety, SLO, autoscaling, recovery, provenance, and production operations evidence |
| `inference-i5` | sustained production quality, cost, incident drills, and model-version rollout evidence |

### A17.24 Capability-local qualification progression

**Milestone 0 — pure local pipeline:** immutable request, feature fixture, one model bundle, reference execution, confidence/ranking, and result manifest.

**Milestone 1 — durable asynchronous vertical slice:** gateway job, feature artifact, queue/lease, one-GPU worker, cancellation, atomic result publication, and SDK polling.

**Milestone 2 — production batching:** model-aware admission, dynamic batching, shape buckets, promoted compilation/kernels, memory controls, and load qualification.

**Milestone 3 — online and large scientific profiles:** warm residency/autoscaling, distributed sampling where needed, restricted-data pools, SLOs, and incident runbooks.

### A17.25 Definition of done

Inference is production-ready when:

1. every result identifies the exact request, features, model bundle, plan, provider, kernel, and code digests;
2. public request/job semantics are independent of GPU worker internals;
3. model loading verifies immutable state and readiness before serving;
4. dynamic batching preserves per-request semantics, RNG independence, isolation, and deadlines;
5. cancellation, retry, duplicate delivery, and stale attempts cannot create ambiguous results;
6. sampling, confidence, ranking, and postprocessing are versioned contracts;
7. artifact publication is atomic and large payloads remain outside queues/databases;
8. fallbacks never silently change model, precision, provider, or scientific budget;
9. safety, tenancy, and data classification apply end to end;
10. each deployment profile has passed its scientific, numerical, performance, and operational gates.

### A17.26 Final inference invariants

- pure inference semantics do not depend on serving transport;
- every production invocation resolves mutable aliases to immutable artifacts;
- one executable plan owns model placement, precision, kernels, and compilation;
- one durable job and one fenced attempt own publication;
- candidate randomness is request/sample keyed and auditable;
- batched execution never changes another request's semantics;
- results are manifests with provenance, not opaque worker files.
