from __future__ import annotations

import inspect

import pytest
import torch

from kernels.api import AutogradPolicy, ShapeOf, ShapeTuple
from kernels.pairformer.triangle_attention import dispatch as dispatch_module
from kernels.pairformer.triangle_attention.dispatch import (
    FallbackPolicy,
    NativeOperatorUnavailable,
    triangle_attention,
)
from kernels.pairformer.triangle_attention.reference import (
    fake,
    triangle_attention_reference,
)
from kernels.pairformer.triangle_attention.spec import IMPLEMENTATION_SPECS, KERNEL_SPEC
from kernels.pairformer.triangle_attention.tilelang import (
    TRIANGLE_ATTENTION_PROFILES,
    build_backward_program_group,
    build_forward_program,
    build_forward_program_group,
    build_tilelang_program,
)


def _explicit_reference(q, k, v, bias, mask, scale):
    output = torch.zeros_like(q)
    expanded_bias = bias.expand(*q.shape[:-4], q.shape[-4], q.shape[-2], q.shape[-3], q.shape[-3])
    batch_shape = q.shape[:-4]
    for flat_batch in range(max(1, int(torch.tensor(batch_shape).prod()))):
        batch_index = () if not batch_shape else tuple(int(index) for index in torch.unravel_index(torch.tensor(flat_batch), batch_shape))
        for anchor in range(q.shape[-4]):
            valid = torch.nonzero(mask[batch_index + (anchor,)], as_tuple=False).flatten()
            for query in range(q.shape[-3]):
                for head in range(q.shape[-2]):
                    if valid.numel() == 0:
                        continue
                    scores = torch.stack([
                        torch.dot(q[batch_index + (anchor, query, head)], k[batch_index + (anchor, source, head)]) * scale
                        + expanded_bias[batch_index + (anchor, head, query, source)]
                        for source in valid.tolist()
                    ])
                    weights = torch.softmax(scores, dim=0)
                    output[batch_index + (anchor, query, head)] = torch.sum(
                        weights[:, None] * v[batch_index + (anchor, valid, head, slice(None))], dim=0
                    )
    return output


def _inputs(*, dtype=torch.float64):
    torch.manual_seed(7)
    q = torch.randn(2, 3, 3, 2, 4, dtype=dtype)
    k = torch.randn_like(q)
    v = torch.randn_like(q)
    bias = torch.randn(3, 1, 3, 3, dtype=dtype)
    mask = torch.tensor([
        [[True, False, True], [False, False, False], [True, True, False]],
        [[False, True, True], [True, False, False], [True, True, True]],
    ])
    return q, k, v, bias, mask


def test_reference_matches_explicit_attention_and_broadcast_bias():
    q, k, v, bias, mask = _inputs()
    torch.testing.assert_close(
        triangle_attention_reference(q, k, v, bias, mask, 0.37),
        _explicit_reference(q, k, v, bias, mask, 0.37),
        rtol=1e-12,
        atol=1e-12,
    )


def test_all_masked_rows_and_masked_nan_values_are_exact_zero():
    q, k, v, bias, mask = _inputs(dtype=torch.float32)
    v = v.clone()
    v[0, 1] = torch.nan
    output = triangle_attention_reference(q, k, v, bias, mask, 0.5)
    assert torch.equal(output[0, 1], torch.zeros_like(output[0, 1]))
    assert torch.isfinite(output).all()


def test_fake_preserves_metadata_and_reference_gradients_cover_named_inputs():
    q, k, v, bias, mask = _inputs()
    assert fake(q, k, v, bias, mask, 0.5).shape == q.shape
    q, k, v, bias = (tensor.requires_grad_(True) for tensor in (q, k, v, bias))
    gradients = torch.autograd.grad(
        triangle_attention_reference(q, k, v, bias, mask, 0.5).square().sum(),
        (q, k, v, bias),
    )
    assert all(torch.isfinite(gradient).all() for gradient in gradients)


def test_required_spec_has_saved_lse_delta_workspace_and_named_gradients():
    assert KERNEL_SPEC.autograd_policy is AutogradPolicy.REQUIRED
    assert KERNEL_SPEC.composite is None
    assert isinstance(KERNEL_SPEC.forward.outputs[0].shape, ShapeOf)
    assert isinstance(KERNEL_SPEC.forward.outputs[1].shape, ShapeTuple)
    assert KERNEL_SPEC.forward.outputs[1].initialization.mode == "negative_infinity"
    assert tuple(output.name for output in KERNEL_SPEC.forward.outputs) == ("output", "lse")
    assert all(output.saved_for_backward for output in KERNEL_SPEC.forward.outputs)
    assert tuple(node.name for node in KERNEL_SPEC.forward.program_group.nodes) == ("forward",)
    assert {node.name for node in KERNEL_SPEC.backward.program_group.nodes} == {
        "delta", "dbias", "dk", "dq", "dv"
    }
    assert tuple(workspace.name for workspace in KERNEL_SPEC.backward.program_group.workspaces) == ("delta",)
    assert {gradient.input_name for gradient in KERNEL_SPEC.backward.gradients} == {"q", "k", "v", "bias"}
    assert all(gradient.optional for gradient in KERNEL_SPEC.backward.gradients)
    assert KERNEL_SPEC.backward.supports_double_backward is False


def test_logical_descriptors_exactly_match_program_groups():
    assert build_forward_program_group() == {
        "phase": "forward",
        "logical_symbol": "mindclade_tilelang_triangle_attention_fwd_launch",
        "execution_order": ("forward",),
        "workspaces": (),
        "version": 1,
    }
    assert build_backward_program_group() == {
        "phase": "backward",
        "logical_symbol": "mindclade_tilelang_triangle_attention_bwd_launch",
        "execution_order": ("delta", "dbias", "dk", "dq", "dv"),
        "workspaces": ("delta",),
        "version": 1,
    }


def test_candidates_are_independent_by_architecture_and_dtype():
    assert {(item.envelope.architectures, item.envelope.dtypes) for item in IMPLEMENTATION_SPECS} == {
        (("sm90a",), ("float16",)),
        (("sm90a",), ("bfloat16",)),
        (("sm100a",), ("float16",)),
        (("sm100a",), ("bfloat16",)),
    }
    assert all(item.operation == "triangle_attention" for item in IMPLEMENTATION_SPECS)


def test_facade_materializes_static_native_layout_and_hides_lse(monkeypatch):
    q, k, v, bias, mask = _inputs(dtype=torch.float32)
    captured = {}

    def native(q_, k_, v_, bias_, mask_, scale_):
        captured.update(q=q_, bias=bias_, mask=mask_, scale=scale_)
        return q_.clone(), torch.zeros(q_.shape[0], q_.shape[2], 32, dtype=torch.float32)

    monkeypatch.setattr(dispatch_module, "_native_operator", lambda: native)
    output = triangle_attention(q, k, v, bias, mask, 0.5)
    assert output.shape == q.shape
    assert captured["q"].shape == (6, 3, 2, 4)
    assert captured["bias"].shape == (6, 2, 3, 3)
    assert captured["mask"].shape == (6, 3, 3)
    assert captured["bias"].is_contiguous()
    assert captured["mask"].is_contiguous()


def test_reference_fallback_is_explicit(monkeypatch):
    q, k, v, bias, mask = _inputs(dtype=torch.float32)
    monkeypatch.setattr(dispatch_module, "_native_operator", lambda: None)
    with pytest.raises(NativeOperatorUnavailable):
        triangle_attention(q, k, v, bias, mask, 0.5)
    torch.testing.assert_close(
        triangle_attention(q, k, v, bias, mask, 0.5, fallback=FallbackPolicy.REFERENCE),
        triangle_attention_reference(q, k, v, bias, mask, 0.5),
    )


def test_profiles_are_bounded_and_builder_rejects_unqualified_target():
    assert 1 <= len(TRIANGLE_ATTENTION_PROFILES) <= 8
    with pytest.raises(ValueError, match="explicit cuda target"):
        build_tilelang_program(
            target="auto", architecture="sm90a", batch=1, n=32,
            heads=4, head_dim=32, dtype="float16", threads=64,
        )


def test_forward_builder_uses_one_pass_online_softmax_without_materialization():
    source = inspect.getsource(build_forward_program)
    assert source.count("for key_index in T.serial(n)") == 1
    assert "old_scale = T.exp(row_max[0] - next_max)" in source
    assert "new_scale = T.exp(score[0] - next_max)" in source
    assert "probability_numerator" not in source


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
    requests = {
        node.name: sum(binding.source is ProgramBindingSource.GRADIENT_REQUEST for binding in node.bindings)
        for node in KERNEL_SPEC.backward.program_group.nodes
    }
    assert requests == {"delta": 0, "dbias": 1, "dk": 1, "dq": 1, "dv": 1}

def test_runtime_workload_contract_is_exact():
    from kernels.pairformer.triangle_attention.spec import KERNEL_SPEC

    workload = KERNEL_SPEC.runtime_workload
    assert tuple((binding.name, binding.value.argument, binding.value.axis) for binding in workload.dimensions) == (
        ("batch", "q", 0), ("head_dim", "q", 3),
        ("heads", "q", 2), ("n", "q", 1),
    )
    assert workload.input_dtype.argument == "q"
    assert workload.layout == "contiguous"
    assert workload.mode_selector is None
    assert workload.attributes == ()
