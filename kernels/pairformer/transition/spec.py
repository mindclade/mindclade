# Copyright (c) 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

"""Declarative integration contract for Pairformer transition."""

from kernels.api import (
    AutogradPolicy, CompositeAutogradSpec, DeviceRef, DimRef, DTypeRef,
    EffectSpec, ForwardSpec, GradientSpec, KernelSpec, LaunchContract,
    DeterminismClass, OutputSpec, ShapeTuple,
)

KERNEL_SPEC = KernelSpec(
    name="transition", namespace="mindclade", family="pairformer",
    source="pairformer/transition/spec.py",
    operator_schema="transition(Tensor gate, Tensor value, Tensor output_weight, Tensor output_bias, Tensor mask) -> Tensor output",
    facade_outputs=("output",), fake=None,
    forward=ForwardSpec(
        schema="_transition_fwd(Tensor gate, Tensor value, Tensor output_weight, Tensor output_bias, Tensor mask) -> Tensor output",
        builder="kernels.pairformer.transition.tilelang:build_tilelang_program",
        symbol="mindclade_tilelang_transition_fwd_launch",
        outputs=(OutputSpec(
            name="output", shape=ShapeTuple((DimRef("gate", 0), DimRef("gate", 1), DimRef("output_weight", 1))),
            dtype=DTypeRef("gate"), device=DeviceRef("gate"),
            semantic_axes=("batch", "row", "channel"), visible_in_facade=True, saved_for_backward=False,
        ),),
    ),
    backward=None, autograd_policy=AutogradPolicy.COMPOSITE,
    composite=CompositeAutogradSpec(
        decomposition="kernels.pairformer.transition.reference:composite_backward",
        source_digest="sha256:66ee4727de452b204913aea9afedf38efaf7b744c18d7eaa3bc4d723454a49a2", runtime_envelope="pytorch>=2.10,<2.11",
        gradients=(GradientSpec("gate", "grad_gate"), GradientSpec("value", "grad_value"), GradientSpec("output_weight", "grad_output_weight"), GradientSpec("output_bias", "grad_output_bias")),
        supports_double_backward=False,
    ),
    effects=EffectSpec(),
    launch=LaunchContract(graph_capture_safe=False, determinism=DeterminismClass.CONDITIONALLY_DETERMINISTIC),
)
