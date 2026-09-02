"""Declarative native contract for Pairformer outer-product mean."""

from kernels.api import (
    RuntimeWorkloadSpec, WorkloadDimensionBinding,
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
    ProgramArtifactBoundary,
    ProgramBindingSource,
    ProgramBindingSpec,
    ProgramEntryABI,
    ProgramParameterKind,
    ProgramParameterSpec,
    ProgramReturnABI,
    ScalarABIType,
    ProgramNodeSpec,
    RankRef,
    ScalarRef,
    ScalarType,
    ShapePrefix,
    ShapeTuple,
    TensorCapabilityConstraint,
    WorkspaceAccess,
    ShapeOf,
    WorkspaceLifetime,
    WorkspaceSpec,
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
                name='normalizer',
                builder='kernels.pairformer.outer_product_mean.tilelang:build_normalizer_program',
                symbol='mindclade_tilelang_outer_product_mean_normalizer_launch',
                entry_symbol="call",
                entry_abi=ProgramEntryABI.TILELANG_0_1_13_HOST_CALL,
                parameters=(
                    ProgramParameterSpec(position=0, name='mask', kind=ProgramParameterKind.TENSOR, access=WorkspaceAccess.READ, shape=ShapeOf(argument='mask'), dtype=DTypeRef(argument='mask'), device=DeviceRef(argument='mask')),
                    ProgramParameterSpec(position=1, name='normalizer', kind=ProgramParameterKind.TENSOR, access=WorkspaceAccess.WRITE, shape=ConcatShape(parts=(ShapePrefix(argument="left", trailing_rank=3), ShapeTuple(dimensions=(DimRef(argument="left", axis=-2), DimRef(argument="right", axis=-2))))), dtype=ConstantDType(value="float32"), device=DeviceRef(argument='left')),
                    ProgramParameterSpec(position=2, name='stream', kind=ProgramParameterKind.STREAM, access=WorkspaceAccess.READ),
                ),
                bindings=(
                    ProgramBindingSpec(parameter='mask', source=ProgramBindingSource.OPERATOR_ARGUMENT, source_name='mask'),
                    ProgramBindingSpec(parameter='normalizer', source=ProgramBindingSource.PROVIDER_OUTPUT, source_name='normalizer'),
                    ProgramBindingSpec(parameter='stream', source=ProgramBindingSource.CURRENT_STREAM),
             
             
             
             
            )
            ,
                return_abi=ProgramReturnABI.STATUS_I32_ZERO_SUCCESS,
                artifact_boundary=ProgramArtifactBoundary.NODE_CONTENT_ADDRESSED_DSO,
            ),
            ProgramNodeSpec(
                name='numerator',
                builder='kernels.pairformer.outer_product_mean.tilelang:build_numerator_program',
                symbol='mindclade_tilelang_outer_product_mean_numerator_launch',
                entry_symbol="call",
                entry_abi=ProgramEntryABI.TILELANG_0_1_13_HOST_CALL,
                parameters=(
                    ProgramParameterSpec(position=0, name='left', kind=ProgramParameterKind.TENSOR, access=WorkspaceAccess.READ, shape=ShapeOf(argument='left'), dtype=DTypeRef(argument='left'), device=DeviceRef(argument='left')),
                    ProgramParameterSpec(position=1, name='right', kind=ProgramParameterKind.TENSOR, access=WorkspaceAccess.READ, shape=ShapeOf(argument='right'), dtype=DTypeRef(argument='right'), device=DeviceRef(argument='right')),
                    ProgramParameterSpec(position=2, name='mask', kind=ProgramParameterKind.TENSOR, access=WorkspaceAccess.READ, shape=ShapeOf(argument='mask'), dtype=DTypeRef(argument='mask'), device=DeviceRef(argument='mask')),
                    ProgramParameterSpec(position=3, name='epsilon', kind=ProgramParameterKind.SCALAR, access=WorkspaceAccess.READ, scalar_type=ScalarABIType.FLOAT64),
                    ProgramParameterSpec(position=4, name='normalizer', kind=ProgramParameterKind.TENSOR, access=WorkspaceAccess.READ, shape=ConcatShape(parts=(ShapePrefix(argument="left", trailing_rank=3), ShapeTuple(dimensions=(DimRef(argument="left", axis=-2), DimRef(argument="right", axis=-2))))), dtype=ConstantDType(value="float32"), device=DeviceRef(argument='left')),
                    ProgramParameterSpec(position=5, name='output', kind=ProgramParameterKind.TENSOR, access=WorkspaceAccess.WRITE, shape=ConcatShape(parts=(ShapePrefix(argument="left", trailing_rank=3), ShapeTuple(dimensions=(DimRef(argument="left", axis=-2), DimRef(argument="right", axis=-2), DimRef(argument="left", axis=-1), DimRef(argument="right", axis=-1))))), dtype=DTypeRef(argument='left'), device=DeviceRef(argument='left')),
                    ProgramParameterSpec(position=6, name='stream', kind=ProgramParameterKind.STREAM, access=WorkspaceAccess.READ),
                ),
                bindings=(
                    ProgramBindingSpec(parameter='left', source=ProgramBindingSource.OPERATOR_ARGUMENT, source_name='left'),
                    ProgramBindingSpec(parameter='right', source=ProgramBindingSource.OPERATOR_ARGUMENT, source_name='right'),
                    ProgramBindingSpec(parameter='mask', source=ProgramBindingSource.OPERATOR_ARGUMENT, source_name='mask'),
                    ProgramBindingSpec(parameter='epsilon', source=ProgramBindingSource.OPERATOR_ARGUMENT, source_name='epsilon'),
                    ProgramBindingSpec(parameter='normalizer', source=ProgramBindingSource.FORWARD_OUTPUT, source_name='normalizer'),
                    ProgramBindingSpec(parameter='output', source=ProgramBindingSource.PROVIDER_OUTPUT, source_name='output'),
                    ProgramBindingSpec(parameter='stream', source=ProgramBindingSource.CURRENT_STREAM),
             
             
             
             
            )
            ,
                depends_on=('normalizer',),
                return_abi=ProgramReturnABI.STATUS_I32_ZERO_SUCCESS,
                artifact_boundary=ProgramArtifactBoundary.NODE_CONTENT_ADDRESSED_DSO,
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
            GradientSpec(input_name="left", output_name="grad_left", shape=ShapeOf(argument="left"), dtype=DTypeRef(argument="left"), device=DeviceRef(argument="left"), optional=True, accumulation_dtype="float32"),
            GradientSpec(input_name="right", output_name="grad_right", shape=ShapeOf(argument="right"), dtype=DTypeRef(argument="right"), device=DeviceRef(argument="right"), optional=True, accumulation_dtype="float32"),
            GradientSpec(input_name="mask", output_name="grad_mask", shape=ShapeOf(argument="mask"), dtype=DTypeRef(argument="mask"), device=DeviceRef(argument="mask"), optional=True, accumulation_dtype="float32"),
        ),
        supports_double_backward=False,
        program_group=ProgramGroupSpec(
            nodes=(
            ProgramNodeSpec(
                name='dleft',
                builder='kernels.pairformer.outer_product_mean.tilelang:build_dleft_program',
                symbol='mindclade_tilelang_outer_product_mean_dleft_launch',
                entry_symbol="call",
                entry_abi=ProgramEntryABI.TILELANG_0_1_13_HOST_CALL,
                parameters=(
                    ProgramParameterSpec(position=0, name='grad_output', kind=ProgramParameterKind.TENSOR, access=WorkspaceAccess.READ, shape=ConcatShape(parts=(ShapePrefix(argument="left", trailing_rank=3), ShapeTuple(dimensions=(DimRef(argument="left", axis=-2), DimRef(argument="right", axis=-2), DimRef(argument="left", axis=-1), DimRef(argument="right", axis=-1))))), dtype=DTypeRef(argument='left'), device=DeviceRef(argument='left')),
                    ProgramParameterSpec(position=1, name='right', kind=ProgramParameterKind.TENSOR, access=WorkspaceAccess.READ, shape=ShapeOf(argument='right'), dtype=DTypeRef(argument='right'), device=DeviceRef(argument='right')),
                    ProgramParameterSpec(position=2, name='mask', kind=ProgramParameterKind.TENSOR, access=WorkspaceAccess.READ, shape=ShapeOf(argument='mask'), dtype=DTypeRef(argument='mask'), device=DeviceRef(argument='mask')),
                    ProgramParameterSpec(position=3, name='epsilon', kind=ProgramParameterKind.SCALAR, access=WorkspaceAccess.READ, scalar_type=ScalarABIType.FLOAT64),
                    ProgramParameterSpec(position=4, name='normalizer', kind=ProgramParameterKind.TENSOR, access=WorkspaceAccess.READ, shape=ConcatShape(parts=(ShapePrefix(argument="left", trailing_rank=3), ShapeTuple(dimensions=(DimRef(argument="left", axis=-2), DimRef(argument="right", axis=-2))))), dtype=ConstantDType(value="float32"), device=DeviceRef(argument='left')),
                    ProgramParameterSpec(position=5, name='grad_left', kind=ProgramParameterKind.TENSOR, access=WorkspaceAccess.WRITE, shape=ShapeOf(argument='left'), dtype=DTypeRef(argument='left'), device=DeviceRef(argument='left'), optional=True),
                    ProgramParameterSpec(position=6, name='need_left_grad', kind=ProgramParameterKind.SCALAR, access=WorkspaceAccess.READ, scalar_type=ScalarABIType.BOOL),
                    ProgramParameterSpec(position=7, name='stream', kind=ProgramParameterKind.STREAM, access=WorkspaceAccess.READ),
                ),
                bindings=(
                    ProgramBindingSpec(parameter='grad_output', source=ProgramBindingSource.OUTPUT_GRADIENT, source_name='output'),
                    ProgramBindingSpec(parameter='right', source=ProgramBindingSource.OPERATOR_ARGUMENT, source_name='right'),
                    ProgramBindingSpec(parameter='mask', source=ProgramBindingSource.OPERATOR_ARGUMENT, source_name='mask'),
                    ProgramBindingSpec(parameter='epsilon', source=ProgramBindingSource.OPERATOR_ARGUMENT, source_name='epsilon'),
                    ProgramBindingSpec(parameter='normalizer', source=ProgramBindingSource.FORWARD_OUTPUT, source_name='normalizer'),
                    ProgramBindingSpec(parameter='grad_left', source=ProgramBindingSource.PROVIDER_OUTPUT, source_name='grad_left'),
                    ProgramBindingSpec(parameter='need_left_grad', source=ProgramBindingSource.GRADIENT_REQUEST, source_name='left'),
                    ProgramBindingSpec(parameter='stream', source=ProgramBindingSource.CURRENT_STREAM),
             
             
             
             
            )
            ,
                return_abi=ProgramReturnABI.STATUS_I32_ZERO_SUCCESS,
                artifact_boundary=ProgramArtifactBoundary.NODE_CONTENT_ADDRESSED_DSO,
            ),
            ProgramNodeSpec(
                name='dright',
                builder='kernels.pairformer.outer_product_mean.tilelang:build_dright_program',
                symbol='mindclade_tilelang_outer_product_mean_dright_launch',
                entry_symbol="call",
                entry_abi=ProgramEntryABI.TILELANG_0_1_13_HOST_CALL,
                parameters=(
                    ProgramParameterSpec(position=0, name='grad_output', kind=ProgramParameterKind.TENSOR, access=WorkspaceAccess.READ, shape=ConcatShape(parts=(ShapePrefix(argument="left", trailing_rank=3), ShapeTuple(dimensions=(DimRef(argument="left", axis=-2), DimRef(argument="right", axis=-2), DimRef(argument="left", axis=-1), DimRef(argument="right", axis=-1))))), dtype=DTypeRef(argument='left'), device=DeviceRef(argument='left')),
                    ProgramParameterSpec(position=1, name='left', kind=ProgramParameterKind.TENSOR, access=WorkspaceAccess.READ, shape=ShapeOf(argument='left'), dtype=DTypeRef(argument='left'), device=DeviceRef(argument='left')),
                    ProgramParameterSpec(position=2, name='mask', kind=ProgramParameterKind.TENSOR, access=WorkspaceAccess.READ, shape=ShapeOf(argument='mask'), dtype=DTypeRef(argument='mask'), device=DeviceRef(argument='mask')),
                    ProgramParameterSpec(position=3, name='epsilon', kind=ProgramParameterKind.SCALAR, access=WorkspaceAccess.READ, scalar_type=ScalarABIType.FLOAT64),
                    ProgramParameterSpec(position=4, name='normalizer', kind=ProgramParameterKind.TENSOR, access=WorkspaceAccess.READ, shape=ConcatShape(parts=(ShapePrefix(argument="left", trailing_rank=3), ShapeTuple(dimensions=(DimRef(argument="left", axis=-2), DimRef(argument="right", axis=-2))))), dtype=ConstantDType(value="float32"), device=DeviceRef(argument='left')),
                    ProgramParameterSpec(position=5, name='grad_right', kind=ProgramParameterKind.TENSOR, access=WorkspaceAccess.WRITE, shape=ShapeOf(argument='right'), dtype=DTypeRef(argument='right'), device=DeviceRef(argument='right'), optional=True),
                    ProgramParameterSpec(position=6, name='need_right_grad', kind=ProgramParameterKind.SCALAR, access=WorkspaceAccess.READ, scalar_type=ScalarABIType.BOOL),
                    ProgramParameterSpec(position=7, name='stream', kind=ProgramParameterKind.STREAM, access=WorkspaceAccess.READ),
                ),
                bindings=(
                    ProgramBindingSpec(parameter='grad_output', source=ProgramBindingSource.OUTPUT_GRADIENT, source_name='output'),
                    ProgramBindingSpec(parameter='left', source=ProgramBindingSource.OPERATOR_ARGUMENT, source_name='left'),
                    ProgramBindingSpec(parameter='mask', source=ProgramBindingSource.OPERATOR_ARGUMENT, source_name='mask'),
                    ProgramBindingSpec(parameter='epsilon', source=ProgramBindingSource.OPERATOR_ARGUMENT, source_name='epsilon'),
                    ProgramBindingSpec(parameter='normalizer', source=ProgramBindingSource.FORWARD_OUTPUT, source_name='normalizer'),
                    ProgramBindingSpec(parameter='grad_right', source=ProgramBindingSource.PROVIDER_OUTPUT, source_name='grad_right'),
                    ProgramBindingSpec(parameter='need_right_grad', source=ProgramBindingSource.GRADIENT_REQUEST, source_name='right'),
                    ProgramBindingSpec(parameter='stream', source=ProgramBindingSource.CURRENT_STREAM),
             
             
             
             
            )
            ,
                return_abi=ProgramReturnABI.STATUS_I32_ZERO_SUCCESS,
                artifact_boundary=ProgramArtifactBoundary.NODE_CONTENT_ADDRESSED_DSO,
            ),
            ProgramNodeSpec(
                name='dmask',
                builder='kernels.pairformer.outer_product_mean.tilelang:build_dmask_program',
                symbol='mindclade_tilelang_outer_product_mean_dmask_launch',
                entry_symbol="call",
                entry_abi=ProgramEntryABI.TILELANG_0_1_13_HOST_CALL,
                parameters=(
                    ProgramParameterSpec(position=0, name='grad_output', kind=ProgramParameterKind.TENSOR, access=WorkspaceAccess.READ, shape=ConcatShape(parts=(ShapePrefix(argument="left", trailing_rank=3), ShapeTuple(dimensions=(DimRef(argument="left", axis=-2), DimRef(argument="right", axis=-2), DimRef(argument="left", axis=-1), DimRef(argument="right", axis=-1))))), dtype=DTypeRef(argument='left'), device=DeviceRef(argument='left')),
                    ProgramParameterSpec(position=1, name='left', kind=ProgramParameterKind.TENSOR, access=WorkspaceAccess.READ, shape=ShapeOf(argument='left'), dtype=DTypeRef(argument='left'), device=DeviceRef(argument='left')),
                    ProgramParameterSpec(position=2, name='right', kind=ProgramParameterKind.TENSOR, access=WorkspaceAccess.READ, shape=ShapeOf(argument='right'), dtype=DTypeRef(argument='right'), device=DeviceRef(argument='right')),
                    ProgramParameterSpec(position=3, name='mask', kind=ProgramParameterKind.TENSOR, access=WorkspaceAccess.READ, shape=ShapeOf(argument='mask'), dtype=DTypeRef(argument='mask'), device=DeviceRef(argument='mask')),
                    ProgramParameterSpec(position=4, name='epsilon', kind=ProgramParameterKind.SCALAR, access=WorkspaceAccess.READ, scalar_type=ScalarABIType.FLOAT64),
                    ProgramParameterSpec(position=5, name='output', kind=ProgramParameterKind.TENSOR, access=WorkspaceAccess.READ, shape=ConcatShape(parts=(ShapePrefix(argument="left", trailing_rank=3), ShapeTuple(dimensions=(DimRef(argument="left", axis=-2), DimRef(argument="right", axis=-2), DimRef(argument="left", axis=-1), DimRef(argument="right", axis=-1))))), dtype=DTypeRef(argument='left'), device=DeviceRef(argument='left')),
                    ProgramParameterSpec(position=6, name='normalizer', kind=ProgramParameterKind.TENSOR, access=WorkspaceAccess.READ, shape=ConcatShape(parts=(ShapePrefix(argument="left", trailing_rank=3), ShapeTuple(dimensions=(DimRef(argument="left", axis=-2), DimRef(argument="right", axis=-2))))), dtype=ConstantDType(value="float32"), device=DeviceRef(argument='left')),
                    ProgramParameterSpec(position=7, name='grad_mask', kind=ProgramParameterKind.TENSOR, access=WorkspaceAccess.WRITE, shape=ShapeOf(argument='mask'), dtype=DTypeRef(argument='mask'), device=DeviceRef(argument='mask'), optional=True),
                    ProgramParameterSpec(position=8, name='need_mask_grad', kind=ProgramParameterKind.SCALAR, access=WorkspaceAccess.READ, scalar_type=ScalarABIType.BOOL),
                    ProgramParameterSpec(position=9, name='stream', kind=ProgramParameterKind.STREAM, access=WorkspaceAccess.READ),
                ),
                bindings=(
                    ProgramBindingSpec(parameter='grad_output', source=ProgramBindingSource.OUTPUT_GRADIENT, source_name='output'),
                    ProgramBindingSpec(parameter='left', source=ProgramBindingSource.OPERATOR_ARGUMENT, source_name='left'),
                    ProgramBindingSpec(parameter='right', source=ProgramBindingSource.OPERATOR_ARGUMENT, source_name='right'),
                    ProgramBindingSpec(parameter='mask', source=ProgramBindingSource.OPERATOR_ARGUMENT, source_name='mask'),
                    ProgramBindingSpec(parameter='epsilon', source=ProgramBindingSource.OPERATOR_ARGUMENT, source_name='epsilon'),
                    ProgramBindingSpec(parameter='output', source=ProgramBindingSource.FORWARD_OUTPUT, source_name='output'),
                    ProgramBindingSpec(parameter='normalizer', source=ProgramBindingSource.FORWARD_OUTPUT, source_name='normalizer'),
                    ProgramBindingSpec(parameter='grad_mask', source=ProgramBindingSource.PROVIDER_OUTPUT, source_name='grad_mask'),
                    ProgramBindingSpec(parameter='need_mask_grad', source=ProgramBindingSource.GRADIENT_REQUEST, source_name='mask'),
                    ProgramBindingSpec(parameter='stream', source=ProgramBindingSource.CURRENT_STREAM),
             
             
             
             
            )
            ,
                return_abi=ProgramReturnABI.STATUS_I32_ZERO_SUCCESS,
                artifact_boundary=ProgramArtifactBoundary.NODE_CONTENT_ADDRESSED_DSO,
            ),
            ),
        ),
    ),
    autograd_policy=AutogradPolicy.REQUIRED,
    runtime_workload=RuntimeWorkloadSpec(
        dimensions=(
            WorkloadDimensionBinding(name="batch_size", value=DimRef(argument="left", axis=0)),
            WorkloadDimensionBinding(name="left_channels", value=DimRef(argument="left", axis=3)),
            WorkloadDimensionBinding(name="node_count", value=DimRef(argument="left", axis=2)),
            WorkloadDimensionBinding(name="right_channels", value=DimRef(argument="right", axis=3)),
            WorkloadDimensionBinding(name="source_count", value=DimRef(argument="left", axis=1)),
        ),
        input_dtype=DTypeRef(argument="left"),
        layout="contiguous",
        mode_selector=None,
        attributes=(),
        canonicalization_version=1,
        version=1,
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
