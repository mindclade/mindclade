## Appendix A38 — Reliability, continuity, and first-production acceptance

### A38.1 Reliability model

Production readiness is evaluated across four independent classes:

```text
service criticality and availability
artifact/data durability
recovery objective and drill cadence
evidence retention and freshness
```

A component declares all applicable classes in `component.yaml`; an artifact declares them in its manifest. The higher-risk dependency determines the minimum composite requirement. Availability cannot compensate for corruption, security failure, or irreproducible scientific state.

### A38.2 Service criticality classes

Initial production targets are:

| Class | Examples | Availability or completion objective | Maximum RTO | Maximum RPO |
|---|---|---|---:|---:|
| `S0-truth` | control-plane database, artifact catalog, identity/policy, release trust | 99.9% monthly plus integrity invariants | 1 hour | 5 minutes |
| `S1-critical` | public API/gateway, artifact transfer, job admission, GitOps control | 99.9% monthly | 4 hours | 15 minutes for durable state |
| `S2-workload` | ingestion, feature, training, evaluation, inference, agent workers | completion/recovery SLO by workload class | 8 hours to restore service capacity | latest advertised durable recovery point |
| `S3-supporting` | console, docs, noncritical telemetry views | 99.5% monthly or documented business-hours target | 24 hours | 24 hours where state exists |
| `S4-development` | research/dev environments and experimental services | best effort with explicit data policy | 2 business days | 24 hours unless stricter data class applies |

These are launch baselines, not universal promises. Customer contracts or regulated workloads may require stronger values. A weaker value requires an explicit non-production scope or approved risk exception; a dashboard cannot silently redefine the class.

### A38.3 Artifact durability classes

| Class | Content | Required behavior |
|---|---|---|
| `D0-irreplaceable` | audit, release trust, legal/consent records, critical catalog metadata | immutable/append-only as applicable, independent backup, cross-region recovery, periodic integrity scan |
| `D1-released` | released datasets, models, evaluation reports, production manifests | digest-verified immutable storage, replication by policy, lineage and revocation retained |
| `D2-recovery` | durable checkpoints, in-progress curated datasets, agent-run evidence | at least the advertised generations, integrity verification, lease-aware retention |
| `D3-reconstructible` | caches, derived previews, compilation/autotune caches | safe loss, deterministic/reviewed reconstruction, bounded invalidation |
| `D4-ephemeral` | attempt scratch, local staging, transient buffers | no durability claim, automatic cleanup, no sole copy of required evidence |

Deduplication never collapses authorization, classification, retention, revocation, or lineage even when byte digests match.

### A38.4 Evidence retention and freshness

| Class | Examples | Default retention/freshness rule |
|---|---|---|
| `E0-governance` | audit, approvals, release provenance, security and biological-governance decisions | longer of seven years or applicable legal/contractual policy; integrity checked |
| `E1-scientific-release` | dataset/model cards, qualification reports, reference baselines | supported artifact lifetime plus three years |
| `E2-production-run` | run manifests, checkpoints retained by policy, agent receipts, operational reports | one year unless lineage/support policy requires longer |
| `E3-diagnostic` | profiles, verbose logs, crash artifacts | 30 days by default; shorter for sensitive payloads |
| `E4-ephemeral` | local debug output and transient telemetry buffers | hours to seven days; never required for correctness |

Deletion, privacy, consent withdrawal, legal hold, source-license change, and biological-risk policy override these defaults. Evidence freshness is separate from retention: security scans, performance results, recovery drills, and compatibility reports expire according to their risk and change triggers even while historical evidence remains stored.

### A38.5 Workload recovery classes

| Class | Guarantee |
|---|---|
| `W0-exact` | resume from a declared snapshot with exact logical state and data progress under the same supported plan semantics |
| `W1-reshardable` | resume from a durable generation under a qualified topology-changing load plan |
| `W2-restartable` | restart the job from immutable inputs; duplicate external effects remain fenced/idempotent |
| `W3-best-effort` | no recovery claim beyond preserved terminal diagnostics |

Training claims W0/W1 only at Appendix A14 durable recovery points. Ingestion, evaluation, inference, and agents usually claim W2 unless they publish finer-grained committed state. A worker cannot advertise recovery based solely on local scratch, queue redelivery, or provider session state.

### A38.6 SLO and error-budget policy

SLOs measure public contract behavior: successful authorized operations, latency, job admission, artifact integrity, terminal-state convergence, recovery, and freshness. Infrastructure metrics explain symptoms but do not replace user-visible indicators.

Error budgets may guide release pace for availability and latency. They cannot waive authorization, tenant isolation, artifact/checkpoint integrity, numerical/scientific qualification, biological-safety decisions, provenance, or required recovery evidence. These are invariants and fail closed.

### A38.7 Operational readiness contract

Every production component must have:

```text
owner and escalation path
component metadata and dependency graph
criticality/durability/recovery/evidence classes
SLIs, SLOs, dashboards, alerts, and error-budget policy
capacity model and overload behavior
configuration and secret inventory
deployment, rollback, migration, and revocation procedure
backup/restore or reconstruction procedure
failure-mode analysis and tested runbooks
security/data classification and threat model
support window and deprecation policy
```

Alerts require actionable impact, owner, severity, runbook, and bounded labels. Readiness/liveness probes reflect safe service behavior and cannot create restart storms during a tolerable dependency outage.

### A38.8 Required failure and recovery drills

Before first production release, demonstrate:

1. control-plane database PITR and reconciliation with artifact/outbox state;
2. object/artifact corruption detection and recovery from a verified replica/backup;
3. queue duplicate, delay, dead-letter, and replay without duplicate success;
4. stale worker/agent/training attempt rejected by fencing;
5. checkpoint restore after process, node, and control-plane interruption;
6. Kubernetes node-pool/zone loss and workload rescheduling;
7. signer, CI worker/cache, image, and GitOps compromise containment and rollback;
8. workload-identity or secret revocation;
9. telemetry backend outage without correctness loss;
10. policy change, artifact quarantine/revocation, and downstream admission impact;
11. agent provider/tool failure, approval expiry, budget exhaustion, and safe replay;
12. isolated recovery from primary `us-central1` into `us-east4` of Tier S0/S1 truth within declared RTO/RPO and approved residency policy;
13. loss/rebuild of the feature derivation projection plus injected duplicate/divergent feature materialization, proving no false cache hit and determinism violations fail closed.

Each drill records source/release identity, environment, injected fault, expected invariant, observations, result, evidence digest, owner, expiry, and remediation.

### A38.9 First-production vertical slice

This is the Wave 8 production integration gate, not the initial Wave 2 implementation slice. It builds on the independently qualified Wave 2S/Wave 2P evidence and starts from the exact SQP-001 PDB dataset/model profile; additional sources or modalities are not required for launch and may appear only after separate qualification.

The first production release is a small but complete programmable-biology workflow:

```text
authenticated project and policy context
→ legally usable SQP-001 PDB source snapshot and released dataset
→ canonical biological parse/normalization and deterministic feature artifact
→ reduced CladeFold/Pairformer + diffusion training task
→ durable checkpoint, restore, and immutable model bundle
→ fixed evaluation suite and signed report
→ asynchronous inference request and mmCIF/confidence/diagnostic artifacts
→ policy-gated biological analysis agent using SDK-backed tools
→ Python/TypeScript SDK and accessible console evidence view
→ signed release manifest and digest-only GitOps promotion on GCP
```

The slice proves authority, identity, recovery, policy, and evidence boundaries. Frontier-scale quality and throughput are not required for this gate; truthful limitations and reproducible evidence are.

### A38.10 Requirement-to-evidence acceptance matrix

| ID | Requirement | Minimum direct evidence |
|---|---|---|
| `PA-01` | clean checkout and pinned dependency/toolchain closure | isolated CPU build/test/package plus lock reconciliation |
| `PA-02` | architecture and ownership laws | dependency/visibility/component metadata checks with negative fixtures |
| `PA-03` | authentication, authorization, tenant and classification isolation | API/integration negative tests and scoped workload identity evidence |
| `PA-04` | source/data legality, integrity, lineage, deterministic feature identity/output, and cache safety | connector resume/integrity test, conformance corpus, `FeatureKeyDigest` golden/determinism/cache-isolation evidence, dataset/feature manifests and card |
| `PA-05` | model logical state and reference numerics | forward/backward/state/save-load fixtures and model bundle verification |
| `PA-06` | trainer update, progress, checkpoint, and recovery correctness | failure after committed update, exact receipt/progress restore, no duplicate/skip |
| `PA-07` | evaluation validity | immutable suite/snapshot/report with metric/statistical and leakage evidence |
| `PA-08` | durable inference | duplicate/cancel/retry/stale-attempt tests and verified result artifacts |
| `PA-09` | bounded agent workflow | receipts/replay, tool schema, policy/approval/budget, injection and failure tests |
| `PA-10` | control plane and database integrity | transaction/outbox/fence/migration/PITR integration evidence |
| `PA-11` | Kubernetes/GCP workload and recovery | Kueue/JobSet admission, observed topology, preemption and recovery drill |
| `PA-12` | supply chain and promotion | SBOM, provenance, signatures, admission verification, exact-digest rollback |
| `PA-13` | operability | SLO/runbook/capacity/alert review and required failure drills |
| `PA-14` | security and biological governance | threat model, restricted-data/egress/log controls, safety evaluation and incident drill |
| `PA-15` | SDK/console client journey | SDK conformance and accessible end-to-end submit/watch/cancel/result workflow |
| `PA-16` | cost and resource bounds | workload estimate, budget enforcement, utilization/cost report and leak/orphan checks |

Each row points to immutable evidence identifiers in a `ProductionAcceptanceManifest`; prose assertions or screenshots alone do not pass a criterion.

### A38.11 Production acceptance manifest

The release candidate publishes:

```json
{
  "schema_version": "mindclade.production-acceptance.v1",
  "release_ref": "artifact://release/example",
  "source_revision": "<protected-revision>",
  "environment_profile_ref": "artifact://profiles/gcp-production",
  "criteria": [
    {
      "id": "PA-01",
      "result": "PASS",
      "evidence_refs": ["artifact://evidence/example"],
      "expires_at": "<policy-derived-time>",
      "reviewers": ["<reviewer-ref>"]
    }
  ],
  "exceptions": [],
  "decision": "APPROVED"
}
```

Valid criterion states are `PASS`, `PARTIAL`, `FAIL`, and `INCONCLUSIVE`. Production approval requires `PASS` for every required criterion, no unresolved critical or high finding, no expired evidence, no blocked/quarantined dependency, and no exception to a non-negotiable constitutional invariant. `PARTIAL` or `INCONCLUSIVE` is not silently rounded up; a release policy may exclude a genuinely inapplicable criterion only with recorded rationale and owner approval.

### A38.12 Review and sign-off

Required reviewers are risk-based and independent of the evidence producer where practical:

- engineering owner for architecture and implementation;
- scientific/data owner for biological semantics and evaluation;
- training/runtime owner for numerical and recovery evidence;
- security/safety owner for threat, data, and responsible-use controls;
- platform/operations owner for GCP, SLO, capacity, and recovery;
- product/API owner for SDK and console behavior.

No single role can approve its own material exception across all axes. Approval records exact evidence and source/release identity. A later code, configuration, dependency, model, data, policy, or environment change invalidates the affected criteria through dependency mapping.

### A38.13 Go-live and rollback conditions

Go-live requires:

- approved production acceptance manifest;
- staged deployment of the exact release digest;
- database/config compatibility and rollback decision;
- capacity and quota confirmation;
- on-call and incident channels active;
- dashboards/alerts and synthetic checks verified;
- backup/restore and break-glass evidence current;
- explicit launch scope and known limitations.

Rollback or containment triggers include authorization/tenant breach, artifact/checkpoint corruption, unsafe biological behavior, unexplained numerical divergence, unreconciled job state, provenance/signature failure, migration incompatibility, sustained SLO exhaustion, or inability to recover inside the declared class.

### A38.14 Post-launch qualification

The first 30 days operate under heightened review:

- daily correctness/security/failed-job review initially, tapering by evidence;
- comparison of planned versus observed capacity, cost, and topology;
- inspection of agent/tool policy denials and near misses;
- checkpoint, artifact, queue, and database reconciliation checks;
- SLO/error-budget review;
- one production-like restore and rollback rehearsal if no real incident exercised them;
- closure of launch exceptions before expiry.

Production experience updates tests, runbooks, capacity models, anti-patterns, and the risk register. It does not weaken evidence requirements merely because the first launch succeeded.

### A38.15 Definition of done

The blueprint is fully operationalized for first production when:

1. all production components declare service, durability, recovery, and evidence classes;
2. SLOs measure contract behavior and preserve correctness/security invariants outside error-budget tradeoffs;
3. required failure and recovery drills meet their declared RTO/RPO and preserve joined state;
4. the complete biological vertical slice crosses every canonical boundary without a shadow source of truth;
5. every `PA-*` criterion is `PASS` with current, direct, traceable evidence;
6. the release is built once, signed, promoted by digest, and independently reversible;
7. agent actions are bounded, authorized, receipted, replayable, and scientifically/safety evaluated;
8. GCP infrastructure is concrete, private, least-privilege, recoverable, and provider-contained;
9. reviewers approve exact evidence with no unresolved critical/high finding or constitutional exception;
10. post-launch feedback closes through owned remediation, new evidence, and versioned architectural change.

### A38.16 Final production invariants

- production readiness is evidence, not document completeness;
- availability never substitutes for integrity, authorization, recovery, or scientific validity;
- only verified durable points create recovery claims;
- a release passes each material axis independently;
- every provider, agent, tool, kit, and optimization remains subordinate to canonical Mindclade contracts;
- the first production slice is small enough to understand and complete, but complete enough to prove the whole system.
