import importlib
import math
from typing import Any

import torch

from kernels.native.tilelang.decorator import mindclade_kernel

QUALIFIED_NAME = "mindclade::outer_product_mean"
_SCHEMA = "outer_product_mean(Tensor left, Tensor right, Tensor mask, float epsilon) -> Tensor"
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


def _check(condition: Any, message: str) -> None:
    torch._check(condition, lambda: message)


def _validate_metadata(
    left: torch.Tensor,
    right: torch.Tensor,
    mask: torch.Tensor,
    epsilon: float,
) -> tuple[tuple[int, ...], int, int, int, int]:
    if not isinstance(left, torch.Tensor):
        raise TypeError("left must be a torch.Tensor")
    if not isinstance(right, torch.Tensor):
        raise TypeError("right must be a torch.Tensor")
    if not isinstance(mask, torch.Tensor):
        raise TypeError("mask must be a torch.Tensor")
    if isinstance(epsilon, bool) or not isinstance(epsilon, (int, float)):
        raise TypeError("epsilon must be a finite positive float")
    epsilon_value = float(epsilon)
    if not math.isfinite(epsilon_value) or epsilon_value <= 0.0:
        raise ValueError("epsilon must be finite and greater than zero")

    _check(left.ndim >= 3, "left must have shape [..., S, N, C_l]")
    _check(right.ndim >= 3, "right must have shape [..., S, N, C_r]")
    _check(mask.ndim >= 2, "mask must have shape [..., S, N]")
    _check(left.dtype.is_floating_point, "left must have a floating dtype")
    _check(right.dtype.is_floating_point, "right must have a floating dtype")
    _check(mask.dtype.is_floating_point, "mask must have a floating dtype")
    _check(left.dtype == right.dtype, "left and right must have the same dtype")
    _check(left.dtype == mask.dtype, "mask must have the same dtype as left and right")
    _check(left.device == right.device, "left and right must be on the same device")
    _check(left.device == mask.device, "mask must be on the same device as left and right")

    left_batch = tuple(left.shape[:-3])
    right_batch = tuple(right.shape[:-3])
    _check(len(left_batch) == len(right_batch), "left and right batch ranks must match")
    for left_extent, right_extent in zip(left_batch, right_batch):
        _check(left_extent == right_extent, "left and right batch shapes must match exactly")

    sequence_length = left.shape[-3]
    nodes = left.shape[-2]
    left_channels = left.shape[-1]
    _check(right.shape[-3] == sequence_length, "left and right sequence dimensions must match")
    _check(right.shape[-2] == nodes, "left and right node dimensions must match")
    _check(mask.shape[-2] == sequence_length, "mask sequence dimension must match inputs")
    _check(mask.shape[-1] == nodes, "mask node dimension must match inputs")

    mask_batch = tuple(mask.shape[:-2])
    _check(len(mask_batch) <= len(left_batch), "mask has more batch dimensions than inputs")
    padded_mask_batch = (1,) * (len(left_batch) - len(mask_batch)) + mask_batch
    for mask_extent, input_extent in zip(padded_mask_batch, left_batch):
        _check(
            (mask_extent == 1) | (mask_extent == input_extent),
            "mask batch dimensions must broadcast exactly to the input batch shape",
        )

    return (
        left_batch,
        sequence_length,
        nodes,
        left_channels,
        right.shape[-1],
    )


def _expanded_mask(
    mask: torch.Tensor,
    batch_shape: tuple[int, ...],
    sequence_length: int,
    nodes: int,
) -> torch.Tensor:
    mask_batch = tuple(mask.shape[:-2])
    padded_shape = (
        (1,) * (len(batch_shape) - len(mask_batch))
        + mask_batch
        + (sequence_length, nodes)
    )
    return mask.reshape(padded_shape).expand(batch_shape + (sequence_length, nodes))


def outer_product_mean_reference(
    left: torch.Tensor,
    right: torch.Tensor,
    mask: torch.Tensor,
    epsilon: float,
    *,
    _check_values: bool = True,
) -> torch.Tensor:
    """Compute the canonical CPU/reference outer-product-mean semantics."""

    batch_shape, sequence_length, nodes, _, _ = _validate_metadata(
        left, right, mask, epsilon
    )
    if _check_values:
        if not bool(torch.isfinite(left).all()):
            raise ValueError("left must contain only finite values")
        if not bool(torch.isfinite(right).all()):
            raise ValueError("right must contain only finite values")
        if not bool(torch.isfinite(mask).all()):
            raise ValueError("mask must contain only finite values")

    accumulation_dtype = torch.float64 if left.dtype == torch.float64 else torch.float32
    mask_acc = _expanded_mask(
        mask, batch_shape, sequence_length, nodes
    ).to(dtype=accumulation_dtype)
    left_acc = left.to(dtype=accumulation_dtype)
    right_acc = right.to(dtype=accumulation_dtype)
    weighted_left = left_acc * mask_acc.unsqueeze(-1)
    weighted_right = right_acc * mask_acc.unsqueeze(-1)

    numerator = torch.einsum("...sic,...sjd->...ijcd", weighted_left, weighted_right)
    denominator = torch.einsum("...si,...sj->...ij", mask_acc, mask_acc)
    denominator = denominator.clamp_min(float(epsilon))
    output = numerator / denominator.unsqueeze(-1).unsqueeze(-1)
    result = output.to(dtype=left.dtype)

    if _check_values and not bool(torch.isfinite(result).all()):
        raise ValueError("outer_product_mean produced a non-finite result")
    return result


def fake(
    left: torch.Tensor,
    right: torch.Tensor,
    mask: torch.Tensor,
    epsilon: float,
) -> torch.Tensor:
    """Validate metadata and return the exact fake/meta output shape."""

    batch_shape, _, nodes, left_channels, right_channels = _validate_metadata(
        left, right, mask, epsilon
    )
    return left.new_empty(
        batch_shape + (nodes, nodes, left_channels, right_channels)
    )


def setup_context(ctx: Any, inputs: tuple[Any, ...], output: torch.Tensor) -> None:
    del output
    left, right, mask, epsilon = inputs
    ctx.save_for_backward(left, right, mask)
    ctx.epsilon = float(epsilon)


def backward(
    ctx: Any,
    grad_output: torch.Tensor | None,
) -> tuple[torch.Tensor | None, torch.Tensor | None, torch.Tensor | None, None]:
    """Recompute the reference expression to obtain exact registered gradients."""

    if grad_output is None:
        return None, None, None, None

    left, right, mask = ctx.saved_tensors
    needs_input_grad = tuple(getattr(ctx, "needs_input_grad", (True, True, True, False)))
    requested = [
        tensor
        for tensor, needed in zip((left, right, mask), needs_input_grad[:3])
        if needed
    ]
    if not requested:
        return None, None, None, None

    create_graph = torch.is_grad_enabled()
    with torch.enable_grad():
        recomputed = outer_product_mean_reference(
            left,
            right,
            mask,
            ctx.epsilon,
            _check_values=False,
        )
        computed = torch.autograd.grad(
            recomputed,
            requested,
            grad_output,
            allow_unused=True,
            create_graph=create_graph,
        )

    gradients: list[torch.Tensor | None] = []
    iterator = iter(computed)
    for needed in needs_input_grad[:3]:
        gradients.append(next(iterator) if needed else None)
    return gradients[0], gradients[1], gradients[2], None


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


@mindclade_kernel(
    name="outer_product_mean",
    schema="outer_product_mean(Tensor left, Tensor right, Tensor mask, float epsilon) -> Tensor",
    family="pairformer",
    fake={
        "module": "kernels.pairformer.outer_product_mean.tilelang",
        "symbol": "fake",
    },
    autograd={
        "mode": "registered",
        "setup_context": {
            "module": "kernels.pairformer.outer_product_mean.tilelang",
            "symbol": "setup_context",
        },
        "backward": {
            "module": "kernels.pairformer.outer_product_mean.tilelang",
            "symbol": "backward",
        },
    },
    namespace="mindclade",
    backend="tilelang",
    version=1,
    launch_symbol="mindclade_tilelang_outer_product_mean_launch",
    devices=("cuda",),
)
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
