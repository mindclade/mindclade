"""Declarative native contract for Pairformer SwiGLU transition."""

from kernels.api import (
    And,
    AutogradPolicy,
    BackwardArgumentBinding,
    BackwardArgumentSource,
    BackwardSpec,
    CapabilityEnvelope,
    ConcatShape,
    DeterminismClass,
    DeviceRef,
    DimensionConstraint,
    DimRef,
    DTypeRef,
    EffectSpec,
    Eq,
    ForwardSpec,
    GradientSpec,
    ImplementationSpec,
    ImplementationTier,
    IntLiteral,
    KernelSpec,
    LaunchContract,
    MissingGradientPolicy,
    Or,
    OutputSpec,
    ProgramGroupSpec,
    ProgramNodeSpec,
    RankRef,
    ShapePrefix,
    ShapeTuple,
    TensorCapabilityConstraint,
)


KERNEL_SPEC: KernelSpec = KernelSpec(
    name="transition",
    namespace="mindclade",
    family="pairformer",
    source="pairformer/transition/spec.py",
    operator_schema=(
        "transition(Tensor gate, Tensor value, Tensor output_weight, "
        "Tensor output_bias, Tensor mask) -> (Tensor output, Tensor pre_mask_output)"
    ),
    facade_outputs=("output",),
    fake=None,
    forward=ForwardSpec(
        schema=(
            "_transition_fwd(Tensor gate, Tensor value, Tensor output_weight, "
            "Tensor output_bias, Tensor mask) -> "
            "(Tensor output, Tensor pre_mask_output)"
        ),
        builder="kernels.pairformer.transition.tilelang:build_forward",
        symbol="mindclade_tilelang_transition_fwd_launch",
        outputs=(
            OutputSpec(
                name="output",
                shape=ConcatShape(
                    parts=(
                        ShapePrefix(argument="gate", trailing_rank=1),
                        ShapeTuple(
                            dimensions=(DimRef(argument="output_weight", axis=1),)
                        ),
                    )
                ),
                dtype=DTypeRef(argument="gate"),
                device=DeviceRef(argument="gate"),
                semantic_axes=("batch", "row", "output_channel"),
                visible_in_facade=True,
                saved_for_backward=False,
            ),
            OutputSpec(
                name="pre_mask_output",
                shape=ConcatShape(
                    parts=(
                        ShapePrefix(argument="gate", trailing_rank=1),
                        ShapeTuple(
                            dimensions=(DimRef(argument="output_weight", axis=1),)
                        ),
                    )
                ),
                dtype=DTypeRef(argument="gate"),
                device=DeviceRef(argument="gate"),
                semantic_axes=("batch", "row", "output_channel"),
                visible_in_facade=False,
                saved_for_backward=True,
            ),
        ),
        program_group=ProgramGroupSpec(
            nodes=(
                ProgramNodeSpec(
                    name="transition_forward",
                    builder="kernels.pairformer.transition.tilelang:build_forward_program",
                    symbol="mindclade_tilelang_transition_forward_program_launch",
                ),
            )
        ),
    ),
    backward=BackwardSpec(
        schema=(
            "_transition_bwd(Tensor grad_output, Tensor gate, Tensor value, "
            "Tensor output_weight, Tensor output_bias, Tensor mask, "
            "Tensor pre_mask_output, bool need_gate_grad, bool need_value_grad, "
            "bool need_weight_grad, bool need_bias_grad, bool need_mask_grad) -> "
            "(Tensor? grad_gate, Tensor? grad_value, Tensor? grad_weight, "
            "Tensor? grad_bias, Tensor? grad_mask)"
        ),
        builder="kernels.pairformer.transition.tilelang:build_backward",
        symbol="mindclade_tilelang_transition_bwd_launch",
        argument_bindings=(
            BackwardArgumentBinding(provider_argument="grad_output", source=BackwardArgumentSource.OUTPUT_GRADIENT, source_name="output", missing=MissingGradientPolicy.ERROR),
            BackwardArgumentBinding(provider_argument="gate", source=BackwardArgumentSource.OPERATOR_ARGUMENT, source_name="gate"),
            BackwardArgumentBinding(provider_argument="value", source=BackwardArgumentSource.OPERATOR_ARGUMENT, source_name="value"),
            BackwardArgumentBinding(provider_argument="output_weight", source=BackwardArgumentSource.OPERATOR_ARGUMENT, source_name="output_weight"),
            BackwardArgumentBinding(provider_argument="output_bias", source=BackwardArgumentSource.OPERATOR_ARGUMENT, source_name="output_bias"),
            BackwardArgumentBinding(provider_argument="mask", source=BackwardArgumentSource.OPERATOR_ARGUMENT, source_name="mask"),
            BackwardArgumentBinding(provider_argument="pre_mask_output", source=BackwardArgumentSource.FORWARD_OUTPUT, source_name="pre_mask_output"),
            BackwardArgumentBinding(provider_argument="need_gate_grad", source=BackwardArgumentSource.NEEDS_INPUT_GRAD, source_name="gate"),
            BackwardArgumentBinding(provider_argument="need_value_grad", source=BackwardArgumentSource.NEEDS_INPUT_GRAD, source_name="value"),
            BackwardArgumentBinding(provider_argument="need_weight_grad", source=BackwardArgumentSource.NEEDS_INPUT_GRAD, source_name="output_weight"),
            BackwardArgumentBinding(provider_argument="need_bias_grad", source=BackwardArgumentSource.NEEDS_INPUT_GRAD, source_name="output_bias"),
            BackwardArgumentBinding(provider_argument="need_mask_grad", source=BackwardArgumentSource.NEEDS_INPUT_GRAD, source_name="mask"),
        ),
        gradients=(
            GradientSpec(input_name="gate", output_name="grad_gate", optional=True, accumulation_dtype="float32"),
            GradientSpec(input_name="value", output_name="grad_value", optional=True, accumulation_dtype="float32"),
            GradientSpec(input_name="output_weight", output_name="grad_weight", optional=True, accumulation_dtype="float32"),
            GradientSpec(input_name="output_bias", output_name="grad_bias", optional=True, accumulation_dtype="float32"),
            GradientSpec(input_name="mask", output_name="grad_mask", optional=True, accumulation_dtype="float32"),
        ),
        supports_double_backward=False,
        program_group=ProgramGroupSpec(
            nodes=(
                ProgramNodeSpec(name="grad_gate_value", builder="kernels.pairformer.transition.tilelang:build_grad_gate_value", symbol="mindclade_tilelang_transition_grad_gate_value_launch"),
                ProgramNodeSpec(name="grad_weight", builder="kernels.pairformer.transition.tilelang:build_grad_weight", symbol="mindclade_tilelang_transition_grad_weight_launch"),
                ProgramNodeSpec(name="grad_bias", builder="kernels.pairformer.transition.tilelang:build_grad_bias", symbol="mindclade_tilelang_transition_grad_bias_launch"),
                ProgramNodeSpec(name="grad_mask", builder="kernels.pairformer.transition.tilelang:build_grad_mask", symbol="mindclade_tilelang_transition_grad_mask_launch"),
            )
        ),
    ),
    autograd_policy=AutogradPolicy.REQUIRED,
    effects=EffectSpec(),
    launch=LaunchContract(
        current_stream_only=True,
        global_synchronization=False,
        hidden_device_allocation=False,
        graph_capture_safe=True,
        determinism=DeterminismClass.DETERMINISTIC,
    ),
)


IMPLEMENTATION_SPECS = (
    ImplementationSpec(
        operation="transition",
        name="transition_sm90a_sm100a_fp16_bf16_v1",
        family="pairformer",
        backend="tilelang",
        builder="kernels.pairformer.transition.tilelang:build_forward",
        version=1,
        tier=ImplementationTier.SPECIALIZED,
        requires=("cuda", "tilelang-0.1.13"),
        envelope=CapabilityEnvelope(
            architectures=("sm90a", "sm100a"),
            dtypes=("float16", "bfloat16"),
            layouts=("contiguous",),
            modes=("pair_b1_r147456_h512_c128", "single_b1_r768_h1536_c384"),
            constraints=(
                DimensionConstraint(
                    predicate=And(
                        operands=(
                            Eq(lhs=RankRef(argument="gate"), rhs=IntLiteral(value=3)),
                            Eq(lhs=RankRef(argument="value"), rhs=IntLiteral(value=3)),
                            Eq(lhs=RankRef(argument="output_weight"), rhs=IntLiteral(value=2)),
                            Eq(lhs=RankRef(argument="output_bias"), rhs=IntLiteral(value=1)),
                            Eq(lhs=RankRef(argument="mask"), rhs=IntLiteral(value=2)),
                            Eq(lhs=DimRef(argument="value", axis=0), rhs=DimRef(argument="gate", axis=0)),
                            Eq(lhs=DimRef(argument="value", axis=1), rhs=DimRef(argument="gate", axis=1)),
                            Eq(lhs=DimRef(argument="value", axis=2), rhs=DimRef(argument="gate", axis=2)),
                            Eq(lhs=DimRef(argument="output_weight", axis=0), rhs=DimRef(argument="gate", axis=2)),
                            Eq(lhs=DimRef(argument="output_bias", axis=0), rhs=DimRef(argument="output_weight", axis=1)),
                            Eq(lhs=DimRef(argument="mask", axis=0), rhs=DimRef(argument="gate", axis=0)),
                            Eq(lhs=DimRef(argument="mask", axis=1), rhs=DimRef(argument="gate", axis=1)),
                            Or(
                                operands=(
                                    And(operands=(Eq(lhs=DimRef(argument="gate", axis=0), rhs=IntLiteral(value=1)), Eq(lhs=DimRef(argument="gate", axis=1), rhs=IntLiteral(value=147456)), Eq(lhs=DimRef(argument="gate", axis=2), rhs=IntLiteral(value=512)), Eq(lhs=DimRef(argument="output_weight", axis=1), rhs=IntLiteral(value=128)))),
                                    And(operands=(Eq(lhs=DimRef(argument="gate", axis=0), rhs=IntLiteral(value=1)), Eq(lhs=DimRef(argument="gate", axis=1), rhs=IntLiteral(value=768)), Eq(lhs=DimRef(argument="gate", axis=2), rhs=IntLiteral(value=1536)), Eq(lhs=DimRef(argument="output_weight", axis=1), rhs=IntLiteral(value=384)))),
                                )
                            ),
                        )
                    ),
                    code="TRANSITION_APPROVED_PROFILE",
                    message="requires one of the two approved transition shape profiles",
                ),
            ),
            graph_capture_safe=True,
            training_capable=True,
            tensor_constraints=(
                TensorCapabilityConstraint(argument="gate", dtypes=("float16", "bfloat16"), layouts=("contiguous",), devices=("cuda",), ranks=(3,)),
                TensorCapabilityConstraint(argument="value", dtypes=("float16", "bfloat16"), layouts=("contiguous",), devices=("cuda",), ranks=(3,)),
                TensorCapabilityConstraint(argument="output_weight", dtypes=("float16", "bfloat16"), layouts=("contiguous",), devices=("cuda",), ranks=(2,)),
                TensorCapabilityConstraint(argument="output_bias", dtypes=("float16", "bfloat16"), layouts=("contiguous",), devices=("cuda",), ranks=(1,)),
                TensorCapabilityConstraint(argument="mask", dtypes=("float16", "bfloat16", "float32"), layouts=("contiguous",), devices=("cuda",), ranks=(2,)),
            ),
        ),
        priority=100,
    ),
)
