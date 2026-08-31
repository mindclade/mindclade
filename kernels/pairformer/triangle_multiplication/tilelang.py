"""Operation-owned triangle multiplication reference and TileLang program."""

from __future__ import annotations

from typing import TYPE_CHECKING

from kernels.native.tilelang.decorator import mindclade_kernel

if TYPE_CHECKING:
    import torch


def _validate(left: "torch.Tensor", right: "torch.Tensor", mask: "torch.Tensor") -> None:
    import torch

    if left.ndim < 3:
        raise ValueError("left must have shape [..., N, N, C]")
    if left.shape != right.shape:
        raise ValueError("left and right must have identical shapes")
    if left.shape[-3] != left.shape[-2]:
        raise ValueError("left and right residue axes must be square")
    if mask.shape != left.shape[:-1]:
        raise ValueError("mask must have shape [..., N, N]")
    if not left.dtype.is_floating_point or not right.dtype.is_floating_point:
        raise TypeError("left and right must use floating-point dtypes")
    if not mask.dtype.is_floating_point and mask.dtype != torch.bool:
        raise TypeError("mask must be boolean or floating point")
    if left.dtype != right.dtype:
        raise TypeError("left and right must have the same dtype")
    if left.device != right.device or left.device != mask.device:
        raise ValueError("left, right, and mask must be on the same device")


def reference(
    left: "torch.Tensor",
    right: "torch.Tensor",
    mask: "torch.Tensor",
    outgoing: bool,
) -> "torch.Tensor":
    """Compute masked AlphaFold-style triangle multiplication.

    ``outgoing=True`` contracts ``left[..., i, k, c]`` with
    ``right[..., j, k, c]``. Incoming mode contracts
    ``left[..., k, i, c]`` with ``right[..., k, j, c]``.
    """

    import torch

    _validate(left, right, mask)
    if not isinstance(outgoing, bool):
        raise TypeError("outgoing must be a bool")
    mask_values = mask.to(dtype=left.dtype)
    masked_left = left * mask_values.unsqueeze(-1)
    masked_right = right * mask_values.unsqueeze(-1)
    if outgoing:
        result = torch.einsum("...ikc,...jkc->...ijc", masked_left, masked_right)
    else:
        result = torch.einsum("...kic,...kjc->...ijc", masked_left, masked_right)
    return result * mask_values.unsqueeze(-1)


def fake(
    left: "torch.Tensor",
    right: "torch.Tensor",
    mask: "torch.Tensor",
    outgoing: bool,
) -> "torch.Tensor":
    _validate(left, right, mask)
    if not isinstance(outgoing, bool):
        raise TypeError("outgoing must be a bool")
    return left.new_empty(left.shape)


def setup_context(ctx: object, inputs: tuple[object, ...], output: object) -> None:
    del output
    left, right, mask, outgoing = inputs
    ctx.save_for_backward(left, right, mask)  # type: ignore[attr-defined]
    ctx.outgoing = outgoing  # type: ignore[attr-defined]


def backward(ctx: object, grad_output: "torch.Tensor") -> tuple[object, ...]:
    import torch

    left, right, mask = ctx.saved_tensors  # type: ignore[attr-defined]
    needs_input_grad = getattr(ctx, "needs_input_grad", (True, True, False, False))
    with torch.enable_grad():
        left_input = left.detach().requires_grad_(True)
        right_input = right.detach().requires_grad_(True)
        result = reference(left_input, right_input, mask, bool(ctx.outgoing))  # type: ignore[attr-defined]
        grad_left, grad_right = torch.autograd.grad(
            result,
            (left_input, right_input),
            grad_output,
            allow_unused=True,
        )
    return (
        grad_left if needs_input_grad[0] else None,
        grad_right if needs_input_grad[1] else None,
        None,
        None,
    )


@mindclade_kernel(
    name="triangle_multiplication",
    schema="triangle_multiplication(Tensor left, Tensor right, Tensor mask, bool outgoing) -> Tensor",
    family="pairformer",
    fake={
        "module": "kernels.pairformer.triangle_multiplication.tilelang",
        "symbol": "fake",
    },
    autograd={
        "mode": "registered",
        "setup_context": {
            "module": "kernels.pairformer.triangle_multiplication.tilelang",
            "symbol": "setup_context",
        },
        "backward": {
            "module": "kernels.pairformer.triangle_multiplication.tilelang",
            "symbol": "backward",
        },
    },
)
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

    if target not in {"cuda", "cuda-sm80", "cuda-sm90", "cuda-sm100"}:
        raise ValueError(f"unsupported TileLang target: {target}")
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
