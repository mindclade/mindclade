"""Offline TileLang FWD/BWD builders for triangle multiplication."""

from __future__ import annotations

from typing import Any

_ARCHITECTURES = {"sm90a": "sm_90a", "sm100a": "sm_100a"}


def _prepare(
    *, target: str, architecture: str, batch: int, residues: int,
    channels: int, outgoing: bool, dtype: str, block_channels: int, threads: int,
    block_residues: int = 64, reduction_block: int = 32,
    num_stages: int = 3, enable_rasterization: bool = True,
) -> tuple[Any, str]:
    if target != "cuda":
        raise ValueError("triangle_multiplication target must be exactly cuda")
    if architecture not in _ARCHITECTURES:
        raise ValueError("architecture must be sm90a or sm100a")
    if any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in (batch, residues, channels)):
        raise ValueError("batch, residues, and channels must be positive integers")
    if dtype not in {"float16", "bfloat16"}:
        raise ValueError("production dtype must be float16 or bfloat16")
    if block_channels not in {32, 64, 128} or threads not in {64, 128, 256}:
        raise ValueError("profile is outside the bounded schedule inventory")
    if block_residues not in {32, 64, 128}:
        raise ValueError("block_residues must be one of 32, 64, or 128")
    if reduction_block not in {16, 32, 64}:
        raise ValueError("reduction_block must be one of 16, 32, or 64")
    if num_stages not in {2, 3, 4}:
        raise ValueError("num_stages must be one of 2, 3, or 4")
    if not isinstance(enable_rasterization, bool):
        raise TypeError("enable_rasterization must be a bool")
    if not isinstance(outgoing, bool):
        raise TypeError("outgoing must be a bool")
    try:
        import tilelang
        import tilelang.language as T
    except ModuleNotFoundError as exc:  # pragma: no cover - compile lane only
        raise RuntimeError("TileLang 0.1.13 is required in the offline CUDA build lane") from exc
    if getattr(tilelang, "__version__", None) != "0.1.13":
        raise RuntimeError(
            f"TileLang 0.1.13 is required, found {getattr(tilelang, '__version__', 'unknown')}"
        )
    return T, _ARCHITECTURES[architecture]


def _descriptor(
    *, phase: str, logical_symbol: str, execution_order: tuple[str, ...],
    workspaces: tuple[str, ...],
) -> dict[str, object]:
    return {
        "phase": phase,
        "logical_symbol": logical_symbol,
        "execution_order": execution_order,
        "workspaces": workspaces,
        "version": 1,
    }


def build_forward_program_group(**_: object) -> dict[str, object]:
    return _descriptor(
        phase="forward",
        logical_symbol="mindclade_tilelang_triangle_multiplication_fwd_launch",
        execution_order=("forward",),
        workspaces=(),
    )


def build_backward_program_group(**_: object) -> dict[str, object]:
    return _descriptor(
        phase="backward",
        logical_symbol="mindclade_tilelang_triangle_multiplication_bwd_launch",
        execution_order=("dleft", "dright"),
        workspaces=(),
    )


def build_forward_program(
    *, target: str, architecture: str, batch: int, residues: int,
    channels: int, outgoing: bool, dtype: str = "float16",
    block_channels: int = 64, threads: int = 128,
    block_residues: int = 64, reduction_block: int = 32,
    num_stages: int = 3, enable_rasterization: bool = True, **_: object,
) -> Any:
    T, target_arch = _prepare(
        target=target, architecture=architecture, batch=batch, residues=residues,
        channels=channels, outgoing=outgoing, dtype=dtype,
        block_channels=block_channels, threads=threads,
        block_residues=block_residues, reduction_block=reduction_block,
        num_stages=num_stages, enable_rasterization=enable_rasterization,
    )

    tilelang = __import__("tilelang")

    @tilelang.jit(out_idx=[3], target=target_arch)
    @T.prim_func
    def mindclade_tilelang_triangle_multiplication_forward_raw(
        left: T.Tensor((batch, residues, residues, channels), dtype),
        right: T.Tensor((batch, residues, residues, channels), dtype),
        mask: T.Tensor((batch, residues, residues), dtype),
        output: T.Tensor((batch, residues, residues, channels), dtype),
    ):
        with T.Kernel(
            T.ceildiv(residues, block_residues),
            T.ceildiv(residues, block_residues),
            batch * channels,
            threads=threads,
        ) as (column_block, row_block, batch_channel):
            batch_index = batch_channel // channels
            channel = batch_channel % channels
            left_shared = T.alloc_shared(
                (block_residues, reduction_block), dtype
            )
            right_shared = T.alloc_shared(
                (block_residues, reduction_block), dtype
            )
            accumulation = T.alloc_fragment(
                (block_residues, block_residues), "float32"
            )
            T.use_swizzle(panel_size=10, enable=enable_rasterization)
            T.clear(accumulation)
            for reduction_tile in T.Pipelined(
                T.ceildiv(residues, reduction_block),
                num_stages=num_stages,
            ):
                for local_row, local_reduction in T.Parallel(
                    block_residues, reduction_block
                ):
                    row = row_block * block_residues + local_row
                    reduction = reduction_tile * reduction_block + local_reduction
                    if row < residues and reduction < residues:
                        if outgoing:
                            left_shared[local_row, local_reduction] = T.Cast(
                                dtype,
                                T.Cast(
                                    "float32",
                                    left[batch_index, row, reduction, channel],
                                )
                                * T.Cast(
                                    "float32", mask[batch_index, row, reduction]
                                ),
                            )
                        else:
                            left_shared[local_row, local_reduction] = T.Cast(
                                dtype,
                                T.Cast(
                                    "float32",
                                    left[batch_index, reduction, row, channel],
                                )
                                * T.Cast(
                                    "float32", mask[batch_index, reduction, row]
                                ),
                            )
                    else:
                        left_shared[local_row, local_reduction] = T.Cast(dtype, 0)
                for local_column, local_reduction in T.Parallel(
                    block_residues, reduction_block
                ):
                    column = column_block * block_residues + local_column
                    reduction = reduction_tile * reduction_block + local_reduction
                    if column < residues and reduction < residues:
                        if outgoing:
                            right_shared[local_column, local_reduction] = T.Cast(
                                dtype,
                                T.Cast(
                                    "float32",
                                    right[batch_index, column, reduction, channel],
                                )
                                * T.Cast(
                                    "float32", mask[batch_index, column, reduction]
                                ),
                            )
                        else:
                            right_shared[local_column, local_reduction] = T.Cast(
                                dtype,
                                T.Cast(
                                    "float32",
                                    right[batch_index, reduction, column, channel],
                                )
                                * T.Cast(
                                    "float32", mask[batch_index, reduction, column]
                                ),
                            )
                    else:
                        right_shared[local_column, local_reduction] = T.Cast(dtype, 0)
                T.gemm(
                    left_shared,
                    right_shared,
                    accumulation,
                    transpose_B=True,
                )
            for local_row, local_column in T.Parallel(
                block_residues, block_residues
            ):
                row = row_block * block_residues + local_row
                column = column_block * block_residues + local_column
                if row < residues and column < residues:
                    output[batch_index, row, column, channel] = T.Cast(
                        dtype,
                        accumulation[local_row, local_column]
                        * T.Cast("float32", mask[batch_index, row, column]),
                    )

    return mindclade_tilelang_triangle_multiplication_forward_raw.with_attr(
        {"target": target_arch, "global_symbol": "mindclade_tilelang_triangle_multiplication_forward_raw"}
    )


def build_dleft(
    *, target: str, architecture: str, batch: int, residues: int,
    channels: int, outgoing: bool, dtype: str = "float16",
    block_channels: int = 64, threads: int = 128, **_: object,
) -> Any:
    T, target_arch = _prepare(
        target=target, architecture=architecture, batch=batch, residues=residues,
        channels=channels, outgoing=outgoing, dtype=dtype,
        block_channels=block_channels, threads=threads,
    )

    tilelang = __import__("tilelang")

    @tilelang.jit(out_idx=[4], target=target_arch)
    @T.prim_func
    def mindclade_tilelang_triangle_multiplication_dleft_raw(
        grad_output: T.Tensor((batch, residues, residues, channels), dtype),
        left: T.Tensor((batch, residues, residues, channels), dtype),
        right: T.Tensor((batch, residues, residues, channels), dtype),
        mask: T.Tensor((batch, residues, residues), dtype),
        grad_left: T.Tensor((batch, residues, residues, channels), dtype),
    ):
        with T.Kernel(T.ceildiv(channels, block_channels), batch * residues * residues, threads=threads) as (channel_block, pair_index):
            batch_index = pair_index // (residues * residues)
            pair = pair_index % (residues * residues)
            row = pair // residues
            column = pair % residues
            accumulation = T.alloc_fragment((block_channels,), "float32")
            T.clear(accumulation)
            for reduction in T.serial(residues):
                for local_channel in T.Parallel(block_channels):
                    channel = channel_block * block_channels + local_channel
                    if channel < channels:
                        if outgoing:
                            accumulation[local_channel] += (
                                T.Cast("float32", grad_output[batch_index, row, reduction, channel])
                                * T.Cast("float32", mask[batch_index, row, reduction])
                                * T.Cast("float32", right[batch_index, reduction, column, channel])
                                * T.Cast("float32", mask[batch_index, reduction, column])
                            )
                        else:
                            accumulation[local_channel] += (
                                T.Cast("float32", grad_output[batch_index, column, reduction, channel])
                                * T.Cast("float32", mask[batch_index, column, reduction])
                                * T.Cast("float32", right[batch_index, row, reduction, channel])
                                * T.Cast("float32", mask[batch_index, row, reduction])
                            )
            for local_channel in T.Parallel(block_channels):
                channel = channel_block * block_channels + local_channel
                if channel < channels:
                    grad_left[batch_index, row, column, channel] = T.Cast(
                        dtype,
                        accumulation[local_channel]
                        * T.Cast("float32", mask[batch_index, row, column]),
                    )

    return mindclade_tilelang_triangle_multiplication_dleft_raw.with_attr(
        {"target": target_arch, "global_symbol": "mindclade_tilelang_triangle_multiplication_dleft_raw"}
    )


def build_dright(
    *, target: str, architecture: str, batch: int, residues: int,
    channels: int, outgoing: bool, dtype: str = "float16",
    block_channels: int = 64, threads: int = 128, **_: object,
) -> Any:
    T, target_arch = _prepare(
        target=target, architecture=architecture, batch=batch, residues=residues,
        channels=channels, outgoing=outgoing, dtype=dtype,
        block_channels=block_channels, threads=threads,
    )

    tilelang = __import__("tilelang")

    @tilelang.jit(out_idx=[4], target=target_arch)
    @T.prim_func
    def mindclade_tilelang_triangle_multiplication_dright_raw(
        grad_output: T.Tensor((batch, residues, residues, channels), dtype),
        left: T.Tensor((batch, residues, residues, channels), dtype),
        right: T.Tensor((batch, residues, residues, channels), dtype),
        mask: T.Tensor((batch, residues, residues), dtype),
        grad_right: T.Tensor((batch, residues, residues, channels), dtype),
    ):
        with T.Kernel(T.ceildiv(channels, block_channels), batch * residues * residues, threads=threads) as (channel_block, pair_index):
            batch_index = pair_index // (residues * residues)
            pair = pair_index % (residues * residues)
            row = pair // residues
            column = pair % residues
            accumulation = T.alloc_fragment((block_channels,), "float32")
            T.clear(accumulation)
            for reduction in T.serial(residues):
                for local_channel in T.Parallel(block_channels):
                    channel = channel_block * block_channels + local_channel
                    if channel < channels:
                        if outgoing:
                            accumulation[local_channel] += (
                                T.Cast("float32", grad_output[batch_index, reduction, row, channel])
                                * T.Cast("float32", mask[batch_index, reduction, row])
                                * T.Cast("float32", left[batch_index, reduction, column, channel])
                                * T.Cast("float32", mask[batch_index, reduction, column])
                            )
                        else:
                            accumulation[local_channel] += (
                                T.Cast("float32", grad_output[batch_index, reduction, column, channel])
                                * T.Cast("float32", mask[batch_index, reduction, column])
                                * T.Cast("float32", left[batch_index, row, reduction, channel])
                                * T.Cast("float32", mask[batch_index, row, reduction])
                            )
            for local_channel in T.Parallel(block_channels):
                channel = channel_block * block_channels + local_channel
                if channel < channels:
                    grad_right[batch_index, row, column, channel] = T.Cast(
                        dtype,
                        accumulation[local_channel]
                        * T.Cast("float32", mask[batch_index, row, column]),
                    )

    return mindclade_tilelang_triangle_multiplication_dright_raw.with_attr(
        {"target": target_arch, "global_symbol": "mindclade_tilelang_triangle_multiplication_dright_raw"}
    )


build_forward = build_forward_program_group
build_backward = build_backward_program_group
build_tilelang_program = build_forward_program

__all__ = (
    "build_backward_program_group",
    "build_dleft",
    "build_dright",
    "build_forward_program",
    "build_forward_program_group",
    "build_tilelang_program",
)
