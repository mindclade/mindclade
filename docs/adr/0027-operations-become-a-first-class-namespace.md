# ADR-0027: Long-running operations become a first-class namespace

- Status: Accepted in blueprint specification
- Connected ratification: Pending independent review on protected infrastructure
- Specification date: 2026-09-02
- Effective date: 2026-09-02
- Compatibility window: None; the v1 descriptor set is candidate-only and unratified
- Supersedes: None
- Superseded by: None
- Owners: Architecture, Contract Governance
- Reviewers: Architecture, Security

## Context

The blueprint lists `operations` among the domains of the initial contract
estate and requires long-running operations to be first-class control-plane
resources. The repository instead declared `Operation` and `OperationState`
inside `mindclade.job.v1`, in `protocols/proto/mindclade/job/v1/operation.proto`.

Eleven internal service contracts — admin, agent, artifact, dataset,
evaluation, inference, job, model, policy, training, and workflow — import that
file. Every one of them returns an operation from its long-running verbs, so
each depends on the job domain purely to name a resource that is not a job.
The dependency is backwards: `Operation` is the shared control-plane concept
that jobs are one instance of, not a member of the job aggregate.

`mindclade.api.v1` separately declares `Operation`, `OperationResult`, and
`OperationEvent`. Those are the public HTTP/JSON and server-sent-event
projection, governed by ADR-0012 and the descriptor-owned `public_message` and
`public_http` contracts. They carry resource names, string enums, and
`PublicError` rather than the internal shapes, so they are a projection of the
canonical resource and not a duplicate of it.

## Decision

Move `Operation` and `OperationState` into their own namespace:

```text
protocols/proto/mindclade/job/v1/operation.proto
  → protocols/proto/mindclade/operation/v1/operation.proto

package mindclade.job.v1  →  package mindclade.operation.v1
go_package …/generated/go/job/v1;jobv1
  → …/generated/go/operation/v1;operationv1
```

The message and enum definitions are unchanged field-for-field. The eleven
importing service contracts update their import path and their type references;
no request or response shape changes.

`mindclade.api.v1`'s public operation view stays where it is. It belongs to the
public edge, its shape is fixed by the published OpenAPI projection and the SSE
contract, and moving it would change a public surface this decision does not
touch.

This is a breaking Protobuf change, and the blueprint permits exactly one:

> There are currently no external compatibility commitments, so one clean v1
> reset is allowed.

The v1 baseline is candidate-only — `protocols/compatibility/baselines/protobuf.lock.json`
is deliberately absent until Stage 5 — so `buf breaking` compares the candidate
against the archived predecessor rather than a ratified baseline. After Stage 5
ratification this move would require a new version instead.

## Consequences

Four generated bindings move package-for-package, and a new
`protocols/generated/go/operation/v1` Bazel package appears. The Python
reconciliation applies its `mindclade/` prefix after the path replacement, so
the replacement values stay prefix-free.

The `operation` domain joins `ALL_CONTRACT_BASELINE_DOMAINS`, which binds the
new paths to `//:all_contract_sources` and `//:all_contract_tests` exactly as
the other v1 domains are bound, and `mindclade.operation.v1` joins the contract
matrix with `Operation` as its round-trip subject.

Consumers that used `jobv1.Operation` now use `operationv1.Operation`. Files
that also use `Job`, `Attempt`, or `Run` keep their `jobv1` import alongside the
new one. The four SDK façades, the control-plane services, and the conformance
suites follow the same substitution; no behaviour changes.

Nothing in the event registry, the published OpenAPI document, or the SSE
contract changes: none of them referenced `mindclade.job.v1.Operation`.

## Qualification and rollback

Qualification is complete when `buf lint` and `buf build` pass, contract
generation is byte-identical across two consecutive runs, `just check-contract-drift`
exits zero, the Go, Python, Rust, and TypeScript suites pass, the Bazel contract
tests pass, and the repository path policy reports `PASS` at the expected count.

Rollback is the inverse rename with the same manifest and digest refresh. No
published artifact or external consumer observes either direction.

## Decision record metadata

- Affected invariants: Protobuf owns resource meaning; long-running operations are first-class control-plane resources; the public projection is derived, never authoritative
- Affected paths: `protocols/proto/mindclade/operation/v1/`; the eleven `protocols/proto/mindclade/internal/*/v1/*_service.proto`; `protocols/generated/*/operation/v1/`; `sdks/`; `services/control_plane/`; `tests/conformance/contract_matrix.yaml`; `tools/repo/path_policy.py`
- Affected contracts: `mindclade.operation.v1` replaces `mindclade.job.v1.Operation` and `mindclade.job.v1.OperationState`
- Security and safety impact: none; no field, enum value, authentication, or tenancy semantics change
- Migration: move the proto, repoint the eleven service imports, regenerate all four languages, substitute the binding in every consumer, reconcile the path manifest
- Rollback: rename back and repeat the manifest and digest refresh
- Required evidence: buf lint and build; two-pass generation determinism; contract drift; four-language build and test; Bazel contract tests; repository path policy
