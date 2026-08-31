# Copyright (c) 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

"""Independent PyTorch semantics and composite autograd for outer-product mean."""

from __future__ import annotations

import math
from typing import Any

import torch


def _check(condition: Any, message: str) -> None:
    torch._check(condition, lambda: message)


def validate_inputs(
    left: torch.Tensor,
    right: torch.Tensor,
    mask: torch.Tensor,
    epsilon: float,
) -> tuple[tuple[int, ...], int, int, int, int]:
    if not isinstance(left, torch.Tensor):
        raise TypeError("left must be a torch.Tensor")
    if not isinstance(right, torch.Tensor):
        raise TypeError("right must be a torch.Tensor")
    if not isinstance(mask, torch.Tensor):
        raise TypeError("mask must be a torch.Tensor")
    if isinstance(epsilon, bool) or not isinstance(epsilon, (int, float)):
        raise TypeError("epsilon must be a finite positive float")
    epsilon_value = float(epsilon)
    if not math.isfinite(epsilon_value) or epsilon_value <= 0.0:
        raise ValueError("epsilon must be finite and greater than zero")

    _check(left.ndim >= 3, "left must have shape [..., S, N, C_l]")
    _check(right.ndim >= 3, "right must have shape [..., S, N, C_r]")
    _check(mask.ndim >= 2, "mask must have shape [..., S, N]")
    _check(left.dtype.is_floating_point, "left must have a floating dtype")
    _check(right.dtype.is_floating_point, "right must have a floating dtype")
    _check(mask.dtype.is_floating_point, "mask must have a floating dtype")
    _check(left.dtype == right.dtype, "left and right must have the same dtype")
    _check(left.dtype == mask.dtype, "mask must have the same dtype as left and right")
    _check(left.device == right.device, "left and right must be on the same device")
    _check(left.device == mask.device, "mask must be on the same device as left and right")

    left_batch = tuple(left.shape[:-3])
    right_batch = tuple(right.shape[:-3])
    _check(len(left_batch) == len(right_batch), "left and right batch ranks must match")
    for left_extent, right_extent in zip(left_batch, right_batch):
        _check(left_extent == right_extent, "left and right batch shapes must match exactly")
    sequence_length = left.shape[-3]
    nodes = left.shape[-2]
    left_channels = left.shape[-1]
    _check(right.shape[-3] == sequence_length, "left and right sequence dimensions must match")
    _check(right.shape[-2] == nodes, "left and right node dimensions must match")
    _check(mask.shape[-2] == sequence_length, "mask sequence dimension must match inputs")
    _check(mask.shape[-1] == nodes, "mask node dimension must match inputs")
    mask_batch = tuple(mask.shape[:-2])
    _check(len(mask_batch) <= len(left_batch), "mask has more batch dimensions than inputs")
    padded_mask_batch = (1,) * (len(left_batch) - len(mask_batch)) + mask_batch
    for mask_extent, input_extent in zip(padded_mask_batch, left_batch):
        _check(
            (mask_extent == 1) | (mask_extent == input_extent),
            "mask batch dimensions must broadcast exactly to the input batch shape",
        )
    return left_batch, sequence_length, nodes, left_channels, right.shape[-1]


def _expanded_mask(mask: torch.Tensor, batch_shape: tuple[int, ...], sequence_length: int, nodes: int) -> torch.Tensor:
    mask_batch = tuple(mask.shape[:-2])
    padded_shape = (1,) * (len(batch_shape) - len(mask_batch)) + mask_batch + (sequence_length, nodes)
    return mask.reshape(padded_shape).expand(batch_shape + (sequence_length, nodes))


def outer_product_mean_reference(
    left: torch.Tensor,
    right: torch.Tensor,
    mask: torch.Tensor,
    epsilon: float,
    *,
    _check_values: bool = True,
) -> torch.Tensor:
    batch_shape, sequence_length, nodes, _, _ = validate_inputs(left, right, mask, epsilon)
    if _check_values:
        for name, tensor in (("left", left), ("right", right), ("mask", mask)):
            if not bool(torch.isfinite(tensor).all()):
                raise ValueError(f"{name} must contain only finite values")
    accumulation_dtype = torch.float64 if left.dtype == torch.float64 else torch.float32
    mask_acc = _expanded_mask(mask, batch_shape, sequence_length, nodes).to(accumulation_dtype)
    weighted_left = left.to(accumulation_dtype) * mask_acc.unsqueeze(-1)
    weighted_right = right.to(accumulation_dtype) * mask_acc.unsqueeze(-1)
    numerator = torch.einsum("...sic,...sjd->...ijcd", weighted_left, weighted_right)
    denominator = torch.einsum("...si,...sj->...ij", mask_acc, mask_acc).clamp_min(float(epsilon))
    result = (numerator / denominator.unsqueeze(-1).unsqueeze(-1)).to(left.dtype)
    if _check_values and not bool(torch.isfinite(result).all()):
        raise ValueError("outer_product_mean produced a non-finite result")
    return result


def setup_context(ctx: Any, inputs: tuple[Any, ...], output: torch.Tensor) -> None:
    del output
    left, right, mask, epsilon = inputs
    ctx.save_for_backward(left, right, mask)
    ctx.epsilon = float(epsilon)


def composite_backward(ctx: Any, grad_output: torch.Tensor | None) -> tuple[torch.Tensor | None, ...]:
    if grad_output is None:
        return None, None, None, None
    left, right, mask = ctx.saved_tensors
    needs = tuple(getattr(ctx, "needs_input_grad", (True, True, True, False)))
    requested = [tensor for tensor, needed in zip((left, right, mask), needs[:3]) if needed]
    if not requested:
        return None, None, None, None
    with torch.enable_grad():
        replay = outer_product_mean_reference(left, right, mask, ctx.epsilon, _check_values=False)
        computed = torch.autograd.grad(
            replay, requested, grad_output, allow_unused=True, create_graph=torch.is_grad_enabled()
        )
    iterator = iter(computed)
    aligned = [next(iterator) if needed else None for needed in needs[:3]]
    return aligned[0], aligned[1], aligned[2], None
