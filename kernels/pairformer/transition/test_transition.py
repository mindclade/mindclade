# Copyright (c) 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
import torch

from kernels.api import EvaluationContext, TensorMetadata
from kernels.pairformer.transition.dispatch import transition
from kernels.pairformer.transition.reference import composite_backward, setup_context, transition_reference
from kernels.pairformer.transition.spec import KERNEL_SPEC
from kernels.pairformer.transition.tilelang import build_tilelang_program

def inputs(dtype=torch.float64):
    gate=torch.randn(2,5,8,dtype=dtype); value=torch.randn_like(gate); weight=torch.randn(8,4,dtype=dtype); bias=torch.randn(4,dtype=dtype); mask=torch.tensor([[1,1,0,1,0],[1,0,1,1,1]],dtype=torch.bool); return gate,value,weight,bias,mask

def test_reference_formula_mask_and_gradcheck():
    gate,value,weight,bias,mask=inputs(); expected=((torch.nn.functional.silu(gate)*value)@weight+bias)*mask.unsqueeze(-1)
    torch.testing.assert_close(transition_reference(gate,value,weight,bias,mask),expected)
    tensors=tuple(item.requires_grad_(True) for item in (gate,value,weight,bias)); assert torch.autograd.gradcheck(lambda g,v,w,b: transition_reference(g,v,w,b,mask),tensors)

def test_composite_backward_maps_four_gradients():
    gate,value,weight,bias,mask=inputs(); originals=tuple(item.requires_grad_(True) for item in (gate,value,weight,bias)); output=transition_reference(*originals,mask); grad=torch.randn_like(output); expected=torch.autograd.grad(output,originals,grad)
    class Context:
        needs_input_grad=(True,True,True,True,False)
        def save_for_backward(self,*values): self.saved_tensors=values
    ctx=Context(); setup_context(ctx,(*originals,mask),output); actual=composite_backward(ctx,grad)
    for got,want in zip(actual[:4],expected): torch.testing.assert_close(got,want)
    assert actual[4] is None

def test_declarative_shape_dispatch_digest_and_profile_guards():
    context=EvaluationContext({"gate":TensorMetadata((2,7,16),"bf16","cuda"),"output_weight":TensorMetadata((16,6),"bf16","cuda")})
    assert KERNEL_SPEC.forward.outputs[0].shape.evaluate(context)==(2,7,6)
    gate,value,weight,bias,mask=inputs(torch.float32); assert transition(gate,value,weight,bias,mask,use_reference=True).shape==(2,5,4)
    reference=Path(__file__).parents[0]/"reference.py"; assert KERNEL_SPEC.composite.source_digest=="sha256:"+hashlib.sha256(reference.read_bytes()).hexdigest()
    assert KERNEL_SPEC.backward is None and KERNEL_SPEC.forward.symbol.endswith("_fwd_launch")
    with pytest.raises(ValueError,match="explicit CUDA"): build_tilelang_program(target="cpu",batch_size=1,rows=2,hidden_channels=16,output_channels=8)
