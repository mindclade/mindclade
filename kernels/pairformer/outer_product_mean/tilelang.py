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
    target_config = _configuration(**locals())
    tilelang, T = _tilelang()
    total = batch_size * node_count * node_count
    blocks = (total + threads - 1) // threads

    @tilelang.jit(out_idx=[1], target=target_config)
    @T.prim_func
    def mindclade_tilelang_outer_product_mean_normalizer_launch(
        mask: T.Tensor((batch_size, source_count, node_count), dtype),
        output: T.Tensor((batch_size, node_count, node_count), "float32"),
    ):
        T.func_attr({"global_symbol": "mindclade_tilelang_outer_product_mean_normalizer_launch"})
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

    return mindclade_tilelang_outer_product_mean_normalizer_launch


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
) -> object:
    target_config = _configuration(**locals())
    tilelang, T = _tilelang()
    total = batch_size * node_count * node_count * left_channels * right_channels
    blocks = (total + threads - 1) // threads

    @tilelang.jit(out_idx=[5], target=target_config)
    @T.prim_func
    def mindclade_tilelang_outer_product_mean_numerator_launch(
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
        T.func_attr({"global_symbol": "mindclade_tilelang_outer_product_mean_numerator_launch"})
        with T.Kernel(blocks, threads=threads) as block:
            accumulation = T.alloc_local((1,), "float32")
            for lane in T.Parallel(threads):
                flat = block * threads + lane
                if flat < total:
                    right_channel = flat % right_channels
                    left_channel = (flat // right_channels) % left_channels
                    right_node = (flat // (right_channels * left_channels)) % node_count
                    left_node = (
                        flat // (right_channels * left_channels * node_count)
                    ) % node_count
                    batch = flat // (
                        right_channels * left_channels * node_count * node_count
                    )
                    accumulation[0] = T.float32(0)
                    for source in T.serial(source_count):
                        accumulation[0] += (
                            T.Cast("float32", left[batch, source, left_node, left_channel])
                            * T.Cast("float32", right[batch, source, right_node, right_channel])
                            * T.Cast("float32", mask[batch, source, left_node])
                            * T.Cast("float32", mask[batch, source, right_node])
                        )
                    denominator = T.max(normalizer[batch, left_node, right_node], epsilon)
                    output[batch, left_node, right_node, left_channel, right_channel] = T.Cast(
                        dtype, accumulation[0] / denominator
                    )

    return mindclade_tilelang_outer_product_mean_numerator_launch


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
    def mindclade_tilelang_outer_product_mean_dleft_launch(
        grad_output: T.Tensor((batch_size, node_count, node_count, left_channels, right_channels), dtype),
        right: T.Tensor((batch_size, source_count, node_count, right_channels), dtype),
        mask: T.Tensor((batch_size, source_count, node_count), dtype),
        epsilon: T.float32,
        normalizer: T.Tensor((batch_size, node_count, node_count), "float32"),
        grad_left: T.Tensor((batch_size, source_count, node_count, left_channels), dtype),
    ):
        T.func_attr({"global_symbol": "mindclade_tilelang_outer_product_mean_dleft_launch"})
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

    return mindclade_tilelang_outer_product_mean_dleft_launch


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
    def mindclade_tilelang_outer_product_mean_dright_launch(
        grad_output: T.Tensor((batch_size, node_count, node_count, left_channels, right_channels), dtype),
        left: T.Tensor((batch_size, source_count, node_count, left_channels), dtype),
        mask: T.Tensor((batch_size, source_count, node_count), dtype),
        epsilon: T.float32,
        normalizer: T.Tensor((batch_size, node_count, node_count), "float32"),
        grad_right: T.Tensor((batch_size, source_count, node_count, right_channels), dtype),
    ):
        T.func_attr({"global_symbol": "mindclade_tilelang_outer_product_mean_dright_launch"})
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

    return mindclade_tilelang_outer_product_mean_dright_launch


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
    def mindclade_tilelang_outer_product_mean_dmask_launch(
        grad_output: T.Tensor((batch_size, node_count, node_count, left_channels, right_channels), dtype),
        left: T.Tensor((batch_size, source_count, node_count, left_channels), dtype),
        right: T.Tensor((batch_size, source_count, node_count, right_channels), dtype),
        mask: T.Tensor((batch_size, source_count, node_count), dtype),
        epsilon: T.float32,
        output: T.Tensor((batch_size, node_count, node_count, left_channels, right_channels), dtype),
        normalizer: T.Tensor((batch_size, node_count, node_count), "float32"),
        grad_mask: T.Tensor((batch_size, source_count, node_count), dtype),
    ):
        T.func_attr({"global_symbol": "mindclade_tilelang_outer_product_mean_dmask_launch"})
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

    return mindclade_tilelang_outer_product_mean_dmask_launch


def build_forward_program_group(**_: object) -> dict[str, object]:
    """Describe deterministic normalizer -> numerator orchestration."""

    return {
        "phase": "forward",
        "logical_symbol": "mindclade_tilelang_outer_product_mean_fwd_launch",
        "execution_order": ("normalizer", "numerator"),
        "workspaces": ("normalizer",),
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
