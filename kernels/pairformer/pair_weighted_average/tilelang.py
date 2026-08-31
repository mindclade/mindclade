# Copyright (c) 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

"""Offline TileLang forward builder for pair weighted average."""

from __future__ import annotations

from typing import Any

_TILELANG_VERSION = "0.1.13"

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
