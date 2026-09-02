from __future__ import annotations

import inspect

import pytest

torch = pytest.importorskip("torch")

from kernels.api import AutogradPolicy, ShapeOf
from kernels.pairformer.triangle_multiplication import dispatch as dispatch_module
from kernels.pairformer.triangle_multiplication.dispatch import (
    FallbackPolicy,
    NativeOperatorUnavailable,
    triangle_multiplication,
)
from kernels.pairformer.triangle_multiplication.reference import (
    fake,
    triangle_multiplication_reference,
)
from kernels.pairformer.triangle_multiplication.spec import IMPLEMENTATION_SPECS, KERNEL_SPEC
from kernels.pairformer.triangle_multiplication.tilelang import (
    build_backward_program_group,
    build_forward_program,
    build_forward_program_group,
    build_tilelang_program,
)


def _loop_reference(left, right, mask, outgoing):
    result = torch.zeros_like(left)
    n = left.shape[-2]
    for i in range(n):
        for j in range(n):
            for k in range(n):
                if outgoing:
                    result[..., i, j, :] += left[..., i, k, :] * mask[..., i, k, None] * right[..., j, k, :] * mask[..., j, k, None]
                else:
                    result[..., i, j, :] += left[..., k, i, :] * mask[..., k, i, None] * right[..., k, j, :] * mask[..., k, j, None]
    return result * mask[..., None]


@pytest.mark.parametrize("outgoing", [False, True])
def test_reference_matches_direct_contraction_and_gradcheck(outgoing):
    generator = torch.Generator().manual_seed(7)
    left = torch.randn((1, 3, 3, 4), dtype=torch.float64, generator=generator)
    right = torch.randn((1, 3, 3, 4), dtype=torch.float64, generator=generator)
    mask = torch.tensor([[[1, 1, 0], [1, 1, 1], [0, 1, 1]]], dtype=torch.float64)
    torch.testing.assert_close(
        triangle_multiplication_reference(left, right, mask, outgoing),
        _loop_reference(left, right, mask, outgoing),
    )
    left.requires_grad_(True)
    right.requires_grad_(True)
    assert torch.autograd.gradcheck(
        lambda lhs, rhs: triangle_multiplication_reference(lhs, rhs, mask, outgoing),
        (left, right),
    )


def test_fake_preserves_metadata_and_rejects_invalid_shapes():
    left = torch.empty((2, 3, 3, 4), device="meta")
    mask = torch.empty((2, 3, 3), device="meta")
    output = fake(left, left, mask, True)
    assert output.shape == left.shape
    assert output.dtype == left.dtype
    with pytest.raises(ValueError, match="square"):
        fake(torch.empty((2, 3, 4, 5)), torch.empty((2, 3, 4, 5)), torch.empty((2, 3, 4)), True)


def test_required_spec_is_workspace_free_and_named():
    assert KERNEL_SPEC.autograd_policy is AutogradPolicy.REQUIRED
    assert KERNEL_SPEC.composite is None
    assert isinstance(KERNEL_SPEC.forward.outputs[0].shape, ShapeOf)
    assert KERNEL_SPEC.forward.outputs[0].saved_for_backward is False
    assert tuple(node.name for node in KERNEL_SPEC.forward.program_group.nodes) == ("forward",)
    assert {node.name for node in KERNEL_SPEC.backward.program_group.nodes} == {"dleft", "dright"}
    assert KERNEL_SPEC.forward.program_group.workspaces == ()
    assert KERNEL_SPEC.backward.program_group.workspaces == ()
    assert KERNEL_SPEC.launch.hidden_device_allocation is False
    assert KERNEL_SPEC.launch.graph_capture_safe is True
    assert tuple(item.input_name for item in KERNEL_SPEC.backward.gradients) == ("left", "right")
    assert all(item.optional for item in KERNEL_SPEC.backward.gradients)


def test_logical_descriptors_exactly_match_program_groups():
    assert build_forward_program_group() == {
        "phase": "forward",
        "logical_symbol": "mindclade_tilelang_triangle_multiplication_fwd_launch",
        "execution_order": ("forward",),
        "workspaces": (),
        "version": 1,
    }
    assert build_backward_program_group() == {
        "phase": "backward",
        "logical_symbol": "mindclade_tilelang_triangle_multiplication_bwd_launch",
        "execution_order": ("dleft", "dright"),
        "workspaces": (),
        "version": 1,
    }


def test_candidates_are_independent_by_architecture_and_dtype():
    assert {(item.envelope.architectures, item.envelope.dtypes) for item in IMPLEMENTATION_SPECS} == {
        (("sm90a",), ("float16",)),
        (("sm90a",), ("bfloat16",)),
        (("sm100a",), ("float16",)),
        (("sm100a",), ("bfloat16",)),
    }
    assert all(item.operation == "triangle_multiplication" for item in IMPLEMENTATION_SPECS)


def test_facade_normalizes_mask_before_native_dispatch(monkeypatch):
    left = torch.randn((2, 3, 3, 4), dtype=torch.float32)
    right = torch.randn_like(left)
    mask = torch.ones((2, 3, 3), dtype=torch.bool)
    captured = {}

    def native(left_, right_, mask_, outgoing_):
        captured.update(left=left_, right=right_, mask=mask_, outgoing=outgoing_)
        return left_.clone()

    monkeypatch.setattr(dispatch_module, "_native_operator", lambda: native)
    output = triangle_multiplication(left, right, mask, True)
    assert output.shape == left.shape
    assert captured["mask"].dtype == left.dtype
    assert captured["mask"].is_contiguous()


def test_reference_fallback_requires_explicit_policy(monkeypatch):
    left = torch.randn((1, 2, 2, 2))
    right = torch.randn_like(left)
    mask = torch.ones((1, 2, 2), dtype=torch.bool)
    monkeypatch.setattr(dispatch_module, "_native_operator", lambda: None)
    with pytest.raises(NativeOperatorUnavailable):
        triangle_multiplication(left, right, mask, True)
    torch.testing.assert_close(
        triangle_multiplication(left, right, mask, True, fallback=FallbackPolicy.REFERENCE),
        triangle_multiplication_reference(left, right, mask, True),
    )


def test_builder_rejects_unqualified_target_before_tilelang_import():
    with pytest.raises(ValueError, match="target must be exactly cuda"):
        build_tilelang_program(
            target="auto", architecture="sm90a", batch=1,
            residues=64, channels=64, outgoing=True,
        )


def test_forward_builder_is_tiled_gemm_with_fused_mask_epilogue():
    source = inspect.getsource(build_forward_program)
    assert "T.alloc_shared" in source
    assert "T.Pipelined" in source
    assert "T.gemm(" in source
    assert "transpose_B=True" in source
    assert 'mask[batch_index, row, column]' in source


def test_callable_nodes_use_artifact_scoped_host_call_abi():
    from kernels.api import ProgramArtifactBoundary, ProgramBindingSource, ProgramEntryABI

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
    from kernels.pairformer.triangle_multiplication.spec import KERNEL_SPEC

    workload = KERNEL_SPEC.runtime_workload
    assert tuple((binding.name, binding.value.argument, binding.value.axis) for binding in workload.dimensions) == (
        ("batch", "left", 0), ("channels", "left", 3),
        ("residues", "left", 1),
    )
    assert workload.input_dtype.argument == "left"
    assert workload.layout == "contiguous"
    assert workload.mode_selector == "mode"
    assert workload.attributes == ()
