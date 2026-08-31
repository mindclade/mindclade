# Copyright (c) 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

"""Independent PyTorch authority for triangle-attention semantics and autograd."""

from __future__ import annotations

import math
from numbers import Real
from typing import Any

import torch


def _check(condition: object, message: str) -> None:
    if type(condition) is bool:
        if not condition:
            raise ValueError(message)
        return
    torch._check(condition, lambda: message)


def _require_tensor(name: str, value: object) -> torch.Tensor:
    if not isinstance(value, torch.Tensor):
        raise TypeError(f"{name} must be a torch.Tensor")
    return value


def validate_inputs(
    q: torch.Tensor,
    k: torch.Tensor,
    v: torch.Tensor,
    bias: torch.Tensor,
    mask: torch.Tensor,
    scale: float,
) -> tuple[tuple[torch.SymInt | int, ...], torch.SymInt | int, torch.SymInt | int]:
    q = _require_tensor("q", q)
    k = _require_tensor("k", k)
    v = _require_tensor("v", v)
    bias = _require_tensor("bias", bias)
    mask = _require_tensor("mask", mask)

    if q.dim() < 4:
        raise ValueError("q must have shape [..., N, N, H, D]")
    if k.dim() != q.dim() or v.dim() != q.dim():
        raise ValueError("q, k, and v must have the same rank")
    for axis in range(q.dim()):
        _check(k.shape[axis] == q.shape[axis], "q, k, and v must have identical shapes")
        _check(v.shape[axis] == q.shape[axis], "q, k, and v must have identical shapes")

    n = q.shape[-4]
    heads = q.shape[-2]
    head_dim = q.shape[-1]
    _check(n == q.shape[-3], "q, k, and v require equal pair dimensions N")
    _check(n > 0, "N must be positive")
    _check(heads > 0, "H must be positive")
    _check(head_dim > 0, "D must be positive")

    if not q.dtype.is_floating_point:
        raise TypeError("q, k, and v must use a floating-point dtype")
    if k.dtype != q.dtype or v.dtype != q.dtype:
        raise TypeError("q, k, and v must use the same dtype")
    if bias.dtype != q.dtype:
        raise TypeError("bias must use the q dtype")
    if mask.dtype != torch.bool:
        raise TypeError("mask must use torch.bool")
    if any(tensor.device != q.device for tensor in (k, v, bias, mask)):
        raise ValueError("q, k, v, bias, and mask must be on the same device")

    prefix = tuple(q.shape[:-4])
    expected_mask = (*prefix, n, n)
    if mask.dim() != len(expected_mask):
        raise ValueError("mask must have shape [..., N, N] with the q batch prefix")
    for axis, expected in enumerate(expected_mask):
        _check(
            mask.shape[axis] == expected,
            "mask must have shape [..., N, N] with the q batch prefix",
        )

    bias_target = (*prefix, n, heads, n, n)
    try:
        broadcast_shape = torch.broadcast_shapes(tuple(bias.shape), bias_target)
    except RuntimeError as exc:
        raise ValueError("bias must be broadcastable to [..., N, H, N, N]") from exc
    if len(broadcast_shape) != len(bias_target):
        raise ValueError("bias must be broadcastable to [..., N, H, N, N]")
    for actual, expected in zip(broadcast_shape, bias_target, strict=True):
        _check(actual == expected, "bias must be broadcastable to [..., N, H, N, N]")

    if isinstance(scale, bool) or not isinstance(scale, Real):
        raise TypeError("scale must be a finite real number")
    if not math.isfinite(float(scale)):
        raise ValueError("scale must be finite")
    return prefix, n, heads


def triangle_attention_reference(
    q: torch.Tensor,
    k: torch.Tensor,
    v: torch.Tensor,
    bias: torch.Tensor,
    mask: torch.Tensor,
    scale: float,
) -> torch.Tensor:
    """Apply stable masked triangle attention over the source residue axis."""

    validate_inputs(q, k, v, bias, mask, scale)
    accumulation_dtype = (
        torch.float32 if q.dtype in {torch.float16, torch.bfloat16} else q.dtype
    )
    q_acc = q.to(accumulation_dtype)
    k_acc = k.to(accumulation_dtype)
    v_acc = v.to(accumulation_dtype)
    logits = torch.einsum("...ijhd,...ikhd->...ihjk", q_acc, k_acc)
    logits = logits * float(scale) + bias.to(accumulation_dtype)

    valid = mask.unsqueeze(-2).unsqueeze(-2)
    masked_logits = logits.masked_fill(~valid, -torch.inf)
    has_source = valid.any(dim=-1, keepdim=True)
    row_max = masked_logits.amax(dim=-1, keepdim=True)
    row_max = torch.where(has_source, row_max, torch.zeros_like(row_max))
    exponentials = torch.exp(masked_logits - row_max)
    denominator = exponentials.sum(dim=-1, keepdim=True)
    safe_denominator = torch.where(has_source, denominator, torch.ones_like(denominator))
    weights = exponentials / safe_denominator

    safe_v = torch.where(mask.unsqueeze(-1).unsqueeze(-1), v_acc, torch.zeros_like(v_acc))
    output = torch.einsum("...ihjk,...ikhd->...ijhd", weights, safe_v)
    output_has_source = mask.any(dim=-1)[..., :, None, None, None]
    output = torch.where(output_has_source, output, torch.zeros_like(output))
    return output.to(q.dtype)


def fake(
    q: torch.Tensor,
    k: torch.Tensor,
    v: torch.Tensor,
    bias: torch.Tensor,
    mask: torch.Tensor,
    scale: float,
) -> torch.Tensor:
    """Validate the abstract contract and return exact output metadata."""

    validate_inputs(q, k, v, bias, mask, scale)
    return q.new_empty(q.shape)


def setup_context(ctx: Any, inputs: tuple[object, ...], output: torch.Tensor) -> None:
    """Save explicit inputs for the qualified composite backward decomposition."""

    del output
    q, k, v, bias, mask, scale = inputs
    if not all(isinstance(tensor, torch.Tensor) for tensor in (q, k, v, bias, mask)):
        raise TypeError("triangle_attention autograd context received non-tensor inputs")
    ctx.save_for_backward(q, k, v, bias, mask)
    ctx.scale = float(scale)


def composite_backward(ctx: Any, grad_output: torch.Tensor) -> tuple[torch.Tensor | None, ...]:
    """Differentiate the independent reference without claiming a native BWD."""

    q, k, v, bias, mask = ctx.saved_tensors
    needs = tuple(getattr(ctx, "needs_input_grad", (True, True, True, True, False, False)))
    if len(needs) != 6:
        raise RuntimeError("triangle_attention autograd context has invalid input arity")

    tensor_inputs = [q, k, v, bias]
    recompute_inputs: list[torch.Tensor] = []
    differentiable: list[torch.Tensor] = []
    differentiable_positions: list[int] = []
    for position, tensor in enumerate(tensor_inputs):
        candidate = tensor
        if needs[position] and not candidate.requires_grad:
            candidate = candidate.detach().requires_grad_(True)
        recompute_inputs.append(candidate)
        if needs[position]:
            differentiable.append(candidate)
            differentiable_positions.append(position)

    result: list[torch.Tensor | None] = [None, None, None, None, None, None]
    if not differentiable:
        return tuple(result)

    create_graph = torch.is_grad_enabled()
    with torch.enable_grad():
        output = triangle_attention_reference(
            recompute_inputs[0],
            recompute_inputs[1],
            recompute_inputs[2],
            recompute_inputs[3],
            mask,
            ctx.scale,
        )
        gradients = torch.autograd.grad(
            output,
            differentiable,
            grad_output,
            allow_unused=False,
            create_graph=create_graph,
        )
    for position, gradient in zip(differentiable_positions, gradients, strict=True):
        result[position] = gradient
    return tuple(result)


__all__ = (
    "composite_backward",
    "fake",
    "setup_context",
    "triangle_attention_reference",
    "validate_inputs",
)
