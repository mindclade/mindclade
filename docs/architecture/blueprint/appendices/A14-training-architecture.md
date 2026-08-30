## Appendix A14 — Training architecture

### A14.1 Executive decision

Mindclade owns the trainer contract, task and objective semantics, training phases, logical state identity, optimizer lifecycle, data-progress semantics, topology policy, parallel-plan intermediate representation, checkpoint schema, callback ordering, reproducibility claims, and numerical qualification. Execution engines and optimized providers consume these contracts.

> **Mindclade owns one semantic control plane, one canonical trainer lifecycle, one compiled step-program contract, one logical state registry, one checkpoint schema, and one durable run record. Native PyTorch is the production execution substrate. Upstream systems contribute qualified capabilities; they do not become overlapping control planes.**
> **Critical-path constraint:** Through Wave 5, active training dependencies are native PyTorch, DeviceMesh/DTensor, FSDP2, DCP, NCCL, and maintained PyTorch reference operations. All other frameworks, providers, kernel languages, and custom accelerator paths described in this appendix form a capability-intake catalog only. They create no production package, configuration field, compatibility promise, or required test until a measured gap activates them under Section 3.5 and Wave 6.

The key distinction is between semantic ownership and execution ownership:

```text
Mindclade Trainer
  owns lifecycle, phase selection, update intent, progress commit,
  checkpoint/evaluation decisions, callbacks, and termination

CompiledStepProgram
  owns the distributed forward/backward microbatch schedule,
  collective ordering, pipeline communication, gradient synchronization,
  and provider-specific execution mechanics for one frozen plan
```

This boundary is required because a pipeline schedule may own warmup, steady state, cooldown, interleaving, virtual stages, activation deallocation, point-to-point communication, and delayed gradient synchronization. A low-level interface consisting only of `backward()` and `synchronize_gradients()` is not sufficient for all supported execution plans.

### A14.2 Training system planes

```text
┌────────────────────────────────────────────────────────────────────────────┐
│                           Model and task plane                             │
│  CladeFold / Clade-1 / Pairformer / diffusion / MoE / post-training       │
│  Pure model mathematics + provider-neutral task/objective semantics       │
└───────────────────────────────────┬────────────────────────────────────────┘
                                    │ TrainingSpec / immutable inputs
┌───────────────────────────────────▼────────────────────────────────────────┐
│                         Semantic control plane                            │
│  Trainer  TrainingTask  TrainingPhaseGraph  TrainingStateRegistry        │
│  ParameterUpdateGraph  DataProgress  CallbackBus  Evaluation policy      │
└───────────────────────────────────┬────────────────────────────────────────┘
                                    │ logical plan request
┌───────────────────────────────────▼────────────────────────────────────────┐
│                  Planning, transformation, and qualification plane        │
│  topology analysis  mesh IR  ordered pass graph  provider selection      │
│  collective plan  memory/cost model  compile regions  qualification      │
└───────────────────────────────────┬────────────────────────────────────────┘
                                    │ frozen ExecutablePlan
┌───────────────────────────────────▼────────────────────────────────────────┐
│                         Numerical execution plane                         │
│  CompiledStepProgram: microbatches → forward/backward → reductions       │
│  Native PyTorch engine + optional qualified provider implementations      │
└───────────────────────────────────┬────────────────────────────────────────┘
                                    │ logical distributed state
┌───────────────────────────────────▼────────────────────────────────────────┐
│                            Durable state plane                            │
│  PyTorch DCP  state epochs  snapshot fencing  async staging              │
│  atomic commit  integrity  reshard/migrate  recovery and durable tiers   │
└───────────────────────────────────┬────────────────────────────────────────┘
                                    │ optional multi-role workflow
┌───────────────────────────────────▼────────────────────────────────────────┐
│                         Outer orchestration plane                         │
│  Mindclade job control + Kubernetes/Kueue/JobSet                          │
│  optional Monarch meshes for trainer/generator/evaluator/simulator roles │
└────────────────────────────────────────────────────────────────────────────┘
```

OpenTelemetry-compatible events, metrics, logs, profiling, security classification, and artifact provenance cross all planes. No observability backend is allowed to become a correctness dependency of the numerical hot loop.

### A14.3 Ownership and package authority

| Concern | Canonical owner |
|---|---|
| Model mathematics, semantic axes, logical parameter roles, and model state schema | `models/` |
| Task semantics, named objectives, reduction meaning, and task-specific state | `training/api/` and `training/tasks/` |
| Trainer lifecycle, phase transitions, progress commit, and termination | `training/core/trainer/` |
| Logical state identity, schema, epochs, and registration | `training/core/state/` |
| Parameter ownership, optimizer phases, reductions, clipping, EMA, and health policy | `training/core/optimization/` |
| Training dataset manifest, batch receipts, packing, work units, and durable progress | `training/core/data/` |
| Mesh, placements, transformation passes, collectives, schedules, and executable plans | `training/execution/` |
| Provider-specific implementations | `training/providers/` |
| Precision policy and provider-neutral quantization state | `training/precision/` |
| DCP planning, snapshots, atomic publication, integrity, migration, and retention | `training/checkpointing/` |
| Evaluation semantics and release thresholds | top-level `evaluation/` |
| Evaluation scheduling, snapshot publication, and leases from a trainer | `training/evaluation/` |
| Kernel signatures, dispatch, and operation qualification | `kernels/` |
| Generic topology discovery, device/runtime primitives, compiler services, RNG utilities, and diagnostics | top-level `runtime/` |
| Durable jobs, tenancy, policy, quota requests, and audit | Go control plane |
| GPU process composition, job lease, cancellation, artifacts, and heartbeat | `workers/training_worker/` |
| Kubernetes quota admission and coordinated pods | Kueue and JobSet through deployment/GitOps packages |
| Multi-role in-job actor coordination when justified | `training/orchestration/monarch/` |

Package authority is exclusive:

- `training/core/state/` owns the only training state registry; checkpointing consumes it and does not define a second registry.
- `training/core/data/` owns durable training progress; checkpointing serializes it and execution engines do not reinterpret it.
- `training/precision/` owns provider-neutral policy; Transformer Engine integration lives under `training/providers/transformer_engine/`.
- `training/api/events.py` defines public event types; `training/telemetry/` owns sinks, reductions, and exporters.
- top-level `evaluation/` owns evaluation meaning; `training/evaluation/` only coordinates snapshots and scheduling.
- model-family packages expose capabilities and semantic metadata; task behavior belongs in `training/tasks/` unless it is strictly model forward logic.

There is no provider-owned experiment database or shadow run registry. The Go control plane remains the durable system of record for jobs and artifact references. The training process emits immutable run evidence and structured events.

### A14.4 Stable semantic contracts

The public API is intentionally small, typed, and provider-neutral. Exact Python signatures may evolve, but the ownership boundaries and semantic guarantees are mandatory.

#### Step context, loss terms, and objective bundles

```python
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Generic, Mapping, Protocol, Sequence, TypeVar

from torch import Tensor, nn

BatchT = TypeVar("BatchT")
OutputT = TypeVar("OutputT")


class ReductionScope(str, Enum):
    LOCAL = "local"
    DATA_PARALLEL = "data_parallel"
    REPLICA = "replica"
    EXPERT = "expert"
    GLOBAL = "global"


@dataclass(frozen=True, slots=True)
class StepContext:
    run_id: str
    phase_id: str
    step_epoch: int
    global_step: int
    optimizer_step: int
    microbatch_index: int
    consumed_samples: int
    consumed_tokens: int
    consumed_residues: int
    consumed_atoms: int
    training: bool
    rng: "RNGStreams"


@dataclass(frozen=True, slots=True)
class LossTerm:
    numerator: Tensor
    denominator: Tensor
    normalization_basis: str
    reduction_scope: ReductionScope
    backward_weight: float = 1.0


@dataclass(frozen=True, slots=True)
class ObjectiveBundle:
    losses: Mapping[str, LossTerm]
    metrics: Mapping[str, Tensor | float] = field(default_factory=dict)
    artifacts: Mapping[str, "DeferredArtifact"] = field(default_factory=dict)
```

A `LossTerm` carries a numerator and denominator instead of a pre-averaged microbatch scalar. This makes normalization explicit and independent of packing, microbatch count, and data-parallel layout.

Approved normalization bases include:

```text
examples
sequences
tokens
residues
atoms
valid_pair_cells
msa_tokens
diffusion_samples
complexes
```

A task may define a new basis only with a documented reduction contract and qualification fixtures.

#### Training task

```python
class TrainingTask(Protocol, Generic[BatchT, OutputT]):
    def build_model(self, context: "ModelBuildContext") -> nn.Module: ...
    def build_data(self, context: "DataBuildContext") -> "DataSource": ...
    def prepare_batch(self, sample: "ModelInputSample", context: StepContext) -> BatchT: ...

    def forward(
        self,
        model: nn.Module,
        batch: BatchT,
        context: StepContext,
    ) -> OutputT: ...

    def objectives(
        self,
        output: OutputT,
        batch: BatchT,
        context: StepContext,
    ) -> ObjectiveBundle: ...

    def evaluators(self) -> Sequence["EvaluatorRef"]: ...
    def checkpointables(self) -> Mapping[str, "Checkpointable"]: ...
```

`TrainingTask` defines model-objective semantics. Shared feature resolution and the released model's deterministic `ModelFeatureView` occur before `prepare_batch`; the task receives a `ModelInputSample` and may perform only task-owned runtime transformations declared by its `BatchRecipe`/logical RNG contract. It does not reinterpret `FeatureContract`s, query `data/featurization/`, own model tensorization, create process groups, wrap modules with FSDP, choose providers, call `optimizer.step()`, publish checkpoints, write to the control-plane database, or resolve cluster credentials.

#### Training phase graph

A run may contain explicit phase transitions such as pretraining, domain adaptation, fine-tuning, distillation, quantization-aware training, sparsity, confidence-head training, or reinforcement learning.

```python
@dataclass(frozen=True, slots=True)
class TrainingPhase:
    phase_id: str
    task: "TaskRef"
    data: "TrainingDatasetRef"
    optimization: "OptimizationPlan"
    precision: "PrecisionPolicy"
    evaluation: "EvaluationPolicy"
    transition: "PhaseTransitionPolicy"


@dataclass(frozen=True, slots=True)
class TrainingPhaseGraph:
    entry_phase: str
    phases: Mapping[str, TrainingPhase]
    edges: tuple["PhaseEdge", ...]
```

A phase boundary may change the dataset mixture, objectives, frozen modules, parameter ownership, optimizers, schedules, precision, evaluation suite, or executable plan. Any executable-plan change occurs through a committed checkpoint boundary and creates explicit lineage.

#### Logical state identity and schema

Python module names are not stable enough to be the durable identity of frontier-scale state. FSDP wrapping, provider replacement, pipeline partitioning, compilation, fusion, and model migration may all change physical names.

```python
@dataclass(frozen=True, slots=True)
class LogicalStateId:
    namespace: str
    component: str
    path: tuple[str, ...]
    role: str
    schema_version: int


@dataclass(frozen=True, slots=True)
class StateSchemaEntry:
    logical_id: LogicalStateId
    shape_expression: "ShapeExpression"
    dtype: str
    semantic_axes: tuple[str, ...]
    placements: tuple["Placement", ...]
    replication: "ReplicationPolicy"
    update_owner: str | None
    migration_key: str | None


class TrainingStateRegistry(Protocol):
    def register(
        self,
        logical_id: LogicalStateId,
        component: "Checkpointable",
        schema: StateSchemaEntry,
    ) -> None: ...

    def describe(self) -> Mapping[LogicalStateId, StateSchemaEntry]: ...
    def local_state(self, selection: "StateSelection") -> "LocalStateView": ...
    def restore(self, source: "StateSource", plan: "LoadPlan") -> None: ...
```

The registry exposes distributed state handles and schemas to save/load planners. It must not require materializing the entire global state into one Python mapping.

#### Optimization phases and parameter update graph

```python
@dataclass(frozen=True, slots=True)
class OptimizationPhase:
    name: str
    optimizer: str
    losses: tuple[str, ...]
    every_steps: int = 1
    accumulation_steps: int = 1
    retain_graph: bool = False
    gradient_clip: "GradientClipPolicy | None" = None


@dataclass(frozen=True, slots=True)
class OptimizationPlan:
    phases: tuple[OptimizationPhase, ...]


@dataclass(frozen=True, slots=True)
class ParameterUpdateEdge:
    parameter: LogicalStateId
    phase: str
    optimizer: str
    group: str


@dataclass(frozen=True, slots=True)
class ParameterUpdateGraph:
    edges: tuple[ParameterUpdateEdge, ...]
```

For each active phase, every trainable parameter has exactly one update owner unless an explicit, qualified shared-update rule says otherwise. Validation rejects double ownership, missing ownership, stale optimizer state, and provider replacement after optimizer construction.

#### Compiled step program

```python
class CompiledStepProgram(Protocol):
    def execute_forward_backward(
        self,
        *,
        task: TrainingTask,
        microbatches: "MicrobatchStream",
        context: StepContext,
    ) -> "StepExecutionResult": ...

    def apply_update(
        self,
        *,
        execution: "StepExecutionResult",
        phase: OptimizationPhase,
    ) -> "UpdateReceipt": ...

    def quiesce(self, snapshot_epoch: "SnapshotEpoch") -> "SnapshotHandle": ...


class TrainingEngine(Protocol):
    def prepare(
        self,
        *,
        model: nn.Module,
        task: TrainingTask,
        state: TrainingStateRegistry,
        executable_plan: "ExecutablePlan",
        precision: "PrecisionPolicy",
        update_graph: ParameterUpdateGraph,
    ) -> CompiledStepProgram: ...

    def close(self) -> None: ...
```

The trainer selects phases, requests execution, validates the returned receipts, commits progress, and makes lifecycle decisions. The compiled step program owns provider-specific forward/backward and distributed schedule mechanics.

### A14.5 Canonical trainer lifecycle and update ownership

The trainer is an explicit state machine:

```text
CREATED
  -> INITIALIZING
  -> MATERIALIZING
  -> READY
  -> RUNNING
       -> VALIDATING -> RUNNING
       -> QUIESCING -> SNAPSHOTTING -> RUNNING
       -> CHECKPOINTING -> RUNNING
       -> PHASE_TRANSITION -> MATERIALIZING -> READY -> RUNNING
       -> RECOVERING -> READY -> RUNNING
       -> COMPLETED
       -> CANCELLED
       -> FAILED
```

A successful logical update has one authoritative order:

```text
resolve phase and deterministic batch identity
-> fetch and prepare batch stream
-> execute compiled forward/backward schedule
-> aggregate loss numerators and denominators
-> complete gradient accumulation
-> synchronize or partition gradients according to the plan
-> unscale gradients when required
-> finite-value and health-policy checks
-> apply clipping and update through the compiled program
-> update scheduler, EMA, and registered post-update state
-> validate UpdateReceipt
-> atomically commit StepEpoch and DataProgress
-> reduce and emit metrics
-> evaluate/checkpoint/callback decisions
```

The `UpdateReceipt` records at least:

```text
run, phase, and step epoch
optimizer phase and update identity
logical parameter-set digest
input batch-receipt digest set
loss numerator/denominator summary
precision and loss-scale outcome
finite-value and clipping outcome
provider/executable-plan digest
success or classified failure
```

The progress commit occurs only after the optimizer update and associated registered-state updates succeed. Recovery must never advance the data cursor while losing an update, or repeat an update while advancing the cursor.

Pipeline execution is not implemented as callbacks around a generic eager loop. A schedule registry selects a `CompiledStepProgram` that may own:

- GPipe, 1F1B, interleaved, zero-bubble, or provider-specific ordering;
- microbatch warmup, steady state, and cooldown;
- virtual pipeline stages;
- activation deallocation or recomputation;
- point-to-point sends and receives;
- delayed data-parallel synchronization;
- overlap between compute and collectives.

The trainer remains authoritative because it selects the phase and update intent, while the schedule program remains authoritative for distributed execution ordering.

### A14.6 State epochs, snapshots, and durable recovery

The system distinguishes four concepts:

| Concept | Meaning |
|---|---|
| Execution boundary | An internal transition in the trainer or compiled program |
| Consistent snapshot point | Registered state can be observed or copied without cross-component races |
| Committed update | Model, optimizer-related state, and progress share one logical `StepEpoch` |
| Durable recovery point | A verified checkpoint generation can reproduce the declared next logical update |

Core identities are:

```text
StepEpoch
SnapshotEpoch
CheckpointGeneration
DurableRecoveryPoint
WorkerAttempt
```

The default durable recovery boundary is a committed optimizer update. Mid-accumulation recovery is optional and enabled only when gradient buffers, microbatch position, pipeline state, data progress, and provider semantics are explicitly registered and qualified.

Asynchronous checkpointing uses snapshot fencing:

```text
update N completes
-> StepEpoch N commits
-> SnapshotEpoch N is frozen, copied, or versioned
-> asynchronous staging reads only SnapshotEpoch N
-> live training may proceed to N+1
-> generation N publishes only after every required shard verifies
```

A checkpoint that mixes model, optimizer, scheduler, precision, EMA, callback, or data state from different epochs is invalid and must be rejected.

Use two operational checkpoint tiers:

1. **Recovery checkpoints** are frequent and optimized for restart latency. They may use node-local or regional durable caches, but still require an integrity manifest and attempt fencing.
2. **Durable checkpoints** are immutable object-store generations with complete lineage, verification, retention, and promotion evidence.

A preemption policy receives the termination deadline and selects one of these actions:

```text
finish current committed update and write recovery checkpoint
quiesce at the latest consistent snapshot point
terminate and restore from the latest durable recovery point
```

It must not attempt an unsafe best-effort save that produces a seemingly valid mixed-epoch generation.

The recovery guarantee is:

> A restored run resumes from the latest verified durable recovery point and reproduces the same next logical update, data position, RNG derivations, registered state, and provider plan under the declared reproducibility level.

### A14.7 Deterministic RNG, training data manifests, and batch receipts

The RNG hierarchy derives independent streams from a run seed, stable sample identity, phase, step epoch, microbatch identity, and semantic purpose.

Required streams include:

```text
python
numpy
torch_cpu
torch_cuda
model
data
diffusion
routing
augmentation
evaluation_sampling
```

Diffusion noise, classifier-free dropout, MoE routing randomness, data augmentation, and sampling evaluation must not accidentally share streams. Where practical, stochastic objectives use stateless sample-keyed randomness so changing data-parallel degree or resuming on a new topology does not silently change sample-level semantics.

Before task-owned preparation, the input path is fixed as:

```text
TrainingDatasetManifest / stable sample identity
    ↓
resolved reusable FeatureBundle
    ↓ released model ModelFeatureView
ModelInputSample
    ↓ task-owned BatchRecipe + logical RNG transforms
ModelBatch
    ↓ TrainingTask.forward/objectives
```

`feature_resolver.py` may resolve/verify `FeatureBundle`s but does not apply model tensorization. The model-owned feature view creates `ModelInputSample`. `TrainingTask.prepare_batch` starts only from that model input and may apply declared task/runtime transforms; it cannot call back into semantic feature discovery.

A training-eligible input is represented by a `TrainingDatasetManifest` containing:

```text
dataset and feature artifact digests
stable sample-identity schema
shard index and source offsets
ordering and shuffle algorithm/version
packing and bucketing algorithm/version
data mixture and curriculum policy
quarantine/exclusion set
expected shape and work-unit distributions
feature and model compatibility
license, policy, and security classification
```

Every prepared batch produces a compact `BatchReceipt`:

```text
batch identity
sample identities
source shard identities and offsets
FeatureBundleDigest and required FeatureManifest/artifact digests
model feature-view / deterministic model-input artifact digest when materialized
packing-layout and BatchRecipe digest
shape and work-unit counts
augmentation/RNG derivation identities
quarantine/exclusion decisions
data-pipeline implementation/version
```

Receipts contain identifiers and digests, not raw biological payloads. They support bad-batch replay, duplicate/skip detection, dataset-mixture audits, numerical incident reconstruction, and step capsules.

Data progress is a durable logical cursor, not a Python iterator position. It records:

```text
training dataset manifest
phase and cycle/epoch
ordered sample or token frontier
shard assignment
packing/bucket state
sampler state
prefetch visibility boundary
last committed BatchReceipt set
```

Fetched or prefetched data is not considered consumed until the corresponding `UpdateReceipt` and `StepEpoch` commit.

Biological workloads use model-aware work units rather than examples alone:

```text
work =
    α * sequence_tokens
  + β * pair_cells
  + γ * msa_tokens
  + δ * atoms
  + ε * diffusion_samples
  + ζ * template_tokens
```

A model family supplies the cost features and a qualified calibration record. The batching/planning system uses them for bucketing, packing, microbatch limits, pipeline balance, OOM prevention, and systems autotuning. Production coefficients are frozen into the executable plan rather than adapted invisibly during an official run.

### A14.8 Parallel-plan IR, transformation passes, topology, and collectives

Model code describes mathematical structure. A separate plan describes placement and execution.

```text
model and logical state schema
+ task and phase graph
+ immutable shape/work distribution
+ hardware topology manifest
+ precision and reproducibility policy
+ logical parallel-plan request
+ qualified provider set
= frozen executable distributed program
```

Standard logical mesh axes are:

```text
dp_replicate   replicated data-parallel groups
dp_shard       FSDP/HSDP parameter-sharding dimension
tp             tensor parallelism
pp             pipeline parallelism
cp             context/long-sequence parallelism
ep             expert parallelism
```

Sequence parallelism is normally a tensor-layout transformation associated with TP or CP, not an unrelated world-size dimension.

Mindclade model families may declare semantic axes:

```text
sequence
pair_i
pair_j
msa
atom
sample
recycle
expert
modality
```

These are model semantics. They become physical mesh axes only when the executable plan chooses that mapping.

#### `HardwareTopologyManifest`

Planning consumes an immutable `HardwareTopologyManifest` containing:

```text
nodes and failure domains
GPU architecture, count, and memory
NVLink/NVSwitch or equivalent connectivity
PCIe and NUMA placement
NICs, rails, and RDMA capabilities
measured bandwidth and latency classes
driver, firmware, CUDA/ROCm, collective-library, and kernel identity
```

The manifest is a planning input and run-evidence artifact. A production plan is not silently reused on materially different topology.

#### Ordered transformation-pass graph

Execution preparation is a dependency-checked pass DAG, not a collection of independent booleans.

Canonical order is:

```text
construct/analyze on meta device
-> establish logical state and semantic tensor metadata
-> replace qualified modules/providers while still unmaterialized
-> apply TP/EP/model-specific partitioning
-> partition pipeline stages
-> apply activation checkpoint/offload policy
-> apply FSDP/HSDP
-> establish precision and quantization policy
-> materialize, initialize, load, or reshard logical state into the target layout
-> construct parameter update graph and optimizer state
-> select compile regions
-> capture eligible CUDA graphs
```

Each pass declares:

```python
class TransformationPass(Protocol):
    name: str
    requires: frozenset[str]
    provides: frozenset[str]
    incompatible_with: frozenset[str]

    def analyze(self, graph: "ModelGraph") -> "PassReport": ...
    def apply(self, graph: "ModelGraph") -> "ModelGraph": ...
```

The exact order may differ for a qualified provider combination, but it must be explicit, validated, and recorded. A provider may not mutate the module graph after logical state, parameter groups, or optimizer state have been finalized unless a declared pass invalidates and rebuilds those dependent artifacts.

#### Collective plan

One registry creates all process groups and communicator views. The `CollectivePlan` records:

```text
mesh views and rank coordinates
process-group identity and owner
collective ordering constraints
TP/CP/EP communication strategy
all-gather and reduce-scatter overlap policy
pipeline peer mappings
hierarchical collective selection
communicator limits and timeouts
health and diagnostic policy
```

Hidden process-group creation is prohibited.

#### Executable plan

The planner:

1. Analyzes model, logical state, shape families, semantic axes, and capabilities.
2. Validates world-size, dimension, expert, sequence, residue, atom, sample, and bucket constraints.
3. Partitions stages and estimates bubble and imbalance.
4. Assigns tensor placements and state ownership.
5. Resolves the transformation-pass graph.
6. Selects provider implementations by capability.
7. Creates the collective plan and process-group inventory.
8. Selects activation, offload, compilation, and CUDA-graph regions.
9. Estimates parameter, gradient, optimizer, activation, temporary, communication, staging, and fragmentation headroom.
10. Validates checkpoint resharding, state migration, RNG partitioning, and reproducibility claims.
11. Emits an immutable `ExecutablePlan` and digest.

The executable plan records:

```text
logical mesh and physical topology mapping
ordered transformation passes
module/provider ownership
state-name and placement mappings
pipeline schedule
collective plan
precision and quantization choices
compiled-region manifests
kernel dispatch qualifications
memory and work-unit estimates
reproducibility guarantees
approved fallback set
```

Provider composition is fail-closed:

- one provider owns sharding for a module subtree;
- one schedule owns a pipeline stage set;
- native TP and Megatron TP may not wrap the same logical parameter;
- native and provider pipeline schedules may not own the same stages;
- FSDP2 around provider-managed sharding or a distributed optimizer is rejected unless that exact composition is qualified;
- Transformer Engine or TileLang may replace leaf operations inside another provider-owned subtree because they are precision/kernel providers, not trainer owners;
- actor messaging may coordinate roles but may not occur inside rank-synchronous collectives or autograd execution;
- unsupported combinations fail before a large GPU allocation is consumed.

### A14.9 Engines, schedule registry, and execution profiles

#### Single-process reference engine

`SingleProcessEngine` is the correctness oracle for CPU and one-GPU execution. It supports eager FP32/BF16, deterministic fixtures, finite-difference checks, one-step capsules, and checkpoint round trips.

#### Native production engine

`NativePyTorchEngine` is the default production engine. It uses native PyTorch distributed primitives and TorchTitan-compatible patterns for DeviceMesh/DTensor, DDP, FSDP2/HSDP, tensor/pipeline/context parallelism, meta initialization, activation checkpointing, compilation, distributed checkpointing, and distributed diagnostics.

TorchTitan compatibility tests track upstream behavior and permit selective intake of proven components. TorchTitan configuration and extension interfaces are not permanent Mindclade public contracts.

#### Fabric developer engine

`FabricEngine` provides local launch, device setup, precision setup, notebooks, and small-scale DDP ergonomics while consuming the same task, state, recipe, callback, evaluation, and checkpoint contracts. It does not establish a second production lifecycle.

#### Virtual distributed profile

A `virtual-mesh` profile exercises mesh, placement, state-schema, and planning logic in one process or a lightweight emulation environment. It is for plan development and conformance tests, not a substitute for real distributed qualification.

#### Schedule registry

The schedule registry maps a qualified pipeline capability to a compiled program implementation:

```text
eager
gpipe
1f1b
interleaved_1f1b
zero_bubble_family
provider_specific
model_specific
```

A schedule declares supported stage graphs, microbatch constraints, activation policy, collective requirements, recovery boundaries, compilation compatibility, and determinism behavior.

#### Execution profiles

| Profile | Engine and providers | Intended use |
|---|---|---|
| `developer` | Single-process or Fabric | CPU, one GPU, notebooks, local DDP, rapid debugging |
| `virtual-mesh` | Single-process distributed emulation | Plan, placement, and state-schema development |
| `native-production` | Native PyTorch engine | Default dense, multimodal, diffusion, and structure training |
| `frontier-transformer` | Native engine plus qualified Megatron Core and Transformer Engine capabilities | Largest Transformer and MoE configurations |
| `pairformer-production` | Native engine plus Pairformer-aware planning and qualified TileLang kernels | CladeFold structure and multimodal biological models |
| `posttraining-production` | Native trainer plus optional rollout/reward roles | Distillation, preference optimization, RL, and self-improvement |
| `qualification` | Native reference plus provider comparison harnesses | Numerical, recovery, performance, and conversion evidence |
| `edge-intake` | Pinned upstream development revisions | Feature evaluation only; never an unqualified production default |

A resolved run manifest records the model, task, phase graph, recipe, dataset, hardware topology, executable plan, providers, kernels, checkpoint schema, code, container, compiler, PyTorch, CUDA/ROCm, collective libraries, and qualification evidence. Provider selection never changes silently after resume.

### A14.10 Provider architecture

Upstream projects are capability sources, not trainer owners.

| Upstream system | Capabilities to adopt | Integration boundary | Must not own |
|---|---|---|---|
| Native PyTorch and TorchTitan | DeviceMesh/DTensor, DDP, FSDP2/HSDP, TP/PP/CP, meta initialization, activation checkpointing, compilation, DCP, fault-tolerance integration, diagnostics | Native engine and upstream intake lane | Mindclade task semantics, stable API, recipe language, or checkpoint publication |
| Megatron Core | TP/PP/CP/EP, advanced pipeline schedules, communication overlap, MoE routing/dispatch, grouped GEMM, optimized transformer components, distributed optimizer concepts | Qualified execution, schedule, MoE, optimizer, and kernel capabilities | Global argument state, hidden process groups, monolithic training scripts, or canonical checkpoints |
| DeepSpeed | CPU/NVMe state placement, activation offload, memory estimation, CPU optimizer concepts, coalesced reductions, tuning ideas | Narrow memory/optimizer/reduction capability or independently authored equivalent | `DeepSpeedEngine`, DeepSpeed JSON as canonical configuration, or ZeRO checkpoints as canonical state |
| PyTorch Lightning | Lifecycle ergonomics, callback/event design, debug profiles, validation cadence, progress presentation | Developer-experience reference | Production semantic ownership |
| Lightning Fabric | Launch, device/precision setup, notebooks, small-scale distributed execution | Developer engine | A second production distributed control plane |
| TorchForge | Algorithm/infrastructure separation, rollout APIs, synchronous/asynchronous post-training patterns, policy versioning | Post-training/RL adapter and design input | Generic task, state, artifact, or job ownership |
| Monarch | Actor meshes, supervision, role-level recovery, messaging, distributed tensors, direct transfers | Optional outer role orchestration | Rank-synchronous model execution, backward, optimizer stepping, quota admission, or job truth |
| Transformer Engine | FP8-family formats, scaling metadata, fused transformer operations, optimized attention/MLP/norm components | Precision and leaf-kernel provider | Model API types, global precision policy, or silent fallback |
| TorchAO | Quantization, sparsity, QAT, and low-precision primitives | Quantization and post-training provider | Phase semantics or canonical quantization state |
| TileLang | Specialized biological-model kernels, TMA/swizzle pipelines, custom fusion | Kernel provider through `kernels/` qualification | Unqualified replacement of reference paths |

Representative capabilities include:

```text
parallel.fsdp2
parallel.pipeline.interleaved
parallel.pipeline.zero_bubble
parallel.context
parallel.expert
moe.route
moe.dispatch
moe.grouped_gemm
precision.fp8.linear
precision.mxfp8.linear
precision.nvfp4.linear
quantization.qat
attention.flash
attention.variable_length
pairformer.triangle_attention
pairformer.triangle_multiplication
checkpoint.async
memory.offload.cpu
memory.offload.nvme
optimizer.cpu_adam
reduction.coalesced
compilation.aot_region
```

Each capability declaration includes:

```text
provider and version
hardware and software constraints
shape/dtype/layout constraints
semantic guarantees
state and checkpoint implications
compile compatibility
determinism and reproducibility claims
qualification report digest
explicit fallback policy
```

Provider-specific state is translated into stable logical state. Provider-specific global arguments, singleton registries, process groups, and checkpoint naming may not leak into model or task APIs.

### A14.11 Precision, quantization state, and reproducibility

Precision is a typed policy rather than one global string:

```python
@dataclass(frozen=True, slots=True)
class PrecisionPolicy:
    parameter_dtype: str
    gradient_reduce_dtype: str
    optimizer_state_dtype: str
    default_compute_dtype: str
    accumulation_dtype: str
    module_overrides: Mapping[str, "ModulePrecision"]
    loss_scaling: "LossScalingPolicy | None"
    permitted_fallbacks: frozenset[str]
    reproducibility: "ReproducibilityPolicy"
```

Initial modes are:

| Mode | Purpose |
|---|---|
| BF16 parameters/compute with FP32-sensitive accumulations | Universal distributed correctness baseline |
| BF16 with selected FP8 operations | Qualified hardware acceleration |
| Selected MXFP8 operations | Qualified compatible-hardware configurations |
| Selected NVFP4 operations | Experimental until model-family long-horizon qualification passes |
| FP32 reference | Small numerical-oracle and finite-difference runs |
| Mixed custom policy | Pairformer geometry, diffusion schedules, confidence heads, norms, reductions, and other sensitive paths |

Low precision is selected per operation or module family. Geometry, coordinate updates, diffusion schedule math, normalization statistics, confidence heads, and sensitive reductions may remain BF16 or FP32 while projections use lower precision.

Provider-independent quantization state includes:

```text
logical module identity
format and recipe identity
scale and amax history
calibration state
forward/backward format asymmetry
scaling algorithm and update cadence
fallback records
schema and migration version
```

The checkpoint schema stores this logical state rather than opaque provider objects whenever possible.

Reproducibility is not a binary flag. Recipes declare a level:

| Level | Contract |
|---|---|
| `bitwise` | Identical state and outputs on the same qualified hardware/software stack |
| `numerically_equivalent` | Results stay within declared operation and accumulated tolerances |
| `statistically_equivalent` | Long-horizon metrics and distributions stay within accepted bounds |
| `best_effort` | Research/debug execution without release guarantees |

Claims are separated by dimension:

```text
batch invariance
microbatch invariance
data-parallel topology invariance
full topology invariance
restart invariance
hardware-generation portability
```

A provider combination advertises only the strongest level it has actually qualified. Requested guarantees fail preflight if unavailable.

### A14.12 Optimization, reductions, parameter ownership, and health policy

Optimizer construction receives logical parameter metadata, topology, placements, precision, phase graph, expected step count, and update ownership.

Required capabilities include:

- one or more named optimizers and update phases;
- independent scheduler state;
- semantic parameter-group rules;
- decoupled weight decay and no-decay policy;
- layer-wise or model-family-specific learning-rate rules;
- distributed optimizer support where qualified;
- exact gradient-accumulation scaling;
- delayed or coalesced reductions where qualified;
- global, per-group, and model-specific clipping;
- EMA and other registered post-update transitions;
- CPU optimizer-state placement;
- optional CPU/NVMe parameter or optimizer offload;
- activation checkpointing and activation offload;
- bounded prefetch and staging memory;
- memory estimation before launch.

#### Reduction semantics

For each loss term, the trainer and compiled program aggregate numerators and denominators across microbatches and the declared mesh scope before constructing the scalar objective.

Required equivalence tests are:

```text
one global batch
≈ multiple gradient-accumulation microbatches
≈ supported data-parallel layouts
≈ supported topology-changing resume
```

A mean of per-microbatch means is prohibited unless mathematically proven equivalent for that term.

#### Parameter ownership

The `ParameterUpdateGraph` is built after provider replacement and sharding passes but before optimizer state creation. It validates:

- exactly one update owner for each trainable logical parameter in an active phase;
- no optimizer state for absent or incompatible logical parameters;
- no unexpected gradient on frozen state;
- scheduler and optimizer phase compatibility;
- checkpoint schema compatibility across phase transitions;
- explicit ownership of shared experts, adapters, teacher/student state, and auxiliary heads.

#### Multi-objective health policy

The recipe maps conditions to typed actions:

```text
NaN or Inf
gradient explosion
loss-scale collapse
routing collapse
data starvation
persistent straggler
kernel shadow mismatch
collective timeout
GPU hardware fault
checkpoint backlog
evaluation regression
```

Possible actions are:

```text
continue and record
retry current batch under the same plan
quarantine a policy-approved sample
request an explicitly approved provider fallback
write recovery checkpoint and terminate
terminate immediately
request replacement allocation
```

A fallback is permitted only when named in the immutable recipe and executable plan. It produces a new run-evidence event and may require a new plan digest. Official qualification runs default to fail-closed behavior.

### A14.13 Canonical checkpointing, recovery tiers, and migration

The canonical format is PyTorch Distributed Checkpoint wrapped by Mindclade logical state schemas, manifests, snapshot epochs, atomic publication, integrity verification, lineage, migration, retention, and load-time resharding.

Every recovery generation contains or references:

```text
logical model state
optimizer and scheduler state
precision and quantization state
EMA and registered post-update state
StepEpoch and progress commit
optional gradient-accumulation state
RNG streams
data progress and BatchReceipt frontier
task-specific state
callback delivery state
evaluation scheduling state
phase graph and active phase
hardware topology and executable-plan manifests
provider and compiled-region manifests
autotune record
run manifest
post-training/RL state when applicable
```

#### Save protocol

```text
1. Reserve CheckpointGeneration and parent lineage.
2. Fence a consistent SnapshotEpoch.
3. Resolve registered logical state through the save planner.
4. Stage shards asynchronously with bounded memory and backpressure.
5. Write component inventory, schemas, placements, and content digests.
6. Verify epoch consistency, distributed completeness, and integrity.
7. Publish the immutable generation manifest.
8. Atomically update the latest-valid catalog reference.
9. Apply retention only after commit succeeds.
```

#### Restore protocol

```text
1. Resolve an immutable generation and verify its manifest.
2. Validate model, task, phase, logical state schema, recipe, and migration path.
3. Discover the target hardware topology and compile the target executable plan.
4. Build the target DeviceMesh and logical state layout.
5. Load and reshard through DCP planners.
6. Restore optimizer, scheduler, precision, EMA, callbacks, evaluation, and task state.
7. Restore RNG streams, data progress, BatchReceipt frontier, and StepEpoch.
8. Validate the declared reproducibility and recovery contract.
9. Resume through the trainer lifecycle.
```

Required behavior includes:

- asynchronous save with snapshot fencing;
- request coalescing and bounded staging;
- recovery and durable checkpoint tiers;
- atomic publication;
- partial load by logical component;
- load-time resharding;
- corruption and mixed-epoch detection;
- schema migration;
- parent lineage and branch/fork semantics;
- retention and lease-aware deletion;
- preemption-aware checkpoint deadlines;
- conversion to release model bundles.

Provider-native formats are import/export formats only:

```text
Megatron / DeepSpeed / Hugging Face / safetensors
    -> converter -> Mindclade logical DCP

Mindclade logical DCP
    -> exporter -> model bundle / safetensors / provider format
```

A converter maps stable logical state identities and records any lossy or unsupported transformation. File-name heuristics are not accepted as schema.

### A14.14 Model-family and phase execution requirements

#### Dense, multimodal, and representation pretraining

- DDP, FSDP2, HSDP, TP, PP, and CP as required;
- packed and variable-length batches;
- selective activation checkpointing;
- shape-bucket-aware compilation;
- multiple modalities and auxiliary objectives;
- deterministic masking and corruption;
- semantic parameter groups;
- checkpoint conversion and topology-changing resume.

#### Pairformer and structure models

- independent `pair_i` and `pair_j` semantic placement;
- row/column sharding for pair representations;
- triangle multiplication, triangle attention, outer-product mean, and transition provider interfaces;
- sequence, MSA, pair, template, atom, sample, and recycle metadata;
- residue/atom/sample-aware batching, normalization, and memory estimation;
- model-aware work-unit calibration;
- module-specific activation and precision policies;
- TileLang kernels behind standard dispatch and qualification;
- two-dimensional communication plans that do not treat `[B, N, N, C]` pair tensors as ordinary decoder-token tensors;
- immutable sampling and confidence-evaluation references.

#### Mixture-of-experts and hybrid architectures

The MoE contract includes:

```text
router interface
top-k/grouped routing
capacity and token-drop/padding policy
token permutation/unpermutation
all-to-all transport
expert and expert-tensor-parallel mapping
shared experts
load-balancing objectives
aux-loss-free balancing
router z-loss
grouped GEMM
communication overlap
expert checkpoint placement
```

Required telemetry includes expert-load histograms, routing entropy, capacity utilization, dropped/padded tokens, all-to-all bytes and latency, expert compute time, exposed communication, shared-expert overlap, and per-expert gradient/update norms.

Megatron Core may provide routing, dispatch, grouped GEMM, schedules, overlap, or EP capabilities. The task owns routing loss meaning, the planner owns placement, and the logical state registry owns checkpoint semantics.

#### Diffusion and flow models

The platform natively supports:

- discrete timesteps and continuous-time objectives;
- noise, interpolation, and weighting schedules;
- stateless sample-keyed RNG;
- self-conditioning;
- classifier-free guidance dropout;
- EMA as registered durable state;
- SNR or schedule-aware normalization;
- deterministic restart of stochastic objectives;
- sampling-based validation and immutable sample artifacts;
- multiple samplers/solvers;
- structure-specific geometry, alignment, confidence, and validity metrics.

Diffusion and flow training are first-class tasks, not callbacks attached to an LLM loop.

#### Distillation, adapters, sparsity, and quantization-aware training

The phase graph supports:

- teacher/student models and versioned teacher snapshots;
- adapter and LoRA state with distinct logical identities;
- confidence-head-only or module-selective phases;
- structured pruning and sparsity schedules;
- quantization-aware training through qualified provider capabilities;
- model expansion, surgery, and state migration at committed boundaries.

Each phase rebuilds and validates its parameter update graph. A phase transition cannot silently retain stale optimizer state for a different logical parameter set.

#### Reinforcement learning and self-improvement

Post-training follows algorithm/infrastructure separation and may use Monarch for outer coordination:

```text
experiment/algorithm
  -> rollout controller
      -> generator mesh
      -> environment or simulator mesh
      -> reward/rubric mesh
      -> evaluator mesh
      -> policy-trainer mesh
```

Every rollout records:

```text
sample and trajectory identity
environment/simulator version
policy and generator version
reward/rubric version
sampling configuration
input and artifact lineage
actions, trajectory, and log probabilities
advantages, returns, or preference labels
validity and policy flags
```

The staleness contract supports:

```text
max_policy_lag = 0     synchronous on-policy execution
max_policy_lag > 0     bounded asynchronous execution
```

Weight publication is versioned, atomic, and tied to a durable checkpoint or a separately qualified lightweight publication schema. Generators never infer policy version from mutable filenames. Replay and rollout progress are checkpointable.

Monarch is optional and remains inside the admitted Kubernetes workload. It does not replace the Mindclade job record, Kueue quota admission, JobSet grouping, artifact catalog, or GitOps deployment model.

### A14.15 Asynchronous evaluation, callbacks, telemetry, and step capsules

#### Callback contract

Callbacks consume typed events and return typed actions:

```text
RequestCheckpoint
RequestEvaluation
RequestStop
AdjustLoggingCadence
EmitArtifact
MarkRunUnhealthy
```

A callback may observe lifecycle events, but it cannot mutate engine internals, call collectives out of order, publish a checkpoint outside the checkpoint manager, or perform blocking network I/O inside the numerical schedule. Action ordering and delivery state are explicit and checkpointable when they affect run semantics.

#### Asynchronous evaluation snapshots

Large evaluation should not block the trainer unnecessarily.

```text
trainer commits evaluation snapshot
-> immutable EvaluationSnapshotManifest
-> evaluation worker acquires a lease
-> evaluator loads only required logical components
-> report references the exact snapshot, dataset, code, and suite
-> retention cannot delete the snapshot while leased
```

Supported snapshots include:

- full recovery generation;
- EMA-only state;
- selected heads or adapters;
- lightweight inference publication;
- low-frequency sampling state.

Early stopping or promotion based on asynchronous evaluation declares a maximum acceptable staleness. Dashboard state is never release evidence.

#### Telemetry

Core telemetry includes:

```text
run, phase, StepEpoch, optimizer step
samples, tokens, residues, atoms, pair cells, and work units
loss numerators, denominators, normalization bases, and scopes
optimizer, gradient, update, and parameter norms
precision, quantization, and loss-scale state
input throughput, packing efficiency, and starvation
forward/backward/reduction/update timing
collective bytes, latency, and exposed communication
pipeline bubble and recomputation overhead
GPU utilization, memory, fragmentation, and headroom
compile graph breaks, cache hits, and CUDA-graph status
checkpoint snapshot, staging, backlog, commit latency, and failures
provider, schedule, compiled-region, and kernel selections
numerical anomalies and recovery actions
```

Mindclade-specific telemetry includes pair/atom work throughput, triangle-kernel utilization, diffusion timestep/SNR buckets, coordinate/alignment losses, confidence calibration, structure-sampling throughput, MoE balance, and shape-bucket occupancy.

Metrics use bounded-cardinality labels. Run IDs, artifact digests, sample identities, biological payloads, and customer data belong in traces, structured logs, durable event artifacts, or exemplars.

#### Step capsules

Selected steps emit a compact `StepCapsule`:

```text
run, phase, and StepEpoch
BatchReceipt digest set
checkpoint or snapshot generation
RNG derivation roots
recipe, hardware, and executable-plan digests
provider, schedule, compiled-region, and kernel manifests
loss numerator/denominator summaries
gradient/update summaries
environment and toolchain manifest
```

Step capsules support offline reproduction, reference-versus-optimized comparison, incident analysis, and regression fixtures generated from real workloads.

#### Shadow qualification

For selected operations or sampled steps, the optimized path may be compared with a maintained reference path outside the critical schedule:

```text
production optimized result
+ sampled reference execution
-> tolerance and statistical comparison
-> alert, quarantine, or fail-closed policy
```

Shadow execution must be bounded, policy-approved, data-safe, and disabled when it would leak restricted payloads. It is especially valuable for new TileLang kernels, low-precision paths, MoE dispatch, and Pairformer operations.

### A14.16 Compilation and compiled-region artifacts

Compilation is planned and evidenced rather than treated as an incidental runtime optimization.

A `CompiledRegionManifest` records:

```text
model graph and executable-plan digests
region boundaries
input shape guards
dtype and layout constraints
compiler and backend versions
graph breaks and reasons
generated kernel or binary digests
autotune record
hardware compatibility
numerical qualification report
```

Use two lanes:

```text
developer JIT
  rapid iteration, local cache, graph-break diagnostics

production promoted compilation
  qualified regions and binaries, immutable manifests,
  controlled cache population, no surprise critical-path compilation
```

Production recipes declare:

- critical regions expected to compile;
- permitted graph-break budget;
- dynamic-shape/guard policy;
- cache and artifact policy;
- CUDA-graph eligibility;
- fallback behavior.

A plan fails preflight when a required critical region cannot satisfy the declared compilation contract. A graph break may not silently move a numerically or operationally important path to eager execution during a release qualification run.

### A14.17 Systems autotuning and scientific studies

Systems tuning and scientific hyperparameter optimization are separate systems.

#### Systems-plan tuning

Tunes:

```text
microbatch size and accumulation
DP replicate/shard, TP, PP, CP, and EP degrees
pipeline partition, schedule, and virtual stages
activation checkpoint/offload policy
communication overlap
shape and work-unit bucket boundaries
packing policy
compile regions and CUDA-graph eligibility
precision and provider choice
optimizer implementation
prefetch depth
checkpoint staging budget
```

Objective:

```text
maximize useful throughput or minimize cost
subject to memory, numerical, convergence, recovery,
reproducibility, and provider compatibility constraints
```

Result: immutable `AutotuneRecord` and promoted `ExecutablePlan`.

#### Scientific study/HPO

Tunes:

```text
learning rate and optimizer coefficients
objective weights
data mixture and curriculum
architecture dimensions
diffusion schedules
router configuration
regularization
scientific task choices
```

Objective: scientific evaluation quality.

Artifacts are separate:

```text
StudyDefinition
TrialManifest
TrialResult
PromotionDecision
```

A systems plan may be reused across scientifically distinct trials. An HPO trial may not silently rewrite the executable plan or provider set.

Production runs consume frozen promoted records. They do not perform unconstrained adaptive systems tuning or scientific HPO inside an official run.

### A14.18 Recipes, phase graphs, and developer interface

Recipes are typed, validated, versioned configurations. They are not arbitrary YAML bags or embedded provider configuration files.

A recipe references immutable:

- model configuration and logical state schema;
- training dataset manifest;
- task and training phase graph;
- optimization and parameter update policy;
- precision, quantization, and reproducibility policy;
- logical plan request or promoted executable plan;
- checkpoint tiers and recovery policy;
- evaluation suite and staleness policy;
- resource profile and hardware constraints;
- permitted providers and fallbacks;
- compilation and graph-break contract;
- health and anomaly policy;
- observability and debug profile;
- safety and data-classification policy.

Configuration resolution order is:

```text
schema defaults
< named recipe
< approved environment-independent overlay
< explicit operator/debug override
```

The resolved configuration is immutable and content-addressed. Secrets, cluster names, credentials, mutable object-store paths, and live Kubernetes placement are injected by the execution environment and never embedded in recipes.

Recommended CLI:

```bash
mindclade train plan --recipe cladefold.pretrain.h100
mindclade train tune --recipe cladefold.pretrain.h100 --budget quick
mindclade train run --recipe cladefold.pretrain.h100
mindclade train resume --checkpoint artifact://training/.../generation-0042
mindclade train qualify --recipe cladefold.pretrain.h100 --suite production
mindclade train inspect-checkpoint artifact://training/.../generation-0042
mindclade train reproduce-step --capsule artifact://training/.../step-000123
mindclade train convert-checkpoint --from megatron --to mindclade-dcp
```

Debug profiles are layered on the same trainer:

```text
fast_dev_run
single_batch_overfit
single_optimizer_step
deterministic_reference
virtual_mesh
anomaly_detection
memory_snapshot
distributed_flight_recorder
compile_explain
kernel_parity
recovery_point_drill
batch_invariance
microbatch_invariance
step_capsule
```

### A14.19 Resilience and elasticity

The default recovery model is fail-stop restart from the latest valid recovery point. Checkpoint-and-restart elasticity is preferred over mutating a live distributed program.

The resilience layer handles:

- preemption and termination signals;
- quiesce and checkpoint deadlines;
- rank/process/node failure classification;
- retryable versus terminal failure policy;
- worker-attempt fencing;
- node replacement and topology-changing restore;
- fault-tolerance integration where qualified;
- distributed flight-recorder collection;
- duplicate job delivery;
- partial artifact cleanup;
- recovery drills and failure injection.

A supported capacity change follows:

```text
failure or planned resize
-> restore verified checkpoint
-> discover new hardware topology
-> compile new executable plan
-> reshard through DCP
-> validate reproducibility contract
-> resume with explicit lineage
```

Changing only data-parallel degrees is the first supported elasticity target. TP, PP, CP, EP, batch semantics, precision, provider selection, optimizer ownership, or phase changes require an explicitly qualified replan and a new executable-plan digest.

Automatic in-run replanning is deferred until its state, data, numerical, and lineage semantics are proven.

### A14.20 Qualification gates

A capability exists only after passing the required Mindclade gates.

#### Q0 — contracts and CPU

- dependency and ownership laws;
- task, phase graph, loss, update-graph, and state-schema invariants;
- stable logical state identity and migration fixtures;
- deterministic data order, BatchReceipts, and RNG hierarchy;
- CPU forward/gradient tests;
- recipe and manifest validation;
- checkpoint unit and mixed-epoch rejection tests.

#### Q1 — single-GPU numerics

- eager reference versus compiled/provider execution;
- forward, gradient, and optimizer-update parity;
- BF16/low-precision comparison against FP32 reference;
- microbatch and normalization equivalence;
- declared durable recovery-point resume;
- step-capsule reproduction;
- memory-leak and anomaly tests.

#### Q2 — single-node distributed

- DDP, FSDP2, TP, PP, CP, and EP where applicable;
- process-group inventory and collective ordering;
- uneven and empty shards;
- accumulation and data-parallel equivalence;
- topology-changing supported restore;
- pipeline schedule correctness;
- process termination and restart.

#### Q3 — multi-node recovery

- node/rank loss, timeout, and preemption;
- snapshot-epoch consistency under asynchronous save;
- recovery and durable checkpoint tiers;
- corrupt, incomplete, and mixed-epoch rejection;
- data duplicate/skip detection from BatchReceipts;
- worker-attempt fencing;
- supported topology changes at restore.

#### Q4 — provider and compiled-region qualification

For every Megatron Core, DeepSpeed, Transformer Engine, TorchAO, TileLang, TorchTitan-compatibility, Fabric, Monarch, or compiler path:

- contract compatibility;
- logical state mapping and migration;
- forward, gradient, normalization, and update parity;
- checkpoint and conversion parity;
- compile and distributed-layout compatibility;
- reproducibility behavior where claimed;
- memory and throughput regression gates;
- shadow-qualification results where required;
- explicit failure behavior;
- license and supply-chain review.

#### Q5 — long-horizon model qualification

- training and validation curves;
- downstream evaluation suites;
- diffusion/flow sample quality;
- structure and geometry metrics;
- confidence calibration;
- MoE router stability;
- phase-transition correctness;
- reproducibility across restarts;
- no statistically material regression from provider, kernel, precision, or compilation substitutions.

#### Q6 — production scale

- sustained multi-node execution;
- input-pipeline saturation and work-unit efficiency;
- checkpoint/recovery drills;
- memory fragmentation and headroom;
- communication overlap and utilization;
- asynchronous evaluation and lease behavior;
- operational dashboards, alerts, and runbooks;
- clean-checkout image and artifact provenance;
- cost and capacity evidence.

Numerical goldens are never updated merely because a test failed. Every baseline change requires evidence, an owner, a rationale, and a review date.

### A14.21 Dependency and release lanes

Maintain stable and edge lanes within one controlled lock universe.

#### Stable production lane

- exact PyTorch, CUDA/ROCm, collective libraries, compiler, Megatron Core, DeepSpeed, Lightning, Monarch, Transformer Engine, TorchAO, TileLang, and related versions as applicable;
- pinned through `uv.lock`, Nix, Bazel, and OCI image digests;
- prebuilt and qualified provider, kernel, and compiled-region artifacts;
- no runtime package installation;
- no surprise JIT compilation in critical production regions;
- signed provenance, SBOM, capability manifest, and qualification evidence.

#### Edge intake lane

- PyTorch development revisions and TorchTitan feature tracking;
- new Megatron schedules, generalized parallelism, MoE, and overlap paths;
- new Transformer Engine precision formats;
- new TorchAO quantization and sparsity paths;
- new compiler and kernel-authoring backends;
- TorchForge and Monarch integration changes;
- experimental DeepSpeed offload and reduction capabilities.

Promotion path:

```text
upstream experiment
-> Mindclade capability adapter
-> logical state and contract mapping
-> numerical and recovery qualification
-> performance and scale qualification
-> frozen capability and compiled artifacts
-> stable dependency promotion
```

### A14.22 Capability-local qualification progression

#### Milestone 0 — freeze correctness contracts

Implement the following contracts under foundational ADR-0007 (and ADR-0005 for dataset/sample identity). Do not create one ADR per type; a separate record is required only when a new decision changes a frozen invariant or reaches a just-in-time gate:

```text
TrainingTask and ObjectiveBundle
LossTerm and ReductionScope
TrainingPhaseGraph
LogicalStateId and StateSchemaEntry
TrainingStateRegistry
ParameterUpdateGraph
CompiledStepProgram
StepEpoch, SnapshotEpoch, and DurableRecoveryPoint
TrainingDatasetManifest and BatchReceipt
ExecutablePlan and transformation-pass graph
ReproducibilityPolicy
```

Exit criterion: contracts are tested on CPU and cannot be bypassed by provider code.

#### Milestone 1 — one complete vertical slice

Support:

```text
single process and one GPU
FP32 reference and BF16
AdamW and one scheduler
the exact SQP-001 CladeFold-Q0 model and dataset profile from Section 15.3.1
one supervised structure head and one 20-step coordinate-diffusion head
numerator/denominator loss reduction
deterministic data progress and BatchReceipts
local recovery checkpoint
object-store durable checkpoint
one evaluation suite
step capsule and structured local events
```

Exit criterion: one complete run, failure, restore, evaluation, and artifact lineage path works from a clean checkout.

#### Milestone 2 — native distributed correctness

Add:

```text
DDP and FSDP2/HSDP
DeviceMesh/DTensor
meta initialization
activation checkpointing
DCP resharding
data-parallel topology-changing restore
distributed reduction equivalence
virtual-mesh planning tests
multi-node failure injection
```

Exit criterion: native distributed correctness and recovery are qualified before advanced providers.

#### Milestone 3 — profiling and first measured optimization

Add:

```text
representative profiling and a ranked bottleneck report
one frozen operation or provider capability contract
maintained reference behavior and predeclared benefit threshold
the smallest candidate implementation selected by evidence
state, checkpoint, recovery, precision, and artifact mapping
shadow qualification, fallback, revocation, and envelope-specific promotion
```

Exit criterion: no optimized path is promoted without state mapping, parity, recovery, and performance evidence.

#### Milestone 4 — model-required multidimensional parallelism

Add only as real CladeFold configurations require:

```text
TP
Pairformer pair-axis sharding
CP
PP and schedule registry
EP/MoE
communication overlap
topology-aware collective planning
```

Exit criterion: each dimension has independent conformance tests and a supported checkpoint migration path.

#### Milestone 5 — memory and systems optimization

Add:

```text
work-unit batch planner
memory and cost model
systems autotuning
activation offload
CPU optimizer-state offload
recovery/durable checkpoint tier optimization
preemption-aware checkpoint policy
```

NVMe model-state offload is added only after measured memory or cost requirements justify it.

#### Milestone 6 — post-training and multi-role orchestration

Then add:

```text
distillation and adapter phases
QAT and sparsity phases
rollout and replay contracts
policy versioning and weight publication
TorchForge-compatible algorithms
Monarch actor meshes
generator, environment, reward, and evaluator workers
bounded policy staleness
```

Exit criterion: trainer and generator roles scale independently while preserving policy-version, rollout, checkpoint, and job consistency.

### A14.23 Definition of done for the first production release

The first production release is complete only when all of these hold:

1. One global batch and an equivalent accumulated-microbatch execution produce equivalent updates under the declared tolerance.
2. Loss normalization remains equivalent across supported packing and data-parallel layouts.
3. Checkpoint restore produces no skipped or duplicated sample identities.
4. A checkpoint created under one supported data-parallel topology restores under another.
5. Corrupt, incomplete, or mixed-epoch checkpoints are rejected.
6. Logical state identity survives FSDP wrapping and at least one provider replacement.
7. Provider, schedule, collective, kernel, precision, and compiled-region choices are frozen in the executable-plan manifest.
8. Asynchronous checkpointing cannot mix state epochs.
9. Reference and optimized paths pass forward, gradient, update, recovery, and long-horizon qualification.
10. A sampled production step can be reconstructed from a step capsule without logging raw biological payloads.
11. A failed worker attempt cannot publish a partial result or advance durable job state incorrectly.
12. An evaluation report names the exact checkpoint/snapshot, dataset, code, suite, plan, and provider digests.
13. The complete training-worker image builds and runs from a clean checkout in authoritative CI.
14. The same immutable release artifact is promoted without rebuilding.
15. Loss of a non-critical telemetry backend does not stop training; local durable events remain available.
16. No model, task, or recipe imports a provider-owned trainer or global control API.
17. A phase transition rebuilds and validates parameter ownership and checkpoint compatibility.
18. Recovery drills and operator runbooks pass on the production workload class.

### A14.24 Final training invariants

- one Mindclade trainer lifecycle owns every run;
- one compiled step program owns each frozen distributed forward/backward schedule;
- one executable plan owns every process group, placement, provider, transformation, and compiled region;
- one logical state identity scheme names every recoverable component;
- one parameter update graph owns update responsibility per phase;
- one numerator/denominator reduction contract defines every objective term;
- one committed `StepEpoch` binds optimizer state and data progress;
- one DCP-based logical checkpoint schema is canonical;
- only verified durable recovery points are advertised as resumable;
- one immutable recipe and run manifest explain what executed;
- providers are narrow, qualified, replaceable, and fail-closed;
- model mathematics remains independent of engines and orchestration;
- the Go control plane and Kubernetes remain the durable job/admission plane;
- Monarch, when used, is outer role orchestration rather than the numerical engine;
- systems autotuning and scientific HPO remain separate;
- optimized execution is never promoted without reference, recovery, long-horizon, performance, and provenance evidence.
