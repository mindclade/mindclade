"""Explicit model-facing dispatch for Pairformer transition."""

from __future__ import annotations

from enum import StrEnum
from typing import Callable

import torch

from .reference import transition_reference, validate_inputs


class FallbackPolicy(StrEnum):
    ERROR = "error"
    REFERENCE = "reference"


class NativeOperatorUnavailable(RuntimeError):
    """Raised when no qualified native transition operator is loaded."""


def _native_operator() -> Callable[..., object] | None:
    try:
        return torch.ops.mindclade.transition.default
    except (AttributeError, RuntimeError):
        return None


def transition(
    gate: torch.Tensor,
    value: torch.Tensor,
    output_weight: torch.Tensor,
    output_bias: torch.Tensor,
    mask: torch.Tensor,
    *,
    fallback: FallbackPolicy | str = FallbackPolicy.ERROR,
) -> torch.Tensor:
    """Run a qualified native kernel or an explicitly selected reference."""

    validate_inputs(gate, value, output_weight, output_bias, mask)
    native = _native_operator()
    if native is None:
        if FallbackPolicy(fallback) is FallbackPolicy.REFERENCE:
            return transition_reference(gate, value, output_weight, output_bias, mask)
        raise NativeOperatorUnavailable(
            "torch.ops.mindclade.transition is unavailable; load a qualified native "
            "bundle or pass fallback='reference' explicitly"
        )
    result = native(gate, value, output_weight, output_bias, mask)
    if not isinstance(result, (tuple, list)) or len(result) != 2:
        raise RuntimeError("mindclade::transition violated its (output, pre_mask_output) contract")
    output = result[0]
    if not isinstance(output, torch.Tensor):
        raise RuntimeError("mindclade::transition returned a non-Tensor output")
    return output
