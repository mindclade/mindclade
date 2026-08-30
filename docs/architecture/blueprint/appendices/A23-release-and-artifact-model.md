## Appendix A23 — Release and artifact model

There is no monorepo version.

| Artifact | Version identity |
|---|---|
| Internal service/worker image | Git revision plus immutable OCI digest |
| Python/TypeScript public SDK | Semantic version |
| Go/Rust internal library | Source revision; public extraction gets independent semantic version |
| Protobuf API | Package version plus compatibility baseline |
| Dataset | Immutable logical version plus content digest |
| Feature dataset | Feature schema version plus source/config digest |
| Training dataset manifest | Dataset/feature digests plus sample-identity, ordering, packing, mixture, and work-distribution schema |
| Batch receipt | Batch identity plus ordered sample/source/packing/RNG digest |
| Checkpoint generation | Logical checkpoint schema plus state epoch, content digest, and parent lineage |
| Evaluation snapshot | Selected logical state plus checkpoint/publication, plan, phase, and code digests |
| Training recipe | Recipe schema version plus immutable configuration digest |
| Training phase graph | Phase/edge schema plus immutable task, data, optimization, and transition digests |
| Hardware topology manifest | Discovered hardware/connectivity/software identity plus measurement digest |
| Executable plan | Plan schema plus model, state, topology, pass, collective, provider, and compilation digests |
| Provider manifest | Capability set plus provider versions, constraints, state mapping, and qualification digests |
| Compiled region | Graph/guard/compiler/hardware digest plus generated binary and qualification evidence |
| Training run manifest | Run identity plus recipe, phase, plan, provider, dataset, checkpoint, code, image, and policy digests |
| Step capsule | Step epoch plus BatchReceipts, RNG roots, plan/provider/kernel summaries, and numerical evidence |
| Autotune record | Search-space/version plus model, shape/work distribution, topology, environment, and provider digests |
| Scientific study/trial | Study schema plus immutable trial inputs, results, and promotion decision |
| Rollout/trajectory dataset | Immutable policy, environment, reward, generator, and input lineage plus content digest |
| Model bundle | Model family version plus immutable manifest digest |
| Kernel bundle | Implementation/toolchain digest plus qualification matrix |
| Evaluation report | Suite, snapshot/model, dataset, code, statistical method, and result digest |
| Deployment package | Package version/digest; environment promotion references immutable artifacts |

### A23.1 Release manifest

Every release job emits a manifest containing:

- source revision;
- build target;
- dependencies and lockfile digests;
- toolchain and compiler identity;
- output artifacts and digests;
- SBOM references;
- provenance and attestation references;
- test and qualification report digests;
- signer/build identity;
- promotion eligibility.

Promotion copies or references the same artifact. It never rebuilds from source for each environment.

### A23.2 Training run evidence

A production training run publishes a run manifest at initialization and finalizes it at termination. It records:

```text
immutable inputs
resolved phase graph
hardware topology
executable-plan lineage
provider and compiled-region manifests
checkpoint and evaluation lineage
worker attempts and recovery events
reproducibility claim
qualification level
terminal outcome
```

Mutable dashboards and process-local logs are not the run record.

### A23.3 Artifact authority and catalog model

An artifact is immutable content plus a manifest that explains identity, interpretation, lineage, policy, and qualification. The catalog is the durable index of artifacts; object storage holds bytes.

```text
Artifact
  logical namespace/name/type
  immutable generations
  content and manifest digests
  aliases resolved through revisions
  lineage and policy
  retention/leases/legal hold
  qualification/promotion status
```

A storage object without a committed catalog generation is staging or orphaned data, not a release artifact.

### A23.4 Artifact generation state machine

```text
RESERVED
→ UPLOADING / BUILDING
→ STAGED
→ VERIFYING
→ COMMITTED
→ PROMOTED
```

A generation may instead become `FAILED`, `ABANDONED`, `QUARANTINED`, `REVOKED`, or eventually `DELETED` under policy. `COMMITTED` content never mutates. Promotion changes catalog relationships/status, not bytes.

### A23.5 Common artifact manifest

Every artifact manifest contains, where applicable:

```text
artifact type and schema version
logical name and immutable generation
media type, size, digest, and shard inventory
source revision and build/transformation target
input artifact digest set and lineage
configuration, lockfile, toolchain, image, and environment digests
producer and worker/build attempt
policy/data classification, encryption, and access scope
compatibility and runtime requirements
qualification/evidence references
SBOM, license, provenance, and signatures
retention, lease, legal-hold, and revocation metadata
```

Type-specific manifests extend this common envelope rather than replacing it.

### A23.6 Content and manifest identity

The byte digest identifies content; the manifest digest identifies interpretation and provenance. Two generations may reference identical bytes while carrying different logical purpose or policy, but deduplication must not weaken authorization, retention, or audit.

Digest algorithms and canonical encodings are explicit and upgradeable. A digest mismatch is corruption or attack and fails closed.

### A23.7 Sharded artifacts

Datasets, checkpoints, models, and large reports may be sharded. A shard manifest records ordered/logical membership, per-shard digest/size/media type, placement hints, and completeness rules. The parent commits only after every required shard verifies.

Consumers resolve through the parent inventory. Listing an object-store prefix is not a completeness protocol. Partial, duplicate, unexpected, or mixed-generation shards invalidate publication.

### A23.8 Alias semantics

Aliases such as `latest`, `production`, `candidate`, or human-friendly model names are mutable catalog resources with revisions and policy. Before execution, an alias resolves to:

```text
immutable artifact generation
resolution time and actor
alias revision
policy decision
```

The resolved generation is embedded in the job/run manifest. Resume and reproduction never re-resolve a mutable alias.

### A23.9 Build-once and promotion

Promotion flow is:

```text
build/transform once
→ commit immutable generation
→ qualify exact generation
→ attach signed release/evidence manifest
→ promote catalog status or copy by digest where registry mechanics require
→ GitOps/runtime consumes exact digest
```

No environment rebuilds source. Copying to another registry/storage boundary verifies source and destination digest and preserves original lineage/provenance.

### A23.10 Release channels

Artifact types may use channels:

```text
experimental
candidate
internal
staging
production
revoked/deprecated
```

Channels are policy and compatibility constructs, not mutable tags without history. Promotion requires type-specific evidence, approval, and destination eligibility. Demotion/revocation preserves audit and does not rewrite historical run records.

### A23.11 Software release artifacts

OCI images, wheels, npm packages, binaries, and deployment packages include:

- locked dependencies;
- SBOM;
- build provenance and source revision;
- compiler/toolchain/build flags;
- supported platforms;
- signatures/attestations;
- license/notice inventory;
- vulnerability policy result;
- installation and runtime smoke evidence;
- compatibility/deprecation metadata.

Production images contain only declared runtime/provider groups and run as non-root where feasible. Debug tooling is separately packaged or access-controlled.

### A23.12 Model bundle release

A model release requires:

```text
immutable logical weights/state
model configuration and state schema
FeatureRequirementSetRef + ModelFeatureViewRef + model input-contract compatibility
tokenizer/component compatibility
TransformStateArtifact/FitReceipt compatibility where fitted preprocessing is part of the release
precision/quantization/calibration state
supported inference/training capabilities
provider/kernel/compiled-region compatibility
conversion history
scientific, robustness, safety, and systems evaluation
model card and intended-use policy
license/distribution/access controls
```

A checkpoint is not automatically a model release. Conversion to a bundle selects only required logical state, validates inference parity, and records losses or omissions.

### A23.13 Dataset and feature release

A dataset release contains source and license records, lineage, canonical schema, quality/dedup/leakage/split reports, sample identity, policy classification, and dataset card. A feature release additionally records semantic `FeatureContract`s, `FeatureKeyDigest` derivation identity, immutable inputs/upstream feature references, transformation implementation or qualified equivalence identity, external snapshots/cutoffs, validation, model compatibility, packing/indexing where the released feature dataset owns it, work-unit distribution, and reproducibility evidence. Ordinary cache-index entries are not releases; promotion/release is a catalog decision over immutable artifacts and manifests.

Source deletion or license change may trigger quarantine/revocation and downstream impact analysis without rewriting historical lineage.

### A23.14 Checkpoint generation lifecycle

Checkpoint generations follow the Appendix A14 snapshot and atomic commit protocol. Artifact release adds:

- catalog registration and parent/fork lineage;
- recovery versus durable tier;
- retention and active-run/evaluation leases;
- migration/conversion eligibility;
- promotion to model bundle;
- corruption/revocation response.

Recovery checkpoints may have shorter retention and narrower portability, but every advertised recovery point remains integrity verified.

### A23.15 Evaluation and evidence artifacts

Reports, per-sample results, step capsules, profiler traces, and qualification evidence are immutable artifacts with classification and retention. Rendered documents are derived from machine-readable source reports. A release manifest links exact evidence digests rather than copying scalar claims.

### A23.16 Provenance and attestation

Provenance states who/what built the artifact, from which source and dependencies, with which parameters, on which platform, and what outputs resulted. Attestations are signed statements such as:

```text
build provenance
SBOM generation
qualification passed
vulnerability/policy scan
promotion approval
model/data safety review
```

Signatures bind digest and predicate. Verification policy defines trusted issuers, identity constraints, source repository, branch/tag, builder, and freshness. A valid signature from an untrusted builder is insufficient.

### A23.17 SBOM and license policy

Software artifacts include machine-readable dependency inventories covering language packages, system libraries, native binaries, base images, and embedded third-party sources where possible. License notices are generated and reviewed.

Models and datasets use analogous source/component inventories appropriate to their domain, including upstream checkpoints, vocabularies, chemical dictionaries, databases, and training data/license references.

### A23.18 Vulnerability and defect response

When a defect or vulnerability is discovered:

1. identify affected artifact generations through lineage/SBOM;
2. classify exploitability/scientific impact;
3. quarantine or revoke future use;
4. notify owners and downstream deployments/runs;
5. patch/rebuild/requalify into a new generation;
6. promote the replacement;
7. preserve historical evidence and incident record;
8. update retention/deletion only under policy.

Artifacts are never overwritten “in place” to hide an affected version.

### A23.19 Compatibility and support windows

Every released artifact declares compatible consumers/environments and support status. Examples:

```text
SDK ↔ API versions
model bundle ↔ inference runtime, FeatureRequirementSet, ModelFeatureView, and model input contract
checkpoint ↔ model/state schema and migration graph
kernel bundle ↔ hardware/runtime/compiler ABI
OCI image ↔ deployment package/CRD versions
dataset ↔ feature/model requirements
```

Compatibility is evidence-backed and time-bounded. Unsupported combinations fail before execution.

### A23.20 Retention, leases, and deletion

Retention considers:

- artifact type and channel;
- active jobs/runs;
- checkpoint/evaluation leases;
- parent/child lineage;
- reproducibility and audit requirements;
- legal hold;
- customer/tenant deletion policy;
- cost and storage tier.

Deletion is two-phase: mark ineligible, verify no protected references/leases, then remove bytes and record a tombstone. Catalog/audit metadata may remain according to policy. Garbage collection is idempotent and never infers liveness solely from storage prefixes.

### A23.21 Replication and disaster recovery

Critical artifacts declare replication class, region/failure domains, recovery point objective, and verification cadence. Replication copies immutable content by digest and confirms manifests/signatures. Catalog backups and object bytes are recoverable together.

Disaster-recovery drills restore selected release artifacts into a clean environment and verify signature, lineage, installation/load, and runtime behavior.

### A23.22 Access and distribution

Access decisions combine principal, tenant/project, artifact classification, intended operation, region/environment, and policy version. Transfer authorization is short-lived and scoped to exact generation/range/action.

Public distribution is a separate promotion requiring public license, safety, privacy, export, and documentation review. An internally qualified artifact is not automatically publishable.

### A23.23 Registry and storage abstraction

`ArtifactRef` abstracts storage, but not semantics. Storage adapters implement reserve, transfer, verify, commit, read/range, replicate, and delete. Catalog transactions own generation state and aliases.

Direct cloud URIs may appear in internal transfer tickets but are never durable public identity. Storage migration updates locators while preserving artifact identity, digest, and lineage.

### A23.24 Release orchestration and approvals

A release candidate resolves an immutable `ReleaseManifest` and a required evidence policy. Approval roles may include engineering owner, scientific/evaluation owner, security/safety owner, and operations owner depending on artifact risk.

Approvals bind the exact manifest digest. Any artifact or evidence change invalidates approval. Emergency release paths are time-bounded, audited, and require post-release review.

### A23.25 Rollback and revocation

Rollback selects a previously qualified immutable artifact; it does not rebuild old source. Deployment/runtime records the rollback reason and target digest. Data/model schema compatibility must be checked before rollback.

Revocation policy distinguishes:

```text
prevent new use
stop or checkpoint active use
remove deployment
restrict download/access
retain for incident/audit only
```

Historical run manifests continue to reference revoked artifacts with status visible.

### A23.26 Artifact and release qualification levels

| Level | Required evidence |
|---|---|
| `artifact-a0` | manifest/schema, digest/size verification, immutable commit |
| `artifact-a1` | lineage, compatibility, install/load/read round trip, retention metadata |
| `artifact-a2` | signatures, SBOM/license/provenance, policy and access controls |
| `artifact-a3` | promotion/rollback/revocation, replication/restore, downstream conformance |
| `artifact-a4` | sustained production use, incident drills, support window and audit evidence |

Type-specific scientific or numerical qualification is additionally required.

### A23.27 Capability-local qualification progression

**Milestone 0 — common artifact contract:** `ArtifactRef`, generation state, manifests, upload/verify/commit, aliases, and lineage.

**Milestone 1 — software and scientific artifacts:** OCI/wheel/npm plus dataset, feature, checkpoint, model bundle, evaluation report, and run evidence schemas.

**Milestone 2 — trusted release:** SBOM, provenance, signing, promotion policy, GitOps handoff, rollback/revocation, and lease-aware retention.

**Milestone 3 — resilience and distribution:** replication/DR drills, public/internal channels, storage migration, vulnerability impact analysis, and support windows.

### A23.28 Definition of done

The release and artifact model is production-ready when:

1. every durable large output is a committed immutable generation with a verified manifest;
2. content identity and interpretation/provenance identity are both explicit;
3. aliases resolve to immutable generations before execution and resolution is recorded;
4. sharded artifacts cannot publish partially or mix generations;
5. promotion references the same built bytes and binds exact evidence and approvals;
6. software artifacts include SBOM, provenance, signatures, and installation/runtime qualification;
7. datasets/models/checkpoints/reports carry complete domain lineage and policy;
8. retention, leases, legal hold, revocation, replication, and deletion are enforced from catalog truth;
9. rollback selects a prior immutable qualified artifact without rebuilding;
10. a clean environment can verify, restore, and run the released artifact from its evidence bundle.

### A23.29 Final release invariants

- no monorepo-wide version obscures artifact-specific lifecycles;
- object bytes are not authoritative without a committed manifest;
- builds happen once and promotion never recompiles;
- signatures are evaluated against trusted identity policy, not merely cryptographic validity;
- every release decision binds exact artifacts and evidence;
- revocation and rollback preserve history and lineage;
- mutable aliases are never execution inputs after resolution.
