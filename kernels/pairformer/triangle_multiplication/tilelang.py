"""Offline TileLang FWD/BWD builders for triangle multiplication."""

from __future__ import annotations

from typing import Any

_ARCHITECTURES = {"sm90a": "sm_90a", "sm100a": "sm_100a"}


def _prepare(
    *, target: str, architecture: str, batch: int, residues: int,
    channels: int, outgoing: bool, dtype: str, block_channels: int, threads: int,
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
    block_channels: int = 64, threads: int = 128, **_: object,
) -> Any:
    T, target_arch = _prepare(
        target=target, architecture=architecture, batch=batch, residues=residues,
        channels=channels, outgoing=outgoing, dtype=dtype,
        block_channels=block_channels, threads=threads,
    )

    @T.prim_func
    def mindclade_tilelang_triangle_multiplication_forward_raw(
        left: T.Tensor((batch, residues, residues, channels), dtype),
        right: T.Tensor((batch, residues, residues, channels), dtype),
        mask: T.Tensor((batch, residues, residues), dtype),
        output: T.Tensor((batch, residues, residues, channels), dtype),
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
                                T.Cast("float32", left[batch_index, row, reduction, channel])
                                * T.Cast("float32", mask[batch_index, row, reduction])
                                * T.Cast("float32", right[batch_index, column, reduction, channel])
                                * T.Cast("float32", mask[batch_index, column, reduction])
                            )
                        else:
                            accumulation[local_channel] += (
                                T.Cast("float32", left[batch_index, reduction, row, channel])
                                * T.Cast("float32", mask[batch_index, reduction, row])
                                * T.Cast("float32", right[batch_index, reduction, column, channel])
                                * T.Cast("float32", mask[batch_index, reduction, column])
                            )
            for local_channel in T.Parallel(block_channels):
                channel = channel_block * block_channels + local_channel
                if channel < channels:
                    output[batch_index, row, column, channel] = T.Cast(
                        dtype,
                        accumulation[local_channel]
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
