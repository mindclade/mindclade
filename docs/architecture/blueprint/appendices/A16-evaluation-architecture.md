## Appendix A16 — Evaluation architecture

Evaluation is independent of training loops and serving APIs.

An evaluation suite defines:

- immutable dataset references;
- input transformation;
- model/inference contract;
- required logical state selection;
- metrics;
- aggregation;
- uncertainty/statistical method;
- pass/fail thresholds;
- report schema;
- reproducibility settings;
- safety policy.

### A16.1 Evaluation classes

- unit numerical checks;
- model-component parity;
- model-family regression;
- structure and complex prediction quality;
- sequence representation/generation;
- molecular design objectives;
- confidence calibration;
- robustness and perturbation;
- data leakage;
- runtime performance;
- distributed consistency;
- safety and policy qualification.

### A16.2 Snapshot and lease contract

Training publishes an immutable evaluation snapshot rather than granting an evaluator access to mutable trainer state.

```text
trainer commits snapshot manifest
-> evaluation worker acquires lease
-> evaluator loads selected logical components
-> immutable report is published
-> lease releases
-> retention may delete only after every lease expires
```

A snapshot records:

```text
checkpoint or lightweight publication identity
logical state selection
model and state-schema digests
recipe, phase, executable-plan, provider, and code digests
dataset and evaluation-suite digests
publication and retention policy
```

Asynchronous evaluation policies declare maximum staleness for early stopping, phase transitions, or promotion decisions. A stale or failed evaluation never silently approves a release.

Every model release references an immutable evaluation report digest. Dashboard state is not release evidence.

### A16.3 Evaluation-system planes

Evaluation is organized into distinct authority planes:

```text
scientific question and suite definition
→ immutable inputs and execution protocol
→ metric/statistical aggregation
→ report, threshold decision, and promotion evidence
```

Top-level `evaluation/` owns what is measured and what constitutes acceptable evidence. `training/evaluation/` only schedules snapshots and tracks trainer-side leases. Inference provides the pure execution path. Workers provide operational composition. The control plane stores durable references and decisions but does not reinterpret metric meaning.

### A16.4 Evaluation suite contract

A suite is a versioned, immutable definition:

```python
from dataclasses import dataclass
from typing import Mapping, Sequence

@dataclass(frozen=True, slots=True)
class EvaluationSuite:
    suite_id: str
    schema_version: int
    tasks: tuple["EvaluationTask", ...]
    datasets: tuple["EvaluationDatasetRef", ...]
    inference_policy: "InferencePolicy"
    aggregation: "AggregationPlan"
    statistics: "StatisticalPlan"
    thresholds: tuple["ThresholdRule", ...]
    reproducibility: "ReproducibilityPolicy"
    safety_policy: "EvaluationSafetyPolicy"
```

The suite defines all preprocessing, sampling, postprocessing, metric versions, subset rules, missing/error handling, uncertainty estimation, and threshold semantics. It contains no mutable aliases after resolution.

### A16.5 Evaluation task contract

An evaluation task defines:

```text
scientific capability under test
required model capability and logical state selection
input feature transformation
inference/sampling procedure
prediction/output schema
metric set and versions
aggregation units and grouping keys
validity/exclusion rules
resource and determinism profile
```

Tasks do not import a training loop or inspect mutable model internals. Shared inference code is called through stable APIs. Any special evaluator-only hook is part of the model capability contract and receives compatibility tests.

### A16.6 Dataset and cohort contract

An evaluation dataset manifest contains:

- immutable data/feature digests;
- stable sample and cohort identities;
- inclusion/exclusion criteria;
- source/license/policy classification;
- leakage and temporal-cutoff evidence;
- subgroup labels approved for evaluation;
- expected missingness and label quality;
- weighting and stratification rules;
- challenge-set or perturbation construction;
- reproducible ordering and shard mapping.

Published scores always name the exact dataset version. Hidden/private benchmark sets use sealed references and controlled worker access; their identifiers and score summaries may be public while payloads remain restricted.

### A16.7 Snapshot selection and model loading

An evaluation consumes an immutable `EvaluationSnapshotManifest` or released model bundle. The snapshot selection declares:

```text
base model state
EMA versus raw state
adapter/head selection
quantization/calibration state
FeatureRequirementSetRef and ModelFeatureViewRef/input-contract digest
TransformStateArtifact/FitReceipt references and fitting scope where used
tokenizer/component versions
precision and kernel/provider constraints
checkpoint schema and migration path
```

The evaluator verifies every digest before execution. Partial logical-state loading is allowed only when the suite proves the omitted state is irrelevant. A mutable trainer object or process-local pointer is never an evaluation input.

### A16.8 Inference protocol for evaluation

Evaluation execution freezes:

- batching and packing behavior;
- shape buckets and padding;
- precision and accumulation policy;
- provider, kernel, and compiled-region choices;
- random seed and sample-key derivation;
- number of recycles, diffusion samples, or decoding candidates;
- sampler/solver and guidance parameters;
- confidence and ranking algorithms;
- timeout and invalid-result behavior.

A score cannot be compared across runs when execution differences exceed the suite's declared equivalence class. Changes create a new suite or execution-protocol version.

### A16.9 Metric contract

Each metric provides:

```text
name and semantic version
input and target schema
units, scale, and directionality
per-sample computation
validity domain and missing-value behavior
aggregation unit
weighting and subgroup semantics
uncertainty method
reference implementation and fixtures
numerical tolerance
```

Metric names alone are insufficient. For structure metrics, alignment, atom/residue selection, symmetry handling, chain mapping, coordinate frame, and unresolved residues are explicit. For generative metrics, validity filtering, candidate selection, diversity, novelty, and sampling budget are explicit. For calibration, binning or continuous scoring and confidence interpretation are explicit.

### A16.10 Aggregation semantics

The suite distinguishes:

```text
micro aggregation over observations
macro aggregation over samples/entities/cohorts
weighted aggregation
hierarchical aggregation across complexes, chains, and residues
best-of-N or top-ranked candidate evaluation
paired model comparison
```

A mean of per-batch means is prohibited unless equivalent to the declared unit. Aggregation retains numerators, denominators, counts, invalid/missing counts, and subgroup support. Distributed evaluators merge associative sufficient statistics rather than pre-rounded scalar summaries.

### A16.11 Statistical plan

A `StatisticalPlan` specifies:

- estimand;
- paired or unpaired comparison;
- confidence interval or credible interval method;
- bootstrap/permutation/randomization procedure;
- clustering unit for dependent observations;
- multiple-comparison correction;
- minimum sample/subgroup support;
- practical significance margin;
- non-inferiority/superiority/equivalence rule;
- random seed and resampling count;
- treatment of invalid or censored outcomes.

Release decisions distinguish statistical significance from practical significance. Repeated benchmark probing and threshold tuning require governance to avoid overfitting the evaluation set.

### A16.12 Threshold and decision contract

Threshold rules are typed:

```text
absolute floor or ceiling
relative regression budget
non-inferiority margin
subgroup floor
safety hard stop
performance/cost budget
confidence/calibration budget
required absence of critical failures
```

A release decision records each rule's input report, result, uncertainty, waiver if any, owner, and expiry. A dashboard color or manually copied scalar is not a promotion decision.

### A16.13 Evaluation classes and required evidence

**Numerical/component evaluation** validates operation and module semantics.

**Model regression evaluation** detects behavior changes on stable fixtures and representative cohorts.

**Scientific capability evaluation** measures sequence, structure, complex, design, confidence, and multimodal quality.

**Robustness evaluation** applies perturbations, missing modalities, noise, length/size extremes, adversarial shapes, and out-of-distribution cohorts.

**Safety evaluation** evaluates policy-defined misuse, restricted generation, biological-risk screening, and refusal/containment behavior where product surfaces expose generation.

**Systems evaluation** measures latency, throughput, memory, cost, cancellation, and distributed consistency without conflating these with scientific quality.

### A16.14 Structure and complex evaluation

Structure suites explicitly define:

- reference assembly and chain mapping;
- polymer/non-polymer inclusion;
- resolved atom/residue masks;
- alternate locations and symmetry;
- rigid or flexible alignment;
- ligand/cofactor handling;
- interface and per-chain metrics;
- stereochemistry and physical-validity checks;
- confidence-to-error calibration;
- candidate ranking and best-of-N reporting.

A single global score is accompanied by stratification across sequence length, complex size, modality, taxonomic/source cohort, disorder/missingness, ligand class, and novelty where policy and statistical support permit.

### A16.15 Sequence and representation evaluation

Sequence suites may include:

```text
masked/corrupted prediction
likelihood or pseudo-likelihood
retrieval and clustering
function/property probes
zero/few-shot transfer
controlled generation validity
novelty and diversity
constraint satisfaction
```

Probe training data, hyperparameters, splits, and selection criteria are immutable artifacts. Probe performance is not presented as intrinsic representation quality without the declared protocol.

### A16.16 Diffusion, flow, and design evaluation

Generative structure/design evaluation records:

- sample count and random roots;
- sampler/solver, steps, and schedules;
- conditioning and guidance;
- validity and failure filters;
- diversity and mode-collapse metrics;
- structural/chemical constraints;
- energy or surrogate-model versions;
- novelty/database search version;
- confidence and ranker behavior;
- wet-lab or simulator evidence when available.

Best-of-N quality is always reported with N and compute budget. Invalid samples remain in denominators according to suite policy; they are not silently dropped.

### A16.17 Confidence, uncertainty, and calibration

Confidence outputs are evaluated for:

```text
calibration error and proper scoring rules
coverage-risk curves
selective prediction
per-residue/per-atom/per-interface reliability
group calibration and tail behavior
ranking quality
uncertainty under perturbation or ensemble sampling
```

Confidence semantics identify the predicted event or error quantity. Calibration transformations are versioned model state or release artifacts and are not fitted on the final test cohort.

### A16.18 Leakage controls

Evaluation rejects leakage from:

- exact or near-duplicate training samples;
- shared chains, complexes, scaffolds, or homologous families beyond declared thresholds;
- future source revisions in temporal benchmarks;
- model-selection access to hidden test labels;
- feature caches built from disallowed databases or time horizons;
- cache hits whose `FeatureManifest` cannot prove the required database snapshot, temporal cutoff, retrieval/filter policy, and derivation identity;
- repeated manual tuning against challenge sets.

Leakage reports identify algorithm, index/database versions, thresholds, unresolved cases, excluded sample digests, and the accepted feature-manifest/key identities. Evaluation feature resolution fails closed when provenance is missing or when a snapshot/cutoff is newer or broader than the suite policy. Ambiguous cases default to quarantine or separate reporting.

### A16.19 Distributed evaluation

A distributed plan defines:

```text
immutable sample-to-rank assignment
retry and duplicate suppression
partial-result schema
associative metric state
failure/restart boundary
candidate artifact ownership
final aggregation fence
```

Sample results are idempotent and keyed by suite, snapshot, sample, inference configuration, and attempt. A stale evaluator attempt cannot overwrite a completed valid result. Partial reports are never marked final.

### A16.20 Lease and retention semantics

The control plane or evaluation scheduler issues a lease over the snapshot and required artifacts. The lease has owner, expiry, heartbeat, attempt, and purpose. Retention must preserve leased state plus the minimum parent lineage needed to reproduce it.

On lease loss, a worker stops publishing, safely completes or abandons local work, and allows a fenced retry. Lease renewal failure does not convert an incomplete report into success.

### A16.21 Failure and invalid-result taxonomy

Classify at least:

```text
invalid input under suite contract
feature preparation failure
model load/schema incompatibility
resource exhaustion
numerical failure
sampler non-convergence
metric undefined
artifact publication failure
worker/lease failure
policy denial
```

The suite declares whether each class counts as an invalid prediction, excluded input, infrastructure retry, or terminal suite failure. Infrastructure failures cannot improve a model score by removing hard examples.

### A16.22 Evaluation report schema

An immutable report contains:

```text
suite and dataset manifests
snapshot/model bundle and logical-state selection
inference/executable-plan/provider/kernel digests
code, image, toolchain, and hardware identity
sample counts and failure taxonomy
metric sufficient statistics and aggregates
uncertainty intervals and subgroup results
threshold-rule outcomes
leakage and safety evidence
performance/cost summary
artifacts and representative diagnostics
signer, provenance, and report digest
```

Reports separate raw machine-readable results from rendered summaries. Rendered HTML/PDF is derived and names the source report digest.

### A16.23 Reproducibility and comparison

A report states whether reproduction is bitwise, numerical, or statistical and over which dimensions. Pairwise comparisons require aligned sample sets and protocol compatibility. When historical reports use incompatible suites, migration recomputes from preserved per-sample results or labels the comparison invalid rather than normalizing by hand.

### A16.24 Safety, privacy, and biological governance

Evaluation workers receive only the data classifications they are approved to process. Controls include:

- restricted dataset isolation and egress policy;
- payload-minimized logs and diagnostics;
- protected hidden benchmark labels;
- controlled access to generated high-risk biological artifacts;
- report redaction/publication policy;
- audit of evaluator and operator access;
- retention and legal-hold handling;
- explicit policy for human-derived data and subgroup reporting.

### A16.25 Evaluation telemetry and operations

Operational telemetry includes queue age, snapshot age, lease state, sample throughput, invalid/failure classes, GPU utilization, metric aggregation lag, artifact publication latency, and report finalization. Scientific metric values remain report evidence; selected bounded summaries may be exported for dashboards.

Runbooks cover stuck leases, corrupted snapshots, metric regressions, leakage discoveries, hidden-set exposure, statistical instability, and artifact-retention conflicts.

### A16.26 Evaluation qualification levels

| Level | Required evidence |
|---|---|
| `evaluation-e0` | suite/schema validation, metric unit fixtures, deterministic local execution |
| `evaluation-e1` | complete single-worker report, snapshot loading, failure accounting, reproducibility |
| `evaluation-e2` | distributed shard/merge equivalence, duplicate suppression, lease/restart behavior |
| `evaluation-e3` | leakage, robustness, subgroup/statistical, and safety evidence |
| `evaluation-e4` | release-threshold governance, historical comparison, production performance and operations |
| `evaluation-e5` | long-term benchmark integrity, independent review, and production release decision evidence |

### A16.27 Capability-local qualification progression

**Milestone 0 — suite and report contracts:** build dataset, metric, statistics, threshold, snapshot, and report schemas with one CPU fixture.

**Milestone 1 — CladeFold vertical suite:** evaluate one immutable snapshot on a small structure/complex cohort with geometry, confidence, failure, and reproducibility evidence.

**Milestone 2 — asynchronous production flow:** add evaluation worker leases, distributed sharding, immutable per-sample results, aggregation fencing, and retention integration.

**Milestone 3 — release qualification:** add leakage, robustness, safety, statistical comparison, subgroup support, and signed promotion decisions.

### A16.28 Definition of done

Evaluation is production-ready when:

1. every score is attributable to exact suite, dataset, snapshot, execution, and metric digests;
2. aggregation retains correct units, counts, numerators/denominators, and failure semantics;
3. distributed and single-worker results are equivalent under the declared contract;
4. asynchronous leases cannot expose mutable state or permit stale publication;
5. statistical and practical significance rules are frozen before final evaluation;
6. leakage and hidden-set access are controlled and evidenced;
7. invalid/infrastructure failures cannot silently improve reported quality;
8. reports are immutable, machine-readable, signed/provenanced, and release-linked;
9. safety and data-classification rules apply to inputs, outputs, logs, and reports;
10. dashboards are derived views and never the sole release evidence.

### A16.29 Final evaluation invariants

- evaluation meaning is independent of training and serving lifecycles;
- every report consumes immutable state and immutable datasets;
- metrics are versioned contracts, not bare function names;
- aggregation and uncertainty match the scientific unit of inference;
- release thresholds are governed, auditable decisions;
- failed or stale asynchronous work cannot approve a model;
- every model release names exact evaluation evidence.
