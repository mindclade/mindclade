"""Explicit model-facing dispatch for outer-product mean."""

from __future__ import annotations

from enum import StrEnum
from typing import Callable

import torch

from .reference import outer_product_mean_reference, validate_inputs


class FallbackPolicy(StrEnum):
    ERROR = "error"
    REFERENCE = "reference"


class NativeOperatorUnavailable(RuntimeError):
    """Raised when the qualified native operator is not loaded."""


def _native_operator() -> Callable[..., object] | None:
    try:
        return torch.ops.mindclade.outer_product_mean.default
    except (AttributeError, RuntimeError):
        return None


def outer_product_mean(
    left: torch.Tensor,
    right: torch.Tensor,
    mask: torch.Tensor,
    epsilon: float = 1.0e-6,
    *,
    fallback: FallbackPolicy | str = FallbackPolicy.ERROR,
) -> torch.Tensor:
    """Run a qualified native kernel or an explicitly requested reference."""

    validate_inputs(left, right, mask, epsilon)
    policy = FallbackPolicy(fallback)
    native = _native_operator()
    if native is None:
        if policy is FallbackPolicy.REFERENCE:
            return outer_product_mean_reference(left, right, mask, epsilon)
        raise NativeOperatorUnavailable(
            "torch.ops.mindclade.outer_product_mean is unavailable; load a qualified "
            "native bundle or pass fallback='reference' explicitly"
        )
    result = native(left, right, mask, epsilon)
    if not isinstance(result, (tuple, list)) or len(result) != 2:
        raise RuntimeError(
            "mindclade::outer_product_mean violated its (output, normalizer) contract"
        )
    output = result[0]
    if not isinstance(output, torch.Tensor):
        raise RuntimeError("mindclade::outer_product_mean returned a non-Tensor output")
    return output
