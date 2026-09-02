"""Explicit model-facing dispatch for triangle multiplication."""

from __future__ import annotations

from enum import StrEnum
from typing import Callable

import torch

from .reference import triangle_multiplication_reference, validate_inputs


class FallbackPolicy(StrEnum):
    ERROR = "error"
    REFERENCE = "reference"


ReferenceFallback = FallbackPolicy


class NativeOperatorUnavailable(RuntimeError):
    """Raised when the generated semantic operator has not been loaded."""


def _native_operator() -> Callable[..., object] | None:
    try:
        return torch.ops.mindclade.triangle_multiplication.default
    except (AttributeError, RuntimeError):
        return None


def triangle_multiplication(
    left: torch.Tensor,
    right: torch.Tensor,
    mask: torch.Tensor,
    outgoing: bool,
    *,
    fallback: FallbackPolicy | str = FallbackPolicy.ERROR,
) -> torch.Tensor:
    """Normalize static inputs and dispatch without implicit fallback."""

    policy = FallbackPolicy(fallback)
    validate_inputs(left, right, mask, outgoing)
    operation = _native_operator()
    if operation is None:
        if policy is FallbackPolicy.REFERENCE:
            return triangle_multiplication_reference(left, right, mask, outgoing)
        raise NativeOperatorUnavailable(
            "torch.ops.mindclade.triangle_multiplication is unavailable; "
            "load a qualified native bundle or pass fallback='reference' explicitly"
        )

    residues = left.shape[-3]
    channels = left.shape[-1]
    flat_left = left.reshape(-1, residues, residues, channels)
    flat_right = right.reshape(-1, residues, residues, channels)
    flat_mask = mask.to(dtype=left.dtype).contiguous().reshape(-1, residues, residues)
    output = operation(flat_left, flat_right, flat_mask, outgoing)
    if not isinstance(output, torch.Tensor):
        raise RuntimeError("mindclade::triangle_multiplication returned non-Tensor output")
    return output.reshape(left.shape)
