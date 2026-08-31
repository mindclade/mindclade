# Copyright (c) 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

from __future__ import annotations

import hashlib
import math
from pathlib import Path

import pytest
import torch

from kernels.api import EvaluationContext, TensorMetadata
from kernels.pairformer.outer_product_mean.dispatch import outer_product_mean
from kernels.pairformer.outer_product_mean.reference import composite_backward, outer_product_mean_reference, setup_context
from kernels.pairformer.outer_product_mean.spec import KERNEL_SPEC
from kernels.pairformer.outer_product_mean.tilelang import build_tilelang_program

def test_reference_shape_zero_mask_and_gradcheck():
    left = torch.randn(2, 3, 2, dtype=torch.float64, requires_grad=True)
    right = torch.randn(2, 3, 4, dtype=torch.float64, requires_grad=True)
    mask = torch.zeros(2, 3, dtype=torch.float64, requires_grad=True)
    output = outer_product_mean_reference(left, right, mask, 1e-6)
    assert output.shape == (3, 3, 2, 4)
    assert torch.count_nonzero(output) == 0 and torch.isfinite(output).all()
    assert torch.autograd.gradcheck(lambda l, r, m: outer_product_mean_reference(l, r, m, 1e-6, _check_values=False), (left, right, mask))

def test_composite_backward_includes_mask_gradient():
    left = torch.randn(2, 2, 2, dtype=torch.float64, requires_grad=True)
    right = torch.randn(2, 2, 3, dtype=torch.float64, requires_grad=True)
    mask = torch.rand(2, 2, dtype=torch.float64, requires_grad=True)
    output = outer_product_mean_reference(left, right, mask, 1e-6)
    grad = torch.randn_like(output)
    expected = torch.autograd.grad(output, (left, right, mask), grad)
    class Context:
        needs_input_grad = (True, True, True, False)
        def save_for_backward(self, *values): self.saved_tensors = values
    ctx = Context(); setup_context(ctx, (left, right, mask, 1e-6), output)
    actual = composite_backward(ctx, grad)
    for got, want in zip(actual[:3], expected): torch.testing.assert_close(got, want)

def test_declarative_shape_dispatch_and_source_digest():
    context = EvaluationContext({"left": TensorMetadata((2, 4, 3, 5), "float32", "cuda"), "right": TensorMetadata((2, 4, 3, 7), "float32", "cuda")})
    assert KERNEL_SPEC.forward.outputs[0].shape.evaluate(context) == (2, 3, 3, 5, 7)
    assert outer_product_mean(torch.ones(2, 3, 2), torch.ones(2, 3, 4), torch.ones(2, 3), 1e-6, use_reference=True).shape == (3, 3, 2, 4)
    reference = Path(__file__).parents[1] / "reference.py"
    assert KERNEL_SPEC.composite.source_digest == "sha256:" + hashlib.sha256(reference.read_bytes()).hexdigest()
    assert KERNEL_SPEC.backward is None and KERNEL_SPEC.forward.symbol.endswith("_fwd_launch")

@pytest.mark.parametrize("epsilon", [0.0, -1.0, math.inf, math.nan])
def test_invalid_epsilon_and_profile_fail_closed(epsilon):
    with pytest.raises(ValueError, match="epsilon"):
        outer_product_mean_reference(torch.ones(2,3,2), torch.ones(2,3,2), torch.ones(2,3), epsilon)
    with pytest.raises(ValueError, match="target"):
        build_tilelang_program(target="cpu", batch_size=1, sequence_length=2, nodes=3, left_channels=2, right_channels=2, dtype="float32", threads=128)
