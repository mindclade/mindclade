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
            shape=ConcatShape((ShapePrefix("left", 3), ShapeTuple((DimRef("left", -2), DimRef("left", -2), DimRef("left", -1), DimRef("right", -1))))),
            dtype=DTypeRef("left"), device=DeviceRef("left"),
            semantic_axes=("batch_prefix", "left_node", "right_node", "left_channel", "right_channel"),
            visible_in_facade=True, saved_for_backward=False,
        ),),
    ),
    backward=None, autograd_policy=AutogradPolicy.COMPOSITE,
    composite=CompositeAutogradSpec(
        decomposition="kernels.pairformer.outer_product_mean.reference:composite_backward",
        source_digest="sha256:9f6694db0522ff7437948081c5248c3bdf32da9a7d2d64578bf832485d137b36", runtime_envelope="pytorch>=2.10,<2.11",
        gradients=(GradientSpec("left", "grad_left"), GradientSpec("right", "grad_right"), GradientSpec("mask", "grad_mask")),
        supports_double_backward=False,
    ),
    effects=EffectSpec(),
    launch=LaunchContract(graph_capture_safe=False, determinism=DeterminismClass.CONDITIONALLY_DETERMINISTIC),
)
