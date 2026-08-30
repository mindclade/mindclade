## Appendix A20 — Research graduation policy

`research/` is intentionally permissive but isolated.

Allowed:

- notebooks;
- one-off studies;
- prototypes;
- ablations;
- exploratory datasets represented only by references;
- paper reproduction.

Not allowed:

- production services importing research code;
- notebooks as training launchers for official runs;
- committed large outputs;
- hidden dependencies installed manually;
- production model checkpoints without manifests;
- secrets or restricted data.

### Graduation path

```text
research prototype
-> reproducible experiment
-> named owner and design note
-> domain package implementation
-> unit/parity tests
-> integration with build graph
-> qualification suite
-> production recipe/service adoption
```

Graduated code leaves `research/`; do not maintain two authoritative implementations.

### A20.1 Research authority and isolation

Research is an evidence-generating environment, not a parallel production architecture. It may explore new algorithms, data, kernels, models, objectives, and systems, but it has no authority over production contracts until graduation.

```text
question and hypothesis
→ reproducible experiment definition
→ immutable inputs and execution record
→ result and analysis
→ decision: abandon, continue, reproduce, or graduate
```

Production packages may be used as dependencies. Research code never becomes an implicit dependency through notebook paths, editable installs, environment variables, or copied source.

### A20.2 Research project shape

A maintained research project has:

```text
research/<topic>/
├── README.md
├── experiment.yaml
├── src/ or notebooks/
├── tests/                  # lightweight but real invariants
├── configs/
├── analysis/
├── fixtures/               # small, legally distributable
└── results/README.md       # references, never large outputs
```

The README states owner, hypothesis, intended duration, data classification, compute budget, production dependencies, expected evidence, and graduation/retirement criteria.

### A20.3 Experiment manifest

Every meaningful run resolves an immutable manifest:

```text
experiment and hypothesis identity
owner and collaborators
source revision and dirty-tree status
entrypoint and configuration digest
dataset/feature/model/checkpoint references
random roots and reproducibility intent
hardware/container/toolchain identity
resource and budget limits
policy/data classification
expected metrics and decision rule
parent experiment and lineage
```

A notebook execution without a manifest may be exploratory, but its result cannot support promotion or a formal scientific claim.

### A20.4 Notebooks

Notebooks are for exploration, visualization, and narrative analysis. Requirements:

- no hidden manual setup required for reproducible runs;
- parameters and data references are explicit;
- outputs are stripped or bounded according to policy;
- secrets and signed URLs are never embedded;
- important transformations move into importable modules;
- long-running official training/evaluation is launched through supported CLIs/jobs;
- execution order is tested or normalized before review;
- rendered reports identify source revision and artifact inputs.

A notebook may consume a production run; it does not define the canonical run lifecycle.

### A20.5 Research dependencies and environments

Research uses the root lock universe and named experimental groups where practical. New dependencies are:

- pinned;
- license and security reviewed at an appropriate level;
- isolated from production images unless promoted;
- recorded in experiment evidence;
- removed when abandoned.

Personal environment packages or uncommitted editable forks invalidate formal reproducibility unless captured as source artifacts and reviewed.

### A20.6 Data use in research

Research datasets are still artifact references with classification, source terms, access policy, and lineage. Researchers may create provisional snapshots, but must declare:

```text
source and collection time
transformation code/configuration
sample identity strategy
known quality/leakage limitations
sharing and retention policy
whether results may be published
```

Restricted or human-derived data uses approved isolated environments. Copies on laptops, notebook outputs, ad hoc buckets, and Git LFS are prohibited unless policy explicitly allows them.

### A20.7 Compute and budget governance

Every nontrivial experiment declares a resource envelope:

- accelerator/CPU type and count;
- maximum wall time;
- expected and hard cost budget;
- storage and artifact-retention budget;
- checkpoint/evaluation cadence;
- priority and preemption class;
- termination/cleanup behavior.

Research urgency does not authorize bypassing quota admission, safety policy, or artifact controls. Abandoned runs are cancelled and cleaned up.

### A20.8 Reproducibility classes

Research results declare:

| Class | Evidence |
|---|---|
| exploratory | code/config reference, best-effort environment, no formal claim |
| reproducible | immutable inputs, clean entrypoint, fixed environment, rerun evidence |
| independently reproduced | another operator or CI lane reproduces the conclusion |
| production candidate | production-style contracts, tests, qualification plan, owner |

The class appears in reports and paper/decision references. An exploratory chart is not silently cited as independently reproduced evidence.

### A20.9 Result artifacts and analysis

Large outputs, checkpoints, metrics, and plots are immutable artifacts. A result manifest records:

```text
experiment/run identity
input and environment digests
metric and analysis versions
raw result references
statistical method
figures/tables derived from exact inputs
known failures and exclusions
conclusion and uncertainty
```

Figures committed to papers or design documents must be regenerable. Manual spreadsheet editing or image retouching that affects scientific meaning is prohibited unless the transformation is documented and reproducible.

### A20.10 Negative and null results

Research should preserve concise evidence for failed hypotheses, incompatible approaches, and null results when they prevent repeated cost. A negative-result note includes attempted configuration space, observed failure, confidence, artifacts retained, and conditions under which reconsideration is justified.

Not every failed run is retained indefinitely; representative evidence and the decision record are sufficient under retention policy.

### A20.11 Ablations and comparisons

Ablations change one declared scientific factor at a time or use a designed study. Comparisons align:

- dataset and split;
- training/evaluation budget;
- model size and compute where relevant;
- systems plan or separately report systems differences;
- random seeds/repeats;
- metric versions;
- checkpoint selection rule;
- failed-run handling.

Systems optimizations and scientific changes are not conflated. A faster kernel cannot be credited with a quality improvement without controlled evidence.

### A20.12 Paper and external reproduction

A paper reproduction records exact upstream revision, license, deviations, dataset availability, environment, and expected versus observed results. Third-party code remains in approved `third_party/` or external pinned sources; it is not copied into production packages without license and independent-implementation review.

External claims are treated as hypotheses until Mindclade obtains sufficient reproduction evidence for the intended workload.

### A20.13 Prototype interfaces

Prototypes may temporarily use simplified interfaces, but must label:

```text
which production contract is bypassed
why the shortcut is acceptable for the experiment
what results depend on it
what migration is required for graduation
expiry/removal date
```

Prototypes may not masquerade as stable SDKs, canonical checkpoints, production recipes, or durable job systems.

### A20.14 Graduation readiness gate

A candidate is ready to enter a domain package only when:

1. the scientific claim has reproducible evidence;
2. a durable owner and target package are identified;
3. public semantics and non-goals are written;
4. data/model/state/artifact contracts are mapped;
5. reference behavior and numerical fixtures exist;
6. security, license, and data implications are reviewed;
7. expected performance and resource envelope are measured;
8. migration from the prototype is planned;
9. duplicate authoritative implementations will be removed.

### A20.15 Graduation implementation protocol

```text
freeze research evidence
→ write ADR/design note where architecture changes
→ define production API/schema
→ independently implement or refactor into target domain
→ add unit, parity, failure, and integration tests
→ integrate Bazel/native manifests and ownership
→ add qualification and operational evidence
→ adopt through one real production consumer
→ archive/remove research authority
```

The production implementation may differ substantially. Parity is against declared semantics and evidence, not source-code similarity.

### A20.16 Kernel/model/training graduation specifics

A research kernel needs an operation spec, reference path, gradient tests, dispatch capability, and workload qualification.

A research model needs typed configuration, feature/output contracts, logical state schema, reference execution, checkpoint conversion, model card, and evaluation evidence.

A research training idea needs a `TrainingTask`/phase/objective mapping, correct normalization, state registration, deterministic progress/RNG, checkpoint behavior, and qualification. It does not introduce another trainer script as a permanent system.

### A20.17 Research security and responsible use

Research follows the same minimum security and biological governance as production:

- no secrets or restricted payloads in Git/notebooks/logs;
- approved identities, storage, compute, and egress;
- classification of generated biological outputs;
- access/audit for high-risk datasets and models;
- external publication review;
- safe sharing of fixtures and examples;
- prompt/model-output retention policy for interactive tools.

Experimental status does not mean exempt from safety controls.

### A20.18 Research lifecycle and retirement

Projects have states:

```text
PROPOSED → ACTIVE → REPRODUCING → CANDIDATE
                      ↘ PAUSED
ACTIVE/CANDIDATE → GRADUATED
any non-graduated state → RETIRED
```

Paused and retired projects release compute, remove unneeded dependencies, clean staging data, and preserve only policy-required evidence. Ownership review identifies stale research quarterly or at another declared cadence.

### A20.19 Research review and qualification

A research review evaluates:

```text
scientific validity
reproducibility
comparison fairness
artifact and data lineage
resource efficiency
security/safety/license
production relevance
next decision and budget
```

Formal production promotion requires independent review by the target domain owner, not only the original researcher.

### A20.20 Research maturity levels

| Level | Meaning |
|---|---|
| `r0-idea` | hypothesis and owner, no trusted evidence |
| `r1-exploratory` | runnable prototype and preliminary artifacts |
| `r2-reproducible` | clean manifest, immutable inputs, repeatable result |
| `r3-reproduced` | independent rerun/robustness or ablation evidence |
| `r4-candidate` | production contract and qualification plan approved |
| `r5-graduated` | adopted production implementation; research source no longer authoritative |

### A20.21 Definition of done

The research architecture is healthy when:

1. every formal result resolves to immutable code, data, model, configuration, and environment evidence;
2. notebooks are analysis surfaces rather than official launch/control planes;
3. restricted data and generated biological outputs remain governed;
4. compute and artifact budgets are explicit and cleanup is routine;
5. negative results prevent avoidable repeated work;
6. comparisons separate scientific and systems variables;
7. graduation has an owner, target package, API/state mapping, and qualification plan;
8. graduated code leaves research and only one authoritative implementation remains;
9. abandoned projects retire dependencies, resources, and access;
10. exploratory evidence is never represented as production qualification.

### A20.22 Final research invariants

- research may depend on production; production never depends on research;
- every consequential claim has a reproducibility class;
- data and outputs remain artifacts with policy and lineage;
- shortcuts are explicit, temporary, and non-authoritative;
- graduation is a contract-and-evidence transfer, not a directory move;
- freedom to explore never bypasses security, biological governance, or resource accountability.
