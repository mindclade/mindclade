"""First-party TileLang program builders for outer-product mean.

All builders are offline-only.  The program group returns the raw FP32
normalizer explicitly and never materializes an outer-product source tensor.
"""

from __future__ import annotations

from typing import Any

_SUPPORTED_ARCHITECTURES = {"sm90a": "sm_90a", "sm100a": "sm_100a"}
_SUPPORTED_DTYPES = {"float16", "bfloat16"}
_SUPPORTED_THREADS = {64, 128, 256}


def _configuration(
    *,
    target: str,
    architecture: str,
    dtype: str,
    batch_size: int,
    source_count: int,
    node_count: int,
    left_channels: int,
    right_channels: int,
    threads: int,
) -> str:
    if target != "cuda":
        raise ValueError("outer-product mean TileLang builders require target='cuda'")
    if architecture not in _SUPPORTED_ARCHITECTURES:
        raise ValueError("architecture must be one of sm90a or sm100a")
    if dtype not in _SUPPORTED_DTYPES:
        raise ValueError("dtype must be float16 or bfloat16")
    if min(batch_size, source_count, node_count, left_channels, right_channels) <= 0:
        raise ValueError("all specialization dimensions must be positive")
    if threads not in _SUPPORTED_THREADS:
        raise ValueError("threads must be one of 64, 128, or 256")
    return f"cuda -arch={_SUPPORTED_ARCHITECTURES[architecture]}"


def _tilelang() -> tuple[Any, Any]:
    try:
        import tilelang
        import tilelang.language as T
    except ImportError as exc:  # pragma: no cover - exercised only in compile lane
        raise RuntimeError(
            "TileLang is required only in the hermetic offline compilation lane"
        ) from exc
    if getattr(tilelang, "__version__", None) != "0.1.13":
        raise RuntimeError(
            "TileLang 0.1.13 is required, found "
            f"{getattr(tilelang, '__version__', 'unknown')}"
        )
    return tilelang, T


def build_normalizer_program(
    *,
    target: str = "cuda",
    architecture: str = "sm90a",
    dtype: str = "float16",
    batch_size: int = 1,
    source_count: int = 64,
    node_count: int = 32,
    left_channels: int = 64,
    right_channels: int = 64,
    threads: int = 256,
) -> object:
    target_config = _configuration(
        target=target,
        architecture=architecture,
        dtype=dtype,
        batch_size=batch_size,
        source_count=source_count,
        node_count=node_count,
        left_channels=left_channels,
        right_channels=right_channels,
        threads=threads,
    )
    tilelang, T = _tilelang()
    total = batch_size * node_count * node_count
    blocks = (total + threads - 1) // threads

    @tilelang.jit(out_idx=[1], target=target_config)
    @T.prim_func
    def mindclade_tilelang_outer_product_mean_normalizer_raw(
        mask: T.Tensor((batch_size, source_count, node_count), dtype),
        output: T.Tensor((batch_size, node_count, node_count), "float32"),
    ):
        T.func_attr({"global_symbol": "mindclade_tilelang_outer_product_mean_normalizer_raw"})
        with T.Kernel(blocks, threads=threads) as block:
            accumulation = T.alloc_local((1,), "float32")
            for lane in T.Parallel(threads):
                flat = block * threads + lane
                if flat < total:
                    right_node = flat % node_count
                    left_node = (flat // node_count) % node_count
                    batch = flat // (node_count * node_count)
                    accumulation[0] = T.float32(0)
                    for source in T.serial(source_count):
                        accumulation[0] += T.Cast(
                            "float32", mask[batch, source, left_node]
                        ) * T.Cast("float32", mask[batch, source, right_node])
                    output[batch, left_node, right_node] = accumulation[0]

    return mindclade_tilelang_outer_product_mean_normalizer_raw


def build_numerator_program(
    *,
    target: str = "cuda",
    architecture: str = "sm90a",
    dtype: str = "float16",
    batch_size: int = 1,
    source_count: int = 64,
    node_count: int = 32,
    left_channels: int = 64,
    right_channels: int = 64,
    threads: int = 256,
    block_left_channels: int = 64,
    block_right_channels: int = 64,
    block_source: int = 32,
    num_stages: int = 3,
    enable_rasterization: bool = True,
) -> object:
    target_config = _configuration(
        target=target,
        architecture=architecture,
        dtype=dtype,
        batch_size=batch_size,
        source_count=source_count,
        node_count=node_count,
        left_channels=left_channels,
        right_channels=right_channels,
        threads=threads,
    )
    if block_left_channels not in {32, 64, 128}:
        raise ValueError("block_left_channels must be one of 32, 64, or 128")
    if block_right_channels not in {32, 64, 128}:
        raise ValueError("block_right_channels must be one of 32, 64, or 128")
    if block_source not in {16, 32, 64}:
        raise ValueError("block_source must be one of 16, 32, or 64")
    if num_stages not in {2, 3, 4}:
        raise ValueError("num_stages must be one of 2, 3, or 4")
    if not isinstance(enable_rasterization, bool):
        raise TypeError("enable_rasterization must be a bool")
    tilelang, T = _tilelang()

    @tilelang.jit(out_idx=[5], target=target_config)
    @T.prim_func
    def mindclade_tilelang_outer_product_mean_numerator_raw(
        left: T.Tensor((batch_size, source_count, node_count, left_channels), dtype),
        right: T.Tensor((batch_size, source_count, node_count, right_channels), dtype),
        mask: T.Tensor((batch_size, source_count, node_count), dtype),
        epsilon: T.float32,
        normalizer: T.Tensor((batch_size, node_count, node_count), "float32"),
        output: T.Tensor(
            (batch_size, node_count, node_count, left_channels, right_channels),
            dtype,
        ),
    ):
        T.func_attr({"global_symbol": "mindclade_tilelang_outer_product_mean_numerator_raw"})
        with T.Kernel(
            T.ceildiv(right_channels, block_right_channels),
            T.ceildiv(left_channels, block_left_channels),
            batch_size * node_count * node_count,
            threads=threads,
        ) as (right_channel_block, left_channel_block, node_pair):
            batch = node_pair // (node_count * node_count)
            pair = node_pair % (node_count * node_count)
            left_node = pair // node_count
            right_node = pair % node_count
            left_shared = T.alloc_shared(
                (block_left_channels, block_source), dtype
            )
            right_shared = T.alloc_shared(
                (block_right_channels, block_source), dtype
            )
            accumulation = T.alloc_fragment(
                (block_left_channels, block_right_channels), "float32"
            )
            T.use_swizzle(panel_size=10, enable=enable_rasterization)
            T.clear(accumulation)
            for source_block in T.Pipelined(
                T.ceildiv(source_count, block_source),
                num_stages=num_stages,
            ):
                for local_channel, local_source in T.Parallel(
                    block_left_channels, block_source
                ):
                    left_channel = (
                        left_channel_block * block_left_channels + local_channel
                    )
                    source = source_block * block_source + local_source
                    if left_channel < left_channels and source < source_count:
                        left_shared[local_channel, local_source] = T.Cast(
                            dtype,
                            T.Cast(
                                "float32",
                                left[batch, source, left_node, left_channel],
                            )
                            * T.Cast(
                                "float32", mask[batch, source, left_node]
                            ),
                        )
                    else:
                        left_shared[local_channel, local_source] = T.Cast(dtype, 0)
                for local_channel, local_source in T.Parallel(
                    block_right_channels, block_source
                ):
                    right_channel = (
                        right_channel_block * block_right_channels + local_channel
                    )
                    source = source_block * block_source + local_source
                    if right_channel < right_channels and source < source_count:
                        right_shared[local_channel, local_source] = T.Cast(
                            dtype,
                            T.Cast(
                                "float32",
                                right[batch, source, right_node, right_channel],
                            )
                            * T.Cast(
                                "float32", mask[batch, source, right_node]
                            ),
                        )
                    else:
                        right_shared[local_channel, local_source] = T.Cast(dtype, 0)
                T.gemm(
                    left_shared,
                    right_shared,
                    accumulation,
                    transpose_B=True,
                )
            denominator = T.max(
                normalizer[batch, left_node, right_node], epsilon
            )
            for local_left, local_right in T.Parallel(
                block_left_channels, block_right_channels
            ):
                left_channel = (
                    left_channel_block * block_left_channels + local_left
                )
                right_channel = (
                    right_channel_block * block_right_channels + local_right
                )
                if left_channel < left_channels and right_channel < right_channels:
                    output[
                        batch,
                        left_node,
                        right_node,
                        left_channel,
                        right_channel,
                    ] = T.Cast(
                        dtype,
                        accumulation[local_left, local_right] / denominator,
                    )

    return mindclade_tilelang_outer_product_mean_numerator_raw


def build_dleft_program(
    *,
    target: str = "cuda",
    architecture: str = "sm90a",
    dtype: str = "float16",
    batch_size: int = 1,
    source_count: int = 64,
    node_count: int = 32,
    left_channels: int = 64,
    right_channels: int = 64,
    threads: int = 256,
) -> object:
    target_config = _configuration(**locals())
    tilelang, T = _tilelang()
    total = batch_size * source_count * node_count * left_channels
    blocks = (total + threads - 1) // threads

    @tilelang.jit(out_idx=[5], target=target_config)
    @T.prim_func
    def mindclade_tilelang_outer_product_mean_dleft_raw(
        grad_output: T.Tensor((batch_size, node_count, node_count, left_channels, right_channels), dtype),
        right: T.Tensor((batch_size, source_count, node_count, right_channels), dtype),
        mask: T.Tensor((batch_size, source_count, node_count), dtype),
        epsilon: T.float32,
        normalizer: T.Tensor((batch_size, node_count, node_count), "float32"),
        grad_left: T.Tensor((batch_size, source_count, node_count, left_channels), dtype),
    ):
        T.func_attr({"global_symbol": "mindclade_tilelang_outer_product_mean_dleft_raw"})
        with T.Kernel(blocks, threads=threads) as block:
            accumulation = T.alloc_local((1,), "float32")
            for lane in T.Parallel(threads):
                flat = block * threads + lane
                if flat < total:
                    channel = flat % left_channels
                    node = (flat // left_channels) % node_count
                    source = (flat // (left_channels * node_count)) % source_count
                    batch = flat // (left_channels * node_count * source_count)
                    accumulation[0] = T.float32(0)
                    for right_node in T.serial(node_count):
                        denominator = T.max(normalizer[batch, node, right_node], epsilon)
                        for right_channel in T.serial(right_channels):
                            accumulation[0] += (
                                T.Cast("float32", grad_output[batch, node, right_node, channel, right_channel])
                                * T.Cast("float32", right[batch, source, right_node, right_channel])
                                * T.Cast("float32", mask[batch, source, node])
                                * T.Cast("float32", mask[batch, source, right_node])
                                / denominator
                            )
                    grad_left[batch, source, node, channel] = T.Cast(dtype, accumulation[0])

    return mindclade_tilelang_outer_product_mean_dleft_raw


def build_dright_program(
    *,
    target: str = "cuda",
    architecture: str = "sm90a",
    dtype: str = "float16",
    batch_size: int = 1,
    source_count: int = 64,
    node_count: int = 32,
    left_channels: int = 64,
    right_channels: int = 64,
    threads: int = 256,
) -> object:
    target_config = _configuration(**locals())
    tilelang, T = _tilelang()
    total = batch_size * source_count * node_count * right_channels
    blocks = (total + threads - 1) // threads

    @tilelang.jit(out_idx=[5], target=target_config)
    @T.prim_func
    def mindclade_tilelang_outer_product_mean_dright_raw(
        grad_output: T.Tensor((batch_size, node_count, node_count, left_channels, right_channels), dtype),
        left: T.Tensor((batch_size, source_count, node_count, left_channels), dtype),
        mask: T.Tensor((batch_size, source_count, node_count), dtype),
        epsilon: T.float32,
        normalizer: T.Tensor((batch_size, node_count, node_count), "float32"),
        grad_right: T.Tensor((batch_size, source_count, node_count, right_channels), dtype),
    ):
        T.func_attr({"global_symbol": "mindclade_tilelang_outer_product_mean_dright_raw"})
        with T.Kernel(blocks, threads=threads) as block:
            accumulation = T.alloc_local((1,), "float32")
            for lane in T.Parallel(threads):
                flat = block * threads + lane
                if flat < total:
                    channel = flat % right_channels
                    node = (flat // right_channels) % node_count
                    source = (flat // (right_channels * node_count)) % source_count
                    batch = flat // (right_channels * node_count * source_count)
                    accumulation[0] = T.float32(0)
                    for left_node in T.serial(node_count):
                        denominator = T.max(normalizer[batch, left_node, node], epsilon)
                        for left_channel in T.serial(left_channels):
                            accumulation[0] += (
                                T.Cast("float32", grad_output[batch, left_node, node, left_channel, channel])
                                * T.Cast("float32", left[batch, source, left_node, left_channel])
                                * T.Cast("float32", mask[batch, source, left_node])
                                * T.Cast("float32", mask[batch, source, node])
                                / denominator
                            )
                    grad_right[batch, source, node, channel] = T.Cast(dtype, accumulation[0])

    return mindclade_tilelang_outer_product_mean_dright_raw


def build_dmask_program(
    *,
    target: str = "cuda",
    architecture: str = "sm90a",
    dtype: str = "float16",
    batch_size: int = 1,
    source_count: int = 64,
    node_count: int = 32,
    left_channels: int = 64,
    right_channels: int = 64,
    threads: int = 256,
) -> object:
    target_config = _configuration(**locals())
    tilelang, T = _tilelang()
    total = batch_size * source_count * node_count
    blocks = (total + threads - 1) // threads

    @tilelang.jit(out_idx=[7], target=target_config)
    @T.prim_func
    def mindclade_tilelang_outer_product_mean_dmask_raw(
        grad_output: T.Tensor((batch_size, node_count, node_count, left_channels, right_channels), dtype),
        left: T.Tensor((batch_size, source_count, node_count, left_channels), dtype),
        right: T.Tensor((batch_size, source_count, node_count, right_channels), dtype),
        mask: T.Tensor((batch_size, source_count, node_count), dtype),
        epsilon: T.float32,
        output: T.Tensor((batch_size, node_count, node_count, left_channels, right_channels), dtype),
        normalizer: T.Tensor((batch_size, node_count, node_count), "float32"),
        grad_mask: T.Tensor((batch_size, source_count, node_count), dtype),
    ):
        T.func_attr({"global_symbol": "mindclade_tilelang_outer_product_mean_dmask_raw"})
        with T.Kernel(blocks, threads=threads) as block:
            accumulation = T.alloc_local((1,), "float32")
            for lane in T.Parallel(threads):
                flat = block * threads + lane
                if flat < total:
                    node = flat % node_count
                    source = (flat // node_count) % source_count
                    batch = flat // (node_count * source_count)
                    accumulation[0] = T.float32(0)
                    for other in T.serial(node_count):
                        left_denominator = T.max(normalizer[batch, node, other], epsilon)
                        right_denominator = T.max(normalizer[batch, other, node], epsilon)
                        for left_channel in T.serial(left_channels):
                            for right_channel in T.serial(right_channels):
                                left_go = T.Cast("float32", grad_output[batch, node, other, left_channel, right_channel])
                                right_go = T.Cast("float32", grad_output[batch, other, node, left_channel, right_channel])
                                accumulation[0] += (
                                    left_go
                                    * T.Cast("float32", left[batch, source, node, left_channel])
                                    * T.Cast("float32", right[batch, source, other, right_channel])
                                    * T.Cast("float32", mask[batch, source, other])
                                    / left_denominator
                                )
                                accumulation[0] += (
                                    right_go
                                    * T.Cast("float32", left[batch, source, other, left_channel])
                                    * T.Cast("float32", right[batch, source, node, right_channel])
                                    * T.Cast("float32", mask[batch, source, other])
                                    / right_denominator
                                )
                                if normalizer[batch, node, other] >= epsilon:
                                    accumulation[0] -= (
                                        left_go
                                        * T.Cast("float32", output[batch, node, other, left_channel, right_channel])
                                        * T.Cast("float32", mask[batch, source, other])
                                        / left_denominator
                                    )
                                if normalizer[batch, other, node] >= epsilon:
                                    accumulation[0] -= (
                                        right_go
                                        * T.Cast("float32", output[batch, other, node, left_channel, right_channel])
                                        * T.Cast("float32", mask[batch, source, other])
                                        / right_denominator
                                    )
                    grad_mask[batch, source, node] = T.Cast(dtype, accumulation[0])

    return mindclade_tilelang_outer_product_mean_dmask_raw


def build_forward_program_group(**_: object) -> dict[str, object]:
    """Describe deterministic normalizer -> numerator orchestration."""

    return {
        "phase": "forward",
        "logical_symbol": "mindclade_tilelang_outer_product_mean_fwd_launch",
        "execution_order": ("normalizer", "numerator"),
        "workspaces": (),
        "version": 1,
    }


def build_backward_program_group(**_: object) -> dict[str, object]:
    """Describe independent named-gradient orchestration."""

    return {
        "phase": "backward",
        "logical_symbol": "mindclade_tilelang_outer_product_mean_bwd_launch",
        "execution_order": ("dleft", "dmask", "dright"),
        "workspaces": (),
        "version": 1,
    }


build_tilelang_program = build_numerator_program
