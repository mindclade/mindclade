"""Independent PyTorch authority for outer-product mean."""

from __future__ import annotations

import math

import torch


def validate_inputs(left: torch.Tensor, right: torch.Tensor, mask: torch.Tensor, epsilon: float) -> None:
    if left.ndim < 3 or right.ndim != left.ndim:
        raise ValueError("left and right must have matching rank >= 3")
    if left.shape[:-1] != right.shape[:-1]:
        raise ValueError("left and right must share batch, source, and node dimensions")
    if mask.shape != left.shape[:-1]:
        raise ValueError("mask shape must equal left.shape[:-1]")
    if 0 in left.shape[-3:] or right.shape[-1] == 0:
        raise ValueError("source, node, and channel dimensions must be nonzero")
    if left.device != right.device or left.device != mask.device:
        raise ValueError("left, right, and mask must be on the same device")
    if left.dtype != right.dtype or left.dtype != mask.dtype:
        raise TypeError("left, right, and mask must have the same dtype")
    if not left.is_floating_point():
        raise TypeError("outer-product mean requires floating-point tensors")
    if not math.isfinite(epsilon) or epsilon <= 0.0:
        raise ValueError("epsilon must be finite and positive")


def outer_product_mean_with_normalizer(
    left: torch.Tensor,
    right: torch.Tensor,
    mask: torch.Tensor,
    epsilon: float = 1.0e-6,
) -> tuple[torch.Tensor, torch.Tensor]:
    """Return the reference result and raw FP32 pair normalizer."""

    validate_inputs(left, right, mask, epsilon)
    accumulation_dtype = torch.float64 if left.dtype == torch.float64 else torch.float32
    left_acc = left.to(accumulation_dtype)
    right_acc = right.to(accumulation_dtype)
    mask_acc = mask.to(accumulation_dtype)
    weighted_left = left_acc * mask_acc.unsqueeze(-1)
    weighted_right = right_acc * mask_acc.unsqueeze(-1)
    numerator = torch.einsum("...sic,...sjd->...ijcd", weighted_left, weighted_right)
    normalizer = torch.einsum("...si,...sj->...ij", mask_acc, mask_acc)
    output = numerator / normalizer.clamp_min(epsilon).unsqueeze(-1).unsqueeze(-1)
    return output.to(left.dtype), normalizer.to(torch.float32)


def outer_product_mean_reference(
    left: torch.Tensor,
    right: torch.Tensor,
    mask: torch.Tensor,
    epsilon: float = 1.0e-6,
) -> torch.Tensor:
    """Compute exact Pairformer outer-product mean semantics."""

    output, _normalizer = outer_product_mean_with_normalizer(left, right, mask, epsilon)
    return output
