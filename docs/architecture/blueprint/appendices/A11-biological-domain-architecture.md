## Appendix A11 — Biological domain architecture

### A11.1 Canonical entity semantics

Mindclade needs explicit, versioned semantics for:

- atoms and coordinates;
- residues and modifications;
- polymer and non-polymer chains;
- assemblies and biological units;
- sequences and alphabets;
- alignments;
- chemical components and bonds;
- missingness and uncertainty;
- alternate locations and occupancy;
- provenance and source identifiers;
- model-ready features.

The canonical semantic schema lives under `bio/schemas/`. Rust and Python implementations must pass the same conformance fixtures.

### A11.2 Parsing and I/O

Rust is the default for:

- FASTA;
- A3M;
- Stockholm;
- mmCIF;
- PDB;
- CCD;
- SDF or equivalent small-molecule exchange formats;
- compressed stream handling;
- indexing and random access;
- validation over large corpora.

A parser must expose:

- streaming and bounded-memory operation where practical;
- strict and permissive modes;
- structured diagnostics;
- source byte offsets when meaningful;
- deterministic output;
- explicit handling of malformed records;
- fuzz and property tests;
- golden fixtures from legally distributable examples.

Python bindings expose typed batches or Arrow-compatible structures. They do not leak Rust implementation internals into model code.

### A11.3 Scientific semantics stay above parsing

Parsing answers, “What does the source file contain?”

Scientific normalization answers, “What does this record mean for Mindclade's model and dataset contract?”

Do not combine them. Source-faithful parsed records should remain available for audit and reprocessing.

### A11.4 Biological semantic planes

The biological domain separates four planes:

```text
source-faithful syntax
→ canonical biological entities
→ scientific normalization and derived meaning
→ reusable semantic feature values
→ model-specific feature views/representation
```

Each plane has a distinct artifact/schema boundary. A parser may report exactly what a source encoded even when the record is chemically incomplete or inconsistent. Canonical entities reconcile source-specific representation into Mindclade semantics without yet making model-specific choices. Scientific normalization adds policy-driven interpretation. Reusable semantic featurization derives model-independent values where the meaning is genuinely shared; model families then own versioned feature views and tensor representations. A shared feature MUST NOT be named or keyed by a model merely because one model first consumed it.

No plane may silently discard the prior representation required for audit or reprocessing.

### A11.5 Canonical entity graph

The canonical entity model includes:

```text
Structure
  assemblies
  models / conformers
  chains and entity references
  residues / components
  atoms and coordinates
  bonds and connection evidence
  symmetry and transforms
  source/provenance annotations

Sequence
  alphabet and polymer class
  canonical and observed symbols
  modifications and ambiguity
  positions and source mapping

ChemicalComponent
  identifiers and synonyms
  atoms, bonds, charges, stereochemistry
  ideal/reference coordinates
  polymer linkage roles
  provenance and version
```

Entities use immutable internal identifiers that remain stable within an artifact. Source identifiers are preserved separately and never assumed globally unique.

### A11.6 Units, frames, and numerical representation

Every numerical field declares its semantics:

- length units, normally Ångström for structural exchange and an explicit canonical internal unit;
- angle units;
- coordinate frame and transform direction;
- occupancy and uncertainty interpretation;
- temperature/B-factor semantics;
- formal versus partial charge;
- integer versus floating bond order representation;
- missing, unknown, not-applicable, and not-observed distinctions;
- precision and rounding rules for serialization.

Coordinate arrays carry or reference a `CoordinateFrame`:

```text
frame identity
units
right/left handedness
origin and basis
parent frame
transform to parent
periodic/symmetry context
```

Algorithms may not assume coordinates from different models, assemblies, or artifacts share a frame without an explicit transform.

### A11.7 Atom and residue identity

An atom identity distinguishes:

```text
canonical component atom identity
source atom label
chain/entity/residue instance
alternate-location identity
model/conformer identity
symmetry/assembly instance
```

A residue/component instance distinguishes author numbering, label numbering, insertion code, canonical sequence position, and observed order. These are separate fields. Converting one numbering system into another produces an explicit mapping with diagnostics; it is never inferred from a concatenated string.

### A11.8 Polymer and sequence semantics

Supported polymer classes include proteins/peptides, DNA, RNA, and explicitly typed noncanonical polymers. A sequence schema declares:

- alphabet/version;
- canonical symbol;
- observed source symbol;
- chemical component reference;
- modification and parent component;
- ambiguity set;
- gap/missingness semantics;
- terminal/circular topology;
- mapping to structural residue instances;
- source offsets and provenance.

Sequence normalization must not convert a modified residue to its parent without preserving the modification and original component identity.

### A11.9 Chemical component and bond semantics

Chemical components are versioned against a specific CCD or approved chemistry source. Canonicalization includes:

- atom identity and element/isotope;
- formal charge and valence diagnostics;
- aromaticity model and provenance;
- stereochemistry and chirality;
- bond order/type and source evidence;
- leaving atoms and polymer linkage roles;
- tautomer/protonation representation policy;
- canonical graph digest;
- synonyms and external identifiers.

Mindclade must distinguish source-declared bonds, dictionary bonds, inferred geometric bonds, and model-generated bonds. Each bond carries evidence and confidence/policy, so inference never masquerades as source truth.

### A11.10 Assemblies, symmetry, and connectivity

A biological assembly is represented by references to source entities plus explicit transforms. Materializing all copies is optional and must be bounded. The schema supports:

```text
assembly definition and source
operation matrices
operation composition order
entity/chain selection
symmetry context
materialized-instance mapping
inter-chain covalent connections
```

Assembly generation is deterministic. Duplicate transforms, invalid matrices, missing chains, and expansion limits produce structured diagnostics.

### A11.11 Alternate locations, conformers, and ensembles

Alternate locations are not flattened by default. The canonical representation records occupancy, selection groups, and mutual-exclusion relationships. A downstream policy may select:

- highest occupancy;
- a named alternate;
- all alternates as an ensemble;
- source order with deterministic tie-breaking;
- a task-specific sampled conformer.

The selected policy and resulting mapping become part of normalization and feature lineage.

Multiple models, NMR ensembles, predicted samples, and trajectories use an explicit ensemble dimension. They are not overloaded into alternate-location fields.

### A11.12 Missingness and uncertainty

Use typed missingness reasons such as:

```text
not_present_in_source
not_observed
not_modeled
not_applicable
unknown_component
invalid_value
filtered_by_policy
outside_selected_assembly
```

Missingness masks are separate from zero-filled numerical arrays. Uncertainty may include occupancy, B-factor, coordinate covariance/variance, confidence scores, or source-specific quality fields, each with provenance and interpretation.

### A11.13 Source-faithful parser contract

A parser exposes a common shape:

```python
class BiologicalParser(Protocol):
    def inspect(self, source: ByteSource) -> SourceSummary: ...
    def records(
        self,
        source: ByteSource,
        *,
        mode: ParseMode,
        limits: ParseLimits,
    ) -> Iterator[ParsedRecord]: ...
```

`ParseLimits` constrains bytes, records, nesting, token length, assembly expansion, decompression ratio, and diagnostics. `ParsedRecord` contains the source-faithful value, byte/line/record location, recoverable diagnostics, and source revision.

Strict mode rejects violations required by the format or selected profile. Permissive mode recovers only through documented deterministic rules and records every recovery.

### A11.14 Diagnostic taxonomy

Diagnostics include:

```text
severity: info / warning / error / fatal
code: stable machine-readable identifier
source span or record identity
entity path
message and safe context
recovery action
related diagnostics
```

Examples include duplicate atom identifiers, unknown components, invalid numeric fields, noninvertible transforms, sequence/structure mismatch, inconsistent bond order, impossible valence, and unsupported extension categories.

Diagnostic codes are stable enough for corpus quality reports and policy decisions. Human messages may evolve.

### A11.15 Streaming, indexing, and bounded memory

Large-format readers support:

- incremental decompression with ratio and size limits;
- record streaming without loading the corpus;
- selective category/column reading where the format permits;
- byte-range and record indexes;
- zero-copy or bounded-copy slices where safe;
- deterministic parallel parsing with ordered output;
- cancellation and early termination;
- checksums over raw and parsed partitions.

Memory and CPU complexity are documented by input dimension. Adversarial input cannot trigger unbounded allocation before limits are checked.

### A11.16 Format-specific authority

Each format package owns:

```text
supported specification/profile versions
lexical and syntactic parser
source-faithful typed representation
serializer where meaningful
strict/permissive behavior
extension handling
limits and security model
fixtures and corpus coverage
compatibility policy
```

A serializer declares whether it is lossless, semantically equivalent, or a normalized export. Round-trip tests use the appropriate guarantee rather than assuming byte identity.

### A11.17 Python and Arrow boundary

Rust-to-Python bindings expose immutable or ownership-clear typed views. Preferred transfer mechanisms are:

- Arrow-compatible arrays/record batches;
- NumPy-compatible buffers for dense numerical data;
- compact typed Python objects for metadata;
- iterators/streams for large corpora.

Bindings document buffer lifetime, mutability, thread/GIL behavior, exceptions, and copy cost. Python model code must not rely on Rust struct layout or unsafe capsules as a durable API.

### A11.18 Canonicalization and normalization contracts

Normalization is a versioned transformation with explicit policy inputs:

```text
component dictionary version
polymer and sequence policy
alternate-location policy
assembly selection
bond inference policy
unknown-component policy
filtering/quarantine policy
coordinate/unit policy
```

Output includes canonical entity artifact, source-to-canonical mapping, diagnostics, excluded elements, and transformation lineage. Re-running the same version and inputs produces the same output.

### A11.19 Cross-language conformance

Rust is normally the canonical parser implementation. Python reference or consumer implementations must agree on:

- entity identities and ordering;
- source mappings;
- units and frames;
- missingness;
- component/bond semantics;
- diagnostic codes;
- canonical digests;
- serialization where supported.

Conformance fixtures include valid minimal cases, realistic public examples, malformed/adversarial inputs, Unicode/encoding cases, large-count boundaries, and every supported polymer/chemical class.

### A11.20 Biological validation levels

| Level | Meaning |
|---|---|
| syntax-valid | input conforms to selected format grammar/profile |
| structurally coherent | identifiers, references, dimensions, and transforms are internally valid |
| chemically coherent | element, valence, bond, chirality, and component rules pass selected policy |
| biologically coherent | polymer/sequence/assembly relationships satisfy domain invariants |
| task-compatible | representation satisfies a named model/feature contract |
| release-qualified | corpus and implementation pass scale, determinism, security, and regression gates |

A record can be syntactically valid but chemically or task invalid. Reports preserve the distinction.

### A11.21 Security and governance

Biological parsers handle untrusted input. Required controls include:

- decompression and expansion bombs limits;
- path traversal and archive-entry validation;
- bounded recursion and token length;
- no dynamic code execution;
- safe temporary-file handling;
- fuzzing and sanitizer lanes;
- data classification propagation;
- payload-free default logging;
- license/source metadata preservation.

### A11.22 Biological qualification gates

#### BQ0 — schema and fixtures

Canonical schemas, identifiers, units, missingness, and diagnostic taxonomy are approved.

#### BQ1 — parser correctness

Golden, malformed, round-trip, property, and cross-language tests pass.

#### BQ2 — corpus scale

Large public corpora parse with bounded memory, deterministic partitioning, and stable diagnostics.

#### BQ3 — scientific conformance

Canonicalization, component chemistry, assembly, sequence mapping, and task compatibility pass expert-reviewed fixtures.

#### BQ4 — production security

Fuzzing, decompression limits, malformed-input resilience, and supply-chain/license review pass.

### A11.23 Capability-local qualification progression

1. Freeze canonical atom/residue/chain/assembly/sequence/component schemas.
2. Implement Rust FASTA, A3M, Stockholm, mmCIF, PDB, CCD, and SDF readers with diagnostics.
3. Add source-to-canonical normalization and Python/Arrow bindings.
4. Add conformance corpus, fuzzing, indexes, and deterministic parallelism.
5. Qualify model-facing feature input mappings and corpus-scale operation.

### A11.24 Definition of done

1. Every biological value has explicit identity, units/frame, missingness, and provenance.
2. Source representation remains recoverable after canonicalization.
3. Parsers are streaming, bounded, deterministic, and safe on malformed input.
4. Rust and Python consumers pass shared conformance fixtures.
5. Alternate locations, assemblies, modifications, and inferred bonds are never silently flattened.
6. Biological and task validation levels are distinct and reportable.
7. Parser and normalization versions are present in every downstream dataset and feature lineage.
