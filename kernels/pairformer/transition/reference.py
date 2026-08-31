# Copyright (c) 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

"""Independent PyTorch semantics and composite autograd for Pairformer transition."""

from __future__ import annotations

from typing import Any

import torch


def validate_inputs(gate: torch.Tensor, value: torch.Tensor, output_weight: torch.Tensor, output_bias: torch.Tensor, mask: torch.Tensor) -> tuple[int, int, int, int]:
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


def transition_reference(gate: torch.Tensor, value: torch.Tensor, output_weight: torch.Tensor, output_bias: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
    validate_inputs(gate, value, output_weight, output_bias, mask)
    accumulation_dtype = torch.float64 if gate.dtype == torch.float64 else torch.float32
    activated = torch.nn.functional.silu(gate.to(accumulation_dtype)) * value.to(accumulation_dtype)
    projected = torch.matmul(activated, output_weight.to(accumulation_dtype)) + output_bias.to(accumulation_dtype)
    return (projected * mask.to(accumulation_dtype).unsqueeze(-1)).to(gate.dtype)


def setup_context(ctx: Any, inputs: tuple[Any, ...], output: torch.Tensor) -> None:
    del output
    ctx.save_for_backward(*inputs)


def composite_backward(ctx: Any, grad_output: torch.Tensor) -> tuple[torch.Tensor | None, ...]:
    gate, value, output_weight, output_bias, mask = ctx.saved_tensors
    needs = tuple(bool(item) for item in ctx.needs_input_grad[:4])
    if not any(needs):
        return None, None, None, None, None
    prepared = [original.detach().requires_grad_(required) for original, required in zip((gate, value, output_weight, output_bias), needs)]
    differentiable = [candidate for candidate, required in zip(prepared, needs) if required]
    with torch.enable_grad():
        result = transition_reference(*prepared, mask)
        computed = torch.autograd.grad(
            result, tuple(differentiable), grad_output, allow_unused=True, create_graph=torch.is_grad_enabled()
        )
    iterator = iter(computed)
    aligned = tuple(next(iterator) if required else None for required in needs)
    return aligned[0], aligned[1], aligned[2], aligned[3], None
