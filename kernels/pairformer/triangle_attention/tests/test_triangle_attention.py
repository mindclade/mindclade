# Copyright (c) 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

from __future__ import annotations

from pathlib import Path

import pytest
import torch
from torch._subclasses.fake_tensor import FakeTensor, FakeTensorMode

from kernels.native.codegen.discover import discover_specs
from kernels.pairformer.triangle_attention.tilelang import (
    TRIANGLE_ATTENTION_PROFILES,
    backward,
    build_tilelang_program,
    fake,
    setup_context,
    triangle_attention_reference,
)


def _explicit_reference(q, k, v, bias, mask, scale):
    output = torch.zeros_like(q)
    expanded_bias = bias.expand(*q.shape[:-4], q.shape[-4], q.shape[-2], q.shape[-3], q.shape[-3])
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
                            torch.dot(q[batch_index + (i, j, h)], k[batch_index + (i, source, h)])
                            * scale
                            + expanded_bias[batch_index + (i, h, j, source)]
                            for source in valid.tolist()
                        ]
                    )
                    weights = torch.softmax(scores, dim=0)
                    output[batch_index + (i, j, h)] = torch.sum(
                        weights[:, None] * v[batch_index + (i, valid, h, slice(None))],
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


def test_reference_passes_gradcheck_with_broadcast_bias_and_all_masked_row():
    q, k, v, bias, mask = _inputs()
    tensors = tuple(tensor.requires_grad_(True) for tensor in (q, k, v, bias))
    assert torch.autograd.gradcheck(
        lambda q_, k_, v_, bias_: triangle_attention_reference(
            q_, k_, v_, bias_, mask, 0.5
        ),
        tensors,
        eps=1e-6,
        atol=2e-5,
        rtol=2e-4,
        fast_mode=True,
    )


class _Context:
    needs_input_grad = (True, True, True, True, False, False)

    def save_for_backward(self, *tensors):
        self.saved_tensors = tensors


def test_registered_backward_matches_safe_reference_recomputation():
    q, k, v, bias, mask = _inputs()
    q, k, v, bias = (tensor.requires_grad_(True) for tensor in (q, k, v, bias))
    output = triangle_attention_reference(q, k, v, bias, mask, 0.5)
    grad_output = torch.randn_like(output)
    expected = torch.autograd.grad(output, (q, k, v, bias), grad_output)

    ctx = _Context()
    setup_context(ctx, (q, k, v, bias, mask, 0.5), output)
    actual = backward(ctx, grad_output)
    for actual_gradient, expected_gradient in zip(actual[:4], expected, strict=True):
        torch.testing.assert_close(actual_gradient, expected_gradient, rtol=1e-10, atol=1e-10)
    assert actual[4:] == (None, None)


def test_literal_contract_discovers_only_mindclade_registered_autograd():
    source = Path(__file__).resolve().parents[1] / "tilelang.py"
    kernels_root = Path(__file__).resolve().parents[3]
    specs = discover_specs(kernels_root, [source])
    assert len(specs) == 1
    spec = specs[0]
    assert spec.qualified_name == "mindclade::triangle_attention"
    assert spec.schema.endswith("float scale) -> Tensor")
    assert spec.autograd.mode == "registered"
    assert spec.fake.module == "kernels.pairformer.triangle_attention.tilelang"
    assert build_tilelang_program.__mindclade_kernel__["namespace"] == "mindclade"


def test_profiles_are_small_bounded_and_builder_rejects_unqualified_shapes():
    assert 1 <= len(TRIANGLE_ATTENTION_PROFILES) <= 8
    assert {profile["name"] for profile in TRIANGLE_ATTENTION_PROFILES} == {
        "b1_n32_h4_d32_fp16",
        "b1_n64_h8_d32_fp16",
        "b1_n128_h8_d64_bf16",
        "b2_n64_h8_d64_fp32",
    }
    with pytest.raises(ValueError, match="target must be exactly"):
        build_tilelang_program(
            target="auto", batch=1, n=32, heads=4, head_dim=32, dtype="float16", threads=64
        )
    with pytest.raises(ValueError, match="head_dim"):
        build_tilelang_program(
            target="cuda", batch=1, n=32, heads=4, head_dim=48, dtype="float16", threads=64
        )
    with pytest.raises(ValueError, match="dtype"):
        build_tilelang_program(
            target="cuda", batch=1, n=32, heads=4, head_dim=32, dtype="float64", threads=64
        )
