# ADR-0006: Durable Work, Idempotency, and Fencing

- Status: Accepted in blueprint specification
- Connected ratification: Pending independent review on protected infrastructure
- Specification date: 2026-08-30
- Effective date: Pending connected ratification
- Compatibility window: Lifecycle/fencing vocabulary fixed before Wave 1 kernel persistence
- Supersedes: None
- Superseded by: None
- Owners: Control Plane, Architecture
- Reviewers: Platform Operations, Security, Worker Owners

## Decision record metadata

- Affected invariants: durable database authority, at-least-once dispatch, idempotent mutation,
  monotonic lease epochs, fenced commits, and observation-only queue/scheduler state.
- Affected paths: future control-plane lifecycle contracts, database migrations, queue adapters,
  workers, reconcilers, and operational runbooks.
- Affected contracts: Operation, Job, Run, Attempt, Workload, Phase, idempotency keys, outbox/inbox
  records, leases, cancellation, and result-commit receipts.
- Security and safety impact: prevents stale or duplicated workers from committing unauthorized
  results and preserves tenant/policy decisions across retries.
- Migration: establish the durable schema and transition table first, then require every adapter to
  carry stable IDs and fencing epochs before activation.
- Rollback: fence new attempts, stop dispatch, restore the prior compatible transition handler,
  and reconcile durable rows; never infer rollback truth from queue deletion.
- Required evidence: duplicate/reorder/crash tests, stale-lease rejection, transactional
  outbox/inbox tests, cancellation races, tenant isolation, and recovery reconciliation.

## Context

Queues, processes, nodes, and accelerators fail. Messages may be duplicated,
delayed, or reordered; workers may continue briefly after losing a lease. A
queue or Kubernetes object cannot safely serve as business truth, and ordinary
retry does not prevent a stale worker from committing a result.

## Decision

The durable lifecycle uses distinct identities:

- `Operation`: client-visible long-running request and result/cancellation
  handle;
- `Job`: durable admitted unit of work and policy/accounting boundary;
- `Run`: one logical execution of a job or phase graph;
- `Attempt`: one fenced lease-bound execution try;
- `Workload`: scheduler/provider materialization of an attempt; and
- `Phase`: an ordered logical part of a run when its owning domain requires it.

The transactional control-plane database is authoritative for lifecycle state,
idempotency, authorization decision references, audit records, inbox
deduplication, outbox intent, lease epochs, and committed result references.
Queue delivery and scheduler objects are observations to reconcile, not state
authorities.

A mutating request supplies a tenant-scoped idempotency key bound to canonical
request semantics. In one transaction the control plane validates policy,
creates or returns the durable resource, records audit evidence, and appends an
outbox record. Dispatch is at least once. Consumers use stable message/event IDs
and durable inbox deduplication; the system makes no exactly-once delivery
claim.

Every attempt receives a monotonically increasing `LeaseEpoch`. Commands and
completion receipts bind job, run, attempt, epoch, deadline, contract digest,
and input artifact references. A worker may write attempt-scoped staged
artifacts but cannot mutate business tables. The control plane accepts a
completion only when the attempt and epoch are current, the lease is valid, the
receipt and artifacts verify, and policy still permits commit. Late or stale
completion is recorded and rejected.

Cancellation is a durable requested state that propagates through outbox and
worker cooperation. Reconciliation converges durable intent, queue delivery,
workload observations, leases, staged artifacts, and terminal state after
crashes or partitions.

## Consequences

- Duplicate requests and messages are safe within their declared scope.
- Stale workers cannot overwrite a newer attempt's result.
- Queue replacement and scheduler recovery do not alter business semantics.
- Transaction/outbox backlog, lease age, redelivery, stale completion, and
  reconciliation lag become required operational signals.
- Result artifacts remain immutable; only verified references are committed.

## Rejected alternatives

- Exactly-once delivery claims were rejected because the end-to-end system
  crosses failure domains that cannot provide one atomic commit.
- Queue or Kubernetes status as business truth was rejected because retention,
  replay, and transactional policy/audit are insufficient.
- Worker database writes were rejected because they bypass authorization,
  fencing, audit, and invariant ownership.
- Process-local locks and timestamps alone were rejected because they cannot
  fence a partitioned stale actor.

## Qualification and rollback

Qualification injects transaction rollback, outbox crash, duplicate/reordered
delivery, lost acknowledgement, lease expiry, clock skew, stale completion,
cancellation races, worker crash, queue outage, and reconciliation restart. A
state-machine migration provides current/previous readers and a reversible
database plan. Rollback never decrements a lease epoch or reopens an immutable
terminal result without a new operation.
