"""First-party TileLang programs for masked pair-weighted average.

The forward program performs online max/sum/value accumulation.  Backward
reconstructs one probability scalar at a time from FP32 LSE and never stores a
probability matrix.
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
    mask_dtype: str,
    batch_size: int,
    node_count: int,
    channels: int,
    heads: int,
    threads: int,
) -> str:
    if target != "cuda":
        raise ValueError("pair-weighted average TileLang builders require target='cuda'")
    if architecture not in _SUPPORTED_ARCHITECTURES:
        raise ValueError("architecture must be one of sm90a or sm100a")
    if dtype not in _SUPPORTED_DTYPES:
        raise ValueError("dtype must be float16 or bfloat16")
    if mask_dtype != "float32":
        raise ValueError("qualified native candidates require an FP32 mask")
    if not 0 < batch_size <= 65535:
        raise ValueError("batch_size must be in [1, 65535]")
    if not 0 < node_count <= 8192:
        raise ValueError("node_count must be in [1, 8192]")
    if not 0 < channels <= 4096:
        raise ValueError("channels must be in [1, 4096]")
    if not 0 < heads <= 256:
        raise ValueError("heads must be in [1, 256]")
    if threads not in _SUPPORTED_THREADS:
        raise ValueError("threads must be one of 64, 128, or 256")
    return f"cuda -arch={_SUPPORTED_ARCHITECTURES[architecture]}"


def _tilelang() -> tuple[Any, Any]:
    try:
        import tilelang
        import tilelang.language as T
    except ImportError as exc:  # pragma: no cover - compile lane only
        raise RuntimeError(
            "TileLang is required only in the hermetic offline compilation lane"
        ) from exc
    if getattr(tilelang, "__version__", None) != "0.1.13":
        raise RuntimeError(
            "TileLang 0.1.13 is required, found "
            f"{getattr(tilelang, '__version__', 'unknown')}"
        )
    return tilelang, T


def build_online_forward_program(
    *,
    target: str = "cuda",
    architecture: str = "sm90a",
    dtype: str = "float16",
    mask_dtype: str = "float32",
    batch_size: int = 1,
    node_count: int = 64,
    channels: int = 64,
    heads: int = 8,
    threads: int = 256,
) -> object:
    target_config = _configuration(**locals())
    tilelang, T = _tilelang()
    total = batch_size * node_count * heads * channels
    blocks = (total + threads - 1) // threads

    @tilelang.jit(out_idx=[4, 5], target=target_config)
    @T.prim_func
    def mindclade_tilelang_pair_weighted_average_online_forward_raw(
        value: T.Tensor((batch_size, node_count, channels), dtype),
        weights: T.Tensor((batch_size, node_count, node_count, heads), dtype),
        mask: T.Tensor((batch_size, node_count), mask_dtype),
        epsilon: T.float32,
        output: T.Tensor((batch_size, node_count, heads, channels), dtype),
        lse: T.Tensor((batch_size, node_count, heads), "float32"),
    ):
        T.func_attr({"global_symbol": "mindclade_tilelang_pair_weighted_average_online_forward_raw"})
        with T.Kernel(blocks, threads=threads) as block:
            row_max = T.alloc_local((1,), "float32")
            denominator = T.alloc_local((1,), "float32")
            accumulation = T.alloc_local((1,), "float32")
            has_source = T.alloc_local((1,), "int32")
            for lane in T.Parallel(threads):
                flat = block * threads + lane
                if flat < total:
                    channel = flat % channels
                    head = (flat // channels) % heads
                    destination = (flat // (channels * heads)) % node_count
                    batch = flat // (channels * heads * node_count)
                    row_max[0] = -T.infinity("float32")
                    denominator[0] = T.float32(0)
                    accumulation[0] = T.float32(0)
                    has_source[0] = 0
                    for source in T.serial(node_count):
                        if mask[batch, source] != T.float32(0):
                            score = T.Cast("float32", weights[batch, destination, source, head])
                            if has_source[0] == 0:
                                row_max[0] = score
                                denominator[0] = T.float32(1)
                                accumulation[0] = T.Cast("float32", value[batch, source, channel])
                                has_source[0] = 1
                            else:
                                next_max = T.max(row_max[0], score)
                                old_scale = T.exp(row_max[0] - next_max)
                                new_scale = T.exp(score - next_max)
                                denominator[0] = denominator[0] * old_scale + new_scale
                                accumulation[0] = (
                                    accumulation[0] * old_scale
                                    + new_scale * T.Cast("float32", value[batch, source, channel])
                                )
                                row_max[0] = next_max
                    if has_source[0] != 0:
                        safe_denominator = T.max(denominator[0], epsilon)
                        output[batch, destination, head, channel] = T.Cast(
                            dtype, accumulation[0] / safe_denominator
                        )
                        if channel == 0:
                            lse[batch, destination, head] = row_max[0] + T.log(safe_denominator)
                    else:
                        output[batch, destination, head, channel] = T.Cast(dtype, 0)
                        if channel == 0:
                            lse[batch, destination, head] = -T.infinity("float32")

    return mindclade_tilelang_pair_weighted_average_online_forward_raw


def build_delta_program(
    *, target: str = "cuda", architecture: str = "sm90a", dtype: str = "float16",
    mask_dtype: str = "float32", batch_size: int = 1, node_count: int = 64,
    channels: int = 64, heads: int = 8, threads: int = 256,
) -> object:
    target_config = _configuration(**locals())
    tilelang, T = _tilelang()
    total = batch_size * node_count * heads
    blocks = (total + threads - 1) // threads

    @tilelang.jit(out_idx=[2], target=target_config)
    @T.prim_func
    def mindclade_tilelang_pair_weighted_average_delta_raw(
        grad_output: T.Tensor((batch_size, node_count, heads, channels), dtype),
        output: T.Tensor((batch_size, node_count, heads, channels), dtype),
        delta: T.Tensor((batch_size, node_count, heads), "float32"),
    ):
        T.func_attr({"global_symbol": "mindclade_tilelang_pair_weighted_average_delta_raw"})
        with T.Kernel(blocks, threads=threads) as block:
            accumulation = T.alloc_local((1,), "float32")
            for lane in T.Parallel(threads):
                flat = block * threads + lane
                if flat < total:
                    head = flat % heads
                    destination = (flat // heads) % node_count
                    batch = flat // (heads * node_count)
                    accumulation[0] = T.float32(0)
                    for channel in T.serial(channels):
                        accumulation[0] += T.Cast("float32", grad_output[batch, destination, head, channel]) * T.Cast("float32", output[batch, destination, head, channel])
                    delta[batch, destination, head] = accumulation[0]

    return mindclade_tilelang_pair_weighted_average_delta_raw


def build_dvalue_program(
    *, target: str = "cuda", architecture: str = "sm90a", dtype: str = "float16",
    mask_dtype: str = "float32", batch_size: int = 1, node_count: int = 64,
    channels: int = 64, heads: int = 8, threads: int = 256,
) -> object:
    target_config = _configuration(**locals())
    tilelang, T = _tilelang()
    total = batch_size * node_count * channels
    blocks = (total + threads - 1) // threads

    @tilelang.jit(out_idx=[4], target=target_config)
    @T.prim_func
    def mindclade_tilelang_pair_weighted_average_dvalue_raw(
        grad_output: T.Tensor((batch_size, node_count, heads, channels), dtype),
        weights: T.Tensor((batch_size, node_count, node_count, heads), dtype),
        mask: T.Tensor((batch_size, node_count), mask_dtype),
        lse: T.Tensor((batch_size, node_count, heads), "float32"),
        grad_value: T.Tensor((batch_size, node_count, channels), dtype),
    ):
        T.func_attr({"global_symbol": "mindclade_tilelang_pair_weighted_average_dvalue_raw"})
        with T.Kernel(blocks, threads=threads) as block:
            accumulation = T.alloc_local((1,), "float32")
            for lane in T.Parallel(threads):
                flat = block * threads + lane
                if flat < total:
                    channel = flat % channels
                    source = (flat // channels) % node_count
                    batch = flat // (channels * node_count)
                    accumulation[0] = T.float32(0)
                    if mask[batch, source] != T.float32(0):
                        for destination in T.serial(node_count):
                            for head in T.serial(heads):
                                probability = T.exp(
                                    T.Cast("float32", weights[batch, destination, source, head])
                                    - lse[batch, destination, head]
                                )
                                accumulation[0] += probability * T.Cast(
                                    "float32", grad_output[batch, destination, head, channel]
                                )
                    grad_value[batch, source, channel] = T.Cast(dtype, accumulation[0])

    return mindclade_tilelang_pair_weighted_average_dvalue_raw


def build_dweights_program(
    *, target: str = "cuda", architecture: str = "sm90a", dtype: str = "float16",
    mask_dtype: str = "float32", batch_size: int = 1, node_count: int = 64,
    channels: int = 64, heads: int = 8, threads: int = 256,
) -> object:
    target_config = _configuration(**locals())
    tilelang, T = _tilelang()
    total = batch_size * node_count * node_count * heads
    blocks = (total + threads - 1) // threads

    @tilelang.jit(out_idx=[6], target=target_config)
    @T.prim_func
    def mindclade_tilelang_pair_weighted_average_dweights_raw(
        grad_output: T.Tensor((batch_size, node_count, heads, channels), dtype),
        value: T.Tensor((batch_size, node_count, channels), dtype),
        weights: T.Tensor((batch_size, node_count, node_count, heads), dtype),
        mask: T.Tensor((batch_size, node_count), mask_dtype),
        lse: T.Tensor((batch_size, node_count, heads), "float32"),
        delta: T.Tensor((batch_size, node_count, heads), "float32"),
        grad_weights: T.Tensor((batch_size, node_count, node_count, heads), dtype),
    ):
        T.func_attr({"global_symbol": "mindclade_tilelang_pair_weighted_average_dweights_raw"})
        with T.Kernel(blocks, threads=threads) as block:
            dot = T.alloc_local((1,), "float32")
            for lane in T.Parallel(threads):
                flat = block * threads + lane
                if flat < total:
                    head = flat % heads
                    source = (flat // heads) % node_count
                    destination = (flat // (heads * node_count)) % node_count
                    batch = flat // (heads * node_count * node_count)
                    if mask[batch, source] != T.float32(0):
                        dot[0] = T.float32(0)
                        for channel in T.serial(channels):
                            dot[0] += T.Cast("float32", grad_output[batch, destination, head, channel]) * T.Cast("float32", value[batch, source, channel])
                        probability = T.exp(
                            T.Cast("float32", weights[batch, destination, source, head])
                            - lse[batch, destination, head]
                        )
                        grad_weights[batch, destination, source, head] = T.Cast(
                            dtype, probability * (dot[0] - delta[batch, destination, head])
                        )
                    else:
                        grad_weights[batch, destination, source, head] = T.Cast(dtype, 0)

    return mindclade_tilelang_pair_weighted_average_dweights_raw


def build_forward_program_group(**_: object) -> dict[str, object]:
    """Describe the one-node online forward group."""

    return {
        "phase": "forward",
        "logical_symbol": "mindclade_tilelang_pair_weighted_average_fwd_launch",
        "execution_order": ("online_forward",),
        "workspaces": (),
        "version": 1,
    }


def build_backward_program_group(**_: object) -> dict[str, object]:
    """Describe delta, dValue, and dWeights orchestration."""

    return {
        "phase": "backward",
        "logical_symbol": "mindclade_tilelang_pair_weighted_average_bwd_launch",
        "execution_order": ("delta", "dvalue", "dweights"),
        "workspaces": ("delta",),
        "version": 1,
    }


build_tilelang_program = build_online_forward_program
