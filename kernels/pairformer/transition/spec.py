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
            name="output", shape=ShapeTuple(dimensions=(
                DimRef(argument="gate", axis=0),
                DimRef(argument="gate", axis=1),
                DimRef(argument="output_weight", axis=1),
            )),
            dtype=DTypeRef(argument="gate"), device=DeviceRef(argument="gate"),
            semantic_axes=("batch", "row", "channel"), visible_in_facade=True, saved_for_backward=False,
        ),),
    ),
    backward=None, autograd_policy=AutogradPolicy.COMPOSITE,
    composite=CompositeAutogradSpec(
        decomposition="kernels.pairformer.transition.reference:transition_reference",
        source_digest="sha256:66ee4727de452b204913aea9afedf38efaf7b744c18d7eaa3bc4d723454a49a2", runtime_envelope="pytorch>=2.10,<2.11",
        gradients=(
            GradientSpec(input_name="gate", output_name="grad_gate"),
            GradientSpec(input_name="value", output_name="grad_value"),
            GradientSpec(input_name="output_weight", output_name="grad_output_weight"),
            GradientSpec(input_name="output_bias", output_name="grad_output_bias"),
        ),
        supports_double_backward=False,
        setup_context="kernels.pairformer.transition.reference:setup_context",
        backward="kernels.pairformer.transition.reference:composite_backward",
    ),
    effects=EffectSpec(),
    launch=LaunchContract(graph_capture_safe=False, determinism=DeterminismClass.CONDITIONALLY_DETERMINISTIC),
)
