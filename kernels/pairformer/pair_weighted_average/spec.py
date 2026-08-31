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
            shape=ConcatShape(parts=(
                ShapePrefix(argument="value", trailing_rank=2),
                ShapeTuple(dimensions=(
                    DimRef(argument="value", axis=-2),
                    DimRef(argument="weights", axis=-1),
                    DimRef(argument="value", axis=-1),
                )),
            )),
            dtype=DTypeRef(argument="value"), device=DeviceRef(argument="value"),
            semantic_axes=("batch_prefix", "destination", "head", "channel"),
            visible_in_facade=True, saved_for_backward=False,
        ),),
    ),
    backward=None, autograd_policy=AutogradPolicy.COMPOSITE,
    composite=CompositeAutogradSpec(
        decomposition="kernels.pairformer.pair_weighted_average.reference:pair_weighted_average_reference",
        source_digest="sha256:884570c0f5747956d21e50135045bdc88586764b815ae07b8a11a4196e3ce22e", runtime_envelope="pytorch>=2.10,<2.11",
        gradients=(
            GradientSpec(input_name="value", output_name="grad_value"),
            GradientSpec(input_name="weights", output_name="grad_weights"),
        ),
        supports_double_backward=False,
        setup_context="kernels.pairformer.pair_weighted_average.reference:setup_context",
        backward="kernels.pairformer.pair_weighted_average.reference:composite_backward",
    ),
    effects=EffectSpec(),
    launch=LaunchContract(graph_capture_safe=False, determinism=DeterminismClass.CONDITIONALLY_DETERMINISTIC),
)

IMPLEMENTATION_SPECS = ()
