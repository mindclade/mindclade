## Appendix A13 — Model architecture

### A13.1 Model packages are pure execution units

A model package owns:

- typed configuration;
- module graph and forward contracts;
- initialization;
- stable logical state schema and migration keys;
- semantic tensor axes such as sequence, pair, MSA, atom, sample, recycle, expert, and modality;
- logical parameter roles and tags used by update, precision, and placement policy;
- checkpoint conversion at the model-schema boundary;
- supported task capabilities;
- feature requirements;
- output semantics;
- maintained reference execution paths;
- numerical qualification fixtures;
- model card metadata;
- provider-neutral sharding, precision, compilation, and kernel capability hints.

It does not own:

- cluster launch;
- experiment database writes;
- queue consumption;
- HTTP handlers;
- environment-specific storage credentials;
- process-group creation;
- provider selection;
- pipeline schedule selection;
- optimizer stepping;
- checkpoint publication.

A model package may describe what transformations are mathematically valid. The training executable-plan compiler decides whether and how to apply them on a particular topology.

### A13.2 Model component boundaries

Keep reusable model components under `models/components/` only after at least two real model consumers exist. Otherwise, keep the component inside the model family to avoid speculative abstraction.

Likely shared components include:

- token and geometric embeddings;
- Pairformer-style blocks;
- diffusion and flow modules;
- confidence heads;
- geometric transforms;
- mixture-of-experts layers;
- output heads and loss primitives.

Kernel-backed components retain a correct framework reference path. Provider-backed components expose stable logical state and semantic metadata independent of the provider implementation.

### A13.3 Model state and transformation contract

A model family publishes:

```text
logical state schema
semantic axis schema
parameter role/tag schema
supported transformation capabilities
state migration registry
reference module graph digest
```

The logical schema is stable across qualified wrappers, sharding layouts, pipeline partitions, and provider replacements. Python fully qualified names may be recorded for diagnostics, but they are not the durable checkpoint identity.

A transformation capability states preconditions and effects, for example:

```text
supports tensor-parallel column split on projection X
supports pair-row or pair-column placement on block Y
requires replication of geometry update Z
permits provider replacement of attention operation A
forbids low precision for normalization/statistics path B
```

### A13.4 Model bundle

A released model bundle contains or references:

- immutable weight shards;
- typed model configuration;
- model family and version;
- logical state/checkpoint schema version and digest;
- semantic axis and parameter-role schema;
- `FeatureRequirementSetRef` for reusable semantic inputs;
- `ModelFeatureViewRef` plus model input contract for architecture-specific representation;
- tokenizer/vocabulary/chemical component versions;
- precision and hardware compatibility;
- qualified provider and kernel signatures;
- optional compiled-region compatibility manifests;
- code revision and build provenance;
- evaluation report digest;
- safety policy metadata;
- license and distribution policy;
- model card.

No serving worker should infer these values from filenames or Python module paths.

### A13.5 Model-system planes

A model family is split into:

```text
semantic API and configuration
→ reference mathematical graph
→ logical state and capability description
→ optimized/provider realizations selected externally
→ model bundle and qualification evidence
```

The reference graph is the semantic oracle. It need not be the fastest implementation, but it must remain maintained for supported model sizes or reduced fixtures. Optimized implementations may change physical modules and layouts while preserving declared semantics and logical state.

### A13.6 Core model API

A provider-neutral API may take this form:

```python
from dataclasses import dataclass
from typing import Generic, Mapping, Protocol, TypeVar
from torch import Tensor, nn

BatchT = TypeVar("BatchT")
OutputT = TypeVar("OutputT")

@dataclass(frozen=True, slots=True)
class ModelBuildContext:
    initialization: "InitializationPolicy"
    device: "DeviceIntent"
    precision_intent: "ModelPrecisionIntent"
    state_schema_version: int
    feature_requirements: "FeatureRequirementSetRef"
    model_feature_view: "ModelFeatureViewRef"
    input_contract: "ModelInputContractRef"

class MindcladeModel(nn.Module, Generic[BatchT, OutputT]):
    config: "ModelConfig"

    def forward(self, batch: BatchT, *, context: "ModelContext") -> OutputT: ...
    def logical_state_schema(self) -> "LogicalStateSchema": ...
    def capabilities(self) -> "ModelCapabilities": ...
```

The stable contract is semantic; exact Python inheritance may evolve. A model does not receive cluster credentials, provider globals, job clients, experiment stores, or checkpoint managers.

### A13.7 Typed configuration

Every model configuration is:

- immutable after construction;
- schema-versioned;
- fully validated before allocation;
- serializable to a canonical manifest;
- explicit about defaults;
- independent of runtime topology and environment;
- capable of migration from supported historical versions.

Validation covers dimensions, divisibility, modality/component compatibility, parameter sharing, attention/head structure, Pairformer geometry, diffusion schedules, MoE expert constraints, vocabulary/component versions, and output head requirements.

Derived values are computed deterministically and either recorded in the resolved configuration or reproducible from it. Environment variables and provider config do not alter model meaning.

### A13.8 Batch contract

A model batch is a typed structure with:

```text
features and masks
semantic axes
shape metadata
sample identities or safe references
coordinate units/frames where applicable
model input contract/version and model-feature-view digest
resolved semantic feature bundle/reference
optional modality presence
packing/unpacking metadata
```

A batch validates dtype, rank, axis meaning, index bounds, masks, and consistency before expensive execution in debug/qualification profiles. Production paths may use compiled validation summaries, but they cannot rely on undocumented tensor-position conventions.

### A13.9 Output contract

Outputs are typed and distinguish:

- primary predictions;
- intermediate representations intentionally exposed;
- confidence/uncertainty values;
- logits/probabilities and calibration semantics;
- geometry/coordinate frames;
- auxiliary state needed by objectives;
- deferred large artifacts;
- diagnostics.

Training objectives and inference postprocessing consume public output fields, not arbitrary hooks into module internals. Internal activations become public only with a compatibility and memory contract.

### A13.10 Semantic axis schema

Every tensor exposed across model, training, inference, kernel, or checkpoint boundaries carries semantic axes such as:

```text
batch
sequence
msa
pair_i
pair_j
atom
sample
template
recycle
expert
modality
channel
head
```

Axis metadata defines size expression, ragged/packed behavior, valid sharding capabilities, masking, and coordinate/unit semantics. Physical layout may differ, but conversion is explicit and plan-owned.

### A13.11 Parameter roles and tags

Logical parameters are tagged by semantic role:

```text
embedding
attention_projection
pair_projection
geometry_update
normalization_scale
output_head
confidence_head
router
expert
adapter
teacher_only
frozen_reference
```

Tags drive initialization, optimizer groups, weight decay, precision restrictions, sharding hints, checkpoint selection, and release packaging. Tag assignment is deterministic and validated; string-name pattern matching is not the durable policy.

### A13.12 Initialization contract

Initialization is a registered, versioned policy based on logical role and shape. It defines:

- distribution and scale;
- fan-in/fan-out semantics;
- residual-depth scaling;
- zero or identity initialization;
- tied/shared parameter handling;
- expert initialization;
- deterministic RNG stream;
- meta-device materialization behavior;
- checkpoint-overrides-initialization order.

Initialization tests compare moments, exact deterministic fixtures where appropriate, and invariants for tied/shared state.

### A13.13 Shared model component contract

A component becomes shared only after stable common behavior appears in multiple model families. Shared components expose:

```text
mathematical contract
input/output and state schema
semantic axes
reference implementation
capability hints
numerical fixtures
migration policy
```

A component must not expose training engine or provider objects. Leaf operation replacement occurs through kernel/provider registries and executable-plan transformations.

### A13.14 Feature requirement and model-view contract

A model family publishes a machine-readable `FeatureRequirementSetRef` that references `bio/featurization/` semantic contracts rather than data-pipeline files or cache locations:

```text
semantic FeatureContract IDs and compatible versions
required and optional feature roles
shape/ragged and biological constraints
vocabulary/component dictionary versions
normalization assumptions
coordinate units/frames
mask and missingness semantics
model-aware cost features
model-feature-view contract/version/digest
model input contract
packing compatibility
```

The model family separately owns deterministic `ModelFeatureView`s that transform verified reusable semantic features into architecture-specific representation. Examples include bucketization, categorical embedding indices, model-specific pair channels, concatenation, PyTorch tensorization, dtype/layout conversion required by model mathematics, and deterministic packing metadata. A model view may produce a durable model-input artifact only when it is sufficiently expensive, deterministic, and versioned; its key includes the model feature-view contract/release compatibility. Cheap tensorization and device/layout views remain runtime-only.

A model MUST NOT redefine a shared semantic feature merely to obtain a preferred physical shape. Conversely, a representation whose scientific meaning is genuinely architecture-specific belongs to the model family and must not be promoted into `bio/` merely to increase cache reuse.

Loading incompatible features fails before model execution. Compatibility adapters are explicit versioned derivations with lineage, not implicit casts, default filling, or shape reinterpretation in `forward()`.

### A13.15 Logical state schema

The model owns stable identities for:

- parameters;
- persistent buffers;
- non-parameter model state;
- tied/shared relationships;
- optional heads/adapters;
- quantization/calibration state at the model boundary;
- migration aliases.

State entries include semantic shape expressions and axes, not only realized shapes. A state schema digest changes when durable identity or interpretation changes, even if physical tensor bytes happen to match.

### A13.16 Tied, shared, and derived state

The schema distinguishes:

- one logical tensor referenced by multiple modules;
- separate tensors initialized equally;
- derived state that can be reconstructed;
- cached state excluded from checkpoints;
- externally supplied frozen state;
- teacher/student or adapter relationships.

Checkpoint and optimizer systems must not duplicate tied state or assign conflicting update ownership.

### A13.17 State migration and model surgery

A migration is a typed graph from source schema to target schema. Operations may include:

```text
rename logical identity
split or concatenate tensor
transpose or reshape with semantic proof
initialize new state
remove state with explicit loss
expand vocabulary/components
insert adapters or experts
convert normalization or parameterization
```

Every operation records preconditions, reversibility, numerical implications, and validation. Lossy migration requires explicit approval and lineage. Model surgery occurs at a committed boundary, never invisibly during resume.

### A13.18 Provider-neutral capability hints

Models may declare mathematically valid capabilities:

- tensor-parallel split axes;
- sequence/context sharding;
- pair-row/pair-column placement;
- pipeline cut candidates and forbidden cuts;
- expert ownership and routing structure;
- activation recomputation boundaries;
- precision-sensitive operations;
- compile-region candidates;
- replaceable leaf operations;
- CUDA-graph/static-shape constraints.

Hints are not commands. The planner validates them against topology, task, provider, and reproducibility policy.

### A13.19 Precision semantics

The model declares numerical sensitivity by operation or role:

```text
minimum compute dtype
minimum accumulation dtype
parameter/storage constraints
allowed low-precision formats
required scaling/calibration state
fallback tolerance
reference comparison profile
```

Geometry transforms, coordinate updates, diffusion schedules, normalization statistics, logits/confidence calibration, and reductions may require stronger precision than projection layers. Model code does not silently cast based on hardware.

### A13.20 Kernel and provider dispatch boundary

Reference modules call stable operation interfaces. During plan preparation, qualified leaf operations may be replaced or dispatched based on exact signature and capability.

The model bundle records which provider/kernel sets are qualified, but a model does not import a provider-owned trainer or global registry. An unsupported implementation falls back only according to the executable plan and workload policy.

### A13.21 Compilation contract

A model family declares:

- graph regions intended to be compilable;
- dynamic dimensions and shape families;
- mutation and side-effect boundaries;
- custom operation schemas;
- graph-break-sensitive paths;
- deterministic/reference mode;
- export/AOT constraints.

Compilation cannot change output semantics, state identity, RNG derivation, or aliasing without explicit qualification. Compiled binaries remain external artifacts keyed by graph, plan, shapes, dtypes, hardware, and compiler.

### A13.22 Model registry

The registry maps stable family/version/capability identifiers to:

```text
configuration schema
builder and reference implementation
logical state schema and migrations
feature requirements
supported tasks
bundle loaders/converters
qualification reports
model card and policy metadata
```

Registry entries are explicit and import-safe. Discovery does not execute arbitrary plugin code or scan mutable Python entrypoints in production.

### A13.23 Checkpoint conversion boundary

Converters translate external/provider state into logical model state. A converter declares:

- source format/version;
- target family/schema;
- exact mapping rules;
- ignored, synthesized, or lossy state;
- tensor transforms;
- numerical verification;
- source license/distribution constraints;
- resulting lineage.

A conversion is not accepted because all keys loaded. It must prove logical coverage and model-output equivalence within the declared profile.

### A13.24 Model bundle loading

Loading a model bundle follows:

```text
verify manifest, digest, signature, and policy
→ validate code/model/schema compatibility
→ validate feature, vocabulary, and component versions
→ select supported precision/provider/kernel profile
→ construct on meta or target device
→ load/reshard logical state
→ run integrity and smoke checks
→ expose immutable loaded-model identity
```

Mutable aliases resolve before loading. A worker never guesses family, dimensions, or tokenizer/component versions from filenames.

### A13.25 Model release qualification

#### MQ0 — contracts

Configuration, batch/output, feature, state, axis, and role schemas pass.

#### MQ1 — reference numerics

Forward, backward where applicable, initialization, serialization, and deterministic fixtures pass.

#### MQ2 — state and conversion

Checkpoint round trip, migration, provider replacement, and external conversion pass.

#### MQ3 — distributed/compiled realization

Supported sharding, pipeline cuts, precision, kernels, and compilation preserve semantics.

#### MQ4 — model-family evaluation

End-to-end task, robustness, confidence, safety, and long-horizon training evidence pass.

#### MQ5 — release bundle

Clean-checkout bundle creation, signature/provenance, load/inference smoke, compatibility matrix, and model card pass.

### A13.26 Security and biological governance

A model package and bundle declare:

- permitted data classifications and tasks;
- training/evaluation lineage references;
- distribution and export policy;
- safety evaluation requirements;
- generated-output classification rules;
- restricted components or weights;
- logging and diagnostic redaction;
- known limitations and misuse considerations.

Model code never embeds secrets, customer data, or restricted examples.

### A13.27 Capability-local qualification progression

1. Freeze model API, configuration, semantic axes, roles, feature, and logical state contracts.
2. Implement a small CladeFold reference family with deterministic fixtures.
3. Implement bundle/checkpoint conversion and state migration.
4. Add planner capability hints, kernel dispatch, and compilation contracts.
5. Qualify distributed, low-precision, and optimized paths.
6. Publish complete model bundles, model cards, and release evidence.

### A13.28 Definition of done

1. Model mathematics runs independently of trainer, worker, service, and provider control planes.
2. Configuration, batches, outputs, axes, roles, and feature requirements are typed and versioned.
3. Logical state survives wrapping, sharding, compilation, and provider replacement.
4. Reference implementations remain maintained for every promoted optimized path.
5. State migration and conversion are explicit, tested, and lineage-preserving.
6. Model bundles are self-describing and never rely on filenames or Python paths.
7. Precision, sharding, compilation, and kernel capabilities are hints consumed by a frozen plan.
8. Release requires numerical, evaluation, safety, compatibility, and provenance evidence.
