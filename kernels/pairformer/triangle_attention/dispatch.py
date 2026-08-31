"""Explicit model-facing dispatch for triangle attention."""

from __future__ import annotations

from enum import StrEnum

import torch

from .reference import triangle_attention_reference, validate_inputs


class ReferenceFallback(StrEnum):
    ERROR = "error"
    REFERENCE = "reference"


class NativeOperatorUnavailable(RuntimeError):
    """The generated semantic operator has not been loaded."""


def _native_operator():
    try:
        return torch.ops.mindclade.triangle_attention.default
    except AttributeError:
        return None


def triangle_attention(
    q: torch.Tensor,
    k: torch.Tensor,
    v: torch.Tensor,
    bias: torch.Tensor,
    mask: torch.Tensor,
    scale: float,
    *,
    fallback: ReferenceFallback | str = ReferenceFallback.ERROR,
) -> torch.Tensor:
    """Dispatch explicitly; reference fallback is never implicit.

    Native specializations consume flattened batches and dense bias. Bias
    expansion and materialization therefore happen visibly at this Python
    boundary rather than as a hidden launcher allocation.
    """

    try:
        fallback_policy = ReferenceFallback(fallback)
    except (TypeError, ValueError) as exc:
        raise ValueError("fallback must be 'error' or 'reference'") from exc
    prefix, n, heads = validate_inputs(q, k, v, bias, mask, scale)
    operation = _native_operator()
    if operation is None:
        if fallback_policy is ReferenceFallback.REFERENCE:
            return triangle_attention_reference(q, k, v, bias, mask, scale)
        raise NativeOperatorUnavailable(
            "torch.ops.mindclade.triangle_attention is unavailable; "
            "load a qualified native bundle or request fallback='reference'"
        )

    head_dim = q.shape[-1]
    dense_bias = bias.expand(*prefix, n, heads, n, n).contiguous()
    flat_q = q.reshape(-1, n, n, heads, head_dim)
    flat_k = k.reshape(-1, n, n, heads, head_dim)
    flat_v = v.reshape(-1, n, n, heads, head_dim)
    flat_bias = dense_bias.reshape(-1, n, heads, n, n)
    flat_mask = mask.reshape(-1, n, n)
    output = operation(flat_q, flat_k, flat_v, flat_bias, flat_mask, float(scale))
    return output.reshape(q.shape)


__all__ = ("NativeOperatorUnavailable", "ReferenceFallback", "triangle_attention")
