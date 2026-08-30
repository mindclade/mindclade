# ADR-0010: Modular Go Control Plane, Relational Durability, and Worker Isolation

- Status: Proposed
- Connected ratification: Pending independent review on protected infrastructure
- Specification date: Proposed 2026-08-30; not accepted
- Effective date: Pending connected ratification and required owner approvals
- Compatibility window: The Wave 1 lifecycle and fencing kernel remains authoritative
- Supersedes: None
- Superseded by: None
- Owners: Control Plane, Architecture
- Reviewers: Security, Data Platform, Worker Owners

## Decision record metadata

- Affected invariants: one durable business-state authority, tenant isolation, transactional accepted intent, at-least-once dispatch, inbox deduplication, monotonic fencing, and worker database isolation.
- Affected paths: Wave 2P control-plane composition, PostgreSQL migrations, authorization, idempotency, audit, outbox/inbox, reconciliation, inference worker, and local platform qualification.
- Affected contracts: inference submission, Operation, Job, Run, Attempt, ArtifactRef, CommandContext, EventEnvelope, LeaseEpoch, cancellation, deadline, and fenced completion.
- Security and safety impact: every tenant-scoped mutation is authorized and audited in one transaction; the application uses a non-owner RLS role; workers receive no business-database capability.
- Migration: extend the Wave 1 schema additively, install ownership and RLS before application access, migrate one module at a time, and retain current/previous readers during rollback windows.
- Rollback: disable the inference route and dispatcher, fence active attempts, revert expand-only application behavior, and reconcile durable rows without deleting accepted intent or decrementing epochs.
- Required evidence: threat model, real PostgreSQL RLS under a non-owner role, transaction rollback, idempotency conflict, outbox crash/replay, duplicate/reordered/poison delivery, stale completion, cancellation/deadline, worker restart, and database-credential denial.

## Context

Wave 2P must prove a complete local platform journey without creating premature service boundaries or allowing a worker to bypass the Wave 1 durability kernel. A queue, process, worker, or object-store path cannot become business truth. Splitting the first slice across services would add distributed transactions and operational boundaries before measured scaling or trust evidence exists.

This record is a proposal. It does not authorize Wave 2P implementation, deployment, connected mutation, or production use until protected ratification evidence binds the decision digest and required owners.

## Decision

The first control plane is one Go deployable with internal domain modules and explicit composition. Modules own their application commands, relational tables, migrations, repositories, authorization checks, and audit vocabulary. Cross-module calls use typed application interfaces; they do not reach through to another module's tables or copy database structs into external contracts. Service extraction is deferred to JIT-11 and requires a measured trust, failure, scaling, or release boundary.

PostgreSQL-compatible relational state is authoritative for tenants, projects, operations, jobs, runs, attempts, lifecycle versions, authorization decision references, idempotency bindings, audit records, inbox deduplication, outbox intent, leases, and committed artifact references. Every tenant-scoped table carries the canonical tenant and project identity. The ordinary application connects as a non-owner role with row-level security forced on protected tables. Request middleware sets verified tenant, project, principal, and policy context transaction-locally. Migration, break-glass, and maintenance roles are separate, narrowly scoped, and audited; the service never silently falls back to an owner role.

An accepted inference submission executes one database transaction that:

1. derives identity and tenant/project context from trusted authentication;
2. authorizes the canonical request and records the decision reference;
3. binds a tenant-scoped idempotency key to the canonical request digest;
4. creates or returns the Operation, Job, Run, and first Attempt;
5. appends immutable audit evidence; and
6. appends the dispatch intent to the SQL outbox.

A different request digest under the same idempotency key is a conflict. A rollback leaves none of the accepted-intent records visible. Dispatch leases outbox rows and delivers at least once. Consumers deduplicate stable event IDs in a durable inbox, quarantine poison or unknown versions, and preserve retry/dead-letter evidence. Queue acknowledgement is never substituted for a database transition.

The Python inference worker is a separate process and composition root. It receives only immutable input/model ArtifactRef values, bounded work identity, absolute deadline, cancellation correlation, AttemptId, and LeaseEpoch. It may read verified artifacts, write attempt-scoped staged artifacts, and emit a completion command. It has no database credential, imports no control-plane persistence package, and cannot update business tables. The control plane alone verifies the current lease, artifact integrity, policy, and inbox identity before atomically committing the terminal operation and follow-up outbox/audit records.

Cancellation is durable intent, not queue deletion. Reconciliation converges database intent, outbox/inbox delivery, attempt lease, artifact staging, and worker observations after crash or partition. Terminal results and audit records are immutable.

## Consequences

- Wave 2P can prove durability and isolation with one operational service boundary and one worker boundary.
- Relational constraints, forced RLS, repositories, and module APIs make ownership executable rather than conventional.
- At-least-once delivery and duplicate work are expected; idempotency and fencing make their commits safe.
- Later service extraction requires an explicit data/API migration instead of treating shared tables as a service contract.
- `production_authority` remains `false`; local proof is not deployment or production evidence.

## Rejected alternatives

- A service per domain was rejected because Wave 2P has no measured boundary that justifies distributed transactions and additional failure domains.
- Queue or worker state as business truth was rejected because it cannot atomically preserve authorization, idempotency, audit, and accepted intent.
- Worker database writes were rejected because they bypass authorization, tenancy, fencing, and audit ownership.
- Database-owner application credentials were rejected because ownership bypasses RLS and makes tenant isolation tests vacuous.
- Exactly-once delivery claims were rejected because the transaction, queue, worker, and artifact store do not share one atomic commit.

## Qualification and rollback

Ratification requires the Wave 1 kernel evidence, a threat model, and a transaction/outbox prototype reviewed by Control Plane, Architecture, and Security. Qualification launches API and worker as separate processes, proves the worker environment has no database credential, and exercises the failure matrix in the required evidence. Rollback disables new admission, fences attempts, drains or quarantines delivery, restores the prior compatible handler, and reconciles retained durable state.
