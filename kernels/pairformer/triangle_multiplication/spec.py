"""Declarative native-training contract for Pairformer triangle multiplication."""

from kernels.api import (
    And,
    AutogradPolicy,
    BackwardArgumentBinding,
    BackwardArgumentSource,
    BackwardSpec,
    CapabilityEnvelope,
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
    OutputSpec,
    ProgramGroupSpec,
    ProgramNodeSpec,
    RankRef,
    ShapeOf,
    TensorCapabilityConstraint,
)


KERNEL_SPEC: KernelSpec = KernelSpec(
    name="triangle_multiplication",
    namespace="mindclade",
    family="pairformer",
    source="pairformer/triangle_multiplication/spec.py",
    operator_schema="triangle_multiplication(Tensor left, Tensor right, Tensor mask, bool outgoing) -> Tensor output",
    facade_outputs=("output",),
    fake=None,
    forward=ForwardSpec(
        schema="_triangle_multiplication_fwd(Tensor left, Tensor right, Tensor mask, bool outgoing) -> Tensor output",
        builder="kernels.pairformer.triangle_multiplication.tilelang:build_forward_program_group",
        symbol="mindclade_tilelang_triangle_multiplication_fwd_launch",
        outputs=(
            OutputSpec(
                name="output",
                shape=ShapeOf(argument="left"),
                dtype=DTypeRef(argument="left"),
                device=DeviceRef(argument="left"),
                semantic_axes=("batch", "pair_row", "pair_column", "channel"),
                visible_in_facade=True,
                saved_for_backward=False,
            ),
        ),
        program_group=ProgramGroupSpec(
            nodes=(
                ProgramNodeSpec(
                    name="forward",
                    builder="kernels.pairformer.triangle_multiplication.tilelang:build_forward_program",
                    symbol="mindclade_tilelang_triangle_multiplication_forward_raw",
                ),
            )
        ),
    ),
    backward=BackwardSpec(
        schema=(
            "_triangle_multiplication_bwd(Tensor grad_output, Tensor left, "
            "Tensor right, Tensor mask, bool outgoing, bool need_left_grad, "
            "bool need_right_grad) -> (Tensor? grad_left, Tensor? grad_right)"
        ),
        builder="kernels.pairformer.triangle_multiplication.tilelang:build_backward_program_group",
        symbol="mindclade_tilelang_triangle_multiplication_bwd_launch",
        argument_bindings=(
            BackwardArgumentBinding(provider_argument="grad_output", source=BackwardArgumentSource.OUTPUT_GRADIENT, source_name="output", missing=MissingGradientPolicy.ERROR),
            BackwardArgumentBinding(provider_argument="left", source=BackwardArgumentSource.OPERATOR_ARGUMENT, source_name="left"),
            BackwardArgumentBinding(provider_argument="right", source=BackwardArgumentSource.OPERATOR_ARGUMENT, source_name="right"),
            BackwardArgumentBinding(provider_argument="mask", source=BackwardArgumentSource.OPERATOR_ARGUMENT, source_name="mask"),
            BackwardArgumentBinding(provider_argument="outgoing", source=BackwardArgumentSource.OPERATOR_ARGUMENT, source_name="outgoing"),
            BackwardArgumentBinding(provider_argument="need_left_grad", source=BackwardArgumentSource.NEEDS_INPUT_GRAD, source_name="left"),
            BackwardArgumentBinding(provider_argument="need_right_grad", source=BackwardArgumentSource.NEEDS_INPUT_GRAD, source_name="right"),
        ),
        gradients=(
            GradientSpec(input_name="left", output_name="grad_left", optional=True, accumulation_dtype="float32"),
            GradientSpec(input_name="right", output_name="grad_right", optional=True, accumulation_dtype="float32"),
        ),
        supports_double_backward=False,
        program_group=ProgramGroupSpec(
            nodes=(
                ProgramNodeSpec(
                    name="dleft",
                    builder="kernels.pairformer.triangle_multiplication.tilelang:build_dleft",
                    symbol="mindclade_tilelang_triangle_multiplication_dleft_raw",
                ),
                ProgramNodeSpec(
                    name="dright",
                    builder="kernels.pairformer.triangle_multiplication.tilelang:build_dright",
                    symbol="mindclade_tilelang_triangle_multiplication_dright_raw",
                ),
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
        operation="triangle_multiplication", name="triangle_multiplication_sm90a_fp16_n64_c64", family="pairformer", backend="tilelang", builder="kernels.pairformer.triangle_multiplication.tilelang:build_forward_program_group", version=1, tier=ImplementationTier.SPECIALIZED, requires=("cuda", "sm90a", "tilelang-0.1.13"),
        envelope=CapabilityEnvelope(
            architectures=("sm90a",), dtypes=("float16",), layouts=("contiguous",), modes=("incoming", "outgoing"),
            constraints=(DimensionConstraint(predicate=And(operands=(Eq(lhs=RankRef(argument="left"), rhs=IntLiteral(value=4)), Eq(lhs=RankRef(argument="right"), rhs=IntLiteral(value=4)), Eq(lhs=RankRef(argument="mask"), rhs=IntLiteral(value=3)), Eq(lhs=DimRef(argument="left", axis=0), rhs=IntLiteral(value=1)), Eq(lhs=DimRef(argument="left", axis=1), rhs=IntLiteral(value=64)), Eq(lhs=DimRef(argument="left", axis=2), rhs=IntLiteral(value=64)), Eq(lhs=DimRef(argument="left", axis=3), rhs=IntLiteral(value=64)), Eq(lhs=DimRef(argument="right", axis=0), rhs=DimRef(argument="left", axis=0)), Eq(lhs=DimRef(argument="right", axis=1), rhs=DimRef(argument="left", axis=1)), Eq(lhs=DimRef(argument="right", axis=2), rhs=DimRef(argument="left", axis=2)), Eq(lhs=DimRef(argument="right", axis=3), rhs=DimRef(argument="left", axis=3)), Eq(lhs=DimRef(argument="mask", axis=0), rhs=DimRef(argument="left", axis=0)), Eq(lhs=DimRef(argument="mask", axis=1), rhs=DimRef(argument="left", axis=1)), Eq(lhs=DimRef(argument="mask", axis=2), rhs=DimRef(argument="left", axis=2)))), code="EXACT_B1_N64_C64", message="requires exact [1,64,64,64] operands and [1,64,64] mask"),), graph_capture_safe=True, training_capable=True,
            tensor_constraints=(TensorCapabilityConstraint(argument="left", dtypes=("float16",), layouts=("contiguous",), devices=("cuda",), ranks=(4,)), TensorCapabilityConstraint(argument="right", dtypes=("float16",), layouts=("contiguous",), devices=("cuda",), ranks=(4,)), TensorCapabilityConstraint(argument="mask", dtypes=("float16",), layouts=("contiguous",), devices=("cuda",), ranks=(3,))),
        ), priority=100,
    ),
    ImplementationSpec(
        operation="triangle_multiplication", name="triangle_multiplication_sm90a_bf16_n64_c64", family="pairformer", backend="tilelang", builder="kernels.pairformer.triangle_multiplication.tilelang:build_forward_program_group", version=1, tier=ImplementationTier.SPECIALIZED, requires=("cuda", "sm90a", "tilelang-0.1.13"),
        envelope=CapabilityEnvelope(architectures=("sm90a",), dtypes=("bfloat16",), layouts=("contiguous",), modes=("incoming", "outgoing"), constraints=(DimensionConstraint(predicate=And(operands=(Eq(lhs=RankRef(argument="left"), rhs=IntLiteral(value=4)), Eq(lhs=RankRef(argument="right"), rhs=IntLiteral(value=4)), Eq(lhs=RankRef(argument="mask"), rhs=IntLiteral(value=3)), Eq(lhs=DimRef(argument="left", axis=0), rhs=IntLiteral(value=1)), Eq(lhs=DimRef(argument="left", axis=1), rhs=IntLiteral(value=64)), Eq(lhs=DimRef(argument="left", axis=2), rhs=IntLiteral(value=64)), Eq(lhs=DimRef(argument="left", axis=3), rhs=IntLiteral(value=64)), Eq(lhs=DimRef(argument="right", axis=0), rhs=DimRef(argument="left", axis=0)), Eq(lhs=DimRef(argument="right", axis=1), rhs=DimRef(argument="left", axis=1)), Eq(lhs=DimRef(argument="right", axis=2), rhs=DimRef(argument="left", axis=2)), Eq(lhs=DimRef(argument="right", axis=3), rhs=DimRef(argument="left", axis=3)), Eq(lhs=DimRef(argument="mask", axis=0), rhs=DimRef(argument="left", axis=0)), Eq(lhs=DimRef(argument="mask", axis=1), rhs=DimRef(argument="left", axis=1)), Eq(lhs=DimRef(argument="mask", axis=2), rhs=DimRef(argument="left", axis=2)))), code="EXACT_B1_N64_C64", message="requires exact [1,64,64,64] operands and [1,64,64] mask"),), graph_capture_safe=True, training_capable=True, tensor_constraints=(TensorCapabilityConstraint(argument="left", dtypes=("bfloat16",), layouts=("contiguous",), devices=("cuda",), ranks=(4,)), TensorCapabilityConstraint(argument="right", dtypes=("bfloat16",), layouts=("contiguous",), devices=("cuda",), ranks=(4,)), TensorCapabilityConstraint(argument="mask", dtypes=("bfloat16",), layouts=("contiguous",), devices=("cuda",), ranks=(3,)))), priority=100,
    ),
    ImplementationSpec(
        operation="triangle_multiplication", name="triangle_multiplication_sm100a_fp16_n64_c64", family="pairformer", backend="tilelang", builder="kernels.pairformer.triangle_multiplication.tilelang:build_forward_program_group", version=1, tier=ImplementationTier.SPECIALIZED, requires=("cuda", "sm100a", "tilelang-0.1.13"),
        envelope=CapabilityEnvelope(architectures=("sm100a",), dtypes=("float16",), layouts=("contiguous",), modes=("incoming", "outgoing"), constraints=(DimensionConstraint(predicate=And(operands=(Eq(lhs=RankRef(argument="left"), rhs=IntLiteral(value=4)), Eq(lhs=RankRef(argument="right"), rhs=IntLiteral(value=4)), Eq(lhs=RankRef(argument="mask"), rhs=IntLiteral(value=3)), Eq(lhs=DimRef(argument="left", axis=0), rhs=IntLiteral(value=1)), Eq(lhs=DimRef(argument="left", axis=1), rhs=IntLiteral(value=64)), Eq(lhs=DimRef(argument="left", axis=2), rhs=IntLiteral(value=64)), Eq(lhs=DimRef(argument="left", axis=3), rhs=IntLiteral(value=64)), Eq(lhs=DimRef(argument="right", axis=0), rhs=DimRef(argument="left", axis=0)), Eq(lhs=DimRef(argument="right", axis=1), rhs=DimRef(argument="left", axis=1)), Eq(lhs=DimRef(argument="right", axis=2), rhs=DimRef(argument="left", axis=2)), Eq(lhs=DimRef(argument="right", axis=3), rhs=DimRef(argument="left", axis=3)), Eq(lhs=DimRef(argument="mask", axis=0), rhs=DimRef(argument="left", axis=0)), Eq(lhs=DimRef(argument="mask", axis=1), rhs=DimRef(argument="left", axis=1)), Eq(lhs=DimRef(argument="mask", axis=2), rhs=DimRef(argument="left", axis=2)))), code="EXACT_B1_N64_C64", message="requires exact [1,64,64,64] operands and [1,64,64] mask"),), graph_capture_safe=True, training_capable=True, tensor_constraints=(TensorCapabilityConstraint(argument="left", dtypes=("float16",), layouts=("contiguous",), devices=("cuda",), ranks=(4,)), TensorCapabilityConstraint(argument="right", dtypes=("float16",), layouts=("contiguous",), devices=("cuda",), ranks=(4,)), TensorCapabilityConstraint(argument="mask", dtypes=("float16",), layouts=("contiguous",), devices=("cuda",), ranks=(3,)))), priority=100,
    ),
    ImplementationSpec(
        operation="triangle_multiplication", name="triangle_multiplication_sm100a_bf16_n64_c64", family="pairformer", backend="tilelang", builder="kernels.pairformer.triangle_multiplication.tilelang:build_forward_program_group", version=1, tier=ImplementationTier.SPECIALIZED, requires=("cuda", "sm100a", "tilelang-0.1.13"),
        envelope=CapabilityEnvelope(architectures=("sm100a",), dtypes=("bfloat16",), layouts=("contiguous",), modes=("incoming", "outgoing"), constraints=(DimensionConstraint(predicate=And(operands=(Eq(lhs=RankRef(argument="left"), rhs=IntLiteral(value=4)), Eq(lhs=RankRef(argument="right"), rhs=IntLiteral(value=4)), Eq(lhs=RankRef(argument="mask"), rhs=IntLiteral(value=3)), Eq(lhs=DimRef(argument="left", axis=0), rhs=IntLiteral(value=1)), Eq(lhs=DimRef(argument="left", axis=1), rhs=IntLiteral(value=64)), Eq(lhs=DimRef(argument="left", axis=2), rhs=IntLiteral(value=64)), Eq(lhs=DimRef(argument="left", axis=3), rhs=IntLiteral(value=64)), Eq(lhs=DimRef(argument="right", axis=0), rhs=DimRef(argument="left", axis=0)), Eq(lhs=DimRef(argument="right", axis=1), rhs=DimRef(argument="left", axis=1)), Eq(lhs=DimRef(argument="right", axis=2), rhs=DimRef(argument="left", axis=2)), Eq(lhs=DimRef(argument="right", axis=3), rhs=DimRef(argument="left", axis=3)), Eq(lhs=DimRef(argument="mask", axis=0), rhs=DimRef(argument="left", axis=0)), Eq(lhs=DimRef(argument="mask", axis=1), rhs=DimRef(argument="left", axis=1)), Eq(lhs=DimRef(argument="mask", axis=2), rhs=DimRef(argument="left", axis=2)))), code="EXACT_B1_N64_C64", message="requires exact [1,64,64,64] operands and [1,64,64] mask"),), graph_capture_safe=True, training_capable=True, tensor_constraints=(TensorCapabilityConstraint(argument="left", dtypes=("bfloat16",), layouts=("contiguous",), devices=("cuda",), ranks=(4,)), TensorCapabilityConstraint(argument="right", dtypes=("bfloat16",), layouts=("contiguous",), devices=("cuda",), ranks=(4,)), TensorCapabilityConstraint(argument="mask", dtypes=("bfloat16",), layouts=("contiguous",), devices=("cuda",), ranks=(3,)))), priority=100,
    ),
)
