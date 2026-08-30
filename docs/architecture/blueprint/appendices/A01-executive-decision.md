## Appendix A1 — Executive decision

Mindclade should use a **domain-first polyglot monorepo** with strong language lanes:

- **Python** owns model architecture, training, evaluation, inference semantics, scientific feature logic, and experimentation that has graduated into production.
- **Rust** owns high-throughput biological parsing, data-plane I/O, preprocessing hot paths, artifact transfer, CPU runtime components, and carefully bounded Python extensions.
- **Go** owns the control plane, durable job APIs, Kubernetes controllers, service infrastructure, authorization middleware, and operational automation.
- **TypeScript** owns the web console, administrative surfaces, documentation application, and browser/server SDKs.
- **Agent packages** own provider-neutral tool, policy, state, workflow, memory-reference, and biological-agent semantics; durable job truth remains in the Go control plane and numerical/scientific work remains in its owning domain.
- **Protobuf and JSON Schema** own stable cross-process and cross-language contracts.
- **TileLang, CUDA, and limited C++** form a specialized accelerator lane for qualified kernels and native extensions.
- **Bazel/Starlark, Nix, and shell** are build and developer-environment tools, not places for product logic.

The monorepo is the authoritative source for application code and service-owned deployment packages. It does **not** own organization governance, foundational cloud trust, live cloud desired state, or live Kubernetes environment promotion. Those authorities are `github-config`, `bootstrap`, `infrastructure-live`, and `gitops`, respectively.

The default application architecture is a **Go modular control-plane monolith plus specialized Rust and Python workers**, not a fleet of premature microservices.

The default training architecture is a **single Mindclade-owned semantic control plane, one canonical trainer lifecycle, and one compiled step-program contract**. Native PyTorch is the production execution substrate. TorchTitan, Megatron Core, DeepSpeed, PyTorch Lightning, Lightning Fabric, TorchForge, Monarch (TorchMonarch), Transformer Engine, TorchAO, and TileLang contribute qualified capabilities behind Mindclade contracts; none becomes a competing source of truth for training semantics, state, checkpointing, recipes, or job lifecycle.

Bazel is the repository-wide integration graph. Native ecosystem managers remain the source of truth for ecosystem dependency resolution and local developer ergonomics:

- `uv` for Python
- Cargo for Rust
- one root Go module for internal Go code
- `pnpm` for TypeScript
- Buf for Protobuf
- Nix for pinned developer tools and system libraries

There is no repository-wide release version. Services, SDKs, schemas, models, datasets, kernels, and deployment packages are versioned according to their own artifact semantics.

The MCDK, MDDK, MMDK, MTDK, MEDK, MADK, and Mindclade SDK family is represented as a set of governed authoring and runtime facades over these canonical domains. A development kit may compose public contracts, validation, generators, CLI workflows, and packaging, but it must not duplicate the underlying source of truth. Independently distributed kit repositories, if later required, are generated or released from monorepo-owned source closures and do not become shadow implementations.

### A1.1 Architecture thesis

The monorepo is not merely a storage choice. It is the transaction boundary for coordinated changes across scientific semantics, executable code, contracts, qualification evidence, and release artifacts. Mindclade should optimize for **atomic scientific-to-production change**, while keeping operational trust and environment state outside the source repository.

The architecture therefore separates six kinds of authority:

| Authority | Canonical owner | Examples |
|---|---|---|
| Scientific meaning | `bio/`, `data/`, `models/`, `training/tasks/`, `evaluation/` | residue semantics, feature meaning, objectives, metrics |
| Agent intent and bounded autonomy | `agents/` plus policy contracts | tool eligibility, workflow meaning, approval gates, memory references |
| Product and workflow meaning | Go control plane and Protobuf contracts | jobs, projects, runs, policies, quotas, audit |
| Numerical execution | `runtime/`, `kernels/`, `training/execution/`, `inference/` | placements, collectives, compiled regions, kernel dispatch |
| Durable artifact truth | artifact manifests, catalog metadata, immutable object storage | datasets, checkpoints, model bundles, reports, run evidence |
| Environment desired state | `infrastructure-live` and `gitops` | clusters, IAM bindings, production overlays, promotion |

No implementation may become authoritative merely because it is convenient or widely used upstream. Authority is assigned explicitly by this blueprint and enforced through contracts, ownership, dependency policy, and release evidence.

### A1.2 Decision hierarchy

When two implementation choices conflict, use this order:

1. **Safety and legal obligations** override performance and convenience.
2. **Scientific and numerical correctness** override throughput.
3. **Durable recovery and lineage** override local ergonomics.
4. **Clear ownership and replaceable contracts** override framework convenience.
5. **Operational simplicity** overrides speculative scale flexibility.
6. **Measured performance** overrides aesthetic abstraction.
7. **Developer velocity** is optimized inside the preceding constraints.

An exception that reverses this order requires an ADR that names the affected guarantee, duration, compensating controls, owner, and removal condition.

### A1.3 Canonical systems of record

Mindclade must be able to answer “where is the truth?” without consulting tribal knowledge.

| Question | Source of truth |
|---|---|
| What code was intended? | Protected Git revision |
| What cross-process contract is valid? | Versioned Protobuf/JSON Schema plus compatibility baseline |
| What dependencies and tools were used? | Native lockfiles, Nix lock, Bazel module graph, release manifest |
| What durable job exists and who owns it? | Control-plane relational state and audit log |
| What data/model/checkpoint/report was used? | Immutable artifact manifest and digest |
| What ran on which hardware? | Run manifest plus hardware topology and executable-plan manifests |
| What is deployed in an environment? | GitOps desired state referencing immutable digests |
| What actually happened at runtime? | Durable events, attempts, checkpoints, reports, and reconciled status |
| What release is approved? | Promotion decision and signed release evidence |

Dashboards, mutable aliases, process-local configuration, Kubernetes status, notebook state, and provider-native metadata are views or caches, never canonical truth.

### A1.4 Architectural planes

The whole platform follows the same separation used in Appendix A14:

```text
Scientific and product semantics
        ↓ immutable requests and contracts
Control and planning
        ↓ frozen plans and admitted work
Execution
        ↓ immutable artifacts and events
Durable state and evidence
        ↓ promotion references
Environment reconciliation
```

The boundaries are intentionally asymmetric:

- semantics may request execution, but execution cannot redefine semantics;
- planners may select qualified capabilities, but capabilities cannot mutate policy;
- workers may report observed state, but they cannot directly declare durable business success;
- GitOps may deploy artifacts, but it cannot rebuild or reinterpret them;
- observability may explain behavior, but dashboards cannot become a correctness dependency.

### A1.5 Consequences of the executive decision

The selected architecture implies:

- fewer deployables than source packages;
- explicit worker composition roots around specialist Python and Rust code;
- generated contracts at network boundaries rather than shared database structs;
- one artifact-reference abstraction across all languages;
- one dependency graph visible to Bazel, while native lockfiles remain authoritative;
- model and training APIs that remain stable across provider replacement;
- release units with independent identities instead of a repository-wide version;
- qualification as a first-class product capability rather than a final test phase;
- intentionally duplicated reference and optimized numerical paths where parity evidence is required;
- gradual service extraction only after a durable operational boundary exists.

### A1.6 Decision and exception lifecycle

A top-level architectural exception follows:

```text
problem observed
→ owner writes evidence and proposed exception
→ architecture/security/scientific review as applicable
→ ADR approved with expiry and migration plan
→ policy exception encoded in machine-readable metadata
→ CI verifies the exception remains narrow
→ owner removes or renews before expiry
```

Exceptions must not be encoded only as comments, disabled tests, broad Bazel visibility, wildcard IAM, or undocumented configuration flags.

### A1.7 Architecture health indicators

The architecture is functioning when:

- cross-domain changes land atomically without manual release reconstruction;
- developers can identify the owner and canonical contract of every production capability;
- a clean checkout reproduces releasable artifacts;
- an artifact digest can be traced to inputs, source, build, policy, and qualification;
- production jobs survive duplicate delivery, worker failure, and topology-changing restart without corrupting business or numerical state;
- provider and kernel upgrades can be evaluated and rolled back without changing model/task APIs;
- CI cost scales with affected targets and risk class;
- operational incidents can be reconstructed without relying on raw biological payloads.

Architecture degradation indicators include rising exception count, direct database coupling, unowned packages, mutable production aliases, hidden code generation, provider APIs leaking into model/task code, and manual environment drift.

### A1.8 Definition of done

The executive architecture is implemented only when:

1. Every top-level domain has an owner, dependency policy, and documented source of truth.
2. Repository-estate boundaries are enforced by CI and identity policy.
3. Every deployable and releasable component has machine-readable metadata.
4. Cross-language calls use approved versioned mechanisms.
5. Build, test, package, sign, and promote paths work from a clean checkout.
6. Artifact, job, training, evaluation, and deployment lineage can be joined by immutable identifiers.
7. No upstream framework owns a competing lifecycle or durable state model.
8. Exceptions are visible, owned, expiring, and measurable.

### A1.9 Final executive invariants

- one canonical owner per semantic concern;
- one durable system of record per business fact;
- immutable identities cross repository and process boundaries;
- plans are frozen before production execution;
- optimized capabilities remain replaceable behind qualified contracts;
- source, artifacts, and environment state have separate trust boundaries;
- the monorepo optimizes coordinated change, not universal co-location of all state.
