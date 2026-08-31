# Copyright (c) 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

"""Triangle attention semantics and the bounded TileLang CUDA implementation.

The semantic contract accepts arbitrary leading batch dimensions and a bias
broadcastable to ``[..., N, H, N, N]``. Offline TileLang specializations flatten
those leading dimensions into ``batch`` and consume a dense expanded bias. The
operation-specific launch adapter is responsible for that materialization; it
must not broaden the accepted contract or compile at request time.
"""

from __future__ import annotations

from collections.abc import Mapping
import importlib
import math
from numbers import Real
from typing import Any

import torch

from kernels.native.tilelang.decorator import mindclade_kernel


_SCHEMA = (
    "triangle_attention(Tensor q, Tensor k, Tensor v, Tensor bias, Tensor mask, "
    "float scale) -> Tensor"
)
_MODULE = "kernels.pairformer.triangle_attention.tilelang"
_TILELANG_VERSION = "0.1.13"
_SUPPORTED_DTYPES = frozenset({"float16", "bfloat16", "float32"})
_SUPPORTED_HEAD_DIMS = frozenset({16, 32, 64, 128})
_SUPPORTED_THREADS = frozenset({32, 64, 128, 256})
_MAX_BATCH = 64
_MAX_N = 256
_MAX_HEADS = 64
_MAX_ROWS = 2_147_483_647

TRIANGLE_ATTENTION_PROFILES: tuple[Mapping[str, object], ...] = (
    {
        "name": "b1_n32_h4_d32_fp16",
        "arguments": {
            "batch": 1,
            "n": 32,
            "heads": 4,
            "head_dim": 32,
            "dtype": "float16",
            "threads": 64,
        },
    },
    {
        "name": "b1_n64_h8_d32_fp16",
        "arguments": {
            "batch": 1,
            "n": 64,
            "heads": 8,
            "head_dim": 32,
            "dtype": "float16",
            "threads": 128,
        },
    },
    {
        "name": "b1_n128_h8_d64_bf16",
        "arguments": {
            "batch": 1,
            "n": 128,
            "heads": 8,
            "head_dim": 64,
            "dtype": "bfloat16",
            "threads": 128,
        },
    },
    {
        "name": "b2_n64_h8_d64_fp32",
        "arguments": {
            "batch": 2,
            "n": 64,
            "heads": 8,
            "head_dim": 64,
            "dtype": "float32",
            "threads": 128,
        },
    },
)


def _check(condition: object, message: str) -> None:
    if type(condition) is bool:
        if not condition:
            raise ValueError(message)
        return
    torch._check(condition, lambda: message)


def _require_tensor(name: str, value: object) -> torch.Tensor:
    if not isinstance(value, torch.Tensor):
        raise TypeError(f"{name} must be a torch.Tensor")
    return value


def _validate_inputs(
    q: torch.Tensor,
    k: torch.Tensor,
    v: torch.Tensor,
    bias: torch.Tensor,
    mask: torch.Tensor,
    scale: float,
) -> tuple[tuple[torch.SymInt | int, ...], torch.SymInt | int, torch.SymInt | int]:
    q = _require_tensor("q", q)
    k = _require_tensor("k", k)
    v = _require_tensor("v", v)
    bias = _require_tensor("bias", bias)
    mask = _require_tensor("mask", mask)

    if q.dim() < 4:
        raise ValueError("q must have shape [..., N, N, H, D]")
    if k.dim() != q.dim() or v.dim() != q.dim():
        raise ValueError("q, k, and v must have the same rank")
    for axis in range(q.dim()):
        _check(k.shape[axis] == q.shape[axis], "q, k, and v must have identical shapes")
        _check(v.shape[axis] == q.shape[axis], "q, k, and v must have identical shapes")

    n = q.shape[-4]
    heads = q.shape[-2]
    head_dim = q.shape[-1]
    _check(n == q.shape[-3], "q, k, and v require equal pair dimensions N")
    _check(n > 0, "N must be positive")
    _check(heads > 0, "H must be positive")
    _check(head_dim > 0, "D must be positive")

    if not q.dtype.is_floating_point:
        raise TypeError("q, k, and v must use a floating-point dtype")
    if k.dtype != q.dtype or v.dtype != q.dtype:
        raise TypeError("q, k, and v must use the same dtype")
    if bias.dtype != q.dtype:
        raise TypeError("bias must use the q dtype")
    if mask.dtype != torch.bool:
        raise TypeError("mask must use torch.bool")
    if any(tensor.device != q.device for tensor in (k, v, bias, mask)):
        raise ValueError("q, k, v, bias, and mask must be on the same device")

    prefix = tuple(q.shape[:-4])
    expected_mask = (*prefix, n, n)
    if mask.dim() != len(expected_mask):
        raise ValueError("mask must have shape [..., N, N] with the q batch prefix")
    for axis, expected in enumerate(expected_mask):
        _check(
            mask.shape[axis] == expected,
            "mask must have shape [..., N, N] with the q batch prefix",
        )

    bias_target = (*prefix, n, heads, n, n)
    try:
        broadcast_shape = torch.broadcast_shapes(tuple(bias.shape), bias_target)
    except RuntimeError as exc:
        raise ValueError("bias must be broadcastable to [..., N, H, N, N]") from exc
    if len(broadcast_shape) != len(bias_target):
        raise ValueError("bias must be broadcastable to [..., N, H, N, N]")
    for actual, expected in zip(broadcast_shape, bias_target, strict=True):
        _check(actual == expected, "bias must be broadcastable to [..., N, H, N, N]")

    if isinstance(scale, bool) or not isinstance(scale, Real):
        raise TypeError("scale must be a finite real number")
    if not math.isfinite(float(scale)):
        raise ValueError("scale must be finite")
    return prefix, n, heads


def triangle_attention_reference(
    q: torch.Tensor,
    k: torch.Tensor,
    v: torch.Tensor,
    bias: torch.Tensor,
    mask: torch.Tensor,
    scale: float,
) -> torch.Tensor:
    """Apply stable masked triangle attention over the source residue axis."""

    _validate_inputs(q, k, v, bias, mask, scale)
    accumulation_dtype = (
        torch.float32 if q.dtype in {torch.float16, torch.bfloat16} else q.dtype
    )
    q_acc = q.to(accumulation_dtype)
    k_acc = k.to(accumulation_dtype)
    v_acc = v.to(accumulation_dtype)
    logits = torch.einsum("...ijhd,...ikhd->...ihjk", q_acc, k_acc)
    logits = logits * float(scale) + bias.to(accumulation_dtype)

    valid = mask.unsqueeze(-2).unsqueeze(-2)
    masked_logits = logits.masked_fill(~valid, -torch.inf)
    has_source = valid.any(dim=-1, keepdim=True)
    row_max = masked_logits.amax(dim=-1, keepdim=True)
    row_max = torch.where(has_source, row_max, torch.zeros_like(row_max))
    exponentials = torch.exp(masked_logits - row_max)
    denominator = exponentials.sum(dim=-1, keepdim=True)
    safe_denominator = torch.where(has_source, denominator, torch.ones_like(denominator))
    weights = exponentials / safe_denominator

    safe_v = torch.where(mask.unsqueeze(-1).unsqueeze(-1), v_acc, torch.zeros_like(v_acc))
    output = torch.einsum("...ihjk,...ikhd->...ijhd", weights, safe_v)
    output_has_source = mask.any(dim=-1)[..., :, None, None, None]
    output = torch.where(output_has_source, output, torch.zeros_like(output))
    return output.to(q.dtype)


def fake(
    q: torch.Tensor,
    k: torch.Tensor,
    v: torch.Tensor,
    bias: torch.Tensor,
    mask: torch.Tensor,
    scale: float,
) -> torch.Tensor:
    """Validate the abstract contract and return a shape/dtype/device-faithful tensor."""

    _validate_inputs(q, k, v, bias, mask, scale)
    return q.new_empty(q.shape)


def setup_context(ctx: Any, inputs: tuple[object, ...], output: torch.Tensor) -> None:
    del output
    q, k, v, bias, mask, scale = inputs
    if not all(isinstance(tensor, torch.Tensor) for tensor in (q, k, v, bias, mask)):
        raise TypeError("triangle_attention autograd context received non-tensor inputs")
    ctx.save_for_backward(q, k, v, bias, mask)
    ctx.scale = float(scale)


def backward(ctx: Any, grad_output: torch.Tensor) -> tuple[torch.Tensor | None, ...]:
    """Recompute the safe PyTorch reference and differentiate tensor inputs."""

    q, k, v, bias, mask = ctx.saved_tensors
    needs = tuple(getattr(ctx, "needs_input_grad", (True, True, True, True, False, False)))
    if len(needs) != 6:
        raise RuntimeError("triangle_attention autograd context has invalid input arity")

    tensor_inputs = [q, k, v, bias]
    recompute_inputs: list[torch.Tensor] = []
    differentiable: list[torch.Tensor] = []
    differentiable_positions: list[int] = []
    for position, tensor in enumerate(tensor_inputs):
        candidate = tensor
        if needs[position] and not candidate.requires_grad:
            candidate = candidate.detach().requires_grad_(True)
        recompute_inputs.append(candidate)
        if needs[position]:
            differentiable.append(candidate)
            differentiable_positions.append(position)

    result: list[torch.Tensor | None] = [None, None, None, None, None, None]
    if not differentiable:
        return tuple(result)

    create_graph = torch.is_grad_enabled()
    with torch.enable_grad():
        output = triangle_attention_reference(
            recompute_inputs[0],
            recompute_inputs[1],
            recompute_inputs[2],
            recompute_inputs[3],
            mask,
            ctx.scale,
        )
        gradients = torch.autograd.grad(
            output,
            differentiable,
            grad_output,
            allow_unused=False,
            create_graph=create_graph,
        )
    for position, gradient in zip(differentiable_positions, gradients, strict=True):
        result[position] = gradient
    return tuple(result)


def _validate_build_profile(
    *,
    target: str,
    batch: int,
    n: int,
    heads: int,
    head_dim: int,
    dtype: str,
    threads: int,
) -> None:
    if target != "cuda":
        raise ValueError("triangle_attention TileLang target must be exactly 'cuda'")
    for name, value, maximum in (
        ("batch", batch, _MAX_BATCH),
        ("n", n, _MAX_N),
        ("heads", heads, _MAX_HEADS),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
            raise ValueError(f"{name} must be an integer in [1, {maximum}]")
    if head_dim not in _SUPPORTED_HEAD_DIMS:
        raise ValueError(f"head_dim must be one of {sorted(_SUPPORTED_HEAD_DIMS)}")
    if dtype not in _SUPPORTED_DTYPES:
        raise ValueError(f"dtype must be one of {sorted(_SUPPORTED_DTYPES)}")
    if threads not in _SUPPORTED_THREADS or threads < head_dim:
        raise ValueError(
            f"threads must be one of {sorted(_SUPPORTED_THREADS)} and at least head_dim"
        )
    rows = batch * n * n * heads
    if rows > _MAX_ROWS:
        raise ValueError("specialization exceeds the bounded CUDA grid row count")


@mindclade_kernel(
    name="triangle_attention",
    schema="triangle_attention(Tensor q, Tensor k, Tensor v, Tensor bias, Tensor mask, float scale) -> Tensor",
    family="pairformer",
    fake={"module": "kernels.pairformer.triangle_attention.tilelang", "symbol": "fake"},
    autograd={
        "mode": "registered",
        "setup_context": {
            "module": "kernels.pairformer.triangle_attention.tilelang",
            "symbol": "setup_context",
        },
        "backward": {
            "module": "kernels.pairformer.triangle_attention.tilelang",
            "symbol": "backward",
        },
    },
    namespace="mindclade",
    backend="tilelang",
    version=1,
    launch_symbol="mindclade_tilelang_triangle_attention_launch",
    devices=("cuda",),
)
def build_tilelang_program(
    *,
    target: str,
    batch: int,
    n: int,
    heads: int,
    head_dim: int,
    dtype: str,
    threads: int,
):
    """Return a lazy, compilable TileLang 0.1.13 CUDA specialization.

    Inputs use flattened batch shapes ``[B,N,N,H,D]`` and dense bias shape
    ``[B,N,H,N,N]``. This correctness-first baseline assigns one CUDA block to
    each attention row and parallelizes output channels without cross-thread
    reductions, avoiding reduction-order ambiguity for masked rows.
    """

    _validate_build_profile(
        target=target,
        batch=batch,
        n=n,
        heads=heads,
        head_dim=head_dim,
        dtype=dtype,
        threads=threads,
    )
    try:
        tilelang = importlib.import_module("tilelang")
        T = importlib.import_module("tilelang.language")
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "TileLang 0.1.13 is required only in the trusted offline CUDA build environment"
        ) from exc
    version = getattr(tilelang, "__version__", None)
    if version != _TILELANG_VERSION:
        raise RuntimeError(
            f"triangle_attention requires TileLang {_TILELANG_VERSION}, found {version!r}"
        )

    tensor_shape = (batch, n, n, heads, head_dim)
    bias_shape = (batch, n, heads, n, n)
    mask_shape = (batch, n, n)
    accumulation_dtype = "float32"
    row_count = batch * n * n * heads

    @tilelang.jit(out_idx=[-1], target=target)
    def triangle_attention_cuda():
        @T.prim_func
        def kernel(
            Q: T.Tensor(tensor_shape, dtype),
            K: T.Tensor(tensor_shape, dtype),
            V: T.Tensor(tensor_shape, dtype),
            Bias: T.Tensor(bias_shape, dtype),
            Mask: T.Tensor(mask_shape, "bool"),
            Scale: T.float32,
            Output: T.Tensor(tensor_shape, dtype),
        ):
            with T.Kernel(row_count, threads=threads) as row:
                h_index = row % heads
                row_without_head = row // heads
                j_index = row_without_head % n
                row_without_j = row_without_head // n
                i_index = row_without_j % n
                batch_index = row_without_j // n

                score = T.alloc_fragment((head_dim,), accumulation_dtype)
                row_max = T.alloc_fragment((head_dim,), accumulation_dtype)
                denominator = T.alloc_fragment((head_dim,), accumulation_dtype)
                output_accumulator = T.alloc_fragment((head_dim,), accumulation_dtype)
                valid_count = T.alloc_fragment((head_dim,), "int32")
                T.fill(row_max, -T.infinity(accumulation_dtype))
                T.clear(denominator)
                T.clear(output_accumulator)
                T.clear(valid_count)

                for output_dim in T.Parallel(head_dim):
                    for source_index in T.serial(n):
                        if Mask[batch_index, i_index, source_index]:
                            score[output_dim] = 0.0
                            for reduction_dim in T.serial(head_dim):
                                score[output_dim] += (
                                    Q[batch_index, i_index, j_index, h_index, reduction_dim]
                                    * K[
                                        batch_index,
                                        i_index,
                                        source_index,
                                        h_index,
                                        reduction_dim,
                                    ]
                                )
                            score[output_dim] = (
                                score[output_dim] * Scale
                                + Bias[
                                    batch_index,
                                    i_index,
                                    h_index,
                                    j_index,
                                    source_index,
                                ]
                            )
                            row_max[output_dim] = T.max(
                                row_max[output_dim], score[output_dim]
                            )
                            valid_count[output_dim] += 1

                for output_dim in T.Parallel(head_dim):
                    if valid_count[output_dim] > 0:
                        for source_index in T.serial(n):
                            if Mask[batch_index, i_index, source_index]:
                                score[output_dim] = 0.0
                                for reduction_dim in T.serial(head_dim):
                                    score[output_dim] += (
                                        Q[
                                            batch_index,
                                            i_index,
                                            j_index,
                                            h_index,
                                            reduction_dim,
                                        ]
                                        * K[
                                            batch_index,
                                            i_index,
                                            source_index,
                                            h_index,
                                            reduction_dim,
                                        ]
                                    )
                                score[output_dim] = T.exp(
                                    score[output_dim] * Scale
                                    + Bias[
                                        batch_index,
                                        i_index,
                                        h_index,
                                        j_index,
                                        source_index,
                                    ]
                                    - row_max[output_dim]
                                )
                                denominator[output_dim] += score[output_dim]
                                output_accumulator[output_dim] += (
                                    score[output_dim]
                                    * V[
                                        batch_index,
                                        i_index,
                                        source_index,
                                        h_index,
                                        output_dim,
                                    ]
                                )
                        Output[batch_index, i_index, j_index, h_index, output_dim] = (
                            output_accumulator[output_dim] / denominator[output_dim]
                        )
                    else:
                        Output[batch_index, i_index, j_index, h_index, output_dim] = 0.0

        return kernel

    return triangle_attention_cuda


assert _SCHEMA == build_tilelang_program.__mindclade_kernel__["schema"]
