## 1. Executive summary

Mindclade SHALL use a domain-first polyglot monorepo to develop and operate generative models and bounded agents for programmable biology. The architecture joins scientific semantics, contract sources, implementation, qualification, and release metadata in one atomic change boundary while keeping live environment state and foundational cloud trust in separately controlled repositories.

The default production shape is a Go modular control-plane monolith plus specialized Rust and Python workers. It is not a microservice fleet. Python/PyTorch owns models, training, evaluation, inference semantics, and scientific workflows; Rust owns biological parsing, feature construction, bulk transfer, and CPU-sensitive data paths; Go owns durable workflow state, reconciliation, authorization, policy enforcement, and Kubernetes control; TypeScript owns supported applications and browser/server client experience. Protobuf owns internal RPC, durable commands, events, and lifecycle contracts. JSON Schema owns manifests, evidence, and human-authored configuration. If later activated, qualified TileLang/CUDA implementations sit behind operation contracts with PyTorch reference implementations and mandatory fallback.

Reusable feature computation follows the same authority model. `bio/` owns canonical biological and reusable semantic feature meaning; `data/featurization/` owns derivation planning, materialization, cache projection, coverage, and publication; `workers/feature_worker/` executes fenced derivations; model families own only model-specific feature requirements, deterministic views, tensorization, and packing. Feature cache state is reconstructible acceleration over immutable artifacts and manifests, never a fifth system of record or a model-named mutable directory.

Feature derivation is a specialization of the repository-wide transform dataflow contract rather than a second DAG engine. `data/transforms/` owns the generic typed `TransformGraph`, semantic/execution identity separation, planning, fitting-state contract, lineage-map compaction, execution adapters, and receipts. `data/featurization/` resolves `FeatureRequirement`s, computes feature-specific identity/cache policy, and lowers `FeaturePlan` into the generic transform graph. Model views and runtime stochastic transforms remain outside shared feature semantics.

The monorepo defines four separate authorities that MUST never be conflated:

| Authority | Canonical source | Operational realization |
|---|---|---|
| Intended code and contracts | protected Git revision in this monorepo | hermetic build closure |
| Durable business and workflow state | control-plane relational database | transactions, audit, idempotency, outbox |
| Immutable scientific and execution evidence | content-addressed object storage plus catalog metadata | signed manifests and digests |
| Live environment desired state | separately protected GitOps/environment repositories | reconciled GKE and cloud resources |

This document is an approved target architecture, not evidence that the target exists. Version 3.4.3 reconciles 2,487 canonical paths against the greenfield repository, its Wave 0 governance sources, and the five operational source repositories. The 386 Wave 1 paths remain target-only and absent. ADR-0008, `FounderBootstrapException/v1`, and FBE-0001 establish the `FOUNDER_BOOTSTRAPPED` source-only state for the public GitHub Free repository-level profile; `production_authority` remains `false`. That source authority does not prove connected GitHub controls, independent review, signed CI evidence, later-wave capabilities, deployment, or production readiness. Those claims remain `INCONCLUSIVE` until their named executable gates pass.

### 1.1 Finalization outcomes

This revision makes the following material reconciliations:

| Issue | Authoritative resolution |
|---|---|
| Fragmented chapter milestones | Section 15 is the sole cross-repository implementation sequence. Appendix milestones are capability-local qualification guidance only. |
| Optional paths versus no empty scaffolds | Section 4 lists required namespaces and an activation-gated path register. A conditional path MUST NOT exist before its first real target and owner. |
| Reserved Go/Rust SDK directories | Removed from the active tree. Public Go/Rust SDKs are deferred and create their directories only after an approved consumer and compatibility commitment. |
| Competing training frameworks | Native PyTorch is the only production execution substrate. Other frameworks are qualified capability providers or intake sources behind Mindclade contracts. |
| Training lifecycle terminology | `Operation`, `Job`, `Run`, `Attempt`, `Workload`, `Phase`, `ExecutablePlan`, `Checkpoint`, and `Release` have one definition in Section 6. |
| Generated code ambiguity | Protobuf generated sources are committed under `protocols/generated/` and drift-checked; build-derived validators, OpenAPI bundles, and published SDK transports are generated reproducibly and handled as stated in Section 6. |
| Deployment ownership ambiguity | `deploy/` owns service-shipped Kubernetes packages, local integration, and CRDs. It MUST NOT contain production overlays, cluster foundations, secrets, or live desired state. |
| Agent architecture gap | `agents/`, MADK, control-plane entities, worker boundaries, tool receipts, sandboxing, policy, evaluation, and release evidence are first-class parts of the lifecycle. |
| Development-kit duplication risk | MCDK–MADK are governed façades over canonical domains; they own authoring experience and assemblies, never scientific or operational truth. |
| Blueprint status ambiguity | All design statements are classified as approved target, wave scope, deferred, prohibited, or evidence-backed implemented. No item is `IMPLEMENTED` without repository and test evidence. |
| Wave 0 governance load | Wave 0 ratifies only seven expensive-to-reverse foundational ADRs. All other decisions are recorded now but receive standalone ADR ratification immediately before the first wave that depends on them. |
| Oversized initial vertical | Wave 2 contains two independently qualifying slices: a local scientific slice and a CPU/local platform slice. Neither waits for the other, Kubernetes, the console, agents, or development kits. |
| Ambiguous first workload | `SQP-001` freezes one protein-only PDB dataset, one reduced Pairformer model, one supervised structure head, one small coordinate-diffusion head, and exact CPU/H100 qualification gates. |
| Premature technology breadth | The critical-path allowlist is native PyTorch, DeviceMesh/DTensor, FSDP2, DCP, NCCL, Kueue/JobSet, and reference PyTorch kernels. All named provider/optimization systems remain intake candidates until a measured gap exists. |
| Premature contract stabilization | Wave 1 freezes only the cross-system contract kernel. Dataset, model, checkpoint, evaluation, inference, agent, kit, kernel, and deployment schemas stabilize with their owning waves. |
| Migration before evidence | The first Wave 0 artifact is a repository drift report covering the actual tree, dependency graph, ownership, contracts, releases, duplicate authorities, and compatibility-aware moves. |
| Repository-estate ambiguity | The monorepo tree now includes an exhaustive activation-stub contract. Repo-local `mindclade/.github/` is distinct from the organization `.github` repository, and `.github`, `github-config`, `bootstrap`, `infrastructure-live`, and `gitops` each have a canonical file tree, sole owner, apply identity, state boundary, test gates, and recovery behavior. |
| Cross-model feature-cache ambiguity | Reusable biological feature meaning is owned by `bio/`; derivation/materialization and cache projection are owned by `data/featurization/`; models own only model-specific feature views/tensorization. `FeatureKeyDigest` captures complete derivation semantics, immutable feature artifacts are CAS-addressed, cache indexes are reconstructible and tenant/policy partitioned, and stochastic runtime transforms never masquerade as ordinary durable feature cache entries. |
| Feature/data transform ambiguity | Transform composition is now explicit and layered: `data/transforms/` owns transform graph/spec/execution contracts, existing `data/{normalization,curation,deduplication,splits,sampling,...}` packages own their domain semantics, `bio/featurization/` owns reusable semantic feature transforms, models own model-view transforms, and training/inference own runtime batch transforms. `TransformSpec`, `TransformGraph`, and `TransformReceipt` make cardinality, ordering, state, determinism, RNG, schema, snapshots, lineage, and side effects explicit without introducing a universal workflow or feature-store authority. |
| Repository-tree completeness | Appendix A6 now enumerates every approved target file path explicitly. Brace-expansion shorthand is prohibited in authoritative trees; previously namespace-only leaf stubs now list their concrete first-file surfaces or are represented as generated-output paths. The five operational repository trees are likewise fully expanded. Future private files are not silently implied: adding one updates the machine-readable path manifest in the same change. |
| Repository-tree authority duplication | `docs/architecture/repository-path-manifest.yaml` is now the machine-readable path authority. Appendix A6 remains fully explicit but is generated deterministically from that manifest; CI compares manifest, rendered tree, actual populated paths, owners, waves, Bazel targets, and activation status. |
| Duplicate feature/transform planners | `TransformGraph` is the sole generic dataflow graph/planner substrate. `FeaturePlan` is a feature-domain request/evidence artifact that lowers into a constrained `TransformGraph`; `data/featurization/` no longer owns a parallel cycle/partition/execution planner. |
| Fitted-transform state gap | `TransformStateArtifact`, `FitSemanticKey`, and `FitReceipt` make fit/apply transforms explicit for normalization statistics, vocabularies, calibration state, learned projections, clustering state, and other fitted data transformations. Evaluation can prove fitting scope and prevent leakage. |
| Transform identity ambiguity | Transform semantic identity is separated from `TransformExecutionPlanDigest`. Backend, worker count, partitioning, fusion, spill, and materialization placement are execution choices unless a contract explicitly makes them semantic. |
| Transform-spec ceremony | A small common `TransformSpec` base now has typed profiles for map, filter, explode, join, aggregate, fitted, semantic-feature, and runtime-stochastic transforms. Class-specific fields are mandatory only where relevant. |
| Registry terminology ambiguity | `FeatureCatalog` and `TransformCatalog` own semantic declarations; `ImplementationRegistry` owns qualified executable implementations; `ArtifactCatalog` owns published immutable artifact metadata. Generic runtime plugin discovery is not an authority. |
| Model/training feature boundary | Model bundles now distinguish `FeatureRequirementSetRef`, `ModelFeatureViewRef`, input contract, and output contract. Training receives model-view outputs before task-owned runtime batch transforms; `TrainingTask` cannot rediscover semantic features or model tensorization. |
| Corpus-scale lineage overhead | Persisted transforms may reference a compact `LineageMapArtifact`/membership index that deterministically reconstructs per-sample lineage instead of emitting billions of expanded edges. |
| Remote feature/transform protocol breadth | Remote commands carry immutable plan/graph artifact references plus `AttemptId`, `LeaseEpoch`, and deadline; queue messages do not embed large transform graphs or feature payloads. |
| Materialization inefficiency | Transform planning may use non-semantic cost hints for compute, read I/O, output size, reuse, fan-out, and recovery value. Cost estimates may alter execution/materialization choices but never semantic identity. |
| Blueprint maintenance load | The combined blueprint remains the full review artifact but is generated from ordered, smaller source files plus machine-readable manifests. Humans edit the smaller sources; CI renders and verifies the combined document. |

### 1.2 Normative language and precedence

`MUST` and `MUST NOT` are mandatory. `SHOULD` is the default and requires a recorded, owner-approved exception to deviate. `MAY` is optional within all surrounding controls.

When provisions conflict, precedence is:

```text
law, contracts, privacy, security, and biological-safety obligations
→ architecture constitution in Appendix A34
→ Sections 1–18 of this document
→ approved superseding ADR with migration and expiry
→ normative domain appendices
→ examples and informative implementation notes
```

An ADR cannot waive law or safety. Exact dependency versions belong in lockfiles and release evidence, not prose. The architecture owner SHALL update this document when an ADR changes a constitutional or cross-domain decision.

### 1.3 Readiness vocabulary

| Label | Meaning | Required evidence |
|---|---|---|
| `IMPLEMENTED` | Present and conforming in the identified repository revision | source target, tests, owner, build evidence, and relevant qualification |
| `TARGET` | Approved architecture; implementation may be absent | this specification and accepted ADR |
| `WAVE-n` | Target committed to implementation wave n | prerequisites and exit gate in Section 15 |
| `DEFERRED` | Deliberately outside the critical path | activation criteria, owner, and no placeholder code |
| `PROHIBITED` | Violates an invariant | policy rule or constitutional provision |
| `INCONCLUSIVE` | Evidence needed to decide is unavailable or insufficient | named missing evidence and verification owner |

### 1.4 Production-readiness conclusion

The architecture is source-ready under the bounded founder-bootstrap exception. The system is not connected- or production-ready. Wave 0 MUST bind these target decisions to the actual repository, produce the authoritative repository drift baseline, create machine-readable ownership and dependency metadata, establish contract/build baselines, and independently ratify the eight foundational ADRs in Section 14 before `CONNECTED_QUALIFIED`. Production use remains prohibited until the applicable wave gates and Section 16 acceptance evidence pass.
