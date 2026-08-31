"""Declarative integration contract for Pairformer triangle attention."""

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
    name="triangle_attention",
    namespace="mindclade",
    family="pairformer",
    source="pairformer/triangle_attention/spec.py",
    operator_schema=(
        "triangle_attention(Tensor q, Tensor k, Tensor v, Tensor bias, "
        "Tensor mask, float scale) -> Tensor output"
    ),
    facade_outputs=("output",),
    fake="kernels.pairformer.triangle_attention.reference:fake",
    forward=ForwardSpec(
        schema=(
            "_triangle_attention_fwd(Tensor q, Tensor k, Tensor v, Tensor bias, "
            "Tensor mask, float scale) -> Tensor output"
        ),
        builder="kernels.pairformer.triangle_attention.tilelang:build_tilelang_program",
        symbol="mindclade_tilelang_triangle_attention_fwd_launch",
        outputs=(
            OutputSpec(
                name="output",
                shape=ShapeOf(argument="q"),
                dtype=SameAsInputDType(argument="q"),
                device=SameAsInputDevice(argument="q"),
                semantic_axes=(
                    "batch_prefix",
                    "pair_row",
                    "pair_column",
                    "head",
                    "channel",
                ),
                visible_in_facade=True,
                saved_for_backward=False,
            ),
        ),
    ),
    backward=None,
    autograd_policy=AutogradPolicy.COMPOSITE,
    composite=CompositeAutogradSpec(
        decomposition=(
            "kernels.pairformer.triangle_attention.reference:"
            "triangle_attention_reference"
        ),
        source_digest="sha256:485361b7d3a06836dfd7b13a24bd41ba2480852b0446a0c2e35e74dc1b9a2854",
        runtime_envelope="pytorch-reference;promotion=unpromoted",
        gradients=(
            GradientSpec(input_name="q", output_name="grad_q"),
            GradientSpec(input_name="k", output_name="grad_k"),
            GradientSpec(input_name="v", output_name="grad_v"),
            GradientSpec(input_name="bias", output_name="grad_bias"),
        ),
        supports_double_backward=False,
        setup_context="kernels.pairformer.triangle_attention.reference:setup_context",
        backward="kernels.pairformer.triangle_attention.reference:composite_backward",
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
