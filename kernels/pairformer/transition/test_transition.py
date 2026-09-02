from __future__ import annotations

import pytest
import torch

from kernels.api import AutogradPolicy, EvaluationContext, TensorMetadata
from kernels.pairformer.transition.dispatch import transition
from kernels.pairformer.transition.reference import (
    transition_reference,
    transition_with_saved,
)
from kernels.pairformer.transition.spec import KERNEL_SPEC
from kernels.pairformer.transition.tilelang import build_forward, build_forward_program


def inputs(dtype: torch.dtype = torch.float64):
    gate = torch.randn(2, 5, 8, dtype=dtype)
    value = torch.randn_like(gate)
    weight = torch.randn(8, 4, dtype=dtype)
    bias = torch.randn(4, dtype=dtype)
    mask = torch.rand(2, 5, dtype=dtype)
    return gate, value, weight, bias, mask


def test_reference_formula_saved_output_and_all_gradients() -> None:
    gate, value, weight, bias, mask = inputs()
    expected_pre_mask = (torch.nn.functional.silu(gate) * value) @ weight + bias
    expected = expected_pre_mask * mask.unsqueeze(-1)
    output, pre_mask = transition_with_saved(gate, value, weight, bias, mask)
    torch.testing.assert_close(output, expected)
    torch.testing.assert_close(pre_mask, expected_pre_mask)
    differentiable = tuple(
        tensor.requires_grad_(True) for tensor in (gate, value, weight, bias, mask)
    )
    assert torch.autograd.gradcheck(
        lambda g, v, w, b, m: transition_reference(g, v, w, b, m),
        differentiable,
    )


def test_required_contract_shape_and_named_gradient_coverage() -> None:
    context = EvaluationContext(
        {
            "gate": TensorMetadata((2, 7, 16), "bf16", "cuda"),
            "output_weight": TensorMetadata((16, 6), "bf16", "cuda"),
        }
    )
    assert KERNEL_SPEC.forward.outputs[0].shape.evaluate(context) == (2, 7, 6)
    assert KERNEL_SPEC.autograd_policy is AutogradPolicy.REQUIRED
    assert KERNEL_SPEC.backward is not None
    assert tuple(gradient.input_name for gradient in KERNEL_SPEC.backward.gradients) == (
        "gate",
        "value",
        "output_weight",
        "output_bias",
        "mask",
    )
    assert KERNEL_SPEC.forward.outputs[1].saved_for_backward
    assert not KERNEL_SPEC.backward.supports_double_backward


def test_dispatch_fallback_and_build_contract_are_explicit() -> None:
    gate, value, weight, bias, mask = inputs(torch.float32)
    result = transition(
        gate, value, weight, bias, mask, fallback="reference"
    )
    torch.testing.assert_close(
        result, transition_reference(gate, value, weight, bias, mask)
    )
    descriptor = build_forward()
    assert descriptor["execution_order"] == ("transition_forward",)
    assert descriptor["logical_symbol"].endswith("_fwd_launch")
    with pytest.raises(ValueError, match="target='cuda'"):
        build_forward_program(
            target="cpu",
            architecture="sm90a",
            dtype="bfloat16",
            batch_size=1,
            rows=2,
            hidden_channels=16,
            output_channels=8,
        )



def test_callable_nodes_split_independently_optional_gradients():
    from kernels.api import ProgramArtifactBoundary, ProgramBindingSource, ProgramEntryABI

    assert tuple(node.name for node in KERNEL_SPEC.backward.program_group.nodes) == (
        "grad_bias", "grad_gate", "grad_mask", "grad_value", "grad_weight"
    )
    groups = (KERNEL_SPEC.forward.program_group, KERNEL_SPEC.backward.program_group)
    for group in groups:
        assert group is not None
        for node in group.nodes:
            assert node.entry_symbol == "call"
            assert node.entry_abi is ProgramEntryABI.TILELANG_0_1_13_HOST_CALL
            assert node.artifact_boundary is ProgramArtifactBoundary.NODE_CONTENT_ADDRESSED_DSO
            assert sum(binding.source is ProgramBindingSource.CURRENT_STREAM for binding in node.bindings) == 1
    assert all(
        sum(binding.source is ProgramBindingSource.GRADIENT_REQUEST for binding in node.bindings) == 1
        for node in KERNEL_SPEC.backward.program_group.nodes
    )

def test_runtime_workload_contract_is_exact():
    from kernels.pairformer.transition.spec import KERNEL_SPEC

    workload = KERNEL_SPEC.runtime_workload
    assert tuple((binding.name, binding.value.argument, binding.value.axis) for binding in workload.dimensions) == (
        ("batch_size", "gate", 0), ("hidden_channels", "gate", 2),
        ("output_channels", "output_weight", 1), ("rows", "gate", 1),
    )
    assert workload.input_dtype.argument == "gate"
    assert workload.layout == "contiguous"
    assert workload.mode_selector is None
    assert workload.attributes == ()
