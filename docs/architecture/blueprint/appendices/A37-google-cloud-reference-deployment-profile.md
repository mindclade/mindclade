## Appendix A37 — Google Cloud reference deployment profile

### A37.1 Executive decision

Google Cloud is the first concrete production provider. The profile is opinionated enough to operate and qualify, while provider-neutral Mindclade contracts remain authoritative. Cloud-specific identifiers, SDKs, IAM bindings, resource schemas, and failure modes are confined to MCDK/provider adapters, `infrastructure-live`, `gitops`, and service composition roots.

The default profile uses:

```text
Google Cloud organization/folders/projects
→ Shared VPC and private regional GKE Standard clusters
→ Kueue + JobSet for admitted distributed workloads
→ Cloud Storage for immutable artifacts
→ Cloud SQL for PostgreSQL for initial operational truth
→ Pub/Sub for at-least-once message delivery
→ Artifact Registry for OCI and package artifacts
→ Secret Manager + Cloud KMS
→ Workload Identity Federation
→ OpenTelemetry with Google-managed or replaceable backends
```

All service choices remain subject to measured scale, supported-region, accelerator, compliance, and recovery requirements.

The owner-selected initial profile is fixed: development, staging, and production environments; `us-central1` primary; `us-east4` recovery; and Google Identity Platform for application-user authentication. These selections do not claim accelerator quota/capacity, protected apply/promotion, or recovery qualification.

### A37.2 Project and environment topology

Use separate projects and identities for:

| Boundary | Purpose |
|---|---|
| bootstrap/security | durable trust, state, KMS roots, break-glass, recovery |
| shared networking | Shared VPC, DNS, egress, connectivity, centralized policy |
| CI/build | trusted/untrusted builders, caches, release identities |
| artifact/data | registries, object storage, catalog dependencies by classification |
| development | non-production services and clusters |
| staging | production-like qualification and promotion rehearsal |
| production | customer/scientific production workloads and durable truth |
| restricted data/compute (deferred) | separately activated perimeter, identity, egress, logging, and residency policy when approved data requires it |

Projects are grouped under development, staging, and production environment and trust folders with inherited organization policy. Production does not share broad service accounts, secrets, node pools, write caches, or mutable artifact locations with development or untrusted CI. A restricted environment is not part of the initial active set and requires a separately approved activation.

### A37.3 Contract-to-service mapping

| Mindclade contract | Initial Google Cloud realization | Canonical authority preserved |
|---|---|---|
| immutable artifact bytes | Cloud Storage, versioning/retention/replication by class | artifact manifest and digest |
| operational relational state | regional Cloud SQL for PostgreSQL with HA/PITR | control-plane schema and audit |
| at-least-once queue | Pub/Sub subscriptions with dead-letter policy | database job/outbox state |
| OCI/package registry | Artifact Registry | release manifest and digest |
| Kubernetes workload | private regional GKE Standard | control-plane job and executable plan |
| quota/admission/grouping | Kueue and JobSet | Mindclade job/resource policy |
| workload identity | GKE Workload Identity Federation and federated CI identity | Mindclade principal/workload mapping |
| application-user authentication | Google Identity Platform OIDC | Mindclade tenant membership and action/resource authorization |
| secrets and encryption | Secret Manager and Cloud KMS | typed secret/key references and policy |
| edge protection | Google Cloud load balancing, managed TLS, Cloud Armor as applicable | API authorization and request contracts |
| telemetry | OpenTelemetry collectors, Managed Service for Prometheus/Cloud Logging or qualified alternative | durable domain events and evidence |
| environment promotion | Argo CD/ApplicationSet in `gitops` | signed release manifest and GitOps desired state |

Cloud services implement a contract; provider resource names and URLs are not durable public identities.

### A37.4 Network architecture

Production uses Shared VPC, private cluster nodes, private service access/connectivity, explicit ingress, and default-deny east-west and egress policy. Workloads access Google APIs through private paths where supported. Internet egress is denied by default for restricted and production compute and enabled only through named policies with DNS/IP/host validation, rate limits, logging, and data-loss controls.

Separate network paths exist for:

- product/API ingress;
- service-to-service control traffic;
- artifact and data transfer;
- distributed training collectives;
- administration and break-glass;
- observability export.

High-throughput collective traffic does not traverse a service mesh or generic proxy. Network policy, firewall rules, routes, MTU, DNS, and accelerator fabric configuration are rendered and qualified together.

### A37.5 Identity, secrets, and keys

Application users authenticate through Google Identity Platform OIDC; Mindclade resolves tenant/project membership and authorization internally. Google Cloud administrative workforce access uses centralized workforce identity and short-lived sessions. GitHub Actions, Buildkite, GitOps, and workloads use federation with claims restricted by repository, protected ref/environment, pipeline, namespace, service account, and intended audience.

Each component receives a distinct Google service account or equivalent identity binding. Kubernetes service accounts map narrowly through Workload Identity Federation. No node-wide credential is treated as application identity.

Secret Manager stores secret values; manifests store typed references. Cloud KMS protects encryption and signing keys with separation between use and administration. Production release signing and break-glass keys require stronger approval, audit, rotation, and recovery controls than ordinary service secrets.

### A37.6 GKE control and workload clusters

Use regional GKE Standard clusters for GPU, distributed, privileged-device, and topology-sensitive workloads. Separate control/service and accelerator pools—and, when trust or blast radius justifies it, separate clusters—prevent general services from sharing the failure and privilege envelope of large training jobs.

Node pools are immutable, tainted, labeled by exact accelerator/driver/network/storage capability, and regularly rebuilt. Admission enforces signed images, allowed registries, workload identity, resource limits, security context, host/device access, topology requirements, and policy classification.

Autopilot or other managed modes may host compatible stateless services only after policy, cost, debugging, and workload constraints are qualified. They are not assumed to support every training/runtime requirement.

### A37.7 Accelerators and distributed training

The GCP adapter resolves a provider-neutral resource and topology request into qualified machine/accelerator/network/storage profiles. It records actual instance type, accelerator architecture/count, host topology, driver/runtime, collective library, fabric capability, placement policy, and reservation/provisioning mode in `HardwareTopologyManifest`.

Capacity strategy may combine reservations, committed use, dynamic/flex-start capacity, and preemptible/spot pools according to workload recovery class. Frontier training never assumes capacity availability; admission reports queue reason, reservation, expected constraints, and fallback policy. A fallback to another accelerator, region, topology, or network class creates a new admitted plan and qualification decision.

Provider-specific high-performance networking is qualified per machine generation. RDMA/GPUDirect settings, topology placement, collective tuning, and failure behavior are executable-plan inputs, not mutable shell configuration.

### A37.8 Storage and data paths

Cloud Storage is canonical for immutable datasets, features, checkpoints, model bundles, reports, release evidence, and large diagnostics. Buckets are separated by environment, classification, and lifecycle; access occurs through artifact authorization rather than handcrafted object paths.

Persistent Disk, local SSD, Filestore/Parallelstore or another qualified high-throughput service may provide staging, caching, or shared-read acceleration. These layers are reconstructible unless a specific durability contract says otherwise. Cache keys include artifact digest, transformation/executable plan, platform, and trust class.

Transfers use resumable/multipart behavior, per-part and whole-object integrity, bounded concurrency, encryption, scoped access, and atomic catalog commit. Cross-region copies verify digest and preserve manifest identity.

### A37.9 Database, queue, and cache

Cloud SQL for PostgreSQL is the initial operational database because the modular control plane requires transactions, constraints, relational queries, idempotency, and outbox semantics. Production uses regional HA, PITR, automated backups, connection pooling, tested failover, and migration discipline. AlloyDB or another database is adopted only when measured scale/availability requirements justify migration and compatibility evidence.

Pub/Sub transports compact outbox-derived messages at least once. Ordering is requested only for declared keys. Consumers use attempt fencing and idempotency; dead-letter topics preserve diagnostic references and never become a shadow job database. A committed database transaction—not Pub/Sub delivery—is the business state transition.

Redis/Memorystore or another cache is optional and reconstructible. It may support rate limiting, bounded coordination, or read acceleration, but cannot own authorization, job truth, artifact lineage, checkpoints, or agent memory evidence.

### A37.10 Build, registry, and supply chain

Trusted Buildkite agents run in isolated projects/pools with ephemeral workers and federated identity. Untrusted pull requests have no production secrets, release signing, protected cache writes, or environment mutation. GPU qualification pools are separate from ordinary builders and expose exact hardware labels.

Bazel remote cache/execution may use a qualified managed or self-hosted backend. Cache identity includes source, toolchain, platform, flags, and trust class. Release outputs are independently verified regardless of cache hit.

Artifact Registry stores images and distributable packages by digest. Release pipelines produce SBOM, SLSA v1.2-aligned provenance, signatures/attestations, qualification references, and release manifests. GitOps and workload admission verify the required predicates before deployment.

### A37.11 Observability and audit

All services and workers emit OpenTelemetry-compatible signals through controlled collectors. Google-managed telemetry backends may be the initial sink, but instrumentation, semantic conventions, and durable events remain vendor-neutral.

Log buckets/sinks are separated by environment and classification. High-volume GPU and data telemetry uses explicit budgets and sampling. Audit logs, release evidence, domain events, and agent/tool receipts have stronger integrity and retention than ordinary debug logs. Telemetry export failure degrades visibility, not authorization or durable correctness.

### A37.12 Deployment and promotion

The monorepo builds versioned deployment packages and images. The `gitops` repository selects exact digests and environment configuration; Argo CD/ApplicationSet reconciles them. `infrastructure-live` owns Google Cloud resources and IAM. MCDK may produce target-neutral and GCP-bound assemblies, but it does not apply production changes from the source monorepo.

Promotion follows development, staging, and production evidence policies. Rollback selects a retained trusted digest and compatible schema/config state; it never rebuilds an old commit. Database migrations use expand/migrate/contract and block incompatible rollback before promotion.

### A37.13 Backup, disaster recovery, and regional strategy

The initial profile is regional high availability in `us-central1` with documented isolated recovery into `us-east4` for Tier 0/1 state and artifacts. Multi-region active-active operation is deferred until product requirements justify its consistency, cost, and operational complexity. A protected data class may replicate to the recovery region only after its residency policy approves that movement.

Recovery covers the complete joined truth:

```text
database backup/PITR
+ artifact bytes and manifests
+ KMS/signing and secret recovery
+ release/GitOps history
+ identity and policy configuration
+ queued/outbox reconciliation
```

Drills restore into an isolated project, verify digests and schema, fence stale workers, reconcile external resources, and demonstrate the RTO/RPO class in Appendix A38.

### A37.14 Capacity and FinOps

Resources carry tenant/project, workload class, environment, model/run, owner, and cost-center attribution where cardinality and privacy permit. Budgets and forecasts distinguish committed baseline, elastic capacity, accelerator reservation, object/storage lifecycle, egress, CI, and observability.

Cost policy is admission-aware: large jobs require estimates and reservations; agents have explicit spend budgets; idle accelerator and orphaned artifact detection is automated; retention and replication follow durability class. Cost optimization cannot weaken recovery, security, numerical qualification, or provenance without an approved change.

### A37.15 Portability and future providers

Portability is preserved through:

- Protobuf/JSON Schema contracts;
- content-addressed portable artifacts;
- Kubernetes workload and resource-profile IR;
- explicit storage, queue, identity, database, registry, and telemetry adapters;
- provider-neutral model/training/agent semantics;
- conformance tests and frozen reference plans.

Mindclade does not wrap every Google Cloud API or promise live workload portability. An Azure, AWS, or on-prem profile implements named interfaces, declares semantic differences, migrates locators without changing artifact identity, and passes the relevant qualification. Multi-cloud activation remains governed by Appendix A32.8.

### A37.16 GCP qualification levels

| Level | Required evidence |
|---|---|
| `gcp-g0` | rendered plans/manifests, policy tests, isolated development environment |
| `gcp-g1` | private GKE service + artifact/database/identity path, backup and rollback smoke |
| `gcp-g2` | Kueue/JobSet GPU job, checkpoint/preemption, queue/outbox, signed admission |
| `gcp-g3` | multi-node topology/network/storage qualification, HA failover, restricted egress |
| `gcp-g4` | production SLO/capacity/cost, cross-region restore, identity/CI/registry compromise drills |

### A37.17 Capability-local qualification progression

1. Establish organization/folder/project, bootstrap, Shared VPC, identity federation, KMS, and state-recovery foundations for the fixed regional profile.
2. Deliver development GKE in `us-central1`, Cloud Storage artifact path, Cloud SQL control-plane slice, Pub/Sub outbox adapter, Artifact Registry, and Google Identity Platform integration.
3. Add staging promotion, signed admission, Kueue/JobSet, and separately approved one-GPU and multi-node qualification pools in `us-central1`.
4. Add production boundaries in `us-central1`, HA/PITR, private egress controls, SLOs, cost attribution, and isolated `us-east4` recovery drills. Restricted activation remains separate.
5. Qualify the first production release against Appendix A38 and preserve a tested portability seam.

### A37.18 Definition of done and invariants

The Google Cloud profile is production-ready when:

1. every provider resource implements a named Mindclade contract and has a single live-state owner;
2. projects, identities, networks, data, caches, builders, and clusters respect environment and trust boundaries;
3. production uses short-lived federated workload identity and external secret references;
4. private networking and explicit egress protect restricted and production workloads;
5. artifact, database, queue, build, registry, Kubernetes, and GitOps paths preserve canonical identity and fencing;
6. accelerator topology, networking, storage, and runtime are frozen and observed in run evidence;
7. build-once promotion verifies digest, provenance, signature, policy, and qualification;
8. HA, backup, restore, rollback, and cross-region recovery meet declared classes;
9. cost and capacity are attributable, budgeted, and admission-aware;
10. a future provider can be added through explicit adapters without changing domain truth.

Final invariants:

- Google Cloud is the initial realization, not the semantic authority;
- Pub/Sub delivers work; PostgreSQL/outbox owns state;
- Cloud Storage holds bytes; artifact manifests own identity and interpretation;
- GKE executes workloads; control-plane jobs and executable plans own intent;
- GitOps promotes existing digests; it never rebuilds or reinterprets releases.
