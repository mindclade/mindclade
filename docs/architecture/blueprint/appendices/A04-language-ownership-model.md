## Appendix A4 — Language ownership model

| Lane | Primary ownership | Allowed secondary use | Explicit exclusions |
|---|---|---|---|
| Python | Model definitions, objectives, training, evaluation, inference pipelines, scientific transformations, feature semantics | Thin orchestration inside GPU workers; bindings over Rust/native extensions | Control-plane services, high-volume parsers when Rust is justified, cloud controllers, generic platform daemons |
| Rust | Biological format parsing, high-throughput I/O, normalization hot paths, artifact streaming, CPU runtime, memory-safe native extensions | Selected low-latency services and command-line tools | Model research framework, business workflow orchestration, web product |
| Go | Control plane, APIs, Kubernetes controllers, durable job lifecycle, authorization, tenancy, operational services | CLIs and release automation | Tensor numerics, scientific feature semantics, GPU kernels |
| TypeScript | Console, admin, docs app, web/server SDKs, design system | Repository developer tools where Node is already required | Model execution and cluster control plane |
| Protobuf / JSON Schema | RPC, events, manifests, compatibility contracts | Generated OpenAPI and SDK models | Business logic |
| TileLang / CUDA / C++ | Performance-critical GPU kernels and native operators | Narrow native interfaces | General application logic |
| Starlark / Nix / shell | Hermetic build graph, toolchain pinning, bootstrap, small wrappers | Repository automation | Domain or product behavior |

### Hard policy: `libs/python` is torch-free

`libs/python` is a horizontal foundation used by tools, services, data workflows, and local utilities. It must not depend on:

- `torch`;
- model packages;
- training packages;
- CUDA-specific wheels;
- GPU runtime initialization.

PyTorch belongs in `models/`, `training/`, `evaluation/`, `inference/`, and GPU worker release units. A dependency-policy test must enforce this rule.

### A4.1 Language-selection rubric

Choose a language by the dominant constraints of the capability, not team preference.

| Constraint | Preferred lane |
|---|---|
| tensor/model research, autograd, scientific iteration | Python |
| bounded-memory parsing, throughput, memory safety, native I/O | Rust |
| durable APIs, controllers, concurrency-heavy control workflows | Go |
| browser/product UI and web SDKs | TypeScript |
| cross-process schema and compatibility | Protobuf / JSON Schema |
| accelerator-level performance | TileLang / CUDA / narrow C++ |
| build/toolchain description | Starlark / Nix |

A mixed-language implementation is justified when it creates a measurable boundary: for example, Rust parses and validates a corpus, Python owns scientific feature semantics, and the boundary is an Arrow-compatible batch or PyO3 API. A second language must not be introduced merely to wrap a command or duplicate domain types.

### A4.2 Language authority versus deployment authority

Language ownership does not imply a separate service. A Go control plane may call Rust and Python workers through contracts; a Python worker may load Rust bindings; TypeScript apps may consume SDKs. Deployment boundaries are determined by trust, scaling, hardware, lifecycle, and operational needs—not by language.

### A4.3 Common cross-language semantic rules

All lanes use the same concepts for:

- resource names and immutable identifiers;
- time, duration, and deadlines;
- error codes and retry classification;
- content digests and artifact references;
- optional versus missing versus unknown values;
- pagination and cursors;
- idempotency and attempt identity;
- data classification and policy labels;
- schema and compatibility version;
- trace and correlation context.

Generated code may encode these concepts differently, but conformance fixtures prove equivalent semantics.

### A4.4 Python production baseline

Python production packages require:

- typed public interfaces and strict type checking for maintained code;
- explicit package boundaries and `src/` layout for wheels;
- deterministic import behavior without repository-relative hacks;
- no import-time network, GPU allocation, distributed initialization, or secret resolution;
- structured exceptions with stable error classification;
- explicit async/thread/process ownership;
- reproducible serialization and schema validation;
- bounded caches and resource cleanup;
- reference numerics for optimized model and kernel paths;
- wheel and Bazel install/run parity.

`libs/python` additionally prohibits PyTorch, CUDA, model, and training dependencies. Enforcement scans direct and transitive imports and validates built wheel metadata.

### A4.5 Rust production baseline

Rust crates require:

- workspace-inherited edition, lints, dependency versions, and metadata;
- explicit ownership of allocations, buffering, and concurrency;
- streaming APIs for large biological and artifact data;
- `Send`/`Sync` and cancellation semantics documented where exposed;
- structured error enums preserving source and byte/record context;
- fuzz, property, malformed-input, and corpus tests for parsers;
- unsafe code isolated behind stated invariants and targeted tests;
- stable pure-Rust core before bindings;
- no panic across FFI or on malformed external input;
- feature flags that do not create untested dependency combinations.

### A4.6 Go production baseline

Go packages require:

- `context.Context` propagation for deadlines, cancellation, auth, and traces;
- no context stored in long-lived structs;
- explicit idempotency and transactional boundaries;
- typed fault mapping at transport edges;
- bounded goroutines, queues, retries, and connection pools;
- clean shutdown and readiness behavior;
- interfaces defined by consumers, kept narrow;
- service-local `internal/` packages for implementation;
- migration and outbox correctness for durable modules;
- race tests and failure injection for concurrency-sensitive code.

### A4.7 TypeScript production baseline

TypeScript packages require:

- strict compiler settings;
- explicit browser versus Node runtime exports;
- generated clients hidden behind public SDK adapters;
- runtime validation of untrusted network data;
- cancellable requests, typed errors, and retry policy;
- no secrets or authorization policy embedded in client code;
- accessible UI components and keyboard/screen-reader tests;
- stable package exports and public API compatibility checks;
- SSR/client boundary discipline;
- telemetry and privacy policy at interaction boundaries.

### A4.8 Native and accelerator boundary

Native extensions expose the narrowest practical interface:

```text
validated typed inputs
→ explicit device/layout/dtype contract
→ bounded native execution
→ typed result or classified error
```

They must define ownership, lifetime, stream semantics, synchronization, error propagation, ABI compatibility, and fallback behavior. A Python extension cannot terminate the process for ordinary invalid input, silently copy large tensors, or initialize global runtime state without an explicit contract.

### A4.9 Error and cancellation conformance

Each lane maps internal errors to a shared taxonomy:

```text
invalid_argument
failed_precondition
not_found
already_exists
permission_denied
unauthenticated
resource_exhausted
aborted / conflict
unavailable
 deadline_exceeded
cancelled
internal
data_loss
unsupported
policy_denied
```

Retryability is explicit and may differ by operation. Cancellation is cooperative and must not publish partial durable success. Conformance tests send equivalent failure fixtures through Go, Rust, Python, TypeScript, and protocol adapters.

### A4.10 Language-boundary qualification

A cross-language boundary is production-ready only after:

- schema compatibility and generated-code drift checks;
- round-trip and unknown-field tests;
- error, deadline, cancellation, and retry tests;
- Unicode, large payload, and malformed-input tests;
- memory ownership/leak tests where native code is involved;
- throughput and backpressure tests for streams;
- security classification and logging review;
- package/install tests from released artifacts;
- version-skew tests across the supported compatibility window.

### A4.11 Definition of done

1. Every package has one primary language owner and a documented reason.
2. Cross-language boundaries use approved contracts and conformance fixtures.
3. Language-specific production baselines are automated in CI.
4. No domain model is independently reimplemented without a generated or conformance-backed contract.
5. Native and GPU boundaries define lifetime, synchronization, ABI, and failure semantics.
6. `libs/python` remains transitively torch-free.
