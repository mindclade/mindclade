# Copyright (c) 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
import torch

from kernels.api import EvaluationContext, TensorMetadata
from kernels.pairformer.pair_weighted_average.dispatch import pair_weighted_average
from kernels.pairformer.pair_weighted_average.reference import composite_backward, pair_weighted_average_reference, setup_context
from kernels.pairformer.pair_weighted_average.spec import KERNEL_SPEC
from kernels.pairformer.pair_weighted_average.tilelang import build_tilelang_program

def test_reference_all_masked_and_gradcheck():
    value = torch.randn(2, 3, 2, dtype=torch.float64, requires_grad=True)
    weights = torch.randn(2, 3, 3, 2, dtype=torch.float64, requires_grad=True)
    mask = torch.zeros(2, 3, dtype=torch.bool)
    assert torch.equal(pair_weighted_average_reference(value, weights, mask, 1e-12), torch.zeros(2,3,2,2, dtype=torch.float64))
    mask[0] = True
    assert torch.autograd.gradcheck(lambda v, w: pair_weighted_average_reference(v, w, mask, 1e-12), (value, weights))

def test_composite_backward_maps_only_value_and_weights():
    value = torch.randn(2,3,2,dtype=torch.float64,requires_grad=True); weights = torch.randn(2,3,3,2,dtype=torch.float64,requires_grad=True); mask = torch.ones(2,3,dtype=torch.bool)
    output = pair_weighted_average_reference(value, weights, mask, 1e-12); grad = torch.randn_like(output)
    expected = torch.autograd.grad(output, (value, weights), grad)
    class Context:
        needs_input_grad = (True, True, False, False)
        def save_for_backward(self, *values): self.saved_tensors = values
    ctx=Context(); setup_context(ctx,(value,weights,mask,1e-12),output); actual=composite_backward(ctx,grad)
    torch.testing.assert_close(actual[0],expected[0]); torch.testing.assert_close(actual[1],expected[1]); assert actual[2:] == (None,None)

def test_declarative_shape_dispatch_digest_and_profiles():
    context=EvaluationContext({"value":TensorMetadata((2,4,5),"float32","cuda"),"weights":TensorMetadata((2,4,4,3),"float32","cuda")})
    assert KERNEL_SPEC.forward.outputs[0].shape.evaluate(context)==(2,4,3,5)
    result=pair_weighted_average(torch.ones(2,4,5),torch.zeros(2,4,4,3),torch.ones(2,4,dtype=torch.bool),1e-8,use_reference=True); assert result.shape==(2,4,3,5)
    reference=Path(__file__).parents[0]/"reference.py"
    assert KERNEL_SPEC.composite.source_digest=="sha256:"+hashlib.sha256(reference.read_bytes()).hexdigest()
    assert KERNEL_SPEC.backward is None and KERNEL_SPEC.forward.symbol.endswith("_fwd_launch")
    with pytest.raises(ValueError,match="only target='cuda'"): build_tilelang_program(target="cpu",batch_size=1,num_residues=32,channels=64,heads=4)
