## Appendix A15 — Kernel architecture

> **ADR-0009 source-incubation exception.** Through 2026-11-30, `kernels/native/` may exist as a populated TARGET/proposed component with an empty native-operator inventory. The exception covers only reviewable schema registration, deterministic build-time projections, offline TileLang intake, fail-closed loading policy, build definitions, tests, and documentation. It does not satisfy Wave 5, JIT-06, kernel K0, numerical or hardware qualification, signed-artifact, fallback, revocation, connected, or production gates. Every eventual operator must register exclusively as `torch.ops.mindclade.<name>` and still requires operation-local semantics, reference parity, gradients, measured need, an operation-specific JIT-06 ADR, immutable qualification evidence, and reference fallback before activation.

### A15.1 Kernel package contract

Every optimized operation provides:

```text
reference implementation
optimized implementation
shape/dtype/layout capability declaration
semantic-axis assumptions
dispatch policy
autotuning search space
correctness tests
gradient tests
determinism/reproducibility claims
hardware qualification
benchmarks
fallback policy
state or calibration implications
```

### A15.2 Registry key

A kernel qualification key includes at least:

```text
operation
implementation version
input/output dtypes
accumulation dtype
shape or shape family
semantic axes
layout/strides
mask/bias mode
device architecture
compiler/toolchain version
determinism mode
reproducibility level
numerical tolerance profile
```

A benchmark result without this key is not actionable.

### A15.3 Dispatch policy

Production dispatch is explicit:

1. Resolve the operation signature and semantic-axis contract.
2. Select only implementations qualified for the current signature, hardware, precision, and reproducibility policy.
3. Apply deterministic, safety, memory, and compilation constraints.
4. Bind the selected implementation and qualification digest into the executable plan.
5. Record the decision in provider, compiled-region, and run manifests.
6. Fail clearly or use only an explicitly approved reference fallback.

Never silently use a slower or numerically different path in a production qualification run.

### A15.4 Qualification gates

For each supported signature:

- forward parity;
- backward/gradient parity;
- update-level parity where fusion changes optimizer-visible behavior;
- finite-difference or high-precision checks where appropriate;
- randomized and adversarial shape coverage;
- NaN/Inf behavior;
- determinism and reproducibility where claimed;
- memory safety;
- race detection where available;
- performance floor versus the accepted baseline;
- compilation-cache behavior;
- clean-process reproducibility;
- checkpoint/calibration-state round trips when applicable.

Benchmarks are structured artifacts and compared statistically. A single best timing is not a release gate.

### A15.5 Compiled artifacts and shadow qualification

A promoted kernel or fused region produces an immutable artifact containing:

```text
source and generated-code digests
compiler/toolchain identity
hardware compatibility
shape/dtype/layout constraints
autotune record
qualification report
fallback policy
```

For high-risk or newly promoted kernels, sampled shadow qualification may compare the optimized result with the maintained reference path outside the critical numerical schedule. Drift triggers the configured health policy and may quarantine the capability.

Kernel dispatch may be shared by training and inference, but promotion evidence is workload-specific. An inference-only qualification does not imply backward, optimizer-update, or long-horizon training qualification.

### A15.6 Kernel-system planes

The kernel subsystem is divided into four authority planes:

```text
operation semantics and reference path
→ implementation capability and dispatch
→ compilation/autotuning and immutable binaries
→ workload-specific qualification and promotion
```

`kernels/api/` defines operation meaning and signatures. `kernels/registry/` and `kernels/dispatch/` select only qualified implementations. Operation packages own reference and optimized implementations. `kernels/qualification/` owns evidence, not implementation policy. The training or inference executable plan freezes the selected kernel; no hot-loop component performs independent provider discovery.

### A15.7 Operation contract

Every public kernel operation has a provider-neutral specification:

```python
from dataclasses import dataclass
from typing import Mapping, Protocol, Sequence

@dataclass(frozen=True, slots=True)
class TensorSpec:
    dtype: str
    semantic_axes: tuple[str, ...]
    shape: tuple["DimExpr", ...]
    layout: "LayoutConstraint"
    device: "DeviceConstraint"

@dataclass(frozen=True, slots=True)
class OperationSignature:
    operation: str
    version: int
    inputs: Mapping[str, TensorSpec]
    outputs: Mapping[str, TensorSpec]
    attributes: Mapping[str, "CanonicalValue"]
    side_effects: frozenset[str]

class KernelImplementation(Protocol):
    def capability(self) -> "KernelCapability": ...
    def invoke(self, *args: object, **kwargs: object) -> object: ...
```

The operation specification defines:

- mathematical function and approximation, if any;
- input, output, and gradient semantics;
- semantic axes and legal broadcasting;
- mask, bias, padding, ragged, and causal behavior;
- accumulation and reduction order where material;
- aliasing and in-place guarantees;
- supported autograd orders;
- NaN, Inf, denormal, and empty-dimension behavior;
- deterministic and reproducibility modes;
- numerical reference and tolerance profiles;
- required calibration or persistent state.

An implementation is replaceable only when it satisfies the same operation version. A semantics change creates a new operation version rather than silently widening tolerances.

### A15.8 Reference implementation policy

Every optimized operation retains a maintained reference implementation using ordinary PyTorch or another simple, auditable substrate. The reference path prioritizes clarity and mathematical faithfulness over speed.

Reference implementations must:

- avoid the optimization under test;
- support CPU or a small GPU fixture where practical;
- expose intermediate values for diagnosis when safe;
- use higher-precision accumulation for oracle tests where appropriate;
- cover forward and backward semantics;
- be stable enough to generate qualification fixtures;
- remain installable without custom compiler toolchains for CPU tests.

For very large operations, reduced-size references are acceptable if the decomposition and equivalence argument are documented. A vendor kernel is not the sole reference for a Mindclade kernel.

### A15.9 Capability declaration

A `KernelCapability` is immutable and machine-readable:

```text
implementation identity and source digest
operation/version
hardware architecture and minimum driver/runtime
compiler/backend versions
input/output/accumulation dtypes
shape families and divisibility constraints
semantic-axis and layout constraints
mask/bias/ragged modes
forward/backward/higher-order-gradient support
determinism and reproducibility level
workspace and alignment requirements
compilation and CUDA-graph compatibility
persistent/calibration state contract
explicit fallback class
qualification report digests
```

Capabilities use positive allowlists. “All shapes” or “all dtypes” is not accepted unless proven by construction and tested with bounded property generation.

### A15.10 Dispatch resolution

Dispatch is a pure resolution step over immutable inputs:

```text
OperationSignature
+ realized shape/layout
+ hardware and toolchain identity
+ precision/reproducibility policy
+ workload class
+ promoted capability set
= DispatchDecision
```

A `DispatchDecision` records:

```text
selected implementation
qualification key and report digest
compiled artifact or JIT policy
workspace estimate
fallback decision and reason
selection-rule version
```

The resolver applies, in order:

1. exact semantic operation/version compatibility;
2. hardware and software compatibility;
3. dtype, shape, layout, alignment, mask, and gradient requirements;
4. determinism and reproducibility constraints;
5. compilation/CUDA-graph constraints;
6. memory/workspace budget;
7. workload-specific qualification and performance floor;
8. deterministic tie-breaking.

Production plans bind the decision before execution. Runtime dispatch may select among preapproved shape buckets but may not reach an unqualified implementation.

### A15.11 Fallback classes

Fallback is explicit and typed:

| Class | Meaning | Production behavior |
|---|---|---|
| `reference_exact` | maintained semantic reference, same declared precision | permitted only when recipe allows |
| `qualified_alternate` | another optimized implementation with equivalent contract | permitted if bound in plan |
| `recompile_same_source` | same implementation for a new promoted shape guard | only under declared compilation policy |
| `degraded_precision` | changes precision or numerical contract | never silent; normally fail closed |
| `unsupported` | no valid implementation | preflight failure |

An OOM, compiler error, or graph break does not automatically authorize a different kernel. Fallback records become run evidence and may invalidate performance or reproducibility claims.

### A15.12 Autotuning contract

Autotuning searches implementation parameters, not scientific semantics. A search space may include:

```text
tile and block dimensions
warp/thread allocation
pipeline stages
TMA descriptors
shared-memory layout and swizzle
register and occupancy tradeoffs
split-K or reduction strategy
persistent-kernel scheduling
fusion boundaries
```

The tuner receives a frozen operation signature, shape/workload distribution, hardware manifest, correctness profile, workspace budget, warmup policy, and objective. It must:

- reject candidates that fail correctness before ranking performance;
- isolate compilation and benchmark processes;
- control clock/warmup/synchronization methodology;
- measure distributions, not one best sample;
- detect thermal, contention, and outlier effects;
- record every attempted configuration and failure class;
- use a holdout shape set when promoting generalized rules;
- produce an immutable `AutotuneRecord`.

Production never performs unconstrained first-use tuning. It consumes promoted records or uses a bounded, policy-approved cache-population lane outside an official run.

### A15.13 TileLang, CUDA, and C++ ownership

TileLang is the preferred authored optimization lane for suitable tensor kernels, especially Pairformer and biological-model operations. CUDA or C++ is justified when:

- required primitives are unavailable or materially limited;
- host/device integration demands a native extension;
- collective or communication fusion requires vendor APIs;
- a security- or performance-critical runtime shim cannot be expressed safely elsewhere.

Native code is kept behind a narrow ABI and operation contract. It must declare compiler flags, architecture targets, exception/error translation, stream semantics, memory ownership, and shutdown behavior. Unsafe host code and pointer arithmetic receive focused invariants, sanitizers where supported, and code ownership review.

### A15.14 Memory, streams, and aliasing

Each implementation documents:

- input/output aliasing;
- temporary workspace size as a shape expression;
- allocation ownership;
- stream capture compatibility;
- synchronization behavior;
- asynchronous error surfacing;
- alignment and stride requirements;
- lifetime of descriptors or compiled handles;
- behavior under allocator pressure.

Kernels do not call global device synchronization except where the operation contract explicitly requires it. Hidden allocations in a captured region are prohibited. Workspace estimates feed the executable-plan memory model.

### A15.15 Gradient and autograd contract

For differentiable operations, qualification covers:

```text
forward
vector-Jacobian product
parameter/input gradients
mixed requested-gradient masks
recomputation/checkpointing behavior
gradient accumulation and reduction interaction
optional higher-order gradients
```

Custom autograd functions save only declared state, respect autocast/precision policy, and do not rely on mutable global buffers. In-place modifications are rejected unless alias analysis proves correctness. Gradient tests use reference autograd, finite differences or complex-step methods where appropriate, and update-level comparisons for fused operations.

### A15.16 Numerical qualification profiles

Tolerance is operation- and regime-specific. A profile defines:

```text
reference dtype and accumulation
absolute/relative/ULP criteria
per-output and per-gradient thresholds
norm and cosine-similarity thresholds
rare-tail limits
NaN/Inf equivalence
statistical criteria for nondeterministic reductions
long-chain or repeated-application drift budget
```

Qualification includes adversarial inputs: extreme magnitudes, cancellation, sparse masks, all-masked rows, empty partitions, ragged tails, near-singular geometry, odd strides, non-contiguous views, and boundary dimensions.

Pairformer kernels additionally test symmetry/transpose expectations, row/column orientation, mask propagation, residue-padding behavior, and repeated-block drift. Diffusion kernels test timestep extremes, schedule-sensitive scaling, and coordinate stability.

### A15.17 Determinism and reproducibility

An implementation declares one of:

```text
bitwise deterministic on an exact stack
numerically deterministic within a tolerance profile
statistically reproducible
nondeterministic and prohibited under strict policy
```

Tests vary launch order, stream placement, repeated executions, process restarts, and supported device counts. Atomic reduction order or vendor-library algorithm selection must be recorded when it limits determinism.

### A15.18 Performance qualification

A performance report includes:

- latency distribution after controlled warmup;
- throughput for representative shape mixtures;
- memory bandwidth and compute utilization estimates;
- workspace and peak allocated memory;
- compile latency and cache hit behavior;
- launch count and fusion benefit;
- comparison against reference and accepted baseline;
- regression confidence interval;
- hardware, clocks/power policy, driver, runtime, and contention context.

Gates are workload-specific. A microbenchmark speedup that reduces end-to-end throughput, increases peak memory beyond plan headroom, or harms convergence is not promotable.

### A15.19 Compiled artifact lifecycle

The lifecycle is:

```text
source + operation spec
→ hermetic compile
→ candidate binary
→ correctness/gradient qualification
→ performance qualification
→ signed kernel bundle
→ registry promotion
→ executable-plan binding
→ telemetry and revocation
```

A kernel bundle contains generated source where policy permits, binary/cubin or equivalent artifacts, architecture compatibility, compiler options, dispatch metadata, autotune record, SBOM/license data, qualification reports, and signature/provenance.

Revocation prevents new plans from selecting a capability. Existing runs follow explicit policy: continue, checkpoint-and-stop, or replan from a durable boundary. The registry never mutates an existing qualification record in place.

### A15.20 Shape-bucket and compilation interaction

Dynamic workloads resolve to declared shape families. A family defines guard ranges, padding policy, semantic validity, memory estimate, and kernel selection. New shape guards are not introduced during a release run unless the compilation policy permits and produces immutable evidence.

The compiler and kernel registries share identities but remain distinct:

- a leaf kernel may be precompiled and called from eager or compiled graphs;
- a compiled region may fuse multiple operations and therefore requires region-level evidence;
- a graph compiler-generated kernel is not automatically entered as a reusable operation implementation;
- cache keys include source, graph, guard, toolchain, hardware, and policy digests.

### A15.21 Telemetry and incident diagnostics

Bounded telemetry includes:

```text
operation and implementation family
shape bucket and dtype/layout class
selected capability/qualification digest
latency, workspace, and launch count
fallback and compile-cache outcome
shadow mismatch counts
asynchronous device error class
```

Raw tensor values, biological payloads, sample identities, and unbounded shape strings are not metric labels. A failure artifact may contain sanitized tensor summaries, seeds, operation signature, environment manifest, and a reproducible fixture reference under access policy.

### A15.22 Security and supply-chain requirements

Kernel sources and binaries are high-trust execution artifacts. Controls include:

- pinned compiler and backend dependencies;
- hermetic builds without undeclared network fetches;
- source and generated-binary provenance;
- license and patch review;
- isolated compilation for untrusted contributions;
- no loading arbitrary user-provided PTX, shared libraries, or tuning code;
- signature and digest verification before loading;
- bounded compiler cache permissions;
- vulnerability and revocation process;
- fuzzing of host-side shape/stride/index handling.

### A15.23 Kernel qualification levels

| Level | Required evidence |
|---|---|
| `kernel-k0` | operation spec, reference path, CPU/small-shape fixtures, API and error behavior |
| `kernel-k1` | single-GPU forward, gradient, adversarial shape, NaN/Inf, and memory-safety evidence |
| `kernel-k2` | determinism/reproducibility, compilation, CUDA-graph, and workspace evidence |
| `kernel-k3` | representative workload performance and end-to-end integration evidence |
| `kernel-k4` | multi-node/layout/provider composition where applicable, shadow qualification, and recovery compatibility |
| `kernel-k5` | long-horizon model training/inference quality, production-scale stability, provenance, and operations evidence |

The dispatch registry exposes only the highest fully passed level for each exact qualification key.

### A15.24 Capability-local qualification progression

#### Milestone 0 — contracts and registry

Implement operation signatures, capability schema, deterministic dispatch, reference-path policy, and qualification report schema.

#### Milestone 1 — first Pairformer vertical slice

Implement and qualify one triangle operation through reference, TileLang implementation, gradients, autotuning, bundle promotion, dispatch, and a CladeFold smoke workload.

#### Milestone 2 — common primitives

Add attention, normalization, outer-product mean, transition, diffusion, and quantization operations only as real model profiles require them.

#### Milestone 3 — production compilation

Add promoted binary caches, signed bundles, graph-region integration, shadow qualification, revocation, and hardware-specific lanes.

### A15.25 Definition of done

The kernel architecture is production-ready when:

1. every selected optimized implementation maps to a versioned operation contract and qualification key;
2. reference and optimized paths pass forward, gradient, adversarial, and update-level tests where applicable;
3. dispatch is deterministic, plan-bound, fail-closed, and fully evidenced;
4. workspace, stream, aliasing, and capture behavior are explicit;
5. tuning records are reproducible and separate from scientific hyperparameters;
6. performance promotion is based on representative distributions and end-to-end benefit;
7. compiled artifacts are immutable, signed, traceable, and revocable;
8. no production path silently changes precision, semantics, or implementation;
9. training and inference each possess workload-specific qualification;
10. operational telemetry can identify a kernel decision without exposing biological payloads.

### A15.26 Final kernel invariants

- operation semantics outlive implementations;
- every optimized path has a maintained oracle;
- every dispatch decision is constrained by exact qualification evidence;
- no first-use production autotuning or surprise critical-path compilation;
- kernel selection is frozen by the executable plan;
- numerical, gradient, state, recovery, long-horizon, and performance evidence are all required where relevant;
- binaries are software-supply-chain artifacts, not opaque cache entries.
