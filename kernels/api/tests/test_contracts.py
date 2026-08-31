from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from kernels.api.backward import BackwardSpec
from kernels.api.capability import CapabilityEnvelope, DimensionConstraint
from kernels.api.effects import EffectSpec
from kernels.api.environment import CompileEnvironment, RuntimeCompatibility
from kernels.api.errors import KernelContractError, SchemaError
from kernels.api.expressions import BoolLiteral, ConstantDType, ConstantDevice, DimRef
from kernels.api.forward import ForwardSpec
from kernels.api.gradient import GradientSpec
from kernels.api.kernel import AutogradPolicy, CompositeAutogradSpec, KernelSpec
from kernels.api.launch import DeterminismClass, LaunchContract
from kernels.api.numerics import NumericalEnvelope, TensorTolerance
from kernels.api.output import InitializationSpec, OutputSpec
from kernels.api.program_group import ProgramGroupSpec, ProgramNodeSpec, WorkspaceSpec
from kernels.api.qualification import QualifiedCapability
from kernels.api.schedule import ScheduleSpec, SpecializationSpec
from kernels.api.workload import WorkloadSpec

_SHA = "sha256:" + "a" * 64


def output(name: str = "result", *, visible: bool = True, saved: bool = False) -> OutputSpec:
    return OutputSpec(
        name=name,
        shape=(DimRef("x", 0), DimRef("x", 1)),
        dtype=ConstantDType("float32"),
        device=ConstantDevice("cuda"),
        semantic_axes=("batch", "channel"),
        visible_in_facade=visible,
        saved_for_backward=saved,
        initialization=InitializationSpec("zero") if saved else None,
    )


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
        gradients=(GradientSpec("x", "grad_x"),),
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
        "capability_envelope": envelope(),
    }
    values.update(changes)
    return KernelSpec(**values)  # type: ignore[arg-type]


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
        composite=CompositeAutogradSpec("pkg:backward", _SHA, "pytorch-2.10"),
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
        gradients=(GradientSpec("weight", "grad_x"),),
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
        gradients=(GradientSpec("x", "grad_x"),),
        supports_double_backward=True,
    )
    with pytest.raises(KernelContractError, match="second-order provider"):
        required_kernel(backward=backward)


def test_launch_and_effect_contracts_fail_on_false_safety_claims() -> None:
    with pytest.raises(KernelContractError, match="cannot globally synchronize"):
        LaunchContract(global_synchronization=True)
    with pytest.raises(KernelContractError, match="atomic kernel"):
        required_kernel(effects=EffectSpec(uses_atomics=True))
    with pytest.raises(KernelContractError, match="graph-capture claims"):
        required_kernel(launch=LaunchContract(graph_capture_safe=False))
    nondeterministic = required_kernel(
        effects=EffectSpec(uses_atomics=True),
        launch=LaunchContract(determinism=DeterminismClass.CONDITIONALLY_DETERMINISTIC),
    )
    assert nondeterministic.effects.uses_atomics


def test_program_group_has_deterministic_topology_and_rejects_cycles() -> None:
    workspace = WorkspaceSpec(
        "delta",
        (DimRef("x", 0),),
        ConstantDType("float32"),
        zero_initialize=True,
    )
    group = ProgramGroupSpec(
        (
            ProgramNodeSpec("dq", "pkg:dq", "dq_launch", depends_on=("delta",)),
            ProgramNodeSpec("delta", "pkg:delta", "delta_launch", workspaces=(workspace,)),
            ProgramNodeSpec("dkv", "pkg:dkv", "dkv_launch", depends_on=("delta",)),
        )
    )
    assert group.topological_order() == ("delta", "dkv", "dq")
    with pytest.raises(KernelContractError, match="cycle"):
        ProgramGroupSpec(
            (
                ProgramNodeSpec("a", "pkg:a", "a_launch", depends_on=("b",)),
                ProgramNodeSpec("b", "pkg:b", "b_launch", depends_on=("a",)),
            )
        )


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
    with pytest.raises(KernelContractError, match="tolerance identities"):
        NumericalEnvelope(
            "bf16",
            1,
            (
                TensorTolerance("result", "bf16", 0.1),
                TensorTolerance("result", "bf16", 0.2),
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
