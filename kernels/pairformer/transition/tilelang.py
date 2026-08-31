# Copyright (c) 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

"""Offline TileLang forward builder for the Pairformer transition contraction."""

from typing import Any

from kernels.native.tilelang.swizzle import (
    CtaRasterPolicy, OperandRole, RasterOrder, SharedLayoutKind,
    SharedLayoutPolicy, apply_cta_raster, shared_layout_for,
)
from kernels.native.tilelang.targets import capability_manifest, normalize_target, validate_toolchain

_SUPPORTED_DTYPES = {"float16", "bfloat16", "float32"}

def build_tilelang_program(
    *,
    target: str,
    batch_size: int,
    rows: int,
    hidden_channels: int,
    output_channels: int,
    dtype: str = "bfloat16",
    mask_dtype: str = "float32",
    block_m: int = 64,
    block_n: int = 64,
    block_k: int = 32,
    num_stages: int = 2,
    threads: int = 128,
    architecture: str | None = None,
    shared_layout: str = "auto",
    raster_panel: int = 0,
    raster_order: str = "row",
    capability_digest: str | None = None,
) -> Any:
    """Return a lazy, offline-compilable tiled GEMM program."""

    if target != "cuda":
        raise ValueError("transition manifest v2 supports the explicit CUDA build lane only")
    if dtype not in _SUPPORTED_DTYPES:
        raise ValueError(f"unsupported transition dtype: {dtype!r}")
    if mask_dtype not in {"bool", "float16", "bfloat16", "float32"}:
        raise ValueError(f"unsupported transition mask dtype: {mask_dtype!r}")
    dimensions = (batch_size, rows, hidden_channels, output_channels)
    if any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in dimensions):
        raise ValueError("transition dimensions must be positive integers")
    tiles = (block_m, block_n, block_k)
    if any(tile not in {16, 32, 64, 128} for tile in tiles):
        raise ValueError("transition tiles must be one of 16, 32, 64, or 128")
    if block_m % 16 or block_n % 16 or block_k % 16:
        raise ValueError("transition tensor-core tiles must be multiples of 16")
    if threads not in {128, 256}:
        raise ValueError("transition threads must be 128 or 256")
    if num_stages not in {1, 2, 3, 4}:
        raise ValueError("transition num_stages must be between one and four")

    import tilelang
    import tilelang.language as T

    target_contract = normalize_target(architecture or target)
    validate_toolchain(target_contract, tilelang_version=str(tilelang.__version__))
    expected_capability_digest = capability_manifest()["semantic_digest"]
    if capability_digest is not None and capability_digest != expected_capability_digest:
        raise ValueError("TileLang capability manifest digest does not match the approved contract")
    layout_kind = SharedLayoutKind(shared_layout)
    raster_policy = CtaRasterPolicy(raster_panel, RasterOrder(raster_order))

    accumulation_dtype = "float32"
    total_rows = batch_size * rows

    @tilelang.jit(out_idx=[5], target=target_contract.tilelang_target)
    def transition_kernel():
        @T.prim_func
        def main(
            Gate: T.Tensor((batch_size, rows, hidden_channels), dtype),
            Value: T.Tensor((batch_size, rows, hidden_channels), dtype),
            OutputWeight: T.Tensor((hidden_channels, output_channels), dtype),
            OutputBias: T.Tensor((output_channels,), dtype),
            Mask: T.Tensor((batch_size, rows), mask_dtype),
            Output: T.Tensor((batch_size, rows, output_channels), dtype),
        ):
            with T.Kernel(
                T.ceildiv(total_rows, block_m),
                T.ceildiv(output_channels, block_n),
                threads=threads,
            ) as (bx, by):
                activation_shared = T.alloc_shared((block_m, block_k), dtype)
                weight_shared = T.alloc_shared((block_k, block_n), dtype)
                accumulator = T.alloc_fragment(
                    (block_m, block_n), accumulation_dtype
                )
                apply_cta_raster(raster_policy, language=T)
                T.annotate_layout(
                    {
                        activation_shared: shared_layout_for(
                            activation_shared,
                            SharedLayoutPolicy(kind=layout_kind, role=OperandRole.GEMM_A, k_major=True),
                            target_contract,
                        ),
                        weight_shared: shared_layout_for(
                            weight_shared,
                            SharedLayoutPolicy(kind=layout_kind, role=OperandRole.GEMM_B, k_major=True),
                            target_contract,
                        ),
                    }
                )
                T.clear(accumulator)

                for ko in T.Pipelined(
                    T.ceildiv(hidden_channels, block_k),
                    num_stages=num_stages,
                ):
                    for i, k in T.Parallel(block_m, block_k):
                        flat_row = bx * block_m + i
                        hidden = ko * block_k + k
                        if flat_row < total_rows and hidden < hidden_channels:
                            batch = flat_row // rows
                            row = flat_row % rows
                            gate_value = T.cast(Gate[batch, row, hidden], accumulation_dtype)
                            input_value = T.cast(Value[batch, row, hidden], accumulation_dtype)
                            silu_value = gate_value / (
                                T.float32(1.0) + T.exp(-gate_value)
                            )
                            activation_shared[i, k] = T.cast(
                                silu_value * input_value, dtype
                            )
                        else:
                            activation_shared[i, k] = T.cast(0, dtype)

                    for k, j in T.Parallel(block_k, block_n):
                        hidden = ko * block_k + k
                        channel = by * block_n + j
                        if hidden < hidden_channels and channel < output_channels:
                            weight_shared[k, j] = OutputWeight[hidden, channel]
                        else:
                            weight_shared[k, j] = T.cast(0, dtype)

                    T.gemm(activation_shared, weight_shared, accumulator)

                for i, j in T.Parallel(block_m, block_n):
                    flat_row = bx * block_m + i
                    channel = by * block_n + j
                    if flat_row < total_rows and channel < output_channels:
                        batch = flat_row // rows
                        row = flat_row % rows
                        if Mask[batch, row] != 0:
                            Output[batch, row, channel] = T.cast(
                                accumulator[i, j]
                                + T.cast(OutputBias[channel], accumulation_dtype),
                                dtype,
                            )
                        else:
                            Output[batch, row, channel] = T.cast(0, dtype)

        return main

    return transition_kernel
