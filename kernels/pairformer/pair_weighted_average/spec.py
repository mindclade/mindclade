# Copyright (c) 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

"""Declarative integration contract for pair weighted average."""

from kernels.api import (
    AutogradPolicy, CompositeAutogradSpec, ConcatShape, DeviceRef, DimRef,
    DTypeRef, EffectSpec, ForwardSpec, GradientSpec, KernelSpec, LaunchContract,
    DeterminismClass, OutputSpec, ShapePrefix, ShapeTuple,
)

KERNEL_SPEC = KernelSpec(
    name="pair_weighted_average", namespace="mindclade", family="pairformer",
    source="pairformer/pair_weighted_average/spec.py",
    operator_schema="pair_weighted_average(Tensor value, Tensor weights, Tensor mask, float epsilon) -> Tensor output",
    facade_outputs=("output",), fake=None,
    forward=ForwardSpec(
        schema="_pair_weighted_average_fwd(Tensor value, Tensor weights, Tensor mask, float epsilon) -> Tensor output",
        builder="kernels.pairformer.pair_weighted_average.tilelang:build_tilelang_program",
        symbol="mindclade_tilelang_pair_weighted_average_fwd_launch",
        outputs=(OutputSpec(
            name="output",
            shape=ConcatShape((ShapePrefix("value", 2), ShapeTuple((DimRef("value", -2), DimRef("weights", -1), DimRef("value", -1))))),
            dtype=DTypeRef("value"), device=DeviceRef("value"),
            semantic_axes=("batch_prefix", "destination", "head", "channel"),
            visible_in_facade=True, saved_for_backward=False,
        ),),
    ),
    backward=None, autograd_policy=AutogradPolicy.COMPOSITE,
    composite=CompositeAutogradSpec(
        decomposition="kernels.pairformer.pair_weighted_average.reference:composite_backward",
        source_digest="sha256:884570c0f5747956d21e50135045bdc88586764b815ae07b8a11a4196e3ce22e", runtime_envelope="pytorch>=2.10,<2.11",
        gradients=(GradientSpec("value", "grad_value"), GradientSpec("weights", "grad_weights")),
        supports_double_backward=False,
    ),
    effects=EffectSpec(),
    launch=LaunchContract(graph_capture_safe=False, determinism=DeterminismClass.CONDITIONALLY_DETERMINISTIC),
)
