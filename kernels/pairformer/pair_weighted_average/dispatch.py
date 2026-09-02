"""Explicit model-facing dispatch for pair-weighted average."""

from __future__ import annotations

from enum import StrEnum
from typing import Callable

import torch

from .reference import pair_weighted_average_reference, validate_inputs


class FallbackPolicy(StrEnum):
    ERROR = "error"
    REFERENCE = "reference"


class NativeOperatorUnavailable(RuntimeError):
    """Raised when the qualified native operator is not loaded."""


def _native_operator() -> Callable[..., object] | None:
    try:
        return torch.ops.mindclade.pair_weighted_average.default
    except (AttributeError, RuntimeError):
        return None


def pair_weighted_average(
    value: torch.Tensor,
    weights: torch.Tensor,
    mask: torch.Tensor,
    epsilon: float = 1.0e-6,
    *,
    fallback: FallbackPolicy | str = FallbackPolicy.ERROR,
) -> torch.Tensor:
    """Run a qualified native kernel or an explicitly requested reference."""

    validate_inputs(value, weights, mask, epsilon)
    policy = FallbackPolicy(fallback)
    native = _native_operator()
    if native is None:
        if policy is FallbackPolicy.REFERENCE:
            return pair_weighted_average_reference(value, weights, mask, epsilon)
        raise NativeOperatorUnavailable(
            "torch.ops.mindclade.pair_weighted_average is unavailable; load a "
            "qualified native bundle or pass fallback='reference' explicitly"
        )
    result = native(value, weights, mask, epsilon)
    if not isinstance(result, (tuple, list)) or len(result) != 2:
        raise RuntimeError(
            "mindclade::pair_weighted_average violated its (output, lse) contract"
        )
    output = result[0]
    if not isinstance(output, torch.Tensor):
        raise RuntimeError("mindclade::pair_weighted_average returned a non-Tensor output")
    return output
