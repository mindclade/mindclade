# Copyright (c) 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

"""Offline TileLang forward builder for outer-product mean."""

import importlib
from typing import Any

_TILELANG_VERSION = "0.1.13"
_SUPPORTED_TARGETS = {
    "cuda": "cuda",
    "cuda-sm80": {"kind": "cuda", "arch": "sm_80"},
    "cuda-sm86": {"kind": "cuda", "arch": "sm_86"},
    "cuda-sm89": {"kind": "cuda", "arch": "sm_89"},
    "cuda-sm90": {"kind": "cuda", "arch": "sm_90"},
}
_SUPPORTED_DTYPES = {"float16", "bfloat16", "float32"}
_SUPPORTED_THREADS = {32, 64, 128, 256}
_MAX_BATCH_SIZE = 4096
_MAX_SEQUENCE_LENGTH = 4096
_MAX_NODES = 512
_MAX_CHANNELS = 256
_MAX_OUTPUT_ELEMENTS = 2_147_483_647

class _LazyTileLangProgram:
    def __init__(self, compiler: Any, prim_func: Any, target: Any) -> None:
        self._compiler = compiler
        self._prim_func = prim_func
        self._target = target
        self._compiled: Any | None = None

    def compile(self) -> Any:
        if self._compiled is None:
            self._compiled = self._compiler(
                self._prim_func,
                out_idx=4,
                target=self._target,
                execution_backend="cython",
            )
        return self._compiled

    def get_kernel_source(self) -> str:
        compiled = self.compile()
        source = compiled.get_kernel_source()
        if not isinstance(source, str) or not source.strip():
            raise RuntimeError("TileLang returned an empty outer_product_mean kernel source")
        return source


def _bounded_positive(name: str, value: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
        raise ValueError(f"{name} must be an integer in [1, {maximum}]")
    return value


def build_tilelang_program(
    *,
    target: str,
    batch_size: int,
    sequence_length: int,
    nodes: int,
    left_channels: int,
    right_channels: int,
    dtype: str,
    threads: int,
) -> _LazyTileLangProgram:
    """Build, but do not compile, a bounded TileLang CUDA specialization."""

    if target not in _SUPPORTED_TARGETS:
        raise ValueError(f"target must be one of {sorted(_SUPPORTED_TARGETS)}")
    batch_size = _bounded_positive("batch_size", batch_size, _MAX_BATCH_SIZE)
    sequence_length = _bounded_positive(
        "sequence_length", sequence_length, _MAX_SEQUENCE_LENGTH
    )
    nodes = _bounded_positive("nodes", nodes, _MAX_NODES)
    left_channels = _bounded_positive("left_channels", left_channels, _MAX_CHANNELS)
    right_channels = _bounded_positive("right_channels", right_channels, _MAX_CHANNELS)
    if dtype not in _SUPPORTED_DTYPES:
        raise ValueError(f"dtype must be one of {sorted(_SUPPORTED_DTYPES)}")
    if threads not in _SUPPORTED_THREADS:
        raise ValueError(f"threads must be one of {sorted(_SUPPORTED_THREADS)}")

    output_elements = (
        batch_size * nodes * nodes * left_channels * right_channels
    )
    if output_elements > _MAX_OUTPUT_ELEMENTS:
        raise ValueError(
            "specialization output exceeds the bounded 32-bit element envelope"
        )

    tilelang = importlib.import_module("tilelang")
    version = str(getattr(tilelang, "__version__", "")).split("+", 1)[0]
    if version != _TILELANG_VERSION:
        raise RuntimeError(
            f"outer_product_mean requires TileLang {_TILELANG_VERSION}, found {version or 'unknown'}"
        )
    T = importlib.import_module("tilelang.language")
    tilelang_target = _SUPPORTED_TARGETS[target]
    accumulation_dtype = "float32"

    @T.prim_func
    def outer_product_mean_kernel(
        left: T.Tensor(
            (batch_size, sequence_length, nodes, left_channels), dtype
        ),
        right: T.Tensor(
            (batch_size, sequence_length, nodes, right_channels), dtype
        ),
        mask: T.Tensor((batch_size, sequence_length, nodes), dtype),
        epsilon: T.float32,
        output: T.Tensor(
            (batch_size, nodes, nodes, left_channels, right_channels), dtype
        ),
    ):
        with T.Kernel(
            T.ceildiv(output_elements, threads), threads=threads
        ) as block:
            numerator = T.alloc_fragment((threads,), accumulation_dtype)
            denominator = T.alloc_fragment((threads,), accumulation_dtype)

            for lane in T.Parallel(threads):
                numerator[lane] = 0.0
                denominator[lane] = 0.0

            for sequence_index in T.Serial(sequence_length):
                for lane in T.Parallel(threads):
                    linear_index = block * threads + lane
                    if linear_index < output_elements:
                        remaining = linear_index
                        right_channel = remaining % right_channels
                        remaining = remaining // right_channels
                        left_channel = remaining % left_channels
                        remaining = remaining // left_channels
                        right_node = remaining % nodes
                        remaining = remaining // nodes
                        left_node = remaining % nodes
                        batch_index = remaining // nodes

                        weight = T.cast(
                            mask[batch_index, sequence_index, left_node]
                            * mask[batch_index, sequence_index, right_node],
                            accumulation_dtype,
                        )
                        numerator[lane] += (
                            weight
                            * T.cast(
                                left[
                                    batch_index,
                                    sequence_index,
                                    left_node,
                                    left_channel,
                                ],
                                accumulation_dtype,
                            )
                            * T.cast(
                                right[
                                    batch_index,
                                    sequence_index,
                                    right_node,
                                    right_channel,
                                ],
                                accumulation_dtype,
                            )
                        )
                        denominator[lane] += weight

            for lane in T.Parallel(threads):
                linear_index = block * threads + lane
                if linear_index < output_elements:
                    remaining = linear_index
                    right_channel = remaining % right_channels
                    remaining = remaining // right_channels
                    left_channel = remaining % left_channels
                    remaining = remaining // left_channels
                    right_node = remaining % nodes
                    remaining = remaining // nodes
                    left_node = remaining % nodes
                    batch_index = remaining // nodes
                    output[
                        batch_index,
                        left_node,
                        right_node,
                        left_channel,
                        right_channel,
                    ] = numerator[lane] / T.max(denominator[lane], epsilon)

    return _LazyTileLangProgram(
        tilelang.compile,
        outer_product_mean_kernel,
        tilelang_target,
    )
