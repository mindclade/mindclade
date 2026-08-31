# ADR-0012: HTTP/JSON Operation Projection and Python SDK

> Partially superseded by ADR-0015: the curated checked-in OpenAPI document is
> the external HTTP/JSON and SDK authority, with exact parity to the public
> gRPC facade. Stainless is the primary SDK generator and oagen is the
> promotable shadow; the original one-way derivation and provider deferral no
> longer apply.

- Status: Proposed
- Connected ratification: Pending independent review on protected infrastructure
- Specification date: Proposed 2026-08-30; not accepted
- Effective date: Pending connected ratification and required owner approvals
- Compatibility window: Supported HTTP v1 and Python SDK 1.x remain additive within the major
- Supersedes: None
- Superseded by: ADR-0015 only for language/provider deferments; the curated operation and artifact-verification model remains in force
- Owners: Developer Experience, Control Plane, Architecture
- Reviewers: Security, Contract Governance, Inference Systems

## Decision record metadata

- Affected invariants: curated external projection, durable asynchronous operations, finite deadlines, idempotent mutation, revision-aware polling, immutable artifact verification, stable errors, and transport-independent SDK types.
- Affected paths: Wave 2P HTTP edge, OpenAPI output, Python SDK client/models/errors/artifact transfer, compatibility baselines, and platform journey qualification.
- Affected contracts: inference submission, Operation, InferenceResult, cancellation, ETag/revision, ArtifactRef download, public error envelope, synchronous and asynchronous Python clients.
- Security and safety impact: authentication remains transport metadata; tenant/project identity is verified; credentials and restricted request bodies are not logged; downloads verify digest before atomic replacement.
- Migration: evolve HTTP v1 and Python 1.x additively, preserve unknown fields where possible, serve current and immediately previous compatible projections, and use a new major for breaking changes.
- Rollback: disable the fixture inference route, keep terminal operations readable, retain the previous compatible SDK/server pair, and never invalidate immutable result artifacts.
- Required evidence: curated OpenAPI drift, version/skew fixtures, idempotency conflict, ETag polling, deadline/cancellation, stable error mapping, clean wheel installation, sync/async parity, artifact corruption, and a 16-input consumer journey.

## Context

Wave 2P needs one supported external surface without leaking internal Protobuf layout, database rows, queue state, or provider objects. The workflow is asynchronous and may outlive one HTTP connection, so the public contract must expose a durable Operation and verified result artifact rather than a synchronous inference response.

This record is a proposal. It does not create a supported API or SDK release until protected ratification and conformance evidence exist; `production_authority` remains `false`.

## Decision

The supported projection is HTTP/JSON profile `v1`. Canonical resource names are:

```text
parent:    tenants/{tenant}/projects/{project}
operation: tenants/{tenant}/projects/{project}/operations/{operation}
artifact:  tenants/{tenant}/projects/{project}/artifacts/{artifact}
```

The minimal Wave 2P routes are:

```text
POST /v1/{parent=tenants/*/projects/*}/inferenceOperations
GET  /v1/{name=tenants/*/projects/*/operations/*}
POST /v1/{name=tenants/*/projects/*/operations/*}:cancel
GET  /v1/{name=tenants/*/projects/*/artifacts/*}:download
```

Submission requires `Authorization`, `Idempotency-Key`, and an absolute RFC 3339 UTC `X-Mindclade-Deadline`; the server rejects an expired or absent deadline. A successful submission returns HTTP 202 and an Operation resource with canonical `name`, `state`, `revision`, `createTime`, `updateTime`, `done`, and exactly one terminal `result` or `error`. The request carries only the fixture profile and immutable input/model ArtifactRef values required by Wave 2P. A reused idempotency key with different canonical request bytes returns a conflict.

Operation reads return an `ETag` derived from the durable revision. The SDK sends `If-None-Match` while polling and treats HTTP 304 as unchanged state. Polling always has a finite client deadline and bounded jittered interval. Cancellation is an idempotent request for durable cancellation, requires the last observed `If-Match` ETag, returns the current Operation, and does not claim immediate worker termination. A stale ETag returns a conflict with the current safe revision detail.

The terminal result contains the result ArtifactRef plus the verified input, model, fixture-profile, AttemptId, and LeaseEpoch identities. Artifact download supports bounded streaming/range behavior where available, writes to an attempt-local temporary destination, verifies size and digest, and atomically replaces the caller destination only after verification. Callers never construct storage paths or receive cloud credentials as durable identity.

All non-success responses use one public error envelope with stable `code`, safe `message`, `requestId`, bounded typed `details`, and optional `retryAfter`. HTTP status is transport classification, not the stable domain code. The Python SDK maps errors to the documented MindcladeError hierarchy and preserves the cause without exposing raw transport or server internals.

The supported package exports synchronous `MindcladeClient` and asynchronous `AsyncMindcladeClient`, typed request/result/operation/artifact models, and equivalent operations:

```text
submit_inference(request, *, idempotency_key, deadline) -> OperationHandle[InferenceResult]
get_operation(name, *, etag=None) -> Operation
wait_operation(operation, *, deadline, polling_policy=None) -> InferenceResult
cancel_operation(operation, *, etag) -> Operation
download_artifact(ref, destination, *, deadline) -> verified destination
```

The package is strictly typed and ships `py.typed`; construction is explicit; credentials are lazy; import performs no network or credential lookup; public models are SDK-owned rather than generated transport structs; sync and async clients have semantic parity; and model/training/torch packages are not dependencies. Under ADR-0015, the curated checked-in OpenAPI document is the HTTP/JSON source, while exact operation and model mappings prove parity with the public gRPC façade.

Within HTTP v1 and Python SDK 1.x, changes are additive, existing field meaning is stable, unknown response fields are preserved where the runtime permits, and stable error codes are not repurposed. A breaking route, required request field, resource-name rule, error meaning, or public Python signature requires a new major and a tested migration window.

## Consequences

- Clients can survive process restarts and long work without keeping an HTTP request open.
- Internal messages and persistence remain free to evolve behind one curated projection.
- Idempotency, deadlines, ETags, and typed errors have one testable client/server meaning.
- Artifact integrity is checked at the supported SDK boundary.
- ADR-0015 supersedes the TypeScript SDK, streaming-contract, and broader-resource deferments; the console runtime remains deferred until its own activation evidence exists.

## Rejected alternatives

- Exposing generated Protobuf types directly was rejected because generated layout is not the supported external SDK contract.
- A synchronous inference endpoint was rejected because work and cancellation outlive one transport connection.
- Unbounded polling was rejected because it leaks resources and makes cancellation/deadline behavior ambiguous.
- Returning storage paths or mutable URLs as result identity was rejected because ArtifactRef is the durable authority.
- An OpenAPI surface without exact public-facade mappings was rejected because its semantics could drift across public transports.

## Qualification and rollback

Ratification requires one reviewed Operation resource, versioning fixtures, and the complete Python consumer journey. Qualification builds a wheel, installs it in a clean environment, proves no import-time I/O, exercises sync/async submission, polling, cancellation, errors, and verified download across all 16 deterministic fixtures, and tests current/previous compatibility. Rollback disables new submission while retaining readable operations and verified result downloads through the previous compatible projection.
