"""Declarative native-training contract for Pairformer triangle attention."""

from kernels.api import (
    And,
    AutogradPolicy,
    BackwardArgumentBinding,
    BackwardArgumentSource,
    BackwardSpec,
    CapabilityEnvelope,
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
    InitializationSpec,
    IntLiteral,
    IsFinite,
    KernelSpec,
    LaunchContract,
    LessEqual,
    MissingGradientPolicy,
    Or,
    OutputSpec,
    ProgramGroupSpec,
    ProgramNodeSpec,
    RankRef,
    RoundUp,
    ScalarRef,
    ScalarType,
    ShapeOf,
    ShapeTuple,
    TensorCapabilityConstraint,
    WorkspaceAccess,
    WorkspaceSpec,
    WorkspaceUseSpec,
)


KERNEL_SPEC: KernelSpec = KernelSpec(
    name="triangle_attention",
    namespace="mindclade",
    family="pairformer",
    source="pairformer/triangle_attention/spec.py",
    operator_schema=(
        "triangle_attention(Tensor q, Tensor k, Tensor v, Tensor bias, "
        "Tensor mask, float scale) -> (Tensor output, Tensor lse)"
    ),
    facade_outputs=("output",),
    fake=None,
    forward=ForwardSpec(
        schema=(
            "_triangle_attention_fwd(Tensor q, Tensor k, Tensor v, Tensor bias, "
            "Tensor mask, float scale) -> (Tensor output, Tensor lse)"
        ),
        builder="kernels.pairformer.triangle_attention.tilelang:build_forward_program_group",
        symbol="mindclade_tilelang_triangle_attention_fwd_launch",
        outputs=(
            OutputSpec(
                name="output",
                shape=ShapeOf(argument="q"),
                dtype=DTypeRef(argument="q"),
                device=DeviceRef(argument="q"),
                semantic_axes=("batch", "pair_anchor", "query", "head", "channel"),
                visible_in_facade=True,
                saved_for_backward=True,
            ),
            OutputSpec(
                name="lse",
                shape=ShapeTuple(
                    dimensions=(
                        DimRef(argument="q", axis=0),
                        DimRef(argument="q", axis=1),
                        DimRef(argument="q", axis=3),
                        RoundUp(
                            value=DimRef(argument="q", axis=2),
                            multiple=IntLiteral(value=32),
                        ),
                    )
                ),
                dtype=ConstantDType(value="float32"),
                device=DeviceRef(argument="q"),
                semantic_axes=("batch", "pair_anchor", "head", "padded_query"),
                visible_in_facade=False,
                saved_for_backward=True,
                initialization=InitializationSpec(mode="negative_infinity"),
            ),
        ),
        program_group=ProgramGroupSpec(
            nodes=(
                ProgramNodeSpec(
                    name="forward",
                    builder="kernels.pairformer.triangle_attention.tilelang:build_forward_program",
                    symbol="mindclade_tilelang_triangle_attention_forward_raw",
                ),
            )
        ),
    ),
    backward=BackwardSpec(
        schema=(
            "_triangle_attention_bwd(Tensor grad_output, Tensor q, Tensor k, "
            "Tensor v, Tensor bias, Tensor mask, float scale, Tensor output, "
            "Tensor lse, bool need_q_grad, bool need_k_grad, bool need_v_grad, "
            "bool need_bias_grad) -> (Tensor? grad_q, Tensor? grad_k, "
            "Tensor? grad_v, Tensor? grad_bias)"
        ),
        builder="kernels.pairformer.triangle_attention.tilelang:build_backward_program_group",
        symbol="mindclade_tilelang_triangle_attention_bwd_launch",
        argument_bindings=(
            BackwardArgumentBinding(provider_argument="grad_output", source=BackwardArgumentSource.OUTPUT_GRADIENT, source_name="output", missing=MissingGradientPolicy.ERROR),
            BackwardArgumentBinding(provider_argument="q", source=BackwardArgumentSource.OPERATOR_ARGUMENT, source_name="q"),
            BackwardArgumentBinding(provider_argument="k", source=BackwardArgumentSource.OPERATOR_ARGUMENT, source_name="k"),
            BackwardArgumentBinding(provider_argument="v", source=BackwardArgumentSource.OPERATOR_ARGUMENT, source_name="v"),
            BackwardArgumentBinding(provider_argument="bias", source=BackwardArgumentSource.OPERATOR_ARGUMENT, source_name="bias"),
            BackwardArgumentBinding(provider_argument="mask", source=BackwardArgumentSource.OPERATOR_ARGUMENT, source_name="mask"),
            BackwardArgumentBinding(provider_argument="scale", source=BackwardArgumentSource.OPERATOR_ARGUMENT, source_name="scale"),
            BackwardArgumentBinding(provider_argument="output", source=BackwardArgumentSource.FORWARD_OUTPUT, source_name="output"),
            BackwardArgumentBinding(provider_argument="lse", source=BackwardArgumentSource.FORWARD_OUTPUT, source_name="lse"),
            BackwardArgumentBinding(provider_argument="need_q_grad", source=BackwardArgumentSource.NEEDS_INPUT_GRAD, source_name="q"),
            BackwardArgumentBinding(provider_argument="need_k_grad", source=BackwardArgumentSource.NEEDS_INPUT_GRAD, source_name="k"),
            BackwardArgumentBinding(provider_argument="need_v_grad", source=BackwardArgumentSource.NEEDS_INPUT_GRAD, source_name="v"),
            BackwardArgumentBinding(provider_argument="need_bias_grad", source=BackwardArgumentSource.NEEDS_INPUT_GRAD, source_name="bias"),
        ),
        gradients=(
            GradientSpec(input_name="q", output_name="grad_q", optional=True, accumulation_dtype="float32"),
            GradientSpec(input_name="k", output_name="grad_k", optional=True, accumulation_dtype="float32"),
            GradientSpec(input_name="v", output_name="grad_v", optional=True, accumulation_dtype="float32"),
            GradientSpec(input_name="bias", output_name="grad_bias", optional=True, accumulation_dtype="float32"),
        ),
        supports_double_backward=False,
        program_group=ProgramGroupSpec(
            nodes=(
                ProgramNodeSpec(
                    name="delta",
                    builder="kernels.pairformer.triangle_attention.tilelang:build_delta",
                    symbol="mindclade_tilelang_triangle_attention_delta_raw",
                    workspace_uses=(WorkspaceUseSpec(workspace="delta", access=WorkspaceAccess.WRITE),),
                ),
                ProgramNodeSpec(
                    name="dbias",
                    builder="kernels.pairformer.triangle_attention.tilelang:build_dbias",
                    symbol="mindclade_tilelang_triangle_attention_dbias_raw",
                    depends_on=("delta",),
                    workspace_uses=(WorkspaceUseSpec(workspace="delta", access=WorkspaceAccess.READ),),
                ),
                ProgramNodeSpec(
                    name="dkv",
                    builder="kernels.pairformer.triangle_attention.tilelang:build_dkv",
                    symbol="mindclade_tilelang_triangle_attention_dkv_raw",
                    depends_on=("delta",),
                    workspace_uses=(WorkspaceUseSpec(workspace="delta", access=WorkspaceAccess.READ),),
                ),
                ProgramNodeSpec(
                    name="dq",
                    builder="kernels.pairformer.triangle_attention.tilelang:build_dq",
                    symbol="mindclade_tilelang_triangle_attention_dq_raw",
                    depends_on=("delta",),
                    workspace_uses=(WorkspaceUseSpec(workspace="delta", access=WorkspaceAccess.READ),),
                ),
            ),
            workspaces=(
                WorkspaceSpec(
                    name="delta",
                    shape=ShapeTuple(
                        dimensions=(
                            DimRef(argument="q", axis=0),
                            DimRef(argument="q", axis=1),
                            DimRef(argument="q", axis=3),
                            RoundUp(
                                value=DimRef(argument="q", axis=2),
                                multiple=IntLiteral(value=32),
                            ),
                        )
                    ),
                    dtype=ConstantDType(value="float32"),
                    zero_initialize=False,
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
        operation="triangle_attention",
        name="triangle_attention_sm90a_fp16_online_v1",
        family="pairformer",
        backend="tilelang",
        builder="kernels.pairformer.triangle_attention.tilelang:build_forward_program_group",
        version=1,
        tier=ImplementationTier.OPTIMIZED,
        requires=("cuda", "sm90a", "tilelang-0.1.13", "online-softmax"),
        envelope=CapabilityEnvelope(
            architectures=("sm90a",), dtypes=("float16",), layouts=("contiguous",), modes=("default",),
            constraints=(
                DimensionConstraint(predicate=And(operands=(Eq(lhs=RankRef(argument="q"), rhs=IntLiteral(value=5)), Eq(lhs=RankRef(argument="k"), rhs=IntLiteral(value=5)), Eq(lhs=RankRef(argument="v"), rhs=IntLiteral(value=5)), Eq(lhs=RankRef(argument="bias"), rhs=IntLiteral(value=5)), Eq(lhs=RankRef(argument="mask"), rhs=IntLiteral(value=3)), GreaterThan(lhs=DimRef(argument="q", axis=0), rhs=IntLiteral(value=0)), LessEqual(lhs=DimRef(argument="q", axis=0), rhs=IntLiteral(value=2)), GreaterThan(lhs=DimRef(argument="q", axis=1), rhs=IntLiteral(value=0)), LessEqual(lhs=DimRef(argument="q", axis=1), rhs=IntLiteral(value=128)), Eq(lhs=DimRef(argument="q", axis=2), rhs=DimRef(argument="q", axis=1)), GreaterThan(lhs=DimRef(argument="q", axis=3), rhs=IntLiteral(value=0)), LessEqual(lhs=DimRef(argument="q", axis=3), rhs=IntLiteral(value=8)), Or(operands=(Eq(lhs=DimRef(argument="q", axis=4), rhs=IntLiteral(value=32)), Eq(lhs=DimRef(argument="q", axis=4), rhs=IntLiteral(value=64)))), Eq(lhs=DimRef(argument="k", axis=0), rhs=DimRef(argument="q", axis=0)), Eq(lhs=DimRef(argument="k", axis=1), rhs=DimRef(argument="q", axis=1)), Eq(lhs=DimRef(argument="k", axis=2), rhs=DimRef(argument="q", axis=2)), Eq(lhs=DimRef(argument="k", axis=3), rhs=DimRef(argument="q", axis=3)), Eq(lhs=DimRef(argument="k", axis=4), rhs=DimRef(argument="q", axis=4)), Eq(lhs=DimRef(argument="v", axis=0), rhs=DimRef(argument="q", axis=0)), Eq(lhs=DimRef(argument="v", axis=1), rhs=DimRef(argument="q", axis=1)), Eq(lhs=DimRef(argument="v", axis=2), rhs=DimRef(argument="q", axis=2)), Eq(lhs=DimRef(argument="v", axis=3), rhs=DimRef(argument="q", axis=3)), Eq(lhs=DimRef(argument="v", axis=4), rhs=DimRef(argument="q", axis=4)), Eq(lhs=DimRef(argument="bias", axis=0), rhs=DimRef(argument="q", axis=0)), Eq(lhs=DimRef(argument="bias", axis=1), rhs=DimRef(argument="q", axis=1)), Eq(lhs=DimRef(argument="bias", axis=2), rhs=DimRef(argument="q", axis=3)), Eq(lhs=DimRef(argument="bias", axis=3), rhs=DimRef(argument="q", axis=2)), Eq(lhs=DimRef(argument="bias", axis=4), rhs=DimRef(argument="q", axis=2)), Eq(lhs=DimRef(argument="mask", axis=0), rhs=DimRef(argument="q", axis=0)), Eq(lhs=DimRef(argument="mask", axis=1), rhs=DimRef(argument="q", axis=1)), Eq(lhs=DimRef(argument="mask", axis=2), rhs=DimRef(argument="q", axis=2)))), code="TRIANGLE_ATTENTION_SHAPES", message="requires dense B,N,N,H,D attention with B<=2, N<=128, H<=8, and D in {32,64}"),
                DimensionConstraint(predicate=IsFinite(value=ScalarRef(argument="scale", value_type=ScalarType.FLOAT)), code="SCALE_FINITE", message="scale must be finite"),
            ), graph_capture_safe=False, training_capable=True,
            tensor_constraints=(TensorCapabilityConstraint(argument="q", dtypes=("float16",), layouts=("contiguous",), devices=("cuda",), ranks=(5,)), TensorCapabilityConstraint(argument="k", dtypes=("float16",), layouts=("contiguous",), devices=("cuda",), ranks=(5,)), TensorCapabilityConstraint(argument="v", dtypes=("float16",), layouts=("contiguous",), devices=("cuda",), ranks=(5,)), TensorCapabilityConstraint(argument="bias", dtypes=("float16",), layouts=("contiguous",), devices=("cuda",), ranks=(5,)), TensorCapabilityConstraint(argument="mask", dtypes=("bool",), layouts=("contiguous",), devices=("cuda",), ranks=(3,))),
        ), priority=100,
    ),
    ImplementationSpec(
        operation="triangle_attention", name="triangle_attention_sm90a_bf16_online_v1", family="pairformer", backend="tilelang", builder="kernels.pairformer.triangle_attention.tilelang:build_forward_program_group", version=1, tier=ImplementationTier.OPTIMIZED, requires=("cuda", "sm90a", "tilelang-0.1.13", "online-softmax"),
        envelope=CapabilityEnvelope(
            architectures=("sm90a",), dtypes=("bfloat16",), layouts=("contiguous",), modes=("default",),
            constraints=(DimensionConstraint(predicate=And(operands=(Eq(lhs=RankRef(argument="q"), rhs=IntLiteral(value=5)), Eq(lhs=RankRef(argument="k"), rhs=IntLiteral(value=5)), Eq(lhs=RankRef(argument="v"), rhs=IntLiteral(value=5)), Eq(lhs=RankRef(argument="bias"), rhs=IntLiteral(value=5)), Eq(lhs=RankRef(argument="mask"), rhs=IntLiteral(value=3)), GreaterThan(lhs=DimRef(argument="q", axis=0), rhs=IntLiteral(value=0)), LessEqual(lhs=DimRef(argument="q", axis=0), rhs=IntLiteral(value=2)), GreaterThan(lhs=DimRef(argument="q", axis=1), rhs=IntLiteral(value=0)), LessEqual(lhs=DimRef(argument="q", axis=1), rhs=IntLiteral(value=128)), Eq(lhs=DimRef(argument="q", axis=2), rhs=DimRef(argument="q", axis=1)), GreaterThan(lhs=DimRef(argument="q", axis=3), rhs=IntLiteral(value=0)), LessEqual(lhs=DimRef(argument="q", axis=3), rhs=IntLiteral(value=8)), Or(operands=(Eq(lhs=DimRef(argument="q", axis=4), rhs=IntLiteral(value=32)), Eq(lhs=DimRef(argument="q", axis=4), rhs=IntLiteral(value=64)))), Eq(lhs=DimRef(argument="k", axis=0), rhs=DimRef(argument="q", axis=0)), Eq(lhs=DimRef(argument="k", axis=1), rhs=DimRef(argument="q", axis=1)), Eq(lhs=DimRef(argument="k", axis=2), rhs=DimRef(argument="q", axis=2)), Eq(lhs=DimRef(argument="k", axis=3), rhs=DimRef(argument="q", axis=3)), Eq(lhs=DimRef(argument="k", axis=4), rhs=DimRef(argument="q", axis=4)), Eq(lhs=DimRef(argument="v", axis=0), rhs=DimRef(argument="q", axis=0)), Eq(lhs=DimRef(argument="v", axis=1), rhs=DimRef(argument="q", axis=1)), Eq(lhs=DimRef(argument="v", axis=2), rhs=DimRef(argument="q", axis=2)), Eq(lhs=DimRef(argument="v", axis=3), rhs=DimRef(argument="q", axis=3)), Eq(lhs=DimRef(argument="v", axis=4), rhs=DimRef(argument="q", axis=4)), Eq(lhs=DimRef(argument="bias", axis=0), rhs=DimRef(argument="q", axis=0)), Eq(lhs=DimRef(argument="bias", axis=1), rhs=DimRef(argument="q", axis=1)), Eq(lhs=DimRef(argument="bias", axis=2), rhs=DimRef(argument="q", axis=3)), Eq(lhs=DimRef(argument="bias", axis=3), rhs=DimRef(argument="q", axis=2)), Eq(lhs=DimRef(argument="bias", axis=4), rhs=DimRef(argument="q", axis=2)), Eq(lhs=DimRef(argument="mask", axis=0), rhs=DimRef(argument="q", axis=0)), Eq(lhs=DimRef(argument="mask", axis=1), rhs=DimRef(argument="q", axis=1)), Eq(lhs=DimRef(argument="mask", axis=2), rhs=DimRef(argument="q", axis=2)))), code="TRIANGLE_ATTENTION_SHAPES", message="requires dense B,N,N,H,D attention with B<=2, N<=128, H<=8, and D in {32,64}"), DimensionConstraint(predicate=IsFinite(value=ScalarRef(argument="scale", value_type=ScalarType.FLOAT)), code="SCALE_FINITE", message="scale must be finite")), graph_capture_safe=False, training_capable=True,
            tensor_constraints=(TensorCapabilityConstraint(argument="q", dtypes=("bfloat16",), layouts=("contiguous",), devices=("cuda",), ranks=(5,)), TensorCapabilityConstraint(argument="k", dtypes=("bfloat16",), layouts=("contiguous",), devices=("cuda",), ranks=(5,)), TensorCapabilityConstraint(argument="v", dtypes=("bfloat16",), layouts=("contiguous",), devices=("cuda",), ranks=(5,)), TensorCapabilityConstraint(argument="bias", dtypes=("bfloat16",), layouts=("contiguous",), devices=("cuda",), ranks=(5,)), TensorCapabilityConstraint(argument="mask", dtypes=("bool",), layouts=("contiguous",), devices=("cuda",), ranks=(3,))),
        ), priority=100,
    ),
    ImplementationSpec(
        operation="triangle_attention", name="triangle_attention_sm100a_fp16_online_v1", family="pairformer", backend="tilelang", builder="kernels.pairformer.triangle_attention.tilelang:build_forward_program_group", version=1, tier=ImplementationTier.OPTIMIZED, requires=("cuda", "sm100a", "tilelang-0.1.13", "online-softmax"),
        envelope=CapabilityEnvelope(
            architectures=("sm100a",), dtypes=("float16",), layouts=("contiguous",), modes=("default",),
            constraints=(DimensionConstraint(predicate=And(operands=(Eq(lhs=RankRef(argument="q"), rhs=IntLiteral(value=5)), Eq(lhs=RankRef(argument="k"), rhs=IntLiteral(value=5)), Eq(lhs=RankRef(argument="v"), rhs=IntLiteral(value=5)), Eq(lhs=RankRef(argument="bias"), rhs=IntLiteral(value=5)), Eq(lhs=RankRef(argument="mask"), rhs=IntLiteral(value=3)), GreaterThan(lhs=DimRef(argument="q", axis=0), rhs=IntLiteral(value=0)), LessEqual(lhs=DimRef(argument="q", axis=0), rhs=IntLiteral(value=2)), GreaterThan(lhs=DimRef(argument="q", axis=1), rhs=IntLiteral(value=0)), LessEqual(lhs=DimRef(argument="q", axis=1), rhs=IntLiteral(value=128)), Eq(lhs=DimRef(argument="q", axis=2), rhs=DimRef(argument="q", axis=1)), GreaterThan(lhs=DimRef(argument="q", axis=3), rhs=IntLiteral(value=0)), LessEqual(lhs=DimRef(argument="q", axis=3), rhs=IntLiteral(value=8)), Or(operands=(Eq(lhs=DimRef(argument="q", axis=4), rhs=IntLiteral(value=32)), Eq(lhs=DimRef(argument="q", axis=4), rhs=IntLiteral(value=64)))), Eq(lhs=DimRef(argument="k", axis=0), rhs=DimRef(argument="q", axis=0)), Eq(lhs=DimRef(argument="k", axis=1), rhs=DimRef(argument="q", axis=1)), Eq(lhs=DimRef(argument="k", axis=2), rhs=DimRef(argument="q", axis=2)), Eq(lhs=DimRef(argument="k", axis=3), rhs=DimRef(argument="q", axis=3)), Eq(lhs=DimRef(argument="k", axis=4), rhs=DimRef(argument="q", axis=4)), Eq(lhs=DimRef(argument="v", axis=0), rhs=DimRef(argument="q", axis=0)), Eq(lhs=DimRef(argument="v", axis=1), rhs=DimRef(argument="q", axis=1)), Eq(lhs=DimRef(argument="v", axis=2), rhs=DimRef(argument="q", axis=2)), Eq(lhs=DimRef(argument="v", axis=3), rhs=DimRef(argument="q", axis=3)), Eq(lhs=DimRef(argument="v", axis=4), rhs=DimRef(argument="q", axis=4)), Eq(lhs=DimRef(argument="bias", axis=0), rhs=DimRef(argument="q", axis=0)), Eq(lhs=DimRef(argument="bias", axis=1), rhs=DimRef(argument="q", axis=1)), Eq(lhs=DimRef(argument="bias", axis=2), rhs=DimRef(argument="q", axis=3)), Eq(lhs=DimRef(argument="bias", axis=3), rhs=DimRef(argument="q", axis=2)), Eq(lhs=DimRef(argument="bias", axis=4), rhs=DimRef(argument="q", axis=2)), Eq(lhs=DimRef(argument="mask", axis=0), rhs=DimRef(argument="q", axis=0)), Eq(lhs=DimRef(argument="mask", axis=1), rhs=DimRef(argument="q", axis=1)), Eq(lhs=DimRef(argument="mask", axis=2), rhs=DimRef(argument="q", axis=2)))), code="TRIANGLE_ATTENTION_SHAPES", message="requires dense B,N,N,H,D attention with B<=2, N<=128, H<=8, and D in {32,64}"), DimensionConstraint(predicate=IsFinite(value=ScalarRef(argument="scale", value_type=ScalarType.FLOAT)), code="SCALE_FINITE", message="scale must be finite")), graph_capture_safe=False, training_capable=True,
            tensor_constraints=(TensorCapabilityConstraint(argument="q", dtypes=("float16",), layouts=("contiguous",), devices=("cuda",), ranks=(5,)), TensorCapabilityConstraint(argument="k", dtypes=("float16",), layouts=("contiguous",), devices=("cuda",), ranks=(5,)), TensorCapabilityConstraint(argument="v", dtypes=("float16",), layouts=("contiguous",), devices=("cuda",), ranks=(5,)), TensorCapabilityConstraint(argument="bias", dtypes=("float16",), layouts=("contiguous",), devices=("cuda",), ranks=(5,)), TensorCapabilityConstraint(argument="mask", dtypes=("bool",), layouts=("contiguous",), devices=("cuda",), ranks=(3,))),
        ), priority=100,
    ),
    ImplementationSpec(
        operation="triangle_attention", name="triangle_attention_sm100a_bf16_online_v1", family="pairformer", backend="tilelang", builder="kernels.pairformer.triangle_attention.tilelang:build_forward_program_group", version=1, tier=ImplementationTier.OPTIMIZED, requires=("cuda", "sm100a", "tilelang-0.1.13", "online-softmax"),
        envelope=CapabilityEnvelope(
            architectures=("sm100a",), dtypes=("bfloat16",), layouts=("contiguous",), modes=("default",),
            constraints=(DimensionConstraint(predicate=And(operands=(Eq(lhs=RankRef(argument="q"), rhs=IntLiteral(value=5)), Eq(lhs=RankRef(argument="k"), rhs=IntLiteral(value=5)), Eq(lhs=RankRef(argument="v"), rhs=IntLiteral(value=5)), Eq(lhs=RankRef(argument="bias"), rhs=IntLiteral(value=5)), Eq(lhs=RankRef(argument="mask"), rhs=IntLiteral(value=3)), GreaterThan(lhs=DimRef(argument="q", axis=0), rhs=IntLiteral(value=0)), LessEqual(lhs=DimRef(argument="q", axis=0), rhs=IntLiteral(value=2)), GreaterThan(lhs=DimRef(argument="q", axis=1), rhs=IntLiteral(value=0)), LessEqual(lhs=DimRef(argument="q", axis=1), rhs=IntLiteral(value=128)), Eq(lhs=DimRef(argument="q", axis=2), rhs=DimRef(argument="q", axis=1)), GreaterThan(lhs=DimRef(argument="q", axis=3), rhs=IntLiteral(value=0)), LessEqual(lhs=DimRef(argument="q", axis=3), rhs=IntLiteral(value=8)), Or(operands=(Eq(lhs=DimRef(argument="q", axis=4), rhs=IntLiteral(value=32)), Eq(lhs=DimRef(argument="q", axis=4), rhs=IntLiteral(value=64)))), Eq(lhs=DimRef(argument="k", axis=0), rhs=DimRef(argument="q", axis=0)), Eq(lhs=DimRef(argument="k", axis=1), rhs=DimRef(argument="q", axis=1)), Eq(lhs=DimRef(argument="k", axis=2), rhs=DimRef(argument="q", axis=2)), Eq(lhs=DimRef(argument="k", axis=3), rhs=DimRef(argument="q", axis=3)), Eq(lhs=DimRef(argument="k", axis=4), rhs=DimRef(argument="q", axis=4)), Eq(lhs=DimRef(argument="v", axis=0), rhs=DimRef(argument="q", axis=0)), Eq(lhs=DimRef(argument="v", axis=1), rhs=DimRef(argument="q", axis=1)), Eq(lhs=DimRef(argument="v", axis=2), rhs=DimRef(argument="q", axis=2)), Eq(lhs=DimRef(argument="v", axis=3), rhs=DimRef(argument="q", axis=3)), Eq(lhs=DimRef(argument="v", axis=4), rhs=DimRef(argument="q", axis=4)), Eq(lhs=DimRef(argument="bias", axis=0), rhs=DimRef(argument="q", axis=0)), Eq(lhs=DimRef(argument="bias", axis=1), rhs=DimRef(argument="q", axis=1)), Eq(lhs=DimRef(argument="bias", axis=2), rhs=DimRef(argument="q", axis=3)), Eq(lhs=DimRef(argument="bias", axis=3), rhs=DimRef(argument="q", axis=2)), Eq(lhs=DimRef(argument="bias", axis=4), rhs=DimRef(argument="q", axis=2)), Eq(lhs=DimRef(argument="mask", axis=0), rhs=DimRef(argument="q", axis=0)), Eq(lhs=DimRef(argument="mask", axis=1), rhs=DimRef(argument="q", axis=1)), Eq(lhs=DimRef(argument="mask", axis=2), rhs=DimRef(argument="q", axis=2)))), code="TRIANGLE_ATTENTION_SHAPES", message="requires dense B,N,N,H,D attention with B<=2, N<=128, H<=8, and D in {32,64}"), DimensionConstraint(predicate=IsFinite(value=ScalarRef(argument="scale", value_type=ScalarType.FLOAT)), code="SCALE_FINITE", message="scale must be finite")), graph_capture_safe=False, training_capable=True,
            tensor_constraints=(TensorCapabilityConstraint(argument="q", dtypes=("bfloat16",), layouts=("contiguous",), devices=("cuda",), ranks=(5,)), TensorCapabilityConstraint(argument="k", dtypes=("bfloat16",), layouts=("contiguous",), devices=("cuda",), ranks=(5,)), TensorCapabilityConstraint(argument="v", dtypes=("bfloat16",), layouts=("contiguous",), devices=("cuda",), ranks=(5,)), TensorCapabilityConstraint(argument="bias", dtypes=("bfloat16",), layouts=("contiguous",), devices=("cuda",), ranks=(5,)), TensorCapabilityConstraint(argument="mask", dtypes=("bool",), layouts=("contiguous",), devices=("cuda",), ranks=(3,))),
        ), priority=100,
    ),
)
