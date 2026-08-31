"""Offline TileLang builder and optimized mathematics for triangle multiplication."""

from __future__ import annotations

def build_tilelang_program(
    *,
    target: str,
    batch: int,
    residues: int,
    channels: int,
    outgoing: bool,
    dtype: str = "float16",
    block_channels: int = 64,
    threads: int = 128,
):
    """Build one static-shape lazy TileLang program for offline compilation."""

    if target != "cuda":
        raise ValueError("triangle_multiplication target must be exactly cuda; "
                         "architecture-specific promotion is not declared")
    if batch <= 0 or residues <= 0 or channels <= 0:
        raise ValueError("batch, residues, and channels must be positive")
    if dtype not in {"float16", "bfloat16", "float32"}:
        raise ValueError("dtype must be float16, bfloat16, or float32")
    if block_channels not in {32, 64, 128} or threads not in {64, 128, 256}:
        raise ValueError("profile is outside the bounded schedule inventory")
    if not isinstance(outgoing, bool):
        raise TypeError("outgoing must be a bool")

    import tilelang
    import tilelang.language as T

    version = str(getattr(tilelang, "__version__", "")).split("+", 1)[0]
    if version != "0.1.13":
        raise RuntimeError(f"TileLang 0.1.13 is required, found {version or 'unknown'}")

    @tilelang.jit(target="cuda", out_idx=[3])
    def triangle_multiplication_program():
        @T.prim_func
        def kernel(
            left: T.Tensor((batch, residues, residues, channels), dtype),
            right: T.Tensor((batch, residues, residues, channels), dtype),
            mask: T.Tensor((batch, residues, residues), dtype),
            output: T.Tensor((batch, residues, residues, channels), dtype),
        ):
            with T.Kernel(
                T.ceildiv(channels, block_channels),
                batch * residues * residues,
                threads=threads,
            ) as (channel_block, pair_index):
                batch_index = pair_index // (residues * residues)
                pair_offset = pair_index % (residues * residues)
                row = pair_offset // residues
                column = pair_offset % residues
                accumulator = T.alloc_fragment((block_channels,), "float32")
                T.clear(accumulator)

                for contracted in T.serial(residues):
                    for local_channel in T.Parallel(block_channels):
                        channel = channel_block * block_channels + local_channel
                        if channel < channels:
                            if outgoing:
                                accumulator[local_channel] += (
                                    left[batch_index, row, contracted, channel]
                                    * mask[batch_index, row, contracted]
                                    * right[batch_index, column, contracted, channel]
                                    * mask[batch_index, column, contracted]
                                )
                            else:
                                accumulator[local_channel] += (
                                    left[batch_index, contracted, row, channel]
                                    * mask[batch_index, contracted, row]
                                    * right[batch_index, contracted, column, channel]
                                    * mask[batch_index, contracted, column]
                                )

                for local_channel in T.Parallel(block_channels):
                    channel = channel_block * block_channels + local_channel
                    if channel < channels:
                        output[batch_index, row, column, channel] = (
                            accumulator[local_channel] * mask[batch_index, row, column]
                        )

        return kernel

    return triangle_multiplication_program
