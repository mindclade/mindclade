"""Declarative native-training contract for Pairformer triangle attention."""

from kernels.api import (
    RuntimeWorkloadSpec,
    WorkloadDimensionBinding,
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
    RoundUp,
    ScalarRef,
    ScalarType,
    ShapeOf,
    ShapeTuple,
    TensorCapabilityConstraint,
    WorkspaceAccess,
    WorkspaceLifetime,
    WorkspaceSpec,
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
                    symbol="mindclade_tilelang_triangle_attention_forward_launch",
                    entry_symbol="call",
                    entry_abi=ProgramEntryABI.TILELANG_0_1_13_HOST_CALL,
                    parameters=(
                        ProgramParameterSpec(
                            position=0,
                            name="q",
                            kind=ProgramParameterKind.TENSOR,
                            access=WorkspaceAccess.READ,
                            shape=ShapeOf(argument="q"),
                            dtype=DTypeRef(argument="q"),
                            device=DeviceRef(argument="q"),
                        ),
                        ProgramParameterSpec(
                            position=1,
                            name="k",
                            kind=ProgramParameterKind.TENSOR,
                            access=WorkspaceAccess.READ,
                            shape=ShapeOf(argument="k"),
                            dtype=DTypeRef(argument="k"),
                            device=DeviceRef(argument="k"),
                        ),
                        ProgramParameterSpec(
                            position=2,
                            name="v",
                            kind=ProgramParameterKind.TENSOR,
                            access=WorkspaceAccess.READ,
                            shape=ShapeOf(argument="v"),
                            dtype=DTypeRef(argument="v"),
                            device=DeviceRef(argument="v"),
                        ),
                        ProgramParameterSpec(
                            position=3,
                            name="bias",
                            kind=ProgramParameterKind.TENSOR,
                            access=WorkspaceAccess.READ,
                            shape=ShapeOf(argument="bias"),
                            dtype=DTypeRef(argument="bias"),
                            device=DeviceRef(argument="bias"),
                        ),
                        ProgramParameterSpec(
                            position=4,
                            name="mask",
                            kind=ProgramParameterKind.TENSOR,
                            access=WorkspaceAccess.READ,
                            shape=ShapeOf(argument="mask"),
                            dtype=DTypeRef(argument="mask"),
                            device=DeviceRef(argument="mask"),
                        ),
                        ProgramParameterSpec(
                            position=5,
                            name="scale",
                            kind=ProgramParameterKind.SCALAR,
                            access=WorkspaceAccess.READ,
                            scalar_type=ScalarABIType.FLOAT64,
                        ),
                        ProgramParameterSpec(
                            position=6,
                            name="output",
                            kind=ProgramParameterKind.TENSOR,
                            access=WorkspaceAccess.WRITE,
                            shape=ShapeOf(argument="q"),
                            dtype=DTypeRef(argument="q"),
                            device=DeviceRef(argument="q"),
                        ),
                        ProgramParameterSpec(
                            position=7,
                            name="lse",
                            kind=ProgramParameterKind.TENSOR,
                            access=WorkspaceAccess.WRITE,
                            shape=ShapeTuple(
                                dimensions=(
                                    DimRef(argument="q", axis=0),
                                    DimRef(argument="q", axis=3),
                                    RoundUp(
                                        value=DimRef(argument="q", axis=1),
                                        multiple=IntLiteral(value=32),
                                    ),
                                )
                            ),
                            dtype=ConstantDType(value="float32"),
                            device=DeviceRef(argument="q"),
                        ),
                        ProgramParameterSpec(
                            position=8,
                            name="stream",
                            kind=ProgramParameterKind.STREAM,
                            access=WorkspaceAccess.READ,
                        ),
                    ),
                    bindings=(
                        ProgramBindingSpec(
                            parameter="q",
                            source=ProgramBindingSource.OPERATOR_ARGUMENT,
                            source_name="q",
                        ),
                        ProgramBindingSpec(
                            parameter="k",
                            source=ProgramBindingSource.OPERATOR_ARGUMENT,
                            source_name="k",
                        ),
                        ProgramBindingSpec(
                            parameter="v",
                            source=ProgramBindingSource.OPERATOR_ARGUMENT,
                            source_name="v",
                        ),
                        ProgramBindingSpec(
                            parameter="bias",
                            source=ProgramBindingSource.OPERATOR_ARGUMENT,
                            source_name="bias",
                        ),
                        ProgramBindingSpec(
                            parameter="mask",
                            source=ProgramBindingSource.OPERATOR_ARGUMENT,
                            source_name="mask",
                        ),
                        ProgramBindingSpec(
                            parameter="scale",
                            source=ProgramBindingSource.OPERATOR_ARGUMENT,
                            source_name="scale",
                        ),
                        ProgramBindingSpec(
                            parameter="output",
                            source=ProgramBindingSource.PROVIDER_OUTPUT,
                            source_name="output",
                        ),
                        ProgramBindingSpec(
                            parameter="lse",
                            source=ProgramBindingSource.PROVIDER_OUTPUT,
                            source_name="lse",
                        ),
                        ProgramBindingSpec(
                            parameter="stream", source=ProgramBindingSource.CURRENT_STREAM
                        ),
                    ),
                    return_abi=ProgramReturnABI.STATUS_I32_ZERO_SUCCESS,
                    artifact_boundary=ProgramArtifactBoundary.NODE_CONTENT_ADDRESSED_DSO,
                ),
            ),
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
            BackwardArgumentBinding(
                provider_argument="grad_output",
                source=BackwardArgumentSource.OUTPUT_GRADIENT,
                source_name="output",
                missing=MissingGradientPolicy.ERROR,
            ),
            BackwardArgumentBinding(
                provider_argument="q",
                source=BackwardArgumentSource.OPERATOR_ARGUMENT,
                source_name="q",
            ),
            BackwardArgumentBinding(
                provider_argument="k",
                source=BackwardArgumentSource.OPERATOR_ARGUMENT,
                source_name="k",
            ),
            BackwardArgumentBinding(
                provider_argument="v",
                source=BackwardArgumentSource.OPERATOR_ARGUMENT,
                source_name="v",
            ),
            BackwardArgumentBinding(
                provider_argument="bias",
                source=BackwardArgumentSource.OPERATOR_ARGUMENT,
                source_name="bias",
            ),
            BackwardArgumentBinding(
                provider_argument="mask",
                source=BackwardArgumentSource.OPERATOR_ARGUMENT,
                source_name="mask",
            ),
            BackwardArgumentBinding(
                provider_argument="scale",
                source=BackwardArgumentSource.OPERATOR_ARGUMENT,
                source_name="scale",
            ),
            BackwardArgumentBinding(
                provider_argument="output",
                source=BackwardArgumentSource.FORWARD_OUTPUT,
                source_name="output",
            ),
            BackwardArgumentBinding(
                provider_argument="lse",
                source=BackwardArgumentSource.FORWARD_OUTPUT,
                source_name="lse",
            ),
            BackwardArgumentBinding(
                provider_argument="need_q_grad",
                source=BackwardArgumentSource.NEEDS_INPUT_GRAD,
                source_name="q",
            ),
            BackwardArgumentBinding(
                provider_argument="need_k_grad",
                source=BackwardArgumentSource.NEEDS_INPUT_GRAD,
                source_name="k",
            ),
            BackwardArgumentBinding(
                provider_argument="need_v_grad",
                source=BackwardArgumentSource.NEEDS_INPUT_GRAD,
                source_name="v",
            ),
            BackwardArgumentBinding(
                provider_argument="need_bias_grad",
                source=BackwardArgumentSource.NEEDS_INPUT_GRAD,
                source_name="bias",
            ),
        ),
        gradients=(
            GradientSpec(
                input_name="q",
                output_name="grad_q",
                shape=ShapeOf(argument="q"),
                dtype=DTypeRef(argument="q"),
                device=DeviceRef(argument="q"),
                optional=True,
                accumulation_dtype="float32",
            ),
            GradientSpec(
                input_name="k",
                output_name="grad_k",
                shape=ShapeOf(argument="k"),
                dtype=DTypeRef(argument="k"),
                device=DeviceRef(argument="k"),
                optional=True,
                accumulation_dtype="float32",
            ),
            GradientSpec(
                input_name="v",
                output_name="grad_v",
                shape=ShapeOf(argument="v"),
                dtype=DTypeRef(argument="v"),
                device=DeviceRef(argument="v"),
                optional=True,
                accumulation_dtype="float32",
            ),
            GradientSpec(
                input_name="bias",
                output_name="grad_bias",
                shape=ShapeOf(argument="bias"),
                dtype=DTypeRef(argument="bias"),
                device=DeviceRef(argument="bias"),
                optional=True,
                accumulation_dtype="float32",
            ),
        ),
        supports_double_backward=False,
        program_group=ProgramGroupSpec(
            nodes=(
                ProgramNodeSpec(
                    name="delta",
                    builder="kernels.pairformer.triangle_attention.tilelang:build_delta",
                    symbol="mindclade_tilelang_triangle_attention_delta_launch",
                    entry_symbol="call",
                    entry_abi=ProgramEntryABI.TILELANG_0_1_13_HOST_CALL,
                    parameters=(
                        ProgramParameterSpec(
                            position=0,
                            name="grad_output",
                            kind=ProgramParameterKind.TENSOR,
                            access=WorkspaceAccess.READ,
                            shape=ShapeOf(argument="q"),
                            dtype=DTypeRef(argument="q"),
                            device=DeviceRef(argument="q"),
                        ),
                        ProgramParameterSpec(
                            position=1,
                            name="output",
                            kind=ProgramParameterKind.TENSOR,
                            access=WorkspaceAccess.READ,
                            shape=ShapeOf(argument="q"),
                            dtype=DTypeRef(argument="q"),
                            device=DeviceRef(argument="q"),
                        ),
                        ProgramParameterSpec(
                            position=2,
                            name="delta",
                            kind=ProgramParameterKind.TENSOR,
                            access=WorkspaceAccess.WRITE,
                            shape=ShapeTuple(
                                dimensions=(
                                    DimRef(argument="q", axis=0),
                                    DimRef(argument="q", axis=3),
                                    RoundUp(
                                        value=DimRef(argument="q", axis=1),
                                        multiple=IntLiteral(value=32),
                                    ),
                                )
                            ),
                            dtype=ConstantDType(value="float32"),
                            device=DeviceRef(argument="q"),
                        ),
                        ProgramParameterSpec(
                            position=3,
                            name="stream",
                            kind=ProgramParameterKind.STREAM,
                            access=WorkspaceAccess.READ,
                        ),
                    ),
                    bindings=(
                        ProgramBindingSpec(
                            parameter="grad_output",
                            source=ProgramBindingSource.OUTPUT_GRADIENT,
                            source_name="output",
                        ),
                        ProgramBindingSpec(
                            parameter="output",
                            source=ProgramBindingSource.FORWARD_OUTPUT,
                            source_name="output",
                        ),
                        ProgramBindingSpec(
                            parameter="delta",
                            source=ProgramBindingSource.WORKSPACE,
                            source_name="delta",
                        ),
                        ProgramBindingSpec(
                            parameter="stream", source=ProgramBindingSource.CURRENT_STREAM
                        ),
                    ),
                    return_abi=ProgramReturnABI.STATUS_I32_ZERO_SUCCESS,
                    artifact_boundary=ProgramArtifactBoundary.NODE_CONTENT_ADDRESSED_DSO,
                ),
                ProgramNodeSpec(
                    name="dq",
                    builder="kernels.pairformer.triangle_attention.tilelang:build_dq",
                    symbol="mindclade_tilelang_triangle_attention_dq_launch",
                    entry_symbol="call",
                    entry_abi=ProgramEntryABI.TILELANG_0_1_13_HOST_CALL,
                    parameters=(
                        ProgramParameterSpec(
                            position=0,
                            name="grad_output",
                            kind=ProgramParameterKind.TENSOR,
                            access=WorkspaceAccess.READ,
                            shape=ShapeOf(argument="q"),
                            dtype=DTypeRef(argument="q"),
                            device=DeviceRef(argument="q"),
                        ),
                        ProgramParameterSpec(
                            position=1,
                            name="q",
                            kind=ProgramParameterKind.TENSOR,
                            access=WorkspaceAccess.READ,
                            shape=ShapeOf(argument="q"),
                            dtype=DTypeRef(argument="q"),
                            device=DeviceRef(argument="q"),
                        ),
                        ProgramParameterSpec(
                            position=2,
                            name="k",
                            kind=ProgramParameterKind.TENSOR,
                            access=WorkspaceAccess.READ,
                            shape=ShapeOf(argument="k"),
                            dtype=DTypeRef(argument="k"),
                            device=DeviceRef(argument="k"),
                        ),
                        ProgramParameterSpec(
                            position=3,
                            name="v",
                            kind=ProgramParameterKind.TENSOR,
                            access=WorkspaceAccess.READ,
                            shape=ShapeOf(argument="v"),
                            dtype=DTypeRef(argument="v"),
                            device=DeviceRef(argument="v"),
                        ),
                        ProgramParameterSpec(
                            position=4,
                            name="bias",
                            kind=ProgramParameterKind.TENSOR,
                            access=WorkspaceAccess.READ,
                            shape=ShapeOf(argument="bias"),
                            dtype=DTypeRef(argument="bias"),
                            device=DeviceRef(argument="bias"),
                        ),
                        ProgramParameterSpec(
                            position=5,
                            name="mask",
                            kind=ProgramParameterKind.TENSOR,
                            access=WorkspaceAccess.READ,
                            shape=ShapeOf(argument="mask"),
                            dtype=DTypeRef(argument="mask"),
                            device=DeviceRef(argument="mask"),
                        ),
                        ProgramParameterSpec(
                            position=6,
                            name="scale",
                            kind=ProgramParameterKind.SCALAR,
                            access=WorkspaceAccess.READ,
                            scalar_type=ScalarABIType.FLOAT64,
                        ),
                        ProgramParameterSpec(
                            position=7,
                            name="lse",
                            kind=ProgramParameterKind.TENSOR,
                            access=WorkspaceAccess.READ,
                            shape=ShapeTuple(
                                dimensions=(
                                    DimRef(argument="q", axis=0),
                                    DimRef(argument="q", axis=3),
                                    RoundUp(
                                        value=DimRef(argument="q", axis=1),
                                        multiple=IntLiteral(value=32),
                                    ),
                                )
                            ),
                            dtype=ConstantDType(value="float32"),
                            device=DeviceRef(argument="q"),
                        ),
                        ProgramParameterSpec(
                            position=8,
                            name="delta",
                            kind=ProgramParameterKind.TENSOR,
                            access=WorkspaceAccess.READ,
                            shape=ShapeTuple(
                                dimensions=(
                                    DimRef(argument="q", axis=0),
                                    DimRef(argument="q", axis=3),
                                    RoundUp(
                                        value=DimRef(argument="q", axis=1),
                                        multiple=IntLiteral(value=32),
                                    ),
                                )
                            ),
                            dtype=ConstantDType(value="float32"),
                            device=DeviceRef(argument="q"),
                        ),
                        ProgramParameterSpec(
                            position=9,
                            name="grad_q",
                            kind=ProgramParameterKind.TENSOR,
                            access=WorkspaceAccess.WRITE,
                            shape=ShapeOf(argument="q"),
                            dtype=DTypeRef(argument="q"),
                            device=DeviceRef(argument="q"),
                            optional=True,
                        ),
                        ProgramParameterSpec(
                            position=10,
                            name="need_q_grad",
                            kind=ProgramParameterKind.SCALAR,
                            access=WorkspaceAccess.READ,
                            scalar_type=ScalarABIType.BOOL,
                        ),
                        ProgramParameterSpec(
                            position=11,
                            name="stream",
                            kind=ProgramParameterKind.STREAM,
                            access=WorkspaceAccess.READ,
                        ),
                    ),
                    bindings=(
                        ProgramBindingSpec(
                            parameter="grad_output",
                            source=ProgramBindingSource.OUTPUT_GRADIENT,
                            source_name="output",
                        ),
                        ProgramBindingSpec(
                            parameter="q",
                            source=ProgramBindingSource.OPERATOR_ARGUMENT,
                            source_name="q",
                        ),
                        ProgramBindingSpec(
                            parameter="k",
                            source=ProgramBindingSource.OPERATOR_ARGUMENT,
                            source_name="k",
                        ),
                        ProgramBindingSpec(
                            parameter="v",
                            source=ProgramBindingSource.OPERATOR_ARGUMENT,
                            source_name="v",
                        ),
                        ProgramBindingSpec(
                            parameter="bias",
                            source=ProgramBindingSource.OPERATOR_ARGUMENT,
                            source_name="bias",
                        ),
                        ProgramBindingSpec(
                            parameter="mask",
                            source=ProgramBindingSource.OPERATOR_ARGUMENT,
                            source_name="mask",
                        ),
                        ProgramBindingSpec(
                            parameter="scale",
                            source=ProgramBindingSource.OPERATOR_ARGUMENT,
                            source_name="scale",
                        ),
                        ProgramBindingSpec(
                            parameter="lse",
                            source=ProgramBindingSource.FORWARD_OUTPUT,
                            source_name="lse",
                        ),
                        ProgramBindingSpec(
                            parameter="delta",
                            source=ProgramBindingSource.WORKSPACE,
                            source_name="delta",
                        ),
                        ProgramBindingSpec(
                            parameter="grad_q",
                            source=ProgramBindingSource.PROVIDER_OUTPUT,
                            source_name="grad_q",
                        ),
                        ProgramBindingSpec(
                            parameter="need_q_grad",
                            source=ProgramBindingSource.GRADIENT_REQUEST,
                            source_name="q",
                        ),
                        ProgramBindingSpec(
                            parameter="stream", source=ProgramBindingSource.CURRENT_STREAM
                        ),
                    ),
                    depends_on=("delta",),
                    return_abi=ProgramReturnABI.STATUS_I32_ZERO_SUCCESS,
                    artifact_boundary=ProgramArtifactBoundary.NODE_CONTENT_ADDRESSED_DSO,
                ),
                ProgramNodeSpec(
                    name="dk",
                    builder="kernels.pairformer.triangle_attention.tilelang:build_dk",
                    symbol="mindclade_tilelang_triangle_attention_dk_launch",
                    entry_symbol="call",
                    entry_abi=ProgramEntryABI.TILELANG_0_1_13_HOST_CALL,
                    parameters=(
                        ProgramParameterSpec(
                            position=0,
                            name="grad_output",
                            kind=ProgramParameterKind.TENSOR,
                            access=WorkspaceAccess.READ,
                            shape=ShapeOf(argument="q"),
                            dtype=DTypeRef(argument="q"),
                            device=DeviceRef(argument="q"),
                        ),
                        ProgramParameterSpec(
                            position=1,
                            name="q",
                            kind=ProgramParameterKind.TENSOR,
                            access=WorkspaceAccess.READ,
                            shape=ShapeOf(argument="q"),
                            dtype=DTypeRef(argument="q"),
                            device=DeviceRef(argument="q"),
                        ),
                        ProgramParameterSpec(
                            position=2,
                            name="k",
                            kind=ProgramParameterKind.TENSOR,
                            access=WorkspaceAccess.READ,
                            shape=ShapeOf(argument="k"),
                            dtype=DTypeRef(argument="k"),
                            device=DeviceRef(argument="k"),
                        ),
                        ProgramParameterSpec(
                            position=3,
                            name="v",
                            kind=ProgramParameterKind.TENSOR,
                            access=WorkspaceAccess.READ,
                            shape=ShapeOf(argument="v"),
                            dtype=DTypeRef(argument="v"),
                            device=DeviceRef(argument="v"),
                        ),
                        ProgramParameterSpec(
                            position=4,
                            name="bias",
                            kind=ProgramParameterKind.TENSOR,
                            access=WorkspaceAccess.READ,
                            shape=ShapeOf(argument="bias"),
                            dtype=DTypeRef(argument="bias"),
                            device=DeviceRef(argument="bias"),
                        ),
                        ProgramParameterSpec(
                            position=5,
                            name="mask",
                            kind=ProgramParameterKind.TENSOR,
                            access=WorkspaceAccess.READ,
                            shape=ShapeOf(argument="mask"),
                            dtype=DTypeRef(argument="mask"),
                            device=DeviceRef(argument="mask"),
                        ),
                        ProgramParameterSpec(
                            position=6,
                            name="scale",
                            kind=ProgramParameterKind.SCALAR,
                            access=WorkspaceAccess.READ,
                            scalar_type=ScalarABIType.FLOAT64,
                        ),
                        ProgramParameterSpec(
                            position=7,
                            name="lse",
                            kind=ProgramParameterKind.TENSOR,
                            access=WorkspaceAccess.READ,
                            shape=ShapeTuple(
                                dimensions=(
                                    DimRef(argument="q", axis=0),
                                    DimRef(argument="q", axis=3),
                                    RoundUp(
                                        value=DimRef(argument="q", axis=1),
                                        multiple=IntLiteral(value=32),
                                    ),
                                )
                            ),
                            dtype=ConstantDType(value="float32"),
                            device=DeviceRef(argument="q"),
                        ),
                        ProgramParameterSpec(
                            position=8,
                            name="delta",
                            kind=ProgramParameterKind.TENSOR,
                            access=WorkspaceAccess.READ,
                            shape=ShapeTuple(
                                dimensions=(
                                    DimRef(argument="q", axis=0),
                                    DimRef(argument="q", axis=3),
                                    RoundUp(
                                        value=DimRef(argument="q", axis=1),
                                        multiple=IntLiteral(value=32),
                                    ),
                                )
                            ),
                            dtype=ConstantDType(value="float32"),
                            device=DeviceRef(argument="q"),
                        ),
                        ProgramParameterSpec(
                            position=9,
                            name="grad_k",
                            kind=ProgramParameterKind.TENSOR,
                            access=WorkspaceAccess.WRITE,
                            shape=ShapeOf(argument="k"),
                            dtype=DTypeRef(argument="k"),
                            device=DeviceRef(argument="k"),
                            optional=True,
                        ),
                        ProgramParameterSpec(
                            position=10,
                            name="need_k_grad",
                            kind=ProgramParameterKind.SCALAR,
                            access=WorkspaceAccess.READ,
                            scalar_type=ScalarABIType.BOOL,
                        ),
                        ProgramParameterSpec(
                            position=11,
                            name="stream",
                            kind=ProgramParameterKind.STREAM,
                            access=WorkspaceAccess.READ,
                        ),
                    ),
                    bindings=(
                        ProgramBindingSpec(
                            parameter="grad_output",
                            source=ProgramBindingSource.OUTPUT_GRADIENT,
                            source_name="output",
                        ),
                        ProgramBindingSpec(
                            parameter="q",
                            source=ProgramBindingSource.OPERATOR_ARGUMENT,
                            source_name="q",
                        ),
                        ProgramBindingSpec(
                            parameter="k",
                            source=ProgramBindingSource.OPERATOR_ARGUMENT,
                            source_name="k",
                        ),
                        ProgramBindingSpec(
                            parameter="v",
                            source=ProgramBindingSource.OPERATOR_ARGUMENT,
                            source_name="v",
                        ),
                        ProgramBindingSpec(
                            parameter="bias",
                            source=ProgramBindingSource.OPERATOR_ARGUMENT,
                            source_name="bias",
                        ),
                        ProgramBindingSpec(
                            parameter="mask",
                            source=ProgramBindingSource.OPERATOR_ARGUMENT,
                            source_name="mask",
                        ),
                        ProgramBindingSpec(
                            parameter="scale",
                            source=ProgramBindingSource.OPERATOR_ARGUMENT,
                            source_name="scale",
                        ),
                        ProgramBindingSpec(
                            parameter="lse",
                            source=ProgramBindingSource.FORWARD_OUTPUT,
                            source_name="lse",
                        ),
                        ProgramBindingSpec(
                            parameter="delta",
                            source=ProgramBindingSource.WORKSPACE,
                            source_name="delta",
                        ),
                        ProgramBindingSpec(
                            parameter="grad_k",
                            source=ProgramBindingSource.PROVIDER_OUTPUT,
                            source_name="grad_k",
                        ),
                        ProgramBindingSpec(
                            parameter="need_k_grad",
                            source=ProgramBindingSource.GRADIENT_REQUEST,
                            source_name="k",
                        ),
                        ProgramBindingSpec(
                            parameter="stream", source=ProgramBindingSource.CURRENT_STREAM
                        ),
                    ),
                    depends_on=("delta",),
                    return_abi=ProgramReturnABI.STATUS_I32_ZERO_SUCCESS,
                    artifact_boundary=ProgramArtifactBoundary.NODE_CONTENT_ADDRESSED_DSO,
                ),
                ProgramNodeSpec(
                    name="dv",
                    builder="kernels.pairformer.triangle_attention.tilelang:build_dv",
                    symbol="mindclade_tilelang_triangle_attention_dv_launch",
                    entry_symbol="call",
                    entry_abi=ProgramEntryABI.TILELANG_0_1_13_HOST_CALL,
                    parameters=(
                        ProgramParameterSpec(
                            position=0,
                            name="grad_output",
                            kind=ProgramParameterKind.TENSOR,
                            access=WorkspaceAccess.READ,
                            shape=ShapeOf(argument="q"),
                            dtype=DTypeRef(argument="q"),
                            device=DeviceRef(argument="q"),
                        ),
                        ProgramParameterSpec(
                            position=1,
                            name="q",
                            kind=ProgramParameterKind.TENSOR,
                            access=WorkspaceAccess.READ,
                            shape=ShapeOf(argument="q"),
                            dtype=DTypeRef(argument="q"),
                            device=DeviceRef(argument="q"),
                        ),
                        ProgramParameterSpec(
                            position=2,
                            name="k",
                            kind=ProgramParameterKind.TENSOR,
                            access=WorkspaceAccess.READ,
                            shape=ShapeOf(argument="k"),
                            dtype=DTypeRef(argument="k"),
                            device=DeviceRef(argument="k"),
                        ),
                        ProgramParameterSpec(
                            position=3,
                            name="v",
                            kind=ProgramParameterKind.TENSOR,
                            access=WorkspaceAccess.READ,
                            shape=ShapeOf(argument="v"),
                            dtype=DTypeRef(argument="v"),
                            device=DeviceRef(argument="v"),
                        ),
                        ProgramParameterSpec(
                            position=4,
                            name="bias",
                            kind=ProgramParameterKind.TENSOR,
                            access=WorkspaceAccess.READ,
                            shape=ShapeOf(argument="bias"),
                            dtype=DTypeRef(argument="bias"),
                            device=DeviceRef(argument="bias"),
                        ),
                        ProgramParameterSpec(
                            position=5,
                            name="mask",
                            kind=ProgramParameterKind.TENSOR,
                            access=WorkspaceAccess.READ,
                            shape=ShapeOf(argument="mask"),
                            dtype=DTypeRef(argument="mask"),
                            device=DeviceRef(argument="mask"),
                        ),
                        ProgramParameterSpec(
                            position=6,
                            name="scale",
                            kind=ProgramParameterKind.SCALAR,
                            access=WorkspaceAccess.READ,
                            scalar_type=ScalarABIType.FLOAT64,
                        ),
                        ProgramParameterSpec(
                            position=7,
                            name="lse",
                            kind=ProgramParameterKind.TENSOR,
                            access=WorkspaceAccess.READ,
                            shape=ShapeTuple(
                                dimensions=(
                                    DimRef(argument="q", axis=0),
                                    DimRef(argument="q", axis=3),
                                    RoundUp(
                                        value=DimRef(argument="q", axis=1),
                                        multiple=IntLiteral(value=32),
                                    ),
                                )
                            ),
                            dtype=ConstantDType(value="float32"),
                            device=DeviceRef(argument="q"),
                        ),
                        ProgramParameterSpec(
                            position=8,
                            name="grad_v",
                            kind=ProgramParameterKind.TENSOR,
                            access=WorkspaceAccess.WRITE,
                            shape=ShapeOf(argument="v"),
                            dtype=DTypeRef(argument="v"),
                            device=DeviceRef(argument="v"),
                            optional=True,
                        ),
                        ProgramParameterSpec(
                            position=9,
                            name="need_v_grad",
                            kind=ProgramParameterKind.SCALAR,
                            access=WorkspaceAccess.READ,
                            scalar_type=ScalarABIType.BOOL,
                        ),
                        ProgramParameterSpec(
                            position=10,
                            name="stream",
                            kind=ProgramParameterKind.STREAM,
                            access=WorkspaceAccess.READ,
                        ),
                    ),
                    bindings=(
                        ProgramBindingSpec(
                            parameter="grad_output",
                            source=ProgramBindingSource.OUTPUT_GRADIENT,
                            source_name="output",
                        ),
                        ProgramBindingSpec(
                            parameter="q",
                            source=ProgramBindingSource.OPERATOR_ARGUMENT,
                            source_name="q",
                        ),
                        ProgramBindingSpec(
                            parameter="k",
                            source=ProgramBindingSource.OPERATOR_ARGUMENT,
                            source_name="k",
                        ),
                        ProgramBindingSpec(
                            parameter="v",
                            source=ProgramBindingSource.OPERATOR_ARGUMENT,
                            source_name="v",
                        ),
                        ProgramBindingSpec(
                            parameter="bias",
                            source=ProgramBindingSource.OPERATOR_ARGUMENT,
                            source_name="bias",
                        ),
                        ProgramBindingSpec(
                            parameter="mask",
                            source=ProgramBindingSource.OPERATOR_ARGUMENT,
                            source_name="mask",
                        ),
                        ProgramBindingSpec(
                            parameter="scale",
                            source=ProgramBindingSource.OPERATOR_ARGUMENT,
                            source_name="scale",
                        ),
                        ProgramBindingSpec(
                            parameter="lse",
                            source=ProgramBindingSource.FORWARD_OUTPUT,
                            source_name="lse",
                        ),
                        ProgramBindingSpec(
                            parameter="grad_v",
                            source=ProgramBindingSource.PROVIDER_OUTPUT,
                            source_name="grad_v",
                        ),
                        ProgramBindingSpec(
                            parameter="need_v_grad",
                            source=ProgramBindingSource.GRADIENT_REQUEST,
                            source_name="v",
                        ),
                        ProgramBindingSpec(
                            parameter="stream", source=ProgramBindingSource.CURRENT_STREAM
                        ),
                    ),
                    return_abi=ProgramReturnABI.STATUS_I32_ZERO_SUCCESS,
                    artifact_boundary=ProgramArtifactBoundary.NODE_CONTENT_ADDRESSED_DSO,
                ),
                ProgramNodeSpec(
                    name="dbias",
                    builder="kernels.pairformer.triangle_attention.tilelang:build_dbias",
                    symbol="mindclade_tilelang_triangle_attention_dbias_launch",
                    entry_symbol="call",
                    entry_abi=ProgramEntryABI.TILELANG_0_1_13_HOST_CALL,
                    parameters=(
                        ProgramParameterSpec(
                            position=0,
                            name="grad_output",
                            kind=ProgramParameterKind.TENSOR,
                            access=WorkspaceAccess.READ,
                            shape=ShapeOf(argument="q"),
                            dtype=DTypeRef(argument="q"),
                            device=DeviceRef(argument="q"),
                        ),
                        ProgramParameterSpec(
                            position=1,
                            name="q",
                            kind=ProgramParameterKind.TENSOR,
                            access=WorkspaceAccess.READ,
                            shape=ShapeOf(argument="q"),
                            dtype=DTypeRef(argument="q"),
                            device=DeviceRef(argument="q"),
                        ),
                        ProgramParameterSpec(
                            position=2,
                            name="k",
                            kind=ProgramParameterKind.TENSOR,
                            access=WorkspaceAccess.READ,
                            shape=ShapeOf(argument="k"),
                            dtype=DTypeRef(argument="k"),
                            device=DeviceRef(argument="k"),
                        ),
                        ProgramParameterSpec(
                            position=3,
                            name="v",
                            kind=ProgramParameterKind.TENSOR,
                            access=WorkspaceAccess.READ,
                            shape=ShapeOf(argument="v"),
                            dtype=DTypeRef(argument="v"),
                            device=DeviceRef(argument="v"),
                        ),
                        ProgramParameterSpec(
                            position=4,
                            name="bias",
                            kind=ProgramParameterKind.TENSOR,
                            access=WorkspaceAccess.READ,
                            shape=ShapeOf(argument="bias"),
                            dtype=DTypeRef(argument="bias"),
                            device=DeviceRef(argument="bias"),
                        ),
                        ProgramParameterSpec(
                            position=5,
                            name="mask",
                            kind=ProgramParameterKind.TENSOR,
                            access=WorkspaceAccess.READ,
                            shape=ShapeOf(argument="mask"),
                            dtype=DTypeRef(argument="mask"),
                            device=DeviceRef(argument="mask"),
                        ),
                        ProgramParameterSpec(
                            position=6,
                            name="scale",
                            kind=ProgramParameterKind.SCALAR,
                            access=WorkspaceAccess.READ,
                            scalar_type=ScalarABIType.FLOAT64,
                        ),
                        ProgramParameterSpec(
                            position=7,
                            name="lse",
                            kind=ProgramParameterKind.TENSOR,
                            access=WorkspaceAccess.READ,
                            shape=ShapeTuple(
                                dimensions=(
                                    DimRef(argument="q", axis=0),
                                    DimRef(argument="q", axis=3),
                                    RoundUp(
                                        value=DimRef(argument="q", axis=1),
                                        multiple=IntLiteral(value=32),
                                    ),
                                )
                            ),
                            dtype=ConstantDType(value="float32"),
                            device=DeviceRef(argument="q"),
                        ),
                        ProgramParameterSpec(
                            position=8,
                            name="delta",
                            kind=ProgramParameterKind.TENSOR,
                            access=WorkspaceAccess.READ,
                            shape=ShapeTuple(
                                dimensions=(
                                    DimRef(argument="q", axis=0),
                                    DimRef(argument="q", axis=3),
                                    RoundUp(
                                        value=DimRef(argument="q", axis=1),
                                        multiple=IntLiteral(value=32),
                                    ),
                                )
                            ),
                            dtype=ConstantDType(value="float32"),
                            device=DeviceRef(argument="q"),
                        ),
                        ProgramParameterSpec(
                            position=9,
                            name="grad_bias",
                            kind=ProgramParameterKind.TENSOR,
                            access=WorkspaceAccess.WRITE,
                            shape=ShapeOf(argument="bias"),
                            dtype=DTypeRef(argument="bias"),
                            device=DeviceRef(argument="bias"),
                            optional=True,
                        ),
                        ProgramParameterSpec(
                            position=10,
                            name="need_bias_grad",
                            kind=ProgramParameterKind.SCALAR,
                            access=WorkspaceAccess.READ,
                            scalar_type=ScalarABIType.BOOL,
                        ),
                        ProgramParameterSpec(
                            position=11,
                            name="stream",
                            kind=ProgramParameterKind.STREAM,
                            access=WorkspaceAccess.READ,
                        ),
                    ),
                    bindings=(
                        ProgramBindingSpec(
                            parameter="grad_output",
                            source=ProgramBindingSource.OUTPUT_GRADIENT,
                            source_name="output",
                        ),
                        ProgramBindingSpec(
                            parameter="q",
                            source=ProgramBindingSource.OPERATOR_ARGUMENT,
                            source_name="q",
                        ),
                        ProgramBindingSpec(
                            parameter="k",
                            source=ProgramBindingSource.OPERATOR_ARGUMENT,
                            source_name="k",
                        ),
                        ProgramBindingSpec(
                            parameter="v",
                            source=ProgramBindingSource.OPERATOR_ARGUMENT,
                            source_name="v",
                        ),
                        ProgramBindingSpec(
                            parameter="bias",
                            source=ProgramBindingSource.OPERATOR_ARGUMENT,
                            source_name="bias",
                        ),
                        ProgramBindingSpec(
                            parameter="mask",
                            source=ProgramBindingSource.OPERATOR_ARGUMENT,
                            source_name="mask",
                        ),
                        ProgramBindingSpec(
                            parameter="scale",
                            source=ProgramBindingSource.OPERATOR_ARGUMENT,
                            source_name="scale",
                        ),
                        ProgramBindingSpec(
                            parameter="lse",
                            source=ProgramBindingSource.FORWARD_OUTPUT,
                            source_name="lse",
                        ),
                        ProgramBindingSpec(
                            parameter="delta",
                            source=ProgramBindingSource.WORKSPACE,
                            source_name="delta",
                        ),
                        ProgramBindingSpec(
                            parameter="grad_bias",
                            source=ProgramBindingSource.PROVIDER_OUTPUT,
                            source_name="grad_bias",
                        ),
                        ProgramBindingSpec(
                            parameter="need_bias_grad",
                            source=ProgramBindingSource.GRADIENT_REQUEST,
                            source_name="bias",
                        ),
                        ProgramBindingSpec(
                            parameter="stream", source=ProgramBindingSource.CURRENT_STREAM
                        ),
                    ),
                    depends_on=("delta",),
                    return_abi=ProgramReturnABI.STATUS_I32_ZERO_SUCCESS,
                    artifact_boundary=ProgramArtifactBoundary.NODE_CONTENT_ADDRESSED_DSO,
                ),
            ),
            workspaces=(
                WorkspaceSpec(
                    name="delta",
                    shape=ShapeTuple(
                        dimensions=(
                            DimRef(argument="q", axis=0),
                            DimRef(argument="q", axis=3),
                            RoundUp(
                                value=DimRef(argument="q", axis=1), multiple=IntLiteral(value=32)
                            ),
                        )
                    ),
                    dtype=ConstantDType(value="float32"),
                    zero_initialize=False,
                    lifetime=WorkspaceLifetime.PROGRAM_GROUP,
                ),
            ),
        ),
    ),
    autograd_policy=AutogradPolicy.REQUIRED,
    runtime_workload=RuntimeWorkloadSpec(
        dimensions=(
            WorkloadDimensionBinding(name="batch", value=DimRef(argument="q", axis=0)),
            WorkloadDimensionBinding(name="head_dim", value=DimRef(argument="q", axis=3)),
            WorkloadDimensionBinding(name="heads", value=DimRef(argument="q", axis=2)),
            WorkloadDimensionBinding(name="n", value=DimRef(argument="q", axis=1)),
        ),
        input_dtype=DTypeRef(argument="q"),
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
            architectures=("sm90a",),
            dtypes=("float16",),
            layouts=("contiguous",),
            modes=("default",),
            constraints=(
                DimensionConstraint(
                    predicate=And(
                        operands=(
                            Eq(lhs=RankRef(argument="q"), rhs=IntLiteral(value=5)),
                            Eq(lhs=RankRef(argument="k"), rhs=IntLiteral(value=5)),
                            Eq(lhs=RankRef(argument="v"), rhs=IntLiteral(value=5)),
                            Eq(lhs=RankRef(argument="bias"), rhs=IntLiteral(value=5)),
                            Eq(lhs=RankRef(argument="mask"), rhs=IntLiteral(value=3)),
                            GreaterThan(lhs=DimRef(argument="q", axis=0), rhs=IntLiteral(value=0)),
                            LessEqual(lhs=DimRef(argument="q", axis=0), rhs=IntLiteral(value=2)),
                            GreaterThan(lhs=DimRef(argument="q", axis=1), rhs=IntLiteral(value=0)),
                            LessEqual(lhs=DimRef(argument="q", axis=1), rhs=IntLiteral(value=128)),
                            Eq(lhs=DimRef(argument="q", axis=2), rhs=DimRef(argument="q", axis=1)),
                            GreaterThan(lhs=DimRef(argument="q", axis=3), rhs=IntLiteral(value=0)),
                            LessEqual(lhs=DimRef(argument="q", axis=3), rhs=IntLiteral(value=8)),
                            Or(
                                operands=(
                                    Eq(lhs=DimRef(argument="q", axis=4), rhs=IntLiteral(value=32)),
                                    Eq(lhs=DimRef(argument="q", axis=4), rhs=IntLiteral(value=64)),
                                )
                            ),
                            Eq(lhs=DimRef(argument="k", axis=0), rhs=DimRef(argument="q", axis=0)),
                            Eq(lhs=DimRef(argument="k", axis=1), rhs=DimRef(argument="q", axis=1)),
                            Eq(lhs=DimRef(argument="k", axis=2), rhs=DimRef(argument="q", axis=2)),
                            Eq(lhs=DimRef(argument="k", axis=3), rhs=DimRef(argument="q", axis=3)),
                            Eq(lhs=DimRef(argument="k", axis=4), rhs=DimRef(argument="q", axis=4)),
                            Eq(lhs=DimRef(argument="v", axis=0), rhs=DimRef(argument="q", axis=0)),
                            Eq(lhs=DimRef(argument="v", axis=1), rhs=DimRef(argument="q", axis=1)),
                            Eq(lhs=DimRef(argument="v", axis=2), rhs=DimRef(argument="q", axis=2)),
                            Eq(lhs=DimRef(argument="v", axis=3), rhs=DimRef(argument="q", axis=3)),
                            Eq(lhs=DimRef(argument="v", axis=4), rhs=DimRef(argument="q", axis=4)),
                            Eq(
                                lhs=DimRef(argument="bias", axis=0),
                                rhs=DimRef(argument="q", axis=0),
                            ),
                            Eq(
                                lhs=DimRef(argument="bias", axis=1),
                                rhs=DimRef(argument="q", axis=1),
                            ),
                            Eq(
                                lhs=DimRef(argument="bias", axis=2),
                                rhs=DimRef(argument="q", axis=3),
                            ),
                            Eq(
                                lhs=DimRef(argument="bias", axis=3),
                                rhs=DimRef(argument="q", axis=2),
                            ),
                            Eq(
                                lhs=DimRef(argument="bias", axis=4),
                                rhs=DimRef(argument="q", axis=2),
                            ),
                            Eq(
                                lhs=DimRef(argument="mask", axis=0),
                                rhs=DimRef(argument="q", axis=0),
                            ),
                            Eq(
                                lhs=DimRef(argument="mask", axis=1),
                                rhs=DimRef(argument="q", axis=1),
                            ),
                            Eq(
                                lhs=DimRef(argument="mask", axis=2),
                                rhs=DimRef(argument="q", axis=2),
                            ),
                        )
                    ),
                    code="TRIANGLE_ATTENTION_SHAPES",
                    message="requires dense B,N,N,H,D attention with B<=2, N<=128, H<=8, and D in {32,64}",
                ),
                DimensionConstraint(
                    predicate=IsFinite(
                        value=ScalarRef(argument="scale", value_type=ScalarType.FLOAT)
                    ),
                    code="SCALE_FINITE",
                    message="scale must be finite",
                ),
            ),
            graph_capture_safe=False,
            training_capable=True,
            tensor_constraints=(
                TensorCapabilityConstraint(
                    argument="q",
                    dtypes=("float16",),
                    layouts=("contiguous",),
                    devices=("cuda",),
                    ranks=(5,),
                ),
                TensorCapabilityConstraint(
                    argument="k",
                    dtypes=("float16",),
                    layouts=("contiguous",),
                    devices=("cuda",),
                    ranks=(5,),
                ),
                TensorCapabilityConstraint(
                    argument="v",
                    dtypes=("float16",),
                    layouts=("contiguous",),
                    devices=("cuda",),
                    ranks=(5,),
                ),
                TensorCapabilityConstraint(
                    argument="bias",
                    dtypes=("float16",),
                    layouts=("contiguous",),
                    devices=("cuda",),
                    ranks=(5,),
                ),
                TensorCapabilityConstraint(
                    argument="mask",
                    dtypes=("bool",),
                    layouts=("contiguous",),
                    devices=("cuda",),
                    ranks=(3,),
                ),
            ),
        ),
        priority=100,
    ),
    ImplementationSpec(
        operation="triangle_attention",
        name="triangle_attention_sm90a_bf16_online_v1",
        family="pairformer",
        backend="tilelang",
        builder="kernels.pairformer.triangle_attention.tilelang:build_forward_program_group",
        version=1,
        tier=ImplementationTier.OPTIMIZED,
        requires=("cuda", "sm90a", "tilelang-0.1.13", "online-softmax"),
        envelope=CapabilityEnvelope(
            architectures=("sm90a",),
            dtypes=("bfloat16",),
            layouts=("contiguous",),
            modes=("default",),
            constraints=(
                DimensionConstraint(
                    predicate=And(
                        operands=(
                            Eq(lhs=RankRef(argument="q"), rhs=IntLiteral(value=5)),
                            Eq(lhs=RankRef(argument="k"), rhs=IntLiteral(value=5)),
                            Eq(lhs=RankRef(argument="v"), rhs=IntLiteral(value=5)),
                            Eq(lhs=RankRef(argument="bias"), rhs=IntLiteral(value=5)),
                            Eq(lhs=RankRef(argument="mask"), rhs=IntLiteral(value=3)),
                            GreaterThan(lhs=DimRef(argument="q", axis=0), rhs=IntLiteral(value=0)),
                            LessEqual(lhs=DimRef(argument="q", axis=0), rhs=IntLiteral(value=2)),
                            GreaterThan(lhs=DimRef(argument="q", axis=1), rhs=IntLiteral(value=0)),
                            LessEqual(lhs=DimRef(argument="q", axis=1), rhs=IntLiteral(value=128)),
                            Eq(lhs=DimRef(argument="q", axis=2), rhs=DimRef(argument="q", axis=1)),
                            GreaterThan(lhs=DimRef(argument="q", axis=3), rhs=IntLiteral(value=0)),
                            LessEqual(lhs=DimRef(argument="q", axis=3), rhs=IntLiteral(value=8)),
                            Or(
                                operands=(
                                    Eq(lhs=DimRef(argument="q", axis=4), rhs=IntLiteral(value=32)),
                                    Eq(lhs=DimRef(argument="q", axis=4), rhs=IntLiteral(value=64)),
                                )
                            ),
                            Eq(lhs=DimRef(argument="k", axis=0), rhs=DimRef(argument="q", axis=0)),
                            Eq(lhs=DimRef(argument="k", axis=1), rhs=DimRef(argument="q", axis=1)),
                            Eq(lhs=DimRef(argument="k", axis=2), rhs=DimRef(argument="q", axis=2)),
                            Eq(lhs=DimRef(argument="k", axis=3), rhs=DimRef(argument="q", axis=3)),
                            Eq(lhs=DimRef(argument="k", axis=4), rhs=DimRef(argument="q", axis=4)),
                            Eq(lhs=DimRef(argument="v", axis=0), rhs=DimRef(argument="q", axis=0)),
                            Eq(lhs=DimRef(argument="v", axis=1), rhs=DimRef(argument="q", axis=1)),
                            Eq(lhs=DimRef(argument="v", axis=2), rhs=DimRef(argument="q", axis=2)),
                            Eq(lhs=DimRef(argument="v", axis=3), rhs=DimRef(argument="q", axis=3)),
                            Eq(lhs=DimRef(argument="v", axis=4), rhs=DimRef(argument="q", axis=4)),
                            Eq(
                                lhs=DimRef(argument="bias", axis=0),
                                rhs=DimRef(argument="q", axis=0),
                            ),
                            Eq(
                                lhs=DimRef(argument="bias", axis=1),
                                rhs=DimRef(argument="q", axis=1),
                            ),
                            Eq(
                                lhs=DimRef(argument="bias", axis=2),
                                rhs=DimRef(argument="q", axis=3),
                            ),
                            Eq(
                                lhs=DimRef(argument="bias", axis=3),
                                rhs=DimRef(argument="q", axis=2),
                            ),
                            Eq(
                                lhs=DimRef(argument="bias", axis=4),
                                rhs=DimRef(argument="q", axis=2),
                            ),
                            Eq(
                                lhs=DimRef(argument="mask", axis=0),
                                rhs=DimRef(argument="q", axis=0),
                            ),
                            Eq(
                                lhs=DimRef(argument="mask", axis=1),
                                rhs=DimRef(argument="q", axis=1),
                            ),
                            Eq(
                                lhs=DimRef(argument="mask", axis=2),
                                rhs=DimRef(argument="q", axis=2),
                            ),
                        )
                    ),
                    code="TRIANGLE_ATTENTION_SHAPES",
                    message="requires dense B,N,N,H,D attention with B<=2, N<=128, H<=8, and D in {32,64}",
                ),
                DimensionConstraint(
                    predicate=IsFinite(
                        value=ScalarRef(argument="scale", value_type=ScalarType.FLOAT)
                    ),
                    code="SCALE_FINITE",
                    message="scale must be finite",
                ),
            ),
            graph_capture_safe=False,
            training_capable=True,
            tensor_constraints=(
                TensorCapabilityConstraint(
                    argument="q",
                    dtypes=("bfloat16",),
                    layouts=("contiguous",),
                    devices=("cuda",),
                    ranks=(5,),
                ),
                TensorCapabilityConstraint(
                    argument="k",
                    dtypes=("bfloat16",),
                    layouts=("contiguous",),
                    devices=("cuda",),
                    ranks=(5,),
                ),
                TensorCapabilityConstraint(
                    argument="v",
                    dtypes=("bfloat16",),
                    layouts=("contiguous",),
                    devices=("cuda",),
                    ranks=(5,),
                ),
                TensorCapabilityConstraint(
                    argument="bias",
                    dtypes=("bfloat16",),
                    layouts=("contiguous",),
                    devices=("cuda",),
                    ranks=(5,),
                ),
                TensorCapabilityConstraint(
                    argument="mask",
                    dtypes=("bool",),
                    layouts=("contiguous",),
                    devices=("cuda",),
                    ranks=(3,),
                ),
            ),
        ),
        priority=100,
    ),
    ImplementationSpec(
        operation="triangle_attention",
        name="triangle_attention_sm100a_fp16_online_v1",
        family="pairformer",
        backend="tilelang",
        builder="kernels.pairformer.triangle_attention.tilelang:build_forward_program_group",
        version=1,
        tier=ImplementationTier.OPTIMIZED,
        requires=("cuda", "sm100a", "tilelang-0.1.13", "online-softmax"),
        envelope=CapabilityEnvelope(
            architectures=("sm100a",),
            dtypes=("float16",),
            layouts=("contiguous",),
            modes=("default",),
            constraints=(
                DimensionConstraint(
                    predicate=And(
                        operands=(
                            Eq(lhs=RankRef(argument="q"), rhs=IntLiteral(value=5)),
                            Eq(lhs=RankRef(argument="k"), rhs=IntLiteral(value=5)),
                            Eq(lhs=RankRef(argument="v"), rhs=IntLiteral(value=5)),
                            Eq(lhs=RankRef(argument="bias"), rhs=IntLiteral(value=5)),
                            Eq(lhs=RankRef(argument="mask"), rhs=IntLiteral(value=3)),
                            GreaterThan(lhs=DimRef(argument="q", axis=0), rhs=IntLiteral(value=0)),
                            LessEqual(lhs=DimRef(argument="q", axis=0), rhs=IntLiteral(value=2)),
                            GreaterThan(lhs=DimRef(argument="q", axis=1), rhs=IntLiteral(value=0)),
                            LessEqual(lhs=DimRef(argument="q", axis=1), rhs=IntLiteral(value=128)),
                            Eq(lhs=DimRef(argument="q", axis=2), rhs=DimRef(argument="q", axis=1)),
                            GreaterThan(lhs=DimRef(argument="q", axis=3), rhs=IntLiteral(value=0)),
                            LessEqual(lhs=DimRef(argument="q", axis=3), rhs=IntLiteral(value=8)),
                            Or(
                                operands=(
                                    Eq(lhs=DimRef(argument="q", axis=4), rhs=IntLiteral(value=32)),
                                    Eq(lhs=DimRef(argument="q", axis=4), rhs=IntLiteral(value=64)),
                                )
                            ),
                            Eq(lhs=DimRef(argument="k", axis=0), rhs=DimRef(argument="q", axis=0)),
                            Eq(lhs=DimRef(argument="k", axis=1), rhs=DimRef(argument="q", axis=1)),
                            Eq(lhs=DimRef(argument="k", axis=2), rhs=DimRef(argument="q", axis=2)),
                            Eq(lhs=DimRef(argument="k", axis=3), rhs=DimRef(argument="q", axis=3)),
                            Eq(lhs=DimRef(argument="k", axis=4), rhs=DimRef(argument="q", axis=4)),
                            Eq(lhs=DimRef(argument="v", axis=0), rhs=DimRef(argument="q", axis=0)),
                            Eq(lhs=DimRef(argument="v", axis=1), rhs=DimRef(argument="q", axis=1)),
                            Eq(lhs=DimRef(argument="v", axis=2), rhs=DimRef(argument="q", axis=2)),
                            Eq(lhs=DimRef(argument="v", axis=3), rhs=DimRef(argument="q", axis=3)),
                            Eq(lhs=DimRef(argument="v", axis=4), rhs=DimRef(argument="q", axis=4)),
                            Eq(
                                lhs=DimRef(argument="bias", axis=0),
                                rhs=DimRef(argument="q", axis=0),
                            ),
                            Eq(
                                lhs=DimRef(argument="bias", axis=1),
                                rhs=DimRef(argument="q", axis=1),
                            ),
                            Eq(
                                lhs=DimRef(argument="bias", axis=2),
                                rhs=DimRef(argument="q", axis=3),
                            ),
                            Eq(
                                lhs=DimRef(argument="bias", axis=3),
                                rhs=DimRef(argument="q", axis=2),
                            ),
                            Eq(
                                lhs=DimRef(argument="bias", axis=4),
                                rhs=DimRef(argument="q", axis=2),
                            ),
                            Eq(
                                lhs=DimRef(argument="mask", axis=0),
                                rhs=DimRef(argument="q", axis=0),
                            ),
                            Eq(
                                lhs=DimRef(argument="mask", axis=1),
                                rhs=DimRef(argument="q", axis=1),
                            ),
                            Eq(
                                lhs=DimRef(argument="mask", axis=2),
                                rhs=DimRef(argument="q", axis=2),
                            ),
                        )
                    ),
                    code="TRIANGLE_ATTENTION_SHAPES",
                    message="requires dense B,N,N,H,D attention with B<=2, N<=128, H<=8, and D in {32,64}",
                ),
                DimensionConstraint(
                    predicate=IsFinite(
                        value=ScalarRef(argument="scale", value_type=ScalarType.FLOAT)
                    ),
                    code="SCALE_FINITE",
                    message="scale must be finite",
                ),
            ),
            graph_capture_safe=False,
            training_capable=True,
            tensor_constraints=(
                TensorCapabilityConstraint(
                    argument="q",
                    dtypes=("float16",),
                    layouts=("contiguous",),
                    devices=("cuda",),
                    ranks=(5,),
                ),
                TensorCapabilityConstraint(
                    argument="k",
                    dtypes=("float16",),
                    layouts=("contiguous",),
                    devices=("cuda",),
                    ranks=(5,),
                ),
                TensorCapabilityConstraint(
                    argument="v",
                    dtypes=("float16",),
                    layouts=("contiguous",),
                    devices=("cuda",),
                    ranks=(5,),
                ),
                TensorCapabilityConstraint(
                    argument="bias",
                    dtypes=("float16",),
                    layouts=("contiguous",),
                    devices=("cuda",),
                    ranks=(5,),
                ),
                TensorCapabilityConstraint(
                    argument="mask",
                    dtypes=("bool",),
                    layouts=("contiguous",),
                    devices=("cuda",),
                    ranks=(3,),
                ),
            ),
        ),
        priority=100,
    ),
    ImplementationSpec(
        operation="triangle_attention",
        name="triangle_attention_sm100a_bf16_online_v1",
        family="pairformer",
        backend="tilelang",
        builder="kernels.pairformer.triangle_attention.tilelang:build_forward_program_group",
        version=1,
        tier=ImplementationTier.OPTIMIZED,
        requires=("cuda", "sm100a", "tilelang-0.1.13", "online-softmax"),
        envelope=CapabilityEnvelope(
            architectures=("sm100a",),
            dtypes=("bfloat16",),
            layouts=("contiguous",),
            modes=("default",),
            constraints=(
                DimensionConstraint(
                    predicate=And(
                        operands=(
                            Eq(lhs=RankRef(argument="q"), rhs=IntLiteral(value=5)),
                            Eq(lhs=RankRef(argument="k"), rhs=IntLiteral(value=5)),
                            Eq(lhs=RankRef(argument="v"), rhs=IntLiteral(value=5)),
                            Eq(lhs=RankRef(argument="bias"), rhs=IntLiteral(value=5)),
                            Eq(lhs=RankRef(argument="mask"), rhs=IntLiteral(value=3)),
                            GreaterThan(lhs=DimRef(argument="q", axis=0), rhs=IntLiteral(value=0)),
                            LessEqual(lhs=DimRef(argument="q", axis=0), rhs=IntLiteral(value=2)),
                            GreaterThan(lhs=DimRef(argument="q", axis=1), rhs=IntLiteral(value=0)),
                            LessEqual(lhs=DimRef(argument="q", axis=1), rhs=IntLiteral(value=128)),
                            Eq(lhs=DimRef(argument="q", axis=2), rhs=DimRef(argument="q", axis=1)),
                            GreaterThan(lhs=DimRef(argument="q", axis=3), rhs=IntLiteral(value=0)),
                            LessEqual(lhs=DimRef(argument="q", axis=3), rhs=IntLiteral(value=8)),
                            Or(
                                operands=(
                                    Eq(lhs=DimRef(argument="q", axis=4), rhs=IntLiteral(value=32)),
                                    Eq(lhs=DimRef(argument="q", axis=4), rhs=IntLiteral(value=64)),
                                )
                            ),
                            Eq(lhs=DimRef(argument="k", axis=0), rhs=DimRef(argument="q", axis=0)),
                            Eq(lhs=DimRef(argument="k", axis=1), rhs=DimRef(argument="q", axis=1)),
                            Eq(lhs=DimRef(argument="k", axis=2), rhs=DimRef(argument="q", axis=2)),
                            Eq(lhs=DimRef(argument="k", axis=3), rhs=DimRef(argument="q", axis=3)),
                            Eq(lhs=DimRef(argument="k", axis=4), rhs=DimRef(argument="q", axis=4)),
                            Eq(lhs=DimRef(argument="v", axis=0), rhs=DimRef(argument="q", axis=0)),
                            Eq(lhs=DimRef(argument="v", axis=1), rhs=DimRef(argument="q", axis=1)),
                            Eq(lhs=DimRef(argument="v", axis=2), rhs=DimRef(argument="q", axis=2)),
                            Eq(lhs=DimRef(argument="v", axis=3), rhs=DimRef(argument="q", axis=3)),
                            Eq(lhs=DimRef(argument="v", axis=4), rhs=DimRef(argument="q", axis=4)),
                            Eq(
                                lhs=DimRef(argument="bias", axis=0),
                                rhs=DimRef(argument="q", axis=0),
                            ),
                            Eq(
                                lhs=DimRef(argument="bias", axis=1),
                                rhs=DimRef(argument="q", axis=1),
                            ),
                            Eq(
                                lhs=DimRef(argument="bias", axis=2),
                                rhs=DimRef(argument="q", axis=3),
                            ),
                            Eq(
                                lhs=DimRef(argument="bias", axis=3),
                                rhs=DimRef(argument="q", axis=2),
                            ),
                            Eq(
                                lhs=DimRef(argument="bias", axis=4),
                                rhs=DimRef(argument="q", axis=2),
                            ),
                            Eq(
                                lhs=DimRef(argument="mask", axis=0),
                                rhs=DimRef(argument="q", axis=0),
                            ),
                            Eq(
                                lhs=DimRef(argument="mask", axis=1),
                                rhs=DimRef(argument="q", axis=1),
                            ),
                            Eq(
                                lhs=DimRef(argument="mask", axis=2),
                                rhs=DimRef(argument="q", axis=2),
                            ),
                        )
                    ),
                    code="TRIANGLE_ATTENTION_SHAPES",
                    message="requires dense B,N,N,H,D attention with B<=2, N<=128, H<=8, and D in {32,64}",
                ),
                DimensionConstraint(
                    predicate=IsFinite(
                        value=ScalarRef(argument="scale", value_type=ScalarType.FLOAT)
                    ),
                    code="SCALE_FINITE",
                    message="scale must be finite",
                ),
            ),
            graph_capture_safe=False,
            training_capable=True,
            tensor_constraints=(
                TensorCapabilityConstraint(
                    argument="q",
                    dtypes=("bfloat16",),
                    layouts=("contiguous",),
                    devices=("cuda",),
                    ranks=(5,),
                ),
                TensorCapabilityConstraint(
                    argument="k",
                    dtypes=("bfloat16",),
                    layouts=("contiguous",),
                    devices=("cuda",),
                    ranks=(5,),
                ),
                TensorCapabilityConstraint(
                    argument="v",
                    dtypes=("bfloat16",),
                    layouts=("contiguous",),
                    devices=("cuda",),
                    ranks=(5,),
                ),
                TensorCapabilityConstraint(
                    argument="bias",
                    dtypes=("bfloat16",),
                    layouts=("contiguous",),
                    devices=("cuda",),
                    ranks=(5,),
                ),
                TensorCapabilityConstraint(
                    argument="mask",
                    dtypes=("bool",),
                    layouts=("contiguous",),
                    devices=("cuda",),
                    ranks=(3,),
                ),
            ),
        ),
        priority=100,
    ),
)
