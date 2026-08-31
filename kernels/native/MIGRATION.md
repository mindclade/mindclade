<!--
Copyright (c) 2026 Mindclade. All rights reserved.
Proprietary and confidential. Unauthorized use, copying, or distribution is prohibited.
-->

# Native manifest-v3 forward and backward design

Status: PROPOSED TARGET. This document defines a reviewed design and migration
contract. It does not claim that manifest v3, native backward kernels, an
Evoformer operation, or a qualified GPU artifact exists.

## Review disposition

The proposed native-infrastructure and Evoformer text contains a valid
architectural direction, but it mixed future design with current behavior.
The following corrections are normative for this design.

| Supplied claim | Disposition |
|---|---|
| Operation-local `tilelang.py` owns optimized math and native owns integration. | Accepted. Semantic truth and readable reference behavior also remain operation-local. |
| Discovery imports no operation modules. | Accepted for discovery. Offline compilation may import only the already validated, explicitly declared builder module. |
| One declaration automatically creates a shipped operator without other edits. | Rejected. Repository-path activation, explicit Bazel input, profiles, generated outputs, locks, qualification, signing, and promotion remain mandatory. |
| CMake runs codegen and builds `libmindclade_ops.so`. | Not implemented. Current CMake consumes committed generated source and builds `mindclade_native_schema`, with optional external GPU-artifact intake. |
| `MINDCLADE_NATIVE_SCHEMA_ONLY=ON` is the current build switch. | Incorrect. It is currently a compile definition; the public switch is `MINDCLADE_NATIVE_ENABLE_GPU`. |
| The Stable ABI bridge exports an ABI function and validates tensor dtypes. | Incorrect. Both are target capabilities; the current bridge is an unavailable placeholder. |
| `KernelSpec` already contains raw forward/backward contracts. | Incorrect. Current manifest v2 has one public schema and launch symbol plus Python fake/autograd callable references. |
| Public output can hide LSE while public `setup_context` saves it. | Incomplete. `setup_context` can save only inputs and outputs it receives. The raw forward tuple must be the autograd-bearing operation, or forward state must be recomputed. |
| Backward can return required and omitted gradients under a fixed `Tensor` tuple schema. | Incomplete. Optional gradients require qualified optional Stable ABI support or unconditional tensor outputs followed by generated `None` alignment. |
| `supports_double_backward=False` is self-enforcing. | Rejected. Generated registration must explicitly prohibit second derivatives and qualification must prove the failure mode. |
| `test_opcheck.py` proves real CUDA `opcheck`. | Incorrect. Current GPU `opcheck` execution belongs to the CUDA qualification harness. |
| Handwritten CUDA math is categorically forbidden. | Narrowed. TileLang is the current optimized-math authority; an exceptional CUDA implementation requires an explicit architecture decision, ownership, dependency, and independent qualification. |

## Design goals

Manifest v3 must describe one logical operation completely enough to generate:

- the stable public schema;
- an internal raw-forward schema and launcher;
- an internal raw-backward schema and launcher when required;
- fake implementations for every dispatcher-visible operation;
- autograd registration with explicit saved state;
- Stable ABI schema and CUDA registrations;
- CMake and Bazel inventories;
- offline compiler inputs and exact symbols;
- qualification matrices and artifact identity;
- an explicit no-autograd or no-double-backward failure contract.

All generated public and internal operations remain under
`torch.ops.mindclade.{name}`. Underscore-prefixed names indicate internal API
status, not another dispatcher namespace.

## Required dispatcher model

For an operation that needs hidden forward state, the generated dispatcher
family is:

```text
mindclade::evoformer_attention
mindclade::_evoformer_attention_fwd
mindclade::_evoformer_attention_bwd
```

The call and gradient path is:

```text
public CompositeExplicitAutograd operation
        |
        v
raw forward CUDA operation -> (output, saved auxiliary tensors)
        |
        | autograd is registered on this tuple-returning operation
        v
raw backward CUDA operation -> gradients
```

The public composite invokes the raw forward and returns only its public output.
Autograd remains connected to the raw forward result, whose setup context can
therefore save LSE or other auxiliary tensors. Registering autograd only on a
single-output public operation cannot make a hidden LSE available to
`setup_context`.

This design requires loader policy to distinguish:

| Operation class | Required dispatch behavior |
|---|---|
| Public operation | Public schema, fake/meta behavior, generated composite implementation, no provider alias. |
| Raw forward | Internal schema, fake/meta behavior, exact CUDA launcher, registered autograd when differentiable. |
| Raw backward | Internal schema, fake/meta behavior, exact CUDA launcher, explicit first- or higher-order policy. |

The manifest and loader must reconcile the complete derived operator set rather
than assuming every manifest entry has exactly one CUDA implementation.

## Proposed typed contract

The existing `AutogradPolicy` dataclass should not be reused as an enum. The v3
contract uses `AutogradMode` to avoid type and migration ambiguity.

```python
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class AutogradMode(StrEnum):
    NATIVE_REQUIRED = "native_required"
    COMPOSITE = "composite"
    NONE = "none"


@dataclass(frozen=True, slots=True)
class CallableRef:
    module: str
    symbol: str


@dataclass(frozen=True, slots=True)
class SavedOutputSpec:
    name: str
    dtype: str
    semantic_axes: tuple[str, ...]
    differentiable: bool = False


@dataclass(frozen=True, slots=True)
class ForwardSpec:
    schema: str
    builder: CallableRef
    fake: CallableRef
    symbol: str
    saved_outputs: tuple[SavedOutputSpec, ...]


@dataclass(frozen=True, slots=True)
class BackwardSpec:
    schema: str
    builder: CallableRef
    fake: CallableRef
    symbol: str
    differentiable_inputs: tuple[str, ...]
    supports_double_backward: bool


@dataclass(frozen=True, slots=True)
class KernelSpec:
    name: str
    namespace: str
    family: str
    version: int
    public_schema: str
    public_fake: CallableRef
    forward: ForwardSpec
    backward: BackwardSpec | None
    autograd_mode: AutogradMode
```

`SavedOutputSpec.semantic_axes` documents and qualifies meaning; it is not
sufficient to calculate a FakeTensor shape. `ForwardSpec.fake` remains explicit
and must return the complete raw-forward tuple.

Builder references must resolve to the same canonical operation module as the
declaration. They are imported only by the offline compiler after AST discovery,
source hashing, locality validation, and explicit build-input validation.

## Contract validation

The generator must reject a spec unless all applicable rules hold.

### Common rules

- `namespace` is exactly `mindclade`.
- `family`, operation name, source directory, schema names, callable modules,
  and launch symbols agree.
- All metadata used by discovery is literal and bounded.
- Public and internal names are unique across the complete generated registry.
- Every callable reference remains in the canonical operation module.
- Every launch symbol is unique and follows the exact Mindclade symbol policy.
- Saved-output names and semantic axes are unique and nonempty.

### `NATIVE_REQUIRED`

- `backward` is present.
- `differentiable_inputs` is nonempty and names only public tensor arguments.
- Raw forward returns the public output plus all declared saved outputs.
- Raw backward consumes every value required by the derivative formula.
- Generated registration attaches autograd to the raw forward.
- Forward, backward, gradcheck, stream, compile, graph, and determinism gates
  are mandatory before promotion.
- If double backward is false, generated code explicitly blocks it.
- If double backward is true, the raw backward itself has a complete derivative
  contract and passes gradgrad qualification.

### `COMPOSITE`

- The optimized forward remains explicit.
- Backward behavior is expressed by a declared, readable PyTorch formula rather
  than inferred by the generator.
- Production use requires an operation-specific decision because composite
  backward can erase the performance benefit of the optimized forward.
- The generated manifest identifies the composite formula and its source digest.

### `NONE`

- `backward` is absent.
- No differentiable input is declared.
- Generated autograd behavior fails clearly rather than returning artificial
  zero gradients.
- Qualification includes the expected failure behavior.

## Evoformer example

The following is the target logical contract. The concrete schemas remain
subject to operation-level semantic review, Stable ABI tuple/optional support,
and qualification.

```python
EVOFORMER_ATTENTION = KernelSpec(
    name="evoformer_attention",
    namespace="mindclade",
    family="attention",
    version=1,
    public_schema=(
        "evoformer_attention("
        "Tensor q, Tensor k, Tensor v, "
        "Tensor bias1, Tensor bias2"
        ") -> Tensor"
    ),
    public_fake=CallableRef(
        module="kernels.attention.evoformer.tilelang",
        symbol="fake_evoformer_attention",
    ),
    forward=ForwardSpec(
        schema=(
            "_evoformer_attention_fwd("
            "Tensor q, Tensor k, Tensor v, "
            "Tensor bias1, Tensor bias2"
            ") -> (Tensor, Tensor)"
        ),
        builder=CallableRef(
            module="kernels.attention.evoformer.tilelang",
            symbol="build_evoformer_attention_forward",
        ),
        fake=CallableRef(
            module="kernels.attention.evoformer.tilelang",
            symbol="fake_evoformer_attention_forward",
        ),
        symbol=(
            "mindclade_tilelang_"
            "evoformer_attention_fwd_launch"
        ),
        saved_outputs=(
            SavedOutputSpec(
                name="lse",
                dtype="float32",
                semantic_axes=(
                    "flattened_batch",
                    "head",
                    "padded_query",
                ),
            ),
        ),
    ),
    backward=BackwardSpec(
        schema=(
            "_evoformer_attention_bwd("
            "Tensor grad_output, "
            "Tensor q, Tensor k, Tensor v, "
            "Tensor output, Tensor lse, "
            "Tensor bias1, Tensor bias2"
            ") -> (Tensor, Tensor, Tensor, Tensor, Tensor)"
        ),
        builder=CallableRef(
            module="kernels.attention.evoformer.tilelang",
            symbol="build_evoformer_attention_backward",
        ),
        fake=CallableRef(
            module="kernels.attention.evoformer.tilelang",
            symbol="fake_evoformer_attention_backward",
        ),
        symbol=(
            "mindclade_tilelang_"
            "evoformer_attention_bwd_launch"
        ),
        differentiable_inputs=(
            "q",
            "k",
            "v",
            "bias1",
            "bias2",
        ),
        supports_double_backward=False,
    ),
    autograd_mode=AutogradMode.NATIVE_REQUIRED,
)
```

This first version intentionally computes all five gradients. Gradient-request
flags should be added only after the schema parser and Stable ABI layer have a
qualified representation for optional gradient results or independently
qualified gradient-mask launch variants. A fixed `Tensor` return must not use
empty tensors as undocumented `None` sentinels.

## Generated autograd behavior

The conceptual generated path is:

```python
def _public_impl(q, k, v, bias1, bias2):
    output, _lse = torch.ops.mindclade._evoformer_attention_fwd(
        q, k, v, bias1, bias2
    )
    return output


def _setup_raw_forward_context(ctx, inputs, output):
    q, k, v, bias1, bias2 = inputs
    public_output, lse = output
    ctx.save_for_backward(
        q,
        k,
        v,
        public_output,
        lse,
        bias1,
        bias2,
    )


def _raw_forward_backward(ctx, grad_output, grad_lse):
    if grad_lse is not None:
        raise RuntimeError("saved LSE is not a differentiable public output")
    q, k, v, output, lse, bias1, bias2 = ctx.saved_tensors
    gradients = torch.ops.mindclade._evoformer_attention_bwd(
        grad_output,
        q,
        k,
        v,
        output,
        lse,
        bias1,
        bias2,
    )
    return gradients
```

The real generated code must use the supported PyTorch custom-operator APIs,
validate output arity, align gradients to raw-forward input order, and explicitly
enforce the double-backward contract. This pseudocode is explanatory, not a
copy-paste implementation.

## Schema and ABI revision

Manifest v3 requires a deliberate parser and ABI revision. At minimum it needs:

- tuple returns;
- internal underscore-prefixed operator names;
- output arity and return-type metadata;
- Stable ABI boxed tuple support;
- fake registration for public, raw-forward, and raw-backward operations;
- distinct dispatch requirements for composite and CUDA operations;
- optional tensor returns only if the exact Stable ABI supports and tests them;
- an ABI manifest version that distinguishes v2 and v3 bundles.

No permissive general schema parser should be introduced. Extend the current
closed subset only for constructs required by accepted operations.

## Offline build model

One logical builder may produce multiple physical TileLang programs. The
logical raw-backward symbol may orchestrate delta, dQ, dK/dV, and bias-reduction
kernels while remaining one dispatcher operation.

Build receipts must enumerate every physical artifact rather than hashing only
an aggregate path:

```text
logical operation identity
public/raw schema digests
source digest
builder identity
specialization profile
TileLang and dependency closure
target architecture and features
generated source digests
physical cubin/library digests
exported launcher symbols
resource reports
qualification-record digest
```

No builder, compilation, code generation, or specialization selection occurs
on a production request path.

## Qualification matrix

`NATIVE_REQUIRED` promotion requires evidence for:

| Area | Required evidence |
|---|---|
| Schemas | Public, raw-forward, and raw-backward dispatcher schemas and exact symbol reconciliation. |
| Fake/meta | Output and saved-output shape, dtype, device, and alias behavior for all three operations. |
| Forward | PyTorch-reference parity over representative, tail, empty-mask, extreme, and malformed cases. |
| Backward | Analytical reference parity for every differentiable input and gradient-request combination that is supported. |
| Gradcheck | First-order gradcheck with dtype-appropriate finite-difference settings. |
| Double backward | Either gradgrad qualification or a deterministic explicit rejection. |
| Compiler | Exact source, TileLang, TVM FFI, Torch, CUDA, compiler, target, and generated-source receipts. |
| Runtime | `torch.compile`, export, non-default streams, CUDA graph capture, repeated execution, and loader reconciliation. |
| Determinism | Repeated-run and concurrent-stream evidence under the declared determinism mode. |
| Safety | Bounds, tails, strides, dtype/device rejection, sanitizer, timeout, and resource-limit evidence. |
| Performance | Measured qualified hardware, reference baseline, latency distribution, memory use, and regression threshold. |
| Integration | Workload-level equivalence and executable-plan selection evidence. |

## Migration sequence

1. Ratify this design through the owning architecture source and JIT-06 decision.
2. Extend repository-path and ownership governance before adding Evoformer paths.
3. Introduce manifest v3 models without changing manifest-v2 runtime behavior.
4. Extend the narrow schema parser and Stable ABI tests for tuple returns and
   internal operation names.
5. Make codegen expand one logical spec into public, raw-forward, and
   raw-backward dispatcher records.
6. Extend generated fake, composite, autograd, CMake, Bazel, manifest, and
   loader reconciliation surfaces.
7. Implement and source-qualify one forward/backward vertical slice.
8. Compile and qualify the exact SM90 artifact with TileLang 0.1.13.
9. Tune and qualify SM100 independently rather than copying SM90 receipts.
10. Promote only a signed, non-revoked artifact selected by an immutable
    executable plan.

Until all gates complete, manifest v2 remains authoritative and production
authority remains false.

## Kernel Platform v3 Constitution and Implementation Plan

**Status:** approved target; implementation and accelerator promotion remain
evidence-gated.

This section supersedes older migration examples in this document when their
terminology or authority differs. It does not claim that unimplemented paths or
unqualified GPU capabilities are active.

## Authority model

Each logical operation has exactly one declarative authority:

```text
kernels/<family>/<operation>/spec.py
```

`spec.py` contains an import-free, immutable `KernelSpec`. `reference.py` is
the independent numerical authority. `tilelang.py` contains first-party
TileLang builders and optimized mathematics without registration side effects.
`dispatch.py` is the Python facade and owns boundary normalization plus the
explicit fallback policy. Generic discovery, generation, Stable-ABI binding,
offline compilation, loading, receipts, and ABI tests remain in
`kernels/native/`.

Discovery parses only canonical `spec.py` files through a restricted AST. It
never imports operation packages and never scans `tilelang.py`. A generated
registry is the sole inventory used by build and runtime integration.

## Three API surfaces

1. **Python facade:** ergonomic model-facing function returning only declared
   `facade_outputs`.
2. **Semantic operator:** stable `mindclade::<operation>` schema. Saved state is
   returned explicitly when autograd requires it.
3. **Provider operators:** generated internal
   `mindclade::_<operation>_fwd` and `mindclade::_<operation>_bwd` operations.

All native schemas register under `torch.ops.mindclade.*`. Operation code must
not create another namespace or a hand-maintained registry.

## Two-plane dependency law

The authoring/build/qualification plane owns contracts, the TileLang SDK,
specialization, resource planning, candidate generation, offline tuning,
hermetic compilation, immutable artifacts, and K0-K5 evidence. The runtime
plane owns facade validation, compact capability lookup, deterministic
selection, integrity checking, and precompiled Stable-ABI launch.

Runtime targets must not depend on TileLang authoring code, candidate planners,
tuners, benchmark runners, source discovery, or compiler entry points.

## Core laws

- `operator_schema` is the sole schema field; `public_schema` is retired.
- Output shape, dtype, device, visibility, saved state, gradients, effects,
  launch behavior, capability constraints, and numerical policy are typed and
  canonically serializable.
- Shape and constraint expressions use a restricted expression AST. `eval`,
  `exec`, arbitrary calls, and raw executable strings are forbidden.
- Autograd wiring is generated by argument and output names, never by builder
  position or mutable global state.
- `AutogradPolicy.REQUIRED` requires qualified forward and backward artifacts,
  promoted atomically. `NONE` cannot invent gradients. `COMPOSITE` records and
  qualifies its decomposition as a versioned dependency.
- A logical provider may launch an explicit acyclic program group with declared
  workspaces. Hidden allocation, global synchronization, or undeclared mutable
  device state is forbidden.
- The capability envelope is the single source for facade, FakeTensor, native
  host, dispatch, manifest, explanation, fuzz, and generated negative-case
  decisions.
- Compilation and tuning are trusted offline activities. Production runtime is
  limited to signed, content-addressed, prequalified artifacts.
- Fallback is caller-policy-controlled, explicit, and receipted. Critical
  training defaults to error.
- Promotion records are immutable. Supersession, revocation, and rollback are
  explicit records.
- CPU/schema CI cannot satisfy GPU hardware or release qualification.

## Contract partitions

`KernelSpec` defines semantic integration only: operation name/version,
operator schema, facade outputs, forward/backward contracts, explicit output
and gradient mappings, effects, launch contract, backend, and devices.

Scheduling and release identity remain separate immutable records:

```text
KernelSpec
ImplementationSpec
WorkloadSpec
ScheduleSpec
SpecializationSpec
CapabilityEnvelope
NumericalEnvelope
CompileEnvironment
RuntimeCompatibility
QualifiedCapability
```

For a `REQUIRED` operation, `QualifiedCapability.backward_artifact_digest` is
mandatory. Runtime tables contain only qualified capability metadata and do
not contain builders, candidate generators, or tuner objects.

## Evidence model

Qualification is a content-addressed DAG rooted at an immutable
`ReleaseReceipt`:

```text
SemanticReceipt
IntegrationReceipt
CompilerReceipt
SpecializationReceipt
NumericalReceipt
PerformanceReceipt
ModelQualificationReceipt
ReleaseReceipt
```

The gates are K0 contract, K1 semantic, K2 integration, K3 numerical, K4 real
hardware/performance, and K5 release. Evidence reuse requires exact matching
semantic, source, toolchain, artifact, numerical-policy, and compatibility
digests as appropriate. Filenames, labels, or timestamps are not identities.

## Implementation waves

1. Freeze this constitution, terminology, dependency laws, governance scope,
   fallback law, and evidence model.
2. Implement the typed expression AST and core contracts under `kernels/api/`.
3. Migrate declarations to canonical `spec.py` and restricted import-free AST
   discovery.
4. Generate semantic/provider schemas, Stable-ABI bindings, FakeTensor rules,
   and named autograd wiring.
5. Implement program groups, workspaces, effects enforcement, capability
   validators, and generated negative tests.
6. Implement hermetic co-compilation, complete input-closure identities, and
   generated Bazel/CMake inventories.
7. Implement artifacts, CAS interfaces, SBOM/provenance/signature hooks, and
   the evidence DAG with promotion, revocation, and rollback.
8. Implement environment identity, resource planning, candidates, presets,
   offline tuning, benchmark protocols, and immutable tuning records.
9. Implement foundational `kernels/dsl/` primitives and real GEMM,
   normalization, and online-softmax proving kernels.
10. Complete outer-product mean forward/backward as the first differentiable
    vertical slice.
11. Complete MLA prefill/decode forward/backward.
12. Complete Evoformer attention forward/backward and the pinned DeepSpeed
    differential qualification lane.
13. Generate the compact runtime registry, deterministic dispatch, receipts,
    explanation, and `kernelctl`.
14. Wire K0-K5 CI and clean-checkout release lanes.
15. Expand through MoE, remaining Pairformer, general/Flash/sparse attention,
    quantized, persistent, diffusion, and biological-geometry families without
    creating family-local authorities.

Every wave remains `UNVERIFIED` until its tests and required evidence are
recorded. Hardware profiles remain unpromoted when the exact accelerator and
software envelope is unavailable.
