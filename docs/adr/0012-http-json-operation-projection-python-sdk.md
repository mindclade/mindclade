# ADR-0012: Candidate HTTP/JSON and Server-Sent Event Projection

> Partially superseded by ADR-0015: Protobuf plus Buf-generated native
> Protobuf/gRPC/Connect bindings are the internal transport authority.
> Mindclade-owned facades under `internal/sdk` add ergonomics without
> redefining wire models. The curated OpenAPI document remains an HTTP/JSON
> projection; Fern and Speakeasy may be evaluated only as optional internal
> REST generators and never become foundational dependencies. This proposed
> public SDK is not adopted by ADR-0015 and has no current release authority.
> This revision narrows the proposal to the descriptor-derived candidate HTTP
> and Server-Sent Event projection already permitted by ADR-0015.

- Status: Proposed
- Connected ratification: Pending independent review on protected infrastructure
- Specification date: Proposed 2026-08-30; not accepted
- Effective date: Pending connected ratification and required owner approvals
- Compatibility window: The projection remains an unratified candidate; additive v1 compatibility starts only after the protected ADR-0015 baseline is created
- Supersedes: None
- Superseded by: ADR-0015
- Owners: Developer Experience, Control Plane, Architecture
- Reviewers: Security, Contract Governance, Inference Systems

## Decision record metadata

- Affected invariants: descriptor-derived HTTP projection, explicit SSE operation kind, durable asynchronous operations, finite mutation deadlines, idempotent mutation, resumable watches, immutable artifact verification, and stable errors.
- Affected paths: the candidate HTTP edge, public-safe protobuf facade, raw/curated/published OpenAPI projections, compatibility candidates, and gateway qualification.
- Affected contracts: inference submission, Operation, OperationEvent, operation watch/cancellation, ETag/revision, ArtifactRef download, and the public error envelope.
- Security and safety impact: authentication remains transport metadata; tenant/project identity is verified; credentials and restricted request bodies are not logged; downloads verify digest before atomic replacement.
- Migration: evolve HTTP v1 and Python 1.x additively, preserve unknown fields where possible, serve current and immediately previous compatible projections, and use a new major for breaking changes.
- Rollback: disable the fixture inference route, keep terminal operations readable, retain the previous compatible SDK/server pair, and never invalidate immutable result artifacts.
- Required evidence: descriptor/OpenAPI drift, exact HTTP-binding parity, operation-kind projection, idempotency conflict, ETag reads, deadline/cancellation, resumable SSE cursor/heartbeat/terminal behavior, stable error mapping, artifact corruption, and four-language generated-stream conformance.

## Context

The candidate HTTP surface must not leak internal Protobuf layout, database rows, queue state, or provider objects. Work may outlive one HTTP connection, so the candidate contract exposes a durable Operation, resumable OperationEvent stream, and verified result artifact rather than a synchronous inference response.

This record is a proposal. It does not create a supported API or SDK release until protected ratification and conformance evidence exist; `production_authority` remains `false`.

## Decision

The candidate projection is HTTP/JSON profile `v1`. Canonical resource names are:

```text
parent:    tenants/{tenant}/projects/{project}
operation: tenants/{tenant}/projects/{project}/operations/{operation}
artifact:  tenants/{tenant}/projects/{project}/artifacts/{artifact}
```

The minimal Wave 2P routes are:

```text
POST /v1/{parent=tenants/*/projects/*}/inferenceOperations
GET  /v1/{name=tenants/*/projects/*/operations/*}
GET  /v1/{name=tenants/*/projects/*/operations/*}:watch
POST /v1/{name=tenants/*/projects/*/operations/*}:cancel
GET  /v1/{name=tenants/*/projects/*/artifacts/*}:download
```

Submission requires `Authorization`, `Idempotency-Key`, and an absolute RFC 3339 UTC `X-Mindclade-Deadline`; the server rejects an expired or absent deadline. A successful submission returns HTTP 202 and an Operation resource with canonical `name`, `state`, `revision`, `createTime`, `updateTime`, `done`, and exactly one terminal `result` or `error`. The request carries only the fixture profile and immutable input/model ArtifactRef values required by Wave 2P. A reused idempotency key with different canonical request bytes returns a conflict.

Operation reads return an `ETag` derived from the durable revision. The SDK sends `If-None-Match` while polling and treats HTTP 304 as unchanged state. Polling always has a finite client deadline and bounded jittered interval. Cancellation is an idempotent request for durable cancellation, requires the last observed `If-Match` ETag, returns the current Operation, and does not claim immediate worker termination. A stale ETag returns a conflict with the current safe revision detail.

Operation watch is an explicit SSE capability, not a unary JSON method. The
`PublicHttpContract` method option owns a nested `PublicSseContract` with this
candidate policy:

```text
retry_milliseconds = 3000
heartbeat_interval_seconds = 15
heartbeat_reuses_last_durable_event_id = true
replay_acknowledged_terminal_event = false
```

`Last-Event-ID` is an optional opaque, authenticated, resource-bound resume
cursor. Resume is exclusive of the acknowledged cursor. No heartbeat is
emitted before a durable application event establishes cursor truth; later
heartbeats repeat that cursor and never advance it. A connection emits at most
one terminal event and returns immediately afterward. Reconnecting with an
acknowledged terminal cursor emits no duplicate terminal event; reconnecting
from an earlier valid cursor may replay it once. A client must apply one finite
overall deadline and a bounded retry budget across all connections. Each
connection ends on terminal state, caller cancellation or disconnect,
transport failure, server shutdown, or exhaustion of that caller-owned
deadline, while per-connection buffers and goroutines remain bounded.

Generation derives `unary`, `server-stream`, or `sse` operation kind from the
RPC and stream projection. It emits `x-mindclade-operation-kind` for every
operation and `x-mindclade-sse` for the watch, including the response event
model, resume header, retry, heartbeat, durable-cursor, and terminal-replay
policy. Generation fails closed when streaming shape, HTTP method, request
body, resume header, media type, response type, or required SSE policy does not
match. The current candidate permits SSE only for
`MindcladeService.WatchOperation -> OperationEvent`.

The terminal result contains the result ArtifactRef plus the verified input, model, fixture-profile, AttemptId, and LeaseEpoch identities. Artifact download supports bounded streaming/range behavior where available, writes to an attempt-local temporary destination, verifies size and digest, and atomically replaces the caller destination only after verification. Callers never construct storage paths or receive cloud credentials as durable identity.

All non-success responses use one public error envelope with stable `code`, safe `message`, `requestId`, bounded typed `details`, and optional `retryAfter`. HTTP status is transport classification, not the stable domain code. Internal SDK facades map transport failures to their documented Mindclade error types and preserve safe causes without exposing raw transport or server internals.

ADR-0015 does not adopt the public Python package proposed by the predecessor
text of this record. Internal Go, Python, Rust, and TypeScript SDKs remain thin
Mindclade-owned facades over generated native transports. Any supported public
HTTP SDK requires a separate release decision. During this candidate program,
generated clients must preserve streaming methods as streaming and must never
silently expose SSE as an ordinary unary request/response method.

After protected v1 ratification, HTTP changes are additive, existing field
meaning remains stable, and stable error codes are not repurposed. A breaking
route, required request field, resource-name rule, cursor meaning, event
semantics, or error meaning requires a versioned migration and consumer
evidence.

## Consequences

- Clients can survive process restarts and resume operation observation without treating one HTTP connection as durable truth.
- Internal messages and persistence remain free to evolve behind one curated projection.
- Idempotency, deadlines, ETags, and typed errors have one testable client/server meaning.
- Artifact integrity is checked at the internal SDK/application boundary.
- ADR-0015 remains the authority for internal transports, SDK facades, candidate lifecycle, and eventual compatibility baseline.

## Rejected alternatives

- Exposing generated Protobuf types directly was rejected because generated layout is not the supported external SDK contract.
- A synchronous inference endpoint was rejected because work and cancellation outlive one transport connection.
- Unbounded polling was rejected because it leaks resources and makes cancellation/deadline behavior ambiguous.
- Returning storage paths or mutable URLs as result identity was rejected because ArtifactRef is the durable authority.
- An OpenAPI surface without exact public-facade mappings was rejected because its semantics could drift across public transports.

## Qualification and rollback

Ratification requires one reviewed Operation/OperationEvent contract, exact
descriptor-to-OpenAPI parity, generated streaming conformance, and gateway SSE
qualification covering initial watch, resume, cursor rejection, heartbeat,
terminal acknowledgement, malformed events, slow clients, cancellation, and
resource cleanup. It remains one input to the protected ADR-0015 ratification
receipt and does not independently authorize public release. Rollback restores
the prior complete candidate source/generator closure and retains readable
operations and verified result downloads; it never rolls back one generated
language or projection independently.
