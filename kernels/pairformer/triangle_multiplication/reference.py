"""Independent PyTorch authority for triangle-multiplication semantics."""

from __future__ import annotations

from typing import Any

import torch


def validate_inputs(
    left: torch.Tensor,
    right: torch.Tensor,
    mask: torch.Tensor,
    outgoing: bool,
) -> None:
    if not isinstance(left, torch.Tensor) or not isinstance(right, torch.Tensor):
        raise TypeError("left and right must be torch.Tensor values")
    if not isinstance(mask, torch.Tensor):
        raise TypeError("mask must be a torch.Tensor")
    if left.ndim < 3:
        raise ValueError("left must have shape [..., N, N, C]")
    if left.shape != right.shape:
        raise ValueError("left and right must have identical shapes")
    if left.shape[-3] != left.shape[-2]:
        raise ValueError("left and right residue axes must be square")
    if mask.shape != left.shape[:-1]:
        raise ValueError("mask must have shape [..., N, N]")
    if not left.dtype.is_floating_point or not right.dtype.is_floating_point:
        raise TypeError("left and right must use floating-point dtypes")
    if not mask.dtype.is_floating_point and mask.dtype != torch.bool:
        raise TypeError("mask must be boolean or floating point")
    if left.dtype != right.dtype:
        raise TypeError("left and right must have the same dtype")
    if left.device != right.device or left.device != mask.device:
        raise ValueError("left, right, and mask must be on the same device")
    if not isinstance(outgoing, bool):
        raise TypeError("outgoing must be a bool")


def triangle_multiplication_reference(
    left: torch.Tensor,
    right: torch.Tensor,
    mask: torch.Tensor,
    outgoing: bool,
) -> torch.Tensor:
    """Compute masked outgoing or incoming triangle multiplication."""

    validate_inputs(left, right, mask, outgoing)
    mask_values = mask.to(dtype=left.dtype)
    masked_left = left * mask_values.unsqueeze(-1)
    masked_right = right * mask_values.unsqueeze(-1)
    if outgoing:
        result = torch.einsum("...ikc,...jkc->...ijc", masked_left, masked_right)
    else:
        result = torch.einsum("...kic,...kjc->...ijc", masked_left, masked_right)
    return result * mask_values.unsqueeze(-1)


def fake(
    left: torch.Tensor,
    right: torch.Tensor,
    mask: torch.Tensor,
    outgoing: bool,
) -> torch.Tensor:
    validate_inputs(left, right, mask, outgoing)
    return left.new_empty(left.shape)


def setup_context(ctx: Any, inputs: tuple[object, ...], output: torch.Tensor) -> None:
    del output
    left, right, mask, outgoing = inputs
    if not all(isinstance(tensor, torch.Tensor) for tensor in (left, right, mask)):
        raise TypeError("triangle_multiplication context received non-tensor inputs")
    ctx.save_for_backward(left, right, mask)
    ctx.outgoing = bool(outgoing)


def composite_backward(ctx: Any, grad_output: torch.Tensor) -> tuple[torch.Tensor | None, ...]:
    """Differentiate the independent reference without claiming a native BWD."""

    left, right, mask = ctx.saved_tensors
    needs = tuple(getattr(ctx, "needs_input_grad", (True, True, False, False)))
    if len(needs) != 4:
        raise RuntimeError("triangle_multiplication autograd context has invalid input arity")
    inputs = [left, right]
    recompute: list[torch.Tensor] = []
    differentiable: list[torch.Tensor] = []
    positions: list[int] = []
    for position, tensor in enumerate(inputs):
        candidate = tensor
        if needs[position] and not candidate.requires_grad:
            candidate = candidate.detach().requires_grad_(True)
        recompute.append(candidate)
        if needs[position]:
            differentiable.append(candidate)
            positions.append(position)
    result: list[torch.Tensor | None] = [None, None, None, None]
    if not differentiable:
        return tuple(result)
    create_graph = torch.is_grad_enabled()
    with torch.enable_grad():
        output = triangle_multiplication_reference(
            recompute[0], recompute[1], mask, ctx.outgoing
        )
        gradients = torch.autograd.grad(
            output,
            differentiable,
            grad_output,
            allow_unused=False,
            create_graph=create_graph,
        )
    for position, gradient in zip(positions, gradients, strict=True):
        result[position] = gradient
    return tuple(result)


__all__ = (
    "composite_backward",
    "fake",
    "setup_context",
    "triangle_multiplication_reference",
    "validate_inputs",
)
