"""Independent PyTorch authority for Pairformer SwiGLU transition."""

from __future__ import annotations

import torch
import torch.nn.functional as F


def validate_inputs(
    gate: torch.Tensor,
    value: torch.Tensor,
    output_weight: torch.Tensor,
    output_bias: torch.Tensor,
    mask: torch.Tensor,
) -> None:
    if gate.ndim < 2 or value.shape != gate.shape:
        raise ValueError("gate and value must have the same shape and rank >= 2")
    if output_weight.ndim != 2 or output_weight.shape[0] != gate.shape[-1]:
        raise ValueError("output_weight must be [hidden_channels, output_channels]")
    if output_bias.shape != (output_weight.shape[1],):
        raise ValueError("output_bias must match output_weight output channels")
    if mask.shape != gate.shape[:-1]:
        raise ValueError("mask shape must equal gate.shape[:-1]")
    if gate.numel() == 0 or output_weight.shape[0] == 0:
        raise ValueError("transition dimensions must be nonzero")
    if not all(
        tensor.device == gate.device
        for tensor in (value, output_weight, output_bias, mask)
    ):
        raise ValueError("all transition tensors must be on the same device")
    if not all(
        tensor.dtype == gate.dtype
        for tensor in (value, output_weight, output_bias)
    ):
        raise TypeError("gate, value, weight, and bias must have the same dtype")
    if not gate.is_floating_point() or not (mask.is_floating_point() or mask.dtype == torch.bool):
        raise TypeError("transition inputs must be floating-point and mask bool or floating")


def transition_with_saved(
    gate: torch.Tensor,
    value: torch.Tensor,
    output_weight: torch.Tensor,
    output_bias: torch.Tensor,
    mask: torch.Tensor,
) -> tuple[torch.Tensor, torch.Tensor]:
    """Return the result and explicit pre-mask output used for dMask."""

    validate_inputs(gate, value, output_weight, output_bias, mask)
    accumulation_dtype = torch.float64 if gate.dtype == torch.float64 else torch.float32
    activated = F.silu(gate.to(accumulation_dtype)) * value.to(accumulation_dtype)
    pre_mask = activated @ output_weight.to(accumulation_dtype)
    pre_mask = pre_mask + output_bias.to(accumulation_dtype)
    output = pre_mask * mask.to(accumulation_dtype).unsqueeze(-1)
    return output.to(gate.dtype), pre_mask.to(gate.dtype)


def transition_reference(
    gate: torch.Tensor,
    value: torch.Tensor,
    output_weight: torch.Tensor,
    output_bias: torch.Tensor,
    mask: torch.Tensor,
) -> torch.Tensor:
    output, _pre_mask = transition_with_saved(
        gate, value, output_weight, output_bias, mask
    )
    return output


def fake(
    gate: torch.Tensor,
    value: torch.Tensor,
    output_weight: torch.Tensor,
    output_bias: torch.Tensor,
    mask: torch.Tensor,
) -> torch.Tensor:
    """Legacy developer helper; production fake metadata is generated from spec."""

    validate_inputs(gate, value, output_weight, output_bias, mask)
    return gate.new_empty((*gate.shape[:-1], output_weight.shape[1]))
