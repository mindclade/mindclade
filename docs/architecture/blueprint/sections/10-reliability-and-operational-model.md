## 10. Reliability and operational model

### 10.1 Reliability principles

The system assumes process crashes, duplicate/reordered delivery, temporary network partitions, scheduler restarts, preemption, and object-store delay. It does not assume corruption is normal: integrity failure, cross-tenant access, policy bypass, and inconsistent committed state are safety incidents that fail closed and page an owner.

All durable workflows must be replayable from relational state, outbox/inbox facts, immutable plans/artifacts, and scheduler observations. Reconciliation is level-based and idempotent. Caches, Kubernetes objects, local worker state, and derived indexes are reconstructible. A manual operator action uses an authenticated command that produces audit/outbox records; direct database edits are prohibited except a documented break-glass recovery that is immediately reconciled and reviewed.

### 10.2 Initial target SLOs

These are approved launch targets, not observed performance. Owners MUST refine latency thresholds from measured workloads without weakening durability or security.

| Service/operation | SLI and target | Error-budget action |
|---|---|---|
| Control-plane read/write API | 99.9% monthly good requests; p99 server latency under 1 s excluding declared long work | freeze risky releases at 50% budget; reliability review at 100% |
| Durable command acceptance | 99.9% of valid commands atomically persisted and operation returned within 2 s | page on sustained breach or any acknowledged-but-lost command |
| Outbox dispatch | 99% under 30 s; 99.9% under 5 min | page on oldest age over 5 min or growth without convergence |
| Reconciliation | 99% eligible resources converge within 2 min after an observation | page on stuck resource class or stale leases beyond policy |
| Online inference gateway | 99.9% availability per supported profile; latency SLO defined per model/profile | shed load before violating isolation or correctness |
| Artifact finalization | 99.9% valid finalize operations under 60 s excluding upload; zero accepted digest mismatch | any mismatch is a security/reliability incident |
| Audit pipeline | 99.99% accepted privileged mutations have durable audit in the same transaction; export lag under 5 min | fail privileged mutation if local audit cannot commit |
| Batch workload durability | zero loss of accepted job intent; recovery point equals last committed checkpoint/progress frontier | correctness incident on silent loss or double commit |

Scientific quality, numerical parity, and biological-safety gates are release invariants, not availability SLIs and cannot be traded through error budgets.

### 10.3 Retry, timeout, cancellation, and backpressure policy

| Layer | Owns retry | Rule |
|---|---|---|
| SDK | transport/transient request retry | only idempotent reads or writes with idempotency key; bounded exponential jitter; deadline aware |
| Control plane | workflow attempt/recovery | creates a new fenced attempt according to durable policy |
| Dispatcher/consumer | delivery retry | at least once, deduplicated; poison threshold to quarantine |
| Worker | local transient operation | only when repeated action is safe; capped by job deadline/budget |
| Artifact client | chunk transfer | checksum-verified resume; finalization idempotent by digest |
| Tool adapter | declared tool retry | contract declares side effects, key, compensation, and ambiguity behavior |

Backpressure is explicit at ingress, queue admission, worker concurrency, artifact staging, checkpoint writes, telemetry buffers, and sandbox pools. Services reject or delay before exhausting memory. Cancellation has a resource-specific safe-point and grace period; after grace, the scheduler terminates the attempt and reconciliation chooses the valid terminal/recovery state.

### 10.4 Continuity and disaster recovery

The control-plane database uses point-in-time recovery and regional high availability. Object storage uses versioning/retention and a second failure-domain copy for irreplaceable release/evidence classes. Queue state is reconstructible from outbox and durable resource state. Container/package registries are mirrored or reproducible from signed build evidence. Git and environment repositories have protected mirrors.

Initial targets are control-plane metadata `RPO <= 5 minutes`, `RTO <= 60 minutes`; published artifacts/checkpoints `RPO = 0` after successful finalize within the declared replicated storage profile and `RTO <= 4 hours`; online inference deployment `RTO <= 60 minutes`; batch execution resumes from last committed checkpoint within `RTO <= 4 hours` after platform restoration. Actual regions, residency partitions, and replication classes require the owner decisions in Section 17.

Quarterly drills restore the database to an isolated environment, verify catalog-to-object integrity, rebuild reconstructible projections, resume a representative distributed checkpoint, revoke a release, and replay an outbox backlog. Annual drills exercise regional failover and signing-key compromise. Drill evidence records elapsed time, data frontier, missing/corrupt objects, manual actions, and corrective owners.

### 10.5 Incident response and operational ownership

Each deployable has an on-call owner, service tier, SLO, dashboard, alert, runbook, rollback command, data-classification statement, and dependency map before supported maturity. Severity is based on safety/security, data integrity, tenant scope, scientific correctness, and availability. Incident command preserves logs, events, plans, manifests, and deployed digests; it does not copy restricted payload into tickets. Post-incident actions that reveal a design weakness become an ADR, policy/test, or structural constraint, not only documentation.

Appendix A38 defines the extended continuity and first-production acceptance contract.
