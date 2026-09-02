"""Explicit model-facing dispatch for Pairformer triangle attention."""

from __future__ import annotations

from enum import StrEnum
from typing import Callable

import torch

from .reference import triangle_attention_reference, validate_inputs


class FallbackPolicy(StrEnum):
    ERROR = "error"
    REFERENCE = "reference"


ReferenceFallback = FallbackPolicy


class NativeOperatorUnavailable(RuntimeError):
    """Raised when no qualified triangle-attention bundle is loaded."""


def _native_operator() -> Callable[..., object] | None:
    try:
        return torch.ops.mindclade.triangle_attention.default
    except (AttributeError, RuntimeError):
        return None


def triangle_attention(
    q: torch.Tensor,
    k: torch.Tensor,
    v: torch.Tensor,
    bias: torch.Tensor,
    mask: torch.Tensor,
    scale: float,
    *,
    fallback: FallbackPolicy | str = FallbackPolicy.ERROR,
) -> torch.Tensor:
    """Normalize the facade contract and dispatch without implicit fallback."""

    prefix, n, heads = validate_inputs(q, k, v, bias, mask, scale)
    policy = FallbackPolicy(fallback)
    native = _native_operator()
    if native is None:
        if policy is FallbackPolicy.REFERENCE:
            return triangle_attention_reference(q, k, v, bias, mask, scale)
        raise NativeOperatorUnavailable(
            "torch.ops.mindclade.triangle_attention is unavailable; load a qualified "
            "native bundle or pass fallback='reference' explicitly"
        )

    head_dim = q.shape[-1]
    dense_bias = bias.expand(*prefix, n, heads, n, n).contiguous()
    dense_mask = mask.unsqueeze(-2).expand(*prefix, n, n, n).contiguous()
    flat_q = q.reshape(-1, n, heads, head_dim)
    flat_k = k.reshape(-1, n, heads, head_dim)
    flat_v = v.reshape(-1, n, heads, head_dim)
    flat_bias = dense_bias.reshape(-1, heads, n, n)
    flat_mask = dense_mask.reshape(-1, n, n)
    result = native(flat_q, flat_k, flat_v, flat_bias, flat_mask, scale)
    if not isinstance(result, (tuple, list)) or len(result) != 2:
        raise RuntimeError(
            "mindclade::triangle_attention violated its (output, lse) contract"
        )
    output = result[0]
    if not isinstance(output, torch.Tensor):
        raise RuntimeError("mindclade::triangle_attention returned non-Tensor output")
    return output.reshape(q.shape)
