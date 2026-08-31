# Copyright (c) 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

"""Independent PyTorch semantics and composite autograd for pair weighted average."""

from __future__ import annotations

import math
from typing import Any

import torch

_FLOAT_DTYPES = {torch.float16, torch.bfloat16, torch.float32, torch.float64}


def validate_inputs(value: torch.Tensor, weights: torch.Tensor, mask: torch.Tensor, epsilon: float) -> tuple[tuple[int, ...], int, int, int]:
    if not all(isinstance(tensor, torch.Tensor) for tensor in (value, weights, mask)):
        raise TypeError("value, weights, and mask must be tensors")
    if value.ndim < 2:
        raise ValueError("value must have shape [..., N, C]")
    if weights.ndim != value.ndim + 1:
        raise ValueError("weights must have shape [..., N, N, H]")
    if mask.ndim != value.ndim - 1:
        raise ValueError("mask must have shape [..., N]")
    batch_shape = tuple(value.shape[:-2])
    residues, channels, heads = value.shape[-2], value.shape[-1], weights.shape[-1]
    if tuple(weights.shape[:-3]) != batch_shape:
        raise ValueError("weights batch dimensions must match value")
    if tuple(mask.shape[:-1]) != batch_shape:
        raise ValueError("mask batch dimensions must match value")
    if weights.shape[-3] != residues or weights.shape[-2] != residues:
        raise ValueError("both weights residue dimensions must equal value N")
    if mask.shape[-1] != residues:
        raise ValueError("mask source dimension must equal value N")
    if residues == 0 or channels == 0 or heads == 0:
        raise ValueError("N, C, and H must be nonzero")
    if value.dtype not in _FLOAT_DTYPES:
        raise TypeError("value must use a floating-point dtype")
    if weights.dtype != value.dtype:
        raise TypeError("weights dtype must equal value dtype")
    if mask.dtype != torch.bool and not mask.dtype.is_floating_point:
        raise TypeError("mask must use bool or a floating-point dtype")
    if value.device != weights.device or value.device != mask.device:
        raise ValueError("value, weights, and mask must use the same device")
    if isinstance(epsilon, bool) or not isinstance(epsilon, (int, float)):
        raise TypeError("epsilon must be a real scalar")
    if not math.isfinite(float(epsilon)) or float(epsilon) <= 0.0:
        raise ValueError("epsilon must be finite and greater than zero")
    return batch_shape, residues, channels, heads


def pair_weighted_average_reference(value: torch.Tensor, weights: torch.Tensor, mask: torch.Tensor, epsilon: float) -> torch.Tensor:
    validate_inputs(value, weights, mask, epsilon)
    accumulation_dtype = torch.float32 if value.dtype in {torch.float16, torch.bfloat16} else value.dtype
    logits = weights.to(accumulation_dtype)
    values = value.to(accumulation_dtype)
    source_mask = (mask != 0).unsqueeze(-2).unsqueeze(-1)
    masked_logits = torch.where(source_mask, logits, torch.full_like(logits, -torch.inf))
    has_source = source_mask.any(dim=-2, keepdim=True)
    row_max = masked_logits.amax(dim=-2, keepdim=True)
    safe_row_max = torch.where(has_source, row_max, torch.zeros_like(row_max))
    exponentials = torch.where(source_mask, torch.exp(logits - safe_row_max), torch.zeros_like(logits))
    denominator = exponentials.sum(dim=-2, keepdim=True)
    probabilities = torch.where(
        has_source, exponentials / denominator.clamp_min(float(epsilon)), torch.zeros_like(exponentials)
    )
    return torch.einsum("...ijh,...jc->...ihc", probabilities, values).to(value.dtype)


def setup_context(ctx: Any, inputs: tuple[Any, ...], output: torch.Tensor) -> None:
    del output
    value, weights, mask, epsilon = inputs
    ctx.save_for_backward(value, weights, mask)
    ctx.epsilon = float(epsilon)


def composite_backward(ctx: Any, grad_output: torch.Tensor) -> tuple[torch.Tensor | None, ...]:
    value, weights, mask = ctx.saved_tensors
    need_value, need_weights = ctx.needs_input_grad[:2]
    if not need_value and not need_weights:
        return None, None, None, None
    with torch.enable_grad():
        replay = pair_weighted_average_reference(value, weights, mask, ctx.epsilon)
        requested = tuple(tensor for tensor, needed in ((value, need_value), (weights, need_weights)) if needed)
        computed = torch.autograd.grad(
            replay, requested, grad_output, create_graph=torch.is_grad_enabled(), allow_unused=False
        )
    offset = 0
    grad_value = computed[offset] if need_value else None
    offset += int(need_value)
    grad_weights = computed[offset] if need_weights else None
    return grad_value, grad_weights, None, None
