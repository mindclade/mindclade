# Copyright (c) 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

from __future__ import annotations

from typing import Any
import math

import torch

from kernels.native.tilelang.decorator import mindclade_kernel


_SCHEMA = (
    "pair_weighted_average(Tensor value, Tensor weights, Tensor mask, "
    "float epsilon) -> Tensor"
)
_MODULE = "kernels.pairformer.pair_weighted_average.tilelang"
_TILELANG_VERSION = "0.1.13"
_FLOAT_DTYPES = {
    torch.float16,
    torch.bfloat16,
    torch.float32,
    torch.float64,
}


def _validate_inputs(
    value: torch.Tensor,
    weights: torch.Tensor,
    mask: torch.Tensor,
    epsilon: float,
) -> tuple[tuple[int, ...], int, int, int]:
    if not isinstance(value, torch.Tensor):
        raise TypeError("value must be a Tensor")
    if not isinstance(weights, torch.Tensor):
        raise TypeError("weights must be a Tensor")
    if not isinstance(mask, torch.Tensor):
        raise TypeError("mask must be a Tensor")
    if value.ndim < 2:
        raise ValueError("value must have shape [..., N, C]")
    if weights.ndim != value.ndim + 1:
        raise ValueError("weights must have shape [..., N, N, H]")
    if mask.ndim != value.ndim - 1:
        raise ValueError("mask must have shape [..., N]")

    batch_shape = tuple(value.shape[:-2])
    residues = value.shape[-2]
    channels = value.shape[-1]
    heads = weights.shape[-1]
    if tuple(weights.shape[:-3]) != batch_shape:
        raise ValueError("weights batch dimensions must match value")
    if tuple(mask.shape[:-1]) != batch_shape:
        raise ValueError("mask batch dimensions must match value")
    if weights.shape[-3] != residues or weights.shape[-2] != residues:
        raise ValueError("both weights residue dimensions must equal value N")
    if mask.shape[-1] != residues:
        raise ValueError("mask source dimension must equal value N")
    if residues == 0 or channels == 0 or heads == 0:
        raise ValueError("N, C, and H must be nonzero")

    if value.dtype not in _FLOAT_DTYPES:
        raise TypeError("value must use a floating-point dtype")
    if weights.dtype != value.dtype:
        raise TypeError("weights dtype must equal value dtype")
    if mask.dtype != torch.bool and not mask.dtype.is_floating_point:
        raise TypeError("mask must use bool or a floating-point dtype")
    if value.device != weights.device or value.device != mask.device:
        raise ValueError("value, weights, and mask must use the same device")
    if isinstance(epsilon, bool) or not isinstance(epsilon, (int, float)):
        raise TypeError("epsilon must be a real scalar")
    if not math.isfinite(float(epsilon)) or float(epsilon) <= 0.0:
        raise ValueError("epsilon must be finite and greater than zero")
    return batch_shape, residues, channels, heads


def _reference(
    value: torch.Tensor,
    weights: torch.Tensor,
    mask: torch.Tensor,
    epsilon: float,
) -> torch.Tensor:
    """Differentiable PyTorch definition used by tests and autograd replay."""

    _validate_inputs(value, weights, mask, epsilon)
    accumulation_dtype = (
        torch.float32
        if value.dtype in {torch.float16, torch.bfloat16}
        else value.dtype
    )
    logits = weights.to(dtype=accumulation_dtype)
    values = value.to(dtype=accumulation_dtype)
    source_mask = (mask != 0).unsqueeze(-2).unsqueeze(-1)
    masked_logits = torch.where(
        source_mask,
        logits,
        torch.full_like(logits, -torch.inf),
    )
    has_source = source_mask.any(dim=-2, keepdim=True)
    row_max = masked_logits.amax(dim=-2, keepdim=True)
    safe_row_max = torch.where(has_source, row_max, torch.zeros_like(row_max))
    exponentials = torch.where(
        source_mask,
        torch.exp(logits - safe_row_max),
        torch.zeros_like(logits),
    )
    denominator = exponentials.sum(dim=-2, keepdim=True)
    probabilities = torch.where(
        has_source,
        exponentials / denominator.clamp_min(float(epsilon)),
        torch.zeros_like(exponentials),
    )
    output = torch.einsum("...ijh,...jc->...ihc", probabilities, values)
    return output.to(dtype=value.dtype)


def fake(
    value: torch.Tensor,
    weights: torch.Tensor,
    mask: torch.Tensor,
    epsilon: float,
) -> torch.Tensor:
    batch_shape, residues, channels, heads = _validate_inputs(
        value, weights, mask, epsilon
    )
    return value.new_empty((*batch_shape, residues, heads, channels))


def setup_context(ctx: Any, inputs: tuple[Any, ...], output: torch.Tensor) -> None:
    del output
    value, weights, mask, epsilon = inputs
    ctx.save_for_backward(value, weights, mask)
    ctx.epsilon = float(epsilon)


def backward(
    ctx: Any, grad_output: torch.Tensor
) -> tuple[torch.Tensor | None, torch.Tensor | None, None, None]:
    value, weights, mask = ctx.saved_tensors
    need_value, need_weights = ctx.needs_input_grad[:2]
    if not need_value and not need_weights:
        return None, None, None, None

    create_graph = torch.is_grad_enabled()
    with torch.enable_grad():
        replay = _reference(value, weights, mask, ctx.epsilon)
        requested = tuple(
            tensor
            for tensor, needed in (
                (value, need_value),
                (weights, need_weights),
            )
            if needed
        )
        computed = torch.autograd.grad(
            replay,
            requested,
            grad_output,
            create_graph=create_graph,
            allow_unused=False,
        )

    grad_value: torch.Tensor | None = None
    grad_weights: torch.Tensor | None = None
    offset = 0
    if need_value:
        grad_value = computed[offset]
        offset += 1
    if need_weights:
        grad_weights = computed[offset]
    return grad_value, grad_weights, None, None


def _bounded_profile_int(
    name: str,
    value: int,
    *,
    maximum: int,
    allowed: frozenset[int] | None = None,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if value < 1 or value > maximum:
        raise ValueError(f"{name} must be in [1, {maximum}]")
    if allowed is not None and value not in allowed:
        choices = ", ".join(str(choice) for choice in sorted(allowed))
        raise ValueError(f"{name} must be one of: {choices}")
    return value


@mindclade_kernel(
    name="pair_weighted_average",
    schema="pair_weighted_average(Tensor value, Tensor weights, Tensor mask, float epsilon) -> Tensor",
    family="pairformer",
    fake={"module": "kernels.pairformer.pair_weighted_average.tilelang", "symbol": "fake"},
    autograd={
        "mode": "registered",
        "setup_context": {
            "module": "kernels.pairformer.pair_weighted_average.tilelang",
            "symbol": "setup_context",
        },
        "backward": {
            "module": "kernels.pairformer.pair_weighted_average.tilelang",
            "symbol": "backward",
        },
    },
)
def build_tilelang_program(
    *,
    target: str,
    batch_size: int,
    num_residues: int,
    channels: int,
    heads: int,
    dtype: str = "float16",
    mask_dtype: str = "float32",
    block_sources: int = 64,
    threads: int = 128,
) -> Any:
    """Return a lazy, shape-specialized TileLang CUDA program."""

    if target != "cuda":
        raise ValueError("pair_weighted_average supports only target='cuda'")
    batch_size = _bounded_profile_int("batch_size", batch_size, maximum=65535)
    num_residues = _bounded_profile_int(
        "num_residues", num_residues, maximum=8192
    )
    channels = _bounded_profile_int("channels", channels, maximum=4096)
    heads = _bounded_profile_int("heads", heads, maximum=256)
    block_sources = _bounded_profile_int(
        "block_sources",
        block_sources,
        maximum=128,
        allowed=frozenset({16, 32, 64, 128}),
    )
    threads = _bounded_profile_int(
        "threads",
        threads,
        maximum=256,
        allowed=frozenset({32, 64, 128, 256}),
    )
    if dtype not in {"float16", "bfloat16", "float32"}:
        raise ValueError("dtype must be float16, bfloat16, or float32")
    if mask_dtype not in {"bool", "float32"}:
        raise ValueError("mask_dtype must be bool or float32")
    output_elements = batch_size * num_residues * heads * channels
    if output_elements > 2_147_483_647:
        raise ValueError("profile output element count exceeds signed int32")

    try:
        import tilelang
        import tilelang.language as T
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "TileLang 0.1.13 is required by the offline CUDA build toolchain"
        ) from exc
    installed_version = getattr(tilelang, "__version__", "")
    if installed_version.split("+", 1)[0] != _TILELANG_VERSION:
        raise RuntimeError(
            f"TileLang {_TILELANG_VERSION} is required; got {installed_version!r}"
        )

    @tilelang.jit(out_idx=[4], target="cuda")
    def program():
        @T.prim_func
        def kernel(
            value: T.Tensor(
                (batch_size, num_residues, channels), dtype
            ),
            weights: T.Tensor(
                (batch_size, num_residues, num_residues, heads), dtype
            ),
            mask: T.Tensor((batch_size, num_residues), mask_dtype),
            epsilon: T.float32,
            output: T.Tensor(
                (batch_size, num_residues, heads, channels), dtype
            ),
        ):
            with T.Kernel(
                T.ceildiv(output_elements, threads), threads=threads
            ) as block:
                row_max = T.alloc_local((1,), "float32")
                denominator = T.alloc_local((1,), "float32")
                accumulator = T.alloc_local((1,), "float32")
                has_source = T.alloc_local((1,), "int32")
                for lane in T.Parallel(threads):
                    flat = block * threads + lane
                    if flat < output_elements:
                        channel = flat % channels
                        head = (flat // channels) % heads
                        destination = (
                            flat // (channels * heads)
                        ) % num_residues
                        batch = flat // (
                            channels * heads * num_residues
                        )
                        row_max[0] = -T.infinity("float32")
                        has_source[0] = 0
                        for source_tile in T.serial(
                            T.ceildiv(num_residues, block_sources)
                        ):
                            for source_offset in T.serial(block_sources):
                                source = (
                                    source_tile * block_sources
                                    + source_offset
                                )
                                if (
                                    source < num_residues
                                    and mask[batch, source] != 0
                                ):
                                    row_max[0] = T.max(
                                        row_max[0],
                                        T.cast(
                                            weights[
                                                batch,
                                                destination,
                                                source,
                                                head,
                                            ],
                                            "float32",
                                        ),
                                    )
                                    has_source[0] = 1

                        denominator[0] = 0.0
                        accumulator[0] = 0.0
                        if has_source[0] != 0:
                            for source_tile in T.serial(
                                T.ceildiv(num_residues, block_sources)
                            ):
                                for source_offset in T.serial(block_sources):
                                    source = (
                                        source_tile * block_sources
                                        + source_offset
                                    )
                                    if (
                                        source < num_residues
                                        and mask[batch, source] != 0
                                    ):
                                        probability_numerator = T.exp(
                                            T.cast(
                                                weights[
                                                    batch,
                                                    destination,
                                                    source,
                                                    head,
                                                ],
                                                "float32",
                                            )
                                            - row_max[0]
                                        )
                                        denominator[0] += (
                                            probability_numerator
                                        )
                                        accumulator[0] += (
                                            probability_numerator
                                            * T.cast(
                                                value[
                                                    batch,
                                                    source,
                                                    channel,
                                                ],
                                                "float32",
                                            )
                                        )
                            output[
                                batch, destination, head, channel
                            ] = T.cast(
                                accumulator[0]
                                / T.max(denominator[0], epsilon),
                                dtype,
                            )
                        else:
                            output[
                                batch, destination, head, channel
                            ] = T.cast(0.0, dtype)

        return kernel

    return program
