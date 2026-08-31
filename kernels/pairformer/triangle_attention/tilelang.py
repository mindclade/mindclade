# Copyright (c) 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

"""Offline TileLang builder and optimized mathematics for triangle attention."""

from __future__ import annotations

from collections.abc import Mapping
import importlib

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
