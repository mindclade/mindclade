## Appendix A39 — Feature derivation, caching, and model-specific feature architecture

This appendix is the normative cross-domain blueprint for deriving, reusing, validating, storing, and consuming features across model families. It refines the existing `bio/`, `data/`, `models/`, `training/`, `evaluation/`, `inference/`, worker, protocol, and artifact authorities; it does **not** create a new top-level feature domain or a standalone feature-store authority.

### A39.1 Executive decision

Mindclade SHALL treat feature caching as a consequence of deterministic scientific derivation identity, not as a directory convention or model-owned preprocessing shortcut.

The canonical flow is:

```text
immutable source artifacts
→ canonical biological records
→ reusable semantic feature values
→ immutable feature artifacts/manifests
→ FeatureBundle
→ model-owned deterministic feature views
→ runtime batch/tensor/device views
→ training / evaluation / inference
```

The governing question is:

> Have these exact declared feature semantics already been derived from these exact immutable inputs and dependencies under this exact derivation identity?

The prohibited question is:

> Is there some tensor file for this sample/model in the cache?

### A39.2 Authority and anti-shadow-store law

| Concern | Sole semantic authority | Operational realization |
|---|---|---|
| canonical biological entities | `bio/` | schemas, entities, format conformance, normalization inputs |
| reusable semantic feature meaning | `bio/featurization/` | feature contracts, FeatureCatalog, validators, reference/parity fixtures |
| derivation planning/materialization | `data/featurization/` | DAG planner, resolver, cache projection, coverage, publication |
| immutable feature bytes/evidence | artifact system + data catalog | CAS object, `FeatureManifest`, lineage/catalog row |
| feature execution process | `workers/feature_worker/` | fenced Rust worker plus qualified Python/Rust derivations |
| model-specific feature requirements/views | `models/families/<family>/<model>/features/` | requirement document, derived features, tensor views, packing |
| training-time stochastic transforms | `training/core/data/` and task | `BatchRecipe`, logical RNG, `BatchReceipt` |
| evaluation feature eligibility | `evaluation/` | leakage/cutoff policy and evidence validation |
| inference feature resolution | `inference/` | shared resolver contract plus request-specific model views |

There is no independent “feature store” database that becomes scientific truth. The data catalog is durable metadata/lifecycle authority; object storage is immutable byte authority; a feature-cache index is a rebuildable lookup projection.

### A39.3 Semantic layers and cache levels

Mindclade distinguishes five layers.

#### L0 — source and canonical artifacts

Examples:

```text
raw FASTA/mmCIF/CCD/A3M/Stockholm
Sequence / Structure / ChemicalComponent / Alignment canonical records
```

These are immutable and durable.

#### L1 — reusable semantic features

Examples when activated by real consumers:

```text
bio.sequence.residue_type
bio.sequence.residue_index
bio.sequence.chain_index
bio.structure.atom_positions
bio.structure.atom_mask
bio.geometry.residue_frame
bio.geometry.relative_residue_position
bio.chemistry.atom_element
bio.chemistry.bond_graph
bio.msa.alignment_profile
bio.template.hit_set
```

A feature belongs here only when its scientific meaning is independent of one model architecture. This is the primary cross-model reuse boundary.

#### L2 — deterministic model-specific derived features

Examples:

```text
cladefold.relative_position_buckets
cladefold.template_pair_channels
clade1.biological_token_metadata
```

These live with the model family. They may be persisted when expensive and stable, but are not promoted into shared biological semantics solely for cache reuse.

#### L3 — model tensor and packing views

Examples:

```text
PyTorch tensors
embedding lookup indices
one-hot/bucketized channels
model-specific padding/packing metadata
BF16/FP32 logical tensor representations
```

These normally live in model/training/inference memory and may be opportunistically cached only under explicit model-view identity.

#### L4 — runtime stochastic/device views

Examples:

```text
training crop
masking
augmentation
random MSA/template sampling
diffusion timestep/noise
classifier-free dropout state
padding for one dynamic batch
GPU device transfer
runtime layout conversion
```

These are not ordinary durable semantic feature-cache entries.

### A39.4 Canonical identities

The feature subsystem uses existing `ArtifactDigest` and introduces explicit derivation/bundle vocabulary:

```text
FeatureContractId
FeatureContractVersion
FeatureRequirementSetDigest
FeatureKeyDigest
FeatureManifestDigest        # ordinary artifact/manifest digest
FeatureBundleDigest          # digest of immutable bundle manifest
ModelFeatureViewDigest
FeatureCoverageManifestDigest
FeatureReadinessReceiptDigest
```

`FeatureKeyDigest` identifies the requested deterministic derivation semantics. It is not a path, database primary key, or payload digest.

`ArtifactDigest` identifies the resulting immutable bytes.

`FeatureManifestDigest` identifies the interpretation/provenance manifest associated with the result.

This distinction permits detection of nondeterminism:

```text
same FeatureKeyDigest
+ different valid ArtifactDigest
= DETERMINISM_VIOLATION
```

### A39.5 FeatureContract

A `FeatureContract` defines meaning, not implementation layout.

Representative schema fields are:

```text
contract ID and semantic version
schema digest
domain / feature class
logical value type
semantic dimensions/axes
units/frame where relevant
missingness semantics
canonical ordering
normalization meaning
required upstream semantic inputs
validation invariants
determinism class
cacheability class
leakage class
data/security classification
compatibility/migration policy
```

A conceptual Python representation may be:

```python
from dataclasses import dataclass
from enum import Enum

class DeterminismClass(str, Enum):
    PURE = "pure"
    SNAPSHOT_DEPENDENT = "snapshot_dependent"
    SEEDED = "seeded"
    RUNTIME_STOCHASTIC = "runtime_stochastic"

@dataclass(frozen=True, slots=True)
class FeatureContract:
    feature_id: str
    semantic_version: str
    schema_digest: str
    dimensions: tuple[str, ...]
    determinism: DeterminismClass
    cacheability: str
    leakage_class: str
```

This contract code remains torch-free when it is used below the model boundary.

### A39.6 Feature catalog

`bio/featurization/catalog/` contains the authoritative `FeatureCatalog` for activated reusable semantic features. A catalog entry declares the semantic contract and owner; it does not register model-specific tensor code, executable implementations, or an execution backend.

Example:

```yaml
id: bio.geometry.relative_residue_position
version: 2.0.0
owner: computational-biology
value:
  dtype: int32
axes: [residue_i, residue_j]
determinism: pure
cacheability: durable
leakage: source_local
validators:
  - pair_dimensions_match_residue_set
```

CI rejects duplicate identities, cycles in required semantic dependencies, incompatible semantic changes without version migration, missing owner, undefined axes, undeclared determinism/cacheability/leakage, and catalog entries with no activated consumer.

The active tree initially contains only features required by SQP-001. MSA/template/ligand feature entries activate with their first real model/data consumer and qualification evidence.

### A39.7 Feature requirement contract

Models declare requirements against the registry:

```text
role: residue_type
contract: bio.sequence.residue_type@2
required: true
constraints: ...
```

Conceptually:

```python
@dataclass(frozen=True, slots=True)
class FeatureRequirement:
    role: str
    feature_id: str
    version_range: str
    required: bool = True
```

A model is not permitted to say:

```text
load cache/cladefold/<sample>/features.pt
```

or make a `data/` implementation type part of its public API.

### A39.8 Complete FeatureKeyDigest

Canonical key material is:

```text
FeatureContract ID/version/schema digest
ordered input ArtifactDigest/CanonicalRecord references with semantic roles
ordered upstream FeatureManifest/ArtifactDigest references with semantic roles
derivation semantic operator ID/version
implementation digest OR approved semantic-equivalence-class digest
canonical semantic parameters
external database/index/tool snapshot digests
source/release/time cutoffs and retrieval/filter policy when applicable
seed/logical RNG identity only for SEEDED cacheable derivations
output encoding semantics when encoding changes interpretation
```

Operational authorization context that does not alter scientific value is not mixed into semantic identity. Instead lookup is partitioned:

```text
CachePartitionKey = hash(
    tenant/project or approved shared-domain scope,
    policy/security class,
    FeatureKeyDigest,
)
```

This permits content deduplication without cross-tenant cache discovery.

### A39.9 Canonical encoding

All identity-bearing feature structures use one explicitly defined canonical serialization compatible across Rust and Python. The repository shall ship golden vectors containing:

```text
structured input fixture
expected canonical bytes or canonical JSON form
expected FeatureKeyDigest
expected contract/schema digest
```

Rust and Python must produce identical keys for the same declared derivation. Hashing raw Python `repr`, insertion-order-sensitive maps, local paths, protobuf maps without canonical handling, or platform-dependent float formatting is prohibited.

NaN/Inf, signed zero, float normalization, Unicode normalization, collection ordering, and optional/missing values have explicit rules.

### A39.10 Derivation semantic identity and implementation identity

A derivation has two related identities:

```text
semantic operator identity
implementation identity
```

Default policy includes the exact implementation/build digest in `FeatureKeyDigest`. This is conservative and prevents an implementation change from silently reading stale results.

Two implementations may share an equivalence-class identity only after `SemanticEquivalenceQualification` proves the required relation. Example:

```text
Python reference operator
↕ golden/parity corpus
Rust optimized operator
```

Qualification defines exact equality or numerical tolerance, shape/order/missingness equality, edge cases, deterministic behavior, and supported input envelope. The qualification digest becomes part of the equivalence identity.

### A39.11 Derivation operator boundary

An operator exposes a narrow contract conceptually equivalent to:

```rust
pub trait DerivationOperator {
    fn semantic_id(&self) -> &str;
    fn semantic_version(&self) -> &str;
    fn output_contract(&self) -> &FeatureContractRef;
    fn requirements(&self) -> &[FeatureRequirement];
    fn derive(
        &self,
        ctx: &DerivationContext,
        inputs: &ResolvedInputs,
    ) -> Result<DerivedFeature, DerivationError>;
}
```

The operator does not:

- inspect arbitrary model classes;
- obtain undeclared source/database state;
- read process-global configuration as scientific semantics;
- use undeclared randomness;
- mutate upstream artifacts;
- choose tenant authorization;
- directly publish catalog truth;
- own retries, worker fencing, or object-store commit.

Those responsibilities belong to planner/executor/composition layers.

### A39.12 Derivation DAG and planner

#### A39.13.1 FeaturePlan lowers to the generic TransformGraph

`FeaturePlan` is a feature-domain artifact that records resolved `FeatureRequirement`s, feature-specific identities, cache hit/miss decisions, and expected semantic outputs. It is **not** a second generic DAG implementation. The feature resolver lowers all cache misses into the single `data/transforms/` `TransformGraph` representation:

```text
FeatureRequirementSet
    ↓ feature resolution / FeatureKeyDigest / cache projection
FeaturePlan
    ↓ deterministic lowering
TransformGraph
    ↓ generic graph validation / execution planning / backend selection
feature-producing TransformReceipt(s)
    ↓ feature-specific validation / publication
FeatureManifest + FeatureBundle
```

Cycle detection, generic edge typing, partition planning, graph canonicalization, execution backend selection, generic retries, and transform receipts are owned once by Appendix A40. `data/featurization/` owns only feature-specific resolution, lowering constraints, cache projection, materialization validation, coverage/readiness, and feature manifests.

A `FeaturePlan` is a deterministic DAG.

```text
SequenceRecord
 ├── residue_type ───────────── HIT
 ├── residue_index ──────────── HIT
 └── pair_position
        └── relative_position ─ MISS

StructureRecord
 ├── atom_positions ─────────── HIT
 └── residue_frames ─────────── MISS
```

The planner:

1. resolves the model's feature requirements;
2. resolves exact contract versions under the model compatibility range;
3. expands dependency declarations;
4. validates acyclicity;
5. computes `FeatureKeyDigest` for every resolvable node;
6. performs authorized verified projection lookups;
7. prunes hits;
8. produces deterministic work nodes for misses;
9. attaches cost/resource hints without altering semantics;
10. emits an explainable plan digest.

Cheap deterministic nodes may be recomputed even when a durable artifact exists if a declared cost policy proves recomputation is preferable. This optimization cannot change semantic output or provenance requirements.

### A39.13 Cache/index architecture

There are three distinct storage concerns:

```text
Artifact/CAS store
    immutable feature bytes

Feature manifests + data catalog
    durable interpretation, provenance, policy, lineage, retention

Feature derivation projection
    CachePartitionKey + FeatureKeyDigest → verified FeatureManifest/ArtifactRef
    reconstructible acceleration only
```

Production may store the projection in the existing relational data/catalog store or a bounded cache/index technology selected by the data platform. Local development may use SQLite/filesystem indexes. Neither is a new system of record.

The lookup interface returns a typed reference/evidence object, never a raw trusted path.

### A39.14 Atomic materialization

The publication algorithm is:

```text
resolve requirements
→ compute FeatureKeyDigest
→ authorized projection lookup
→ if hit: verify manifest + artifact + contract + policy and return
→ if miss: execute under attempt/fence or local atomic lock
→ derive
→ semantic validation
→ canonical encode
→ compute payload digest
→ stage bytes
→ finalize CAS object
→ write immutable FeatureManifest
→ CAS/unique publish derivation projection
→ publish derivation receipt
```

The normal Artifact Platform staging/finalize rules are reused. No feature-specific object store protocol is introduced.

### A39.15 Concurrency, fencing, and determinism violation

Remote materialization uses the ordinary `Job`/`Run`/`Attempt`/`LeaseEpoch` lifecycle when durable work is needed. A stale feature-worker attempt can upload orphan staging bytes but cannot update authoritative catalog state or the derivation projection.

For duplicate requests:

```text
worker A derives FeatureKey K → artifact X
worker B derives FeatureKey K → artifact X
```

is safe deduplication.

```text
worker A derives FeatureKey K → artifact X
worker B derives FeatureKey K → artifact Y
X != Y
```

is not ordinary last-writer-wins behavior. It is a `DETERMINISM_VIOLATION`. The conflicting outputs and execution evidence are quarantined; new reads of K fail closed until resolution or a new corrected derivation identity is published.

### A39.16 FeatureManifest

`FeatureManifest` extends the common artifact manifest and records at least the fields below. `FeaturePlan` is the immutable DAG handoff used when derivation crosses a process boundary, and `FeatureDerivationReceipt` records the attempted key, fence/producer identity, output digest, validation, cache-hit/miss reason, and determinism result:

```text
FeatureContract reference and schema digest
FeatureKeyDigest
output ArtifactRef and encoding
logical axes/dimensions/value constraints
ordered source/canonical input refs
ordered upstream feature refs
derivation semantic operator/version
implementation or equivalence qualification digest
canonical semantic parameters
external snapshots/cutoffs/retrieval policy
validation evidence and diagnostic summary
determinism/cacheability/leakage class
security/data classification
producer source/build/attempt identity
```

Operational timestamps may be recorded but are not semantic key material unless the feature contract explicitly defines time as an input.

### A39.17 Read verification

A feature read verifies:

```text
manifest schema and supported version
FeatureContract compatibility
artifact digest/size/media type
manifest-to-payload integrity
FeatureKey/provenance closure where required
required upstream feature refs
logical axes and shape
value dtype/encoding
security/policy access
quarantine/revocation state
semantic validators selected by contract
```

Cache corruption is not silently normalized to a valid hit. Policy may evict the projection and regenerate from authorized immutable inputs; the corruption event remains evidence.

### A39.18 Biological and scientific validators

Representative validators include:

#### Sequence

```text
residue count matches canonical sequence
alphabet/component references valid
chain/residue mappings resolve
```

#### Structure

```text
atom → residue references valid
coordinates and masks align
coordinate frames/units valid
required finite-value policy holds
```

#### Pair/geometry

```text
pair axes correspond to the same declared residue set
distance values satisfy range/finite constraints
rigid frames satisfy orthogonality/tolerance policy
```

#### MSA/template when activated

```text
query length and canonical sequence mapping agree
external database/index snapshot is pinned
retrieval/filter/cutoff policy is present
row/template ordering is canonical
```

Scientific validation distinguishes invalid input, incompatible contract, transient infrastructure failure, corruption, leakage violation, and determinism violation.

### A39.19 FeatureBundle

A `FeatureBundle` is a small immutable manifest:

```text
model feature requirement contract/version
sample/canonical input identity
role -> FeatureManifest/ArtifactRef
bundle-level compatibility constraints
optional deterministic model-input artifact references
provenance closure digest
```

Example:

```text
CladeFold feature bundle
├── residue_type ─────── feat/artifact A
├── residue_index ────── feat/artifact B
├── relative_position ─ feat/artifact C
└── atom_mask ────────── feat/artifact D
```

The bundle does not duplicate A–D. Two models requesting the same semantic feature/key resolve the same permitted artifact while maintaining independent bundle/model-view identities.

### A39.20 Model feature views and tensorization

A model's `features/` package contains:

```text
requirements.py       semantic requirements and compatibility
derived_features.py   deterministic architecture-specific transformations
tensor_views.py       semantic value → model representation declarations
tensorize.py          framework tensor construction
packing.py            model-specific logical packing
validation.py         final ModelBatch validation
```

Representative interface:

```python
class ModelFeatureView(Protocol):
    def source_requirements(self) -> tuple[FeatureRequirement, ...]: ...
    def view_digest(self) -> str: ...
    def build(self, bundle: "FeatureBundle", context: "ModelViewContext") -> "ModelInput": ...
```

`ModelFeatureView` may depend on PyTorch because it lives in the model domain. Shared `bio/featurization/` contract types and `libs/python` foundations remain torch-free.

A model view must not silently repair incompatible scientific inputs. Compatibility failure is explicit before `forward()`.

### A39.21 Runtime stochastic transforms and logical RNG

Appendix A40 defines the common transform contract and ownership boundaries. Durable feature caching stops before ordinary training/request stochasticity.

Training derives runtime RNG from stable logical identity such as:

```text
run seed
phase
StepEpoch
stable sample identity
microbatch/packing identity
semantic transform purpose
```

The exact hierarchy remains the Appendix A14 RNG contract. A `BatchReceipt` records the resulting derivation identities, enabling replay without persisting every stochastic tensor.

If a stochastic derivation is intentionally promoted to a reusable artifact, it must be declared `SEEDED`, its logical seed/RNG identity enters `FeatureKeyDigest`, and the contract states why durable caching is correct.

### A39.22 Training integration

Training resolves:

```text
TrainingDatasetManifest
+ model release / FeatureRequirement contract
→ FeatureCoverageManifest
→ FeatureReadinessReceipt
→ per-sample FeatureBundle
→ model feature view
→ BatchRecipe + logical RNG
→ ModelBatch
→ BatchReceipt
```

Before expensive distributed admission, preflight SHOULD verify mandatory feature coverage and a sampled or policy-defined integrity set. Missing expensive durable features may trigger bounded pre-materialization jobs; they should not unexpectedly consume the optimizer step loop.

`FeatureCoverageManifest` records coverage per required semantic feature/version and identifies unresolved/quarantined samples by digest/reference.

`FeatureReadinessReceipt` records:

```text
dataset version
model/feature requirement contract
coverage manifest
external snapshot/cutoff identities
integrity verification evidence
leakage/policy result
unresolved count/sample-set digest
qualification result
```

### A39.23 BatchReceipt integration

Every prepared training batch records:

```text
stable sample identities
source shard references/offsets
FeatureBundleDigest and required feature manifest/artifact digests
materialized model-input artifact/view digest if any
packing/BatchRecipe digest
work-unit counts
logical augmentation/RNG identities
quarantine/exclusion decisions
```

This links an optimizer update to exact feature derivations without logging raw biological payloads.

### A39.24 Evaluation and leakage safety

Feature eligibility is part of an evaluation snapshot.

Leakage-sensitive features declare classes such as:

```text
SOURCE_LOCAL
DATASET_SNAPSHOT_SENSITIVE
SPLIT_SENSITIVE
TIME_SENSITIVE
RETRIEVAL_SENSITIVE
RUNTIME_ONLY
```

For retrieval/template/MSA-like features, `FeatureKeyDigest` and manifest include all identities that can change allowed information:

```text
query identity
database/index snapshot
release-date cutoff
retrieval algorithm/version
filter policy
thresholds
postprocessing policy
```

An evaluation suite declares maximum permitted snapshots/cutoffs. The leakage guard verifies feature manifests before execution. Missing provenance is not interpreted as evidence of safety.

### A39.25 Inference integration

Inference follows:

```text
authorized request
→ canonical input artifact/record
→ resolve released model FeatureRequirements
→ shared semantic FeaturePlan
→ authorized cache hits + materialized misses
→ FeatureBundle
→ model-owned feature view/tensorization
→ dynamic batching/runtime device view
→ model execution
```

The inference cache partition includes tenant/project or approved shared-domain scope and policy/security classification. Compatible CAS bytes may deduplicate beneath authorization, but batching/cache lookup may not reveal another tenant's object or broaden entitlement.

Request-specific sampling/diffusion randomness is not a semantic feature cache.

### A39.26 Security domains and classification

Content identity and authorization are intentionally distinct.

A feature artifact carries ordinary tenant/classification/retention policy. Cache projections are partitioned by a `SecurityDomain` such as:

```text
platform-public-qualified
mindclade-internal
restricted-dataset:<policy-class>
tenant:<tenant-id>
```

Exact names are implementation policy, not public resource identity.

Cross-domain reuse requires explicit authorization/declassification policy. A negative cache lookup must not reveal that an inaccessible matching artifact exists.

Derived artifacts inherit or elevate classification according to source/use policy. Cache keys/manifests/logs never contain raw sequences or structures merely to aid debugging.

### A39.27 Cache invalidation and schema evolution

Normal semantic changes do not require mutable invalidation:

```text
source changes
contract changes
semantic parameters change
snapshot/cutoff changes
derivation implementation/equivalence identity changes
schema interpretation changes
→ new FeatureKeyDigest
→ new immutable output
```

The old artifact remains historical evidence until retention policy makes it eligible for deletion.

A known defective derivation uses quarantine/revocation and lineage impact analysis. The projection is disabled; descendants are identified; corrected logic receives a new derivation/contract identity as appropriate. Published bytes are never patched in place.

### A39.28 Garbage collection, pins, and reachability

Feature-cache projection eviction and artifact deletion are separate.

The projection may evict entries based on bounded performance policy because it is reconstructible.

Artifact deletion follows Appendix A23 retention and reachability. Roots include applicable:

```text
released datasets
active or retained training runs and checkpoints
model releases
evaluation evidence
inference/agent result evidence
legal holds
manual governed pins
```

A feature artifact is collectable only when catalog/lineage/retention policy says it is unreferenced and no active lease/hold protects it. Cache age alone is insufficient.

### A39.29 Source blueprint and package map

The authoritative tree in Appendix A6 contains the activated namespace. The full responsibility map is:

```text
protocols/schemas/
├── feature_contract/
├── feature_requirement_set/
├── model_feature_view/
├── feature_manifest/
├── feature_bundle/
├── feature_plan/
├── feature_derivation_receipt/
├── feature_coverage_manifest/
└── feature_readiness_receipt/

bio/featurization/
├── contracts/
│   ├── feature_id.py
│   ├── feature_definition.py
│   ├── feature_requirement.py
│   ├── feature_requirement_set.py
│   ├── dimension_semantics.py
│   ├── determinism.py
│   └── leakage.py
├── catalog/
│   ├── feature_catalog.py
│   ├── sequence.yaml
│   ├── structure.yaml
│   └── geometry.yaml
├── python/
├── rust/
├── schemas/
├── validation/
├── parity/
└── tests/

data/featurization/
├── planning/
│   ├── feature_plan.py
│   ├── feature_plan_validation.py
│   ├── lower_to_transform_graph.py
│   └── cache_projection.py
├── derivation/
│   ├── operator.py
│   ├── feature_implementation_registry.py
│   ├── implementation_identity.py
│   └── canonical_parameters.py
├── resolution/
│   ├── resolver.py
│   ├── feature_key.py
│   ├── cache_partition.py
│   ├── coverage.py
│   └── explain.py
├── materialization/
│   ├── materialize.py
│   ├── validation.py
│   ├── atomic_publication.py
│   └── determinism_guard.py
├── manifests/
│   ├── feature_bundle.py
│   ├── feature_coverage.py
│   └── feature_readiness.py
├── storage/
│   ├── feature_index.py
│   ├── local_index.py
│   └── index_rebuild.py
├── feature_sharding.py
├── feature_receipt.py
└── tests/

models/families/<family>/<model>/features/
├── requirements.py
├── derived_features.py
├── tensor_views.py
├── tensorize.py
├── packing.py
└── validation.py

training/core/data/
├── feature_resolver.py
├── batch_recipe.py
├── feature_readiness.py
└── existing progress/receipt/prefetch modules

inference/pipeline/
├── preprocessing.py
├── feature_resolution.py
├── model_feature_views.py
├── model_execution.py
└── postprocessing.py

workers/feature_worker/
├── rust/src/
│   ├── main.rs
│   ├── attempt.rs
│   ├── plan.rs
│   ├── resolve.rs
│   ├── derive.rs
│   ├── validate.rs
│   ├── determinism.rs
│   ├── artifact_commit.rs
│   ├── cancellation.rs
│   └── telemetry.rs
├── python/
│   ├── reference_ops.py
│   └── parity_adapter.py
└── tests/
```

The `<family>/<model>` notation in this appendix is explanatory. Appendix A6 remains the exact activated path manifest and uses concrete model paths such as CladeFold; literal angle-bracket paths are never committed.

### A39.30 Language ownership

The feature system follows Appendix A4 rather than creating a new language lane.

**Python** owns scientific reference semantics, feature contract-facing transformations where research/scientific iteration dominates, model feature views/tensorization, and integration with training/evaluation/inference.

**Rust** owns high-throughput parsing/normalization hot paths, CPU-intensive derivation implementations, bounded-memory serialization, feature-worker execution and transfer hot paths, after parity with the semantic reference where required.

**Go** owns no scientific feature math. It may own control-plane job/resource state, quotas, authorization, and generic reconciliation for feature materialization jobs.

**Protobuf/JSON Schema** own cross-process commands/events and durable feature manifests/receipts.

`libs/python` remains torch-free. Feature-specific scientific code is not moved into `libs/` to make it look reusable.

### A39.31 Model-independent reuse example

Suppose three models require:

```text
Model A: residue_type, residue_index, pair_geometry, feature_D
Model B: residue_type, residue_index, pair_geometry, feature_E
Model C: residue_type, feature_F
```

The cache stores individual feature artifacts:

```text
residue_type ──────────────────────────┐
residue_index ───────────────┐         │
pair_geometry ───────┐       │         │
feature_D             │       │         │
feature_E             │       │         │
feature_F             │       │         │
                      ▼       ▼         ▼
                 model-specific FeatureBundle manifests
```

A bundle-only monolithic tensor cache that duplicates the common values is not the primary representation.

### A39.32 Physical encoding and semantic value

The initial implementation may equate one semantic feature value with one canonical artifact encoding for simplicity. The contracts reserve a future distinction between semantic value and physical representation so a proven need can support:

```text
one semantic feature value
├── canonical Arrow/columnar artifact
├── compressed CPU-oriented representation
└── accelerator-ready deterministic representation
```

This extension is deferred until profiling proves value. It must never allow two physical encodings to claim semantic equivalence without canonical value/equivalence evidence.

### A39.33 Serialization policy

Durable feature payloads use safe, documented, independently readable formats suitable for the value shape, such as Arrow IPC/Parquet or bounded array encodings. Arbitrary Python pickle or `torch.save` object graphs are prohibited as the canonical cross-model feature-cache format.

A feature encoding declares:

```text
media type and schema
logical axes
physical layout/compression
endianness/precision rules where relevant
canonicalization/digest rule
reader compatibility window
```

### A39.34 Feature planning cost and prefetch

A feature node may expose nonsemantic cost metadata:

```text
estimated CPU time
memory bound
expected output bytes
network/database dependence
GPU requirement if ever justified
```

The planner may use this for pre-materialization, scheduling, or recompute-versus-read decisions. Cost metadata never enters scientific meaning unless it changes the transformation itself.

Frontier training SHOULD run a feature readiness/pre-materialization phase so expensive cache misses do not unexpectedly stall accelerator work. Cheap deterministic features may remain JIT.

### A39.35 Explainability and developer tooling

Feature tooling must explain a hit or miss without requiring inspection of opaque cache paths.

Expected capabilities, implemented as data-domain tooling rather than a new service, include:

```text
inspect FeatureManifest/FeatureBundle
resolve a model's FeatureRequirements for a sample
explain FeaturePlan → TransformGraph lowering
explain hit/miss/key difference
verify artifact/manifests
compare two derivation identities/results
report dataset feature coverage
rebuild the cache projection from catalog/manifests
quarantine a defective derivation identity through governed APIs
```

Example diagnostic:

```text
MISS bio.template.hit_set@3
reason: SNAPSHOT_CHANGED
requested: pdb-template-index sha256:abc...
candidate: pdb-template-index sha256:def...
```

### A39.36 Observability

Bounded metrics include:

```text
feature_resolution_total{contract,result}
feature_cache_lookup_total{tier,result}
feature_cache_hit_ratio{contract}
feature_derivation_duration_seconds{contract,operator}
feature_validation_failure_total{contract,reason}
feature_determinism_violation_total{contract}
feature_artifact_bytes_read/written
feature_projection_rebuild_total
feature_coverage_ratio{contract,dataset_class}
feature_worker_lease_wait_seconds
```

Artifact/sample/key digests, raw accessions, sequences, structures, and unrestricted tenant IDs are not unbounded metric labels.

Traces may carry approved short digest prefixes or correlation IDs under cardinality/privacy policy and connect resolution → derivation → validation → artifact publication.

### A39.37 Failure taxonomy

Feature-specific failures map into the common error taxonomy while retaining typed reason:

```text
FEATURE_CONTRACT_MISMATCH
FEATURE_INPUT_INVALID
FEATURE_DEPENDENCY_MISSING
FEATURE_EXTERNAL_SNAPSHOT_UNAVAILABLE
FEATURE_LEAKAGE_POLICY_VIOLATION
FEATURE_SEMANTIC_VALIDATION_FAILURE
FEATURE_CACHE_CORRUPTION
FEATURE_MANIFEST_CORRUPTION
FEATURE_DETERMINISM_VIOLATION
FEATURE_AUTHORIZATION_DENIED
FEATURE_MATERIALIZATION_CANCELLED
```

Transient storage/network/snapshot availability may be retryable. Contract, biological validation, leakage, corruption with unresolved provenance, and determinism violations are not blindly retried into apparent success.

### A39.38 Testing and qualification matrix

Required test classes include:

| Test | Required result |
|---|---|
| canonical key golden | Rust/Python produce identical `FeatureKeyDigest` |
| same-input determinism | repeated derivation produces same canonical artifact/value digest |
| changed source | key changes |
| changed semantic parameter | key changes |
| changed external snapshot/cutoff | key changes |
| unqualified implementation change | key changes / old cache not reused |
| qualified equivalent implementation | parity within declared relation and approved equivalence identity |
| cross-model reuse | identical semantic requirement/key resolves same authorized feature artifact |
| model-view separation | same semantic artifact may produce distinct model views without changing shared contract |
| concurrent duplicate materialization | one logical mapping, same output digest |
| concurrent divergent materialization | determinism violation and quarantine |
| stale attempt | cannot publish projection/catalog success |
| corrupt payload/manifest | verification fails and impact is recorded |
| cross-tenant lookup | no existence or payload leakage |
| evaluation snapshot leak | disallowed/newer snapshot cache hit rejected |
| runtime stochastic transform | not resolved as ordinary durable shared feature hit |
| feature coverage | readiness receipt accurately reports unresolved/quarantined requirements |

### A39.39 CI gates

Presubmit for affected feature code runs:

```text
FeatureCatalog/schema validation
canonical key golden vectors
Bazel/native dependency-law checks
Python type/unit/property tests
Rust fmt/clippy/unit/property tests where applicable
cross-language parity
FeaturePlan lowering plus TransformGraph cycle/deterministic-plan tests
semantic validators
cache projection/atomic publication tests
model feature-view tests
```

Changes to stable derivations additionally run old/new qualification fixtures. Cache-compatible implementation changes require an explicit equivalence qualification artifact; a developer comment is insufficient.

### A39.40 Production failure injection

Before production use at scale, qualification injects:

```text
duplicate derivation jobs
worker crash after payload staging
worker crash after CAS finalize before projection update
stale lease/fence
object corruption
manifest corruption
projection loss and rebuild
database failover during projection publication
external snapshot timeout
policy revocation during materialization
conflicting deterministic outputs
cancellation during derive/validate/publish
```

The expected invariant is no false valid cache hit, no lost durable artifact truth, no cross-tenant disclosure, and no deterministic divergence hidden as success.

### A39.41 Wave mapping

#### Wave 2S

Implement only SQP-001 semantic features, local canonical keys, local CAS/index, manifests/bundles, model CladeFold views, and deterministic receipts. No MSA/template/ligand expansion.

#### Wave 3

Graduate `FeatureContract`, `FeatureManifest`, `FeatureBundle`, key canonicalization, model feature-view compatibility, and integrated inference/training evidence after both initial slices pass.

#### Wave 4

Activate remote `feature_worker` materialization where required, using generic job/attempt/fencing, durable artifact publication, tenant/policy cache partitions, corruption/retry tests, and projection rebuild.

#### Wave 5

Integrate feature readiness/coverage with distributed training admission and prefetch so accelerator runs consume frozen compatible feature artifacts without changing data-progress semantics.

#### Later model waves

Activate MSA/template/ligand/other expensive features only with real consumers, data rights, leakage policy, source snapshot semantics, registry contract, and qualification. Cross-model reuse is measured as evidence rather than assumed.

### A39.42 Migration from legacy/model-named caches

If Wave 0 discovers existing caches such as:

```text
cache/<model>/<sample>.pt
features/<pdb_id>.pkl
latest/features.parquet
```

migration is evidence-first:

1. inventory producer code, consumers, source identity, schema, parameters, and stochastic behavior;
2. classify each value as canonical record, reusable semantic feature, model-specific view, or runtime-only state;
3. define the correct `FeatureContract`/model-view contract;
4. reproduce old outputs on a legal fixture corpus;
5. assign explicit derivation implementation identity;
6. migrate only artifacts whose provenance can be proven;
7. quarantine or recompute ambiguous legacy entries;
8. dual-read only for a bounded migration window;
9. prohibit new writes to the legacy path;
10. remove compatibility code after consumer closure.

A legacy file is never blessed into the new cache solely because its filename looks familiar.

### A39.43 Prohibited anti-patterns

The following are `PROHIBITED` production patterns:

```python
features = torch.load(f"{cache}/{sample_id}.pt")
```

```text
cache/
├── cladefold/
├── clade1/
└── new-model/
```

as the primary semantic identity.

Also prohibited:

- one giant unversioned `make_features()` dictionary as the sole contract;
- model conditionals inside reusable biological feature semantics;
- source accession or row number as complete cache identity;
- mutable overwrite of a published feature object;
- silent implementation changes that reuse old cache keys;
- stochastic augmentation cached without explicit seed identity;
- evaluation cache reuse without snapshot/cutoff provenance;
- trusting cache existence without digest/schema/authorization verification;
- cross-tenant cache discovery or model batching merely for higher hit rate;
- direct model dependency on `data/featurization/` internals;
- moving feature-specific science into `libs/` to bypass domain ownership;
- treating local SSD/NVMe, Redis, a database index, or an object prefix as durable feature truth.

### A39.44 Acceptance gates

The feature architecture is qualified when:

1. every activated reusable feature has one semantic owner and `FeatureContract`;
2. key canonicalization is cross-language stable and fully declares semantic dependencies;
3. identical deterministic requests reproduce the same canonical output under their qualification envelope;
4. duplicate remote attempts cannot create ambiguous publication and divergent outputs fail as determinism violations;
5. cache/index loss is recoverable from durable artifacts/catalog/lineage;
6. cache reads verify artifact, manifest, schema, policy, and quarantine/revocation state;
7. at least one released model proves semantic-feature versus model-view separation; before Mindclade claims cross-model cache compatibility, at least two real model paths additionally demonstrate reuse of the same semantic artifact without sharing model tensorization code;
8. training `BatchReceipt`s identify exact feature bundles and stochastic RNG derivations;
9. evaluation rejects cache entries with disallowed or unprovable snapshot/cutoff provenance;
10. inference cache lookup/batching preserves tenant and policy isolation;
11. legacy/model-named mutable caches are absent from production paths;
12. MSA/template/ligand or other future feature families remain absent until activated by a real qualified consumer.

### A39.45 Definition of done

The subsystem is production-ready only when:

- feature semantics, derivation mechanics, storage/evidence, model views, and runtime stochasticity have separate owners and enforceable dependencies;
- a cache hit is explainable from a complete `FeatureKeyDigest`, not from path convention;
- immutable feature manifests close lineage to canonical inputs and external snapshots;
- model packages can change physical tensor views without mutating shared biological meaning;
- a scientific incident can trace a training update, evaluation score, or inference result through bundle → feature manifests → derivation identities → canonical/source artifacts;
- corruption, stale workers, duplicate delivery, implementation changes, source/snapshot changes, and policy changes fail safely;
- feature reuse improves cost/latency without weakening scientific correctness, leakage controls, reproducibility, authorization, or the artifact authority model.

### A39.46 Final feature invariants

- reusable feature meaning belongs to `bio/`, not to a cache implementation or model name;
- `data/featurization/` derives and materializes but does not own model mathematics;
- models own requirements and views but do not own shared cache truth;
- `FeatureKeyDigest` is complete, canonical, deterministic, and independent of physical path;
- immutable artifacts/manifests are evidence; cache indexes are projections;
- identical deterministic keys cannot legitimately resolve to different values;
- runtime stochasticity is explicit and receipt-replayable rather than silently cached;
- external snapshots and temporal/leakage constraints participate in feature eligibility and identity;
- cross-tenant deduplication never implies cross-tenant discovery or authorization;
- the architecture favors individual reusable feature artifacts plus bundle references over duplicated model-wide tensor blobs.
