## Appendix A28 — Database and migration policy

- The control plane owns the operational relational schema.
- Migrations are forward-only by default and tested from supported historical states.
- Every migration has an owner, compatibility window, and rollback/repair procedure.
- Deployments follow expand/migrate/contract for incompatible schema changes.
- Workers do not query control-plane tables directly; they use APIs or queue contracts.
- Analytical/event exports use explicit pipelines rather than operational replicas becoming undocumented APIs.
- Artifact data remains outside relational rows.
- Audit records are append-oriented and protected against casual mutation.

### A28.1 Database authority and scope

The operational relational database is the durable source for control-plane resources, transitions, ownership, policy metadata, artifact catalog references, and audit indexes. It is not a blob store, event warehouse, feature store, checkpoint store, or model registry by itself.

```text
control-plane domain command
→ transaction over owned aggregate tables
→ outbox record
→ committed revision
→ asynchronous projections/integrations
```

Workers and domain libraries never use direct database connections outside the control-plane composition root.

### A28.2 Schema ownership

Each control-plane module owns a documented table set, migrations, repository interfaces, data classification, retention, and query budget. Shared platform tables are limited to infrastructure such as outbox, idempotency, and migration metadata.

Cross-module foreign keys are allowed only when they preserve a stable resource identity and do not grant write ownership. Cross-module mutations occur through application APIs or process managers, not shared ORM models.

### A28.3 Identifier and reference model

Rows use:

- immutable internal UID;
- canonical public resource name/ID;
- tenant/project ownership;
- revision/ETag;
- create/update/delete timestamps;
- state and transition metadata;
- immutable artifact/resource references;
- bounded labels/metadata.

Database primary keys are not exposed as storage locators or assumed to be globally meaningful. Artifact digests and resource UIDs have typed columns/constraints rather than unvalidated strings where practical.

### A28.4 Transaction boundaries

A command transaction normally:

```text
checks idempotency and expected revision
locks/loads one aggregate
applies domain transition
writes owned rows
writes audit/outbox records
commits
```

External calls, object transfers, queue publication, Kubernetes creation, and long computations do not occur inside the transaction. They are triggered after commit through outbox/process managers and reconciled idempotently.

### A28.5 Isolation and concurrency

Use explicit isolation and locking based on invariant. Optimistic concurrency with revisions is default for API resources. Pessimistic row/advisory locking may protect scarce allocators or serialization points.

Code handles serialization/deadlock retries within a bounded transaction retry policy. It never replays external side effects as part of a transaction retry. Invariants are protected by database constraints in addition to application checks where possible.

### A28.6 Idempotency storage

An idempotency record contains principal/scope, operation, key, canonical request digest, response/resource identity, status, and expiry. Creation and target mutation are atomic.

Rules:

- same key and same request returns the prior result;
- same key and different request conflicts;
- in-progress/unknown outcomes are resolvable;
- keys are tenant/action scoped;
- expiration does not invalidate durable resource identity;
- large request/response bodies are not stored unboundedly.

### A28.7 Outbox schema and delivery

Outbox rows contain immutable event ID/type/version, aggregate identity/revision, payload or artifact reference, classification, trace context, destination class, and delivery status. The dispatcher leases rows using safe concurrent selection and records attempts/receipts.

Retention preserves enough history for audit/replay policy but avoids indefinite operational-table growth. Dead-letter state is visible and repairable through controlled tooling.

### A28.8 Job and attempt persistence

Job tables separate:

```text
immutable request and resolved references
durable lifecycle/revision
desired cancellation
admission/resource state
active attempt/fence
bounded progress summary
terminal result/failure reference
```

Attempt tables record lease, worker/workload identity, heartbeat, checkpoint/result publications, and terminal outcome. Database constraints prevent two active authoritative fences when the job contract allows only one.

High-frequency metrics do not update these rows continuously; progress is sampled/bounded and detailed telemetry is external.

### A28.9 Artifact catalog persistence

The database records artifact generations, manifests/digests, aliases/revisions, lineage edges, leases, retention, policy, qualification/promotion, and transfer reservations. Bytes and large shard inventories may live in object manifests, with indexed summaries in SQL.

Commit uses a transaction that verifies the reservation/fence and records the immutable manifest. Alias update is a separate revisioned action.

### A28.10 Tenancy and row isolation

Every tenant-owned table includes tenant/project constraints and indexes. Repository queries require tenant context structurally. Optional database row-level security may provide defense in depth, but does not replace application authorization or module ownership.

Tests attempt cross-tenant reads/writes, ambiguous joins, missing tenant predicates, pagination/count leakage, and backup/export isolation. Administrative cross-tenant queries use separately authorized repositories and audit.

### A28.11 Sensitive data minimization

Store only operational metadata needed for control-plane behavior. Avoid raw sequences, structures, model weights, feature tensors, user payloads, tokens, signed URLs, and unrestricted logs in rows.

Sensitive metadata columns are classified, encrypted where policy requires, excluded from broad indexes/logging, and protected in support/admin views. Database statement logging and error reporting are configured to avoid value leakage.

### A28.12 Migration lifecycle

Each migration has:

```text
unique ordered identity
owner and affected module
forward SQL/code
preconditions and estimated lock/data cost
compatibility window
backfill/validation procedure
rollback or repair strategy
observability and completion criteria
```

Migrations are tested from every supported historical baseline. Production executes through reviewed automation and records result/evidence.

### A28.13 Expand, migrate, contract

For incompatible changes:

1. **expand:** add new nullable/default-safe structures and dual-compatible code;
2. **migrate:** backfill in bounded resumable batches, validate parity, and switch reads/writes;
3. **contract:** remove old paths only after all deployments and rollback windows expire.

Backfills have progress cursors, rate limits, retry/idempotency, tenant scope, and validation. They do not hold long table locks or assume one uninterrupted process.

### A28.14 Online schema change constraints

Before production, estimate:

- lock level/duration;
- table/index size;
- write amplification and replica lag;
- disk headroom;
- query-plan impact;
- application compatibility;
- backup/restore implications.

High-risk operations use online techniques, shadow tables, or staged replacement. A migration that is safe on an empty test database is not thereby production-safe.

### A28.15 Repository and query policy

Repositories expose intent-specific methods, not arbitrary query builders across the application. Queries are parameterized, bounded, indexed, cancellation-aware, and instrumented by normalized query identity.

List endpoints enforce page size, stable order, tenant filters, and maximum cost. N+1 access and unbounded table scans fail performance tests. Raw SQL is allowed where it improves correctness/performance, with review and tests.

### A28.16 Index and performance governance

Indexes map to documented access paths. Each significant query has expected cardinality, plan, latency budget, and data growth assumptions. CI or staging captures representative explain plans where useful.

Unused/redundant indexes, bloat, autovacuum/maintenance, statistics freshness, connection saturation, slow queries, lock waits, and replication lag are monitored. Performance changes are tested against realistic data distributions, not only row counts.

### A28.17 Connection and pool management

Services use bounded pools with separate connection, query, transaction, and idle timeouts. Pool size is coordinated with service replica counts and database capacity. Overload backpressures requests rather than exhausting connections.

Connections carry application identity and safe trace correlation. Credentials rotate without restart where practical. Workers never receive database credentials.

### A28.18 High availability

The production database declares topology, synchronous/asynchronous replication policy, failover behavior, RPO/RTO, read routing, maintenance, and region strategy. The application tolerates transient connection loss and retries only safe transactions.

Failover cannot create two writable primaries under the supported design. Job/attempt fencing and artifact generation remain valid across failover.

### A28.19 Backup and point-in-time recovery

Backups include base snapshots plus transaction logs/PITR as appropriate, encrypted under controlled keys. Policy defines frequency, retention, cross-region copy, immutability, access, and legal hold.

Restore drills verify:

```text
catalog/resource consistency
migration state
outbox/idempotency/job/attempt correctness
artifact references and storage availability
audit integrity
application startup and reconciliation
```

A database-only restore is insufficient when referenced artifacts are unavailable or incompatible.

### A28.20 Disaster recovery and reconciliation

After restore/failover:

- compare catalog manifests with object storage;
- reconcile pending outbox deliveries idempotently;
- fence attempts/workloads newer than the restored database point;
- recover or classify jobs with ambiguous external side effects;
- validate aliases, leases, retention, and GitOps/deployments;
- emit recovery audit and incident evidence.

Runbooks prioritize preventing stale workers from publishing against restored state.

### A28.21 Retention, deletion, and legal hold

Operational resources have explicit retention and soft-delete/tombstone/purge behavior. Tenant deletion coordinates database metadata, artifact policy, audit/legal obligations, and external projections.

Deletion jobs are idempotent and evidence-producing. Legal hold overrides normal retention without granting broad access. Audit records are retained according to separate policy and may keep non-payload resource references after content deletion.

### A28.22 Analytical exports

Analytics consume versioned CDC/event or scheduled exports with explicit schemas, classification, and latency. They do not query production replicas as an undocumented API or join around authorization boundaries.

Exports minimize sensitive data, use stable pseudonymous identifiers where appropriate, support deletion/retention propagation, and are not fed back into operational decisions without a governed contract.

### A28.23 Database observability

Monitor:

```text
availability/failover/replication lag
connections, pool wait, transaction/query latency
lock/deadlock/serialization retries
slow/failed query classes
outbox/idempotency backlog
migration/backfill progress
storage, bloat, index and maintenance health
backup freshness and restore verification
tenant-isolation/security events
```

Metric labels use normalized query/module names, not SQL text or tenant/resource IDs.

### A28.24 Database security

Controls include private connectivity, workload identity or rotated credentials, TLS, least-privilege roles, separate migration/runtime/admin privileges, encryption, audit, protected backups, statement/log redaction, and break-glass access.

Application roles cannot disable constraints, change schemas, or read unrelated module/tenant data beyond required views. Migration identities are used only by controlled deployment workflows.

### A28.25 Database qualification levels

| Level | Required evidence |
|---|---|
| `db-d0` | schema constraints, repository/unit tests, migration from empty baseline |
| `db-d1` | real DB integration, concurrency/idempotency/outbox, tenant isolation |
| `db-d2` | historical migrations/backfills, load/query plans, failover/retry behavior |
| `db-d3` | backup/PITR restore, artifact reconciliation, security and deletion/legal-hold evidence |
| `db-d4` | sustained production scale, DR and ambiguous-side-effect recovery drills |

### A28.26 Capability-local qualification progression

**Milestone 0 — schema foundation:** module ownership, resources/revisions, idempotency, outbox, jobs/attempts/fences, artifact catalog, migration tooling.

**Milestone 1 — operational correctness:** real database integration, concurrency, tenant isolation, bounded queries, backfills, and service repositories.

**Milestone 2 — availability:** HA/failover, pools/backpressure, backups/PITR, restore and object-store reconciliation.

**Milestone 3 — governance and scale:** deletion/legal hold, analytics exports, query/index lifecycle, security audits, and DR drills.

### A28.27 Definition of done

Database architecture is production-ready when:

1. every table and migration has one module owner and documented classification/retention;
2. command transactions protect aggregate invariants, idempotency, revision, audit, and outbox atomically;
3. external calls never occur inside retried transactions;
4. tenant context is structural in repositories and cross-tenant negative tests pass;
5. workers and domain packages cannot access control-plane tables directly;
6. artifacts remain references and large/scientific payloads stay outside SQL rows;
7. migrations use tested expand/migrate/contract paths with bounded resumable backfills;
8. queries, indexes, pools, and overload behavior are capacity-tested;
9. backups/PITR restore together with artifact reconciliation and stale-attempt fencing;
10. deletion, legal hold, audit, security, and analytical export policies are enforceable and evidenced.

### A28.28 Final database invariants

- one operational database may host many modules, but each table has one write owner;
- transactions end before external side effects begin;
- outbox bridges committed state to asynchronous delivery;
- optimistic revision and attempt fences prevent stale mutation;
- the database catalogs artifacts but never becomes blob storage;
- migrations preserve mixed-version operation through an explicit compatibility window;
- recovery includes external-effect reconciliation, not merely SQL restore.
