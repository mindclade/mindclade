## Appendix A12 — Data platform architecture

### A12.1 Immutable pipeline stages

```text
Source descriptor
    -> raw object
    -> parsed record batch
    -> normalized snapshot
    -> curated dataset
    -> deduplicated/leakage-audited dataset
    -> split
    -> model feature dataset
```

Every arrow is a versioned transformation with:

- code revision;
- configuration digest;
- input digest set;
- output digest set;
- schema version;
- toolchain/runtime identity;
- validation report;
- policy classification;
- timestamps and actor identity;
- retry/idempotency key.

Do not mutate a published dataset version. Produce a new version.

### A12.2 Connector contract

Every source adapter implements the same lifecycle:

```text
discover -> plan -> fetch -> verify -> parse -> normalize -> publish
```

The adapter must support:

- resumable pagination/downloads;
- source rate limits and terms;
- conditional fetch or source revision detection;
- checksums and size verification;
- deterministic source object naming;
- idempotent replay;
- deletion/tombstone semantics;
- source-specific metadata;
- offline fixture mode for CI.

PDB, UniProt, RNACentral, and CCD are adapters, not bespoke pipeline frameworks.

### A12.3 Storage split

Use:

- object storage for raw source files, normalized shards, features, checkpoints, models, reports, and large logs;
- a relational metadata store for jobs, catalog entries, ownership, policy, lineage indexes, and artifact references;
- a queue or durable workflow substrate for execution;
- a cache only for reconstructible acceleration.

Never store model weights or full datasets in the relational database. Never treat an object-store prefix as the only source of catalog truth.

### A12.4 Content-addressed artifact reference

All large artifacts use a stable reference concept:

```text
ArtifactRef
- namespace
- logical name
- media type
- digest algorithm
- digest
- size
- schema version
- storage locator
- encryption/policy metadata
- lineage reference
```

Logical aliases such as `latest` may exist in the catalog but must resolve to an immutable digest before execution.

### A12.5 Dataset qualification

A training-eligible dataset version must have:

- schema validation;
- source integrity validation;
- biological invariant checks;
- deduplication report;
- train/evaluation leakage report;
- license and source-terms record;
- safety/policy classification;
- split manifest;
- feature compatibility declaration;
- stable sample-identity and source-offset schema;
- deterministic ordering/shuffle contract;
- packing and bucketing algorithm/version;
- expected shape and model-aware work-unit distributions;
- exclusion/quarantine-set digest;
- reproducibility record;
- dataset card.

### A12.6 Data-system planes and authority

The data platform separates:

```text
source control plane      discovers and plans external acquisition
data execution plane      fetches, parses, normalizes, curates, and featurizes
data artifact plane       stores immutable raw and derived objects
data catalog plane        indexes identity, lineage, policy, quality, and ownership
training-data plane       defines stable samples, ordering, packing, and work distributions
```

The catalog is authoritative for discoverability and lifecycle metadata. Object storage is authoritative for immutable bytes. Pipeline workers are authoritative only for a fenced attempt while producing a new artifact; they do not mutate published versions.

### A12.7 Core data contracts

#### `SourceDescriptor`

```text
source system and dataset
canonical source locator
terms/license reference
expected revision/version semantics
authentication class
rate-limit and access policy
data classification
connector implementation/version
```

#### `SourceObjectManifest`

```text
source descriptor and observed revision
request/response metadata safe for retention
raw object digest, size, media type, encoding
conditional-fetch validators
fetch attempt and timestamps
integrity verification
storage artifact reference
```

#### `SnapshotManifest`

```text
ordered source-object set
source completeness/watermark
schema and normalization version
excluded/tombstoned objects
validation and policy report
parent snapshot and change summary
```

#### `DatasetManifest`

```text
logical dataset identity and version
input snapshots and transformations
record/shard inventory
schema and statistics
curation, deduplication, leakage, and split reports
sample identity contract
policy/license classification
quality and qualification status
```

### A12.8 Connector API

A connector is deterministic with respect to a source revision and plan.

```python
class DataConnector(Protocol):
    def discover(self, request: DiscoveryRequest) -> DiscoveryResult: ...
    def plan(self, discovery: DiscoveryResult) -> FetchPlan: ...
    def fetch(self, item: FetchItem, context: FetchContext) -> SourceObjectManifest: ...
    def verify(self, artifact: ArtifactRef, expected: FetchItem) -> VerificationReport: ...
```

Discovery and planning are side-effect free except for bounded source queries. Fetch is retryable and idempotent. Parsing and normalization are separate domain transformations rather than hidden connector behavior.

### A12.9 Ingestion lifecycle and state machine

```text
DISCOVERED
→ PLANNED
→ FETCHING
→ FETCHED
→ VERIFIED
→ PARSED
→ NORMALIZED
→ VALIDATED
→ PUBLISHED

Any nonterminal state
→ RETRYABLE_FAILURE
→ prior safe state

Any state
→ QUARANTINED or TERMINAL_FAILURE
```

State transitions are durable, attempt-fenced, and idempotent. Raw bytes become visible as an immutable source artifact only after digest and size verification. A published normalized snapshot never references an uncommitted raw object.

### A12.10 Source revision and change semantics

Connectors classify source change as:

- append-only release;
- mutable current snapshot;
- individually versioned records;
- replacement/deletion/tombstone stream;
- date/versioned archives;
- API without stable revision.

For sources without reliable revision identifiers, Mindclade creates an observed snapshot identity from discovery time, ordered object inventory, response validators, and content digests. The limitation is recorded; it is not presented as stronger reproducibility than the source supports.

### A12.11 Rate limits, politeness, and terms

Connector plans encode:

```text
concurrency
requests per interval
bandwidth
retry/backoff and Retry-After
allowed hours if required
user-agent/contact policy
cache and conditional-fetch policy
terms/license constraints
```

Rate limits are shared across worker attempts through a durable or coordinated limiter where required. Retries do not create abusive amplification. Source terms can block publication or downstream use even when fetching technically succeeds.

### A12.12 Raw, parsed, normalized, curated, and feature artifacts

Each stage is independently addressable:

| Stage | Purpose | Mutability |
|---|---|---|
| raw | preserve exact source bytes | immutable |
| parsed | typed source-faithful records | immutable |
| normalized | canonical Mindclade biological semantics | immutable |
| curated | selected/corrected policy-approved records | immutable |
| deduplicated/leakage-audited | identity and contamination controlled | immutable |
| split | stable train/validation/test partition | immutable |
| feature | model-ready representation | immutable |

Recomputing a later stage does not require refetching if prior immutable artifacts remain valid and policy permits reuse.

### A12.13 Catalog architecture

The catalog indexes but does not duplicate large artifacts. It stores:

```text
resource identity and aliases
artifact digests and locations
schema, producer, and lineage edges
owner and access policy
quality and validation summaries
source/license terms
retention, legal hold, and deletion state
usage and downstream references
qualification and promotion status
```

Catalog writes use transactions and outbox events. Search indexes and caches are rebuildable. A storage locator may change while artifact identity and digest remain stable.

### A12.14 Lineage graph

Every transformation edge records:

```text
transformation name/version
code and container revision
configuration digest
ordered or set-valued input identities
output identities
runtime/toolchain
actor/attempt
validation reports
policy decisions
start/end and resource usage
```

Lineage supports:

- upstream/downstream impact analysis;
- exact reconstruction;
- source/license audit;
- invalidation after schema, code, or policy defects;
- quarantine propagation;
- deletion and legal-hold analysis;
- training/evaluation contamination investigation.

### A12.15 Deterministic partitioning and sharding

Shards are produced by a declared algorithm using stable record identities. A shard manifest includes record ranges or identity sets, ordering, count, byte size, schema, and digest.

Parallel execution may complete out of order, but publication order is deterministic. Repartitioning creates a new artifact version even when record content is unchanged because physical layout affects performance and possibly training data progress.

### A12.16 Stable sample identity

A sample identity is derived from semantic source identity and transformation policy, not row number or storage path. It must survive:

- shard relocation;
- parallelism changes;
- catalog reindexing;
- compression changes;
- deterministic feature regeneration;
- supported schema migration.

When a transformation changes sample meaning, it produces a new sample identity or identity version. Compound/complex samples record ordered constituent identities and assembly/selection policy.

### A12.17 Curation and correction model

Curation changes are explicit overlays or transformations, never manual mutation of a published shard. A curation record includes:

```text
target record/sample identity
rule or reviewer decision
before/after semantic digest
reason and evidence
actor and review
applicability window
supersession relation
```

Automated and human curation use the same provenance model. High-impact manual corrections require review and may need dual control.

### A12.18 Data quality framework

Quality dimensions include:

- completeness;
- schema validity;
- biological/chemical coherence;
- source consistency;
- duplication and near duplication;
- contamination/leakage;
- label confidence;
- temporal/source coverage;
- class and modality balance;
- shape/work-unit distribution;
- licensing and policy completeness;
- reproducibility.

Each dataset declares thresholds by use class. A training dataset may have different requirements from a discovery-only catalog dataset, but failures and waivers remain visible.

### A12.19 Deduplication contract

Deduplication separates:

```text
exact byte duplicate
exact canonical record duplicate
sequence identity/near identity
structure/geometry similarity
chemical graph identity
complex/assembly overlap
feature-level duplicate
source alias
```

Algorithms, thresholds, indexes, and tie-breaking are versioned. The output records duplicate clusters, retained representative, excluded members, and rationale. Deduplication cannot silently erase source lineage.

### A12.20 Leakage prevention

Leakage analysis is defined relative to named evaluation and release suites. It may include:

- exact and near sequence overlap;
- structural/template overlap;
- ligand/component overlap;
- temporal cutoff violations;
- shared complex constituents;
- derived feature contamination;
- benchmark source duplication;
- homolog/family thresholds.

The leakage report identifies algorithm/version, thresholds, reference sets, suspected and confirmed overlaps, exclusions, and residual risk. Evaluation datasets are access-controlled where necessary to reduce accidental contamination.

### A12.21 Split contract

A split manifest declares:

```text
input dataset digest
algorithm and seed
stratification/grouping keys
temporal or source constraints
leakage constraints
ordered sample identities per split
statistics and balance report
exceptions
```

Grouping keeps related entities together when required. Regenerating a split with a new algorithm or seed creates a new version. “Random split” without a stored algorithm, seed, and identity list is prohibited.

### A12.22 Featurization architecture

Featurization consumes canonical biological records and versioned `FeatureContract`s. The architecture distinguishes five layers:

```text
canonical biological records
→ reusable semantic feature values
→ optional deterministic model-specific derived features
→ model-owned tensor views / packing
→ runtime stochastic transforms and device views
```

`bio/featurization/` owns the meaning of reusable semantic features: identifiers, dimensions/axes, dtype/value constraints, normalization meaning, missingness, determinism, cacheability, leakage sensitivity, and biological validators. `data/featurization/` owns feature requirement resolution, `FeaturePlan`, feature-specific lowering constraints, materialization policy, cache projection, coverage, sharding, publication, and lineage; generic graph validation/planning/execution remains in `data/transforms/`. A model family publishes requirements against those contracts and owns only model-specific deterministic derivations, tensorization, embedding/bucket mappings, packing, and runtime layouts.

A reusable semantic feature produces:

- a `FeatureContract` reference and schema digest;
- logical dimensions/semantic axes and value constraints;
- source/canonical-record and upstream-feature references;
- derivation semantic operator and implementation/equivalence identity;
- canonical semantic parameters;
- external database/tool snapshot and cutoff references where applicable;
- determinism, cacheability, leakage, and security classification;
- immutable feature payload plus `FeatureManifest`;
- validation, exclusions, diagnostics, shape/work-unit statistics, and lineage.

Rust may own hot-path extraction, graph execution, serialization, and I/O; Python owns scientific semantics/reference paths where appropriate. An optimized Rust derivation may share a semantic identity with a Python reference only after explicit parity/equivalence qualification. Cross-language parity is qualified on shared fixtures.

#### A12.22.1 Feature derivation identity

`FeatureKeyDigest` is computed from canonical encoding of:

```text
output FeatureContract identity/version/schema digest
ordered input canonical-record or artifact references and roles
ordered upstream FeatureManifest/artifact references and roles
derivation semantic operator and semantic version
exact implementation digest OR approved semantic-equivalence-class digest
canonical semantic parameters
external source/database/tool snapshots and temporal cutoffs
policy values that alter scientific output
seed/RNG identity only for explicitly seeded cacheable derivations
```

The key MUST NOT depend on filesystem path, mutable alias, source accession alone, dataset row number, Python `repr`, unordered map iteration, process/rank identity, hostname, worker attempt, or wall-clock time. A change in any declared semantic dependency produces a new key rather than invalidating or overwriting an old object.

Security partitioning is separate from scientific value identity. A cache lookup uses a `CachePartitionKey` containing tenant/project or approved shared-domain scope, applicable policy/security class, and `FeatureKeyDigest`. CAS may deduplicate identical authorized bytes, but the lookup layer cannot reveal or authorize a cross-tenant hit merely because content exists.

#### A12.22.2 Determinism and cacheability classes

Each feature declares one determinism class:

```text
PURE                same immutable inputs/parameters always produce the same semantic value
SNAPSHOT_DEPENDENT  output also depends on explicit external snapshot/tool/index identity
SEEDED              output also depends on a declared logical RNG/seed identity
RUNTIME_STOCHASTIC  per-step/request randomness; ordinary durable shared cache prohibited
```

Each derivation also declares `durable`, `opportunistic`, `memory_only`, or `forbidden` cacheability. Training crop, masking, augmentation, diffusion noise, dropout, template/MSA random sampling, device casts, and padding are `RUNTIME_STOCHASTIC` or runtime views unless an explicit higher-level contract proves otherwise.

#### A12.22.3 Derivation DAG

A `FeaturePlan` is a DAG of nodes whose outputs are individually addressable feature artifacts. Planning resolves model `FeatureRequirement`s to semantic contracts, expands declared dependencies, computes keys, checks verified cache projections, prunes hits, and schedules only misses. Bundles therefore reference reusable nodes instead of serializing duplicated monolithic dictionaries.

A derivation operator cannot inspect an arbitrary model class, read undeclared mutable global configuration, use undeclared randomness or network databases, publish directly to the catalog, or mutate an upstream artifact. The executor owns policy, cancellation, validation, canonical encoding, publication, and evidence.

### A12.23 Feature storage and access

Feature payloads use the ordinary immutable artifact/CAS architecture. `FeatureManifest` records interpretation/provenance; `ArtifactDigest` records bytes. The data catalog indexes durable feature metadata and lineage. A feature-cache index maps a tenant/policy partition plus `FeatureKeyDigest` to a verified feature manifest/artifact reference and is explicitly reconstructible; loss of this index degrades performance but not scientific truth.

Feature datasets and individual feature artifacts support:

- content-addressed objects/shards;
- manifest-driven discovery and bundle references;
- column/field projection;
- range/random access;
- streaming and prefetch;
- integrity and manifest verification on read;
- compression selected by measured workload;
- schema evolution and partial regeneration;
- feature coverage/readiness manifests for expensive training runs;
- locality/memory/NVMe caching hints that remain noncanonical;
- reachability/retention through ordinary artifact catalog references and leases.

A cache hit is accepted only after manifest/schema/digest/dependency/policy verification. Corrupt or incomplete objects fail as `DATA_LOSS`/quarantine; they are not silently trusted because the lookup index contains a row. Policy may regenerate from immutable inputs when safe.

Publication is:

```text
compute canonical FeatureKeyDigest
→ check authorized verified projection
→ acquire/validate attempt fence where remote
→ derive missing DAG node
→ semantic validation
→ canonical encode and hash
→ stage payload
→ finalize immutable CAS object
→ publish immutable FeatureManifest
→ compare-and-swap derivation projection
→ emit receipt/evidence
```

Concurrent attempts for a deterministic key may publish/deduplicate the same output digest. If valid attempts produce different semantic/payload digests for the same key, publication records `DETERMINISM_VIOLATION`, quarantines conflicting results, invalidates the projection, and requires investigation. It must not choose “first writer wins” and hide the divergence.

Training never infers feature schema, sample order, bundle membership, or cache validity from filenames, directory listing order, or model-named cache roots.

### A12.24 Quarantine, invalidation, and tombstones

A defect may affect one sample, a shard, a transformation version, or all descendants. Quarantine records are immutable and propagated through lineage impact analysis.

Policy actions include:

```text
block new use
allow existing run to finish
require restart from a clean checkpoint
exclude samples through a new manifest
invalidate derived artifacts
retain under legal hold
schedule deletion
```

Published artifacts are not edited in place. A corrected version supersedes them and records the relationship.

### A12.25 Deletion and retention

Deletion is reference- and policy-aware:

1. mark requested deletion/tombstone;
2. evaluate legal hold, license, audit, and downstream references;
3. prevent new use;
4. expire leases and aliases;
5. delete physical replicas according to policy;
6. retain minimal immutable audit and digest metadata where legally permitted;
7. verify deletion completion.

Training checkpoints and model releases retain dataset manifest references even if payload access later becomes restricted.

### A12.26 Data security and access

Access decisions consider tenant/project, data classification, source terms, intended use, geography, and workload identity. Controls include:

- bucket/prefix/project isolation for restricted classes;
- workload identity and short-lived credentials;
- egress restrictions;
- encryption and key policy;
- signed URL scope and lifetime;
- access audit;
- payload-free logs;
- derived-data classification inheritance;
- approved declassification or aggregation process.

### A12.27 Data workflow orchestration

Mindclade uses a durable job/workflow substrate rather than embedding orchestration in connector code. Work units are idempotent and artifact-mediated. The control plane owns desired jobs; workers own bounded attempts; the catalog records published outputs.

A workflow can resume from the latest verified stage artifact. It never relies solely on temporary worker disk or in-memory task state.

### A12.28 Data observability

Metrics and durable reports include:

```text
objects/records/bytes discovered and fetched
source latency, rate-limit, and retry behavior
checksum and parse failures
diagnostic code distribution
throughput and memory
normalization exclusions
quality, duplicate, and leakage statistics
shard balance and feature shape/work distribution
cache hit and storage cost
quarantine/invalidation propagation
lineage publication latency
```

Source URLs, sample identifiers, sequences, structures, and credentials are not metric labels.

### A12.29 Data qualification gates

#### DQ0 — contracts

Source, artifact, snapshot, dataset, sample identity, and lineage schemas pass validation.

#### DQ1 — connector correctness

Offline fixtures, pagination, resume, rate limits, checksums, idempotency, and source-change behavior pass.

#### DQ2 — biological transformation

Parsing, normalization, curation, and feature parity pass domain fixtures.

#### DQ3 — dataset integrity

Deduplication, leakage, split, quality, license, and policy evidence pass.

#### DQ4 — scale and recovery

Corpus-scale throughput, bounded memory, partial failure, retry, and deterministic publication pass.

#### DQ5 — training eligibility

Stable sample identities, ordering, packing/bucketing, work distributions, duplicate/skip detection, and model compatibility pass.

### A12.30 Capability-local qualification progression

1. Implement artifact/source/snapshot/dataset/sample/lineage schemas and catalog core.
2. Implement connector runtime plus PDB, UniProt, RNACentral, and CCD adapters.
3. Implement parsing/normalization and immutable snapshot publication.
4. Implement curation, quality, deduplication, leakage, and split manifests.
5. Implement feature contracts, canonical `FeatureKeyDigest`, `FeaturePlan` → `TransformGraph` lowering, cache projection, individual feature artifacts/bundles, and training dataset manifests with stable identity and work-unit statistics.
6. Add feature coverage/readiness, cross-language key/parity tests, determinism-race and cache-corruption qualification, quarantine propagation, retention/deletion, and production-scale qualification.

### A12.31 Definition of done

1. Every stage is immutable, versioned, and independently reproducible.
2. Source bytes and source-faithful parsed records remain auditable.
3. Catalog identity is separate from physical storage location.
4. Connector retries and duplicate delivery cannot publish duplicate or inconsistent artifacts.
5. Samples retain stable identities across physical re-layout.
6. Deduplication, leakage, split, and curation decisions are explicit artifacts.
7. Training consumes only qualified manifests with deterministic ordering and progress semantics.
8. Quarantine and deletion propagate through lineage without editing published data.
9. Restricted biological data is controlled through identity, egress, logging, and retention policy.
10. Feature-cache projection loss is recoverable without loss of scientific truth, and cache hits are accepted only through complete canonical derivation identity plus verification.
11. Model-specific tensor views remain outside shared biological feature semantics, and runtime stochastic transforms remain receipt-replayable rather than ordinary durable shared cache.
