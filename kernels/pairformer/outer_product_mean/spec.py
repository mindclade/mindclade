# Copyright (c) 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

"""Declarative integration contract for outer product mean."""

from kernels.api import (
    AutogradPolicy, CompositeAutogradSpec, ConcatShape, DeviceRef, DimRef,
    DTypeRef, EffectSpec, ForwardSpec, GradientSpec, KernelSpec, LaunchContract,
    DeterminismClass, OutputSpec, ShapePrefix, ShapeTuple,
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
