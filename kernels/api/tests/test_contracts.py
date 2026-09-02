from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from kernels.api.backward import (
    BackwardArgumentBinding,
    BackwardArgumentSource,
    BackwardSpec,
    MissingGradientPolicy,
)
from kernels.api.capability import (
    CapabilityDecision,
    CapabilityEnvelope,
    CapabilityRequest,
    CapabilityViolation,
    DimensionConstraint,
    TensorCapabilityConstraint,
)
from kernels.api.effects import EffectSpec
from kernels.api.environment import CompileEnvironment, RuntimeCompatibility
from kernels.api.errors import KernelContractError, SchemaError
from kernels.api.expressions import (
    BoolLiteral,
    ConstantDType,
    ConstantDevice,
    DimRef,
    Eq,
    EvaluationContext,
    IntLiteral,
    Modulo,
    ScalarRef,
    ScalarType,
    ShapeTuple,
    TensorMetadata,
)
from kernels.api.forward import ForwardSpec
from kernels.api.gradient import GradientSpec
from kernels.api.kernel import AutogradPolicy, CompositeAutogradSpec, KernelSpec
from kernels.api.launch import DeterminismClass, LaunchContract
from kernels.api.numerics import NumericalEnvelope, TensorTolerance
from kernels.api.output import InitializationSpec, OutputSpec
from kernels.api.program_group import (
    ProgramArtifactBoundary,
    ProgramBindingSource,
    ProgramBindingSpec,
    ProgramEntryABI,
    ProgramGroupSpec,
    ProgramNodeSpec,
    ProgramParameterKind,
    ProgramParameterSpec,
    ProgramReturnABI,
    ProgramSelectorBinding,
    ScalarABIType,
    WorkspaceAccess,
    WorkspaceLifetime,
    WorkspaceSpec,
)
from kernels.api.qualification import QualifiedCapability
from kernels.api.schedule import ScheduleSpec, SpecializationSpec
from kernels.api.workload import (
    RuntimeWorkloadSpec,
    WorkloadAttributeBinding,
    WorkloadDimensionBinding,
    WorkloadSpec,
)

_SHA = "sha256:" + "a" * 64


def required_bindings() -> tuple[BackwardArgumentBinding, ...]:
    return (
        BackwardArgumentBinding(
            "x", BackwardArgumentSource.OPERATOR_ARGUMENT, "x"
        ),
        BackwardArgumentBinding(
            "grad_result", BackwardArgumentSource.OUTPUT_GRADIENT, "result"
        ),
    )


def output(name: str = "result", *, visible: bool = True, saved: bool = False) -> OutputSpec:
    return OutputSpec(
        name=name,
        shape=ShapeTuple((DimRef("x", 0), DimRef("x", 1))),
        dtype=ConstantDType("float32"),
        device=ConstantDevice("cuda"),
        semantic_axes=("batch", "channel"),
        visible_in_facade=visible,
        saved_for_backward=saved,
        initialization=InitializationSpec("zero") if saved else None,
    )


def gradient(
    input_name: str = "x",
    output_name: str = "grad_x",
    *,
    metadata_source: str = "x",
    optional: bool = False,
) -> GradientSpec:
    return GradientSpec(
        input_name,
        output_name,
        ShapeTuple((DimRef(metadata_source, 0), DimRef(metadata_source, 1))),
        ConstantDType("float32"),
        ConstantDevice("cuda"),
        optional=optional,
    )


def program_node(
    name: str,
    *,
    depends_on: tuple[str, ...] = (),
    workspace_accesses: tuple[tuple[str, WorkspaceAccess], ...] = (),
    symbol: str | None = None,
) -> ProgramNodeSpec:
    parameters = []
    bindings = []
    for position, (workspace, access) in enumerate(workspace_accesses):
        parameter = f"workspace_{workspace}"
        parameters.append(
            ProgramParameterSpec(
                position,
                parameter,
                ProgramParameterKind.TENSOR,
                access,
                ShapeTuple((DimRef("x", 0),)),
                ConstantDType("float32"),
                ConstantDevice("cuda"),
            )
        )
        bindings.append(
            ProgramBindingSpec(
                parameter, ProgramBindingSource.WORKSPACE, workspace
            )
        )
    parameters.append(
        ProgramParameterSpec(
            len(parameters),
            "stream",
            ProgramParameterKind.STREAM,
            WorkspaceAccess.READ,
        )
    )
    bindings.append(
        ProgramBindingSpec("stream", ProgramBindingSource.CURRENT_STREAM)
    )
    return ProgramNodeSpec(
        name=name,
        builder=f"pkg:{name}",
        symbol=symbol or f"mindclade_{name}_adapter",
        entry_symbol="call",
        entry_abi=ProgramEntryABI.TILELANG_0_1_13_HOST_CALL,
        parameters=tuple(parameters),
        bindings=tuple(bindings),
        depends_on=depends_on,
    )


def test_negative_infinity_initialization_is_canonical_without_numeric_payload() -> None:
    initialization = InitializationSpec("negative_infinity")
    assert initialization.to_canonical() == {
        "type": "InitializationSpec",
        "mode": "negative_infinity",
        "value": None,
        "version": 1,
    }
    assert initialization.digest == InitializationSpec("negative_infinity").digest
    with pytest.raises(KernelContractError, match="cannot carry a value"):
        InitializationSpec("negative_infinity", -1.0)


def test_contract_schema_canonicalization_is_not_limited_by_expression_tokens() -> None:
    schema = "_long_provider(" + ", ".join(
        f"Tensor input_{index}" for index in range(32)
    ) + ") -> Tensor output"
    forward = ForwardSpec(
        schema=schema,
        builder="kernels.family.operation.tilelang:build_forward",
        symbol="mindclade_tilelang_long_provider_fwd_launch",
        outputs=(output(),),
    )
    assert len(schema) > 256
    assert forward.digest.startswith("sha256:")


def envelope(*, training: bool = True, capture: bool = True) -> CapabilityEnvelope:
    return CapabilityEnvelope(
        architectures=("sm90",),
        dtypes=("float32",),
        layouts=("contiguous",),
        modes=("default",),
        constraints=(DimensionConstraint(BoolLiteral(True), "VALID_SHAPE", "shape is supported"),),
        graph_capture_safe=capture,
        training_capable=training,
    )


def required_kernel(**changes: object) -> KernelSpec:
    result = output()
    forward = ForwardSpec(
        schema="_example_fwd(Tensor x) -> Tensor result",
        builder="kernels.demo.example.tilelang:build_forward",
        symbol="mindclade_tilelang_example_fwd_launch",
        outputs=(result,),
    )
    backward = BackwardSpec(
        schema="_example_bwd(Tensor grad_result, Tensor x) -> Tensor grad_x",
        builder="kernels.demo.example.tilelang:build_backward",
        symbol="mindclade_tilelang_example_bwd_launch",
        argument_bindings=required_bindings(),
        gradients=(gradient(),),
        supports_double_backward=False,
    )
    values: dict[str, object] = {
        "name": "example",
        "namespace": "mindclade",
        "family": "demo",
        "source": "demo/example/spec.py",
        "operator_schema": "example(Tensor x) -> Tensor result",
        "facade_outputs": ("result",),
        "fake": None,
        "forward": forward,
        "backward": backward,
        "autograd_policy": AutogradPolicy.REQUIRED,
        "effects": EffectSpec(),
        "launch": LaunchContract(),
        "runtime_workload": RuntimeWorkloadSpec(
            dimensions=(WorkloadDimensionBinding("batch_size", DimRef("x", 0)),),
            input_dtype=ConstantDType("float32"),
            layout="contiguous",
        ),
    }
    values.update(changes)
    return KernelSpec(**values)  # type: ignore[arg-type]


def test_runtime_workload_is_canonical_and_typed() -> None:
    workload = RuntimeWorkloadSpec(
        dimensions=(
            WorkloadDimensionBinding("width", DimRef("x", 1)),
            WorkloadDimensionBinding("batch_size", DimRef("x", 0)),
        ),
        input_dtype=ConstantDType("float32"),
        layout="contiguous",
        attributes=(WorkloadAttributeBinding("training", BoolLiteral(True)),),
    )
    assert tuple(value.name for value in workload.dimensions) == ("batch_size", "width")
    assert tuple(value.name for value in workload.attributes) == ("training",)
    assert workload.digest == RuntimeWorkloadSpec(
        dimensions=tuple(reversed(workload.dimensions)),
        input_dtype=ConstantDType("float32"),
        layout="contiguous",
        attributes=workload.attributes,
    ).digest
    with pytest.raises(KernelContractError, match="typed integer expression"):
        WorkloadDimensionBinding("bad", BoolLiteral(True))  # type: ignore[arg-type]
    with pytest.raises(KernelContractError, match="input_dtype"):
        RuntimeWorkloadSpec(
            dimensions=(WorkloadDimensionBinding("batch_size", DimRef("x", 0)),),
            input_dtype=IntLiteral(1),  # type: ignore[arg-type]
            layout="contiguous",
        )


def test_runtime_workload_references_semantic_arguments_and_selector() -> None:
    with pytest.raises(KernelContractError, match="unknown semantic arguments"):
        required_kernel(
            runtime_workload=RuntimeWorkloadSpec(
                dimensions=(WorkloadDimensionBinding("batch_size", DimRef("missing", 0)),),
                input_dtype=ConstantDType("float32"),
                layout="contiguous",
            )
        )


def test_contracts_are_immutable_and_digestible() -> None:
    spec = required_kernel()
    assert spec.digest.startswith("sha256:")
    assert spec.digest == required_kernel().digest
    with pytest.raises(FrozenInstanceError):
        spec.name = "changed"  # type: ignore[misc]


def test_required_policy_requires_named_backward() -> None:
    with pytest.raises(KernelContractError, match="requires a backward"):
        required_kernel(backward=None)


def test_none_policy_forbids_backward() -> None:
    with pytest.raises(KernelContractError, match="NONE cannot declare"):
        required_kernel(autograd_policy=AutogradPolicy.NONE)


def test_composite_policy_requires_content_addressed_decomposition() -> None:
    with pytest.raises(KernelContractError, match="requires a qualified decomposition"):
        required_kernel(backward=None, autograd_policy=AutogradPolicy.COMPOSITE)
    spec = required_kernel(
        backward=None,
        autograd_policy=AutogradPolicy.COMPOSITE,
        composite=CompositeAutogradSpec(
            "pkg:backward",
            _SHA,
            "pytorch-2.10",
            (gradient(),),
            False,
            setup_context="pkg:setup_context",
            backward="pkg:backward",
        ),
    )
    assert spec.composite is not None


def test_schema_and_output_metadata_must_agree() -> None:
    bad_forward = ForwardSpec(
        schema="_example_fwd(Tensor x) -> Tensor wrong",
        builder="pkg:builder",
        symbol="mindclade_tilelang_example_fwd_launch",
        outputs=(output(),),
    )
    with pytest.raises(SchemaError, match="do not match"):
        required_kernel(forward=bad_forward)


def test_facade_outputs_exactly_match_visibility() -> None:
    with pytest.raises(KernelContractError, match="exactly match"):
        required_kernel(facade_outputs=())


def test_named_gradient_must_reference_semantic_input_and_backward_output() -> None:
    bad = BackwardSpec(
        schema="_example_bwd(Tensor grad_result, Tensor x) -> Tensor grad_x",
        builder="pkg:builder",
        symbol="mindclade_tilelang_example_bwd_launch",
        argument_bindings=required_bindings(),
        gradients=(gradient("weight", "grad_x"),),
        supports_double_backward=False,
    )
    with pytest.raises(KernelContractError, match="not a semantic operator argument"):
        required_kernel(backward=bad)


def test_saved_output_must_be_explicit_backward_argument() -> None:
    result = output()
    lse = output("lse", visible=False, saved=True)
    forward = ForwardSpec(
        schema="_example_fwd(Tensor x) -> (Tensor result, Tensor lse)",
        builder="pkg:forward",
        symbol="mindclade_tilelang_example_fwd_launch",
        outputs=(result, lse),
    )
    with pytest.raises(KernelContractError, match="saved forward outputs"):
        required_kernel(
            operator_schema="example(Tensor x) -> (Tensor result, Tensor lse)",
            forward=forward,
        )


def test_double_backward_claim_fails_without_second_order_contract() -> None:
    backward = BackwardSpec(
        schema="_example_bwd(Tensor grad_result, Tensor x) -> Tensor grad_x",
        builder="pkg:backward",
        symbol="mindclade_tilelang_example_bwd_launch",
        argument_bindings=required_bindings(),
        gradients=(gradient(),),
        supports_double_backward=True,
    )
    with pytest.raises(KernelContractError, match="second-order provider"):
        required_kernel(backward=backward)


def test_backward_bindings_are_canonical_and_cover_provider_arguments() -> None:
    spec = required_kernel()
    assert tuple(
        binding.provider_argument for binding in spec.backward.argument_bindings
    ) == ("grad_result", "x")
    incomplete = BackwardSpec(
        schema="_example_bwd(Tensor grad_result, Tensor x) -> Tensor grad_x",
        builder="pkg:backward",
        symbol="example_bwd_launch",
        argument_bindings=(required_bindings()[0],),
        gradients=(gradient(),),
        supports_double_backward=False,
    )
    with pytest.raises(KernelContractError, match="exactly cover"):
        required_kernel(backward=incomplete)


def test_semantic_and_forward_parameter_kinds_must_match() -> None:
    forward = ForwardSpec(
        schema="_example_fwd(float x) -> Tensor result",
        builder="pkg:forward",
        symbol="example_fwd_launch",
        outputs=(output(),),
    )
    with pytest.raises(SchemaError, match="names and kinds"):
        required_kernel(forward=forward)


def test_semantic_and_forward_output_kinds_must_match() -> None:
    forward = ForwardSpec(
        schema="_example_fwd(Tensor x) -> float result",
        builder="pkg:forward",
        symbol="example_fwd_launch",
        outputs=(output(),),
    )
    with pytest.raises(SchemaError, match="output names and kinds"):
        required_kernel(forward=forward)


def test_backward_binding_sources_and_kinds_are_validated_by_name() -> None:
    bad_source = BackwardSpec(
        schema="_example_bwd(Tensor grad_result, Tensor x) -> Tensor grad_x",
        builder="pkg:backward",
        symbol="example_bwd_launch",
        argument_bindings=(
            BackwardArgumentBinding(
                "grad_result", BackwardArgumentSource.OUTPUT_GRADIENT, "missing"
            ),
            required_bindings()[0],
        ),
        gradients=(gradient(),),
        supports_double_backward=False,
    )
    with pytest.raises(KernelContractError, match="not a forward output"):
        required_kernel(backward=bad_source)

    bad_kind = BackwardSpec(
        schema="_example_bwd(Tensor grad_result, float x) -> Tensor grad_x",
        builder="pkg:backward",
        symbol="example_bwd_launch",
        argument_bindings=required_bindings(),
        gradients=(gradient(),),
        supports_double_backward=False,
    )
    with pytest.raises(SchemaError, match="does not match semantic kind"):
        required_kernel(backward=bad_kind)


def test_saved_forward_outputs_require_named_consumption() -> None:
    result = output()
    lse = output("lse", visible=False, saved=True)
    forward = ForwardSpec(
        schema="_example_fwd(Tensor x) -> (Tensor result, Tensor lse)",
        builder="pkg:forward",
        symbol="example_fwd_launch",
        outputs=(result, lse),
    )
    backward = BackwardSpec(
        schema=(
            "_example_bwd(Tensor grad_result, Tensor x, Tensor lse) "
            "-> Tensor grad_x"
        ),
        builder="pkg:backward",
        symbol="example_bwd_launch",
        argument_bindings=(
            *required_bindings(),
            BackwardArgumentBinding(
                "lse", BackwardArgumentSource.FORWARD_OUTPUT, "lse"
            ),
        ),
        gradients=(gradient(),),
        supports_double_backward=False,
    )
    spec = required_kernel(
        operator_schema="example(Tensor x) -> (Tensor result, Tensor lse)",
        facade_outputs=("result",),
        forward=forward,
        backward=backward,
    )
    assert spec.backward is backward

    unsaved = output("lse", visible=False, saved=False)
    with pytest.raises(KernelContractError, match="not saved for backward"):
        required_kernel(
            operator_schema="example(Tensor x) -> (Tensor result, Tensor lse)",
            facade_outputs=("result",),
            forward=ForwardSpec(
                schema="_example_fwd(Tensor x) -> (Tensor result, Tensor lse)",
                builder="pkg:forward",
                symbol="example_fwd_launch",
                outputs=(result, unsaved),
            ),
            backward=backward,
        )


def test_needs_input_grad_requires_named_tensor_gradient_and_bool_provider() -> None:
    backward = BackwardSpec(
        schema=(
            "_example_bwd(Tensor grad_result, Tensor x, bool need_x_grad) "
            "-> Tensor grad_x"
        ),
        builder="pkg:backward",
        symbol="example_bwd_launch",
        argument_bindings=(
            *required_bindings(),
            BackwardArgumentBinding(
                "need_x_grad", BackwardArgumentSource.NEEDS_INPUT_GRAD, "x"
            ),
        ),
        gradients=(gradient(),),
        supports_double_backward=False,
    )
    assert required_kernel(backward=backward).backward is backward

    bad = BackwardSpec(
        schema=(
            "_example_bwd(Tensor grad_result, Tensor x, bool need_y_grad) "
            "-> Tensor grad_x"
        ),
        builder="pkg:backward",
        symbol="example_bwd_launch",
        argument_bindings=(
            *required_bindings(),
            BackwardArgumentBinding(
                "need_y_grad", BackwardArgumentSource.NEEDS_INPUT_GRAD, "y"
            ),
        ),
        gradients=(gradient(),),
        supports_double_backward=False,
    )
    with pytest.raises(KernelContractError, match="not a declared gradient input"):
        required_kernel(backward=bad)


def test_gradient_mappings_exactly_cover_named_backward_outputs() -> None:
    backward = BackwardSpec(
        schema=(
            "_example_bwd(Tensor grad_result, Tensor x) "
            "-> (Tensor grad_x, Tensor scratch)"
        ),
        builder="pkg:backward",
        symbol="example_bwd_launch",
        argument_bindings=required_bindings(),
        gradients=(gradient(),),
        supports_double_backward=False,
    )
    with pytest.raises(KernelContractError, match="exactly cover backward outputs"):
        required_kernel(backward=backward)


def test_pass_none_requires_an_optional_provider_parameter() -> None:
    binding = BackwardArgumentBinding(
        "grad_result",
        BackwardArgumentSource.OUTPUT_GRADIENT,
        "result",
        MissingGradientPolicy.PASS_NONE,
    )
    backward = BackwardSpec(
        schema="_example_bwd(Tensor grad_result, Tensor x) -> Tensor grad_x",
        builder="pkg:backward",
        symbol="example_bwd_launch",
        argument_bindings=(binding, required_bindings()[0]),
        gradients=(gradient(),),
        supports_double_backward=False,
    )
    with pytest.raises(SchemaError, match="requires an optional provider kind"):
        required_kernel(backward=backward)

    optional = BackwardSpec(
        schema="_example_bwd(Tensor? grad_result, Tensor x) -> Tensor grad_x",
        builder="pkg:backward",
        symbol="example_bwd_launch",
        argument_bindings=(binding, required_bindings()[0]),
        gradients=(gradient(),),
        supports_double_backward=False,
    )
    assert required_kernel(backward=optional).backward is optional


def test_zero_missing_gradient_requires_and_consumes_saved_forward_output() -> None:
    zero_binding = BackwardArgumentBinding(
        "grad_result",
        BackwardArgumentSource.OUTPUT_GRADIENT,
        "result",
        MissingGradientPolicy.ZERO,
    )
    backward = BackwardSpec(
        schema="_example_bwd(Tensor grad_result, Tensor x) -> Tensor grad_x",
        builder="pkg:backward",
        symbol="example_bwd_launch",
        argument_bindings=(zero_binding, required_bindings()[0]),
        gradients=(gradient(),),
        supports_double_backward=False,
    )
    with pytest.raises(KernelContractError, match="ZERO.*saved for backward"):
        required_kernel(backward=backward)

    saved_result = output(saved=True)
    forward = ForwardSpec(
        schema="_example_fwd(Tensor x) -> Tensor result",
        builder="pkg:forward",
        symbol="example_fwd_launch",
        outputs=(saved_result,),
    )
    with pytest.raises(KernelContractError, match="hidden_device_allocation=True"):
        required_kernel(forward=forward, backward=backward)
    allocation_launch = LaunchContract(
        hidden_device_allocation=True,
        graph_capture_safe=False,
    )
    zero_workspace = WorkspaceSpec(
        "zero_grad",
        ShapeTuple((DimRef("x", 0), DimRef("x", 1))),
        ConstantDType("float32"),
    )
    zero_group = ProgramGroupSpec(
        nodes=(
            program_node(
                "zero_grad",
                workspace_accesses=(("zero_grad", WorkspaceAccess.WRITE),),
            ),
        ),
        workspaces=(zero_workspace,),
    )
    allocated_forward = ForwardSpec(
        schema="_example_fwd(Tensor x) -> Tensor result",
        builder="pkg:forward",
        symbol="example_fwd_launch",
        outputs=(saved_result,),
        program_group=zero_group,
    )
    assert required_kernel(
        forward=allocated_forward,
        backward=backward,
        launch=allocation_launch,
    ).backward is backward


def test_duplicate_output_gradient_bindings_reject_conflicting_missing_policies() -> None:
    backward = BackwardSpec(
        schema=(
            "_example_bwd(Tensor grad_primary, Tensor grad_secondary, Tensor x) "
            "-> Tensor grad_x"
        ),
        builder="pkg:backward",
        symbol="example_bwd_launch",
        argument_bindings=(
            BackwardArgumentBinding(
                "grad_primary",
                BackwardArgumentSource.OUTPUT_GRADIENT,
                "result",
                MissingGradientPolicy.ERROR,
            ),
            BackwardArgumentBinding(
                "grad_secondary",
                BackwardArgumentSource.OUTPUT_GRADIENT,
                "result",
                MissingGradientPolicy.ZERO,
            ),
            required_bindings()[0],
        ),
        gradients=(gradient(),),
        supports_double_backward=False,
    )
    with pytest.raises(KernelContractError, match="conflicting missing-gradient policies"):
        required_kernel(backward=backward)


def test_gradient_formula_need_not_consume_original_input_value() -> None:
    metadata = GradientSpec(
        "x",
        "grad_x",
        ShapeTuple((IntLiteral(1),)),
        ConstantDType("float32"),
        ConstantDevice("cuda"),
    )
    backward = BackwardSpec(
        schema="_example_bwd(Tensor grad_result) -> Tensor grad_x",
        builder="pkg:backward",
        symbol="example_bwd_launch",
        argument_bindings=(
            BackwardArgumentBinding(
                "grad_result", BackwardArgumentSource.OUTPUT_GRADIENT, "result"
            ),
        ),
        gradients=(metadata,),
        supports_double_backward=False,
    )
    assert required_kernel(backward=backward).backward is backward


def test_gradient_metadata_references_are_typed_and_named() -> None:
    assert required_kernel().backward.gradients[0].shape.domain.value == "shape"
    unknown = gradient(metadata_source="missing")
    with pytest.raises(KernelContractError, match="unknown semantic arguments"):
        required_kernel(
            backward=BackwardSpec(
                schema="_example_bwd(Tensor grad_result, Tensor x) -> Tensor grad_x",
                builder="pkg:backward",
                symbol="example_bwd_launch",
                argument_bindings=required_bindings(),
                gradients=(unknown,),
                supports_double_backward=False,
            )
        )
    scalar_as_tensor = GradientSpec(
        "x",
        "grad_x",
        ShapeTuple((ScalarRef("x", ScalarType.INT),)),
        ConstantDType("float32"),
        ConstantDevice("cuda"),
    )
    with pytest.raises(KernelContractError, match="reference kinds do not match"):
        required_kernel(
            backward=BackwardSpec(
                schema="_example_bwd(Tensor grad_result, Tensor x) -> Tensor grad_x",
                builder="pkg:backward",
                symbol="example_bwd_launch",
                argument_bindings=required_bindings(),
                gradients=(scalar_as_tensor,),
                supports_double_backward=False,
            )
        )


def test_program_selector_binding_is_total_canonical_and_group_scoped() -> None:
    selector = ProgramSelectorBinding(
        "outgoing",
        "mode",
        ScalarABIType.BOOL,
        ((False, "incoming"), (True, "outgoing")),
    )
    group = ProgramGroupSpec((program_node("node"),), selector_bindings=(selector,))
    assert group.selector_bindings == (selector,)
    assert group.to_canonical()["selector_bindings"][0]["cases"] == [
        [False, "incoming"],
        [True, "outgoing"],
    ]
    with pytest.raises(KernelContractError, match="canonical and total"):
        ProgramSelectorBinding(
            "outgoing",
            "mode",
            ScalarABIType.BOOL,
            ((True, "outgoing"), (False, "incoming")),
        )


def test_optional_gradient_requires_exactly_one_needs_input_grad_binding() -> None:
    missing_request = BackwardSpec(
        schema="_example_bwd(Tensor grad_result, Tensor x) -> Tensor? grad_x",
        builder="pkg:backward",
        symbol="example_bwd_launch",
        argument_bindings=required_bindings(),
        gradients=(gradient(optional=True),),
        supports_double_backward=False,
    )
    with pytest.raises(KernelContractError, match="exactly one NEEDS_INPUT_GRAD"):
        required_kernel(backward=missing_request)

    represented = BackwardSpec(
        schema=(
            "_example_bwd(Tensor grad_result, Tensor x, bool need_x_grad) "
            "-> Tensor? grad_x"
        ),
        builder="pkg:backward",
        symbol="example_bwd_launch",
        argument_bindings=(
            *required_bindings(),
            BackwardArgumentBinding(
                "need_x_grad", BackwardArgumentSource.NEEDS_INPUT_GRAD, "x"
            ),
        ),
        gradients=(gradient(optional=True),),
        supports_double_backward=False,
    )
    assert required_kernel(backward=represented).backward is represented


def test_optional_tensor_operator_argument_binding_requires_schema_v2() -> None:
    forward = ForwardSpec(
        schema="_example_fwd(Tensor? x) -> Tensor result",
        builder="pkg:forward",
        symbol="example_fwd_launch",
        outputs=(output(),),
    )
    backward = BackwardSpec(
        schema="_example_bwd(Tensor grad_result, Tensor? x) -> Tensor grad_x",
        builder="pkg:backward",
        symbol="example_bwd_launch",
        argument_bindings=required_bindings(),
        gradients=(gradient(),),
        supports_double_backward=False,
    )
    with pytest.raises(SchemaError, match="require schema version 2"):
        required_kernel(
            operator_schema="example(Tensor? x) -> Tensor result",
            forward=forward,
            backward=backward,
        )


def test_launch_and_effect_contracts_fail_on_false_safety_claims() -> None:
    with pytest.raises(KernelContractError, match="cannot globally synchronize"):
        LaunchContract(global_synchronization=True)
    with pytest.raises(KernelContractError, match="atomic kernel"):
        required_kernel(effects=EffectSpec(uses_atomics=True))
    assert not required_kernel(
        launch=LaunchContract(graph_capture_safe=False)
    ).launch.graph_capture_safe
    nondeterministic = required_kernel(
        effects=EffectSpec(uses_atomics=True),
        launch=LaunchContract(determinism=DeterminismClass.CONDITIONALLY_DETERMINISTIC),
    )
    assert nondeterministic.effects.uses_atomics


def test_program_group_has_deterministic_topology_and_rejects_cycles() -> None:
    workspace = WorkspaceSpec(
        "delta", ShapeTuple((DimRef("x", 0),)), ConstantDType("float32")
    )
    group = ProgramGroupSpec(
        nodes=(
            program_node(
                "dq",
                depends_on=("delta",),
                workspace_accesses=(("delta", WorkspaceAccess.READ),),
            ),
            program_node(
                "delta", workspace_accesses=(("delta", WorkspaceAccess.WRITE),)
            ),
            program_node(
                "dkv",
                depends_on=("delta",),
                workspace_accesses=(("delta", WorkspaceAccess.READ),),
            ),
        ),
        workspaces=(workspace,),
    )
    assert group.topological_order() == ("delta", "dkv", "dq")
    with pytest.raises(KernelContractError, match="acyclic"):
        ProgramGroupSpec(
            nodes=(
                program_node("a", depends_on=("b",)),
                program_node("b", depends_on=("a",)),
            )
        )


def test_program_group_canonicalizes_dag_and_workspace_identity() -> None:
    first = WorkspaceSpec(
        "first", ShapeTuple((DimRef("x", 0),)), ConstantDType("float32")
    )
    second = WorkspaceSpec(
        "second", ShapeTuple((DimRef("x", 1),)), ConstantDType("float32")
    )
    producer = program_node(
        "producer",
        workspace_accesses=(
            ("second", WorkspaceAccess.WRITE),
            ("first", WorkspaceAccess.WRITE),
        ),
    )
    consumer = program_node(
        "consumer",
        depends_on=("producer",),
        workspace_accesses=(
            ("second", WorkspaceAccess.READ),
            ("first", WorkspaceAccess.READ),
        ),
    )
    left = ProgramGroupSpec((consumer, producer), (second, first))
    right = ProgramGroupSpec((producer, consumer), (first, second))
    assert left.nodes == right.nodes == (producer, consumer)
    assert tuple(item.name for item in left.workspaces) == ("first", "second")
    assert left.digest == right.digest


def test_program_group_rejects_invalid_workspace_dataflow() -> None:
    workspace = WorkspaceSpec(
        "scratch", ShapeTuple((DimRef("x", 0),)), ConstantDType("float32")
    )
    with pytest.raises(KernelContractError, match="undeclared workspace"):
        ProgramGroupSpec(
            nodes=(program_node(
                "node", workspace_accesses=(("missing", WorkspaceAccess.WRITE),)
            ),),
        )
    with pytest.raises(KernelContractError, match="multiple writers"):
        ProgramGroupSpec(
            nodes=(
                program_node("a", workspace_accesses=(("scratch", WorkspaceAccess.WRITE),)),
                program_node("b", workspace_accesses=(("scratch", WorkspaceAccess.WRITE),)),
            ),
            workspaces=(workspace,),
        )
    with pytest.raises(KernelContractError, match="transitively depend"):
        ProgramGroupSpec(
            nodes=(
                program_node(
                    "producer", workspace_accesses=(("scratch", WorkspaceAccess.WRITE),)
                ),
                program_node(
                    "reader", workspace_accesses=(("scratch", WorkspaceAccess.READ),)
                ),
            ),
            workspaces=(workspace,),
        )


def test_workspace_lifetime_writer_and_domain_laws() -> None:
    with pytest.raises(KernelContractError, match="shape expression"):
        WorkspaceSpec("bad", ConstantDType("float32"), ConstantDType("float32"))
    with pytest.raises(KernelContractError, match="dtype expression"):
        WorkspaceSpec(
            "bad", ShapeTuple((DimRef("x", 0),)), DimRef("x", 0)  # type: ignore[arg-type]
        )
    with pytest.raises(KernelContractError, match="zero_initialize must be bool"):
        WorkspaceSpec(
            "bad", ShapeTuple((DimRef("x", 0),)), ConstantDType("float32"),
            zero_initialize=1,  # type: ignore[arg-type]
        )
    local = WorkspaceSpec(
        "local", ShapeTuple((DimRef("x", 0),)), ConstantDType("float32"),
        zero_initialize=True, lifetime=WorkspaceLifetime.NODE,
    )
    with pytest.raises(KernelContractError, match="exactly one user"):
        ProgramGroupSpec(
            nodes=(
                program_node("a", workspace_accesses=(("local", WorkspaceAccess.READ),)),
                program_node(
                    "b", depends_on=("a",),
                    workspace_accesses=(("local", WorkspaceAccess.READ),),
                ),
            ),
            workspaces=(local,),
        )


def test_callable_node_abi_is_typed_positional_and_artifact_scoped() -> None:
    tensor = ProgramParameterSpec(
        0, "output", ProgramParameterKind.TENSOR, WorkspaceAccess.WRITE,
        ShapeTuple((DimRef("x", 0),)), ConstantDType("float32"),
        ConstantDevice("cuda"),
    )
    stream = ProgramParameterSpec(
        1, "stream", ProgramParameterKind.STREAM, WorkspaceAccess.READ,
    )
    node_a = ProgramNodeSpec(
        "a", "pkg:a", "mindclade_a_adapter", "call",
        ProgramEntryABI.TILELANG_0_1_13_HOST_CALL,
        (stream, tensor),
        (
            ProgramBindingSpec("stream", ProgramBindingSource.CURRENT_STREAM),
            ProgramBindingSpec("output", ProgramBindingSource.PROVIDER_OUTPUT, "result"),
        ),
    )
    node_b = program_node("b")
    assert tuple(parameter.position for parameter in node_a.parameters) == (0, 1)
    assert node_a.entry_symbol == node_b.entry_symbol == "call"
    assert node_a.return_abi is ProgramReturnABI.STATUS_I32_ZERO_SUCCESS
    assert node_a.artifact_boundary is ProgramArtifactBoundary.NODE_CONTENT_ADDRESSED_DSO
    ProgramGroupSpec((node_a, node_b))

    with pytest.raises(KernelContractError, match="contiguous from zero"):
        ProgramNodeSpec(
            "bad", "pkg:bad", "mindclade_bad_adapter", "call",
            ProgramEntryABI.TILELANG_0_1_13_HOST_CALL,
            (ProgramParameterSpec(
                1, "stream", ProgramParameterKind.STREAM, WorkspaceAccess.READ,
            ),),
            (ProgramBindingSpec("stream", ProgramBindingSource.CURRENT_STREAM),),
        )
    with pytest.raises(KernelContractError, match="exactly one CURRENT_STREAM"):
        ProgramNodeSpec(
            "bad", "pkg:bad", "mindclade_bad_adapter", "call",
            ProgramEntryABI.TILELANG_0_1_13_HOST_CALL,
            (tensor,),
            (ProgramBindingSpec(
                "output", ProgramBindingSource.PROVIDER_OUTPUT, "result"
            ),),
        )
    with pytest.raises(KernelContractError, match="read-only bool"):
        ProgramNodeSpec(
            "bad", "pkg:bad", "mindclade_bad_adapter", "call",
            ProgramEntryABI.TILELANG_0_1_13_HOST_CALL,
            (
                ProgramParameterSpec(
                    0, "need_grad", ProgramParameterKind.SCALAR,
                    WorkspaceAccess.READ, scalar_type=ScalarABIType.INT64,
                ),
                stream,
            ),
            (
                ProgramBindingSpec(
                    "need_grad", ProgramBindingSource.GRADIENT_REQUEST, "x"
                ),
                ProgramBindingSpec("stream", ProgramBindingSource.CURRENT_STREAM),
            ),
        )

    optional_output = ProgramParameterSpec(
        0, "grad", ProgramParameterKind.TENSOR, WorkspaceAccess.WRITE,
        ShapeTuple((DimRef("x", 0),)), ConstantDType("float32"),
        ConstantDevice("cuda"), optional=True,
    )
    with pytest.raises(KernelContractError, match="one shared GRADIENT_REQUEST"):
        ProgramNodeSpec(
            "optional", "pkg:optional", "mindclade_optional_adapter", "call",
            ProgramEntryABI.TILELANG_0_1_13_HOST_CALL,
            (optional_output, stream),
            (
                ProgramBindingSpec(
                    "grad", ProgramBindingSource.PROVIDER_OUTPUT, "grad_x"
                ),
                ProgramBindingSpec("stream", ProgramBindingSource.CURRENT_STREAM),
            ),
        )


def test_output_requires_exact_expression_domains_and_boolean_types() -> None:
    with pytest.raises(KernelContractError, match="DTYPE-domain"):
        OutputSpec(
            "bad", ShapeTuple((DimRef("x", 0),)), DimRef("x", 0),
            ConstantDevice("cuda"), ("axis",), True, False,
        )
    with pytest.raises(KernelContractError, match="DEVICE-domain"):
        OutputSpec(
            "bad", ShapeTuple((DimRef("x", 0),)), ConstantDType("float32"),
            ConstantDType("float32"), ("axis",), True, False,
        )
    with pytest.raises(KernelContractError, match="visible_in_facade must be a bool"):
        OutputSpec(
            "bad", ShapeTuple((DimRef("x", 0),)), ConstantDType("float32"),
            ConstantDevice("cuda"), ("axis",), 1, False,
        )


def test_program_group_symbols_and_logical_launch_contract_fail_closed() -> None:
    node = program_node("node", symbol="private_launch")
    group = ProgramGroupSpec((node,))
    forward = ForwardSpec(
        schema="_example_fwd(Tensor x) -> Tensor result",
        builder="pkg:forward",
        symbol="private_launch",
        outputs=(output(),),
        program_group=group,
    )
    with pytest.raises(KernelContractError, match="collide with logical launchers"):
        required_kernel(forward=forward)

    non_current = LaunchContract(
        current_stream_only=False,
        graph_capture_safe=False,
    )
    valid_forward = ForwardSpec(
        schema="_example_fwd(Tensor x) -> Tensor result",
        builder="pkg:forward",
        symbol="forward_launch",
        outputs=(output(),),
        program_group=group,
    )
    with pytest.raises(KernelContractError, match="current-stream-only"):
        required_kernel(forward=valid_forward, launch=non_current)


def test_workspace_plan_and_hidden_allocation_claim_must_match() -> None:
    workspace = WorkspaceSpec(
        "scratch", ShapeTuple((DimRef("x", 0),)), ConstantDType("float32")
    )
    group = ProgramGroupSpec(
        nodes=(program_node(
            "node", workspace_accesses=(("scratch", WorkspaceAccess.WRITE),)
        ),),
        workspaces=(workspace,),
    )
    forward = ForwardSpec(
        schema="_example_fwd(Tensor x) -> Tensor result",
        builder="pkg:forward",
        symbol="forward_launch",
        outputs=(output(),),
        program_group=group,
    )
    with pytest.raises(KernelContractError, match="must equal whether"):
        required_kernel(forward=forward)
    with pytest.raises(KernelContractError, match="cannot allocate hidden device memory"):
        LaunchContract(hidden_device_allocation=True)


def test_capability_and_numerical_contract_reject_ambiguity() -> None:
    with pytest.raises(KernelContractError, match="constraint codes"):
        CapabilityEnvelope(
            architectures=("sm90",),
            dtypes=("bf16",),
            layouts=("contiguous",),
            modes=("default",),
            constraints=(
                DimensionConstraint(BoolLiteral(True), "SAME", "first"),
                DimensionConstraint(BoolLiteral(True), "SAME", "second"),
            ),
            graph_capture_safe=True,
            training_capable=True,
        )
    tensor_constraint = TensorCapabilityConstraint(
        "mask", dtypes=("bool", "float32"), devices=("cuda",), ranks=(2, 3)
    )
    with pytest.raises(KernelContractError, match="argument identities"):
        CapabilityEnvelope(
            architectures=("sm90",),
            dtypes=("bf16",),
            layouts=("contiguous",),
            modes=("default",),
            constraints=(),
            graph_capture_safe=True,
            training_capable=True,
            tensor_constraints=(tensor_constraint, tensor_constraint),
        )
    with pytest.raises(KernelContractError, match="tolerance identities"):
        NumericalEnvelope(
            "bf16",
            1,
            (
                TensorTolerance("result", "bf16", 0.1),
                TensorTolerance("result", "bf16", 0.2),
            ),
        )


def test_capability_contract_requires_boolean_predicates_and_strict_fields() -> None:
    with pytest.raises(KernelContractError, match="typed boolean expression"):
        DimensionConstraint(IntLiteral(1), "POSITIVE", "must be positive")  # type: ignore[arg-type]
    with pytest.raises(KernelContractError, match="constraint code"):
        DimensionConstraint(BoolLiteral(True), "lower-case", "invalid code")
    with pytest.raises(KernelContractError, match="version must be exactly integer 1"):
        DimensionConstraint(BoolLiteral(True), "VALID", "valid", version=True)
    with pytest.raises(KernelContractError, match="must be a non-empty tuple"):
        CapabilityEnvelope(
            architectures=["sm90"],  # type: ignore[arg-type]
            dtypes=("float32",),
            layouts=("contiguous",),
            modes=("default",),
            constraints=(),
            graph_capture_safe=True,
            training_capable=True,
        )
    with pytest.raises(KernelContractError, match="graph_capture_safe must be a bool"):
        CapabilityEnvelope(
            architectures=("sm90",),
            dtypes=("float32",),
            layouts=("contiguous",),
            modes=("default",),
            constraints=(),
            graph_capture_safe=1,  # type: ignore[arg-type]
            training_capable=True,
        )


def test_capability_envelope_has_canonical_order_and_digest() -> None:
    aligned = DimensionConstraint(BoolLiteral(True), "ALIGNED", "aligned")
    bounded = DimensionConstraint(BoolLiteral(True), "BOUNDED", "bounded")
    tensor_a = TensorCapabilityConstraint(
        "x",
        dtypes=("float32", "bfloat16"),
        layouts=("strided", "contiguous"),
        devices=("cuda",),
        ranks=(4, 2),
    )
    tensor_b = TensorCapabilityConstraint(
        "x",
        dtypes=("bfloat16", "float32"),
        layouts=("contiguous", "strided"),
        devices=("cuda",),
        ranks=(2, 4),
    )
    first = CapabilityEnvelope(
        architectures=("sm100", "sm90"),
        dtypes=("float32", "bfloat16"),
        layouts=("strided", "contiguous"),
        modes=("training", "default"),
        constraints=(bounded, aligned),
        graph_capture_safe=True,
        training_capable=True,
        tensor_constraints=(tensor_a,),
    )
    second = CapabilityEnvelope(
        architectures=("sm90", "sm100"),
        dtypes=("bfloat16", "float32"),
        layouts=("contiguous", "strided"),
        modes=("default", "training"),
        constraints=(aligned, bounded),
        graph_capture_safe=True,
        training_capable=True,
        tensor_constraints=(tensor_b,),
    )
    assert first.to_canonical() == second.to_canonical()
    assert first.digest == second.digest


def test_capability_evaluation_and_rendering_are_deterministic_and_fail_closed() -> None:
    envelope = CapabilityEnvelope(
        architectures=("sm90",),
        dtypes=("float32",),
        layouts=("contiguous",),
        modes=("default",),
        constraints=(
            DimensionConstraint(
                Eq(Modulo(DimRef("x", 1), IntLiteral(8)), IntLiteral(0)),
                "ALIGNED",
                "x channel dimension must be divisible by eight",
            ),
        ),
        graph_capture_safe=False,
        training_capable=False,
        tensor_constraints=(
            TensorCapabilityConstraint(
                "x",
                dtypes=("float32",),
                layouts=("contiguous",),
                devices=("cuda",),
                ranks=(2,),
            ),
        ),
    )
    accepted = CapabilityRequest(
        "sm90",
        "float32",
        "contiguous",
        "default",
        False,
        False,
        EvaluationContext(
            tensors={"x": TensorMetadata((2, 8), "float32", "cuda:0")}
        ),
    )
    assert envelope.evaluate(accepted) == CapabilityDecision(True, ())

    rejected = CapabilityRequest(
        "sm80",
        "bfloat16",
        "strided",
        "decode",
        True,
        True,
        EvaluationContext(
            tensors={"x": TensorMetadata((2, 7), "bfloat16", "cpu", "strided")}
        ),
    )
    decision = envelope.evaluate(rejected)
    assert not decision.supported
    assert tuple(item.code for item in decision.violations) == (
        "UNSUPPORTED_ARCHITECTURE",
        "UNSUPPORTED_DTYPE",
        "UNSUPPORTED_LAYOUT",
        "UNSUPPORTED_MODE",
        "GRAPH_CAPTURE_UNSAFE",
        "TRAINING_UNSUPPORTED",
        "TENSOR_DTYPE_UNSUPPORTED",
        "TENSOR_LAYOUT_UNSUPPORTED",
        "TENSOR_DEVICE_UNSUPPORTED",
        "ALIGNED",
    )
    assert envelope.render() == envelope.render()
    assert "ALIGNED:" in envelope.render()

    missing = CapabilityRequest(
        "sm90",
        "float32",
        "contiguous",
        "default",
        False,
        False,
        EvaluationContext(tensors={}),
    )
    missing_decision = envelope.evaluate(missing)
    assert tuple(item.code for item in missing_decision.violations) == (
        "TENSOR_ARGUMENT_MISSING",
        "ALIGNED",
    )
    assert "evaluation failed" in missing_decision.violations[-1].message


def test_capability_decision_consistency_is_validated() -> None:
    violation = CapabilityViolation("UNSUPPORTED_MODE", "mode is unsupported")
    with pytest.raises(KernelContractError, match="exactly when violations are empty"):
        CapabilityDecision(True, (violation,))
    with pytest.raises(KernelContractError, match="exactly when violations are empty"):
        CapabilityDecision(False, ())


def test_composite_gradient_names_bind_semantic_arguments() -> None:
    with pytest.raises(KernelContractError, match="not semantic operator arguments"):
        required_kernel(
            backward=None,
            autograd_policy=AutogradPolicy.COMPOSITE,
            composite=CompositeAutogradSpec(
                "pkg:backward",
                _SHA,
                "pytorch-2.10",
                (gradient("weight", "grad_weight"),),
                False,
                setup_context="pkg:setup_context",
                backward="pkg:backward",
            ),
        )


def test_compile_identity_is_separate_from_runtime_compatibility() -> None:
    compile_environment = CompileEnvironment("sm90", _SHA, _SHA, _SHA, _SHA, _SHA, ("-O3",))
    runtime = RuntimeCompatibility("sm90", ("tma",), ("H100", "H200"), "550.54", "12.4", 65536, False)
    assert compile_environment.digest != runtime.digest


def test_workload_canonicalization_and_schedule_legality() -> None:
    workload = WorkloadSpec(
        "example",
        (("N", 64), ("B", 1)),
        "bf16",
        "bf16",
        "contiguous",
        "training",
        (("causal", False),),
    )
    assert workload.dimensions == (("B", 1), ("N", 64))
    schedule = ScheduleSpec(64, 64, 32, 256, 3, 8, use_tma=True, use_wgmma=True)
    specialization = SpecializationSpec(workload, schedule, "bf16-v1")
    assert specialization.digest.startswith("sha256:")
    with pytest.raises(KernelContractError, match="WGMMA schedule requires TMA"):
        ScheduleSpec(64, 64, 32, 256, 3, 8, use_wgmma=True)


def test_required_qualification_co_promotes_backward() -> None:
    capability = QualifiedCapability(
        "example", 1, "optimized", 1,
        _SHA, _SHA, _SHA, _SHA, _SHA, _SHA, None, _SHA, "qualified",
    )
    with pytest.raises(KernelContractError, match="backward artifact"):
        capability.validate_training_atomicity(autograd_required=True)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
