## 5. Ownership and dependency matrix

### 5.1 Acyclic dependency law

Compile-time dependencies flow downward in this order; runtime calls may flow in either direction only through a versioned protocol and an authorized endpoint:

```text
apps and examples
→ SDKs and development-kit facades
→ worker/service composition roots
→ agents, evaluation, inference, and training
→ models, data, kernels, and runtime
→ bio domain
→ narrow language foundations and generated contracts
→ protocol/schema source definitions
```

This diagram is a partial order, not permission for every higher layer to import every lower layer. `services/` uses generated contracts and Go foundations; it MUST NOT import Python/Rust scientific implementations. `workers/` are composition roots and may import their owning domain libraries. `agents/` calls model, inference, data, and evaluation capabilities through registered ports or services; it MUST NOT import their private implementations. `evaluation/` may depend on public model/inference contracts, but production inference and model code MUST NOT depend on evaluation suites. `deploy/` consumes release metadata; production source never imports `deploy/`.

### 5.2 Ownership and dependency matrix

| Capability | Sole semantic owner | May depend on | Forbidden dependencies |
|---|---|---|---|
| Contract definitions | `protocols/` | schema/protobuf runtimes only | domain or service implementation |
| Cross-domain foundations | language lane in `libs/` | generated contracts, stdlib, approved foundational dependencies | business/scientific domains; PyTorch in `libs/python` |
| Biological truth and reusable feature semantics | `bio/` | `libs/`, schemas | data workflows, model-specific tensor layouts, services |
| Data lifecycle, generic transform dataflow, and feature materialization/cache projection | `data/` | `bio/`, `libs/`, contracts, artifact APIs | model/training internals, model-specific tensorization, service database |
| Runtime primitives | `runtime/` | `libs/`, hardware/runtime APIs | model objective, service policy |
| Kernel semantics | `kernels/` | `runtime/`, `libs/`, operation schemas | training lifecycle, service state |
| Model semantics and model-specific feature views | `models/` | `bio/`, `kernels/`, `runtime/`, `libs/` | data-pipeline implementation, training engine, service implementation |
| Training semantics | `training/` | models, data public contracts, kernels, runtime, bio | Go control-plane internals, apps, research |
| Evaluation meaning | `evaluation/` | public model/inference/bio contracts, data snapshots | trainer callbacks as authority, mutable production aliases |
| Inference meaning | `inference/` | models, kernels, runtime, bio | network authorization, service database |
| Agent meaning | `agents/` | generated contracts, bio types, capability ports, policy foundations | private model/data/service implementations, unrestricted tools |
| Durable operations | `services/control_plane/` | generated Go contracts, Go foundations, DB/queue adapters | scientific implementation, worker-local state as truth |
| Online admission | `services/runtime_gateway/` | auth/policy, generated contracts, routing/admission adapters | inference mathematics |
| Execution composition | `workers/*` | matching domain packages, generated clients, telemetry | direct business-state mutation |
| Client experience | `sdk/` | external generated transport, public schemas | internal events, database models |
| Authoring experience | `kits/` | public domain contracts/validators/CLIs | copied domain logic or durable state |
| Product UI | `apps/` | supported SDKs and design system | direct service database/generated internal client |
| Deployment package | `deploy/` | release descriptors and config schemas | live environment secrets/state, source-code authority |

### 5.3 Enforcement

Every package has `component.yaml` declaring owner, maturity, public targets, allowed dependency classes, data classification, build/test/release targets, SLO/runbook links when deployable, and active exceptions. Bazel visibility enforces the graph; language-native linting catches imports not visible to Bazel; a repository aspect compares actual edges with metadata. CI rejects cycles, undeclared cross-language FFI, production-to-research imports, public imports from `internal/`, direct database access outside the owning service, and new top-level paths without architecture approval.

Tests may depend on fixtures and test-support targets, never on another domain's private production code. A temporary cycle exception requires a time-bounded ADR, named owner, edge list, migration sequence, and CI-visible expiry. New shared packages require two production consumers and a stable responsibility; otherwise code remains with its owner.
