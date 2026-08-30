## Appendix A2 — Goals

The monorepo must make these outcomes routine:

1. A model change can atomically update its kernels, feature schemas, training recipe, evaluation suite, serving path, and SDK contract.
2. A clean checkout can build, test, qualify, and package every releasable target without depending on an engineer's workstation state.
3. Every dataset, feature set, checkpoint, model bundle, kernel binary, image, and SDK can be traced to source revision, inputs, build identity, schema, and policy.
4. CPU-only contributors can work productively without installing the full GPU stack.
5. GPU workflows can be reproduced across local development, CI, and cluster execution.
6. Cross-language interactions are explicit, versioned, and testable.
7. Research code has a clear graduation path into supported production packages.
8. Biological data and model artifacts are governed as first-class security assets.
9. CI scales by affected targets rather than running the entire repository for every change.
10. The repository can support frontier model research without allowing research urgency to erode platform correctness.
11. A training task can move from CPU smoke tests to single-node development and frontier-scale distributed execution without changing its model-objective semantics.
12. Every distributed plan, precision choice, optimized provider, checkpoint generation, and recovery decision is explicit, qualified, and recorded in immutable run evidence.
13. Dense, Pairformer, diffusion/flow, MoE, multimodal, and reinforcement-learning workloads share one trainer, logical state registry, event model, and checkpoint contract.
14. Loss normalization remains correct across packing, microbatching, and supported data-parallel layouts.
15. Every advertised recovery point is epoch-consistent, integrity-verified, and reproducible under an explicit guarantee.
16. Training inputs and progress are auditable through stable sample identities and compact BatchReceipts without logging biological payloads.
17. Systems-plan tuning and scientific hyperparameter studies remain separate, immutable, and independently promotable.
18. Biological agents can compose qualified data, model, training, evaluation, and inference capabilities without bypassing domain ownership, authorization, approval, artifact, or job-lifecycle controls.
19. MCDK through MADK provide stable authoring facades over canonical domain contracts without becoming duplicate engines or deployment systems.
20. The initial Google Cloud deployment is concrete and operable while provider-specific details remain confined to infrastructure, workload, storage, queue, identity, and observability adapters.

### Non-goals

This blueprint does not attempt to:

- turn every domain module into a network service;
- force every language dependency through Bazel alone;
- treat notebooks as production entrypoints;
- store large datasets, model weights, generated experiment output, or secrets in Git;
- put production environment overlays or cloud credentials in the source monorepo;
- create a custom orchestrator, scheduler, feature store, service mesh, or package registry before one is justified;
- make Python a control-plane language or Go a model-numerics language;
- hide unsupported execution behind silent fallbacks;
- stack Megatron, DeepSpeed, Lightning, TorchTitan, or Monarch as overlapping trainer/control planes;
- expose provider-specific global arguments or configuration files as the stable Mindclade training API;
- make a provider-native checkpoint format, experiment database, or scheduler the canonical source of training state;
- claim exact recovery from arbitrary internal execution boundaries that were not declared and durably snapshotted;
- mutate topology, providers, precision, or pipeline schedules invisibly during a production run;
- conflate systems autotuning with scientific hyperparameter optimization.

### A2.1 Goals as verifiable outcomes

Goals are release criteria, not aspirations. Each goal must map to evidence that can be produced by CI, a qualification run, or an operational drill.

| Goal class | Required evidence |
|---|---|
| Atomic change | one change updates contracts, code, tests, packages, and manifests without out-of-band steps |
| Reproducible build | clean-checkout build under pinned toolchains produces an attributable artifact digest |
| Scientific traceability | datasets, features, checkpoints, models, and reports carry complete lineage |
| CPU accessibility | CPU profile installs and runs repository policy, data, contract, and small numerical tests |
| GPU reproducibility | local, CI, and cluster profiles resolve the same locked dependency and capability set |
| Cross-language safety | compatibility, conformance, and error-contract tests pass for every boundary |
| Research graduation | production code contains no runtime import from `research/` and has an owned qualification path |
| Security governance | data classification and policy follow every artifact and workload |
| Scalable CI | affected-target planning is explainable, conservative, and auditable |
| Frontier training | task semantics survive changes in topology, execution profile, checkpoint generation, and provider |

A goal without an evidence producer, owner, and review cadence is incomplete.

### A2.2 Quality-attribute priority

Mindclade should make tradeoffs using the following quality attributes:

1. safety, privacy, biological governance, and legal compliance;
2. semantic and numerical correctness;
3. recoverability, integrity, and auditability;
4. security and tenant isolation;
5. compatibility and migration safety;
6. availability and operational control;
7. reproducibility and provenance;
8. performance and cost efficiency;
9. developer experience;
10. extensibility.

Performance work that weakens a higher-ranked attribute requires explicit qualification and bounded scope. Extensibility must not create a plugin surface before Mindclade has a concrete second implementation and a stable contract.

### A2.3 Stakeholder journeys

The architecture must make these journeys routine.

#### Model researcher

```text
prototype model component
→ run deterministic reference test
→ declare semantic axes and state schema
→ add task/objective integration
→ qualify optimized paths
→ launch immutable recipe
→ inspect exact run and evaluation evidence
```

#### Computational biologist

```text
identify source and license
→ ingest immutable raw objects
→ normalize with canonical biological semantics
→ curate and validate
→ inspect dataset card and exclusions
→ publish training-eligible manifest
→ reproduce a sample or batch by identity
```

#### Platform engineer

```text
add or update deployable component
→ validate component metadata and contracts
→ run affected tests
→ package and attest once
→ submit GitOps promotion by digest
→ observe rollout and rollback through durable status
```

#### Security reviewer

```text
trace component data classifications
→ inspect dependencies, SBOM, provenance, and permissions
→ validate egress/logging/retention policy
→ verify release and admission evidence
→ audit access and promotion receipts
```

#### Operator

```text
receive alert tied to job/run/attempt
→ inspect durable events and diagnostics
→ classify failure
→ retry, recover, quarantine, or terminate through typed actions
→ preserve evidence
→ complete runbook and incident follow-up
```

### A2.4 Measurable success criteria

At minimum, track:

- percentage of production components with valid owners, runbooks, SLOs, and component metadata;
- clean-checkout build and release success rate;
- mean time to identify an artifact’s complete lineage;
- percentage of protocol changes covered by breaking-change checks;
- percentage of production numerical paths with maintained references and current qualification;
- checkpoint recovery drill success and data duplicate/skip rate;
- affected-target precision and false-negative escape rate;
- proportion of production promotions that reuse the exact built digest;
- time to reproduce a failed data sample, training step, inference request, or evaluation report;
- number, age, and scope of architecture exceptions;
- dependency freshness and critical vulnerability remediation time;
- unowned or deprecated components past retirement date.

Targets belong in operational standards and can evolve; the requirement to measure them is architectural.

### A2.5 Non-goal enforcement

Non-goals are enforced through explicit rejection rules:

- no new service without a split decision satisfying Appendix A18;
- no new package manager or lock universe without an environment/release boundary;
- no notebook-based official launch path;
- no mutable large artifact committed to Git;
- no provider-native configuration as the public recipe surface;
- no silent fallback across numerical, topology, provider, precision, or recovery boundaries;
- no environment overlay in the monorepo;
- no direct production database access from workers or apps;
- no custom infrastructure product before a measured gap and ownership plan exist.

### A2.6 Goal ownership and review

Each top-level goal has:

```text
owner
metric or evidence target
producer of evidence
consumer/reviewer
review cadence
exception policy
retirement or replacement condition
```

The architecture group owns consistency of the goals, but domain owners own implementation evidence. Security, scientific, and operational reviewers retain veto authority within their responsibility.

### A2.7 Goal-to-test traceability

A machine-readable control map should link goals to:

- relevant ADRs;
- architecture rules;
- Bazel targets;
- CI lanes;
- component manifests;
- qualification reports;
- release gates;
- runbooks and drills.

A control is not considered implemented because a document mentions it. It is implemented when the repository can point to executable or reviewable evidence.

### A2.8 Definition of done

The goals chapter is operationalized when:

1. Every stated goal has measurable evidence and an owner.
2. Every non-goal has at least one enforcement mechanism.
3. Product, research, platform, security, and operator journeys have complete vertical slices.
4. CI and release reports map failures back to the governing goal or rule.
5. Exceptions and gaps appear in a visible architecture scorecard.
6. Quarterly review can distinguish achieved, at-risk, deferred, and retired goals.
