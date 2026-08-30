## Appendix A25 — Observability

Use OpenTelemetry-compatible traces, metrics, and logs across Go, Rust, Python, and TypeScript.

### A25.1 Correlation context

Propagate:

- trace context;
- request ID;
- job ID;
- run ID;
- phase ID and `StepEpoch`;
- tenant/project identity;
- model manifest and logical state-schema digests;
- training dataset and BatchReceipt references where policy permits;
- checkpoint/evaluation-snapshot digest;
- executable-plan and provider-manifest digests;
- compiled-region and selected-kernel signatures;
- code revision;
- worker attempt.

Do not put unbounded IDs, artifact digests, sample identities, sequences, or customer identifiers into metric labels. Use traces, structured logs, durable event artifacts, or exemplars for high-cardinality correlation.

### A25.2 ML telemetry

Training and evaluation telemetry includes:

- phase, step epoch, optimizer step, microbatch, samples, tokens, residues, atoms, pair cells, and work units;
- loss numerators, denominators, normalization bases, and reduction scopes;
- optimizer, gradient, update, and parameter statistics;
- precision, quantization, and loss-scale state;
- data throughput, packing efficiency, duplicate/skip checks, and starvation;
- compute and communication timing;
- collective bytes/latency, exposed communication, pipeline bubble, and recomputation overhead;
- compile graph breaks, guard/cache state, compiled-region identity, and CUDA-graph status;
- memory, fragmentation, and estimated-versus-observed headroom;
- MoE routing/capacity/load balance;
- checkpoint snapshot, staging, backlog, commit, retention, and restore timing;
- evaluation snapshot age, lease state, and report latency;
- provider, schedule, transformation-pass, and compatibility decisions;
- Pairformer pair/atom throughput and triangle-kernel utilization;
- diffusion timestep/SNR buckets, sampling throughput, and confidence calibration;
- post-training policy version, rollout staleness, generator utilization, reward latency, and discarded-trajectory reasons;
- numerical anomalies, health-policy actions, and recovery decisions.

ML telemetry writes through an adapter. Training continues safely when a non-critical dashboard backend is unavailable while preserving local durable event output.

### A25.3 Step capsules and diagnostics

Step capsules, flight-recorder outputs, memory snapshots, and profiler traces are immutable diagnostic artifacts with explicit retention and data-classification policy. They contain references and summaries rather than biological payloads by default.

### A25.4 Logging policy

Never log:

- raw biological sequences by default;
- structure payloads;
- model weights;
- credentials or signed URLs;
- restricted dataset contents;
- full user prompts/inputs without explicit policy.

Log stable identifiers and digest references instead.

### A25.5 Observability authority and signal model

Observability explains system behavior but does not become a hidden control plane. The authoritative hierarchy is:

```text
durable domain/run/artifact state
→ structured events and diagnostic artifacts
→ traces, metrics, and logs
→ dashboards and alerts
```

Dashboards are derived views. Missing telemetry cannot silently change business state, trainer updates, checkpoint validity, or release evidence.

### A25.6 Common telemetry envelope

Every signal carries the subset of a canonical context permitted by cardinality and data policy:

```text
service/component and version
environment/cluster/region
trace/span/request
principal/tenant/project when permitted
resource/job/run/phase/attempt
source revision, image, and build
artifact/model/dataset/checkpoint/plan/provider identities
severity, event type, and timestamp
policy/data classification
```

Metrics use bounded categorical dimensions. Traces/logs/events may carry high-cardinality identifiers as structured fields. Biological payloads remain excluded by default.

### A25.7 Semantic conventions

Mindclade defines cross-language semantic conventions for:

- RPC/HTTP server and client operations;
- database, queue, object storage, and cache;
- artifact reserve/upload/verify/commit/read;
- job/attempt/lease transitions;
- data connector and transformation stages;
- model load and inference stages;
- training phase/step/checkpoint/evaluation;
- kernel/provider/compiler decisions;
- Kubernetes admission/workload/rank lifecycle.

Field names, units, status, and error classes are centralized and versioned. Language libraries map native instrumentation to the same conventions.

### A25.8 Trace model

A trace follows one logical request or bounded asynchronous handoff. Long-running work uses links across traces rather than one unbounded span:

```text
API request trace
  creates job and records correlation
queue delivery/attempt trace linked to job
  execution child spans
artifact publication trace
follow-up evaluation or SDK retrieval trace linked by resource identity
```

Spans identify operation, owner component, status, retry/attempt, and safe resource references. Instrumentation avoids per-token/residue/atom spans in hot loops; detailed numerical timelines use profiler/flight-recorder artifacts.

### A25.9 Metric design

Every metric defines:

```text
name and unit
type: counter/gauge/histogram
semantic owner
allowed bounded labels
aggregation scope
data sensitivity
expected cardinality and retention
SLO/alert use
```

Histograms use buckets appropriate to the workload or native exponential histograms where the backend supports them. Counters are monotonic. Gauges have a clear collection instant and ownership. Units are encoded consistently.

### A25.10 Cardinality budget

Forbidden metric labels include raw:

- request, job, run, sample, artifact, checkpoint, or digest identity;
- sequence, structure, prompt, user-entered name, path, URL, or error message;
- unconstrained model/dataset name;
- arbitrary shape strings;
- stack traces.

Use bounded family/version classes, shape buckets, error codes, or exemplars. A telemetry schema check estimates label cardinality and blocks unsafe instrumentation.

### A25.11 Structured logging

Logs are structured events with timestamp, severity, component, message template/event code, correlation, and typed fields. Requirements:

- no string-concatenated payload dumps;
- bounded message templates;
- exception chains and stack traces only in controlled operator logs;
- field-level redaction and classification;
- rate limiting/deduplication for repetitive failures;
- explicit audit versus operational log separation;
- UTC timestamps and monotonic duration measurement;
- local buffering under backend outage.

A stable event code supports alerts and runbooks without parsing prose.

### A25.12 Audit versus observability

Audit records answer who did what to which protected resource under what policy and outcome. They are append-oriented, access-controlled, and retained under governance. Operational logs answer how software behaved. The same action may produce both, but audit is not sampled, casually mutable, or discarded by ordinary log retention.

### A25.13 Durable domain events

Domain and training events that affect reconstruction, callbacks, or run evidence use versioned durable schemas. Telemetry exporters may derive metrics/traces from them. Export failure does not erase the underlying event.

Event streams support sequence, deduplication, attempt fencing, and replay. Consumers must not assume global ordering.

### A25.14 Service telemetry

Services expose golden signals plus domain signals:

```text
request rate, latency, error, saturation
authentication/authorization outcomes
DB pool/query and transaction health
outbox backlog and delivery
queue enqueue/lease/heartbeat/retry/dead-letter
artifact transfer/commit failures
job state transition lag and conflict
rate/quota/backpressure decisions
```

SLO metrics are measured at stable API boundaries and exclude only documented non-service conditions.

### A25.15 Worker telemetry

Workers report:

- queue/lease and startup delay;
- immutable input resolution and verification;
- attempt/run/workload/rank lifecycle;
- heartbeat and cancellation latency;
- work-unit throughput;
- local memory/disk/network/GPU utilization;
- staged/committed artifact counts and latency;
- retry/failure classification;
- cleanup and orphaned staging.

Per-sample identities and payloads stay in controlled diagnostic artifacts, not broad telemetry.

### A25.16 Data telemetry

Data pipelines track:

```text
source revision and connector class
objects/bytes/records discovered, fetched, verified, parsed
resume/retry/rate-limit behavior
malformed/quarantined/tombstoned counts
transformation throughput and resource use
schema/invariant/quality failures
dedup/leakage/split summaries
feature cache hit and publication latency
```

Metrics use source family and dataset stage, not unbounded object IDs. Detailed bad-record references are restricted artifacts.

### A25.17 Model and inference telemetry

Model/inference signals include:

- model bundle/plan family and load status;
- batch/work-unit and padding efficiency;
- sampling candidates, steps, validity, and stop reason;
- confidence/ranking stage timing;
- kernel/provider/compiled-region classes;
- GPU memory/fragmentation and utilization;
- request/job latency and cancellation;
- artifact/result publication;
- numerical or geometry invalidity counts.

Scientific result values remain in result/evaluation artifacts unless a bounded aggregate is explicitly approved.

### A25.18 Training telemetry hierarchy

Training emits three layers:

1. **durable semantic events** for lifecycle, phase, committed update, checkpoint, recovery, evaluation snapshot, callback action, and termination;
2. **bounded operational metrics** for throughput, timing, resources, backlog, anomalies, and aggregate loss/update statistics;
3. **diagnostic artifacts** such as step capsules, flight recorders, profiler traces, memory snapshots, and shadow comparisons.

Only layer 1 and registered state may affect reconstruction. Metrics exporters cannot drive hidden optimizer or phase behavior.

### A25.19 Kernel/compiler telemetry

Capture operation family, qualified implementation, shape bucket, dtype/layout class, compile/cache outcome, latency/workspace, and fallback event. Detailed generated code, tensor summaries, and graph captures are artifacts with access and retention controls.

### A25.20 OpenTelemetry collection architecture

Applications emit through language SDKs to local or regional collectors. Collectors handle batching, retry, redaction, sampling, enrichment with infrastructure metadata, routing by classification, and export to backends.

Collector failure modes are bounded:

- local queues have size/disk limits;
- telemetry cannot consume unbounded training memory/disk;
- backpressure drops or samples noncritical signals according to policy;
- audit/durable events use separate reliable paths;
- credentials are scoped per exporter;
- restricted workloads route only to approved backends.

### A25.21 Sampling policy

Sampling differs by signal:

```text
metrics: aggregated, not sampled at source except high-frequency gauges
traces: head/tail or rules-based sampling with error/latency retention
logs: severity/event-based with repetitive-event throttling
audit: no probabilistic sampling
durable run events: no semantic loss; compacted only under explicit schema
profiler/step capsules: scheduled or anomaly-triggered bounded sampling
```

Sampling decisions and rates are observable. Missing sampled detail is never represented as absence of an event.

### A25.22 SLO model

Each production component defines service-level indicators, objectives, and error-budget policy. Examples:

```text
API availability and latency
job acceptance/state-transition correctness
queue-to-start delay by resource class
artifact commit success and latency
training durable-recovery-point freshness
inference latency/terminal-result success
evaluation report staleness
CI release pipeline reliability
```

Correctness and security invariants are not traded through an ordinary error budget. Error budgets guide reliability investment and release pace for availability/performance objectives.

### A25.23 Alert design

Alerts are actionable, symptom-oriented, owned, and linked to a runbook. They include impact, scope, recent change, relevant bounded context, and safe diagnostic links. Avoid alerting on every internal retry or raw metric threshold.

Alert classes include:

- customer/scientific workflow impact;
- data loss/corruption risk;
- security or policy breach;
- durable checkpoint/recovery risk;
- queue/admission saturation;
- persistent numerical anomaly;
- artifact/outbox backlog;
- SLO burn rate;
- telemetry blind spot for critical signals.

### A25.24 Dashboards

Dashboards are organized by user question:

```text
Is the platform serving safely?
Where is job time spent?
Is data input healthy and reproducible?
Is training numerically/operationally healthy?
Are inference quality and latency stable?
Can the latest release be recovered and explained?
```

Each panel names source metric/report semantics. Dashboard links pivot to trace, durable resource, run manifest, or diagnostic artifact. No dashboard is the only location of release evidence.

### A25.25 Retention and cost

Retention is based on signal class, environment, component tier, incident/legal needs, and data classification. High-volume raw traces/logs expire sooner than aggregate metrics or durable audit/run evidence. Diagnostic artifacts use explicit leases and lifecycle tiers.

Telemetry cost is budgeted by component. Libraries expose volume/cardinality estimates. Cost reduction uses sampling, aggregation, and schema discipline—not deletion of critical safety/recovery evidence.

### A25.26 Privacy and redaction

Redaction occurs as close to source as possible and again in collectors. Policies cover:

- biological sequences and structures;
- user/customer inputs;
- human-derived data;
- artifact URLs and credentials;
- database/query contents;
- environment/command-line secret values;
- stack frames containing payloads;
- identifiers that may reveal customer/project names.

Hashing a sensitive payload does not automatically make it safe; dictionary or linkage risk is considered.

### A25.27 Diagnostic capture protocol

An operator or automated health policy may request a diagnostic capture with:

```text
scope and reason
authorization/policy decision
start/end or step range
signal/artifact types
size and overhead budget
payload inclusion/redaction mode
retention and access
```

Captures are attempt/run scoped, immutable, and audited. They cannot insert blocking network operations or unsafe synchronization into the numerical hot loop.

### A25.28 Telemetry outage behavior

Components declare behavior when collectors/backends fail:

- services retain bounded local logs and continue if safe;
- workers preserve critical durable events and terminal outcomes;
- training continues without noncritical dashboards while protecting disk/memory;
- security/audit write failure may fail closed for regulated actions;
- alerts identify the blind spot through independent health paths;
- recovery drains buffers with deduplication.

### A25.29 Observability qualification levels

| Level | Required evidence |
|---|---|
| `obs-o0` | semantic conventions, context propagation, structured logs, bounded metrics |
| `obs-o1` | cross-service traces, worker/domain telemetry, redaction and cardinality tests |
| `obs-o2` | SLOs, alerts/runbooks, collector failure/backpressure, durable event reconciliation |
| `obs-o3` | production load/cost, restricted-data routing, incident diagnostics and audit review |
| `obs-o4` | sustained signal quality, blind-spot/DR exercises, evidence retention and governance |

### A25.30 Capability-local qualification progression

**Milestone 0 — shared conventions/libraries:** context, logging, metrics, tracing, redaction, and build metadata across Go/Rust/Python/TypeScript.

**Milestone 1 — one end-to-end job trace:** API, outbox/queue, worker, artifact commit, SDK retrieval, with bounded metrics and durable correlation.

**Milestone 2 — ML diagnostics:** training events, inference/model telemetry, step capsules, profiler/flight recorder, kernel/compiler decisions.

**Milestone 3 — production operations:** SLOs, burn-rate alerts, restricted routing, outage/backpressure drills, retention/cost governance, and incident dashboards.

### A25.31 Definition of done

Observability is production-ready when:

1. all languages propagate one versioned correlation/semantic convention;
2. metric labels are bounded and automated checks prevent payload/high-cardinality leakage;
3. durable domain/run state remains authoritative over telemetry backends;
4. logs, traces, metrics, audit, and diagnostic artifacts have distinct reliability and retention contracts;
5. training and worker operations survive noncritical telemetry outages without losing reconstruction evidence;
6. SLOs measure stable external/domain boundaries and alerts are actionable with runbooks;
7. restricted data is redacted/routed/access-controlled end to end;
8. diagnostic captures are bounded, immutable, authorized, and do not perturb numerical ordering;
9. telemetry cost and cardinality are measured and governed;
10. incidents can pivot from a user/resource/job to exact run/artifact/plan evidence.

### A25.32 Final observability invariants

- telemetry observes; it does not secretly control correctness;
- durable events and manifests outlive dashboards;
- metrics remain bounded and payload-free;
- audit is unsampled and separately governed;
- diagnostic depth is obtained through explicit artifacts, not hot-loop logging;
- every production alert has an owner, impact model, and runbook.
