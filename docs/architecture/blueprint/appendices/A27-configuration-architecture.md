## Appendix A27 — Configuration architecture

Configuration has six categories:

1. **Code defaults**: safe, environment-independent defaults next to the owner.
2. **Typed recipes**: model, task, phase, training, evaluation, and reproducibility intent in the monorepo.
3. **Promoted systems plans**: immutable hardware/topology/provider/compilation decisions produced by systems tuning.
4. **Scientific studies**: HPO/trial definitions and promotion criteria, separate from systems plans.
5. **Deployment package defaults**: service-owned, non-secret operational defaults.
6. **Environment desired state**: lives in `gitops`, not the monorepo.

Rules:

- every configuration is schema-validated;
- unknown fields fail;
- secrets are references, never values in Git;
- mutable aliases resolve to immutable references before execution;
- configuration digests are recorded in job and artifact manifests;
- environment variables are an injection mechanism, not an undocumented configuration API;
- flags are reserved for operator overrides and debugging, not hundreds of permanent settings;
- recipes express provider-neutral intent;
- raw Megatron namespaces, DeepSpeed JSON, Lightning Trainer configuration, Monarch placement code, or provider singleton state are not the canonical recipe surface;
- provider configuration is generated from the executable plan and recorded in the run manifest;
- systems autotuning and scientific HPO use distinct schemas and artifacts;
- a provider fallback, precision change, phase transition, or topology replan requires an explicit permitted policy and recorded lineage;
- production recipes declare reproducibility level, graph-break budget, health policy, checkpoint tiers, and evaluation staleness limits.

### A27.1 Configuration ownership model

Every configuration field has one semantic owner. The owner defines type, default, validation, mutability, security class, compatibility, and evidence requirements. Configuration is not a cross-cutting dumping ground.

```text
intent configuration
→ schema validation and layered resolution
→ immutable resolved manifest
→ owner-specific compilation into runtime settings
→ sanitized runtime evidence
```

Provider, deployment, and environment adapters consume resolved intent; they do not redefine it.

### A27.2 Configuration categories and boundaries

| Category | Owner | Mutability |
|---|---|---|
| code default | owning package | source-versioned |
| typed scientific recipe | model/training/evaluation/inference owner | immutable after resolution |
| promoted systems plan | planning/autotune owner | immutable artifact |
| study/trial definition | studies/research owner | immutable per trial |
| deployment package default | service/deploy owner | package-versioned |
| environment desired state | GitOps/infrastructure owner | reviewed Git reconciliation |
| secret reference | security/platform owner | externally rotated |
| operator override | authorized execution actor | bounded, recorded, usually attempt-scoped |

Fields must not migrate between categories merely for convenience. Cluster names do not belong in scientific recipes; loss weights do not belong in GitOps overlays.

### A27.3 Schema contract

A configuration schema defines:

```text
field name/type/presence
default and default-source
valid range/enumeration/pattern
cross-field constraints
units and semantic meaning
sensitive/secret/reference classification
mutability and resolution stage
deprecation/migration metadata
owner and documentation
```

Unknown fields fail for production configurations. Experimental extension points use explicit namespaced fields and cannot leak into stable recipes without promotion.

### A27.4 Canonical representation and digest

Resolved configuration is serialized canonically with deterministic field ordering, normalized enums/units, explicit defaults where needed, and stable floating-point/string rules. The digest covers semantic content, schema version, and referenced immutable manifests as defined by the contract.

Comments, source formatting, and secret values are excluded from semantic identity. Secret reference identity and version policy may be included without revealing material.

### A27.5 Resolution pipeline

Resolution follows:

```text
load schema and code defaults
→ load named base recipe/config
→ apply approved environment-independent overlays
→ apply study/trial substitutions if applicable
→ apply explicit authorized operator/debug overrides
→ resolve aliases/references to immutable identities
→ validate cross-domain compatibility and policy
→ emit immutable resolved manifest and provenance
```

Each field records source layer where useful for inspection. Conflicting overlays or duplicate ownership fail rather than relying on order accidents.

### A27.6 Merge semantics

Every compound field declares merge behavior:

```text
scalar replace
map merge by key or replace entirely
sequence replace, append, or keyed merge
explicit delete/clear
set union/intersection where semantically valid
```

Implicit YAML merge keys, environment-variable interpolation, and library-specific coercion do not define production semantics. The resolver implements and tests one language-neutral model.

### A27.7 Reference resolution

Configuration may reference models, datasets, features, checkpoints, suites, resource profiles, providers, or plans by logical resource. Before execution, every mutable alias resolves to an immutable generation/revision and the resolution receipt is embedded in the job/run manifest.

Resolution enforces authorization, compatibility, policy, and revocation. A later alias change does not affect an active or resumed run.

### A27.8 Secret references

A secret field contains a typed reference such as purpose, provider, logical name, and optional version policy—not plaintext. Resolution occurs only in an authorized runtime component and yields an in-memory/file handle with bounded lifetime.

Resolved secret material:

- is never included in configuration digests, logs, manifests, crash reports, or callback payloads;
- is not propagated to child processes unless required;
- is redacted by structure, not regex alone;
- can rotate without changing scientific intent;
- has failure and revocation semantics.

### A27.9 Environment variables

Environment variables are reserved for bootstrap/injection such as endpoint discovery, workload identity paths, and narrowly defined operator settings. Each accepted variable has a schema, owner, type, default, and precedence.

Arbitrary `os.environ.get()` behavior is prohibited in domain code. Production configuration inspection lists sanitized effective environment-derived settings.

### A27.10 Command-line flags

Flags expose entrypoint actions and bounded overrides, not the complete permanent configuration model. A flag maps to a typed field or command parameter and records its effect in the resolved manifest.

Dangerous debug overrides require explicit names, authorization, and evidence that the run is non-production or waiver-scoped. Hidden flags and provider passthrough namespaces are prohibited.

### A27.11 Scientific recipes

Recipes express provider-neutral intent:

```text
model/task/phase and objective
immutable data and feature inputs
optimization and precision intent
reproducibility and health policy
evaluation and checkpoint policy
logical resource/topology constraints
allowed capability/fallback classes
observability/safety policy
```

They do not include rank lists, NCCL communicator details, Kubernetes node selectors, cloud bucket paths, or raw Megatron/DeepSpeed/Lightning configuration. Those are compiled by plan/deployment adapters and evidenced separately.

### A27.12 Systems plans

Promoted systems plans bind concrete topology, placements, providers, kernels, compilation, memory, batching, and communication choices. They reference the scientific intent they are valid for and a hardware/workload class.

Plans are immutable and cannot be hand-edited after tuning/qualification. A change produces a new plan and qualification lineage.

### A27.13 Study and trial configuration

Scientific HPO substitutes only fields declared in the study search space. Every trial receives a fully resolved immutable configuration. The study cannot mutate provider/topology/system fields unless those are explicitly part of a separate systems study.

Search-space schemas enforce types, conditional constraints, budgets, and reproducibility. Failed/invalid trials remain recorded.

### A27.14 Deployment configuration

Service-owned deployment defaults include ports, health paths, concurrency, timeouts, resource requests/limits, and safe feature settings. GitOps overlays bind environment endpoints, replicas, autoscaling, policies, and secret references.

Application code consumes typed effective configuration. It never reads arbitrary Kubernetes YAML or live GitOps files.

### A27.15 Dynamic configuration and feature flags

Dynamic configuration is exceptional. A field is dynamically mutable only when:

- owner and scope are explicit;
- consistency/staleness semantics are defined;
- safe default and rollback exist;
- changes are authorized/audited;
- the value is not part of numerical, artifact, checkpoint, protocol, or security identity unless the transition is versioned;
- clients/workers define update boundaries.

Feature flags do not bypass compatibility, migrations, or qualification. Scientific/training behavior remains frozen within official runs.

### A27.16 Validation stages

Validation occurs at:

1. parse/schema validation;
2. local semantic validation;
3. cross-field validation;
4. cross-artifact compatibility;
5. authorization/policy validation;
6. hardware/provider/capability preflight;
7. runtime assertion of resolved assumptions.

Errors identify field path, value class, constraint, source layer, and safe remediation. Secret values and restricted references are not echoed.

### A27.17 Compatibility and migration

Schema changes follow:

- additive optional fields with stable defaults;
- deprecation before removal;
- explicit rename/split/merge migration;
- behavior-changing default changes only with new schema or versioned recipe;
- preserved ability to read supported historical manifests;
- canonical migration output and fixtures;
- recorded source/target schema and migration tool digest.

A migration never silently changes scientific meaning. Ambiguous legacy fields require operator choice or fail.

### A27.18 Configuration provenance and inspection

Inspection tools show:

```text
resolved value
schema/default
source layer and override history
immutable reference resolution
owner/documentation
sensitive redaction
validation and policy result
configuration digest
```

`mindclade ... plan/inspect` works without allocating large resources. The final run/job manifest stores the exact resolved configuration and adapter-generated provider/deployment manifests.

### A27.19 Testing

Configuration tests include:

- schema examples and invalid cases;
- unknown fields and type coercion rejection;
- merge/clear semantics;
- canonical serialization/digest stability;
- overlay precedence and conflict;
- secret redaction;
- alias resolution and revocation;
- historical migration;
- cross-artifact compatibility;
- provider adapter output;
- environment/flag inspection;
- policy-denied configurations.

Property tests vary layer combinations and field presence to detect accidental precedence behavior.

### A27.20 Configuration qualification levels

| Level | Required evidence |
|---|---|
| `config-c0` | typed schema, unknown-field failure, canonical serialization and docs |
| `config-c1` | layered resolution, references, redaction, migrations, cross-field tests |
| `config-c2` | artifact/policy/provider/deployment compatibility and clean preflight |
| `config-c3` | production rollout/override/audit, historical restore, and incident inspection |

### A27.21 Capability-local qualification progression

**Milestone 0 — common config library:** schemas, canonical values, merge/resolution, error model, digest, secret references, and inspection.

**Milestone 1 — scientific contracts:** model/training/evaluation/inference recipes and immutable artifact reference resolution.

**Milestone 2 — systems/deployment adapters:** executable plans, provider config generation, component defaults, GitOps handoff, and policy preflight.

**Milestone 3 — lifecycle:** migrations, deprecations, controlled dynamic flags, audit, historical reproduction, and config incident tooling.

### A27.22 Definition of done

Configuration architecture is production-ready when:

1. every field has one owner, type, semantic meaning, default, and mutability contract;
2. production parsing rejects unknown fields and implicit unsafe coercions;
3. layer/merge precedence is deterministic, inspectable, and tested;
4. all aliases resolve to immutable authorized artifacts before execution;
5. secrets remain references and never enter semantic digests or evidence;
6. recipes remain provider- and environment-neutral while plans/deployment adapters own concrete lowering;
7. official runs freeze resolved scientific and systems configuration;
8. schema migrations preserve or explicitly change meaning with lineage;
9. command-line/environment overrides are bounded, typed, recorded, and policy-aware;
10. a clean preflight can explain exactly what will execute without allocating production resources.

### A27.23 Final configuration invariants

- configuration is typed intent, not an arbitrary YAML dictionary;
- one field has one semantic owner;
- secrets are references, never values in Git or manifests;
- mutable aliases disappear at execution resolution;
- provider and environment configuration are generated outputs;
- production behavior cannot change through hidden flags, environment reads, or live mutable config.
