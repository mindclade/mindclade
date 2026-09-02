"""First-party TileLang FWD/BWD programs for Pairformer SwiGLU transition.

The operation consumes projected gate/value tensors, applies ``silu(gate) *
value``, projects to pair channels, adds bias, and multiplies by the exact
floating mask.  Programs use FP32 accumulation and fixed-order reductions.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

TILELANG_VERSION = "0.1.13"
SUPPORTED_ARCHITECTURES = ("sm90a", "sm100a")
SUPPORTED_DTYPES = ("float16", "bfloat16")

TRANSITION_PROFILES: tuple[Mapping[str, object], ...] = (
    {"name": "pair_b1_r147456_h512_c128_bf16", "batch_size": 1,
     "rows": 147456, "hidden_channels": 512, "output_channels": 128,
     "dtype": "bfloat16", "mask_dtype": "float32", "threads": 128},
    {"name": "single_b1_r768_h1536_c384_bf16", "batch_size": 1,
     "rows": 768, "hidden_channels": 1536, "output_channels": 384,
     "dtype": "bfloat16", "mask_dtype": "float32", "threads": 128},
)


def _prepare(
    *, target: str, architecture: str, dtype: str, mask_dtype: str,
    batch_size: int, rows: int, hidden_channels: int, output_channels: int,
    threads: int,
) -> tuple[Any, Any, str]:
    if target != "cuda":
        raise ValueError("transition requires target='cuda'")
    if architecture not in SUPPORTED_ARCHITECTURES:
        raise ValueError("architecture must be sm90a or sm100a")
    if dtype not in SUPPORTED_DTYPES:
        raise ValueError("production transition supports float16 and bfloat16")
    if mask_dtype not in ("float16", "bfloat16", "float32"):
        raise ValueError("unsupported floating mask dtype")
    if min(batch_size, rows, hidden_channels, output_channels, threads) <= 0:
        raise ValueError("static launch dimensions must be positive")
    try:
        import tilelang
        from tilelang import language as T
    except ImportError as exc:  # pragma: no cover - hermetic build lane only
        raise RuntimeError("TileLang 0.1.13 is required for offline compilation") from exc
    if getattr(tilelang, "__version__", None) != TILELANG_VERSION:
        raise RuntimeError(
            f"expected TileLang {TILELANG_VERSION}, got "
            f"{getattr(tilelang, '__version__', 'unknown')}"
        )
    target_architecture = {"sm90a": "sm_90a", "sm100a": "sm_100a"}[
        architecture
    ]
    target_config = f"cuda -arch={target_architecture}"
    return tilelang, T, target_config


def build_forward(**_: object) -> dict[str, object]:
    return {"phase": "forward",
            "logical_symbol": "mindclade_tilelang_transition_fwd_launch",
            "execution_order": ("transition_forward",), "workspaces": (), "version": 1}


def build_backward(**_: object) -> dict[str, object]:
    return {"phase": "backward",
            "logical_symbol": "mindclade_tilelang_transition_bwd_launch",
            "execution_order": ("grad_gate_value", "grad_weight", "grad_bias", "grad_mask"),
            "workspaces": (), "version": 1}


def build_forward_program(
    *, target: str, architecture: str, dtype: str, batch_size: int, rows: int,
    hidden_channels: int, output_channels: int, mask_dtype: str = "float32",
    threads: int = 128, **_: object,
) -> Any:
    tilelang, T, target_config = _prepare(target=target, architecture=architecture, dtype=dtype,
                       mask_dtype=mask_dtype, batch_size=batch_size, rows=rows,
                       hidden_channels=hidden_channels,
                       output_channels=output_channels, threads=threads)

    @tilelang.jit(out_idx=[5, 6], target=target_config)
    @T.prim_func
    def mindclade_tilelang_transition_forward_program_launch(
        gate: T.Tensor((batch_size, rows, hidden_channels), dtype),
        value: T.Tensor((batch_size, rows, hidden_channels), dtype),
        output_weight: T.Tensor((hidden_channels, output_channels), dtype),
        output_bias: T.Tensor((output_channels,), dtype),
        mask: T.Tensor((batch_size, rows), mask_dtype),
        output: T.Tensor((batch_size, rows, output_channels), dtype),
        pre_mask_output: T.Tensor((batch_size, rows, output_channels), dtype),
    ):
        with T.Kernel(batch_size * rows, threads=threads) as block:
            row = block % rows
            batch = block // rows
            for channel in T.Parallel(output_channels):
                acc = T.alloc_local((1,), "float32")
                acc[0] = T.Cast("float32", output_bias[channel])
                for hidden in T.serial(hidden_channels):
                    gate_value = T.Cast("float32", gate[batch, row, hidden])
                    activated = gate_value * T.sigmoid(gate_value) * T.Cast(
                        "float32", value[batch, row, hidden])
                    acc[0] += activated * T.Cast(
                        "float32", output_weight[hidden, channel])
                pre_mask_output[batch, row, channel] = T.Cast(dtype, acc[0])
                output[batch, row, channel] = T.Cast(
                    dtype, acc[0] * T.Cast("float32", mask[batch, row])
                )

    return mindclade_tilelang_transition_forward_program_launch


def build_grad_gate_value(
    *, target: str, architecture: str, dtype: str, batch_size: int, rows: int,
    hidden_channels: int, output_channels: int, mask_dtype: str = "float32",
    threads: int = 128, **_: object,
) -> Any:
    tilelang, T, target_config = _prepare(target=target, architecture=architecture, dtype=dtype,
                       mask_dtype=mask_dtype, batch_size=batch_size, rows=rows,
                       hidden_channels=hidden_channels,
                       output_channels=output_channels, threads=threads)

    @tilelang.jit(out_idx=[5, 6], target=target_config)
    @T.prim_func
    def mindclade_tilelang_transition_grad_gate_value_launch(
        grad_output: T.Tensor((batch_size, rows, output_channels), dtype),
        gate: T.Tensor((batch_size, rows, hidden_channels), dtype),
        value: T.Tensor((batch_size, rows, hidden_channels), dtype),
        output_weight: T.Tensor((hidden_channels, output_channels), dtype),
        mask: T.Tensor((batch_size, rows), mask_dtype),
        grad_gate: T.Tensor((batch_size, rows, hidden_channels), dtype),
        grad_value: T.Tensor((batch_size, rows, hidden_channels), dtype),
    ):
        with T.Kernel(batch_size * rows * hidden_channels, threads=threads) as block:
            hidden = block % hidden_channels
            row = (block // hidden_channels) % rows
            batch = block // (hidden_channels * rows)
            grad_activated = T.alloc_local((1,), "float32")
            grad_activated[0] = 0.0
            for channel in T.serial(output_channels):
                grad_activated[0] += T.Cast(
                    "float32", grad_output[batch, row, channel]
                ) * T.Cast("float32", mask[batch, row]) * T.Cast(
                    "float32", output_weight[hidden, channel]
                )
            gate_value = T.Cast("float32", gate[batch, row, hidden])
            sigmoid = T.sigmoid(gate_value)
            grad_gate[batch, row, hidden] = T.Cast(
                dtype,
                grad_activated[0] * T.Cast("float32", value[batch, row, hidden])
                * sigmoid * (1.0 + gate_value * (1.0 - sigmoid)),
            )
            grad_value[batch, row, hidden] = T.Cast(
                dtype, grad_activated[0] * gate_value * sigmoid
            )

    return mindclade_tilelang_transition_grad_gate_value_launch


def build_grad_weight(
    *, target: str, architecture: str, dtype: str, batch_size: int, rows: int,
    hidden_channels: int, output_channels: int, mask_dtype: str = "float32",
    threads: int = 128, **_: object,
) -> Any:
    tilelang, T, target_config = _prepare(target=target, architecture=architecture, dtype=dtype,
                       mask_dtype=mask_dtype, batch_size=batch_size, rows=rows,
                       hidden_channels=hidden_channels,
                       output_channels=output_channels, threads=threads)

    @tilelang.jit(out_idx=[4], target=target_config)
    @T.prim_func
    def mindclade_tilelang_transition_grad_weight_launch(
        grad_output: T.Tensor((batch_size, rows, output_channels), dtype),
        gate: T.Tensor((batch_size, rows, hidden_channels), dtype),
        value: T.Tensor((batch_size, rows, hidden_channels), dtype),
        mask: T.Tensor((batch_size, rows), mask_dtype),
        grad_weight: T.Tensor((hidden_channels, output_channels), dtype),
    ):
        with T.Kernel(output_channels * hidden_channels, threads=threads) as block:
            channel = block % output_channels
            hidden = block // output_channels
            acc = T.alloc_local((1,), "float32")
            acc[0] = 0.0
            for batch in T.serial(batch_size):
                for row in T.serial(rows):
                    gate_value = T.Cast("float32", gate[batch, row, hidden])
                    acc[0] += T.Cast("float32", grad_output[batch, row, channel]) * T.Cast(
                        "float32", mask[batch, row]) * gate_value * T.sigmoid(gate_value) * T.Cast(
                        "float32", value[batch, row, hidden])
            grad_weight[hidden, channel] = T.Cast(dtype, acc[0])

    return mindclade_tilelang_transition_grad_weight_launch


def build_grad_bias(
    *, target: str, architecture: str, dtype: str, batch_size: int, rows: int,
    hidden_channels: int, output_channels: int, mask_dtype: str = "float32",
    threads: int = 128, **_: object,
) -> Any:
    tilelang, T, target_config = _prepare(target=target, architecture=architecture, dtype=dtype,
                       mask_dtype=mask_dtype, batch_size=batch_size, rows=rows,
                       hidden_channels=hidden_channels,
                       output_channels=output_channels, threads=threads)

    @tilelang.jit(out_idx=[2], target=target_config)
    @T.prim_func
    def mindclade_tilelang_transition_grad_bias_launch(
        grad_output: T.Tensor((batch_size, rows, output_channels), dtype),
        mask: T.Tensor((batch_size, rows), mask_dtype),
        grad_bias: T.Tensor((output_channels,), dtype),
    ):
        with T.Kernel(output_channels, threads=threads) as channel:
            acc = T.alloc_local((1,), "float32")
            acc[0] = 0.0
            for batch in T.serial(batch_size):
                for row in T.serial(rows):
                    acc[0] += T.Cast("float32", grad_output[batch, row, channel]) * T.Cast(
                        "float32", mask[batch, row])
            grad_bias[channel] = T.Cast(dtype, acc[0])

    return mindclade_tilelang_transition_grad_bias_launch


def build_grad_mask(
    *, target: str, architecture: str, dtype: str, batch_size: int, rows: int,
    hidden_channels: int, output_channels: int, mask_dtype: str = "float32",
    threads: int = 128, **_: object,
) -> Any:
    tilelang, T, target_config = _prepare(target=target, architecture=architecture, dtype=dtype,
                       mask_dtype=mask_dtype, batch_size=batch_size, rows=rows,
                       hidden_channels=hidden_channels,
                       output_channels=output_channels, threads=threads)

    @tilelang.jit(out_idx=[2], target=target_config)
    @T.prim_func
    def mindclade_tilelang_transition_grad_mask_launch(
        grad_output: T.Tensor((batch_size, rows, output_channels), dtype),
        pre_mask_output: T.Tensor((batch_size, rows, output_channels), dtype),
        grad_mask: T.Tensor((batch_size, rows), mask_dtype),
    ):
        with T.Kernel(batch_size * rows, threads=threads) as block:
            row = block % rows
            batch = block // rows
            acc = T.alloc_local((1,), "float32")
            acc[0] = 0.0
            for channel in T.serial(output_channels):
                acc[0] += T.Cast("float32", grad_output[batch, row, channel]) * T.Cast(
                    "float32", pre_mask_output[batch, row, channel])
            grad_mask[batch, row] = T.Cast(mask_dtype, acc[0])

    return mindclade_tilelang_transition_grad_mask_launch


build_tilelang_program = build_forward_program
