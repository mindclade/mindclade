# Copyright (c) 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

"""AF3 Pairformer SwiGLU transition contraction.

This operation owns the fused activation and down-projection core only. The
model layer owns layer normalization, the up projection that produces ``gate``
and ``value``, residual/dropout policy, sharding, and block orchestration.

Logical contract:

    output = mask * (silu(gate) * value) @ output_weight + mask * output_bias

Inputs use explicit three-dimensional layouts so the same primitive can serve
flattened pair rows and single-representation rows without hidden transposes.
The TileLang schedule is an unqualified offline candidate until exact generated
source, numerical behavior, resource use, and performance are established on
its declared hardware/software envelope.
"""

from typing import Any

from kernels.native.tilelang.decorator import mindclade_kernel

_SUPPORTED_DTYPES = {"float16", "bfloat16", "float32"}


def _torch() -> Any:
    import torch

    return torch


def _validate(
    gate: Any,
    value: Any,
    output_weight: Any,
    output_bias: Any,
    mask: Any,
) -> tuple[int, int, int, int]:
    torch = _torch()
    tensors = (gate, value, output_weight, output_bias, mask)
    if any(not isinstance(tensor, torch.Tensor) for tensor in tensors):
        raise TypeError("transition arguments must be tensors")
    if gate.ndim != 3 or value.ndim != 3:
        raise ValueError("gate and value must have shape [batch, rows, hidden]")
    if gate.shape != value.shape:
        raise ValueError("gate and value must have identical shapes")
    if output_weight.ndim != 2:
        raise ValueError("output_weight must have shape [hidden, channels]")
    if output_bias.ndim != 1:
        raise ValueError("output_bias must have shape [channels]")
    if mask.ndim != 2 or tuple(mask.shape) != tuple(gate.shape[:2]):
        raise ValueError("mask must have shape [batch, rows]")
    batch, rows, hidden = (int(size) for size in gate.shape)
    if int(output_weight.shape[0]) != hidden:
        raise ValueError("output_weight hidden dimension does not match inputs")
    channels = int(output_weight.shape[1])
    if int(output_bias.shape[0]) != channels:
        raise ValueError("output_bias channel dimension does not match output_weight")
    if gate.dtype not in (torch.float16, torch.bfloat16, torch.float32, torch.float64):
        raise TypeError("gate/value must use FP16, BF16, FP32, or FP64")
    if value.dtype != gate.dtype or output_weight.dtype != gate.dtype or output_bias.dtype != gate.dtype:
        raise TypeError("gate, value, output_weight, and output_bias must share dtype")
    if mask.dtype not in (torch.bool, torch.float16, torch.bfloat16, torch.float32, torch.float64):
        raise TypeError("mask must be boolean or floating point")
    if any(tensor.device != gate.device for tensor in tensors[1:]):
        raise ValueError("all transition tensors must share one device")
    return batch, rows, hidden, channels


def transition_reference(
    gate: Any,
    value: Any,
    output_weight: Any,
    output_bias: Any,
    mask: Any,
) -> Any:
    """Readable semantic authority with FP32 accumulation for low precision."""

    torch = _torch()
    _validate(gate, value, output_weight, output_bias, mask)
    accumulation_dtype = torch.float64 if gate.dtype == torch.float64 else torch.float32
    gate_acc = gate.to(accumulation_dtype)
    value_acc = value.to(accumulation_dtype)
    weight_acc = output_weight.to(accumulation_dtype)
    bias_acc = output_bias.to(accumulation_dtype)
    activated = torch.nn.functional.silu(gate_acc) * value_acc
    projected = torch.matmul(activated, weight_acc) + bias_acc
    masked = projected * mask.to(accumulation_dtype).unsqueeze(-1)
    return masked.to(gate.dtype)


def fake(
    gate: Any,
    value: Any,
    output_weight: Any,
    output_bias: Any,
    mask: Any,
) -> Any:
    batch, rows, _hidden, channels = _validate(
        gate, value, output_weight, output_bias, mask
    )
    return gate.new_empty((batch, rows, channels))


def setup_context(ctx: Any, inputs: tuple[Any, ...], output: Any) -> None:
    del output
    gate, value, output_weight, output_bias, mask = inputs
    ctx.save_for_backward(gate, value, output_weight, output_bias, mask)


def backward(ctx: Any, grad_output: Any) -> tuple[Any, Any, Any, Any, None]:
    torch = _torch()
    gate, value, output_weight, output_bias, mask = ctx.saved_tensors
    needs = tuple(bool(item) for item in ctx.needs_input_grad[:4])
    if not any(needs):
        return None, None, None, None, None

    originals = (gate, value, output_weight, output_bias)
    differentiable: list[Any] = []
    prepared: list[Any] = []
    for original, required in zip(originals, needs, strict=True):
        candidate = original.detach().requires_grad_(required)
        prepared.append(candidate)
        if required:
            differentiable.append(candidate)

    with torch.enable_grad():
        result = transition_reference(*prepared, mask)
    computed = torch.autograd.grad(
        result,
        tuple(differentiable),
        grad_output,
        allow_unused=True,
        create_graph=torch.is_grad_enabled(),
    )
    iterator = iter(computed)
    aligned = tuple(next(iterator) if required else None for required in needs)
    return aligned[0], aligned[1], aligned[2], aligned[3], None


@mindclade_kernel(
    name="transition",
    family="pairformer",
    schema=(
        "transition(Tensor gate, Tensor value, Tensor output_weight, "
        "Tensor output_bias, Tensor mask) -> Tensor"
    ),
    fake={
        "module": "kernels.pairformer.transition.tilelang",
        "symbol": "fake",
    },
    autograd={
        "mode": "registered",
        "setup_context": {
            "module": "kernels.pairformer.transition.tilelang",
            "symbol": "setup_context",
        },
        "backward": {
            "module": "kernels.pairformer.transition.tilelang",
            "symbol": "backward",
        },
    },
)
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
    from tilelang.layout import make_swizzled_layout

    accumulation_dtype = "float32"
    total_rows = batch_size * rows

    @tilelang.jit(out_idx=[5], target=target)
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
                T.annotate_layout(
                    {
                        activation_shared: make_swizzled_layout(activation_shared),
                        weight_shared: make_swizzled_layout(weight_shared),
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
