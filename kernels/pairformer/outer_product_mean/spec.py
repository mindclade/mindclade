# Copyright (c) 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

"""Declarative integration contract for outer product mean."""

from kernels.api import (
    AutogradPolicy, CapabilityEnvelope, CompositeAutogradSpec, ConcatShape,
    DeviceRef, DimensionConstraint, DimRef, DTypeRef, EffectSpec, Eq,
    FloatLiteral, ForwardSpec, GradientSpec, GreaterThan, ImplementationSpec,
    ImplementationTier, IntLiteral, IsFinite, KernelSpec, LaunchContract,
    DeterminismClass, OutputSpec, ScalarRef, ScalarType, ShapePrefix,
    ShapeTuple, TensorCapabilityConstraint,
)

KERNEL_SPEC = KernelSpec(
    name="outer_product_mean", namespace="mindclade", family="pairformer",
    source="pairformer/outer_product_mean/spec.py",
    operator_schema="outer_product_mean(Tensor left, Tensor right, Tensor mask, float epsilon) -> Tensor output",
    facade_outputs=("output",), fake=None,
    forward=ForwardSpec(
        schema="_outer_product_mean_fwd(Tensor left, Tensor right, Tensor mask, float epsilon) -> Tensor output",
        builder="kernels.pairformer.outer_product_mean.tilelang:build_tilelang_program",
        symbol="mindclade_tilelang_outer_product_mean_fwd_launch",
        outputs=(OutputSpec(
            name="output",
            shape=ConcatShape(parts=(
                ShapePrefix(argument="left", trailing_rank=3),
                ShapeTuple(dimensions=(
                    DimRef(argument="left", axis=-2),
                    DimRef(argument="left", axis=-2),
                    DimRef(argument="left", axis=-1),
                    DimRef(argument="right", axis=-1),
                )),
            )),
            dtype=DTypeRef(argument="left"), device=DeviceRef(argument="left"),
            semantic_axes=("batch_prefix", "left_node", "right_node", "left_channel", "right_channel"),
            visible_in_facade=True, saved_for_backward=False,
        ),),
    ),
    backward=None, autograd_policy=AutogradPolicy.COMPOSITE,
    composite=CompositeAutogradSpec(
        decomposition="kernels.pairformer.outer_product_mean.reference:outer_product_mean_reference",
        source_digest="sha256:9f6694db0522ff7437948081c5248c3bdf32da9a7d2d64578bf832485d137b36", runtime_envelope="pytorch>=2.10,<2.11",
        gradients=(
            GradientSpec(input_name="left", output_name="grad_left"),
            GradientSpec(input_name="right", output_name="grad_right"),
            GradientSpec(input_name="mask", output_name="grad_mask"),
        ),
        supports_double_backward=False,
        setup_context="kernels.pairformer.outer_product_mean.reference:setup_context",
        backward="kernels.pairformer.outer_product_mean.reference:composite_backward",
    ),
    effects=EffectSpec(),
    launch=LaunchContract(graph_capture_safe=False, determinism=DeterminismClass.CONDITIONALLY_DETERMINISTIC),
)

IMPLEMENTATION_SPECS = (
    ImplementationSpec(
        operation="mindclade::outer_product_mean",
        name="outer_product_mean_sm90_b1_s64_n32_cl64_cr64_fp16",
        family="pairformer",
        backend="tilelang",
        builder="kernels.pairformer.outer_product_mean.tilelang:build_tilelang_program",
        version=1,
        tier=ImplementationTier.SPECIALIZED,
        requires=("cuda", "sm90", "tilelang-0.1.13"),
        envelope=CapabilityEnvelope(
            architectures=("sm90",),
            dtypes=("float16",),
            layouts=("contiguous",),
            modes=("default",),
            constraints=(
                DimensionConstraint(
                    predicate=Eq(lhs=DimRef(argument="left", axis=0), rhs=IntLiteral(value=1)),
                    code="LEFT_BATCH_EXACT",
                    message="left batch dimension must equal 1",
                ),
                DimensionConstraint(
                    predicate=Eq(lhs=DimRef(argument="left", axis=1), rhs=IntLiteral(value=64)),
                    code="LEFT_SEQUENCE_EXACT",
                    message="left sequence dimension must equal 64",
                ),
                DimensionConstraint(
                    predicate=Eq(lhs=DimRef(argument="left", axis=2), rhs=IntLiteral(value=32)),
                    code="LEFT_NODES_EXACT",
                    message="left node dimension must equal 32",
                ),
                DimensionConstraint(
                    predicate=Eq(lhs=DimRef(argument="left", axis=3), rhs=IntLiteral(value=64)),
                    code="LEFT_CHANNELS_EXACT",
                    message="left channel dimension must equal 64",
                ),
                DimensionConstraint(
                    predicate=Eq(lhs=DimRef(argument="right", axis=0), rhs=IntLiteral(value=1)),
                    code="RIGHT_BATCH_EXACT",
                    message="right batch dimension must equal 1",
                ),
                DimensionConstraint(
                    predicate=Eq(lhs=DimRef(argument="right", axis=1), rhs=IntLiteral(value=64)),
                    code="RIGHT_SEQUENCE_EXACT",
                    message="right sequence dimension must equal 64",
                ),
                DimensionConstraint(
                    predicate=Eq(lhs=DimRef(argument="right", axis=2), rhs=IntLiteral(value=32)),
                    code="RIGHT_NODES_EXACT",
                    message="right node dimension must equal 32",
                ),
                DimensionConstraint(
                    predicate=Eq(lhs=DimRef(argument="right", axis=3), rhs=IntLiteral(value=64)),
                    code="RIGHT_CHANNELS_EXACT",
                    message="right channel dimension must equal 64",
                ),
                DimensionConstraint(
                    predicate=Eq(lhs=DimRef(argument="mask", axis=0), rhs=IntLiteral(value=1)),
                    code="MASK_BATCH_EXACT",
                    message="mask batch dimension must equal 1",
                ),
                DimensionConstraint(
                    predicate=Eq(lhs=DimRef(argument="mask", axis=1), rhs=IntLiteral(value=64)),
                    code="MASK_SEQUENCE_EXACT",
                    message="mask sequence dimension must equal 64",
                ),
                DimensionConstraint(
                    predicate=Eq(lhs=DimRef(argument="mask", axis=2), rhs=IntLiteral(value=32)),
                    code="MASK_NODES_EXACT",
                    message="mask node dimension must equal 32",
                ),
                DimensionConstraint(
                    predicate=IsFinite(
                        value=ScalarRef(argument="epsilon", value_type=ScalarType.FLOAT)
                    ),
                    code="EPSILON_FINITE",
                    message="epsilon must be finite",
                ),
                DimensionConstraint(
                    predicate=GreaterThan(
                        lhs=ScalarRef(argument="epsilon", value_type=ScalarType.FLOAT),
                        rhs=FloatLiteral(value=0.0),
                    ),
                    code="EPSILON_POSITIVE",
                    message="epsilon must be greater than zero",
                ),
            ),
            graph_capture_safe=False,
            training_capable=False,
            tensor_constraints=(
                TensorCapabilityConstraint(
                    argument="left", dtypes=("float16",), layouts=("contiguous",),
                    devices=("cuda",), ranks=(4,),
                ),
                TensorCapabilityConstraint(
                    argument="right", dtypes=("float16",), layouts=("contiguous",),
                    devices=("cuda",), ranks=(4,),
                ),
                TensorCapabilityConstraint(
                    argument="mask", dtypes=("float16",), layouts=("contiguous",),
                    devices=("cuda",), ranks=(3,),
                ),
            ),
        ),
        priority=0,
    ),
)
