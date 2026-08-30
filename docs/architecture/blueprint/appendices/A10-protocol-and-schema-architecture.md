## Appendix A10 — Protocol and schema architecture

### A10.1 Source of truth

Use Protobuf as the source of truth for:

- internal RPC;
- durable job requests and status;
- service events;
- audit event payloads;
- generated client models;
- training run requests, resource profiles, lifecycle status, cancellation, and durable progress envelopes;
- agent resources, workflow-run status, approval requests/receipts, tool-call envelopes, and policy-decision events;
- provider-neutral training events that must cross process or service boundaries.

Use JSON Schema for:

- artifact manifests;
- dataset, feature-contract, feature-manifest, feature-bundle, feature-coverage/readiness, checkpoint, and model manifests;
- human-authored configuration that must be validated outside a Protobuf runtime;
- policy documents where JSON/YAML interoperability matters;
- typed training recipes, phase graphs, logical state schemas, training dataset manifests, BatchReceipts, hardware-topology manifests, executable plans, provider manifests, compiled-region manifests, evaluation snapshots, step capsules, autotune records, study/trial manifests, rollout manifests, agent definitions, tool contracts, agent policies, workflow definitions, agent-run manifests, and development-kit assemblies.

Generate OpenAPI only for public HTTP edges. Do not make an OpenAPI document and Protobuf schema independently authoritative for the same API.

### A10.2 Versioning rules

- Stable packages use `v1`, `v2`, and so on.
- Experimental APIs use a clearly marked namespace and may not be consumed by stable SDKs.
- Never reuse a Protobuf field number.
- Reserve removed field names and numbers.
- Events are immutable after publication; new meaning requires a new field or version.
- Manifests include `schema_version`; language bindings may expose idiomatic property names without changing serialized JSON.
- CI compares protocol changes against the protected baseline.
- Breaking changes require an approved migration plan and coordinated SDK/service rollout.

### A10.3 Generated code policy

Generated files are never hand-edited. Protobuf outputs for Go, Python, Rust, and TypeScript are committed under `protocols/generated/` with source-schema digest and generator version because they cross native workspaces and are required for reviewable, hermetic integration. Presubmit regenerates them and fails on byte drift.

JSON Schema validators, database bindings, OpenAPI bundles, documentation, and SDK transports are hermetic declared build/release outputs. A released SDK package may contain generated transport source when its ecosystem requires source distribution, but the repository does not commit that build output unless an approved ecosystem-specific exception says so. The source `.proto`, schema, or curated API projection remains authoritative in every case.

### A10.4 Contract authority and protocol planes

Mindclade separates three protocol planes:

| Plane | Primary representation | Purpose |
|---|---|---|
| synchronous service API | Protobuf RPC, optionally transcoded at public HTTP edge | commands, queries, streaming status |
| asynchronous event plane | immutable Protobuf envelope and typed payload | state changes, integration, audit delivery |
| artifact/configuration plane | JSON Schema plus content-addressed manifest | durable portable documents and human-authored intent |

A concept may appear in more than one plane, but one representation is canonical for each use. Translation is implemented and tested; schemas are not independently authored copies.

### A10.5 Common resource model

Every durable API resource uses consistent fields where applicable:

```text
name                    canonical resource name
uid                     immutable internal identifier
revision / etag         optimistic concurrency token
display_name            mutable human label
create_time
update_time
delete_time             for soft-deletion lifecycle
labels                   bounded user metadata
annotations              controlled non-indexed metadata
state                    typed lifecycle state
owner/project/tenant     tenancy boundary
policy_classification
```

Canonical names follow a resource-oriented hierarchy such as:

```text
tenants/{tenant}/projects/{project}/datasets/{dataset}
tenants/{tenant}/projects/{project}/trainingRuns/{run}
artifacts/{artifact}
models/{model}/versions/{version}
```

Names are opaque identifiers to clients. Clients never parse internal database keys or storage paths from them.

### A10.6 Common scalar and value types

Use shared types for:

- `Timestamp` and `Duration` with UTC semantics;
- UUID/ULID-style identifiers where appropriate;
- content digests with algorithm and canonical encoding;
- byte sizes and work-unit quantities;
- artifact references;
- resource references and immutable revisions;
- pagination cursors;
- policy/data-classification labels;
- money/cost values if introduced;
- semantic versions and schema versions;
- field masks and update masks.

Floating-point values in durable manifests require explicit rules for non-finite values, canonical formatting, and precision. Coordinates and scientific values additionally declare units and frames in their domain schema.

### A10.7 Command, query, and long-running operation conventions

Commands that create durable work return a durable job/operation identity rather than holding a network request open for execution.

```text
CreateTrainingRun request
→ validation and idempotency check
→ durable run/job record
→ response with resource and initial state
→ watch/get/list for progress
→ immutable result references at terminal state
```

Queries are side-effect free. Commands require idempotency semantics. Streaming APIs are resumable through sequence/cursor positions and do not become the only durable record.

### A10.8 Idempotency and concurrency

Mutation requests support an idempotency key scoped to the authenticated principal, tenant/project, operation, and a bounded retention window. The server stores request digest and response/result identity.

Rules:

- reuse with the same canonical request returns the prior result;
- reuse with different request content fails with conflict;
- idempotency does not hide authorization or current preconditions;
- worker attempt identity is separate from client idempotency;
- retry after unknown network outcome is safe.

Updates and deletes use `etag`/revision preconditions. Blind overwrite is prohibited for resources with concurrent actors.

### A10.9 Error contract

Transport status and domain details are both typed. An error includes:

```text
stable code
human-safe message
retryability
request and trace identity
field violations
resource/precondition details
policy or quota details
conflict revision
optional retry delay
support-safe diagnostic reference
```

Messages never expose secrets, raw biological payloads, internal SQL, cloud credentials, or stack traces. SDKs map errors into a stable public hierarchy while preserving typed details.

### A10.10 Pagination, filtering, ordering, and consistency

List APIs define:

- default and maximum page sizes;
- opaque signed/versioned page tokens;
- stable default ordering and tie-breaker;
- supported filter grammar and indexed fields;
- snapshot/continuation consistency semantics;
- behavior when resources are inserted or deleted mid-pagination;
- authorization filtering without count leakage;
- maximum query cost.

Tokens encode no sensitive plaintext and expire under documented policy. APIs never expose database offset pagination as a stable contract for large mutable collections.

### A10.11 Partial updates and field presence

Use field masks for updates. Distinguish:

- omitted field: leave unchanged;
- explicitly empty/default: set to empty/default;
- clear operation: remove optional value;
- unknown field: preserve or reject according to schema/version contract.

Maps and repeated fields declare replace, merge, append, and delete semantics explicitly. Patch behavior is covered by compatibility fixtures.

### A10.12 Durable job and status model

Job protocols separate desired action, durable lifecycle, attempts, and progress.

```text
Job
  immutable request digest
  desired cancellation state
  durable lifecycle state
  admission/resource profile
  active attempt reference
  progress summary
  result/failure references

Attempt
  worker identity
  lease/fence token
  start/heartbeat/end
  observed workload identity
  checkpoints and emitted artifacts
  classified terminal outcome
```

Progress messages are monotonic or explicitly versioned. A stale attempt cannot regress state or publish terminal results.

### A10.13 Event envelope

Every event uses a common envelope:

```text
event_id
event_type and schema version
aggregate/resource name
aggregate revision or sequence
occurred_at and recorded_at
producer identity and source revision
tenant/project and policy classification
trace/request/job/run correlation
idempotency/deduplication key
payload type and bytes
```

Ordering is guaranteed only within a declared aggregate or partition. Consumers are idempotent and tolerate duplicates. Event publication follows transactional outbox or another atomic source-state-plus-event mechanism.

Events are facts, not commands disguised as events. Corrections are new events; published event payloads are immutable.

### A10.14 Audit protocol

Audit records capture:

```text
actor and authentication context
tenant/project/resource
action and authorization decision
request origin and delegated identity
before/after revision references where appropriate
policy reason
result and failure class
time and trace/request identity
```

Sensitive payloads are referenced by digest rather than embedded. Audit retention, access, export, and tamper resistance are stricter than ordinary application logs.

### A10.15 Artifact and manifest schema conventions

All artifact manifests share a base envelope:

```json
{
  "schema_version": "mindclade.artifact-manifest/v1",
  "kind": "DatasetManifest",
  "metadata": {
    "uid": "...",
    "created_at": "...",
    "producer": "...",
    "classification": "..."
  },
  "spec": {},
  "lineage": {},
  "integrity": {}
}
```

Rules include:

- canonical JSON serialization for digest/signature calculation;
- no ambiguous numbers or implicit units;
- explicit content/media type;
- immutable references resolved before execution;
- extension fields namespaced and bounded;
- no secret values;
- schema validation plus domain validation;
- parent/child lineage and supersession semantics.

### A10.16 JSON Schema compatibility

Compatibility classes are declared per schema:

- strict read/write compatibility;
- forward-readable additive evolution;
- migration-required evolution;
- immutable historical schema.

Adding an optional field is not automatically safe if old writers would erase it during round-trip. Readers and writers declare unknown-field behavior. Migrations are deterministic, versioned, and preserve the original manifest digest/reference.

### A10.17 Protobuf evolution details

In addition to field-number rules:

- use presence-aware fields where absence differs from default;
- avoid exposing implementation enums that will evolve rapidly;
- enum zero is `UNSPECIFIED`; consumers handle unknown numeric values;
- oneofs are used for true alternatives, not arbitrary grouping;
- maps are avoided where ordering or duplicate keys matter;
- bytes fields declare encoding/content semantics;
- large payloads use artifact references or streaming, not giant messages;
- package and file options are stable across generated languages;
- RPC removal requires a supported migration and baseline update.

### A10.18 Authentication, authorization, and tenancy context

Authentication credentials are transport metadata, not business-message fields. Trusted middleware derives a principal and authorization context that is passed internally in typed form.

Every tenant-scoped operation identifies its tenant/project through the canonical resource name and verified context. The server rejects conflicting tenant identifiers. Clients cannot select arbitrary internal ownership fields.

Delegation, service-to-service identity, impersonation, and break-glass access have explicit protocol details and audit requirements.

### A10.19 Streaming and large data

Streaming contracts define:

- chunk size and ordering;
- content digest and total size;
- resume offset/token;
- backpressure;
- checksum verification;
- cancellation and partial cleanup;
- encryption and signed-URL lifetime;
- maximum in-flight memory;
- final commit/visibility boundary.

For large artifacts, APIs exchange upload/download sessions and immutable artifact references. Queue messages and database rows do not carry model weights, structures, datasets, or long logs.

#### A10.19.1 Feature and transform execution commands

Remote scientific preprocessing follows the same large-payload law. `mindclade.feature.v1` and `mindclade.transform.v1` command messages are bounded control envelopes, not serialized graph/data containers. They carry:

```text
immutable FeaturePlan / TransformExecutionPlan ArtifactRef
AttemptId and LeaseEpoch
absolute deadline / cancellation correlation
delegated capability reference
optional bounded scheduling hints
```

Completion events carry the fenced attempt identity, terminal classification, and immutable receipt/output references. `TransformGraph`, `FeaturePlan`, `TransformReceipt`, `LineageMapArtifact`, feature arrays, and fitted state remain artifact-plane values. Consumers verify digest, schema, authorization, and expected plan identity before work; unknown plan/schema versions are quarantined. This keeps queue redelivery cheap and prevents protocol size from scaling with a biological dataset or feature graph.

### A10.20 Generated SDK and OpenAPI boundary

Generation pipeline produces low-level clients. Hand-written SDKs add authentication, retries, pagination, polling/streaming, upload/download, resource models, and stable errors.

OpenAPI is derived from the public HTTP edge. Differences from internal RPC semantics are explicitly documented and tested. Generated OpenAPI is not edited by hand.

### A10.21 Compatibility matrix and skew policy

Every protocol package defines supported combinations:

```text
client major/minor range
server version range
event producer/consumer schema range
manifest reader/writer range
minimum migration tooling
sunset date
```

Rolling deployment tests cover old client/new server, new client/old server where supported, old event/new consumer, and historical manifest/current reader.

### A10.22 Protocol security and abuse controls

Contracts declare limits for:

- message and field size;
- nesting and repeated count;
- regex/filter complexity;
- decompression ratio;
- upload size and rate;
- streaming duration and idle timeout;
- pagination depth;
- idempotency retention;
- request fan-out;
- schema extension count.

Validation occurs before expensive allocation or work admission.

### A10.23 Protocol conformance suite

Required tests include:

- descriptor and JSON Schema validation;
- lint and breaking-change comparison;
- deterministic serialization where claimed;
- unknown-field and enum behavior;
- all language round trips;
- error mapping;
- idempotency and conflict;
- pagination stability;
- deadline/cancellation;
- event duplicate/out-of-order handling;
- historical manifest migration;
- authorization/tenant isolation;
- malformed and resource-exhaustion cases.

### A10.24 Agent and workflow contracts

Agent contracts distinguish immutable intent from mutable execution:

```text
AgentDefinition + WorkflowDefinition + ToolContract set + PolicyRef set
→ admitted AgentRun with resolved identities, budgets, and approval policy
→ append-only decisions, observations, tool-call receipts, and approvals
→ domain jobs and immutable artifacts
→ terminal AgentRunManifest and evaluation evidence
```

Every tool call carries agent/run/step identity, tenant/project, exact tool version, policy-decision reference, idempotency key, input digest or safe parameters, deadline, budget reservation, and expected output schema. Large or sensitive values travel through authorized artifact references. Tool completion returns a typed receipt; a model-generated assertion is never treated as proof that a side effect occurred.

Workflow definitions are versioned graphs with typed state, preconditions, compensation or reconciliation behavior, maximum iterations/fan-out, and explicit human-approval nodes. Resume and replay operate from durable events and receipts, not reconstructed chat text.

### A10.25 Capability-local qualification progression

1. Establish common resource, error, artifact, event, audit, and job types.
2. Implement Buf lint/breaking baselines and JSON Schema registry/migrations.
3. Generate Go/Python/Rust/TypeScript clients and conformance fixtures.
4. Implement control-plane job, artifact, dataset, training, inference, and evaluation APIs.
5. Add public HTTP/OpenAPI and SDK wrappers only after internal contracts stabilize.

### A10.26 Definition of done

1. Every cross-process message has one canonical schema owner.
2. Durable resources use consistent identity, revision, time, policy, and tenancy semantics.
3. Mutations are idempotent and concurrency-safe.
4. Errors are typed, safe, and consistently mapped across SDKs.
5. Events are immutable, ordered only where declared, and published atomically with source state.
6. Large payloads move through artifact contracts with integrity and resume.
7. Historical clients/events/manifests pass the declared compatibility window.
8. Generated code and OpenAPI cannot drift from source schemas.
9. Security and resource limits are part of the contract, not only implementation.
