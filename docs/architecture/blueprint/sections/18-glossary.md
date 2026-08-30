## 18. Glossary

| Term | Canonical meaning |
|---|---|
| Admission | Policy/quota/resource decision permitting a validated plan to become a workload; not business success. |
| Agent definition | Immutable declaration of model capability, workflow, tools, memory, budget, approval, evaluation, and policy constraints. |
| Agent run / step | Durable execution of a frozen agent definition; a step is one fenced workflow node execution. |
| Artifact | Immutable bytes and manifest identified by cryptographic digest. |
| Attempt | One leased execution epoch for a run, fenced by `LeaseEpoch`. |
| Batch receipt | Compact evidence of stable input identities/progress used for training/data replay without payload logging. |
| Biological truth | Canonical entity/feature semantics owned by `bio/`, distinct from source bytes and dataset workflow. |
| Capability | Versioned, constrained behavior offered behind a stable contract and qualification envelope. |
| CAS | Content-addressed storage: immutable objects whose identity is their digest. |
| Checkpoint | Committed logical training/model state plus progress, topology, integrity, and lineage manifest. |
| Component | Owned repository unit with metadata, dependencies, public surface, tests, and maturity. |
| Control plane | Go-owned durable APIs, policy, state machines, planning/admission coordination, outbox, and reconciliation. |
| Data plane / execution plane | Rust/Python/GPU work that reports observations and artifacts but does not own business state. |
| Dataset snapshot/version | Immutable selected inputs and policy; a released version adds qualification, approval, and publication state. |
| Desired state | Durable requested condition owned by control-plane DB or live GitOps repository according to scope. |
| Development kit | Governed authoring/package façade (MCDK–MADK) over canonical domain contracts; not a system of record. |
| Evidence | Immutable, attributable result used to prove a qualification, policy, release, or operational claim. |
| Feature contract | Versioned biological/scientific definition of one reusable feature's meaning, logical dimensions, validation, determinism/cacheability, and leakage sensitivity; owned by `bio/`, not a model tensor layout. |
| Feature key digest | Canonical digest of the complete declared derivation request for one feature value: feature contract, immutable inputs/dependencies, derivation semantics/implementation class, parameters, snapshots/cutoffs, and declared seeded randomness. |
| Feature bundle | Immutable manifest that maps named model-facing roles to verified feature artifact/manifest references without duplicating their payloads. |
| Model feature view | Model-owned deterministic mapping from reusable semantic features to architecture-specific representation/tensorization; distinct from shared biological feature meaning. |
| Executable plan | Frozen mapping from semantic work to topology, resources, providers, schedules, and qualified implementations. |
| Fencing | Rejecting stale executors through monotonically increasing lease epochs and expected versions. |
| GitOps | Reconciliation of live environment desired state from a protected repository referencing immutable digests. |
| Idempotency key | Client/producer key bound to scope and canonical request hash that makes repeated commands return one result. |
| Job | Durable desired unit of work owned by the control plane. |
| Lease epoch | Monotonic number proving an attempt/step is the current authorized executor. |
| Logical state | Provider-independent named model/training state that can be checkpointed and migrated. |
| MCDK/MDDK/MMDK/MTDK/MEDK/MADK | Infrastructure, data, model, training, evaluation, and agent development kits. |
| Model bundle | Immutable model configuration, logical state/weights, code and feature/output compatibility manifest. |
| Observation | Worker/scheduler-reported fact awaiting control-plane validation/reconciliation. |
| Operation | Client-visible long-running command and terminal result. |
| Outbox / inbox | Transactional event-to-publish rows / consumer dedup records supporting at-least-once delivery. |
| Phase | Named semantic stage in a versioned training or agent workflow graph. |
| Plan digest | Digest of the canonical executable-plan representation; ranks/workers agree on it before execution. |
| Principal | Authenticated human/workload identity resolved to memberships and attributes; not a client-supplied user ID. |
| Promotion | Authorized update that makes a qualified immutable release eligible/deployed; no rebuild. |
| Qualification envelope | Exact contract, hardware, software, dtype/shape/policy, and tests for which a capability is approved. |
| Reconciliation | Idempotent comparison of desired state, observations, deadlines, and evidence to converge durable state. |
| Release | Immutable subject digest joined to policy, evidence, approval, signature, and revocation state. |
| Run | One logical execution with frozen inputs/configuration/plan; may contain multiple attempts. |
| Sandbox profile | Versioned compute/network/filesystem/identity limits under which a tool or untrusted transform executes. |
| Snapshot | Immutable view at a named source, data, evaluation, or state frontier. |
| Source of truth | The sole authority allowed to commit a category of fact. |
| Tool contract / receipt | Typed permissions/behavior for an agent tool / immutable evidence of one invocation and side effect. |
| Transform semantic key | Digest of a transform's semantic contract, immutable inputs/state/snapshots, semantic parameters, qualified implementation/equivalence identity, and semantic RNG where applicable; independent of ordinary backend/parallelism choices. |
| Transform execution plan | Immutable physical execution mapping for a transform graph: implementation/backend, partitioning, parallelism, fusion, spill, materialization, and resource envelope. |
| Transform state artifact | Immutable fitted state derived from an explicitly identified fit cohort/snapshot and consumed by later transform applications. |
| Lineage map artifact | Compact immutable mapping that permits deterministic reconstruction of sample/record transformation lineage without materializing one standalone edge per record. |
| Transform | Versioned mapping from declared input contracts to output contracts with explicit semantics, cardinality, ordering, determinism/state, parameters, and lineage; not a scheduler or hidden workflow. |
| Transform graph | Acyclic dataflow of transform invocations whose nodes preserve domain ownership and whose execution backend is replaceable. |
| Transform receipt | Immutable evidence of one transform invocation: exact inputs, operator/implementation, parameters/snapshots/RNG, output identities, counts, validation, and lineage. |
| Workload | Reconstructible scheduler object(s) materializing an attempt, such as Kubernetes JobSet/Job. |
