from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
import torch
from torch._subclasses.fake_tensor import FakeTensor, FakeTensorMode

from kernels.api import AutogradPolicy, ShapeOf
from kernels.pairformer.triangle_attention import dispatch as dispatch_module
from kernels.pairformer.triangle_attention.dispatch import (
    NativeOperatorUnavailable,
    ReferenceFallback,
    triangle_attention,
)
from kernels.pairformer.triangle_attention.reference import (
    composite_backward,
    fake,
    setup_context,
    triangle_attention_reference,
)
from kernels.pairformer.triangle_attention.spec import KERNEL_SPEC
from kernels.pairformer.triangle_attention.tilelang import (
    TRIANGLE_ATTENTION_PROFILES,
    build_tilelang_program,
)


def _explicit_reference(q, k, v, bias, mask, scale):
    output = torch.zeros_like(q)
    expanded_bias = bias.expand(
        *q.shape[:-4], q.shape[-4], q.shape[-2], q.shape[-3], q.shape[-3]
    )
    batch_shape = q.shape[:-4]
    for flat_batch in range(max(1, int(torch.tensor(batch_shape).prod()))):
        batch_index = (
            ()
            if not batch_shape
            else tuple(
                int(index)
                for index in torch.unravel_index(torch.tensor(flat_batch), batch_shape)
            )
        )
        for i in range(q.shape[-4]):
            valid = torch.nonzero(mask[batch_index + (i,)], as_tuple=False).flatten()
            for j in range(q.shape[-3]):
                for h in range(q.shape[-2]):
                    if valid.numel() == 0:
                        continue
                    scores = torch.stack(
                        [
                            torch.dot(
                                q[batch_index + (i, j, h)],
                                k[batch_index + (i, source, h)],
                            )
                            * scale
                            + expanded_bias[batch_index + (i, h, j, source)]
                            for source in valid.tolist()
                        ]
                    )
                    weights = torch.softmax(scores, dim=0)
                    output[batch_index + (i, j, h)] = torch.sum(
                        weights[:, None]
                        * v[batch_index + (i, valid, h, slice(None))],
                        dim=0,
                    )
    return output


def _inputs(*, dtype=torch.float64):
    torch.manual_seed(7)
    q = torch.randn(2, 3, 3, 2, 4, dtype=dtype)
    k = torch.randn_like(q)
    v = torch.randn_like(q)
    bias = torch.randn(3, 1, 3, 3, dtype=dtype)
    mask = torch.tensor(
        [
            [[True, False, True], [False, False, False], [True, True, False]],
            [[False, True, True], [True, False, False], [True, True, True]],
        ]
    )
    return q, k, v, bias, mask


def test_reference_matches_explicit_attention_and_broadcast_bias():
    q, k, v, bias, mask = _inputs()
    actual = triangle_attention_reference(q, k, v, bias, mask, 0.5)
    expected = _explicit_reference(q, k, v, bias, mask, 0.5)
    torch.testing.assert_close(actual, expected, rtol=1e-12, atol=1e-12)


def test_all_masked_rows_and_masked_nan_values_are_exact_zero():
    q, k, v, bias, mask = _inputs(dtype=torch.float32)
    v = v.clone()
    v[0, 1] = torch.nan
    output = triangle_attention_reference(q, k, v, bias, mask, 0.5)
    assert torch.equal(output[0, 1], torch.zeros_like(output[0, 1]))
    assert torch.isfinite(output).all()


def test_contract_rejects_invalid_pair_mask_and_bias_shapes():
    q, k, v, bias, mask = _inputs(dtype=torch.float32)
    with pytest.raises(ValueError, match="equal pair dimensions"):
        triangle_attention_reference(q[:, :, :2], k[:, :, :2], v[:, :, :2], bias, mask, 0.5)
    with pytest.raises(ValueError, match="mask must have shape"):
        triangle_attention_reference(q, k, v, bias, mask[:, :2], 0.5)
    with pytest.raises(ValueError, match="bias must be broadcastable"):
        triangle_attention_reference(q, k, v, torch.empty(5, dtype=q.dtype), mask, 0.5)


def test_fake_tensor_contract_preserves_shape_dtype_and_device():
    mode = FakeTensorMode()
    with mode:
        q = torch.empty(2, 3, 3, 2, 4)
        k = torch.empty_like(q)
        v = torch.empty_like(q)
        bias = torch.empty(3, 1, 3, 3)
        mask = torch.empty(2, 3, 3, dtype=torch.bool)
        output = fake(q, k, v, bias, mask, 0.5)
    assert isinstance(output, FakeTensor)
    assert output.shape == q.shape
    assert output.dtype == q.dtype
    assert output.device == q.device


def test_reference_and_composite_backward_cover_q_k_v_and_bias_gradients():
    q, k, v, bias, mask = _inputs()
    q, k, v, bias = (tensor.requires_grad_(True) for tensor in (q, k, v, bias))
    output = triangle_attention_reference(q, k, v, bias, mask, 0.5)
    grad_output = torch.randn_like(output)
    expected = torch.autograd.grad(output, (q, k, v, bias), grad_output)

    class Context:
        needs_input_grad = (True, True, True, True, False, False)

        def save_for_backward(self, *tensors):
            self.saved_tensors = tensors

    context = Context()
    setup_context(context, (q, k, v, bias, mask, 0.5), output)
    actual = composite_backward(context, grad_output)
    for actual_gradient, expected_gradient in zip(actual[:4], expected, strict=True):
        torch.testing.assert_close(actual_gradient, expected_gradient, rtol=1e-10, atol=1e-10)
    assert actual[4:] == (None, None)


def test_spec_is_composite_unpromoted_and_reference_digest_is_exact():
    source = Path(__file__).resolve().parents[1] / "spec.py"
    parsed = KERNEL_SPEC
    assert parsed == KERNEL_SPEC
    assert parsed.autograd_policy is AutogradPolicy.COMPOSITE
    assert parsed.backward is None
    assert parsed.forward.symbol == "mindclade_tilelang_triangle_attention_fwd_launch"
    assert isinstance(parsed.forward.outputs[0].shape, ShapeOf)
    assert parsed.launch.graph_capture_safe is False
    assert parsed.effects.mutates_inputs == ()
    assert parsed.composite is not None
    assert "promotion=unpromoted" in parsed.composite.runtime_envelope
    reference = source.with_name("reference.py")
    digest = "sha256:" + hashlib.sha256(reference.read_bytes()).hexdigest()
    assert parsed.composite.source_digest == digest
    assert tuple(item.input_name for item in parsed.composite.gradients) == (
        "q", "k", "v", "bias"
    )


def test_facade_materializes_dense_bias_before_native_dispatch(monkeypatch):
    q, k, v, bias, mask = _inputs(dtype=torch.float32)
    captured = {}

    def native(q_, k_, v_, bias_, mask_, scale_):
        captured.update(q=q_, k=k_, v=v_, bias=bias_, mask=mask_, scale=scale_)
        return q_.clone()

    monkeypatch.setattr(dispatch_module, "_native_operator", lambda: native)
    output = triangle_attention(q, k, v, bias, mask, 0.5)
    assert output.shape == q.shape
    assert captured["bias"].shape == (2, 3, 2, 3, 3)
    assert captured["bias"].is_contiguous()
    assert captured["q"].shape == (2, 3, 3, 2, 4)


def test_reference_fallback_requires_explicit_caller_policy(monkeypatch):
    q, k, v, bias, mask = _inputs(dtype=torch.float32)
    monkeypatch.setattr(dispatch_module, "_native_operator", lambda: None)
    with pytest.raises(NativeOperatorUnavailable):
        triangle_attention(q, k, v, bias, mask, 0.5)
    expected = triangle_attention_reference(q, k, v, bias, mask, 0.5)
    actual = triangle_attention(
        q, k, v, bias, mask, 0.5, fallback=ReferenceFallback.REFERENCE
    )
    torch.testing.assert_close(actual, expected)


def test_profiles_are_bounded_and_builder_rejects_unqualified_shapes():
    assert 1 <= len(TRIANGLE_ATTENTION_PROFILES) <= 8
    with pytest.raises(ValueError, match="target must be exactly"):
        build_tilelang_program(
            target="auto", batch=1, n=32, heads=4, head_dim=32,
            dtype="float16", threads=64,
        )
    with pytest.raises(ValueError, match="head_dim"):
        build_tilelang_program(
            target="cuda", batch=1, n=32, heads=4, head_dim=48,
            dtype="float16", threads=64,
        )
