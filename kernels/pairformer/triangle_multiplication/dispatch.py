"""Explicit model-facing dispatch for triangle multiplication."""

from __future__ import annotations

from enum import StrEnum

import torch

from .reference import triangle_multiplication_reference, validate_inputs


class ReferenceFallback(StrEnum):
    ERROR = "error"
    REFERENCE = "reference"


class NativeOperatorUnavailable(RuntimeError):
    """The generated semantic operator has not been loaded."""


def _native_operator():
    try:
        return torch.ops.mindclade.triangle_multiplication.default
    except AttributeError:
        return None


def triangle_multiplication(
    left: torch.Tensor,
    right: torch.Tensor,
    mask: torch.Tensor,
    outgoing: bool,
    *,
    fallback: ReferenceFallback | str = ReferenceFallback.ERROR,
) -> torch.Tensor:
    """Dispatch explicitly, with no implicit reference fallback."""

    try:
        fallback_policy = ReferenceFallback(fallback)
    except (TypeError, ValueError) as exc:
        raise ValueError("fallback must be 'error' or 'reference'") from exc
    validate_inputs(left, right, mask, outgoing)
    operation = _native_operator()
    if operation is None:
        if fallback_policy is ReferenceFallback.REFERENCE:
            return triangle_multiplication_reference(left, right, mask, outgoing)
        raise NativeOperatorUnavailable(
            "torch.ops.mindclade.triangle_multiplication is unavailable; "
            "load a qualified native bundle or request fallback='reference'"
        )

    residues = left.shape[-3]
    channels = left.shape[-1]
    flat_left = left.reshape(-1, residues, residues, channels)
    flat_right = right.reshape(-1, residues, residues, channels)
    dense_mask = mask.to(dtype=left.dtype).contiguous()
    flat_mask = dense_mask.reshape(-1, residues, residues)
    output = operation(flat_left, flat_right, flat_mask, outgoing)
    return output.reshape(left.shape)


__all__ = ("NativeOperatorUnavailable", "ReferenceFallback", "triangle_multiplication")
