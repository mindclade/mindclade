"""Declarative integration contract for Pairformer triangle multiplication."""

from kernels.api import (
    AutogradPolicy,
    CompositeAutogradSpec,
    DeterminismClass,
    EffectSpec,
    ForwardSpec,
    GradientSpec,
    KernelSpec,
    LaunchContract,
    OutputSpec,
    SameAsInputDType,
    SameAsInputDevice,
    ShapeOf,
)

KERNEL_SPEC: KernelSpec = KernelSpec(
    name="triangle_multiplication",
    namespace="mindclade",
    family="pairformer",
    source="pairformer/triangle_multiplication/spec.py",
    operator_schema=(
        "triangle_multiplication(Tensor left, Tensor right, Tensor mask, "
        "bool outgoing) -> Tensor output"
    ),
    facade_outputs=("output",),
    fake="kernels.pairformer.triangle_multiplication.reference:fake",
    forward=ForwardSpec(
        schema=(
            "_triangle_multiplication_fwd(Tensor left, Tensor right, Tensor mask, "
            "bool outgoing) -> Tensor output"
        ),
        builder=(
            "kernels.pairformer.triangle_multiplication.tilelang:"
            "build_tilelang_program"
        ),
        symbol="mindclade_tilelang_triangle_multiplication_fwd_launch",
        outputs=(
            OutputSpec(
                name="output",
                shape=ShapeOf(argument="left"),
                dtype=SameAsInputDType(argument="left"),
                device=SameAsInputDevice(argument="left"),
                semantic_axes=("batch_prefix", "pair_row", "pair_column", "channel"),
                visible_in_facade=True,
                saved_for_backward=False,
            ),
        ),
    ),
    backward=None,
    autograd_policy=AutogradPolicy.COMPOSITE,
    composite=CompositeAutogradSpec(
        decomposition=(
            "kernels.pairformer.triangle_multiplication.reference:"
            "triangle_multiplication_reference"
        ),
        source_digest="sha256:5e72ba2c8e667afeb004bdb6e258045c8bdcdf922ec298c3342b624b75fe0bf3",
        runtime_envelope="pytorch-reference;promotion=unpromoted",
        gradients=(
            GradientSpec(input_name="left", output_name="grad_left"),
            GradientSpec(input_name="right", output_name="grad_right"),
        ),
        supports_double_backward=False,
        setup_context="kernels.pairformer.triangle_multiplication.reference:setup_context",
        backward="kernels.pairformer.triangle_multiplication.reference:composite_backward",
    ),
    effects=EffectSpec(),
    launch=LaunchContract(
        current_stream_only=True,
        global_synchronization=False,
        hidden_device_allocation=False,
        graph_capture_safe=False,
        determinism=DeterminismClass.DETERMINISTIC,
    ),
)
