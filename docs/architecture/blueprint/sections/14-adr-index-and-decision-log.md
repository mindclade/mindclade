## 14. ADR index and decision log

The blueprint accepts all decisions recorded in this section, but Wave 0 creates only seven standalone ADRs: the decisions that are expensive to reverse after implementation begins. Version 3.4.2 binds their canonical filenames below. Repository validation proves file presence and metadata; independent review and protected-branch evidence determine acceptance and are never inferred from this index.

### 14.1 Wave 0 foundational ADRs

| ADR | Frozen decision | Rejected alternatives and consequence | Target file |
|---|---|---|---|
| ADR-0001 | Canonical repository identity, estate boundary, domain ownership, and distinct source/durable-state/artifact/live-state authorities | ambiguous remotes/modules; language-first or service-per-repo decomposition; a universal system of record | `docs/adr/0001-repository-identity-and-ownership.md` |
| ADR-0002 | Domain-first acyclic dependency direction, public/internal visibility, native dependency authorities, Bazel integration graph, torch-free `libs/python`, and activation-gated paths | dependency cycles, Bazel-only package resolution, broad shared packages, empty scaffolds | `docs/adr/0002-dependency-and-build-law.md` |
| ADR-0003 | Immutable content-addressed artifact identity, catalog/reference model, evidence linkage, and promote-by-digest semantics | mutable paths/tags, large payloads in database/events, rebuild per environment | `docs/adr/0003-artifact-identity-and-cas.md` |
| ADR-0004 | Protobuf for internal RPC/events, JSON Schema for durable/human documents, curated OpenAPI externally, and committed drift-checked Protobuf generation | database structs as APIs, independently authoritative OpenAPI, ad hoc generation | `docs/adr/0004-contract-and-codegen-authority.md` |
| ADR-0005 | Canonical biological entity/sample identity, source-faithful parsing versus normalization, schema evolution, and lineage-preserving migration | parser-specific identity, mutable biological meaning, file paths as durable identity | `docs/adr/0005-biological-identity-and-schema-evolution.md` |
| ADR-0006 | `Operation`/`Job`/`Run`/`Attempt` semantics, transactional idempotency/audit/outbox, at-least-once delivery, inbox deduplication, lease fencing, and reconciliation | queue/Kubernetes as business truth, exactly-once claims, worker database mutation | `docs/adr/0006-durable-work-and-fencing.md` |
| ADR-0007 | Mindclade-owned training logical state, committed update/data progress, snapshot epochs, prepare/write/verify/commit checkpointing, and recovery guarantees | provider-native state/checkpoint authority, best-effort rank saves, ambiguous progress replay | `docs/adr/0007-training-state-progress-and-checkpoint.md` |

These seven files MAY consolidate several related design consequences, but each MUST remain reviewable as one invariant cluster. Wave 0 does not create empty ADR shells for later systems.

Version 3.4.2 also declares `docs/adr/connected-ratification.v1.schema.json` as the active Wave 0 machine contract for connected ratification evidence. This manifest-first precursor does not create that file: source readiness remains `INCONCLUSIVE` until the schema, its build/test coverage, and independently reviewed evidence land together. The schema supports the seven foundational ADRs and does not create an eighth ADR.

### 14.2 Just-in-time decision register

The following decisions remain normative in this blueprint. Their standalone ADR is ratified immediately before the first merge or release that depends on it, using measured context from the preceding waves.

| Gate | Decision to ratify | Due before | Required evidence at ratification |
|---|---|---|---|
| JIT-01 | Go modular control-plane monolith, relational ownership, tenant/auth/audit enforcement | Wave 2P implementation | minimal contract kernel, threat model, transaction/outbox prototype |
| JIT-02 | `SQP-001` dataset, biological filters, reduced Pairformer, objective, and hardware qualification profile | Wave 2S implementation | scientific, data-rights, and ML-systems owner approval |
| JIT-03 | External API projection and Python SDK support contract | Wave 2P supported surface | one resource/LRO shape, versioning test, consumer journey |
| JIT-04 | Evaluation evidence and dataset/model promotion policy | Wave 3 release graduation | SQP metrics, baseline, uncertainty and rollback evidence |
| JIT-05 | GCP/GKE topology, Kueue/JobSet authority, `deploy/` versus foundation/GitOps boundary, and workload identity | Wave 5 infrastructure merge | environment capability, security review, capacity and failure tests |
| JIT-06 | Each optimized kernel or numerical provider activation | each Wave 6 activation | measured bottleneck, reference parity, recovery mapping, performance threshold, rollback |
| JIT-07 | Agent definition/tool/workflow state, delegated capabilities, sandbox, approval, budget, receipts, and replay | Wave 7 implementation | threat model, biological-safety policy, stable capability APIs, adversarial plan |
| JIT-08 | MCDK–MADK façade boundary and any separate distribution repository | first supported kit release | real kit consumer, canonical domain closure, conformance and compatibility plan |
| JIT-09 | Build signing, qualification policy, GitOps promotion, rollback, and revocation implementation | first promoted release in Wave 3; production profile in Wave 8 | builder trust, subject/evidence schema, signing and rollback drill |
| JIT-10 | Additional cloud or on-premises support profile | first non-GCP environment implementation | funded consumer, provider conformance environment, identity/storage/recovery evidence |
| JIT-11 | Service extraction from the modular monolith | first extraction | measured trust/failure/scaling/release boundary and state/API migration |

An implementer cannot use missing ADR ratification to invent a local alternative. The blueprint decision remains controlling; the just-in-time ADR records concrete context, alternatives, migration, and evidence when that decision becomes operationally relevant.

### 14.3 Decision-change protocol

An ADR states context, decision, alternatives, consequences, affected invariants/paths/contracts, security/safety impact, migration, compatibility window, rollback, evidence, owner, reviewers, effective date, and supersession. An exception has an expiry. The architecture index is generated from ADR metadata and fails CI on duplicate ID, missing owner, broken supersession, or expired exception.

### 14.4 Assumptions carried by this revision

- The canonical implementation will be a private monorepo with protected CI and artifact infrastructure.
- GCP/GKE is the first production environment, while on-premises is a required extension profile after the first verticals are stable.
- PostgreSQL-compatible transactional semantics and a strongly consistent CAS-finalization path are available.
- Python and TypeScript are the only public SDK commitments in the initial program.
- Biological governance policy and protected-data residency/replication choices within the fixed `us-central1` primary and `us-east4` recovery profile will be supplied by accountable owners before protected data or production launch.
