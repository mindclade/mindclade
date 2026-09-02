"""Declarative native contract for Pairformer outer-product mean."""

from kernels.api import (
    And,
    AutogradPolicy,
    BackwardArgumentBinding,
    BackwardArgumentSource,
    BackwardSpec,
    CapabilityEnvelope,
    ConcatShape,
    ConstantDType,
    DeterminismClass,
    DeviceRef,
    DimensionConstraint,
    DimRef,
    DTypeRef,
    EffectSpec,
    Eq,
    FloatLiteral,
    ForwardSpec,
    GradientSpec,
    GreaterThan,
    ImplementationSpec,
    ImplementationTier,
    IntLiteral,
    IsFinite,
    KernelSpec,
    LaunchContract,
    MissingGradientPolicy,
    OutputSpec,
    ProgramGroupSpec,
    ProgramNodeSpec,
    RankRef,
    ScalarRef,
    ScalarType,
    ShapePrefix,
    ShapeTuple,
    TensorCapabilityConstraint,
    WorkspaceAccess,
    WorkspaceSpec,
    WorkspaceUseSpec,
)


KERNEL_SPEC: KernelSpec = KernelSpec(
    name="outer_product_mean",
    namespace="mindclade",
    family="pairformer",
    source="pairformer/outer_product_mean/spec.py",
    operator_schema=(
        "outer_product_mean(Tensor left, Tensor right, Tensor mask, float epsilon) "
        "-> (Tensor output, Tensor normalizer)"
    ),
    facade_outputs=("output",),
    fake=None,
    forward=ForwardSpec(
        schema=(
            "_outer_product_mean_fwd(Tensor left, Tensor right, Tensor mask, "
            "float epsilon) -> (Tensor output, Tensor normalizer)"
        ),
        builder="kernels.pairformer.outer_product_mean.tilelang:build_forward_program_group",
        symbol="mindclade_tilelang_outer_product_mean_fwd_launch",
        outputs=(
            OutputSpec(
                name="output",
                shape=ConcatShape(
                    parts=(
                        ShapePrefix(argument="left", trailing_rank=3),
                        ShapeTuple(
                            dimensions=(
                                DimRef(argument="left", axis=-2),
                                DimRef(argument="right", axis=-2),
                                DimRef(argument="left", axis=-1),
                                DimRef(argument="right", axis=-1),
                            )
                        ),
                    )
                ),
                dtype=DTypeRef(argument="left"),
                device=DeviceRef(argument="left"),
                semantic_axes=(
                    "batch_prefix",
                    "left_node",
                    "right_node",
                    "left_channel",
                    "right_channel",
                ),
                visible_in_facade=True,
                saved_for_backward=True,
            ),
            OutputSpec(
                name="normalizer",
                shape=ConcatShape(
                    parts=(
                        ShapePrefix(argument="left", trailing_rank=3),
                        ShapeTuple(
                            dimensions=(
                                DimRef(argument="left", axis=-2),
                                DimRef(argument="right", axis=-2),
                            )
                        ),
                    )
                ),
                dtype=ConstantDType(value="float32"),
                device=DeviceRef(argument="left"),
                semantic_axes=("batch_prefix", "left_node", "right_node"),
                visible_in_facade=False,
                saved_for_backward=True,
            ),
        ),
        program_group=ProgramGroupSpec(
            nodes=(
                ProgramNodeSpec(
                    name="normalizer",
                    builder="kernels.pairformer.outer_product_mean.tilelang:build_normalizer_program",
                    symbol="mindclade_tilelang_outer_product_mean_normalizer_launch",
                    workspace_uses=(
                        WorkspaceUseSpec(
                            workspace="normalizer", access=WorkspaceAccess.WRITE
                        ),
                    ),
                ),
                ProgramNodeSpec(
                    name="numerator",
                    builder="kernels.pairformer.outer_product_mean.tilelang:build_numerator_program",
                    symbol="mindclade_tilelang_outer_product_mean_numerator_launch",
                    depends_on=("normalizer",),
                    workspace_uses=(
                        WorkspaceUseSpec(
                            workspace="normalizer", access=WorkspaceAccess.READ
                        ),
                    ),
                ),
            ),
            workspaces=(
                WorkspaceSpec(
                    name="normalizer",
                    shape=ConcatShape(
                        parts=(
                            ShapePrefix(argument="left", trailing_rank=3),
                            ShapeTuple(
                                dimensions=(
                                    DimRef(argument="left", axis=-2),
                                    DimRef(argument="right", axis=-2),
                                )
                            ),
                        )
                    ),
                    dtype=ConstantDType(value="float32"),
                ),
            ),
        ),
    ),
    backward=BackwardSpec(
        schema=(
            "_outer_product_mean_bwd(Tensor grad_output, Tensor left, Tensor right, "
            "Tensor mask, float epsilon, Tensor output, Tensor normalizer, "
            "bool need_left_grad, bool need_right_grad, bool need_mask_grad) "
            "-> (Tensor? grad_left, Tensor? grad_right, Tensor? grad_mask)"
        ),
        builder="kernels.pairformer.outer_product_mean.tilelang:build_backward_program_group",
        symbol="mindclade_tilelang_outer_product_mean_bwd_launch",
        argument_bindings=(
            BackwardArgumentBinding(provider_argument="grad_output", source=BackwardArgumentSource.OUTPUT_GRADIENT, source_name="output", missing=MissingGradientPolicy.ERROR),
            BackwardArgumentBinding(provider_argument="left", source=BackwardArgumentSource.OPERATOR_ARGUMENT, source_name="left"),
            BackwardArgumentBinding(provider_argument="right", source=BackwardArgumentSource.OPERATOR_ARGUMENT, source_name="right"),
            BackwardArgumentBinding(provider_argument="mask", source=BackwardArgumentSource.OPERATOR_ARGUMENT, source_name="mask"),
            BackwardArgumentBinding(provider_argument="epsilon", source=BackwardArgumentSource.OPERATOR_ARGUMENT, source_name="epsilon"),
            BackwardArgumentBinding(provider_argument="output", source=BackwardArgumentSource.FORWARD_OUTPUT, source_name="output"),
            BackwardArgumentBinding(provider_argument="normalizer", source=BackwardArgumentSource.FORWARD_OUTPUT, source_name="normalizer"),
            BackwardArgumentBinding(provider_argument="need_left_grad", source=BackwardArgumentSource.NEEDS_INPUT_GRAD, source_name="left"),
            BackwardArgumentBinding(provider_argument="need_right_grad", source=BackwardArgumentSource.NEEDS_INPUT_GRAD, source_name="right"),
            BackwardArgumentBinding(provider_argument="need_mask_grad", source=BackwardArgumentSource.NEEDS_INPUT_GRAD, source_name="mask"),
        ),
        gradients=(
            GradientSpec(input_name="left", output_name="grad_left", optional=True, accumulation_dtype="float32"),
            GradientSpec(input_name="right", output_name="grad_right", optional=True, accumulation_dtype="float32"),
            GradientSpec(input_name="mask", output_name="grad_mask", optional=True, accumulation_dtype="float32"),
        ),
        supports_double_backward=False,
        program_group=ProgramGroupSpec(
            nodes=(
                ProgramNodeSpec(name="dleft", builder="kernels.pairformer.outer_product_mean.tilelang:build_dleft_program", symbol="mindclade_tilelang_outer_product_mean_dleft_launch"),
                ProgramNodeSpec(name="dright", builder="kernels.pairformer.outer_product_mean.tilelang:build_dright_program", symbol="mindclade_tilelang_outer_product_mean_dright_launch"),
                ProgramNodeSpec(name="dmask", builder="kernels.pairformer.outer_product_mean.tilelang:build_dmask_program", symbol="mindclade_tilelang_outer_product_mean_dmask_launch"),
            )
        ),
    ),
    autograd_policy=AutogradPolicy.REQUIRED,
    effects=EffectSpec(),
    launch=LaunchContract(
        current_stream_only=True,
        global_synchronization=False,
        hidden_device_allocation=True,
        graph_capture_safe=False,
        determinism=DeterminismClass.DETERMINISTIC,
    ),
)


IMPLEMENTATION_SPECS = (
    ImplementationSpec(
        operation="outer_product_mean",
        name="outer_product_mean_sm90a_fp16_b1_s64_n32_c64",
        family="pairformer",
        backend="tilelang",
        builder="kernels.pairformer.outer_product_mean.tilelang:build_forward_program_group",
        version=1,
        tier=ImplementationTier.SPECIALIZED,
        requires=("cuda", "sm90a", "tilelang-0.1.13"),
        envelope=CapabilityEnvelope(
            architectures=("sm90a",), dtypes=("float16",), layouts=("contiguous",), modes=("b1_s64_n32_c64",),
            constraints=(
                DimensionConstraint(predicate=And(operands=(Eq(lhs=RankRef(argument="left"), rhs=IntLiteral(value=4)), Eq(lhs=RankRef(argument="right"), rhs=IntLiteral(value=4)), Eq(lhs=RankRef(argument="mask"), rhs=IntLiteral(value=3)), Eq(lhs=DimRef(argument="left", axis=0), rhs=IntLiteral(value=1)), Eq(lhs=DimRef(argument="left", axis=1), rhs=IntLiteral(value=64)), Eq(lhs=DimRef(argument="left", axis=2), rhs=IntLiteral(value=32)), Eq(lhs=DimRef(argument="left", axis=3), rhs=IntLiteral(value=64)), Eq(lhs=DimRef(argument="right", axis=0), rhs=IntLiteral(value=1)), Eq(lhs=DimRef(argument="right", axis=1), rhs=IntLiteral(value=64)), Eq(lhs=DimRef(argument="right", axis=2), rhs=IntLiteral(value=32)), Eq(lhs=DimRef(argument="right", axis=3), rhs=IntLiteral(value=64)), Eq(lhs=DimRef(argument="mask", axis=0), rhs=IntLiteral(value=1)), Eq(lhs=DimRef(argument="mask", axis=1), rhs=IntLiteral(value=64)), Eq(lhs=DimRef(argument="mask", axis=2), rhs=IntLiteral(value=32)))), code="EXACT_B1_S64_N32_C64", message="requires exact [1,64,32,64] operands and [1,64,32] mask"),
                DimensionConstraint(predicate=IsFinite(value=ScalarRef(argument="epsilon", value_type=ScalarType.FLOAT)), code="EPSILON_FINITE", message="epsilon must be finite"),
                DimensionConstraint(predicate=GreaterThan(lhs=ScalarRef(argument="epsilon", value_type=ScalarType.FLOAT), rhs=FloatLiteral(value=0.0)), code="EPSILON_POSITIVE", message="epsilon must be positive"),
            ),
            graph_capture_safe=False, training_capable=True,
            tensor_constraints=(
                TensorCapabilityConstraint(argument="left", dtypes=("float16",), layouts=("contiguous",), devices=("cuda",), ranks=(4,)),
                TensorCapabilityConstraint(argument="right", dtypes=("float16",), layouts=("contiguous",), devices=("cuda",), ranks=(4,)),
                TensorCapabilityConstraint(argument="mask", dtypes=("float16",), layouts=("contiguous",), devices=("cuda",), ranks=(3,)),
            ),
        ), priority=100,
    ),
    ImplementationSpec(
        operation="outer_product_mean",
        name="outer_product_mean_sm90a_bf16_b1_s64_n32_c64",
        family="pairformer", backend="tilelang",
        builder="kernels.pairformer.outer_product_mean.tilelang:build_forward_program_group",
        version=1, tier=ImplementationTier.SPECIALIZED,
        requires=("cuda", "sm90a", "tilelang-0.1.13"),
        envelope=CapabilityEnvelope(
            architectures=("sm90a",), dtypes=("bfloat16",), layouts=("contiguous",), modes=("b1_s64_n32_c64",),
            constraints=(
                DimensionConstraint(predicate=And(operands=(Eq(lhs=RankRef(argument="left"), rhs=IntLiteral(value=4)), Eq(lhs=RankRef(argument="right"), rhs=IntLiteral(value=4)), Eq(lhs=RankRef(argument="mask"), rhs=IntLiteral(value=3)), Eq(lhs=DimRef(argument="left", axis=0), rhs=IntLiteral(value=1)), Eq(lhs=DimRef(argument="left", axis=1), rhs=IntLiteral(value=64)), Eq(lhs=DimRef(argument="left", axis=2), rhs=IntLiteral(value=32)), Eq(lhs=DimRef(argument="left", axis=3), rhs=IntLiteral(value=64)), Eq(lhs=DimRef(argument="right", axis=0), rhs=IntLiteral(value=1)), Eq(lhs=DimRef(argument="right", axis=1), rhs=IntLiteral(value=64)), Eq(lhs=DimRef(argument="right", axis=2), rhs=IntLiteral(value=32)), Eq(lhs=DimRef(argument="right", axis=3), rhs=IntLiteral(value=64)), Eq(lhs=DimRef(argument="mask", axis=0), rhs=IntLiteral(value=1)), Eq(lhs=DimRef(argument="mask", axis=1), rhs=IntLiteral(value=64)), Eq(lhs=DimRef(argument="mask", axis=2), rhs=IntLiteral(value=32)))), code="EXACT_B1_S64_N32_C64", message="requires exact [1,64,32,64] operands and [1,64,32] mask"),
                DimensionConstraint(predicate=IsFinite(value=ScalarRef(argument="epsilon", value_type=ScalarType.FLOAT)), code="EPSILON_FINITE", message="epsilon must be finite"),
                DimensionConstraint(predicate=GreaterThan(lhs=ScalarRef(argument="epsilon", value_type=ScalarType.FLOAT), rhs=FloatLiteral(value=0.0)), code="EPSILON_POSITIVE", message="epsilon must be positive"),
            ), graph_capture_safe=False, training_capable=True,
            tensor_constraints=(TensorCapabilityConstraint(argument="left", dtypes=("bfloat16",), layouts=("contiguous",), devices=("cuda",), ranks=(4,)), TensorCapabilityConstraint(argument="right", dtypes=("bfloat16",), layouts=("contiguous",), devices=("cuda",), ranks=(4,)), TensorCapabilityConstraint(argument="mask", dtypes=("bfloat16",), layouts=("contiguous",), devices=("cuda",), ranks=(3,))),
        ), priority=100,
    ),
    ImplementationSpec(
        operation="outer_product_mean",
        name="outer_product_mean_sm100a_fp16_b1_s64_n32_c64",
        family="pairformer", backend="tilelang",
        builder="kernels.pairformer.outer_product_mean.tilelang:build_forward_program_group",
        version=1, tier=ImplementationTier.SPECIALIZED,
        requires=("cuda", "sm100a", "tilelang-0.1.13"),
        envelope=CapabilityEnvelope(
            architectures=("sm100a",), dtypes=("float16",), layouts=("contiguous",), modes=("b1_s64_n32_c64",),
            constraints=(
                DimensionConstraint(predicate=And(operands=(Eq(lhs=RankRef(argument="left"), rhs=IntLiteral(value=4)), Eq(lhs=RankRef(argument="right"), rhs=IntLiteral(value=4)), Eq(lhs=RankRef(argument="mask"), rhs=IntLiteral(value=3)), Eq(lhs=DimRef(argument="left", axis=0), rhs=IntLiteral(value=1)), Eq(lhs=DimRef(argument="left", axis=1), rhs=IntLiteral(value=64)), Eq(lhs=DimRef(argument="left", axis=2), rhs=IntLiteral(value=32)), Eq(lhs=DimRef(argument="left", axis=3), rhs=IntLiteral(value=64)), Eq(lhs=DimRef(argument="right", axis=0), rhs=IntLiteral(value=1)), Eq(lhs=DimRef(argument="right", axis=1), rhs=IntLiteral(value=64)), Eq(lhs=DimRef(argument="right", axis=2), rhs=IntLiteral(value=32)), Eq(lhs=DimRef(argument="right", axis=3), rhs=IntLiteral(value=64)), Eq(lhs=DimRef(argument="mask", axis=0), rhs=IntLiteral(value=1)), Eq(lhs=DimRef(argument="mask", axis=1), rhs=IntLiteral(value=64)), Eq(lhs=DimRef(argument="mask", axis=2), rhs=IntLiteral(value=32)))), code="EXACT_B1_S64_N32_C64", message="requires exact [1,64,32,64] operands and [1,64,32] mask"),
                DimensionConstraint(predicate=IsFinite(value=ScalarRef(argument="epsilon", value_type=ScalarType.FLOAT)), code="EPSILON_FINITE", message="epsilon must be finite"),
                DimensionConstraint(predicate=GreaterThan(lhs=ScalarRef(argument="epsilon", value_type=ScalarType.FLOAT), rhs=FloatLiteral(value=0.0)), code="EPSILON_POSITIVE", message="epsilon must be positive"),
            ), graph_capture_safe=False, training_capable=True,
            tensor_constraints=(TensorCapabilityConstraint(argument="left", dtypes=("float16",), layouts=("contiguous",), devices=("cuda",), ranks=(4,)), TensorCapabilityConstraint(argument="right", dtypes=("float16",), layouts=("contiguous",), devices=("cuda",), ranks=(4,)), TensorCapabilityConstraint(argument="mask", dtypes=("float16",), layouts=("contiguous",), devices=("cuda",), ranks=(3,))),
        ), priority=100,
    ),
    ImplementationSpec(
        operation="outer_product_mean",
        name="outer_product_mean_sm100a_bf16_b1_s64_n32_c64",
        family="pairformer", backend="tilelang",
        builder="kernels.pairformer.outer_product_mean.tilelang:build_forward_program_group",
        version=1, tier=ImplementationTier.SPECIALIZED,
        requires=("cuda", "sm100a", "tilelang-0.1.13"),
        envelope=CapabilityEnvelope(
            architectures=("sm100a",), dtypes=("bfloat16",), layouts=("contiguous",), modes=("b1_s64_n32_c64",),
            constraints=(
                DimensionConstraint(predicate=And(operands=(Eq(lhs=RankRef(argument="left"), rhs=IntLiteral(value=4)), Eq(lhs=RankRef(argument="right"), rhs=IntLiteral(value=4)), Eq(lhs=RankRef(argument="mask"), rhs=IntLiteral(value=3)), Eq(lhs=DimRef(argument="left", axis=0), rhs=IntLiteral(value=1)), Eq(lhs=DimRef(argument="left", axis=1), rhs=IntLiteral(value=64)), Eq(lhs=DimRef(argument="left", axis=2), rhs=IntLiteral(value=32)), Eq(lhs=DimRef(argument="left", axis=3), rhs=IntLiteral(value=64)), Eq(lhs=DimRef(argument="right", axis=0), rhs=IntLiteral(value=1)), Eq(lhs=DimRef(argument="right", axis=1), rhs=IntLiteral(value=64)), Eq(lhs=DimRef(argument="right", axis=2), rhs=IntLiteral(value=32)), Eq(lhs=DimRef(argument="right", axis=3), rhs=IntLiteral(value=64)), Eq(lhs=DimRef(argument="mask", axis=0), rhs=IntLiteral(value=1)), Eq(lhs=DimRef(argument="mask", axis=1), rhs=IntLiteral(value=64)), Eq(lhs=DimRef(argument="mask", axis=2), rhs=IntLiteral(value=32)))), code="EXACT_B1_S64_N32_C64", message="requires exact [1,64,32,64] operands and [1,64,32] mask"),
                DimensionConstraint(predicate=IsFinite(value=ScalarRef(argument="epsilon", value_type=ScalarType.FLOAT)), code="EPSILON_FINITE", message="epsilon must be finite"),
                DimensionConstraint(predicate=GreaterThan(lhs=ScalarRef(argument="epsilon", value_type=ScalarType.FLOAT), rhs=FloatLiteral(value=0.0)), code="EPSILON_POSITIVE", message="epsilon must be positive"),
            ), graph_capture_safe=False, training_capable=True,
            tensor_constraints=(TensorCapabilityConstraint(argument="left", dtypes=("bfloat16",), layouts=("contiguous",), devices=("cuda",), ranks=(4,)), TensorCapabilityConstraint(argument="right", dtypes=("bfloat16",), layouts=("contiguous",), devices=("cuda",), ranks=(4,)), TensorCapabilityConstraint(argument="mask", dtypes=("bfloat16",), layouts=("contiguous",), devices=("cuda",), ranks=(3,))),
        ), priority=100,
    ),
)
