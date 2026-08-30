## Appendix A7 — Dependency laws

These laws are more important than the visual tree.

### A7.1 Layered dependency direction

```text
public lane:
  protocols ----------------------------> sdk ----------------> apps
  canonical domains --------------------> kits

foundation and domain lanes:
  protocols -> libs
  libs + protocols -> bio -> data
  libs + protocols -> runtime -> kernels

model lane:
  bio + runtime + kernels -> models

execution domains:
  models + data + runtime + kernels + evaluation contracts -> training
  models + runtime + kernels + minimal data/postprocessing contracts -> inference
  models + inference + data contracts + metrics libraries -> evaluation
  public domain contracts + policies + sdk clients -> agents

composition roots:
  data -> ingestion / feature workers
  training -> training worker
  inference -> inference worker
  evaluation -> evaluation worker
  agents -> agent worker
  protocols + selected libs -> control-plane and gateway services
```

The notation describes allowed dependency direction, not a requirement that every package consume every listed predecessor. In particular, `data/` and `models/` remain sibling domains: model packages publish feature requirements and batch contracts without importing data-pipeline implementations, while data pipelines satisfy those contracts through explicitly named featurization boundaries. Reusable feature meaning flows `bio/featurization contracts → data/featurization derivation/materialization → immutable feature artifacts`; model families consume the contracts/artifacts and apply model-owned views without creating a reverse source dependency from `data/` into model implementations.

Services and workers are composition roots. SDKs depend on public protocols, not on
service implementation packages.

The diagram is directional, not a claim that every node depends on every predecessor.

### A7.2 Import rules

1. `protocols/` may not depend on implementation packages.
2. `libs/` may depend on `protocols/` and other lower-level libraries within the same language, but never on domain packages.
3. `bio/` may depend on `libs/` and `protocols/`; it may not depend on data pipelines, models, training, services, workers, SDKs, or apps.
4. `data/` may depend on `bio/`, `libs/`, and `protocols/`; it may not depend on model implementations except through an explicitly named featurization contract. `data/transforms/` owns only transform composition/execution contracts and may call domain-owned data operators through registered interfaces; it MUST NOT absorb curation, split, biological, or model semantics. `data/featurization/` may resolve model-declared requirement documents/artifact schemas as data, but must not import a model family implementation or PyTorch tensorization code.
5. `runtime/` may depend on `libs/` and `protocols/`; it may not contain model-specific policy.
6. `kernels/` may depend on `runtime/` and narrow foundational utilities; it may not import training loops or service code.
7. `models/` may depend on `bio/`, `kernels/`, `runtime/`, and selected `libs/`; it may not import `data/transforms/` or `data/featurization/` implementation, training engines, network services, SDKs, or apps. A model's `features/` package references semantic feature contracts/artifacts and owns model-specific deterministic transforms, views, and tensorization.
8. `training/` may depend on models, data, evaluation contracts, runtime, and kernels.
9. `evaluation/` may depend on models, inference, data contracts, and metrics libraries; production model code must not depend on evaluation suites.
10. `inference/` may depend on models, runtime, kernels, and a minimal set of data/postprocessing contracts.
11. `agents/` may depend only on public domain contracts, policy APIs, artifact references, and supported SDK clients. It may not deep-import model, training, data, evaluation, inference, service, or worker internals, and domain packages may not depend on agent implementations.
12. `kits/` may compose public contracts, generators, validation, SDKs, and CLI entrypoints. It may not contain an alternate data, model, trainer, evaluator, agent, cloud-state, or release implementation.
13. `services/` and `workers/` are composition roots. No foundational or domain package may import from them.
14. `sdk/` consumes generated protocol clients and public hand-written convenience layers; it does not import service implementation code.
15. `apps/` consume SDKs and design-system packages only. They do not import generated database types, Go internals, model code, or agent runtime internals.
16. `research/` may import production code. Production code may never import from `research/`.
17. `deploy/` references packaged components and generated configuration schemas; application code must not parse live environment overlays from `deploy/`.
18. `data/featurization/` owns feature requirement resolution, `FeatureKeyDigest`, cache projection, feature validation, and lowering from `FeaturePlan` into `data/transforms/` `TransformGraph`. Generic DAG validation, partition planning, optimization, backend selection, and execution MUST live only in `data/transforms/`; a parallel feature-specific graph/planner stack is prohibited.
19. `FeatureCatalog` and `TransformCatalog` own build-visible semantic declarations; `ImplementationRegistry` owns only explicitly built and qualified executable implementations. Runtime registration MUST NOT create new scientific/data semantics, and `ArtifactCatalog` remains the durable artifact authority.
20. A fitted transform may consume training-eligible immutable inputs to produce a `TransformStateArtifact`, but apply paths consume that artifact by digest and MUST NOT refit, mutate, or infer fitting scope from ambient process state.

### A7.3 Cross-language boundaries

Allowed cross-language mechanisms:

- Protobuf RPC or messages;
- versioned event envelopes;
- JSON Schema manifests;
- Arrow-compatible columnar data or well-defined file formats;
- a narrow C ABI;
- PyO3/maturin-style Python extension modules;
- subprocess boundaries for deployable workers;
- content-addressed artifacts in object storage.

Disallowed mechanisms:

- copying business models independently into four languages;
- importing generated database structs as API contracts;
- Python shelling into Go or Rust libraries as an internal call mechanism;
- unversioned ad hoc JSON dictionaries crossing services;
- shared mutable files used as inter-process coordination;
- direct database access across service/module ownership boundaries.

### A7.4 Architecture enforcement

Enforce the laws with:

- Bazel visibility;
- Python import-linter or custom AST policy tests;
- Rust workspace dependency policy;
- Go `internal/` packages and static checks;
- TypeScript project references and package exports;
- CODEOWNERS;
- a repository dependency graph check in presubmit.

Exceptions require an ADR with an owner and removal condition.

### A7.5 Training-specific dependency laws

1. `training/api/` defines provider-neutral semantic contracts. It may depend on PyTorch and stable protocol/foundation types, but not on provider packages, worker code, or model-family implementations.
2. `training/core/` owns lifecycle, logical state, parameter updates, training data progress, and callback ordering. It may depend on `training/api/`; it must not import provider-global configuration or outer orchestration.
3. `training/execution/` owns executable-plan compilation, transformation passes, schedules, process groups, collectives, and engine lowering. Exactly one prepared execution owns a run attempt.
4. `training/providers/` may depend on the corresponding third-party package and implement narrow declared capabilities. Providers do not own recipes, phase semantics, progress, callback ordering, or checkpoint publication.
5. `training/precision/` owns provider-neutral precision and quantization state. Provider implementation state is translated through provider adapters.
6. `training/checkpointing/` consumes the single state registry and is the sole canonical recovery implementation. It may not define a competing state registry or reinterpret task semantics.
7. `models/` exposes mathematics, logical state schema, semantic axes, parameter roles, and provider-neutral capability hints. Models may not import training execution or provider adapters.
8. Model-specific training behavior lives under `training/tasks/` and may import the corresponding model family; the model family must not import it back.
9. Top-level `evaluation/` owns evaluation meaning. `training/evaluation/` owns only scheduling, snapshot publication, leases, and trainer-side state.
10. `workers/training_worker/` is the composition root that resolves immutable artifacts, selects engine/providers, starts the trainer, reports progress, and publishes results.
11. `training/orchestration/monarch/` may coordinate trainer, generator, evaluator, simulator, and reward roles. It may not insert actor RPC into rank-synchronous forward, backward, collective, or optimizer execution.
12. Hidden process groups, provider fallbacks, state-name mappings, transformation passes, and compile regions outside the executable plan are prohibited.
13. Unsupported provider combinations fail closed before production allocation; no adapter may silently change numerical, recovery, or data-progress semantics.

### A7.6 Agent and development-kit dependency laws

1. `agents/api/` defines provider-neutral decision, tool, policy, workflow, state, and evidence contracts; it does not import model providers, HTTP clients, databases, queues, or agent-framework globals.
2. Agent tools are adapters over supported SDK/domain boundaries. They return typed receipts and artifact references, not arbitrary mutable objects or unrestricted filesystem/network handles.
3. `agents/workflows/` owns agent workflow meaning and compensation semantics; the Go control plane remains authoritative for durable resource/job state and attempts.
4. `agents/state/` stores replayable agent events, policy decisions, approval receipts, and memory references. It does not copy source documents, model weights, or scientific artifacts into an alternate store.
5. Biological agents call data, model, training, evaluation, and inference capabilities through public contracts. They cannot bypass release eligibility, data classification, tenant scope, budgets, or biological-safety policy.
6. `agents/runtime/` may coordinate inference and tool calls, but it cannot become the numerical execution engine, queue system of record, credential broker, or authorization authority.
7. `kits/*` expose stable authoring experiences over canonical domains. Shared kit code is limited to assembly, validation, conformance, packaging, and UX; semantics remain in the owning domain.
8. Generated kit distributions are traceable to a monorepo source closure, contract versions, compatibility matrix, and release manifest. Downstream customization occurs through supported inputs, not copied internals.

### A7.7 Dependency kinds

The architecture graph distinguishes dependency kinds because they carry different risks:

| Kind | Meaning | Example |
|---|---|---|
| API/compile | source imports and links against another target | model imports kernel dispatch API |
| runtime | process requires another component while running | worker calls artifact service |
| protocol | schemas or generated clients are consumed | SDK consumes inference v1 |
| data/artifact | output artifact is an input | training consumes feature dataset |
| tool/codegen | target is used to produce source or metadata | Buf plugin generates clients |
| test-only | dependency exists only in test configuration | optimized kernel compares reference |
| deployment | package references a released component | Kustomize base references container |
| operational | runbook/dashboard/alert relation | service links to SLO and alert policy |

The source import graph is acyclic by layer. Runtime and artifact graphs may contain workflows that revisit a domain, but cycles must be mediated by durable contracts and cannot become source-level cycles.

### A7.8 Canonical graph representation

Bazel targets are the authoritative source graph for buildable code. A normalized dependency graph supplements Bazel with native package manifests, generated-code relations, protocols, artifacts, services, and deployment metadata.

Every edge records:

```text
source and destination identity
edge kind
public or internal status
owner
justification or inferred rule
runtime/release scope
exception identifier if any
```

The graph is emitted as a CI artifact and used for affected-target planning, ownership review, security analysis, and architecture visualization.

### A7.9 Cycle policy

Forbidden cycles include:

- source import cycles across top-level domains;
- service modules mutually reading each other’s tables;
- SDK and service implementation cycles;
- model and training engine cycles;
- production and research cycles;
- schema generation cycles that require generated output to define its own source;
- release cycles in which artifact A can be built only after deployment of artifact B built from A.

Within a language package, narrowly scoped cycles may be impossible or prevented by the language. Logical cycles should still be removed through interface extraction, event boundaries, or ownership reassignment rather than hidden in global registries.

### A7.10 Bazel visibility policy

Visibility defaults to private. Public visibility is granted at the smallest stable boundary.

Recommended patterns:

```text
//domain/package:__pkg__             same package only
//domain/subtree:__subpackages__     owned subtree
//models/...                         explicit model consumers
//visibility:public                  only true repository-wide APIs
```

Public targets require documented compatibility and an owner. Test-only helpers use test visibility and must not leak into production dependencies. Aliases used during migration carry an expiry.

### A7.11 Language-specific enforcement

#### Python

- AST/import graph checks classify imports by top-level domain;
- wheel metadata validates transitive dependencies;
- forbidden imports are tested in both source and installed layouts;
- type-only imports do not bypass architecture rules when runtime coupling exists.

#### Rust

- workspace metadata is checked against allowed crate-edge rules;
- feature-gated dependencies are validated in every supported feature set;
- binding crates depend on pure core crates, never the reverse.

#### Go

- `internal/` enforces service-private implementation;
- static analysis rejects forbidden top-level imports;
- interfaces do not justify importing higher-level packages into lower-level domains.

#### TypeScript

- package exports and project references define allowed surfaces;
- path aliases cannot escape package boundaries;
- apps may import only SDK/design-system/config public exports.

### A7.12 Third-party dependency placement

Third-party libraries enter at the lowest domain that genuinely needs them. A generic library must not pull a heavy model, cloud, database, or GPU stack into unrelated consumers.

Each dependency is classified:

```text
foundation
scientific
model/training
GPU/provider
cloud/service
developer-only
test-only
release-only
```

Policy checks enforce expected lanes and image composition. Optional provider dependencies cannot appear in CPU or unrelated worker artifacts.

### A7.13 Test and fixture dependency rules

Tests may import reference or higher-cost validation utilities only through test targets. Production code cannot depend on fixtures, golden data, benchmark harnesses, or test-only fakes.

Cross-domain conformance tests live at the lowest common contract owner or under top-level `tests/conformance/`, but they do not create reverse production imports.

### A7.14 Runtime-call boundaries

A legal source dependency does not automatically authorize a runtime call. Network calls require:

- a versioned protocol;
- authentication and authorization context;
- deadline, cancellation, idempotency, and retry semantics;
- data classification and egress approval;
- observability and failure policy;
- ownership of compatibility and availability.

Direct database, object-path, queue-topic, or Kubernetes API coupling is prohibited unless the owning package explicitly exposes it as its implementation boundary.

### A7.15 Architecture exception contract

An exception record includes:

```yaml
id: ARCH-EXAMPLE-001
owner: team-name
source: //path:target
destination: //other:path
rule: no-higher-layer-import
reason: bounded migration
approvedBy: [architecture-owner]
created: 2026-08-24
expires: 2026-10-01
removalIssue: MC-1234
```

CI rejects expired, overly broad, or unowned exceptions. Exception count and age are tracked as architecture debt.

### A7.16 Dependency-change review

Adding or widening a dependency requires review of:

- ownership and direction;
- public API impact;
- transitive closure and image size;
- initialization/network/GPU side effects;
- license and vulnerability posture;
- platform portability;
- compatibility and upgrade burden;
- affected CI and release scope.

### A7.17 Qualification and definition of done

The dependency architecture is complete when:

1. Every source edge is visible in Bazel or normalized graph metadata.
2. Forbidden cycles and imports fail presubmit.
3. Public visibility is rare, owned, and documented.
4. Native package graphs and Bazel agree.
5. Runtime calls use declared contracts rather than infrastructure details.
6. Test-only dependencies cannot enter release artifacts.
7. Exceptions are narrow, expiring, and reported.
8. Affected-target analysis includes reverse source, protocol, artifact, codegen, and release dependencies conservatively.
