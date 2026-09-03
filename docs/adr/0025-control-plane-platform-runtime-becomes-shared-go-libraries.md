# ADR-0025: The control-plane platform runtime becomes shared Go libraries

- Status: Accepted in blueprint specification
- Connected ratification: Pending independent review on protected infrastructure
- Specification date: 2026-09-02
- Effective date: 2026-09-02
- Compatibility window: None required; the moved packages are repository-internal and unpublished
- Supersedes: None
- Superseded by: None
- Owners: Platform Control Plane, Developer Platform
- Reviewers: Architecture, Security

## Context

The authoritative blueprint names eight Go libraries that carry the runtime
every service needs to hold durable state and move events safely:

```text
libs/go/
├── persistence/  ├── outbox/   ├── inbox/       ├── pubsubx/
├── eventruntime/ ├── idempotency/ ├── fencing/  └── servicekit/
```

That runtime existed, but at `services/control_plane/internal/platform`. The
`internal` element made it service-private: Go permits importing it only from
within `services/control_plane`, so no other service, worker, or tool could
depend on transaction plumbing, the transactional outbox, the transactional
inbox, Pub/Sub delivery, the audit projection, idempotency keys, delivery
fencing, or the audit store without duplicating them.

The blueprint's authority tree already declared `libs/go/servicekit/` as a
target path, so the destination was anticipated; only the population is new.

## Decision

Move the nine packages under `internal/platform` into the eight blueprint
libraries. Where the blueprint names a library and the existing tree names it
differently, the blueprint name wins and the Go package is renamed with it:

| Source | Destination | Package |
| --- | --- | --- |
| `platform/database/` | `libs/go/persistence/` | `database` → `persistence` |
| `platform/outbox/` | `libs/go/outbox/` | unchanged |
| `platform/outbox/delivery_fencing.go` | `libs/go/fencing/` | `outbox` → `fencing` |
| `platform/inbox/` | `libs/go/inbox/` | unchanged |
| `platform/queue/` | `libs/go/pubsubx/` | `queue` → `pubsubx` |
| `platform/eventprojection/` | `libs/go/eventruntime/` | `eventprojection` → `eventruntime` |
| `platform/idempotency/` | `libs/go/idempotency/` | unchanged |
| `platform/audit/`, `platform/telemetry/` | `libs/go/servicekit/` | both → `servicekit` |
| `platform/storage/` | `libs/go/storage/` | unchanged; merges |

`platform/storage` merges into the existing `libs/go/storage`, which already
held the storage abstractions its files implement. The two share no symbol and
neither imported the other, so the merge introduces no cycle and renames
nothing.

`services/control_plane/internal/jobs/lease_fencing.go` is **not** moved. It is
domain logic outside the platform tree, and extracting it would pull the `jobs`
package's unexported lease-token helpers with it. `libs/go/fencing` therefore
starts from the delivery predicate alone.

Each library becomes its own Bazel package. The nine `go_library` and `go_test`
rules that lived in `services/control_plane/BUILD.bazel` are deleted and
reconstructed per library, and the moved libraries join `//libs:foundation_sources`
and `//libs:foundation_tests`.

## Consequences

`CanAcknowledge` moves to `libs/go/fencing` and takes the delivery epoch and
terminal marker directly instead of an `outbox.DeliveryRecord`. Taking the
caller's record type would have made the most primitive library in the set
depend on one of its own consumers; the function had no callers, so no
behaviour changes.

The move exposed one layering violation that the service-private path had
concealed: the event-projection test imported the control plane's private
`internal/admin` package to prove the Admin audit query can read a projected
fact. A library test cannot import a service's private package, and should not.
The test now asserts the Admin query's own predicate — tenant, project, action,
and occurrence window — directly against `administrative_audit_records`, which
preserves the claim that the projection writes rows the service can return
without inverting the dependency.

Affected-target selection follows the code. The nine library prefixes are added
to the protected control-plane wave-2 selector, so a change to the outbox,
inbox, or Pub/Sub runtime still selects the suite that exercises it.

The generated event registry moves with its package and is emitted into
`package pubsubx`. No contract, descriptor, or event schema changes; only the
Go import path and package name of the registry's host.

## Qualification and rollback

Qualification is complete when contract generation is byte-identical across two
consecutive runs, `just check-contract-drift` exits zero, `go build ./...` and
`go test` over `libs/go`, `services/control_plane`, `sdks/go`, and
`tools/mindcladectl` pass, the Bazel contract tests pass, and
`tools/repo/path_policy.py` reports `PASS` at the expected canonical count.

Rollback is the inverse rename with the same manifest, activation-bundle, and
digest refresh. Nothing outside the repository observes either direction.

## Decision record metadata

- Affected invariants: PostgreSQL and Pub/Sub stay behind service and event-runtime boundaries; SQL row types never escape persistence; the internal SDK never reaches durable state
- Affected paths: `libs/go/{persistence,outbox,inbox,pubsubx,eventruntime,idempotency,fencing,servicekit,storage}`; `services/control_plane/BUILD.bazel`; `libs/BUILD.bazel`; `protocols/events/registry.yaml`; `tools/ci/affected_targets.py`; `tools/repo/{path_policy.py,activation-bundles.yaml}`
- Affected contracts: none; the event registry's evidence paths and Bazel targets are re-pointed, not redefined
- Security and safety impact: none; tenant isolation, fencing, and inbox deduplication semantics are unchanged, and the move removes a test's access to a service-private package
- Migration: move the trees, rename packages and selectors, rebuild per-library Bazel packages, re-point registry evidence, reconcile the path manifest and activation bundle, regenerate
- Rollback: rename back and repeat the manifest, bundle, and digest refresh
- Required evidence: two-pass generation determinism; contract drift; Go build and test; Bazel contract tests; repository path policy; governance report
