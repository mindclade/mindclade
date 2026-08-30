## Appendix A36 — Agent and development-kit architecture

### A36.1 Executive decision

Mindclade agents are **bounded, policy-governed composers of released platform capabilities**. They may plan, call qualified tools, wait for domain jobs, evaluate evidence, request approval, and publish an attributable result. They do not own model mathematics, datasets, training semantics, evaluation meaning, durable business jobs, authorization policy, or live infrastructure.

MADK owns the agent authoring experience; `agents/` owns agent semantics and runtime contracts; the Go control plane owns durable resources, admission, attempts, approvals, and audit; SDK-backed tools invoke the canonical data/model/training/evaluation/inference APIs. This separation permits rapid agent research without allowing an agent framework or model provider to become an implicit platform control plane.

The initial production agent surface is deliberately closed-world:

- reviewed agent definitions and workflow graphs;
- versioned, allowlisted tools shipped in a qualified release;
- explicit policy, budget, and approval gates;
- durable, replayable receipts;
- no tenant-supplied executable code, packages, containers, or dynamically discovered tool endpoints.

### A36.2 Authority and trust boundaries

| Concern | Canonical owner | Agent responsibility |
|---|---|---|
| tenant, project, principal, authorization | Go control plane and policy service | carry exact context and request decisions |
| durable job, attempt, cancellation, terminal status | Go control plane | submit/watch/cancel through SDK contracts |
| data and scientific semantics | `bio/` and `data/` | select approved operations and consume artifacts |
| model/training/evaluation/inference meaning | owning domain package | compose released capabilities without deep imports |
| tool schema and adapter behavior | `agents/tools/` plus public SDK | validate inputs/outputs and emit receipts |
| agent/workflow meaning | `agents/` | define plans, decisions, state transitions, and compensation |
| safety and approval policy | policy contracts and control plane | pause or reject; never reinterpret or self-approve |
| large durable values | artifact service/catalog | use authorized immutable references |
| live cloud/Kubernetes state | infrastructure and GitOps repositories | no direct mutation except approved MCDK/control-plane operations |

An agent model receives only the minimum context required for a decision. Credentials, signed URLs, hidden policy reasoning, unrestricted tenant metadata, and raw restricted artifacts are never placed in model context.

### A36.3 Stable agent contracts

The semantic API remains independent of any model or agent framework:

```python
from dataclasses import dataclass
from typing import Mapping, Protocol, Sequence

@dataclass(frozen=True, slots=True)
class AgentContext:
    run_id: str
    step_id: str
    tenant_id: str
    project_id: str
    principal_ref: str
    policy_snapshot_ref: str
    budget_ref: str
    cancellation_ref: str

@dataclass(frozen=True, slots=True)
class ToolRequest:
    tool_ref: str
    idempotency_key: str
    arguments: Mapping[str, object]
    input_artifacts: tuple[str, ...]
    deadline_epoch_ms: int

@dataclass(frozen=True, slots=True)
class AgentDecision:
    decision_type: str
    rationale_summary: str
    evidence_refs: tuple[str, ...]
    tool_request: ToolRequest | None
    approval_request_ref: str | None

class MindcladeAgent(Protocol):
    def decide(
        self,
        context: AgentContext,
        observations: Sequence["Observation"],
    ) -> AgentDecision: ...
```

Exact signatures may evolve. The durable contract requires agent/run/step identity, principal and project scope, policy and budget snapshots, evidence references, typed decisions, and deterministic or explicitly stochastic replay metadata.

### A36.4 Agent definition and run lifecycle

An `AgentDefinition` contains:

```text
agent identity and semantic version
purpose and non-goals
model capability requirement
workflow definition reference
exact eligible tool set
policy and approval requirements
input/output schemas
memory policy
budget envelope
maximum depth, iterations, fan-out, and wall time
evaluation suite and release qualification
```

An admitted run follows:

```text
CREATED
→ VALIDATING
→ ADMITTED
→ READY
→ RUNNING
   ↔ WAITING_FOR_TOOL
   ↔ WAITING_FOR_JOB
   ↔ WAITING_FOR_APPROVAL
   ↔ PAUSED
→ SUCCEEDED | FAILED | CANCELLED | EXPIRED
```

Every transition is revisioned and attempt-fenced. A waiting run holds no scarce accelerator solely to preserve conversational state. Terminal success requires a verified `AgentRunManifest` with output artifacts, decision/tool/approval receipt closure, policy/budget outcome, and evaluation status.

### A36.5 Tool contract and side-effect classes

Each `ToolContract` declares:

```text
stable tool identity and version
owner and public capability invoked
input/output JSON Schema
authorization action and resource derivation
data classifications accepted/produced
side-effect class
idempotency and retry semantics
deadline and resource/cost limits
network/storage/credential requirements
receipt and audit schema
compensation or reconciliation behavior
qualification and deprecation window
```

Tools use one of five side-effect classes:

| Class | Example | Default control |
|---|---|---|
| query | read catalog metadata | authorization, bounded result, provenance |
| artifact-producing | run deterministic analysis | durable job, input/output digests |
| job-submitting | start training or inference | quota, idempotency, explicit cost budget |
| state-mutating | quarantine artifact or change policy-bound resource | fresh authorization and approval |
| external effect | webhook, publication, external provider action | explicit approval, reconciliation, strongest audit |

The tool executor derives authorization from canonical resource identity; it never accepts a model-supplied role, tenant, credential, storage path, or policy override. Tool output is schema-validated and independently tied to an execution receipt.

### A36.6 Workflow, compensation, and replay

A `WorkflowDefinition` is a versioned directed graph whose nodes are decisions, tools, domain jobs, conditions, approvals, joins, waits, and terminal results. Edges declare preconditions and permitted state. The workflow has bounded loop and fan-out semantics and cannot dynamically create an unrestricted graph.

Side effects use one of:

- idempotent retry under the same key;
- durable reconciliation against observed state;
- compensating action with explicit limitations;
- irreversible action requiring pre-execution approval.

Replay consumes the frozen definition, model/provider manifest, prompts or instruction artifacts, normalized observations, tool receipts, policy decisions, RNG/sampling metadata, and state events. Replay claims distinguish exact, decision-equivalent, and evidence-only reproduction; nondeterministic model output is never mislabeled as exact.

### A36.7 Memory and knowledge references

Agent memory is not an unbounded transcript database. It consists of typed references:

```text
immutable artifact/document reference
authorized retrieval result with source and extraction digest
run observation or tool receipt
approved durable fact with provenance and expiry
derived summary linked to its complete source set
```

Memory policy defines tenant/project scope, classification, retention, deletion, freshness, embedding/index provenance, and whether a value may enter model context. Summaries never replace source evidence for consequential decisions. Cross-run memory requires an explicit purpose and is isolated from other tenants and projects. Secrets and short-lived credentials are not memory.

### A36.8 Policy, approvals, and budgets

Policy is evaluated at admission and immediately before every consequential tool call. Inputs include principal, tenant/project, agent/tool versions, target resources, classification, requested effect, budget, environment, and current revocation/quarantine state.

An approval receipt binds:

```text
exact proposed action and parameter/artifact digests
agent/run/step and tool identity
policy snapshot and risk class
approver identity and authority
scope, expiry, and single-use/reuse semantics
decision and reason
```

Agents cannot approve their own actions, reinterpret a denial, or reuse an approval for materially changed inputs. Budgets cover model tokens, iterations, tool calls, concurrent branches, accelerator/CPU time, storage, external spend, data volume, and wall time. Reservation precedes work; receipts reconcile actual consumption.

### A36.9 Biological-agent specialization

Biological agents may support discovery, analysis, design, experiment planning, dataset curation, model/evaluation selection, and evidence synthesis. Every specialization declares:

- allowed modalities, targets, data classes, and use cases;
- source and model eligibility;
- screening and human-review requirements;
- scientific uncertainty and evidence expectations;
- prohibited actions and external effects;
- output classification, distribution, and retention;
- domain-specific evaluation and incident escalation.

Agents do not convert generated biological content into source truth. Designed sequences, structures, complexes, protocols, and hypotheses remain generated artifacts with lineage, confidence, safety decisions, and review status.

### A36.10 Model and provider adapters

Provider adapters implement bounded capabilities such as structured generation, tool selection, embedding, reranking, or multimodal interpretation. The agent runtime freezes provider/model/version, sampling policy, context-construction version, tool schema set, and compatibility evidence in the run manifest.

Provider sessions, hosted threads, caches, and tracing consoles are optional accelerators or views. Mindclade events, receipts, artifacts, and policy decisions remain durable truth. Provider fallback is explicit and may create a new attempt or plan; it never silently changes safety, cost, reproducibility, or data-residency semantics.

### A36.11 Agent evaluation and qualification

Agent evaluation separates:

- task/scientific quality;
- tool-selection and argument correctness;
- policy and approval compliance;
- attribution and evidence quality;
- robustness to malformed or adversarial content;
- recovery, replay, cancellation, and budget behavior;
- latency, cost, and resource efficiency.

Suites include prompt injection, indirect injection through retrieved scientific records, conflicting evidence, tool-result forgery, stale policy, approval expiry, duplicate delivery, partial side effects, unavailable providers, cross-tenant memory attempts, recursive fan-out, and data-exfiltration probes. A quality score cannot compensate for a policy, authorization, or isolation failure.

### A36.12 Development-kit ownership map

| Kit | Authoring surface | Canonical domains consumed | Must not own |
|---|---|---|---|
| MCDK | target-neutral infrastructure/workload assembly and validation | deployment protocols, resource profiles, `deploy/`, infrastructure adapters | live cloud state, cluster promotion, universal-cloud semantics |
| MDDK | source, snapshot, dataset, feature, lineage, and curation authoring | `bio/`, `data/`, artifacts, policy | alternate catalog or biological schema |
| MMDK | model architecture, objectives, state schema, conversion, bundle authoring | `models/`, model protocols, kernels/runtime capability descriptions | trainer lifecycle or serving gateway |
| MTDK | recipes, phases, parallel plans, execution profiles, checkpoint authoring | `training/`, `runtime/`, `kernels/`, workload contracts | competing trainer, scheduler, or checkpoint truth |
| MEDK | suites, datasets, metrics, thresholds, reports, qualification authoring | `evaluation/`, inference contracts, evidence system | mutable result database or trainer-owned evaluation meaning |
| MADK | agents, tools, policies, state, workflows, biological-agent authoring | `agents/`, SDKs, policy, artifacts | alternate job, auth, model, or plugin runtime |
| Mindclade SDKs | runtime access to released platform capabilities | public protocols and supported API behavior | service implementation or scientific semantics |

### A36.13 Kit assembly contract

A kit assembly is an immutable, validated authoring artifact:

```text
kit name/version
source contract versions
input document digests
resolved defaults and migrations
generated target-neutral assembly
required capabilities and compatibility
validation and policy reports
generator/tool build identity
```

Compilation is staged: parse, validate, canonicalize, resolve references, bind explicit target profile, emit assembly, verify invariants. MCDK may bind a target-neutral assembly to the Google Cloud profile in Appendix A37, but only `infrastructure-live` and `gitops` may turn approved assemblies into live desired state.

### A36.14 Distribution and extraction

The canonical source remains in the monorepo. A separately distributed kit is produced from a declared Bazel source closure and release manifest. Extraction preserves package history where required, licenses/notices, generated contracts, compatibility tests, documentation, and provenance.

No engineer manually copies a kit implementation into another repository. External repositories accept upstream release automation or synchronized generated outputs and cannot merge changes that bypass the canonical source.

### A36.15 Observability, privacy, and security

Agent telemetry records bounded identifiers, state transitions, policy/approval outcomes, tool identity, latency, token/resource usage, and failure classes. Prompts, retrieved text, scientific payloads, chain-of-thought, credentials, and unrestricted tool arguments are excluded by default. Diagnostic capture is an authorized artifact with classification and retention.

Agent audit covers admission, policy decisions, approvals, consequential tool calls, external effects, terminal corrections, and administrative replay. Tool credentials are short-lived and action-scoped. Each agent worker runs with the least privilege needed for the current admitted step rather than a union of all possible tools.

### A36.16 Qualification levels

| Level | Required evidence |
|---|---|
| `agent-a0` | schemas, lifecycle, fake tools, deterministic state/replay tests |
| `agent-a1` | one real query/artifact tool, receipts, budgets, cancellation, SDK boundary |
| `agent-a2` | approval and mutation controls, failure reconciliation, adversarial security suite |
| `agent-a3` | biological-agent scientific evaluation, restricted-data controls, multi-step recovery |
| `agent-a4` | production SLO/cost, incident and revocation drills, provider change qualification |

An agent release receives the lowest valid level across its definition, workflow, model/provider, tools, policies, domain dependencies, worker, and evaluation suite.

### A36.17 Capability-local qualification progression

1. Freeze agent/tool/workflow/policy/run-manifest contracts and dependency laws.
2. Implement deterministic fake-model/fake-tool state-machine and replay qualification.
3. Add one read-only catalog/artifact tool and one asynchronous inference/evaluation tool through SDKs.
4. Add budgets, typed approvals, mutation/reconciliation, and adversarial content tests.
5. Deliver one qualified biological analysis agent and MADK authoring facade.
6. Add remaining kits only as their canonical domain vertical slices become real.

### A36.18 Definition of done

Agent and kit architecture is production-ready when:

1. agent intent, tool behavior, durable job truth, scientific semantics, policy, and artifacts have distinct canonical owners;
2. every run is admitted, bounded, revisioned, fenced, cancellable, and replayable from durable evidence;
3. every consequential tool call is authorized, schema-valid, idempotent/reconciled, budgeted, and receipted;
4. approval binds the exact action and cannot be self-issued, spoofed, or reused after material change;
5. untrusted content cannot expand authority or cross tenant/project/classification boundaries;
6. biological-agent output carries scientific, safety, lineage, uncertainty, and release status;
7. provider/framework state remains replaceable and non-authoritative;
8. MCDK–MADK assemblies contain no duplicate domain implementation and trace to one source closure;
9. adversarial, failure, replay, security, cost, and scientific qualification meet the claimed level;
10. agent or kit removal does not corrupt domain resources or erase evidence.

### A36.19 Final agent and kit invariants

- agents propose and compose; canonical services authorize and commit;
- tools are typed capabilities, not ambient code execution;
- model output is untrusted data, never authority or execution proof;
- approvals, budgets, policy, and receipts are durable run inputs and evidence;
- memory is scoped, attributable, expiring, and source-linked;
- biological autonomy is bounded by explicit use policy and human control;
- development kits simplify authoring without duplicating runtime truth.
