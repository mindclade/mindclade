# GENERATED FILE - DO NOT EDIT. Generator: kernels.native.codegen.generate@6.
from __future__ import annotations

import torch

_REGISTERED = False


def _mindclade_dtype(value):
    return getattr(torch, value) if isinstance(value, str) else value


def _mindclade_fake_0(left, right, mask, epsilon):
    metadata = {'left': left, 'right': right, 'mask': mask}
    scalars = {'epsilon': epsilon}
    return torch.empty((tuple(metadata["left"].shape[:-3]) + (metadata["left"].shape[-2], metadata["left"].shape[-2], metadata["left"].shape[-1], metadata["right"].shape[-1])), dtype=_mindclade_dtype(metadata["left"].dtype), device=metadata["left"].device)


from kernels.pairformer.outer_product_mean.reference import setup_context as _mindclade_setup_context_0
from kernels.pairformer.outer_product_mean.reference import composite_backward as _mindclade_raw_backward_0

def _mindclade_backward_0(ctx, *grad_outputs):
    if torch.is_grad_enabled() and any(
        gradient is not None and gradient.requires_grad
        for gradient in grad_outputs
    ):
        raise RuntimeError('mindclade::outer_product_mean does not support double backward')
    return _mindclade_raw_backward_0(ctx, *grad_outputs)


def _mindclade_fake_1(value, weights, mask, epsilon):
    metadata = {'value': value, 'weights': weights, 'mask': mask}
    scalars = {'epsilon': epsilon}
    return torch.empty((tuple(metadata["value"].shape[:-2]) + (metadata["value"].shape[-2], metadata["weights"].shape[-1], metadata["value"].shape[-1])), dtype=_mindclade_dtype(metadata["value"].dtype), device=metadata["value"].device)


from kernels.pairformer.pair_weighted_average.reference import setup_context as _mindclade_setup_context_1
from kernels.pairformer.pair_weighted_average.reference import composite_backward as _mindclade_raw_backward_1

def _mindclade_backward_1(ctx, *grad_outputs):
    if torch.is_grad_enabled() and any(
        gradient is not None and gradient.requires_grad
        for gradient in grad_outputs
    ):
        raise RuntimeError('mindclade::pair_weighted_average does not support double backward')
    return _mindclade_raw_backward_1(ctx, *grad_outputs)


def _mindclade_fake_2(gate, value, output_weight, output_bias, mask):
    metadata = {'gate': gate, 'value': value, 'output_weight': output_weight, 'output_bias': output_bias, 'mask': mask}
    scalars = {}
    return torch.empty((metadata["gate"].shape[0], metadata["gate"].shape[1], metadata["output_weight"].shape[1]), dtype=_mindclade_dtype(metadata["gate"].dtype), device=metadata["gate"].device)


from kernels.pairformer.transition.reference import setup_context as _mindclade_setup_context_2
from kernels.pairformer.transition.reference import composite_backward as _mindclade_raw_backward_2

def _mindclade_backward_2(ctx, *grad_outputs):
    if torch.is_grad_enabled() and any(
        gradient is not None and gradient.requires_grad
        for gradient in grad_outputs
    ):
        raise RuntimeError('mindclade::transition does not support double backward')
    return _mindclade_raw_backward_2(ctx, *grad_outputs)


from kernels.pairformer.triangle_attention.reference import fake as _mindclade_fake_3
from kernels.pairformer.triangle_attention.reference import setup_context as _mindclade_setup_context_3
from kernels.pairformer.triangle_attention.reference import composite_backward as _mindclade_raw_backward_3

def _mindclade_backward_3(ctx, *grad_outputs):
    if torch.is_grad_enabled() and any(
        gradient is not None and gradient.requires_grad
        for gradient in grad_outputs
    ):
        raise RuntimeError('mindclade::triangle_attention does not support double backward')
    return _mindclade_raw_backward_3(ctx, *grad_outputs)


from kernels.pairformer.triangle_multiplication.reference import fake as _mindclade_fake_4
from kernels.pairformer.triangle_multiplication.reference import setup_context as _mindclade_setup_context_4
from kernels.pairformer.triangle_multiplication.reference import composite_backward as _mindclade_raw_backward_4

def _mindclade_backward_4(ctx, *grad_outputs):
    if torch.is_grad_enabled() and any(
        gradient is not None and gradient.requires_grad
        for gradient in grad_outputs
    ):
        raise RuntimeError('mindclade::triangle_multiplication does not support double backward')
    return _mindclade_raw_backward_4(ctx, *grad_outputs)


def register_python_kernels() -> None:
    global _REGISTERED
    if _REGISTERED:
        return
    torch.library.register_fake('mindclade::outer_product_mean')(_mindclade_fake_0)
    torch.library.register_fake('mindclade::_outer_product_mean_fwd')(_mindclade_fake_0)
    torch.library.register_autograd('mindclade::outer_product_mean', _mindclade_backward_0, setup_context=_mindclade_setup_context_0)
    torch.library.register_fake('mindclade::pair_weighted_average')(_mindclade_fake_1)
    torch.library.register_fake('mindclade::_pair_weighted_average_fwd')(_mindclade_fake_1)
    torch.library.register_autograd('mindclade::pair_weighted_average', _mindclade_backward_1, setup_context=_mindclade_setup_context_1)
    torch.library.register_fake('mindclade::transition')(_mindclade_fake_2)
    torch.library.register_fake('mindclade::_transition_fwd')(_mindclade_fake_2)
    torch.library.register_autograd('mindclade::transition', _mindclade_backward_2, setup_context=_mindclade_setup_context_2)
    torch.library.register_fake('mindclade::triangle_attention')(_mindclade_fake_3)
    torch.library.register_fake('mindclade::_triangle_attention_fwd')(_mindclade_fake_3)
    torch.library.register_autograd('mindclade::triangle_attention', _mindclade_backward_3, setup_context=_mindclade_setup_context_3)
    torch.library.register_fake('mindclade::triangle_multiplication')(_mindclade_fake_4)
    torch.library.register_fake('mindclade::_triangle_multiplication_fwd')(_mindclade_fake_4)
    torch.library.register_autograd('mindclade::triangle_multiplication', _mindclade_backward_4, setup_context=_mindclade_setup_context_4)
    _REGISTERED = True
