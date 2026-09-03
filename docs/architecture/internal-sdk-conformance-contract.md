# Internal SDK conformance contract

Status: implemented source. This document records the behaviour the four handwritten
façades under `sdks/{go,python,rust,typescript}` are held to, and the gates that
prove it. It is subordinate to `AGENTS.md`, `ARCHITECTURE.md`, the accepted ADRs, and the
repository-path manifest; where it disagrees with those, they win.

## Position in the authority chain

```text
protocols/proto                     canonical meaning
      |
      +--> protocols/generated      wire types, RPC machinery, streaming mechanics
      |         |
      |         +--> sdks   ergonomics and policy, no second wire model
      |         |         |
      |         |         +-------> console, CLI, examples, workers
      |         +-------> service implementations, event consumers
      +--> persistence mappers
      +--> optional OpenAPI projection
```

`sdks` is the physical path because Go reserves an `internal` path segment for
import visibility: placing the tree at the repository root makes it importable by every
Mindclade package while making it unimportable from outside the module. That property is
load-bearing and is verified — a package outside the module fails to compile with
`use of internal package ... not allowed`.

The façade owns endpoint and credential discovery, retry and timeout policy, idempotency,
pagination, operation waiting and watching, artifact helpers, error normalization,
observability, interceptors, and test doubles. It owns no wire type. Generated protobuf
messages are the models; where the façade adds a type, that type carries call mechanics —
a page cursor, a watcher, a typed error — rather than field data.

## What "Stainless quality" means here

Stainless is the quality bar, never a dependency. There is no `stainless.yml`, no
generator integration, and no entry in any dependency manifest. What was adopted is the
shape of a well-made SDK: a documented error hierarchy, auto-pagination that retains
page-level access, raw-response access, explicit escape hatches, a per-request options
object, and a README whose section order a reader can predict.

What was deliberately *not* copied, and why:

| Stainless | mindclade | Reason |
| --- | --- | --- |
| 2 retries, 0.5s→8s, jitter in (0.75, 1] — subtractive, only shortens | 4 attempts, 100ms→2s, **full** jitter over `[0, min(cap, base·2^n)]` | Full jitter spreads a thundering herd; the shorter ceiling suits an internal control plane |
| Go SDK has one error type discriminated by `errors.As` | Eleven typed errors wrapping a base | Appendix A19.10 requires the taxonomy; a caller should not switch on a status code |
| Idempotency key generated client-side (TypeScript only) | `CommandContext` carries command identity in every language | Server-side idempotency is authoritative; an SDK retry never substitutes for it |
| SSE `Stream<T>` client | No SSE client at all | gRPC server-streaming stays native; SSE is the gateway's public projection of exactly one RPC |

Fern contributed one idea worth naming: it addresses validation findings by structural
node path rather than line number, so a diagnostic survives reformatting. Its
`RetriesConfiguration` also carries only *whether* an endpoint may be retried, leaving
counts and backoff to the runtime — independent confirmation that `retry_safety` belongs
in the descriptor projection while the policy constants belong in the SDK.

## The contract

### Retry eligibility is a contract property

Whether replaying a call is semantically valid is a property of the RPC, not of the
language calling it. Three classes, identical everywhere:

- **safe** — read RPCs; retried.
- **idempotent** — mutations whose request embeds a validated `CommandContext`; retried.
- **never** — `RunService.ExpireAttemptLeases`, a control-plane reconciler primitive.
  Never retried under any override.

`tests/conformance/test_sdk_retry_safety_parity.py` binds all four tables to
`sdks/rpc-coverage.generated.json`, which the atomic contract transaction derives
from the candidate descriptor. It asserts that every declared RPC is classified in every
language, that no language classifies an unknown identity, that no two languages disagree,
that the never-retry tier contains exactly the projection's raw-only RPC, and that no read
RPC is classified as a mutation.

That gate exists because its absence was expensive. `method_policy.go` claimed "A
descriptor-conformance test keeps these identities tied to the generated service estate";
no such test existed, the tables were referenced nowhere outside their own modules, and
they had drifted to 122, 126, 131 and 57 of 132 RPCs respectively — so the same RPC was
retried in one language and not another. All four now classify all 132, and agree
exactly: 61 safe, 70 idempotent, 1 never.

Go's share of that drift is worth recording, because the name caused the bug. Its table
was `safeUnaryMethods`, and the five server-streaming reads — `DownloadArtifact` and the
four `Watch*` RPCs — were simply never added, because they are not unary. Nothing rejected
them; the identifier merely made their absence look intentional. It is now `safeMethods`,
which is the actual contract: eligibility follows the RPC, not the call shape.

### Retry mechanics

Four attempts, 100ms→2s, full jitter from a cryptographically seeded or injectable source
so tests script it rather than assert on a range. The `retry-after-ms` trailer replaces the
computed delay, clamped to the configured maximum backoff. The `x-mindclade-should-retry`
trailer overrides the decision in both directions but can only act on an RPC the policy
already considers eligible: it may suppress a retry unconditionally, and may permit one
only for a safe or idempotent RPC. Every attempt sends `x-mindclade-retry-count` (0-based)
and `x-mindclade-timeout-ms` (remaining budget).

A timeout is a **total budget** for one logical call — every attempt, every backoff wait,
and credential acquisition share it. It only ever narrows a deadline the caller's context
already imposes.

### Errors

A base error plus `AuthenticationError`, `AuthorizationError`, `ValidationError`,
`ConflictError`, `NotFoundError`, `RateLimitError`, `QuotaError`, `RetryableServiceError`,
`OperationFailedError`, `CancelledError`, `TransportError`. Each carries a stable code,
safe message, retryability, retry-after hint, request id, trace id, operation id, field and
precondition violations, quota state, fence state, conflict revision, and a diagnostic
reference.

Field and precondition violations are the **generated** `mindclade.common.v1` messages.
Redeclaring them as hand-written types is forbidden and machine-checked: protobuf owns
those models, and a parallel pair would give callers two incompatible shapes for one
contract type.

Errors are sanitized. Raw SQL, SQLSTATE, Pub/Sub internals, provider strings, and stack
traces never reach a caller. An unrecognised `RetryClass`, including the generated
`UNRECOGNIZED` sentinel, maps to never-retry and can never authorize a retry.

### Request identity

`x-request-id` in both directions. The `x-mindclade-request-id` alias is retired — neither
read nor emitted, and stripped from outgoing metadata rather than merely ignored. Request
id is available on **success**, not only on errors, through each language's raw-response
accessor, alongside status, trace id and an allowlisted safe-metadata subset. When a server
echoes no request id the SDK reports the id it sent, so a successful call is always
correlatable.

The safe-metadata allowlist is identical in all four languages, and a credential denylist
is applied on top of it, so `authorization`, lease tokens, cookies, and anything matching
`*token*`, `*secret*`, `*key*`, `*credential*`, `*password*` or `*auth*` cannot surface even
if the allowlist were later mistaken.

### Pagination

Cursor scheme `page_token` in, `next_page_token` out. Tokens are opaque: forwarded
byte-for-byte, never parsed, trimmed or normalized. Every list method returns a page object
that iterates items across pages **and** retains page-level access. Traversal runs under an
explicit budget — 100 pages and 10,000 items by default, hard-capped at 1,000 and
1,000,000. A server that repeats a cursor terminates the traversal rather than looping.

Each fetched page re-invokes the owning list method with the caller's original request and
options, so per-page scope and validation run again on every page. Retraversal is not a
validation bypass.

### Streaming and long-running operations

Server streaming stays native gRPC. One generic resumable watcher per language replaces the
per-domain copies; the former names remain as aliases so message and cursor types are
unchanged. A watcher reconnects **only inside the caller's remaining deadline** and always
resumes from the last acknowledged cursor. Per-domain sequence and identity checks survive
unification.

Operations expose one uniform verb set: `Get`, `Wait`, `Watch`, `Cancel`, `ResumeWatch`.
Options are applied once per logical call, so every poll of a `Wait` and every reconnect of
a `Watch` share one request identity.

### Configuration

The ordinary constructor **never reads the process environment**. An explicit
from-environment constructor is the only path that does, covering
`MINDCLADE_{ENVIRONMENT,ENDPOINT,TENANT_ID,PROJECT_ID,PRINCIPAL_ID,AUDIENCE,LOG}`. It fills
only fields still empty, so an explicit option wins on either side of it.

**No credential is read from the environment, on any path, in any language.** Credentials
come from workload identity only when explicitly requested, and are injected beneath the
interceptor chain at the transport — so a caller interceptor cannot observe or forge an
authorization header. That is a structural property of where gRPC applies per-RPC
credentials, not a convention.

### Observability

An observer seam receives method, attempt, elapsed, status, request id, trace id,
retry-after, and metadata **key names only**. Payloads, bearer tokens, lease tokens, and
metadata values are never emitted; the event type carries key names rather than headers, so
this holds by construction rather than by discipline. An observer that panics cannot change
an RPC outcome.

## Timestamp resolution: a cross-cutting invariant

PostgreSQL `timestamptz` resolves to microseconds. A Go `time.Time` does not, so a response
assembled in memory keeps digits the database drops. Where an accepted command returns one
field re-read from the database and another from memory, the command and its idempotent
replay differ — which breaks the contract that a replay is indistinguishable from the first
call.

Every service clock therefore truncates to microsecond at the clock, not per response
field, so one command carries one timestamp everywhere. This is invisible without a real
database: the in-memory repository has no truncation step, so the defect only appears under
`MINDCLADE_REQUIRE_POSTGRES_INTEGRATION=1`.

## Gates

| Property | Gate |
| --- | --- |
| Retry safety identical in four languages | `tests/conformance/test_sdk_retry_safety_parity.py` |
| No handwritten duplicate of a protobuf model | `test_authoritative_wire_models_are_not_handwritten_again` |
| Clients do not bypass the façade | `test_client_source_roots_do_not_bypass_the_internal_sdk` |
| Façade cannot reach a durable backend | `test_internal_sdk_cannot_access_durable_backend_capabilities` |
| Backends do not depend on the façade | `test_backend_implementations_do_not_depend_on_internal_sdk` |
| SQL row types stay private | `test_sql_row_structures_remain_private` |
| No direct Pub/Sub from a domain transaction | `test_pubsub_clients_are_confined_to_delivery_runtime_and_wiring` |
| Every generated package has a real consumer | `test_every_source_package_has_an_explicit_executable_consumer_profile` |
| README names every activated verb | `test_internal_sdk_documentation_matches_the_activated_surface` |
| API reference matches the descriptor | `//tools:sdk_api_reference_test` |
| Distributed failure modes | `TestPostgresReliabilityHarness`, 11 scenarios against real PostgreSQL |

The per-language API reference at `sdks/<language>/api.md` is rendered from the
coverage projection by `tools/docs/render_sdk_api_reference.py`, written by `just generate`
and drift-checked by `just docs`. It reads no SDK source, so a reference cannot name a
method the descriptor does not declare.

## Known gaps

- The coverage projection's per-file digests go stale whenever SDK sources change, and only
  `just generate-contracts` may rewrite them. In an environment without Buf Schema Registry
  access that command cannot run: `buf build` must resolve the pinned googleapis module and
  fails with "the server hosted at that remote is unavailable". A regeneration commit is
  therefore required before merge, on a runner that can reach the registry.

  While that is outstanding, `test_internal_sdk_rpc_coverage_is_descriptor_bound_and_explicit`
  fails. The failure is **only** the digests: every structural assertion in it — 15 services,
  132 RPCs, the 131/1/0 classification split, per-RPC owner, facade, route prefix, and the
  four-language evidence records — passes, and the sole non-digest diff is the whole-document
  byte comparison those digests feed. Nothing about the RPC estate has drifted.

  One trap to skip on the way: the toolchain gate reports `rustfmt version mismatch` first,
  which looks like the blocker but is not. `toolchain.lock.json` names `flake.lock:nixpkgs`
  as rustfmt's authority, and the Nix-provided binary prints exactly the pinned
  `rustfmt 1.9.0`; a rustup rustfmt earlier on `PATH` prints `1.9.0-stable (<hash> <date>)`
  and fails the exact-string comparison. Put the Nix toolchain first on `PATH` rather than
  relaxing the pin — the exact-string check is what makes the toolchain hermetic.
- `protobuf-job-events` is declared as a dependency by both workers but has zero paths in
  the manifest; the job-event protos are labelled `events-job-v1`, and no `events-*`
  component is declared. Whether the workers should point at an existing component or a new
  one should be declared is a component-boundary decision for Architecture.
