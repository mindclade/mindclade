## Appendix A33 — Repository anti-patterns

Reject these during review:

- a new top-level directory without an architecture owner;
- `common`, `utils`, or `helpers` packages with unrelated content;
- domain code in CI scripts;
- model code inside a worker entrypoint;
- service implementation imported by an SDK;
- a Python package depending on a Go binary for library behavior;
- hidden network access in builds or tests;
- mutable `latest` references in production recipes;
- environment-specific values in model/data manifests;
- direct object-store path construction outside the artifact library;
- silently caught exceptions that change numerical behavior;
- unqualified optimized kernels;
- checkpoints without schema and integrity manifests;
- datasets without lineage, stable sample identity, and policy metadata;
- notebook-only production procedures;
- per-library Go modules;
- separate lockfiles without a real release/environment boundary;
- generated API models edited by hand;
- infrastructure-live or GitOps environment state copied into the monorepo;
- an empty scaffold presented as production capability;
- two trainer lifecycles controlling the same run;
- a raw `backward()`-only engine interface pretending to support arbitrary pipeline schedules;
- model or task code importing provider-owned trainer/global control APIs;
- hidden process-group creation outside the executable plan;
- provider replacement after logical state or optimizer ownership is frozen without an explicit transformation pass;
- Python fully qualified names treated as durable checkpoint identity;
- checkpoint save that materializes all global state into one Python dictionary;
- asynchronous checkpointing without snapshot-epoch fencing;
- mixed-epoch checkpoint generations;
- progress or data cursor committed before the associated update receipt;
- a mean of per-microbatch means used without a valid normalization proof;
- trainable parameters owned by multiple optimizers or no optimizer;
- raw provider configuration treated as the Mindclade recipe contract;
- provider-native checkpoints treated as canonical recovery state;
- callbacks performing collectives, optimizer updates, blocking network I/O, or checkpoint publication;
- actor RPC, queue I/O, telemetry exporters, or artifact uploads inside the rank-synchronous numerical schedule;
- silent precision, kernel, provider, topology, schedule, compilation, or optimizer fallback;
- production JIT/graph breaks outside the declared compilation contract;
- systems autotuning and scientific HPO represented as the same artifact;
- automatic mid-run replanning without a committed checkpoint and new plan lineage;
- performance promotion without logical-state mapping, forward/gradient/update, recovery, and long-horizon evidence.

### A33.1 Anti-pattern taxonomy

Anti-patterns are violations of authority, identity, lifecycle, or evidence—not merely stylistic preferences. Review them by class:

```text
ownership and repository
contracts and dependencies
state and artifacts
data and biological semantics
model/training/kernel execution
services/workers/database
security and operations
CI/testing/release
research and product
```

Each anti-pattern should have automated detection where feasible and a documented repair path.

### A33.2 Ownership and repository anti-patterns

Reject:

- packages with no owner or consumer;
- top-level directories that duplicate an existing domain;
- source organized by language when domain ownership becomes unclear;
- component metadata that lists nonexistent targets or nominal teams;
- production code in `tools/`, CI scripts, notebooks, or deployment templates;
- environment/live infrastructure copied into the monorepo;
- generated/vendor content mixed with authored code without boundaries;
- a repository split used to evade dependency or review policy.

Repair by identifying the system of record and owner, moving code to the correct domain, and deleting empty/duplicate authority.

### A33.3 Contract anti-patterns

Reject:

```text
unversioned dictionaries crossing process/language boundaries
database structs as public APIs
copied business models independently maintained in languages
optional fields whose absence/default meaning is undefined
mutable aliases used at execution time
errors represented only by free-form strings
hidden environment variables or provider globals
callbacks/hooks that mutate unspecified state
```

Repair with a typed source-of-truth schema, compatibility rules, canonical resolution, and conformance fixtures.

### A33.4 Dependency anti-patterns

Reject:

- reverse imports from foundational packages into services/workers/apps;
- production importing `research/`;
- model code importing trainers/providers/queues;
- SDKs importing service internals;
- cross-language shelling as a library call;
- `utils/common/helpers` becoming dependency hubs;
- test-only dependencies leaking into runtime packages;
- provider packages becoming transitive defaults for CPU/base environments;
- runtime network fetches of build dependencies.

Repair by extracting the narrow contract or moving composition to a root. Exceptions require expiry and a removal path.

### A33.5 State and artifact anti-patterns

Reject:

```text
filenames or Python qualified names as durable identity
object-store prefixes as catalogs
partial/mixed-generation publication
mutable overwrite of released bytes
checkpoint without schema, epoch, integrity, or lineage
model weights/datasets in SQL or Git
large payloads in queues/events
alias resolution deferred to a worker retry/resume
local cache treated as durable recovery truth
```

Repair with logical IDs, manifests, atomic generations, catalog transactions, and immutable resolution receipts.

### A33.6 Biological/data anti-patterns

Reject:

- parsing and scientific normalization fused irreversibly;
- loss of source bytes/offsets/provenance needed for audit;
- implicit coordinate units/frames or residue/atom identity;
- silent repair/drop of malformed records;
- datasets mutated in place;
- unstable sample identities or Python iterator checkpoints;
- random splits without dedup/leakage policy;
- feature cache keys missing source/config/schema/tool identity;
- raw restricted data in tests, logs, notebooks, or issue attachments;
- source adapters implemented as unrelated pipelines.

Repair by restoring canonical schemas, source-faithful artifacts, versioned transformations, and dataset qualification.

### A33.7 Model anti-patterns

Reject:

```text
model forward reading environment/provider/job state
untyped tensor position conventions across boundaries
optimizer or process-group creation inside a model
state identity derived from physical wrapper names
provider replacement after state/update ownership without a pass
shared component abstraction before two real consumers
checkpoint conversion by filename heuristics
silent feature/tokenizer/component mismatch
model bundle values inferred from paths
```

Repair by publishing typed configuration, semantic axes, logical state, capability hints, feature requirements, and bundle manifests.

### A33.8 Training anti-patterns

In addition to Appendix A14's list, reject:

- multiple entrypoint loops that implement subtly different semantics;
- progress reported/committed from dataloader fetch rather than update receipt;
- optimizer group creation through regex over physical names without logical tags;
- unregistered EMA/calibration/callback state;
- phase changes applied in-place without committed checkpoint lineage;
- evaluation reading live mutable trainer modules;
- provider config files passed through as canonical recipes;
- “elasticity” that changes world topology without RNG/data/state proof;
- performance benchmark accepted without convergence/recovery evidence.

Repair by routing all execution through the canonical trainer, state registry, plan, and checkpoint contracts.

### A33.9 Kernel/compiler anti-patterns

Reject:

```text
optimized implementation without a maintained reference
benchmark without exact qualification key
forward-only parity for training use
runtime first-use unconstrained autotuning
silent eager/reference fallback
graph break outside declared policy
binary loaded without digest/signature/provenance
workspace/allocation/synchronization hidden from plan
inference qualification assumed to cover backward/training
```

Repair with operation version, capability allowlist, qualification evidence, plan-bound dispatch, and immutable bundles.

### A33.10 Evaluation/inference anti-patterns

Reject:

- dashboard values as release evidence;
- metric names without versions/aggregation/statistics;
- dropping invalid/infrastructure-failed samples to improve scores;
- hidden mutable test sets or untracked manual exclusions;
- evaluator reading mutable checkpoint directories;
- batch neighbors affecting stochastic samples;
- asynchronous result marked success before artifact commit;
- worker retries changing model/sampling/precision silently;
- confidence/ranking/postprocessing embedded as undocumented scripts;
- public API coupled to GPU worker implementation.

Repair with immutable suites/snapshots/requests/plans, per-sample identities, failure accounting, and report/result manifests.

### A33.11 Service/worker/database anti-patterns

Reject:

```text
queue status as business truth
“exactly once” assumed without idempotency/fencing
stale attempt able to heartbeat or publish
direct cross-module table writes
external calls inside database transaction retries
workers querying control-plane tables
unbounded retries/goroutines/prefetch/connections
Kubernetes pod phase copied directly to job state
success without verified result manifest
standalone health/event services without need
```

Repair through domain state machines, transaction/outbox, attempt fences, bounded adapters, and composition-root discipline.

### A33.12 Security anti-patterns

Reject:

- long-lived cloud keys in CI/workers;
- authorization only in UI/gateway;
- tenant scope inferred from request labels without resource checks;
- secrets in environment dumps, commands, logs, manifests, or notebooks;
- unrestricted egress for restricted workloads;
- unsigned mutable images/tags in production;
- public/debug endpoints on workers/rendezvous;
- shared untrusted/trusted caches or runners;
- classification downgrade through derived/generated data;
- security scanner pass treated as complete assurance;
- biological risk controlled only by policy prose.

Repair with explicit identity/policy, workload isolation, verified artifacts, negative tests, and durable audit.

### A33.13 Observability/operations anti-patterns

Reject:

```text
run/sample/artifact IDs as metric labels
raw biological payloads in logs/traces
telemetry backend required for numerical correctness
liveness restart loops during tolerable dependency outage
alerts without user impact, owner, or runbook
local scratch assumed durable
manual production changes outside GitOps/control plane
restore procedure that ignores stale workers/external effects
SLO inferred from host metrics rather than contract boundary
```

Repair with semantic conventions, durable events, bounded labels, typed degraded modes, and exercised runbooks.

### A33.14 CI/test/release anti-patterns

Reject:

- green required check for a different revision;
- untrusted PR executing protected workflow code with secrets;
- affected-target planner with no full-run audit;
- blanket retries hiding deterministic failures;
- flaky tests removed or quarantined without owner/expiry;
- numerical goldens bulk-updated;
- performance compared across uncontrolled hardware;
- cached output treated as provenance;
- environment-specific rebuild during promotion;
- release artifact without SBOM/provenance/signature/evidence;
- failed/indeterminate qualification interpreted as pass.

Repair with exact build identity, trust isolation, structured evidence, and build-once promotion.

### A33.15 Research/product anti-patterns

Reject:

```text
notebook as official training/service launcher
exploratory result represented as reproduced evidence
research dependency in production
prototype API exposed as supported SDK
agent model output treated as authorization, approval, or proof of tool execution
agent tool with unrestricted network/filesystem/credential scope
provider session or chat transcript treated as durable replay state
development kit containing copied domain implementation
manual figure/result editing without lineage
empty public SDK or plugin promise
browser encoding business authorization/state machines
admin privileges hidden in the normal console client
```

Repair by grading evidence, graduating through contracts, and keeping public/product surfaces on stable SDKs.

### A33.16 Automated detection

Implement checks for:

- dependency/visibility rules;
- forbidden imports and package dependencies;
- owner/component metadata;
- unknown config fields and mutable aliases;
- generated drift and protocol breaks;
- missing manifests/signatures/evidence;
- secret/high-entropy/restricted fixture scanning;
- metric label schema/cardinality;
- unbounded retries/timeouts and direct storage paths where statically detectable;
- production dependencies on experimental/research code;
- expired exceptions/deprecations/quarantines.

Automation supplements review; architectural semantics still require owner judgment.

### A33.17 Review checklist

For any substantial change, ask:

1. Who owns the semantics and durable state?
2. Is a second source of truth being introduced?
3. Are identities immutable and versioned?
4. What happens on retry, duplicate, cancellation, partial failure, or resume?
5. Does any fallback change scientific/numerical/security behavior silently?
6. Are cross-language/process boundaries typed and compatible?
7. Are data classification and payload-minimization preserved?
8. Can clean CI reproduce and qualify it?
9. Is the capability real, consumed, and operated—or scaffold only?
10. What is the migration, rollback, and deletion path?

### A33.18 Repair protocol

When an anti-pattern is found:

```text
contain new usage
→ identify current authority and affected consumers/artifacts
→ write migration/ADR if boundary changes
→ introduce correct contract alongside old path
→ migrate and qualify consumers
→ remove bypass/duplicate state
→ add automated regression check
→ close exception and update docs
```

Do not perpetuate a defect merely to preserve an accidental internal API without a support decision.

### A33.19 Definition of done

Anti-pattern governance is effective when:

1. prohibited structures are categorized by violated authority/invariant, not taste;
2. high-frequency violations have automated presubmit checks;
3. reviews consistently test identity, retry/failure, security, compatibility, and evidence;
4. discovered bypasses are contained and migrated rather than normalized;
5. every repair removes duplicate authority and adds a regression test;
6. exceptions remain visible and expiring;
7. empty scaffolds and premature abstractions cannot claim production maturity;
8. incidents feed new anti-pattern checks where generalizable;
9. documentation names both prohibited behavior and the approved path;
10. performance or urgency never justifies silent correctness, state, security, or provenance changes.
