## Appendix A19 — SDK and application architecture

### A19.1 SDK layers

Each SDK has:

1. generated protocol client;
2. transport/authentication layer;
3. typed public resource models;
4. ergonomic high-level client;
5. polling/streaming helpers;
6. artifact upload/download helpers;
7. error hierarchy;
8. conformance tests;
9. examples and API documentation.

SDKs expose agent and workflow resources through the same durable operation, event-stream, approval, cancellation, and artifact abstractions used by other long-running capabilities. They do not expose provider session objects as durable Mindclade state.

Generated protocol code is not the public SDK surface.

### A19.2 Application dependency rule

Applications consume the TypeScript SDK and design system. They do not:

- query service databases;
- import Protobuf-generated code throughout feature components;
- know Kubernetes/job implementation details;
- encode business authorization in the browser;
- duplicate model/dataset state machines.

### A19.3 Initial product surfaces

- `console`: model runs, datasets, training, evaluation, agents, approval queues, artifacts, deployments, usage, and developer workflows;
- `admin`: tenancy, policy, audit, quotas, support, and incident operations;
- `docs`: SDK documentation, API reference, tutorials, model/dataset cards, and platform concepts.

Keep `admin` separate only when its trust boundary and deployment policy are materially different; otherwise begin as a protected console area.

### A19.4 SDK authority and compatibility boundary

SDKs are stable client products over public protocols. They own client ergonomics, not server behavior. Their authority is:

```text
generated wire client
→ stable public resource and error model
→ transport/auth/retry behavior
→ high-level workflows
→ examples and conformance evidence
```

A generated message may appear internally, but public signatures use SDK-owned types or intentionally exported generated types with a documented compatibility promise. Server implementation details, storage locators, database fields, Kubernetes resources, and provider configuration never enter the public SDK.

### A19.5 Public resource models

SDK resources represent durable API concepts:

```text
Tenant / Project
Dataset / DatasetVersion / FeatureSet
Artifact / ArtifactRef
Model / ModelVersion / Deployment
Experiment / TrainingRun / EvaluationReport
InferenceJob / Result
Policy or quota summaries where public
```

Each resource model distinguishes immutable identity, server-managed output, mutable fields, state, revision/ETag, and embedded versus referenced subresources. Unknown fields are preserved where the language/runtime permits forward compatibility. Public models do not mirror database rows.

### A19.6 Client construction and configuration

A client is constructed with explicit:

- endpoint and API profile;
- credential provider;
- transport/TLS policy;
- timeout and retry policy;
- user-agent/application metadata;
- optional telemetry hooks;
- upload/download settings;
- environment selection through named configuration, not hidden globals.

Credentials are obtained lazily and refreshed through a provider interface. SDKs never log credentials, tokens, signed URLs, request bodies containing restricted data, or full environment dumps.

### A19.7 Authentication contract

Supported credential mechanisms may include interactive user OAuth, service-account/workload identity, API credentials where policy permits, and externally supplied bearer tokens. The SDK:

- separates authentication from authorization;
- supports token refresh and expiry;
- scopes credentials to endpoint/audience;
- rejects insecure transport unless explicitly in a local profile;
- exposes typed authentication failures;
- never persists secrets by default;
- integrates with platform-native credential stores rather than inventing a plaintext one.

Administrative clients use separate explicit scopes and surfaces. A general client does not silently elevate based on ambient credentials.

### A19.8 Transport behavior

The transport layer owns:

```text
serialization and protocol negotiation
timeouts and deadlines
connection pooling
TLS and proxy behavior
compression
retry classification
request IDs and trace context
stream resumption
response-size limits
```

Default deadlines are finite and operation-specific. Mutation retries require idempotency or a safe protocol guarantee. The SDK never retries a non-idempotent mutation merely because the transport disconnected.

### A19.9 Retry and backoff

Retry policy considers:

- operation idempotency;
- typed server retryability;
- HTTP/RPC status;
- server-provided retry delay;
- client deadline and retry budget;
- rate-limit/quota semantics;
- stream cursor/resume capability;
- upload part state.

Backoff is jittered and bounded. Retry count, cumulative delay, and final cause are observable. Users can override policy without rewriting transport code, but unsafe overrides require explicit naming.

### A19.10 Error hierarchy

SDK errors preserve stable domain details:

```text
MindcladeError
├── AuthenticationError
├── AuthorizationError
├── ValidationError
├── ConflictError
├── NotFoundError
├── RateLimitError
├── QuotaError
├── RetryableServiceError
├── OperationFailedError
├── CancelledError
└── TransportError
```

Errors include request/trace identity, stable code, field/resource/precondition details, retry advice, and safe diagnostic references. Generated transport exceptions do not leak as the primary public contract.

### A19.11 Pagination and iteration

List operations expose both page-level and iterator/async-iterator APIs. Iteration:

- preserves server ordering;
- handles opaque page tokens;
- respects cancellation and deadlines;
- does not buffer the full collection;
- exposes page metadata when needed;
- never guesses consistency across token expiry;
- supports explicit maximum items to avoid accidental unbounded scans.

Filters and ordering are typed where practical and otherwise validated strings with documented grammar.

### A19.12 Long-running operations and jobs

SDK helpers expose:

```text
create/submit
get current state
wait with deadline and polling policy
watch/stream from cursor
request cancellation
retrieve result manifest
raise typed terminal failure
```

A `wait()` helper does not turn an asynchronous server job into an implicit synchronous API; it remains cancellable and returns the durable resource. Polling uses ETags or revision-aware mechanisms where available. Terminal failure includes the server failure classification and artifact diagnostics.

### A19.13 Streaming and resumability

Status and event streams define:

- initial snapshot versus delta semantics;
- monotonically increasing sequence/cursor;
- reconnect and replay behavior;
- duplicate handling;
- backpressure and client buffer limits;
- terminal event behavior;
- authorization changes during a stream.

SDKs reconnect only within the caller's deadline and resume from the last acknowledged cursor. Streams are convenience views over durable resources; loss of the stream does not erase job state.

### A19.14 Artifact transfer

Artifact helpers support:

```text
upload from bytes/file/stream
multipart or resumable upload
digest and size computation
server reservation and scoped authorization
parallel bounded transfer
retry by completed part/range
post-upload verification and commit
download with digest verification
range and streaming reads
atomic local destination replacement
```

The SDK uses `ArtifactRef`; callers do not build cloud storage paths. Transfer APIs expose progress callbacks with bounded frequency and no payload logging. Failed uploads remain uncommitted and are safe to garbage-collect.

### A19.15 Python SDK design

The Python SDK provides synchronous and asynchronous clients, typed models, context-manager lifecycle, iterator/async-iterator pagination, and file-like artifact transfer. Requirements include:

- `py.typed` and strict static typing;
- no import-time network or credential lookup;
- minimal required dependencies;
- no dependency on model/training packages or torch;
- deterministic serialization of public request models;
- exceptions with preserved causes;
- installed-wheel and clean-environment tests;
- support for notebooks without notebook-specific semantics.

The package namespace is `mindclade`, with generated internals hidden under a non-public module.

### A19.16 TypeScript SDK design

The TypeScript SDK separates browser-safe and Node-specific capabilities. It provides:

- ESM-first packages and declared exports;
- strict types and generated protocol wrappers;
- `AbortSignal` for cancellation;
- fetch-compatible transport abstraction;
- browser upload/download where policy allows;
- Node streaming/file helpers in a separate entrypoint;
- no reliance on Node polyfills in browser bundles;
- API surface extraction and bundle-size budgets;
- stable error classes and discriminated unions.

Credentials suitable only for server contexts cannot be imported into browser bundles.

### A19.17 SDK versioning and compatibility

Public SDKs use semantic versioning. Compatibility rules distinguish:

```text
wire compatibility
source compatibility
binary/package compatibility
behavioral compatibility
documented experimental surfaces
```

Adding optional server fields or SDK methods is normally minor. Removing or changing public types, error semantics, defaults, or retry behavior may be major even when wire-compatible. Each release declares minimum/maximum supported API versions and deprecation dates.

### A19.18 Generated-code intake

Generation is hermetic and pinned. The workflow is:

```text
protocol baseline
→ generate internal transport models
→ compile/lint
→ wrap into public SDK layer
→ run API-surface and conformance tests
→ optionally commit/release generated source
```

Checked-in generated code includes a source schema digest and generator version. Drift fails CI. Hand edits are rejected.

### A19.19 SDK conformance suite

All SDK languages pass common scenarios:

- authentication success/refresh/failure;
- idempotent create and conflicting key reuse;
- optimistic concurrency conflict;
- pagination/filter/order;
- long-running wait/watch/cancel;
- stream reconnect and duplicate replay;
- upload interruption/resume/digest mismatch;
- typed terminal job failure;
- unknown-field/forward-compatibility behavior;
- rate-limit/retry/deadline behavior;
- artifact authorization denial;
- safe telemetry and redaction.

A protocol simulator or controlled test service drives language-neutral fixtures.

### A19.20 Application architecture

Applications are feature-oriented shells over the SDK and design system:

```text
route/page
→ feature controller/query layer
→ SDK client and typed resources
→ state/cache adapter
→ design-system components
```

Business state transitions are not reimplemented in UI reducers. Server resources remain authoritative. Optimistic UI is used only where conflict and rollback behavior are explicit.

### A19.21 Console information architecture

The console provides coherent resource journeys:

```text
Projects
Datasets and feature sets
Models and bundles
Training runs and checkpoints
Evaluations and reports
Inference jobs and results
Artifacts and lineage
Usage, quota, and capacity
Developer/API settings
```

Every detail view shows immutable identities/digests, state, ownership, lineage, policy classification, and allowed actions. Large scientific artifacts use specialized viewers backed by authorized artifact access, not database payloads.

### A19.22 Front-end data and cache policy

Use a query/cache layer with:

- resource-keyed normalized cache;
- revision/ETag awareness;
- finite stale-time based on resource volatility;
- stream/poll reconciliation;
- cancellation on route changes;
- explicit mutation invalidation;
- tenant/project scoping in every cache key;
- logout and principal-change cache clearing;
- no restricted payload persistence in browser storage by default.

The UI never assumes that a websocket event is authoritative without reconciling the durable resource revision.

### A19.23 Authorization and sensitive UI

The server enforces all authorization. The client may hide or disable unavailable actions for usability but cannot infer access from role names alone. Sensitive surfaces require:

- fresh authorization state;
- explicit project/tenant context;
- step-up authentication where policy requires;
- reason and confirmation for destructive/admin actions;
- safe rendering of classified artifacts;
- audit correlation for privileged actions;
- no secrets in client logs, analytics, source maps, or error reports.

### A19.24 Design system and accessibility

`@mindclade/design-system` owns tokens, typography, icons, layout primitives, data-display components, forms, status semantics, scientific viewers, and accessibility behavior. Requirements include:

- WCAG-aligned keyboard, focus, contrast, and semantic markup;
- reduced-motion support;
- color-independent status communication;
- dense-data and large-number formatting;
- consistent loading/empty/error/permission states;
- accessible charts with tables or textual summaries;
- localization-ready date, duration, byte, and scientific-unit formatting;
- visual-regression and component-contract tests.

Brand styling does not override readability or scientific clarity.

### A19.25 Scientific visualization boundary

Structure, sequence, confidence, lineage, and training visualizations consume typed derived data. A viewer declares:

```text
input schema and maximum supported size
client versus server rendering responsibilities
level-of-detail/downsampling policy
coordinate and unit semantics
selection and annotation identity
export behavior
accessibility fallback
security classification and caching
```

The browser does not load entire restricted datasets or checkpoints merely to render a preview. Server-side derived previews are immutable artifacts with lineage.

### A19.26 Admin surface

Admin capabilities include tenant lifecycle, memberships, policies, quotas, audit, support impersonation where allowed, artifact quarantine, job intervention, and incident tools. Admin actions are distinct API operations with stronger authorization, reason fields, audit, and often dual control. Support views minimize data exposure and never provide blanket storage access.

### A19.27 Documentation application

The docs app publishes:

- platform concepts and architecture;
- SDK/API reference generated from stable sources;
- tutorials and end-to-end examples;
- operational and error guidance;
- model and dataset cards;
- changelogs/deprecation notices;
- security and responsible-use guidance.

Code snippets are compiled or executed in CI where practical. Versioned documentation maps to released SDK/API versions. Internal architecture docs remain access-controlled when they contain sensitive operational detail.

### A19.28 Client telemetry and privacy

Client telemetry is opt-in or policy-controlled and payload-minimized. It may include bounded route/action, SDK version, operation latency, error code, and request correlation. It does not include sequences, structures, artifact URLs, tokens, free-form scientific input, or unrestricted resource names. Browser error reports sanitize URLs, local state, and source context.

### A19.29 Application resilience and UX states

Every feature handles:

```text
loading and incremental progress
empty state
validation failure
permission denial
conflict/revision mismatch
rate/quota limit
partial dependency outage
cancelled job
retryable and terminal job failure
stale stream/reconnect
degraded artifact preview
```

Users receive stable job/resource links and diagnostic references. Refreshing or switching devices does not lose durable work. Destructive actions expose consequences and recovery options.

### A19.30 SDK and application qualification levels

| Level | Required evidence |
|---|---|
| `client-c0` | generated drift, type/lint/unit tests, public API surface, local protocol fixtures |
| `client-c1` | auth, retry, pagination, jobs, streams, artifact transfer, error conformance |
| `client-c2` | browser/Node or sync/async matrix, accessibility, security and failure-state testing |
| `client-c3` | load/large-artifact UX, compatibility across API versions, telemetry/privacy evidence |
| `client-c4` | production release, deprecation, incident/support workflow and SLO evidence |

### A19.31 Capability-local qualification progression

**Milestone 0 — generated clients and public core:** Python and TypeScript auth, resources, errors, jobs, pagination, and artifact references.

**Milestone 1 — asynchronous vertical slice:** submit an inference or training job, watch/poll, cancel, download verified result, and render it in the console.

**Milestone 2 — product resource journeys:** datasets, models, runs, evaluations, artifacts/lineage, quota, and robust failure states.

**Milestone 3 — public quality:** semantic versioning, docs, accessibility, conformance, compatibility matrix, telemetry privacy, and support/admin controls.

### A19.32 Definition of done

The SDK and application architecture is production-ready when:

1. generated wire code is hidden behind a stable, versioned public client surface;
2. authentication, retries, deadlines, idempotency, pagination, streams, and errors behave consistently across languages;
3. artifact transfer is resumable, digest-verified, and storage-provider independent;
4. applications depend only on SDK/design-system contracts and never on service internals;
5. tenant/project identity scopes every client cache and resource action;
6. accessibility, sensitive-data handling, and failure states are tested rather than aspirational;
7. durable work survives browser/process loss and remains addressable by resource identity;
8. protocol changes automatically exercise SDK conformance and public API review;
9. admin actions are separately authorized, audited, and minimized;
10. released SDKs, docs, and applications map to exact API compatibility evidence.

### A19.33 Final client invariants

- generated code is transport infrastructure, not product API;
- clients never infer server state from implementation details;
- retries occur only under explicit safety semantics;
- durable jobs remain durable through SDK and UI convenience layers;
- applications enforce usability, while servers enforce authorization;
- restricted scientific payloads do not leak through caches, analytics, logs, or previews;
- every public client release has protocol and behavior conformance evidence.
