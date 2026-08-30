## Appendix A32 — What to defer

Defer until measurable need exists:

- splitting every control-plane module into a service;
- custom distributed scheduler or workflow engine;
- custom feature-store product;
- service mesh;
- multi-cloud abstraction;
- public Go and Rust SDKs;
- model marketplace;
- user-extensible kernel or training-provider plugin system;
- independent event dispatcher or standalone webhook service;
- on-premises packaging;
- multiple Python lock universes or many Go modules;
- checking all generated code into Git;
- a second source of truth for experiment/model metadata;
- implementing every optional training directory before a real consumer exists;
- adopting DeepSpeed as a second complete engine;
- production Monarch orchestration before a concrete multi-role workload requires independent scaling;
- NVMe model/optimizer-state offload before measured memory or cost evidence justifies it;
- arbitrary in-place TP/PP/CP/EP resizing;
- automatic mid-run topology, provider, precision, or schedule mutation;
- unconstrained adaptive systems tuning inside production runs;
- cross-vendor accelerator portability as an unqualified production guarantee;
- full replay/RL/simulation infrastructure before supervised and generative training recovery is production-grade;
- adaptive provider fallback during official qualification runs.

Prefer checkpoint-and-restart replanning:

```text
verified checkpoint
-> discover target topology
-> compile new executable plan
-> reshard logical state
-> validate reproducibility contract
-> resume with explicit lineage
```

The blueprint reserves clean seams for deferred capabilities without paying their implementation and operational cost prematurely.

### A32.1 Deferral decision model

Deferral is an explicit architecture tool: preserve a clean seam while refusing implementation, operational, and compatibility cost before evidence exists.

A capability remains deferred when:

```text
no concrete user/workload requirement
or existing system satisfies the need
or correctness/security foundations are incomplete
or operational ownership is unavailable
or benefit does not exceed lifecycle cost
```

A directory comment or interface reservation is not a promise to implement on a date.

### A32.2 Evidence required to activate deferred scope

Activation requires:

- named workload/user and measurable pain;
- alternatives and why existing capability is insufficient;
- expected scientific, reliability, performance, or business benefit;
- owner and operating model;
- contract and source-of-truth impact;
- security/data/licensing implications;
- implementation and migration plan;
- qualification and definition of done;
- removal/rollback path if the experiment fails.

The burden of proof lies with adding the capability.

### A32.3 Reserved seams versus speculative abstractions

A reserved seam is small and contract-driven—for example, an enum capability, adapter interface, artifact schema extension point, or documented package location. It does not include empty service deployments, generic plugin frameworks, unused database tables, fake provider implementations, or copied upstream control planes.

A seam is accepted only when it does not complicate current consumers or weaken invariants.

### A32.4 Deferred microservices

A control-plane module becomes a service only after measured scaling, trust, availability, sovereignty, ownership, or release pressure. Until then:

- preserve module API and table ownership;
- avoid cross-module direct writes;
- emit stable events where integration exists;
- measure load/latency/failure isolation;
- document possible extraction boundary.

Do not introduce network hops, duplicated auth, deployment, databases, or on-call merely to appear service-oriented.

### A32.5 Deferred scheduler/workflow engine

Kubernetes, Kueue, JobSet, queues, and the durable Mindclade job state cover initial orchestration. A custom scheduler/workflow engine requires evidence that required semantics cannot be expressed reliably through these systems.

Before activation, define quota/admission authority, retry/fencing, workflow state, recovery, UI/API, security, and migration. It cannot coexist as an ambiguous second job truth.

### A32.6 Deferred feature-store product

Initial feature artifacts are immutable, content-addressed, cataloged datasets. Appendix A39's derivation projection is a rebuildable cache/index over those artifacts and is explicitly **not** activation of a feature-store product. A feature-store service is justified only by concrete online/offline retrieval, freshness, sharing, or materialization needs that artifact storage/catalog plus the A39 projection cannot meet.

Until then, avoid mutable “latest feature” keys, opaque online caches, or data-plane services with no stable feature identity.

### A32.7 Deferred service mesh

Adopt a service mesh only for measured identity, policy, traffic, or observability requirements that cannot be met simply. Evaluate sidecar/ambient overhead, RDMA/GPU workloads, debugging, availability dependency, and operational ownership. It must not intercept rank-synchronous training traffic or become required for local correctness.

### A32.8 Deferred multi-cloud abstraction

Use explicit Google Cloud/Kubernetes/storage adapters for current deployment. Multi-cloud is activated only by contractual, resilience, sovereignty, or capacity evidence.

Do not design to the lowest common denominator or wrap every cloud API. Preserve portability through immutable artifacts, protocols, Kubernetes workload contracts, and clean interfaces—not a fictional universal cloud.

### A32.9 Deferred public Go/Rust SDKs

Create public SDKs only when external consumers require those languages and support/versioning capacity exists. Generated internal clients may exist for services. Public extraction requires independent repositories/lifecycle, documentation, examples, semantic versioning, and conformance.

Empty public packages create expectations and supply-chain surface without value.

### A32.10 Deferred plugin systems

A user-extensible model/kernel/training/provider plugin system is high risk because it affects code execution, state, compatibility, security, and support. Initial extension occurs by contributing reviewed source inside the monorepo.

Activation requires sandbox/trust model, API stability, dependency isolation, capability negotiation, state/artifact contracts, version resolution, signing, qualification, and support policy.

This deferral does not prohibit the typed internal agent-tool registry in Appendix A36. Agent tools are reviewed, allowlisted adapters shipped in a qualified release and execute through existing authorization and SDK/domain boundaries. Loading tenant-supplied code, packages, containers, arbitrary URLs, or dynamically discovered tool servers remains deferred plugin behavior.

### A32.11 Deferred DeepSpeed full engine

DeepSpeed capabilities may be adopted narrowly, but a `DeepSpeedEngine` or canonical DeepSpeed configuration/checkpoint remains deferred. Activation would require a proven workload gap not solved by native execution/adapters and a design that preserves one trainer/state/job authority.

No provider proof-of-concept may bypass Mindclade progress, checkpoint, or recipe contracts.

### A32.12 Deferred Monarch production orchestration

Monarch remains research/optional until a real post-training workflow needs independently scalable generator, evaluator, simulator, reward, and trainer roles. Activation requires:

```text
role graph and ownership
policy version/rollout lineage
transport and fault semantics
Kubernetes admission relationship
artifact and checkpoint consistency
security and observability
independent-role recovery qualification
```

It remains outside the rank-synchronous numerical schedule and business job truth.

### A32.13 Deferred NVMe state offload

Activate NVMe model/optimizer offload only when measured memory/cost requirements cannot be met through sharding, activation policy, CPU placement, or model/system changes. Evidence includes I/O bandwidth/tail, endurance, checkpoint interaction, recovery, node loss, security, and cost.

Local NVMe remains reconstructible unless a separately qualified replicated tier exists.

### A32.14 Deferred live elasticity and replanning

Initial elasticity is checkpoint-and-restart. Live rank/topology/provider/precision/schedule mutation requires explicit state, collective, optimizer, RNG, data-progress, checkpoint, and lineage semantics plus production qualification.

Only add after repeated workload evidence demonstrates materially better availability/cost than checkpoint restart and the operational complexity is supportable.

### A32.15 Deferred RL/replay ecosystem

Post-training starts only after supervised/generative trainer recovery, artifacts, evaluation, and job consistency are production-grade. Activation requires a concrete algorithm and role workload, rollout schema, policy versions, replay state, staleness, reward/simulator governance, and safety policy.

Do not build a generic replay platform before one end-to-end algorithm proves its contracts.

### A32.16 Deferred public/on-prem packaging

On-premises or customer-VPC packaging requires defined customer demand, support/SLA, upgrade/rollback, hardware matrix, data/security model, licensing, observability, air-gap story, artifact distribution, and incident access. Internal Kubernetes manifests are not an on-prem product.

### A32.17 Generated-code commitment boundary

The committed Protobuf clients in `protocols/generated/{go,python,rust,typescript}/` are foundational, not deferred. They are regenerated hermetically and fail CI on drift. Other generated outputs remain build/release products unless an ecosystem requires generated source distribution and an approved exception records the owner, drift check, review benefit, and size impact.

### A32.18 Deferred capability register

Maintain a lightweight register:

```text
capability
reason deferred
reserved seam
activation evidence
owner for reevaluation
review trigger, not arbitrary date
known prototypes/research links
```

Review when a trigger occurs—new customer requirement, workload scale, incident, regulation, or upstream capability—not simply every sprint.

### A32.19 Prohibited prework

While deferred, do not:

- create empty packages/services or public APIs;
- add dependencies/images/operators “for later”;
- create database schemas or CRDs;
- expose placeholder configuration fields;
- promise compatibility/support;
- build generalized frameworks around one imagined consumer;
- allow research prototypes into production dependency graphs;
- weaken current architecture to accommodate hypothetical future paths.

### A32.20 Activation protocol

```text
trigger and evidence
→ RFC/prototype in isolated scope
→ architecture/security/scientific review
→ explicit contract and owner
→ vertical implementation and qualification
→ migration/adoption by real consumer
→ production maturity decision
```

If the experiment fails, remove the seam additions and dependencies that are not independently valuable.

### A32.21 Definition of done

Deferral policy is working when:

1. optional complexity remains absent until a named workload and measurable requirement exist;
2. current architecture preserves small, tested seams without generic unused frameworks;
3. every deferred capability has clear activation evidence and authority impact;
4. prototypes remain isolated and cannot become shadow production paths;
5. activation requires ownership, security, migration, qualification, and operations—not enthusiasm alone;
6. no empty services, plugin systems, modules, schemas, CRDs, or provider engines claim maturity;
7. deferred items are reviewed by triggers rather than arbitrary roadmap pressure;
8. checkpoint-and-restart, modular monolith, immutable artifacts, and existing upstream systems remain defaults until disproven;
9. failed activations are reversible and cleaned up;
10. implementation focus remains on complete vertical slices and production evidence.
