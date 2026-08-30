## Appendix A5 — Organizing principle: domain first, language second

Top-level directories represent durable business or technical domains. Language-specific implementations live inside those domains where needed.

Prefer:

```text
data/ingestion/pdb/rust/
models/families/clade/cladefold/python/
services/control_plane/go/
```

over:

```text
python/everything/
rust/everything/
go/everything/
```

A language-first repository becomes four adjacent repositories with weak integration. A domain-first repository keeps each capability's contracts, tests, documentation, and implementations close together while retaining language boundaries.

`libs/` is reserved for genuinely horizontal capabilities. Biological entities, mmCIF parsing, feature schemas, model components, and dataset logic are domain packages, not generic libraries.

### A5.1 Bounded-context rule

A top-level domain represents a stable bounded context with its own vocabulary, invariants, artifacts, and owner. It should survive changes in language, framework, or deployment topology.

A domain is justified when it has at least three of:

- distinct semantic vocabulary;
- independent invariants and qualification;
- artifacts with their own lifecycle;
- a durable owner or team boundary;
- a meaningful dependency direction;
- a distinct security/data classification profile;
- a plausible independent release or deployment boundary.

A directory is not a domain merely because it contains many files.

### A5.2 Domain package anatomy

A domain capability keeps together:

```text
contracts and schemas
reference implementation
optimized or language-specific implementations
fixtures and conformance tests
artifact semantics
qualification and benchmarks
README and ownership
release/deployment metadata when applicable
```

Language subdirectories are adapters or implementations of the same domain meaning. They do not become parallel sources of truth.

### A5.3 Capability placement decision

Use this decision sequence:

1. Is the capability cross-process or cross-language? Put the contract in `protocols/`.
2. Is it genuinely horizontal and domain-neutral? Put it in `libs/<language>/`.
3. Does it define biological meaning? Put it in `bio/`.
4. Does it define acquisition, curation, lineage, or dataset transformation? Put it in `data/`.
5. Does it define generic device/distributed/compiler primitives? Put it in `runtime/`.
6. Is it an optimized operation with dispatch/qualification? Put it in `kernels/`.
7. Is it model mathematics or state schema? Put it in `models/`.
8. Is it training, evaluation, or inference semantics? Put it in the corresponding domain.
9. Is it a composition root? Put it in `services/`, `workers/`, or `apps/`.
10. Is it exploratory and not yet supported? Put it in `research/`.

When two answers appear valid, choose the lower-level semantic owner and expose a narrow adapter to the higher-level consumer.

### A5.4 Package creation, merge, and split criteria

Create a package only when it has:

- a named owner;
- at least one real consumer or deployable target;
- a clear public surface;
- dependency restrictions;
- tests and build target;
- a non-overlapping purpose.

Merge packages when they share ownership, release cadence, invariants, and consumers and their separation creates forwarding layers without independent value.

Split a package when it develops a distinct trust boundary, scaling profile, compatibility contract, artifact lifecycle, or owner. File count is not a split criterion.

### A5.5 Naming rules

Names describe durable concepts, not current implementation techniques.

Prefer:

```text
artifact_reference
training_run
pair_representation
checkpoint_generation
source_snapshot
```

Avoid:

```text
misc
common2
new_pipeline
fast_utils
v2_impl
manager_helpers
```

Terms such as `core`, `common`, `utils`, and `shared` require a specific documented scope. `shared` packages are created only after two maintained consumers demonstrate stable common semantics.

### A5.6 Domain API policy

Each domain defines:

- public contracts and stability level;
- internal implementation packages;
- artifact formats and versions;
- errors and failure classification;
- extension points, if any;
- compatibility window;
- migration and deprecation policy;
- observability and security requirements.

Consumers may depend only on the documented public surface. Deep imports across domain internals are blocked by Bazel visibility, package exports, Go `internal/`, and static checks.

### A5.7 Anti-corruption layers

External providers and source systems enter through adapters that translate into Mindclade semantics.

Examples:

- PDB/UniProt/RNACentral metadata becomes source descriptors and normalized biological records;
- Megatron or Transformer Engine state becomes logical Mindclade state;
- cloud storage SDK errors become artifact-layer faults;
- Kubernetes status becomes observed workload state before control-plane reconciliation;
- generated Protobuf clients become SDK resource models.

External naming, global configuration, database structs, and error taxonomies must not spread beyond the adapter boundary.

### A5.8 Domain dependency budgets

Every domain publishes:

```text
allowed upstream domains
forbidden dependencies
permitted third-party categories
runtime/network permissions
data classifications
build and test cost class
```

New dependencies are reviewed for architectural direction, supply-chain risk, binary/image impact, initialization side effects, and compatibility burden.

### A5.9 Domain documentation and decision records

Each domain has an architecture page covering:

- vocabulary and entity model;
- ownership and boundaries;
- primary flows;
- state and artifact lifecycle;
- failure and recovery behavior;
- security and observability;
- qualification and release gates;
- extension and migration policy.

Implementation detail stays in package documentation. Cross-domain decisions use ADRs.

### A5.10 Domain maturity gates

| Maturity | Minimum evidence |
|---|---|
| experimental | owner, purpose, isolation, no production dependency |
| incubating | contracts, tests, build integration, migration plan |
| supported | compatibility policy, docs, conformance, release evidence |
| production | SLO/runbook/security review, qualification, recovery drills |
| deprecated | replacement, migration tooling, removal date |
| retired | no active consumers, retained lineage and historical docs |

### A5.11 Definition of done

1. Every top-level capability has exactly one domain owner.
2. Packages are created from real consumers, not speculative trees.
3. Public and internal surfaces are enforceable.
4. External systems terminate at anti-corruption adapters.
5. Domain dependency directions match Appendix A7.
6. Each production domain has complete lifecycle, failure, security, qualification, and migration documentation.
