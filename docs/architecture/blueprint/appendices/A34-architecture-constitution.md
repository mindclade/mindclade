## Appendix A34 — Architecture constitution

Adopt these as the concise Mindclade monorepo constitution:

1. **Organize by domain; implement with the language best suited to the domain.**
2. **Use contracts across processes and languages, never accidental shared implementation.**
3. **Keep foundational libraries small, horizontal, and dependency-light.**
4. **Keep `libs/python` free of PyTorch and GPU dependencies.**
5. **Keep model mathematics independent of training engines, providers, workers, and serving processes.**
6. **Keep training policy independent of any one execution provider.**
7. **Use one Mindclade trainer lifecycle and one compiled step-program contract.**
8. **Use stable logical state identities rather than physical Python names.**
9. **Use one parameter update graph per active phase.**
10. **Normalize objectives with explicit numerators, denominators, bases, and reduction scopes.**
11. **Bind optimizer state and data progress through a committed `StepEpoch`.**
12. **Advertise only verified durable recovery points.**
13. **Use one executable plan for placements, transformation passes, process groups, schedules, providers, and compiled regions.**
14. **Use one DCP-based logical checkpoint schema as canonical state.**
15. **Qualify optimized kernels and providers against maintained reference implementations.**
16. **Treat datasets, features, BatchReceipts, checkpoints, plans, models, reports, and run evidence as immutable artifacts with lineage.**
17. **Separate systems autotuning from scientific HPO.**
18. **Start with a modular control-plane monolith and specialized workers.**
19. **Use Bazel as the integration graph and native lockfiles as ecosystem dependency truth.**
20. **Build once, attest once, and promote immutable artifacts through GitOps.**
21. **Keep live cloud and environment desired state outside the source monorepo.**
22. **Make ownership, compatibility, security classification, reproducibility, and qualification machine-readable.**
23. **Allow research freedom, but require an explicit graduation path into production.**
24. **Prefer fewer complete vertical slices over a large tree of unimplemented promises.**
25. **Treat TorchTitan, Megatron Core, DeepSpeed, Lightning/Fabric, TorchForge, Monarch, Transformer Engine, TorchAO, and TileLang as qualified capability sources—not competing owners.**
26. **Keep actor orchestration outside the rank-synchronous numerical schedule and Kubernetes admission boundary.**
27. **Default to fail-stop checkpoint-and-restart recovery before attempting live elasticity.**
28. **Promote training optimizations only with numerical, state, recovery, long-horizon, performance, security, and provenance evidence.**
29. **Treat agents as bounded composers of existing capabilities, never as alternate authorities for jobs, artifacts, policy, scientific semantics, or deployment.**
30. **Authorize and record every consequential agent tool call with exact schema, identity, policy, budget, idempotency, and receipt semantics.**
31. **Treat MCDK through MADK as governed facades over canonical domains, not duplicated engines or source trees.**
32. **Use Google Cloud as the concrete initial deployment profile while confining provider specifics to explicit adapters and live-infrastructure repositories.**
33. **Assign every production component and artifact a reliability, durability, recovery, and evidence-retention class.**
34. **Call the first production release complete only when its requirement-to-evidence acceptance graph closes without material exceptions.**

### A34.1 Constitutional status and precedence

The final architecture rules are normative. When documents conflict, use this precedence:

```text
security/legal/safety obligations
→ this blueprint and accepted ADRs that explicitly supersede it
→ domain architecture and protocol/schema contracts
→ package/component documentation
→ implementation comments and examples
```

An ADR may change a rule only by naming the affected rule, migration, consequences, and replacement invariant. Silent divergence in code or configuration is not a decision.

### A34.2 Rule control matrix

Each constitutional rule maps to:

```text
semantic owner
machine-enforceable checks
human review trigger
required evidence
exception policy
migration/repair path
```

Examples:

| Rule | Primary enforcement |
|---|---|
| domain-first organization | top-level path policy, component review |
| typed cross-boundary contracts | protocol/schema ownership, conformance tests |
| torch-free `libs/python` | dependency/import policy test |
| model independent of training/providers | Bazel visibility/import lint |
| one trainer/state/checkpoint authority | dependency law, contract/qualification tests |
| immutable artifacts and lineage | manifest/catalog schemas and commit protocol |
| bounded agents and tools | tool/policy schemas, approval gates, receipts, replay and adversarial tests |
| development kits are facades | dependency policy, source-closure manifests and conformance |
| build once/promote | release manifest, digest and provenance gates |
| live environment state outside monorepo | repository policy and GitOps boundary checks |

### A34.3 Authority invariants

The architecture preserves one canonical owner for each durable concern:

```text
business jobs/resources        control plane
live environment desired state GitOps/infrastructure repositories
biological semantics           bio schemas/domain
source/data lineage             data artifacts/catalog
model mathematics/state schema  models
training lifecycle/progress      training semantic control plane
execution placement/schedules    executable plan
checkpoint recovery state        logical DCP/checkpoint manager
kernel operation/dispatch        kernels subsystem
scientific evaluation meaning    evaluation
agent intent/workflow meaning      agents
public client behavior           protocols + SDK
release bytes/evidence            artifact/release pipeline
```

Adapters and providers consume these authorities and cannot create parallel records.

### A34.4 Identity invariants

Every durable entity has a stable identity independent of physical location or implementation. Required identities include:

```text
resource and tenant/project
artifact generation and digest
source/dataset/sample/feature
model logical state
job/run/attempt/fence
step/snapshot/checkpoint generation
recipe/phase/executable plan/provider/kernel
suite/report/release
```

Paths, filenames, Python names, pod names, rank numbers, aliases, dashboard labels, and database primary keys are not substitutes unless the contract explicitly makes them canonical.

### A34.5 Atomicity and publication invariants

A durable publication follows reserve/stage/verify/commit. Success is visible only after all required state and artifacts are consistent. This applies to:

- artifact generations;
- checkpoint generations;
- job terminal results;
- evaluation reports;
- release manifests;
- model bundles;
- dataset versions;
- promoted executable/kernel artifacts.

Partial or stale attempts cannot publish. Mutable aliases update only after immutable commit.

### A34.6 Failure and recovery invariants

The system assumes duplicate delivery, retries, process/node loss, network partitions/timeouts, and stale actors. Therefore:

- mutations use idempotency/revision/fencing;
- progress commits after successful semantic state transition;
- external side effects are reconciled from durable state;
- recovery resumes only from verified points;
- topology/provider changes require explicit replan/lineage;
- degraded modes and fallbacks are typed and policy-bound;
- failure cannot silently improve scientific scores or release evidence.

### A34.7 Compatibility invariants

Stable contracts are versioned and migration-capable. Producers and consumers declare support windows. Breaking changes require explicit migration and coordinated rollout. Generated code, SDKs, manifests, checkpoints, databases, deployment packages, and providers each have compatibility tests appropriate to their lifecycle.

Unknown or unsupported combinations fail clearly before expensive or destructive work.

### A34.8 Numerical and scientific invariants

- reference paths define semantic oracles;
- objectives carry numerator, denominator, basis, and reduction scope;
- stochastic behavior uses explicit RNG hierarchy and sample identity;
- optimized/provider behavior is qualified through forward, gradient, update, recovery, and long-horizon evidence as applicable;
- evaluation fixes datasets, procedures, metrics, statistics, and thresholds;
- invalid/failed samples are accounted for;
- scientific HPO remains separate from systems tuning;
- baseline changes require evidence, rationale, and review.

### A34.9 Security and biological-governance invariants

- identity and authorization apply at every trust crossing;
- tenant/project and classification travel with resources/artifacts/jobs;
- secrets remain external references and short-lived;
- untrusted code/input/builds are isolated;
- release/deployment/load verifies immutable artifact integrity and trust;
- restricted/human-derived data and generated biological outputs receive explicit policy;
- logs/telemetry/diagnostics minimize payloads;
- audit and incident response preserve attributable evidence;
- authorization and safety fail closed.

### A34.10 Operational invariants

- every production component has owner, SLO, runbook, rollback, and recovery evidence appropriate to tier;
- Kubernetes is execution substrate, not business truth;
- queues deliver at least once and do not own lifecycle;
- telemetry outage cannot corrupt numerical or durable state;
- capacity/backpressure are bounded;
- releases build once and promote exact digests;
- backups/restores reconcile external artifacts and stale workers;
- live environment changes flow through GitOps or controlled operational APIs.

### A34.11 Research and evolution invariants

Research remains free to prototype but isolated from production authority. Graduation transfers semantics into an owned domain package with reproducibility, tests, state/artifact mapping, security, and qualification. Deferred capabilities require a real workload and owner. Empty abstractions and duplicate implementations are removed.

### A34.12 Machine enforcement program

Minimum constitutional checks include:

```text
Bazel visibility and reverse-dependency policy
Python/Rust/Go/TypeScript dependency rules
protocol/schema breaking and generated drift
component owner/maturity metadata
config unknown fields/secret/mutable-alias checks
artifact/checkpoint manifest completeness
state/update/progress invariants
CI trust and release provenance
security/secret/restricted-fixture scanning
expired exception/deprecation/quarantine checks
```

The check set is versioned and itself tested. Bypassing a check requires an explicit exception, not a hidden CI flag.

### A34.13 Human review program

Automation cannot determine all semantic ownership, scientific validity, threat impact, or operational complexity. Review templates prompt for:

- authority/system-of-record changes;
- identity and migration;
- failure/retry/cancellation/recovery;
- numerical/scientific evidence;
- security/classification/biological use;
- operational SLO/capacity/rollback;
- release and compatibility;
- deferred scope and removal of old paths.

Review is proportional: local implementation inside stable contracts remains lightweight; constitutional changes receive ADR/RFC and cross-owner approval.

### A34.14 Exception hierarchy

Non-negotiable production invariants include authorization fail-closed, artifact integrity, attempt fencing, no mixed-epoch checkpoint, no premature progress commit, no unverified release promotion, and no secret/restricted payload leakage through prohibited channels.

Other rules may have bounded exceptions with compensating controls. Every exception identifies whether it affects experimentation, staging, or production and cannot implicitly raise maturity.

### A34.15 Adoption and migration

Adopt the constitution incrementally:

1. inventory current components, authorities, identities, and violations;
2. classify violations by data-loss/security/correctness risk;
3. freeze creation of new violations;
4. implement foundational schemas/policy checks;
5. migrate one vertical slice through all contracts;
6. expand domain by domain;
7. remove duplicate state/paths;
8. make release maturity depend on compliance/evidence;
9. review the constitution after real incidents and scale evidence.

Legacy code may operate under explicit migration exceptions, but cannot be presented as compliant production capability.

### A34.16 Constitutional audit

A periodic audit samples:

```text
component ownership and dependencies
protocol/config/schema compatibility
artifact and release evidence
jobs/attempts/fencing/outbox
training state/progress/checkpoints
security/classification/egress
Kubernetes/GitOps boundaries
SLO/runbook/restore freshness
research/deferred scope
exceptions/deprecations
```

Findings become owned work with severity, deadline, and verification. The audit looks for actual bypasses in code and operations, not only document conformity.

### A34.17 Amendment process

Amendment requires:

- concrete evidence that a rule is insufficient or harmful;
- affected systems/owners and migration impact;
- proposed replacement invariant;
- alternatives;
- security/scientific/operational consequences;
- machine/human enforcement changes;
- approval and effective version;
- migration deadline and superseded text.

The blueprint revision and ADR index record amendments. Exact dependency/tool versions change through lockfiles and qualification without requiring constitutional amendment unless authority or semantics change.

### A34.18 Definition of done

The architecture constitution is operational when:

1. its rules have clear precedence, owners, checks, review triggers, and exception policy;
2. every durable concern and identity has one canonical authority;
3. publication, retry, failure, recovery, compatibility, security, and scientific invariants are enforced across domains;
4. code, CI, release, and operations cannot silently bypass the rules;
5. production maturity and promotion depend on compliance plus evidence;
6. legacy deviations are inventoried and migrating under explicit scope;
7. audits inspect implemented behavior and close findings;
8. amendments preserve history and replace invariants explicitly;
9. research and future capability remain possible through clean seams without weakening current truth;
10. the concise rules can be traced to concrete implementation and qualification requirements throughout this blueprint.

### A34.19 Final constitutional statement

Mindclade is one domain-first product system with explicit language lanes, immutable contracts and artifacts, one authority per durable concern, reference-backed numerical execution, evidence-based qualification, and build-once promotion. Scale, providers, and optimizations may evolve; ownership, identity, recoverability, security, scientific integrity, and provenance may not become implicit.
