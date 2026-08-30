## Appendix A24 — Kubernetes and workload execution

Use Kubernetes as an execution substrate, not the source of business truth.

### A24.1 Workload classes

- long-running control-plane services;
- stateless gateways;
- CPU ingestion/preprocessing jobs;
- distributed GPU training;
- GPU evaluation;
- online and asynchronous inference;
- maintenance and conversion jobs;
- optional multi-role post-training/simulation workloads.

### A24.2 Scheduling pattern

- Kueue owns quota admission, cohorts, priority, and resource sharing.
- JobSet or the chosen distributed-training API groups coordinated jobs.
- Device plugins advertise accelerator and specialized device resources.
- The Mindclade control plane creates durable logical jobs and desired workload specifications.
- Kubernetes status is observed and reconciled into Mindclade job state; it is not the sole durable job record.
- A distributed workload may start a Monarch controller and role meshes inside its admitted JobSet when independent trainer/generator/evaluator scaling is required.
- The executable training plan defines rank/process topology inside trainer roles; Kubernetes manifests must not duplicate model-sharding policy.

### A24.3 Training workload requirements

Training workload specifications include or resolve:

```text
immutable worker image and recipe digest
hardware/resource profile
checkpoint recovery reference
termination grace and checkpoint deadline
local/regional recovery-cache policy
network/RDMA requirements
security and egress policy
artifact and telemetry destinations
```

Preemption signals flow to the worker, then to the trainer resilience layer. A pod termination does not directly publish a checkpoint or mutate run progress.

Local NVMe or regional cache may accelerate recovery checkpoints, but durable checkpoint generations and catalog truth remain in approved persistent storage. Cache loss must not invalidate the latest advertised durable recovery point.

### A24.4 Deployment flow

```text
monorepo release
  -> immutable image/package/model digests
  -> release manifest
  -> gitops promotion pull request
  -> Argo CD/ApplicationSet reconciliation
  -> environment health and policy gates
```

Use Argo CD projects to constrain source repositories, destinations, and resource kinds. Use ApplicationSets for repeated multi-cluster/environment generation. The GitOps repository owns the actual environment mapping.

### A24.5 Kubernetes authority boundary

Kubernetes owns scheduling and reconciliation of runtime resources. It does not own Mindclade business state, scientific run identity, artifact truth, or model/data semantics.

```text
Mindclade durable Job/Run
→ immutable WorkloadSpecification
→ Kubernetes/Kueue/JobSet resources
→ observed workload status and events
→ reconciled attempt evidence
```

The control plane may recreate Kubernetes resources from durable state. The reverse is not generally true. Deleting a pod, JobSet, or namespace does not erase the durable job or its artifacts.

### A24.6 Workload specification contract

A versioned workload specification contains:

```text
job/run/attempt identity and fence
immutable image and command/entrypoint
recipe/request/plan and input artifact digests
resource profile and topology requirements
queue, priority, cohort, and preemption policy
replica/role graph and completion policy
network/RDMA and storage requirements
checkpoint/recovery and termination deadline
service account, security context, and egress class
artifact, event, and telemetry destinations
labels/annotations with bounded canonical metadata
```

It contains no raw secrets or mutable image tags. Environment-specific mapping is applied by GitOps/admission policy, not embedded in model or training recipes.

### A24.7 Resource profiles

A `ResourceProfile` is a controlled catalog entry, not arbitrary user YAML. It defines:

- CPU, memory, ephemeral storage, and accelerator resources;
- accelerator architecture/memory class;
- node count and devices per role;
- local NVMe and shared storage requirements;
- topology constraints and acceptable relaxation;
- RDMA/NIC/rail requirements;
- queue and priority eligibility;
- maximum wall time and termination grace;
- cost/capacity class;
- security/data-classification eligibility.

Profiles are versioned and resolved before workload creation. Users request intent; platform policy chooses an allowed concrete profile.

### A24.8 Admission with Kueue

Kueue is the quota-admission layer for batch workloads. Mindclade maps workload intent into queue/class/cohort policy and observes admission. The contract distinguishes:

```text
job accepted by Mindclade
job queued for capacity
workload admitted by Kueue
pods created and scheduled
worker attempt running
```

A job is not `RUNNING` merely because a Kubernetes object exists. It becomes running only after a valid fenced worker attempt reports readiness under the job protocol.

Admission policy covers tenant/project quota, priority, fair sharing, cohort borrowing, resource flavor, preemption, maximum wait, and restricted pools. Policy and selected flavor are recorded as run evidence.

### A24.9 JobSet and role graph

JobSet or the selected distributed-workload API groups coordinated jobs/roles. A role declares:

```text
name and replica count
processes/devices per replica
startup and completion dependency
restart policy
network/rendezvous identity
resource profile
failure and success policy
```

Training roles normally form one rank-synchronous group. Optional generator, evaluator, simulator, or reward roles may scale separately inside a multi-role post-training workload. JobSet coordinates pods; the Mindclade executable plan still owns rank/process mesh, sharding, and collectives.

### A24.10 Workload and attempt reconciliation

A controller/reconciler maps observed Kubernetes state to attempt evidence through explicit rules:

```text
submitted resource UID/generation
admission status and conditions
pod/jobset identities
worker readiness and heartbeat
termination reason and exit code
node/preemption/eviction events
completion status
```

Kubernetes status may be stale, duplicated, or transient. The reconciler is idempotent and revision-aware. Only the control-plane job state machine commits business transitions. Conflicting worker and Kubernetes evidence is classified and surfaced, not resolved by last-write-wins.

### A24.11 Distributed rendezvous

Rendezvous is attempt-scoped and authenticated. It provides:

- expected role/rank/world membership;
- immutable attempt/run/plan digest agreement;
- endpoint discovery;
- timeout and restart semantics;
- stale-member fencing;
- diagnostics.

Ranks verify that all peers agree on source image, recipe, checkpoint, executable plan, and logical topology before numerical execution. A previous attempt cannot join a replacement rendezvous.

### A24.12 Topology-aware placement

Placement considers:

```text
failure domains and zones
NVLink/NVSwitch or equivalent islands
PCIe/NUMA locality
NIC/RDMA rails
node/GPU health and maintenance state
local storage
collective bandwidth classes
```

Kubernetes topology constraints express required physical co-location/separation. The discovered `HardwareTopologyManifest` remains authoritative for the executable planner. Requested and observed topology are compared before the run starts.

### A24.13 Accelerator and device resources

Device plugins/operators advertise accelerator resources and health. Mindclade additionally validates:

- architecture and memory;
- driver/runtime/toolkit compatibility;
- device topology;
- RDMA and GPUDirect capability where required;
- firmware/collective-library qualification;
- partitioning mode such as MIG if supported;
- health/retired-page or equivalent diagnostics.

A generic `nvidia.com/gpu` count alone is not sufficient for a production training plan.

### A24.14 Networking and RDMA

Workload network policy defines control-plane, artifact, telemetry, rendezvous, collective, DNS, and approved external endpoints. Distributed profiles declare MTU, RDMA device/network attachments, ports, and topology.

Requirements:

- no unrestricted egress by default for restricted workloads;
- network attachments are generated from platform profiles;
- collective/rendezvous ports are attempt-scoped and not publicly exposed;
- network-policy and service-mesh sidecars do not silently intercept or degrade RDMA traffic;
- bandwidth/latency health is measured and included in topology evidence;
- failed network setup blocks readiness before numerical work.

### A24.15 Storage classes and data paths

Use distinct storage paths:

| Path | Purpose | Durability |
|---|---|---|
| container filesystem | immutable software | image lifetime |
| `emptyDir`/ephemeral disk | attempt scratch, bounded caches | pod/attempt |
| local NVMe | high-speed recovery staging/cache | node-local, reconstructible unless explicitly replicated |
| shared filesystem | only workloads that require POSIX/shared access | platform-defined |
| object storage | canonical artifacts, datasets, checkpoints, reports | durable |
| secret/config projection | short-lived references/config | workload lifetime |

Workers never treat local/shared paths as artifact identity. Every published output passes through artifact commit and digest verification.

### A24.16 Checkpoint and preemption lifecycle

Preemption flow is:

```text
scheduler/node termination signal
→ pod preStop/signal delivery
→ worker records deadline and fences new work
→ trainer selects safe quiesce/checkpoint action
→ checkpoint manager stages/verifies/publishes if feasible
→ worker reports outcome
→ workload terminates
→ control plane retries/restores according to policy
```

The grace period must include signal propagation, quiesce, bounded staging, and shutdown. Kubernetes does not independently upload model state. If a safe checkpoint cannot complete, restore uses the latest verified durable recovery point.

### A24.17 Pod lifecycle and health

Startup, readiness, and liveness have different meanings:

- startup proves the process can initialize dependencies without premature restarts;
- readiness proves the worker/service may safely receive work or traffic;
- liveness detects irrecoverably wedged process state, not transient dependency outage.

GPU worker readiness may require device checks, artifact access, model/plan load, rendezvous completion, and a bounded smoke invocation. Probes are cheap and do not perform expensive scientific work repeatedly.

### A24.18 Security context

Default workload security includes:

```text
non-root user and read-only root filesystem where feasible
no privilege escalation
minimal Linux capabilities
seccomp/AppArmor/SELinux profile where supported
projected workload identity rather than static secrets
namespace/service-account isolation
restricted host paths and host networking
signed-image/admission verification
resource and ephemeral-storage limits
```

Privileged device access is narrowly provided by platform components, not arbitrary worker containers. Debug containers and node access require audited break-glass policy.

### A24.19 Namespace and multi-tenancy model

Namespaces are an operational isolation tool, not the sole tenant boundary. The platform defines namespace strategy by environment, workload class, and data sensitivity. Controls include RBAC, service accounts, network policy, resource quota, limit ranges, pod security, admission policy, and separate node pools/projects for stronger isolation.

Tenant identity remains in Mindclade authorization and resource contracts. A user never receives direct namespace credentials merely because they can submit a job.

### A24.20 Secrets and workload identity

Workloads receive short-lived identity scoped to exact APIs, artifact prefixes/actions, telemetry, and any source connector. Secrets are references resolved at runtime through approved stores. They are not rendered into GitOps, recipes, pod annotations, logs, or command-line arguments.

Rotation must not require image rebuild. Revocation should prevent new access promptly while allowing a policy-defined graceful shutdown for active operations.

### A24.21 Configuration injection

Deployment packages provide non-secret defaults and schemas. GitOps overlays provide environment mapping. The control plane provides immutable job-specific references. Admission may inject platform details such as endpoints, certificates, or sidecars.

The worker records a sanitized resolved-runtime manifest including relevant configuration digests, but not secret values. Unknown or conflicting configuration fails startup.

### A24.22 Deployment controllers and CRDs

Custom controllers/CRDs are justified only for durable platform-specific reconciliation not adequately handled by existing APIs. A CRD requires:

- versioned schema and defaulting/validation;
- status/condition conventions;
- conversion and upgrade strategy;
- finalizer behavior and deletion safety;
- ownership and SLO;
- RBAC and threat review;
- conformance and failure tests;
- GitOps representation.

Do not create a CRD merely to mirror every control-plane resource. Business resources remain in the control-plane database.

### A24.23 GitOps package boundary

The monorepo releases deployable package bases with schemas and safe defaults. The GitOps repository selects:

```text
artifact/image/package digest
environment/cluster/namespace
replicas and autoscaling bounds
resource profile mapping
secret/config references
network/security policy
rollout and promotion wave
```

Argo CD/ApplicationSet reconciles declared environment state. Runtime controllers may create ephemeral workload resources from durable jobs, but they use platform-approved templates and immutable images.

### A24.24 Rollout and rollback

Long-running services use progressive rollout appropriate to state and compatibility:

- pre-deployment schema/admission checks;
- readiness and smoke gates;
- canary or staged replicas;
- SLO/error comparison;
- automatic or approved promotion;
- rollback to exact previous image/package digest.

Workers can often roll out by draining old versions and admitting new jobs only to compatible versions. Active training runs normally continue on the frozen image/plan unless security policy forces checkpoint-and-stop.

### A24.25 Autoscaling

Service autoscaling uses request/concurrency/latency signals. Worker fleet scaling uses queue demand, admitted workloads, work units, model-load cost, and cluster capacity. Kueue admission remains quota authority; autoscaling does not create capacity entitlement.

GPU utilization alone is not an adequate scaling signal. Scale-down respects active leases, draining, checkpoint deadlines, model residency, and minimum warm capacity for latency-sensitive profiles.

### A24.26 Multi-cluster and region strategy

The control plane selects an eligible execution region/cluster using:

```text
data residency and classification
artifact locality
hardware/capacity availability
queue policy and cost
model/provider qualification
network and failure-domain requirements
```

Selection is recorded before workload creation. A job is not live-migrated across clusters; it checkpoints, creates a new fenced attempt, verifies target topology, and resumes with lineage. Cross-region artifacts are replicated by policy, not copied ad hoc by workers.

### A24.27 Observability and audit

Collect:

- admission/queue delay and resource flavor;
- scheduling and image-pull time;
- pod/JobSet state and restart causes;
- node/device/network health;
- requested versus observed resources/topology;
- termination/preemption deadlines and checkpoint outcome;
- resource utilization and throttling;
- controller reconciliation errors;
- policy/admission denials;
- workload identity and audit correlation.

High-cardinality pod/rank details live in logs/traces/diagnostic artifacts rather than broad metric labels.

### A24.28 Failure and recovery runbooks

Runbooks cover:

```text
stuck Kueue admission
unschedulable topology/resource flavor
partial JobSet startup
rendezvous timeout
node/GPU/RDMA failure
image or artifact pull failure
preemption without checkpoint
controller outage or bad reconciliation
namespace/network-policy denial
storage exhaustion
cluster or region loss
stale workload after job fencing
```

Every runbook identifies business-state safety checks before deleting or recreating Kubernetes resources.

### A24.29 Kubernetes qualification levels

| Level | Required evidence |
|---|---|
| `k8s-k0` | rendered schema/policy validation, local controller/unit tests |
| `k8s-k1` | single-cluster service/worker deployment, identity, network, storage, health |
| `k8s-k2` | Kueue admission, JobSet coordination, cancellation/preemption, stale attempt fencing |
| `k8s-k3` | topology/RDMA/GPU qualification, autoscaling, rollout/rollback, failure injection |
| `k8s-k4` | multi-cluster/region restore, DR, security/admission, sustained production operations |

### A24.30 Capability-local qualification progression

**Milestone 0 — service-owned packages:** validated Kustomize/Helm bases, workload specification, resource profiles, identity, network, and security defaults.

**Milestone 1 — one admitted GPU job:** control-plane job to Kueue/JobSet, fenced worker, artifacts, cancellation, preemption signal, and cleanup.

**Milestone 2 — distributed production:** topology discovery, RDMA profiles, multi-node rendezvous, checkpoint/retry, node/device failure injection.

**Milestone 3 — operations and scale:** GitOps promotion, progressive rollout, autoscaling, multi-cluster placement/restore, admission security, and DR drills.

### A24.31 Definition of done

Kubernetes execution is production-ready when:

1. business jobs/runs remain durable and reconstructible independently of Kubernetes resources;
2. every workload is generated from a typed immutable specification and approved resource profile;
3. Kueue admission, JobSet role grouping, worker readiness, and job state are distinct and correctly reconciled;
4. observed hardware/network topology is validated before binding the executable plan;
5. stale attempts and old rendezvous members cannot publish or rejoin;
6. storage paths are classified and only committed artifact generations are durable truth;
7. preemption reaches the trainer/worker safe-point protocol and never fabricates a checkpoint;
8. workload identity, network, pod security, and restricted-data isolation are enforced and tested;
9. GitOps promotes immutable package/image digests without embedding business state;
10. cluster/node/controller/region failures have tested recovery and runbooks.

### A24.32 Final Kubernetes invariants

- Kubernetes schedules execution; Mindclade owns durable job and scientific truth;
- Kueue owns quota admission, not job semantics;
- JobSet owns coordinated pod grouping, not model parallelism;
- every workload is attempt-scoped, fenced, and digest-bound;
- local storage accelerates but never replaces durable artifacts;
- topology-changing recovery occurs through checkpoint, replan, and explicit lineage;
- environment desired state remains in GitOps.
