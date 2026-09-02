"""Declarative native contract for Pairformer pair-weighted average."""

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
    LessEqual,
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
    name="pair_weighted_average",
    namespace="mindclade",
    family="pairformer",
    source="pairformer/pair_weighted_average/spec.py",
    operator_schema=(
        "pair_weighted_average(Tensor value, Tensor weights, Tensor mask, "
        "float epsilon) -> (Tensor output, Tensor lse)"
    ),
    facade_outputs=("output",),
    fake=None,
    forward=ForwardSpec(
        schema=(
            "_pair_weighted_average_fwd(Tensor value, Tensor weights, Tensor mask, "
            "float epsilon) -> (Tensor output, Tensor lse)"
        ),
        builder="kernels.pairformer.pair_weighted_average.tilelang:build_forward_program_group",
        symbol="mindclade_tilelang_pair_weighted_average_fwd_launch",
        outputs=(
            OutputSpec(
                name="output",
                shape=ConcatShape(
                    parts=(
                        ShapePrefix(argument="value", trailing_rank=2),
                        ShapeTuple(
                            dimensions=(
                                DimRef(argument="value", axis=-2),
                                DimRef(argument="weights", axis=-1),
                                DimRef(argument="value", axis=-1),
                            )
                        ),
                    )
                ),
                dtype=DTypeRef(argument="value"),
                device=DeviceRef(argument="value"),
                semantic_axes=("batch_prefix", "destination", "head", "channel"),
                visible_in_facade=True,
                saved_for_backward=True,
            ),
            OutputSpec(
                name="lse",
                shape=ConcatShape(
                    parts=(
                        ShapePrefix(argument="value", trailing_rank=2),
                        ShapeTuple(
                            dimensions=(
                                DimRef(argument="value", axis=-2),
                                DimRef(argument="weights", axis=-1),
                            )
                        ),
                    )
                ),
                dtype=ConstantDType(value="float32"),
                device=DeviceRef(argument="value"),
                semantic_axes=("batch_prefix", "destination", "head"),
                visible_in_facade=False,
                saved_for_backward=True,
            ),
        ),
        program_group=ProgramGroupSpec(
            nodes=(
                ProgramNodeSpec(
                    name="online_forward",
                    builder="kernels.pairformer.pair_weighted_average.tilelang:build_online_forward_program",
                    symbol="mindclade_tilelang_pair_weighted_average_online_forward_launch",
                ),
            )
        ),
    ),
    backward=BackwardSpec(
        schema=(
            "_pair_weighted_average_bwd(Tensor grad_output, Tensor value, "
            "Tensor weights, Tensor mask, float epsilon, Tensor output, Tensor lse, "
            "bool need_value_grad, bool need_weights_grad) "
            "-> (Tensor? grad_value, Tensor? grad_weights)"
        ),
        builder="kernels.pairformer.pair_weighted_average.tilelang:build_backward_program_group",
        symbol="mindclade_tilelang_pair_weighted_average_bwd_launch",
        argument_bindings=(
            BackwardArgumentBinding(provider_argument="grad_output", source=BackwardArgumentSource.OUTPUT_GRADIENT, source_name="output", missing=MissingGradientPolicy.ERROR),
            BackwardArgumentBinding(provider_argument="value", source=BackwardArgumentSource.OPERATOR_ARGUMENT, source_name="value"),
            BackwardArgumentBinding(provider_argument="weights", source=BackwardArgumentSource.OPERATOR_ARGUMENT, source_name="weights"),
            BackwardArgumentBinding(provider_argument="mask", source=BackwardArgumentSource.OPERATOR_ARGUMENT, source_name="mask"),
            BackwardArgumentBinding(provider_argument="epsilon", source=BackwardArgumentSource.OPERATOR_ARGUMENT, source_name="epsilon"),
            BackwardArgumentBinding(provider_argument="output", source=BackwardArgumentSource.FORWARD_OUTPUT, source_name="output"),
            BackwardArgumentBinding(provider_argument="lse", source=BackwardArgumentSource.FORWARD_OUTPUT, source_name="lse"),
            BackwardArgumentBinding(provider_argument="need_value_grad", source=BackwardArgumentSource.NEEDS_INPUT_GRAD, source_name="value"),
            BackwardArgumentBinding(provider_argument="need_weights_grad", source=BackwardArgumentSource.NEEDS_INPUT_GRAD, source_name="weights"),
        ),
        gradients=(
            GradientSpec(input_name="value", output_name="grad_value", optional=True, accumulation_dtype="float32"),
            GradientSpec(input_name="weights", output_name="grad_weights", optional=True, accumulation_dtype="float32"),
        ),
        supports_double_backward=False,
        program_group=ProgramGroupSpec(
            nodes=(
                ProgramNodeSpec(
                    name="delta",
                    builder="kernels.pairformer.pair_weighted_average.tilelang:build_delta_program",
                    symbol="mindclade_tilelang_pair_weighted_average_delta_launch",
                    workspace_uses=(WorkspaceUseSpec(workspace="delta", access=WorkspaceAccess.WRITE),),
                ),
                ProgramNodeSpec(
                    name="dvalue",
                    builder="kernels.pairformer.pair_weighted_average.tilelang:build_dvalue_program",
                    symbol="mindclade_tilelang_pair_weighted_average_dvalue_launch",
                ),
                ProgramNodeSpec(
                    name="dweights",
                    builder="kernels.pairformer.pair_weighted_average.tilelang:build_dweights_program",
                    symbol="mindclade_tilelang_pair_weighted_average_dweights_launch",
                    depends_on=("delta",),
                    workspace_uses=(WorkspaceUseSpec(workspace="delta", access=WorkspaceAccess.READ),),
                ),
            ),
            workspaces=(
                WorkspaceSpec(
                    name="delta",
                    shape=ConcatShape(
                        parts=(
                            ShapePrefix(argument="value", trailing_rank=2),
                            ShapeTuple(dimensions=(DimRef(argument="value", axis=-2), DimRef(argument="weights", axis=-1))),
                        )
                    ),
                    dtype=ConstantDType(value="float32"),
                ),
            ),
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
        operation="pair_weighted_average",
        name="pair_weighted_average_sm90a_fp16",
        family="pairformer", backend="tilelang",
        builder="kernels.pairformer.pair_weighted_average.tilelang:build_forward_program_group",
        version=1, tier=ImplementationTier.OPTIMIZED,
        requires=("cuda", "sm90a", "tilelang-0.1.13"),
        envelope=CapabilityEnvelope(
            architectures=("sm90a",), dtypes=("float16",), layouts=("contiguous",), modes=("default",),
            constraints=(
                DimensionConstraint(predicate=And(operands=(Eq(lhs=RankRef(argument="value"), rhs=IntLiteral(value=3)), Eq(lhs=RankRef(argument="weights"), rhs=IntLiteral(value=4)), Eq(lhs=RankRef(argument="mask"), rhs=IntLiteral(value=2)), Eq(lhs=DimRef(argument="value", axis=0), rhs=DimRef(argument="weights", axis=0)), Eq(lhs=DimRef(argument="value", axis=0), rhs=DimRef(argument="mask", axis=0)), Eq(lhs=DimRef(argument="value", axis=1), rhs=DimRef(argument="weights", axis=1)), Eq(lhs=DimRef(argument="value", axis=1), rhs=DimRef(argument="weights", axis=2)), Eq(lhs=DimRef(argument="value", axis=1), rhs=DimRef(argument="mask", axis=1)))), code="SHAPE_RELATIONSHIPS", message="requires value [B,N,C], weights [B,N,N,H], and mask [B,N]"),
                DimensionConstraint(predicate=And(operands=(GreaterThan(lhs=DimRef(argument="value", axis=0), rhs=IntLiteral(value=0)), LessEqual(lhs=DimRef(argument="value", axis=0), rhs=IntLiteral(value=65535)), GreaterThan(lhs=DimRef(argument="value", axis=1), rhs=IntLiteral(value=0)), LessEqual(lhs=DimRef(argument="value", axis=1), rhs=IntLiteral(value=8192)), GreaterThan(lhs=DimRef(argument="value", axis=2), rhs=IntLiteral(value=0)), LessEqual(lhs=DimRef(argument="value", axis=2), rhs=IntLiteral(value=4096)), GreaterThan(lhs=DimRef(argument="weights", axis=3), rhs=IntLiteral(value=0)), LessEqual(lhs=DimRef(argument="weights", axis=3), rhs=IntLiteral(value=256)))), code="DIMENSION_LIMITS", message="dimensions exceed the compiled scalar-index envelope"),
                DimensionConstraint(predicate=IsFinite(value=ScalarRef(argument="epsilon", value_type=ScalarType.FLOAT)), code="EPSILON_FINITE", message="epsilon must be finite"),
                DimensionConstraint(predicate=GreaterThan(lhs=ScalarRef(argument="epsilon", value_type=ScalarType.FLOAT), rhs=FloatLiteral(value=0.0)), code="EPSILON_POSITIVE", message="epsilon must be positive"),
                DimensionConstraint(predicate=LessEqual(lhs=ScalarRef(argument="epsilon", value_type=ScalarType.FLOAT), rhs=FloatLiteral(value=1.0)), code="EPSILON_AT_MOST_ONE", message="native backward requires epsilon <= 1"),
            ), graph_capture_safe=False, training_capable=True,
            tensor_constraints=(TensorCapabilityConstraint(argument="value", dtypes=("float16",), layouts=("contiguous",), devices=("cuda",), ranks=(3,)), TensorCapabilityConstraint(argument="weights", dtypes=("float16",), layouts=("contiguous",), devices=("cuda",), ranks=(4,)), TensorCapabilityConstraint(argument="mask", dtypes=("float32",), layouts=("contiguous",), devices=("cuda",), ranks=(2,))),
        ), priority=100,
    ),
    ImplementationSpec(
        operation="pair_weighted_average", name="pair_weighted_average_sm90a_bf16", family="pairformer", backend="tilelang",
        builder="kernels.pairformer.pair_weighted_average.tilelang:build_forward_program_group", version=1, tier=ImplementationTier.OPTIMIZED,
        requires=("cuda", "sm90a", "tilelang-0.1.13"),
        envelope=CapabilityEnvelope(
            architectures=("sm90a",), dtypes=("bfloat16",), layouts=("contiguous",), modes=("default",),
            constraints=(
                DimensionConstraint(predicate=And(operands=(Eq(lhs=RankRef(argument="value"), rhs=IntLiteral(value=3)), Eq(lhs=RankRef(argument="weights"), rhs=IntLiteral(value=4)), Eq(lhs=RankRef(argument="mask"), rhs=IntLiteral(value=2)), Eq(lhs=DimRef(argument="value", axis=0), rhs=DimRef(argument="weights", axis=0)), Eq(lhs=DimRef(argument="value", axis=0), rhs=DimRef(argument="mask", axis=0)), Eq(lhs=DimRef(argument="value", axis=1), rhs=DimRef(argument="weights", axis=1)), Eq(lhs=DimRef(argument="value", axis=1), rhs=DimRef(argument="weights", axis=2)), Eq(lhs=DimRef(argument="value", axis=1), rhs=DimRef(argument="mask", axis=1)))), code="SHAPE_RELATIONSHIPS", message="requires value [B,N,C], weights [B,N,N,H], and mask [B,N]"),
                DimensionConstraint(predicate=And(operands=(GreaterThan(lhs=DimRef(argument="value", axis=0), rhs=IntLiteral(value=0)), LessEqual(lhs=DimRef(argument="value", axis=0), rhs=IntLiteral(value=65535)), GreaterThan(lhs=DimRef(argument="value", axis=1), rhs=IntLiteral(value=0)), LessEqual(lhs=DimRef(argument="value", axis=1), rhs=IntLiteral(value=8192)), GreaterThan(lhs=DimRef(argument="value", axis=2), rhs=IntLiteral(value=0)), LessEqual(lhs=DimRef(argument="value", axis=2), rhs=IntLiteral(value=4096)), GreaterThan(lhs=DimRef(argument="weights", axis=3), rhs=IntLiteral(value=0)), LessEqual(lhs=DimRef(argument="weights", axis=3), rhs=IntLiteral(value=256)))), code="DIMENSION_LIMITS", message="dimensions exceed the compiled scalar-index envelope"),
                DimensionConstraint(predicate=IsFinite(value=ScalarRef(argument="epsilon", value_type=ScalarType.FLOAT)), code="EPSILON_FINITE", message="epsilon must be finite"), DimensionConstraint(predicate=GreaterThan(lhs=ScalarRef(argument="epsilon", value_type=ScalarType.FLOAT), rhs=FloatLiteral(value=0.0)), code="EPSILON_POSITIVE", message="epsilon must be positive"), DimensionConstraint(predicate=LessEqual(lhs=ScalarRef(argument="epsilon", value_type=ScalarType.FLOAT), rhs=FloatLiteral(value=1.0)), code="EPSILON_AT_MOST_ONE", message="native backward requires epsilon <= 1"),
            ), graph_capture_safe=False, training_capable=True,
            tensor_constraints=(TensorCapabilityConstraint(argument="value", dtypes=("bfloat16",), layouts=("contiguous",), devices=("cuda",), ranks=(3,)), TensorCapabilityConstraint(argument="weights", dtypes=("bfloat16",), layouts=("contiguous",), devices=("cuda",), ranks=(4,)), TensorCapabilityConstraint(argument="mask", dtypes=("float32",), layouts=("contiguous",), devices=("cuda",), ranks=(2,))),
        ), priority=100,
    ),
    ImplementationSpec(
        operation="pair_weighted_average", name="pair_weighted_average_sm100a_fp16", family="pairformer", backend="tilelang",
        builder="kernels.pairformer.pair_weighted_average.tilelang:build_forward_program_group", version=1, tier=ImplementationTier.OPTIMIZED,
        requires=("cuda", "sm100a", "tilelang-0.1.13"),
        envelope=CapabilityEnvelope(
            architectures=("sm100a",), dtypes=("float16",), layouts=("contiguous",), modes=("default",),
            constraints=(
                DimensionConstraint(predicate=And(operands=(Eq(lhs=RankRef(argument="value"), rhs=IntLiteral(value=3)), Eq(lhs=RankRef(argument="weights"), rhs=IntLiteral(value=4)), Eq(lhs=RankRef(argument="mask"), rhs=IntLiteral(value=2)), Eq(lhs=DimRef(argument="value", axis=0), rhs=DimRef(argument="weights", axis=0)), Eq(lhs=DimRef(argument="value", axis=0), rhs=DimRef(argument="mask", axis=0)), Eq(lhs=DimRef(argument="value", axis=1), rhs=DimRef(argument="weights", axis=1)), Eq(lhs=DimRef(argument="value", axis=1), rhs=DimRef(argument="weights", axis=2)), Eq(lhs=DimRef(argument="value", axis=1), rhs=DimRef(argument="mask", axis=1)))), code="SHAPE_RELATIONSHIPS", message="requires value [B,N,C], weights [B,N,N,H], and mask [B,N]"),
                DimensionConstraint(predicate=And(operands=(GreaterThan(lhs=DimRef(argument="value", axis=0), rhs=IntLiteral(value=0)), LessEqual(lhs=DimRef(argument="value", axis=0), rhs=IntLiteral(value=65535)), GreaterThan(lhs=DimRef(argument="value", axis=1), rhs=IntLiteral(value=0)), LessEqual(lhs=DimRef(argument="value", axis=1), rhs=IntLiteral(value=8192)), GreaterThan(lhs=DimRef(argument="value", axis=2), rhs=IntLiteral(value=0)), LessEqual(lhs=DimRef(argument="value", axis=2), rhs=IntLiteral(value=4096)), GreaterThan(lhs=DimRef(argument="weights", axis=3), rhs=IntLiteral(value=0)), LessEqual(lhs=DimRef(argument="weights", axis=3), rhs=IntLiteral(value=256)))), code="DIMENSION_LIMITS", message="dimensions exceed the compiled scalar-index envelope"),
                DimensionConstraint(predicate=IsFinite(value=ScalarRef(argument="epsilon", value_type=ScalarType.FLOAT)), code="EPSILON_FINITE", message="epsilon must be finite"), DimensionConstraint(predicate=GreaterThan(lhs=ScalarRef(argument="epsilon", value_type=ScalarType.FLOAT), rhs=FloatLiteral(value=0.0)), code="EPSILON_POSITIVE", message="epsilon must be positive"), DimensionConstraint(predicate=LessEqual(lhs=ScalarRef(argument="epsilon", value_type=ScalarType.FLOAT), rhs=FloatLiteral(value=1.0)), code="EPSILON_AT_MOST_ONE", message="native backward requires epsilon <= 1"),
            ), graph_capture_safe=False, training_capable=True,
            tensor_constraints=(TensorCapabilityConstraint(argument="value", dtypes=("float16",), layouts=("contiguous",), devices=("cuda",), ranks=(3,)), TensorCapabilityConstraint(argument="weights", dtypes=("float16",), layouts=("contiguous",), devices=("cuda",), ranks=(4,)), TensorCapabilityConstraint(argument="mask", dtypes=("float32",), layouts=("contiguous",), devices=("cuda",), ranks=(2,))),
        ), priority=100,
    ),
    ImplementationSpec(
        operation="pair_weighted_average", name="pair_weighted_average_sm100a_bf16", family="pairformer", backend="tilelang",
        builder="kernels.pairformer.pair_weighted_average.tilelang:build_forward_program_group", version=1, tier=ImplementationTier.OPTIMIZED,
        requires=("cuda", "sm100a", "tilelang-0.1.13"),
        envelope=CapabilityEnvelope(
            architectures=("sm100a",), dtypes=("bfloat16",), layouts=("contiguous",), modes=("default",),
            constraints=(
                DimensionConstraint(predicate=And(operands=(Eq(lhs=RankRef(argument="value"), rhs=IntLiteral(value=3)), Eq(lhs=RankRef(argument="weights"), rhs=IntLiteral(value=4)), Eq(lhs=RankRef(argument="mask"), rhs=IntLiteral(value=2)), Eq(lhs=DimRef(argument="value", axis=0), rhs=DimRef(argument="weights", axis=0)), Eq(lhs=DimRef(argument="value", axis=0), rhs=DimRef(argument="mask", axis=0)), Eq(lhs=DimRef(argument="value", axis=1), rhs=DimRef(argument="weights", axis=1)), Eq(lhs=DimRef(argument="value", axis=1), rhs=DimRef(argument="weights", axis=2)), Eq(lhs=DimRef(argument="value", axis=1), rhs=DimRef(argument="mask", axis=1)))), code="SHAPE_RELATIONSHIPS", message="requires value [B,N,C], weights [B,N,N,H], and mask [B,N]"),
                DimensionConstraint(predicate=And(operands=(GreaterThan(lhs=DimRef(argument="value", axis=0), rhs=IntLiteral(value=0)), LessEqual(lhs=DimRef(argument="value", axis=0), rhs=IntLiteral(value=65535)), GreaterThan(lhs=DimRef(argument="value", axis=1), rhs=IntLiteral(value=0)), LessEqual(lhs=DimRef(argument="value", axis=1), rhs=IntLiteral(value=8192)), GreaterThan(lhs=DimRef(argument="value", axis=2), rhs=IntLiteral(value=0)), LessEqual(lhs=DimRef(argument="value", axis=2), rhs=IntLiteral(value=4096)), GreaterThan(lhs=DimRef(argument="weights", axis=3), rhs=IntLiteral(value=0)), LessEqual(lhs=DimRef(argument="weights", axis=3), rhs=IntLiteral(value=256)))), code="DIMENSION_LIMITS", message="dimensions exceed the compiled scalar-index envelope"),
                DimensionConstraint(predicate=IsFinite(value=ScalarRef(argument="epsilon", value_type=ScalarType.FLOAT)), code="EPSILON_FINITE", message="epsilon must be finite"), DimensionConstraint(predicate=GreaterThan(lhs=ScalarRef(argument="epsilon", value_type=ScalarType.FLOAT), rhs=FloatLiteral(value=0.0)), code="EPSILON_POSITIVE", message="epsilon must be positive"), DimensionConstraint(predicate=LessEqual(lhs=ScalarRef(argument="epsilon", value_type=ScalarType.FLOAT), rhs=FloatLiteral(value=1.0)), code="EPSILON_AT_MOST_ONE", message="native backward requires epsilon <= 1"),
            ), graph_capture_safe=False, training_capable=True,
            tensor_constraints=(TensorCapabilityConstraint(argument="value", dtypes=("bfloat16",), layouts=("contiguous",), devices=("cuda",), ranks=(3,)), TensorCapabilityConstraint(argument="weights", dtypes=("bfloat16",), layouts=("contiguous",), devices=("cuda",), ranks=(4,)), TensorCapabilityConstraint(argument="mask", dtypes=("float32",), layouts=("contiguous",), devices=("cuda",), ranks=(2,))),
        ), priority=100,
    ),
)
