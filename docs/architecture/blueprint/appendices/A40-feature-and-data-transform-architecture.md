## Appendix A40 — Feature and data transform architecture

### A40.1 Executive decision

Mindclade SHALL treat transforms as typed, versioned, receipt-producing dataflow operations with explicit semantic ownership.

The architecture distinguishes:

```text
source/canonical data transforms
        ↓
dataset transforms
        ↓
reusable semantic feature transforms
        ↓
model-specific deterministic transforms/views
        ↓
runtime batch/request transforms
```

The transform system is **not** a new workflow engine, feature store, dataframe framework, model API, or scheduler. It supplies contracts for composition, deterministic execution, lineage, validation, and backend replacement while each domain continues to own meaning.

### A40.2 Why transforms are distinct from feature derivation

Appendix A39 defines semantic feature identity, derivation, materialization, and cache reuse. Appendix A40 generalizes the operation boundary around transformations that may or may not create cached features.

Examples that are transforms but not reusable semantic feature derivations include:

- record projection and schema migration;
- normalization and canonicalization;
- filtering/curation;
- deduplication and cluster assignment;
- deterministic split assignment;
- sampling and sharding;
- joins and aggregate statistics;
- model-specific bucketization/tensor views;
- stochastic crop/mask/noise operations at training time.

Therefore:

```text
FeatureDerivation ⊂ Transform
```

but a transform becomes an Appendix A39 feature derivation only when it produces a reusable semantic `FeatureContract` value.

### A40.3 Transform ownership matrix

| Transform class | Semantic owner | Composition/execution owner | Typical durability |
|---|---|---|---|
| source-faithful decode/parse-adjacent | `bio/formats/` and ingestion owner | worker/composition root | raw/parsed artifact |
| biological normalization | `bio/` semantics + `data/normalization/` policy | `data/transforms/` executor | durable normalized artifact |
| curation/filter | `data/curation/` | `data/transforms/` executor | durable when part of dataset release |
| deduplication/leakage/split/sample | owning `data/*` package | `data/transforms/` executor | durable receipt/manifest; outputs by policy |
| reusable semantic feature | `bio/featurization/` | `data/featurization/` + feature worker | usually durable/cacheable |
| model-specific deterministic feature/view | model family | model package/runtime | durable only if expensive and justified |
| training batch transform | `training/core/data/` or task | training worker | normally ephemeral |
| inference request transform | `inference/` | inference worker | normally ephemeral/request-scoped |

`data/transforms/` owns **how transforms are declared, composed, validated, executed, and evidenced**. It does not own the domain rule that decides what a valid residue, split, curation filter, feature, or model view means.

### A40.4 Canonical transform identities

Use distinct identities:

```text
TransformId
TransformSemanticVersion
TransformImplementationDigest
TransformEquivalenceQualificationDigest
TransformSpecDigest
TransformGraphDigest
TransformSemanticKey
TransformExecutionPlanDigest
TransformReceiptDigest
FitSemanticKey
TransformStateArtifactDigest
FitReceiptDigest
LineageMapArtifactDigest
```

`TransformId` names semantic behavior, for example:

```text
data.normalize.structure@3
 data.curate.resolution_filter@2
 data.split.sequence_cluster@4
 bio.feature.relative_residue_geometry@2
 model.cladefold.bucket_relative_position@3
 training.crop.contiguous_residue_window@2
```

Model or backend names may appear only when they are truly part of semantics.

#### A40.4.1 Catalog and implementation-registry terminology

Mindclade uses `catalog` for declarative semantic inventories and `registry` only for qualified executable implementations:

```text
FeatureCatalog
    versioned reusable FeatureContracts

TransformCatalog
    versioned TransformSpecs and typed profiles

ImplementationRegistry
    qualified Python/Rust/future-backend implementations for a semantic contract

ArtifactCatalog
    committed immutable artifact/manifests, policy, lineage, retention, releases
```

`FeatureCatalog` and `TransformCatalog` are deterministic, build-visible declarations owned by their semantic domains. They are not runtime plugin systems. `ImplementationRegistry` may resolve among explicitly built and qualified implementations but cannot define new semantics. `ArtifactCatalog` remains the ordinary durable artifact/catalog authority.

### A40.5 TransformSpec

A durable transform definition uses a small common base plus a typed profile. Authoring APIs provide conservative defaults for ordinary pure one-to-one transforms, while canonical serialization expands every default so identity and review remain explicit:

```python
@dataclass(frozen=True)
class TransformBehavior:
    cardinality: Cardinality = Cardinality.ONE_TO_ONE
    ordering: OrderingSemantics = OrderingSemantics.PRESERVE_INPUT_ORDER
    state_scope: StateScope = StateScope.STATELESS
    materialization: MaterializationPolicy = MaterializationPolicy.EPHEMERAL

@dataclass(frozen=True)
class TransformSpec:
    transform_id: str
    semantic_version: str
    input_contracts: tuple[SchemaRef, ...]
    output_contracts: tuple[SchemaRef, ...]
    profile: TransformProfile
    behavior: TransformBehavior
    determinism: DeterminismClass
    side_effects: SideEffectPolicy
    parameter_schema: SchemaRef
    required_snapshots: tuple[SnapshotRequirement, ...]
    data_classification_rule: str
```

A profile may restrict or require behavior fields more strongly than the defaults. The **resolved** canonical spec always contains explicit cardinality, ordering, state scope, and materialization values before digesting, planning, or execution. A spec MUST define enough behavior that a reviewer can understand what constitutes the same transform independently of the current Python/Rust/future backend implementation.

#### A40.5.1 Typed transform profiles

The serialized `TransformSpec` is a discriminated union with a small common base and class-specific profiles. This prevents simple transforms from carrying irrelevant configuration while making high-risk semantics mandatory where needed. Initial profiles are:

```text
MapTransformSpec
FilterTransformSpec
ExplodeTransformSpec
JoinTransformSpec
AggregateTransformSpec
FittedTransformSpec
SemanticFeatureTransformSpec
RuntimeStochasticTransformSpec
```

The common base owns `transform_id`, semantic version, input/output contracts, determinism, side-effect policy, parameter schema, classification propagation, and implementation qualification requirements. Profiles add only relevant fields: for example `JoinTransformSpec` requires key/multiplicity/fan-out semantics; `AggregateTransformSpec` requires reduction/precision/completeness semantics; `FittedTransformSpec` requires fit/apply contracts and state schema; `RuntimeStochasticTransformSpec` requires logical RNG/replay semantics. JSON Schema uses a discriminator plus `oneOf`, and unknown production profiles fail closed.

### A40.6 Cardinality contract

Every transform declares one of:

```text
ONE_TO_ONE
ZERO_OR_ONE
ONE_TO_MANY
MANY_TO_ONE
MANY_TO_MANY
DATASET_GLOBAL
```

Cardinality is part of correctness, lineage, and optimization.

Examples:

- normalization: usually `ONE_TO_ONE`;
- filter: `ZERO_OR_ONE`;
- assembly expansion: `ONE_TO_MANY`;
- aggregate statistics: `MANY_TO_ONE`;
- join: `MANY_TO_MANY` or a stricter declared subtype;
- split/shuffle/repartition: `DATASET_GLOBAL` with stable membership semantics.

A backend optimization may not change cardinality or duplicate/drop records outside the declared contract.

### A40.7 Ordering semantics

Transforms declare whether ordering is:

```text
PRESERVE_INPUT_ORDER
CANONICAL_KEY_ORDER
PARTITION_STABLE_ORDER
SET_SEMANTICS
ORDER_UNDEFINED
```

`ORDER_UNDEFINED` is permitted only when downstream meaning truly ignores order. Training sample order, batch order, and deterministic publication order must never depend on accidental executor completion order.

Sorting requires an explicit stable key and tie-breaker. Locale, process hash randomization, filesystem order, map iteration, and object-store listing order are prohibited implicit ordering authorities.

### A40.8 State scope

A transform declares:

```text
STATELESS
PARTITION_LOCAL_STATE
DATASET_GLOBAL_STATE
EXTERNAL_SNAPSHOT_STATE
RUNTIME_LOGICAL_STATE
```

State must be explicit because it changes retry, determinism, partitioning, and cache identity.

Examples:

- residue encoding: `STATELESS`;
- per-shard streaming compression statistics: `PARTITION_LOCAL_STATE`;
- global deduplication index: `DATASET_GLOBAL_STATE`;
- MSA/template retrieval: `EXTERNAL_SNAPSHOT_STATE`;
- training crop/noise: `RUNTIME_LOGICAL_STATE` through logical RNG.

#### A40.8.1 Fitted transform state artifacts

Transforms that derive reusable state from a dataset use an explicit two-stage contract:

```text
fit(FitInputSnapshot, FitParameters)
    ↓
TransformStateArtifact
    ↓
apply(TransformStateArtifact, input)
```

`TransformStateArtifact` is immutable, content-addressed, schema-versioned, policy-classified, and lineage-linked to the exact fitting dataset/snapshot. Typical state includes normalization statistics, vocabularies, calibration/quantization parameters, learned projections, clustering centroids, fitted thresholds, and other data-derived parameters.

`FitSemanticKey` includes the `FittedTransformSpec`, exact fitting inputs/cohort, semantic fit parameters, permitted external snapshots, implementation/equivalence identity, and seeded RNG identity where declared. `FitReceipt` records fitting membership/scope, exclusions, state artifact digest, validation, implementation, and leakage evidence. `apply` includes the immutable state artifact reference in `TransformSemanticKey`. Re-fitting creates a new state artifact; state is never overwritten in place.

Evaluation and protected-set execution MUST verify that every fitted-state artifact was learned only from a policy-permitted cohort/snapshot. Unknown or overly broad fitting scope fails closed rather than being treated as a benign preprocessing detail.

### A40.9 Determinism classes

The transform contract reuses the feature determinism model and extends it to dataset operations:

```text
PURE
SNAPSHOT_DEPENDENT
SEEDED
RUNTIME_STOCHASTIC
NONDETERMINISTIC_PROHIBITED
```

Production release transforms MUST be `PURE`, `SNAPSHOT_DEPENDENT`, or explicitly `SEEDED`. `RUNTIME_STOCHASTIC` is valid for training/inference transforms with receipt-replay semantics. Uncontrolled nondeterminism is prohibited for any transform whose output participates in dataset/model/release evidence.

### A40.10 Transform semantic key and execution-plan identity

For deterministic or seeded semantics, compute a backend-independent `TransformSemanticKey`:

```text
TransformSemanticKey = hash(canonical_encode(
    TransformSpecDigest,
    input artifact/record identities,
    semantic parameters,
    required snapshot identities,
    semantic-equivalence qualification identity
        # exact implementation digest only when it is the unqualified singleton class,
    TransformStateArtifact reference when fitted,
    partition/order context only when explicitly semantic,
    logical RNG identity only when SEEDED semantics require it
))
```

Execution planning is distinct:

```text
TransformExecutionPlanDigest = hash(canonical_encode(
    TransformGraphDigest,
    selected implementation/backend identities,
    partition plan,
    worker parallelism/resource envelope,
    fusion/vectorization/projection rules,
    spill and scratch policy,
    physical materialization placement
))
```

The semantic key contains an **equivalence-class identity**, not an arbitrary executor choice. Before an implementation has qualified equivalence with another implementation, its exact implementation/build digest is treated as a singleton equivalence class; after qualification, implementations may share the approved equivalence-class digest. The exact selected executable still appears in `TransformExecutionPlanDigest` and the receipt. This prevents an unqualified code change from silently reusing old results while allowing Python, Rust, or a future backend to share semantic identity after explicit parity evidence.

Changing backend, worker count, ordinary partition count, fusion, spill, or materialization placement MUST NOT change `TransformSemanticKey` when the transform claims execution-independent semantics. If one of those choices genuinely changes meaning, the `TransformSpec` must explicitly classify the dimension as semantic and it then participates in the key. Wall clock, hostname, worker PID, ephemeral object path, or scheduler placement are never accidental semantic identity.

### A40.11 TransformReceipt

Every persisted or qualification-significant invocation emits a receipt containing:

```text
TransformSpecDigest
TransformSemanticKey
TransformExecutionPlanDigest
TransformGraphDigest / node identity
input artifact/record/sample identities
output artifact/record/sample identities
semantic parameters digest
snapshot/resource identities
fitted-state artifact / FitReceipt reference when applicable
implementation and build digest
partition and ordering context
logical RNG identity where applicable
input/output counts and cardinality evidence
schema transition
validation result
exclusion/filter reason summary
resource/runtime statistics
attempt/lease identity when remote
parent/child lineage edges
```

The receipt is evidence. Runtime debug logs are not a substitute.

### A40.12 Sample identity rules

Transform semantics determine identity evolution.

**One-to-one.** Preserve `SampleId` only when the transformed value represents the same semantic sample and the sample-identity contract explicitly allows the change. Physical re-encoding alone should not create a new semantic sample identity.

**Filter.** Surviving records keep identity; dataset membership/manifest identity changes.

**One-to-many.** Child identity is derived from parent identity plus transform semantic identity and a canonical child key—not executor ordinal alone unless the ordinal is itself canonical semantics.

**Many-to-one.** Output identity contains the canonical ordered/set-valued constituent identity set plus aggregation semantics.

**Join/complex assembly.** Output identity records left/right constituent identities, join keys, multiplicity, ordering, and assembly policy.

**Split/repartition.** Sample semantic identity usually remains stable; dataset/split/shard physical identities change.

### A40.13 Schema transitions

Every transform declares a schema transition:

```text
input schema(s)
→ transform semantic version
→ output schema(s)
```

A schema-compatible physical change is not automatically a semantic no-op. Conversely, a semantic transformation may retain the same structural schema while changing values. Both cases require explicit receipt evidence.

Schema migration transforms are deterministic, versioned, and retain lineage to the original artifact rather than rewriting it.

### A40.14 Structural transforms

Common structural primitives may include:

```text
project/select fields
rename fields
cast physical representation
reorder canonical fields
explode/unnest
pack/unpack nested records
encode/decode approved columnar representation
```

These helpers may be shared when semantics are truly domain-neutral. They remain low-level transform primitives and cannot silently apply scientific normalization.

### A40.15 Mapping and filtering

A map/filter transform must declare:

- exact input/output contract;
- deterministic predicate/mapping identity;
- missing/error behavior;
- exclusion reason taxonomy;
- whether diagnostics are outputs or evidence;
- cardinality bounds;
- policy/classification propagation.

A filter that drops a record without a receipt/reason is prohibited in release-producing pipelines.

### A40.16 Joins

Joins are high-risk transforms because they introduce hidden information and cardinality changes.

A join spec MUST declare:

```text
left/right input snapshot identities
join keys and normalization
inner/left/right/full/semi/anti semantics
multiplicity expectations
null/missing behavior
collision policy
ordering/tie-breaker
maximum fan-out
policy/classification merge rule
lineage representation
```

Unexpected many-to-many expansion fails or quarantines according to policy rather than silently amplifying a dataset.

### A40.17 Aggregates and global transforms

Aggregates, clustering, deduplication, and statistics may require dataset-global state.

They MUST define:

- partition-independent mathematical semantics;
- merge/reduction operation;
- associativity/commutativity assumptions where used;
- numerical precision/order sensitivity;
- deterministic tie-breaking;
- intermediate-state schema if checkpointed;
- completeness frontier before publication.

An implementation may parallelize a mathematically valid reduction but cannot claim equivalence when floating-point order materially changes release semantics without a tolerance/qualification contract.

### A40.18 Normalization and canonicalization transforms

Normalization transforms remain governed by Appendices A11–A12. `data/transforms/` executes them but `bio/` and the owning data package define:

```text
canonical entity meaning
component/sequence policy
units/frames
alternate-location policy
assembly selection
bond inference policy
missingness handling
unknown-component policy
```

The transform receipt records the exact policy and source-to-canonical mapping artifact.

### A40.19 Curation transforms

Curation is never an anonymous `filter(lambda ...)` in production.

A curation transform references a versioned rule/policy and emits:

```text
kept sample set
excluded sample set or digest
reason taxonomy/counts
before/after dataset statistics
policy/approval references when required
```

Manual curation is represented as an explicit reviewed transform/overlay with the same lineage model.

### A40.20 Deduplication and leakage transforms

Deduplication and leakage transforms declare:

- identity/similarity function and version;
- threshold and normalization;
- clustering/graph algorithm;
- deterministic representative selection;
- protected split/cohort constraints;
- external reference snapshots;
- evidence/report output.

They may generate durable metadata/cluster assignments without rewriting original records.

### A40.21 Split, sampling, and sharding transforms

These concepts are separate:

```text
split      semantic membership partition
sampling   selected subset/distribution
sharding   physical execution/storage partition
packing    runtime/physical batch organization
```

A split transform uses stable sample/cluster identities and a versioned policy. Sampling declares the distribution and RNG/seed semantics. Sharding must not change sample meaning. Packing belongs to training/model runtime unless a released dataset explicitly publishes a physical packing artifact.

### A40.22 Reusable feature transforms

A reusable feature transform implements or produces a `FeatureContract` from Appendix A39.

It additionally obeys:

```text
FeatureContract semantic identity
FeatureKeyDigest rules
biological validators
cacheability/leakage class
model-independent ownership
```

Representative relationship:

```text
TransformSpec
   └── produces FeatureContract
          └── FeatureManifest / FeatureBundle
```

Feature transforms may use the common transform executor, but cache identity remains Appendix A39 `FeatureKeyDigest` rather than a competing generic cache key.

### A40.23 Model-view transforms

Model-view transforms live with the model family and may include:

```text
bucketization
embedding-index mapping
feature concatenation
channel projection
model-specific normalization
logical tensor layout
optional deterministic packing
```

They consume semantic feature contracts/artifacts but do not mutate their meaning. A model-view digest participates in model input/reproducibility evidence.

Shared data code cannot import these model implementations.

### A40.24 Runtime batch transforms

Runtime batch transforms include:

```text
crop
mask
augmentation
random rotation
MSA/template subsampling when task-owned
noise/timestep generation
padding
microbatch packing
dtype/device conversion
```

They execute after durable semantic feature resolution unless the owning scientific contract explicitly says otherwise.

Training stochastic transforms derive RNG from logical run/phase/step/sample/purpose identity. Inference request-specific stochastic transforms derive from request/reproducibility policy. They are receipt-replayable, not silently cached.

### A40.25 External snapshot/resource inputs

A transform that consults external state must convert that state into an immutable declared input before production execution whenever practical.

Examples:

```text
UniRef snapshot
PDB snapshot
CCD release
retrieval index digest
normalization dictionary
ontology release
model/teacher bundle
policy bundle
```

`latest`, wall-clock date, mutable database contents, or ambient service state cannot silently influence output semantics.

### A40.26 Side-effect law

Semantic transform functions MUST NOT perform undeclared side effects.

Prohibited inside a transform operator:

- publishing catalog rows;
- mutating source objects;
- sending events or webhooks;
- resolving ambient credentials;
- arbitrary Internet access;
- writing global mutable state;
- choosing a mutable model/dataset alias;
- updating business workflow state.

Composition roots/executors own source acquisition, artifact staging/finalization, events, lease heartbeat, and cancellation.

### A40.27 Error contract

Transform errors are classified:

```text
INVALID_INPUT
SCHEMA_MISMATCH
SEMANTIC_VALIDATION_FAILED
POLICY_DENIED
SNAPSHOT_UNAVAILABLE
RESOURCE_EXHAUSTED
TRANSIENT_IO
IMPLEMENTATION_FAILURE
DETERMINISM_VIOLATION
CARDINALITY_VIOLATION
ORDERING_VIOLATION
LINEAGE_VIOLATION
CANCELLED
DEADLINE_EXCEEDED
```

The transform contract states whether bad records are terminal, quarantinable, or eligible for an explicit permissive policy. Silent catch-and-drop behavior is prohibited.

### A40.28 Retry and idempotency

Retryability follows declared semantics.

Pure transforms may retry from immutable inputs. Materialization is idempotent by invocation/output identity. Stateful/global transforms resume only from a declared checkpoint/frontier. External-source calls use snapshot-aware acquisition contracts rather than assuming repeatability.

Duplicate attempts may produce the same immutable output; they may not publish contradictory authoritative receipts for one deterministic invocation.

### A40.29 Streaming and bounded memory

Transforms over large biological corpora SHOULD expose streaming or partition-bounded execution where their semantics permit it.

A transform declares:

```text
maximum record size
batch/partition size contract
buffering bounds
spill policy
backpressure behavior
cancellation points
intermediate materialization policy
```

Rust is preferred for hot paths where bounded-memory streaming and CPU efficiency materially matter. Python reference transforms may operate on bounded Arrow batches rather than loading a full corpus.

### A40.30 Partition contract

Partitioning is explicit execution metadata with semantic impact only when declared.

A partition plan contains:

```text
partition key/function version
number/range of partitions
input membership rule
within-partition order
cross-partition merge/publication order
resource estimate
```

Changing partition count must not alter a transform's semantic result unless the transform explicitly declares partition-sensitive semantics, in which case it creates a different invocation/plan identity.

### A40.31 Execution backends

Initial production backends are deliberately small:

```text
Python local/bounded-batch reference executor
Rust streaming/CPU executor
worker-level sharded execution using existing Job/Run/Attempt semantics
```

A distributed engine adapter such as Apache Spark MAY be activated when a measured corpus-scale workload justifies it. Activation requires:

- one real workload and cost/throughput target;
- mapping from `TransformGraph` to engine plan;
- stable input/output/partition/ordering semantics;
- exact `TransformReceipt` compatibility;
- cancellation/retry/failure mapping;
- artifact/catalog authority preservation;
- security and dependency review;
- parity against the reference executor.

Spark/another engine is an execution provider, never the semantic owner or a second dataset catalog.

#### A40.31.1 Remote feature/transform execution protocol

Remote work uses bounded Protobuf commands that reference immutable graph/plan artifacts rather than embedding a large graph or payload in queue messages:

```text
ExecuteTransformCommand
    transform_execution_plan: ArtifactRef
    attempt_id: AttemptId
    lease_epoch: LeaseEpoch
    deadline
    delegated_capability_ref

MaterializeFeaturesCommand
    feature_plan: ArtifactRef
    transform_execution_plan: ArtifactRef
    attempt_id: AttemptId
    lease_epoch: LeaseEpoch
    deadline
    delegated_capability_ref

TransformExecutionCompleted / FeatureMaterializationCompleted
    receipt: ArtifactRef
    output_refs: repeated ArtifactRef
    attempt_id / lease_epoch
    terminal classification
```

The command consumer resolves and verifies the referenced immutable plan, graph, inputs, security context, and deadline before execution. Large `TransformGraph`, `FeaturePlan`, feature payloads, and lineage maps remain artifact-plane values. Duplicate delivery is safe by attempt/fence and semantic/output identity; stale attempts may publish diagnostic evidence but cannot advance the authoritative projection or workflow state.

### A40.32 Transform graph

A `TransformGraph` is an acyclic typed graph:

```python
@dataclass(frozen=True)
class TransformNode:
    node_id: str
    spec: TransformSpecRef
    inputs: tuple[TransformInputRef, ...]
    parameters: CanonicalParameters
    materialization: MaterializationPolicy

@dataclass(frozen=True)
class TransformGraph:
    graph_id: str
    inputs: tuple[GraphInput, ...]
    nodes: tuple[TransformNode, ...]
    outputs: tuple[GraphOutput, ...]
```

Validation proves:

- no cycle;
- contracts connect;
- required snapshots exist;
- cardinality/order constraints are satisfiable;
- state/global barriers are explicit;
- materialization boundaries are legal;
- policy/classification flow is valid;
- no model/private-domain import violates dependency law.

### A40.33 Graph planning

Planning produces a `TransformExecutionPlanDigest` and may choose:

```text
partitioning
batch size
executor implementation/backend
materialization boundary
parallelism
projection pushdown
safe transform fusion
spill/local scratch budget
non-semantic cost-optimized read-versus-recompute decisions
```

Planning MUST NOT change:

```text
transform semantic version
scientific parameters
sample/split meaning
feature contract
allowed external snapshots
RNG semantics
filter/join cardinality
model-view meaning
```

The resulting execution plan is immutable evidence for distributed/release-significant execution.

### A40.34 Transform optimization and fusion

Optimization is permitted only through proven equivalence.

Examples:

- project unused fields earlier;
- fuse consecutive stateless maps;
- vectorize scalar operations;
- push filters before expensive pure transforms when equivalent;
- coalesce physical partitions;
- replace Python reference with qualified Rust implementation.

Optimization is forbidden when it changes observable ordering, floating-point contract, side-effect count, RNG consumption, exclusion diagnostics, missingness, cardinality, or lineage.

An `OptimizationReceipt` records original graph digest, optimized graph digest, applied rules, and qualification identity.

### A40.35 Materialization boundaries

Each transform node declares or inherits:

```text
EPHEMERAL
CHECKPOINTABLE
OPPORTUNISTIC_CACHE
DURABLE_ARTIFACT
RELEASE_ARTIFACT
```

Materialization decisions consider recompute cost, downstream fan-out, failure recovery, lineage, storage cost, security, and release evidence.

Not every intermediate deserves a durable object. Conversely, an expensive/global/release-critical boundary should not exist only in worker memory.

#### A40.35.1 Cost-aware materialization

Materialization policy may consume **non-semantic cost hints**:

```text
estimated_compute_cpu_ms / accelerator_ms
estimated_read_bytes and expected read latency
estimated_output_bytes
expected reuse count / reuse probability
downstream fan-out
failure-recovery value
source/recompute availability
storage and egress cost class
```

A `TransformCostHint` or planner estimate can choose recompute versus read, ephemeral versus opportunistic cache, and useful checkpoint/materialization boundaries. Cost estimates are advisory execution inputs only: an inaccurate estimate may hurt performance or cost but MUST NOT alter scientific values, sample identity, transform semantic identity, leakage policy, or release eligibility. Qualification compares chosen plans with correctness-preserving alternatives and records the final `TransformExecutionPlanDigest`.

### A40.36 Relationship to cache identity

The transform framework does not introduce a second generic cache truth.

For reusable semantic features:

```text
TransformSpec + exact inputs
→ Appendix A39 FeatureKeyDigest
→ FeatureManifest / artifact
```

For non-feature deterministic artifacts, the owning data artifact contract defines the content/manifest identity. `TransformSemanticKey` is provenance/idempotency evidence and may support a reconstructible projection, but an object is authoritative only after normal artifact finalization/catalog publication.

### A40.37 Lineage graph

Every persisted transform closes lineage edges:

```text
input artifact/sample(s)
   ↓
TransformReceipt
   ↓
output artifact/sample(s)
```

For graph execution, lineage can be compacted at shard/partition granularity when per-record provenance is derivable from deterministic membership/index mappings. Compression must not make scientific reconstruction impossible.

#### A40.37.1 LineageMapArtifact and membership indexes

Corpus-scale transforms SHOULD avoid materializing one standalone provenance edge per record when a deterministic compact mapping is equivalent. `LineageMapArtifact` is an immutable, schema-versioned artifact referenced by `TransformReceipt` and may encode:

```text
input and output shard/partition identities
canonical membership ranges or sorted identity sets
parent → child derivation keys for one-to-many transforms
constituent sets for many-to-one/join outputs
filter/exclusion bitmaps or compact reason indexes
physical row ↔ stable SampleId indexes
partition and canonical publication-order mappings
```

The compact form MUST support deterministic reconstruction of the required per-sample lineage and impact analysis without consulting mutable executor state. Compression changes the physical evidence representation, not semantic lineage. Dataset/feature/checkpoint/model releases retain the relevant lineage-map digest for their retention window.

### A40.38 Data classification and tenant policy

Transform context carries:

```text
tenant/project
principal/delegated workload identity
data classification
use/license policy
region/residency constraints
retention class
allowed egress/snapshots
```

Output classification is a declared propagation rule and may only preserve or elevate restrictions unless an explicitly authorized declassification transform exists.

Cross-tenant transform execution, joins, caches, or statistics require an explicit governed shared-data domain; identical content digests do not grant access.

### A40.39 Evaluation leakage controls

Evaluation applies transform-specific leakage rules before execution/materialization.

A transform that can expose future or protected information declares its leakage class and required evidence. Examples include:

- retrieval against evolving databases;
- template search with release dates;
- train/eval statistics fit globally;
- deduplication against hidden sets;
- normalization parameters estimated using protected cohorts.

Evaluation rejects transform graphs whose input snapshots, fitting scope, or cutoff provenance violate the suite policy.

### A40.40 Training reproducibility

Training separates precomputed transforms from runtime transforms.

```text
released dataset
→ deterministic data/feature transform graph
→ FeatureBundle / model inputs
→ runtime BatchTransformGraph
→ BatchReceipt
→ optimizer update
```

The runtime graph records logical RNG derivation, crop/mask/noise parameters, packing identity, and transform versions. Resume restores logical data/RNG progress such that the next committed update consumes the same transform semantics under the declared recovery guarantee.

### A40.41 Inference transforms

Inference uses transform contracts for:

- input canonicalization;
- deterministic preprocessing;
- feature resolution;
- model-view construction;
- bounded request transforms;
- postprocessing/output projection.

Dynamic batching and device packing are execution transforms, not changes to the public scientific request. A serving optimization must preserve per-request transform receipts and output semantics.

### A40.42 Python/Rust boundary

The preferred boundary is typed immutable records or Arrow-compatible batches.

Python owns:

- scientific reference transforms;
- model-view transforms;
- training/inference runtime transforms;
- qualification or rapid scientific iteration where Python is the semantic reference.

Rust owns:

- high-throughput streaming transforms;
- parser-adjacent transforms;
- bounded-memory partition execution;
- CPU-heavy deterministic implementations;
- Arrow/buffer transfer hot paths.

Rust acceleration of Python reference semantics requires parity evidence when the output is scientifically meaningful.

### A40.43 Production UDF policy

Arbitrary serialized closures, pickled lambdas, notebook functions, or user-supplied code are prohibited as production transform identity.

A production transform has:

```text
registered TransformId
versioned parameter schema
owned source target
build/implementation digest
tests/qualification
explicit dependency and side-effect policy
```

Research may use ad hoc functions inside `research/`; graduation requires a named transform contract.

Production executable implementations register only in the qualified `ImplementationRegistry` for an existing `TransformSpec`; registration cannot create a new semantic transform at runtime. Build targets and component metadata enumerate every eligible implementation, making the registry closed-world and auditable for a release.

### A40.44 Source blueprint

```text
protocols/schemas/
├── transform_spec/
├── transform_graph/
├── transform_receipt/
├── transform_execution_plan/
├── transform_state_artifact/
├── fit_receipt/
└── lineage_map/

bio/featurization/
├── contracts/
├── transforms/
│   ├── feature_transform.py
│   ├── feature_transform_spec.py
│   └── feature_transform_receipt.py
├── catalog/
├── python/
├── rust/
├── validation/
└── parity/

data/transforms/
├── contracts/
│   ├── transform.py
│   ├── transform_spec.py
│   ├── transform_context.py
│   ├── transform_receipt.py
│   ├── transform_semantic_key.py
│   ├── cardinality.py
│   ├── ordering.py
│   ├── state_scope.py
│   ├── materialization.py
│   └── profiles/
│       ├── map.py
│       ├── filter.py
│       ├── explode.py
│       ├── join.py
│       ├── aggregate.py
│       ├── fitted.py
│       ├── semantic_feature.py
│       └── runtime_stochastic.py
├── graph/
│   ├── node.py
│   ├── edge.py
│   ├── transform_graph.py
│   ├── validation.py
│   └── canonicalization.py
├── planning/
│   ├── execution_plan.py
│   ├── planner.py
│   ├── partition_plan.py
│   ├── cost_model.py
│   └── materialization_cost.py
├── catalog/
│   └── transform_catalog.py
├── implementations/
│   ├── implementation_registry.py
│   ├── operator_identity.py
│   └── compatibility.py
├── fitting/
│   ├── fit_semantic_key.py
│   ├── transform_state.py
│   ├── fit_receipt.py
│   └── fit_validation.py
├── lineage/
│   ├── lineage_map.py
│   ├── membership_index.py
│   └── compaction.py
├── execution/
│   ├── executor.py
│   ├── local_runner.py
│   ├── stream_runner.py
│   ├── partition_runner.py
│   └── resource_limits.py
├── validation/
│   ├── schema_transition.py
│   ├── determinism.py
│   ├── side_effects.py
│   └── receipt_validation.py
├── optimization/
│   ├── projection_pushdown.py
│   ├── fusion.py
│   ├── partition_coalescing.py
│   └── optimization_receipt.py
├── rust/
│   ├── Cargo.toml
│   └── src/
│       ├── lib.rs
│       ├── executor.rs
│       ├── stream.rs
│       ├── partition.rs
│       └── arrow_bridge.rs
├── fixtures/
│   ├── transform_contract_cases.json
│   ├── fitted_state_cases.json
│   ├── lineage_map_cases.json
│   └── partition_order_cases.json
└── tests/
    ├── test_transform_profiles.py
    ├── test_semantic_execution_identity.py
    ├── test_fit_state_and_scope.py
    ├── test_lineage_map_reconstruction.py
    ├── test_cost_policy_nonsemantic.py
    └── test_backend_equivalence.py

# Domain semantics remain with their owners:
data/normalization/
data/curation/
data/deduplication/
data/leakage/
data/splits/
data/sampling/
data/featurization/

models/families/<family>/<model>/features/
├── requirements.py
├── requirement_set.py
├── derived_features.py
├── model_feature_view.py
├── transforms.py
├── tensor_views.py
├── tensorize.py
├── packing.py
└── validation.py

training/core/data/
├── feature_resolver.py
├── batch_recipe.py
├── batch_transforms.py
├── feature_readiness.py
└── prefetch.py
```

The explanatory `<family>/<model>` path is not a literal committed path; Appendix A6 remains the exact activated tree.

### A40.45 Representative transform API

```python
class Transform(Protocol):
    def spec(self) -> TransformSpec: ...

    def apply(
        self,
        inputs: tuple[TransformInput, ...],
        *,
        context: TransformContext,
    ) -> TransformResult: ...
```

The semantic function returns values/diagnostics. Publication is executor-owned.

The semantic operator does not receive an execution plan. The executor binds the same semantic operator to a `TransformExecutionPlanDigest`; backend replacement therefore cannot silently influence semantic parameters or identity. Fitted transforms expose a separate `fit` interface that returns a `TransformStateArtifact`, and their ordinary `apply` receives that state as an immutable declared input.

For streaming transforms:

```rust
pub trait StreamingTransform<I, O> {
    fn spec(&self) -> &TransformSpec;

    fn apply_batch(
        &self,
        input: I,
        ctx: &TransformContext,
    ) -> Result<O, TransformError>;
}
```

The Rust type is illustrative; exact generated/shared contract types follow the repository language-boundary rules.

### A40.46 Transform context

`TransformContext` is explicit and immutable for an invocation. It may contain:

```text
cancellation/deadline
trace/attempt identity
tenant/project/security context
logical RNG handle
resolved immutable snapshot refs
resource limits
scratch allocator/path capability
artifact read capability
```

It does not expose unrestricted database clients, ambient cloud credentials, arbitrary network clients, or mutable model aliases.

### A40.47 Developer tooling

Recommended commands:

```text
mindclade data transform validate <graph>
mindclade data transform plan <graph> --input <artifact>
mindclade data transform run <graph> --profile local
mindclade data transform explain <receipt-or-output>
mindclade data transform replay <receipt>
mindclade data transform diff <receipt-a> <receipt-b>
mindclade data transform qualify <transform>
```

`explain` should show semantic operator/version, input lineage, snapshots, parameters, implementation, materialization, cardinality/order evidence, and why a result was reused/recomputed.

### A40.48 Observability

Core metrics include:

```text
transform_invocations_total
transform_failures_total
transform_records_in_total
transform_records_out_total
transform_bytes_in_total
transform_bytes_out_total
transform_duration_seconds
transform_partition_duration_seconds
transform_quarantined_records_total
transform_materialized_bytes_total
transform_reused_total
transform_determinism_violations_total
transform_cardinality_violations_total
transform_optimization_applied_total
```

Bounded labels include transform family/version, execution backend, result class, and data class where policy permits. Sample IDs, raw source values, and artifact digests are not metric labels.

### A40.49 Testing and qualification

Required tests are selected by transform class:

```text
schema/contract tests
canonical parameter/digest tests
golden examples
property tests
fuzz/malformed input tests
cardinality tests
ordering/repartition tests
determinism/replay tests
Python↔Rust parity tests
filter/exclusion accounting tests
join fan-out tests
global aggregation merge tests
snapshot/cutoff/leakage tests
cancellation/retry/idempotency tests
optimization/fusion equivalence tests
large-corpus bounded-memory tests
security/classification tests
```

A new backend must pass the same semantic receipts as the reference backend within the declared numerical contract.

### A40.50 CI gates

Presubmit rejects:

- unregistered production transforms;
- missing owner/spec/parameter schema;
- transform graphs with cycles or contract mismatch;
- undeclared external state/network side effects;
- nondeterministic release transforms;
- missing exclusion reasons for filtering transforms;
- partition/order-sensitive behavior without declaration;
- model code imported into `data/transforms/`;
- domain semantics moved into generic `libs/` or transform plumbing;
- materialized transform outputs without lineage/receipt;
- optimization rules lacking equivalence tests;
- a feature planner that bypasses `TransformGraph` lowering or reimplements generic DAG scheduling;
- semantic `FeatureCatalog`/`TransformCatalog` declarations discovered only through runtime plugins;
- fitted transforms without immutable state/fitting-scope evidence;
- execution-plan fields accidentally included in semantic identity without an explicit semantic classification;
- blueprint/tree generated render drift from their machine-readable source manifests.

### A40.51 Failure injection

Production qualification injects:

```text
worker death mid-partition
retry after unknown publication result
partial artifact write
partition duplication/reordering
lost/stale lease
snapshot disappears before execution
external read timeout
corrupt intermediate artifact
out-of-memory/spill limit
cancellation during global reduction
same invocation with divergent implementation output
optimized versus reference graph mismatch
```

The system must either reproduce the declared output or fail with attributable evidence; it cannot silently publish an ambiguous dataset.

### A40.52 Wave mapping

**Wave 2S.** Establish the minimum common `TransformGraph`, typed `TransformSpec` profiles, `TransformSemanticKey`, `TransformExecutionPlanDigest`, and `TransformReceipt` contract needed for SQP-001 normalization, curation, deterministic split/sample/shard, and simple feature transforms. `FeaturePlan` lowers to this common graph. Local Python/Rust execution only; fitted-state support remains schema-level or absent unless SQP-001 acquires a real fitted transform.

**Wave 3.** Graduate durable transform schemas actually exercised by the joined scientific/platform slice. Bind transform receipts and compact `LineageMapArtifact`s into dataset/feature lineage and inspection tooling. Graduate fitted-state contracts only if a real fit/apply operation is exercised.

**Wave 4.** Add bounded remote `ExecuteTransformCommand` and `MaterializeFeaturesCommand` protocols plus durable transform jobs/reconciliation for data and feature materialization. Commands reference immutable plan/graph artifacts and preserve the same semantic/receipt contracts.

**Wave 5.** Qualify large sharded execution, cancellation, preemption/retry, storage faults, and deterministic partition/reduction behavior on GKE.

**Later measured activation.** Add Spark or another distributed transform backend only after profiling demonstrates a concrete corpus-scale need and it passes A40.31 backend qualification. No backend directory or dependency is pre-created before activation.

### A40.53 Migration from ad hoc transforms

Legacy transforms are migrated by:

1. inventorying dataset/model preprocessing functions and scripts;
2. identifying their semantic owner;
3. classifying cardinality, ordering, state, determinism, snapshots, and side effects;
4. freezing canonical fixtures and current outputs;
5. defining a named `TransformSpec` and parameter schema;
6. separating acquisition/publication side effects from pure semantics;
7. adding receipts and lineage;
8. qualifying reference behavior;
9. replacing path/function-name cache assumptions with artifact/feature identities;
10. removing the legacy path after all consumers migrate.

Do not create a giant compatibility transform that perpetually dispatches on model or dataset name.

### A40.54 Prohibited anti-patterns

The following are prohibited in production:

```python
df = df.apply(lambda row: hidden_global_state(row))
```

```python
if model_name == "cladefold":
    transform_data_one_way()
else:
    transform_data_another_way()
```

Also prohibited:

- anonymous mutable notebook functions as release transforms;
- transform identity derived only from Python module/function name;
- implicit row-number identity after filter/join/explode;
- object-store listing order as sample order;
- hidden network/database reads inside transform functions;
- silent exception swallowing/drop-record behavior;
- random transforms without logical RNG/receipt identity;
- generic `utils/transforms.py` becoming the semantic home for unrelated domains;
- executor-specific behavior changing dataset/feature meaning;
- physical repartitioning silently changing split/sample semantics;
- caching runtime stochastic tensors as though they were reusable semantic features;
- optimizer/fusion rewrites without semantic equivalence evidence.

### A40.55 Acceptance gates

The transform architecture is qualified when:

1. every production transform has one semantic owner and versioned `TransformSpec`;
2. cardinality, ordering, state, determinism, materialization, and side-effect policies are explicit;
3. persisted outputs have complete `TransformReceipt` lineage;
4. filter/join/global transforms prove record-count and membership behavior;
5. changing worker count/partitioning does not alter semantics where the contract claims partition independence;
6. Python/Rust implementations agree for shared scientific transforms under their tolerance contract;
7. model-view transforms remain model-owned and data transforms do not import model code;
8. runtime stochastic transforms are logical-RNG replayable and absent from ordinary shared feature cache;
9. evaluation prevents snapshot/fitting-scope leakage;
10. transform optimization/fusion preserves receipt-equivalent semantics;
11. a backend can be replaced without changing transform identities or dataset/feature contracts;
12. source trees contain no anonymous production transform authority outside the declared owners;
13. `FeaturePlan` lowering uses the common `TransformGraph` and no parallel generic feature DAG scheduler exists;
14. fitted transforms publish immutable `TransformStateArtifact` plus fitting-scope evidence and evaluation rejects disallowed fit scope;
15. execution backend/parallelism/materialization changes preserve `TransformSemanticKey` whenever execution independence is claimed;
16. semantic catalogs and implementation registries have distinct authority and runtime plugins cannot create semantics;
17. compact lineage maps reconstruct the required sample lineage and downstream impact set;
18. remote commands carry plan/artifact references rather than large graph/payload bodies.

### A40.56 Definition of done

Feature/data transforms are production-ready when the repository can reconstruct, for any released dataset, feature artifact, training batch, evaluation input, or inference request:

```text
which transform semantics ran
on which immutable inputs
with which parameters/snapshots
under which implementation/equivalence qualification
with which cardinality/order/partition behavior
with which logical RNG where applicable
what was filtered/quarantined
what immutable output was produced
and which downstream artifacts consumed it
```

This evidence must survive worker replacement, executor/backend replacement, artifact relocation, retry, and supported schema migration.

### A40.57 Final transform invariants

- transform composition is generic; transform meaning remains domain-owned;
- every transform states input/output contracts, cardinality, ordering, determinism/state, and side effects;
- immutable inputs and canonical parameters determine reproducible transform identity;
- publication and business state are composition-root responsibilities, not hidden semantic side effects;
- sample identity evolution follows transform semantics, never row or file position;
- feature transforms obey Appendix A39 identity/cache law;
- model-view transforms remain model-owned;
- runtime stochastic transforms remain explicit, logical-RNG-derived, and receipt-replayable;
- executor/backend replacement cannot change scientific or dataset meaning;
- optimization is legal only under proven transform equivalence;
- a transform graph is dataflow intent, never a competing scheduler, queue, workflow engine, or system of record.
