"""Independent PyTorch authority for pair-weighted average."""

from __future__ import annotations

import math

import torch


def validate_inputs(
    value: torch.Tensor,
    weights: torch.Tensor,
    mask: torch.Tensor,
    epsilon: float,
) -> None:
    if value.ndim < 2 or weights.ndim != value.ndim + 1:
        raise ValueError("value must be [...,N,C] and weights must be [...,N,N,H]")
    if weights.shape[:-3] != value.shape[:-2]:
        raise ValueError("value and weights batch prefixes must match")
    node_count = value.shape[-2]
    if weights.shape[-3] != node_count or weights.shape[-2] != node_count:
        raise ValueError("both weights node dimensions must match value")
    if mask.shape != value.shape[:-1]:
        raise ValueError("mask shape must equal value.shape[:-1]")
    if node_count == 0 or value.shape[-1] == 0 or weights.shape[-1] == 0:
        raise ValueError("node, channel, and head dimensions must be nonzero")
    if value.device != weights.device or value.device != mask.device:
        raise ValueError("value, weights, and mask must be on the same device")
    if value.dtype != weights.dtype or not value.is_floating_point():
        raise TypeError("value and weights must share a floating-point dtype")
    if mask.dtype != torch.bool and not mask.is_floating_point():
        raise TypeError("mask must be bool or floating point")
    if not math.isfinite(epsilon) or epsilon <= 0.0:
        raise ValueError("epsilon must be finite and positive")


def pair_weighted_average_with_lse(
    value: torch.Tensor,
    weights: torch.Tensor,
    mask: torch.Tensor,
    epsilon: float = 1.0e-6,
) -> tuple[torch.Tensor, torch.Tensor]:
    """Return the reference result and FP32 log-normalizer."""

    validate_inputs(value, weights, mask, epsilon)
    accumulation_dtype = torch.float64 if value.dtype == torch.float64 else torch.float32
    value_acc = value.to(accumulation_dtype)
    logits = weights.to(accumulation_dtype)
    valid = mask != 0
    valid_logits = valid.unsqueeze(-2).unsqueeze(-1)
    masked_logits = torch.where(
        valid_logits,
        logits,
        torch.full_like(logits, -torch.inf),
    )
    row_has_source = valid.any(dim=-1).unsqueeze(-1).unsqueeze(-1).unsqueeze(-1)
    row_max = masked_logits.amax(dim=-2, keepdim=True)
    safe_max = torch.where(row_has_source, row_max, torch.zeros_like(row_max))
    exponentials = torch.where(
        valid_logits,
        torch.exp(logits - safe_max),
        torch.zeros_like(logits),
    )
    denominator = exponentials.sum(dim=-2)
    safe_denominator = denominator.clamp_min(epsilon)
    probabilities = exponentials / safe_denominator.unsqueeze(-2)
    output = torch.einsum("...ijh,...jc->...ihc", probabilities, value_acc)
    finite_lse = safe_max.squeeze(-2) + torch.log(safe_denominator)
    lse = torch.where(
        row_has_source.squeeze(-2),
        finite_lse,
        torch.full_like(finite_lse, -torch.inf),
    )
    return output.to(value.dtype), lse.to(torch.float32)


def pair_weighted_average_reference(
    value: torch.Tensor,
    weights: torch.Tensor,
    mask: torch.Tensor,
    epsilon: float = 1.0e-6,
) -> torch.Tensor:
    """Compute masked stable-softmax weighted reduction semantics."""

    output, _lse = pair_weighted_average_with_lse(value, weights, mask, epsilon)
    return output
