# GENERATED FILE - DO NOT EDIT. Generator: kernels.native.codegen.generate@8.
from __future__ import annotations

import torch

_REGISTERED = False


def _mindclade_dtype(value):
    return getattr(torch, value) if isinstance(value, str) else value


def _mindclade_fake_0(left, right, mask, epsilon):
    metadata = {'left': left, 'right': right, 'mask': mask}
    scalars = {'epsilon': epsilon}
    return (torch.empty((tuple(metadata["left"].shape[:-3]) + (metadata["left"].shape[-2], metadata["right"].shape[-2], metadata["left"].shape[-1], metadata["right"].shape[-1])), dtype=_mindclade_dtype(metadata["left"].dtype), device=metadata["left"].device), torch.empty((tuple(metadata["left"].shape[:-3]) + (metadata["left"].shape[-2], metadata["right"].shape[-2])), dtype=_mindclade_dtype("float32"), device=metadata["left"].device))


def _mindclade_backward_fake_0(grad_output, left, right, mask, epsilon, output, normalizer, need_left_grad, need_right_grad, need_mask_grad):
    metadata = {'left': left, 'mask': mask, 'right': right}
    scalars = {'epsilon': epsilon}
    return ((torch.empty(tuple(metadata["left"].shape), dtype=_mindclade_dtype(metadata["left"].dtype), device=metadata["left"].device) if need_left_grad else None), (torch.empty(tuple(metadata["right"].shape), dtype=_mindclade_dtype(metadata["right"].dtype), device=metadata["right"].device) if need_right_grad else None), (torch.empty(tuple(metadata["mask"].shape), dtype=_mindclade_dtype(metadata["mask"].dtype), device=metadata["mask"].device) if need_mask_grad else None))


def _mindclade_required_setup_context_0(ctx, inputs, output):
    output_values = output
    ctx.set_materialize_grads(False)
    ctx.save_for_backward(inputs[0], inputs[1], inputs[2], output_values[0], output_values[1])
    ctx._mindclade_saved_scalars_0 = (inputs[3],)


def _mindclade_required_backward_0(ctx, *grad_outputs):
    if torch.is_grad_enabled():
        raise RuntimeError('mindclade::outer_product_mean does not support double backward')
    saved_tensor_0, saved_tensor_1, saved_tensor_2, saved_tensor_3, saved_tensor_4 = ctx.saved_tensors
    saved_scalar_0, = ctx._mindclade_saved_scalars_0
    output_gradient_output = grad_outputs[0]
    if output_gradient_output is None:
        raise RuntimeError('mindclade::outer_product_mean requires a gradient for output output')
    raw = torch.ops.mindclade._outer_product_mean_bwd(
        output_gradient_output,
        saved_tensor_0,
        saved_tensor_1,
        saved_tensor_2,
        saved_scalar_0,
        saved_tensor_3,
        saved_tensor_4,
        ctx.needs_input_grad[0],
        ctx.needs_input_grad[1],
        ctx.needs_input_grad[2],
    )
    raw_values = raw
    return (
        raw_values[0] if ctx.needs_input_grad[0] else None,
        raw_values[1] if ctx.needs_input_grad[1] else None,
        raw_values[2] if ctx.needs_input_grad[2] else None,
        None,
    )


def _mindclade_fake_1(value, weights, mask, epsilon):
    metadata = {'value': value, 'weights': weights, 'mask': mask}
    scalars = {'epsilon': epsilon}
    return (torch.empty((tuple(metadata["value"].shape[:-2]) + (metadata["value"].shape[-2], metadata["weights"].shape[-1], metadata["value"].shape[-1])), dtype=_mindclade_dtype(metadata["value"].dtype), device=metadata["value"].device), torch.empty((tuple(metadata["value"].shape[:-2]) + (metadata["value"].shape[-2], metadata["weights"].shape[-1])), dtype=_mindclade_dtype("float32"), device=metadata["value"].device))


def _mindclade_backward_fake_1(grad_output, value, weights, mask, output, lse, need_value_grad, need_weights_grad):
    metadata = {'mask': mask, 'value': value, 'weights': weights}
    scalars = {}
    return ((torch.empty(tuple(metadata["value"].shape), dtype=_mindclade_dtype(metadata["value"].dtype), device=metadata["value"].device) if need_value_grad else None), (torch.empty(tuple(metadata["weights"].shape), dtype=_mindclade_dtype(metadata["weights"].dtype), device=metadata["weights"].device) if need_weights_grad else None))


def _mindclade_required_setup_context_1(ctx, inputs, output):
    output_values = output
    ctx.set_materialize_grads(False)
    ctx.save_for_backward(inputs[0], inputs[1], inputs[2], output_values[0], output_values[1])
    ctx._mindclade_saved_scalars_1 = ()


def _mindclade_required_backward_1(ctx, *grad_outputs):
    if torch.is_grad_enabled():
        raise RuntimeError('mindclade::pair_weighted_average does not support double backward')
    saved_tensor_0, saved_tensor_1, saved_tensor_2, saved_tensor_3, saved_tensor_4 = ctx.saved_tensors
    output_gradient_output = grad_outputs[0]
    if output_gradient_output is None:
        raise RuntimeError('mindclade::pair_weighted_average requires a gradient for output output')
    raw = torch.ops.mindclade._pair_weighted_average_bwd(
        output_gradient_output,
        saved_tensor_0,
        saved_tensor_1,
        saved_tensor_2,
        saved_tensor_3,
        saved_tensor_4,
        ctx.needs_input_grad[0],
        ctx.needs_input_grad[1],
    )
    raw_values = raw
    return (
        raw_values[0] if ctx.needs_input_grad[0] else None,
        raw_values[1] if ctx.needs_input_grad[1] else None,
        None,
        None,
    )


def _mindclade_fake_2(gate, value, output_weight, output_bias, mask):
    metadata = {'gate': gate, 'value': value, 'output_weight': output_weight, 'output_bias': output_bias, 'mask': mask}
    scalars = {}
    return (torch.empty((tuple(metadata["gate"].shape[:-1]) + (metadata["output_weight"].shape[1],)), dtype=_mindclade_dtype(metadata["gate"].dtype), device=metadata["gate"].device), torch.empty((tuple(metadata["gate"].shape[:-1]) + (metadata["output_weight"].shape[1],)), dtype=_mindclade_dtype(metadata["gate"].dtype), device=metadata["gate"].device))


def _mindclade_backward_fake_2(grad_output, gate, value, output_weight, mask, pre_mask_output, need_gate_grad, need_value_grad, need_weight_grad, need_bias_grad, need_mask_grad):
    metadata = {'gate': gate, 'mask': mask, 'output_weight': output_weight, 'value': value}
    scalars = {}
    return ((torch.empty(tuple(metadata["gate"].shape), dtype=_mindclade_dtype(metadata["gate"].dtype), device=metadata["gate"].device) if need_gate_grad else None), (torch.empty(tuple(metadata["value"].shape), dtype=_mindclade_dtype(metadata["value"].dtype), device=metadata["value"].device) if need_value_grad else None), (torch.empty(tuple(metadata["output_weight"].shape), dtype=_mindclade_dtype(metadata["output_weight"].dtype), device=metadata["output_weight"].device) if need_weight_grad else None), (torch.empty((metadata["output_weight"].shape[1],), dtype=_mindclade_dtype(metadata["output_weight"].dtype), device=metadata["output_weight"].device) if need_bias_grad else None), (torch.empty(tuple(metadata["mask"].shape), dtype=_mindclade_dtype(metadata["mask"].dtype), device=metadata["mask"].device) if need_mask_grad else None))


def _mindclade_required_setup_context_2(ctx, inputs, output):
    output_values = output
    ctx.set_materialize_grads(False)
    ctx.save_for_backward(inputs[0], inputs[1], inputs[2], inputs[4], output_values[1])
    ctx._mindclade_saved_scalars_2 = ()


def _mindclade_required_backward_2(ctx, *grad_outputs):
    if torch.is_grad_enabled():
        raise RuntimeError('mindclade::transition does not support double backward')
    saved_tensor_0, saved_tensor_1, saved_tensor_2, saved_tensor_3, saved_tensor_4 = ctx.saved_tensors
    output_gradient_output = grad_outputs[0]
    if output_gradient_output is None:
        raise RuntimeError('mindclade::transition requires a gradient for output output')
    raw = torch.ops.mindclade._transition_bwd(
        output_gradient_output,
        saved_tensor_0,
        saved_tensor_1,
        saved_tensor_2,
        saved_tensor_3,
        saved_tensor_4,
        ctx.needs_input_grad[0],
        ctx.needs_input_grad[1],
        ctx.needs_input_grad[2],
        ctx.needs_input_grad[3],
        ctx.needs_input_grad[4],
    )
    raw_values = raw
    return (
        raw_values[0] if ctx.needs_input_grad[0] else None,
        raw_values[1] if ctx.needs_input_grad[1] else None,
        raw_values[2] if ctx.needs_input_grad[2] else None,
        raw_values[3] if ctx.needs_input_grad[3] else None,
        raw_values[4] if ctx.needs_input_grad[4] else None,
    )


def _mindclade_fake_3(q, k, v, bias, mask, scale):
    metadata = {'q': q, 'k': k, 'v': v, 'bias': bias, 'mask': mask}
    scalars = {'scale': scale}
    return (torch.empty(tuple(metadata["q"].shape), dtype=_mindclade_dtype(metadata["q"].dtype), device=metadata["q"].device), torch.empty((metadata["q"].shape[0], metadata["q"].shape[1], metadata["q"].shape[3], ((-(-(metadata["q"].shape[2]) // (32))) * (32))), dtype=_mindclade_dtype("float32"), device=metadata["q"].device))


def _mindclade_backward_fake_3(grad_output, q, k, v, bias, mask, scale, output, lse, need_q_grad, need_k_grad, need_v_grad, need_bias_grad):
    metadata = {'bias': bias, 'k': k, 'mask': mask, 'q': q, 'v': v}
    scalars = {'scale': scale}
    return ((torch.empty(tuple(metadata["q"].shape), dtype=_mindclade_dtype(metadata["q"].dtype), device=metadata["q"].device) if need_q_grad else None), (torch.empty(tuple(metadata["k"].shape), dtype=_mindclade_dtype(metadata["k"].dtype), device=metadata["k"].device) if need_k_grad else None), (torch.empty(tuple(metadata["v"].shape), dtype=_mindclade_dtype(metadata["v"].dtype), device=metadata["v"].device) if need_v_grad else None), (torch.empty(tuple(metadata["bias"].shape), dtype=_mindclade_dtype(metadata["bias"].dtype), device=metadata["bias"].device) if need_bias_grad else None))


def _mindclade_required_setup_context_3(ctx, inputs, output):
    output_values = output
    ctx.set_materialize_grads(False)
    ctx.save_for_backward(inputs[0], inputs[1], inputs[2], inputs[3], inputs[4], output_values[0], output_values[1])
    ctx._mindclade_saved_scalars_3 = (inputs[5],)


def _mindclade_required_backward_3(ctx, *grad_outputs):
    if torch.is_grad_enabled():
        raise RuntimeError('mindclade::triangle_attention does not support double backward')
    saved_tensor_0, saved_tensor_1, saved_tensor_2, saved_tensor_3, saved_tensor_4, saved_tensor_5, saved_tensor_6 = ctx.saved_tensors
    saved_scalar_0, = ctx._mindclade_saved_scalars_3
    output_gradient_output = grad_outputs[0]
    if output_gradient_output is None:
        raise RuntimeError('mindclade::triangle_attention requires a gradient for output output')
    raw = torch.ops.mindclade._triangle_attention_bwd(
        output_gradient_output,
        saved_tensor_0,
        saved_tensor_1,
        saved_tensor_2,
        saved_tensor_3,
        saved_tensor_4,
        saved_scalar_0,
        saved_tensor_5,
        saved_tensor_6,
        ctx.needs_input_grad[0],
        ctx.needs_input_grad[1],
        ctx.needs_input_grad[2],
        ctx.needs_input_grad[3],
    )
    raw_values = raw
    return (
        raw_values[0] if ctx.needs_input_grad[0] else None,
        raw_values[1] if ctx.needs_input_grad[1] else None,
        raw_values[2] if ctx.needs_input_grad[2] else None,
        raw_values[3] if ctx.needs_input_grad[3] else None,
        None,
        None,
    )


def _mindclade_fake_4(left, right, mask, outgoing):
    metadata = {'left': left, 'right': right, 'mask': mask}
    scalars = {'outgoing': outgoing}
    return torch.empty(tuple(metadata["left"].shape), dtype=_mindclade_dtype(metadata["left"].dtype), device=metadata["left"].device)


def _mindclade_backward_fake_4(grad_output, left, right, mask, outgoing, need_left_grad, need_right_grad):
    metadata = {'left': left, 'mask': mask, 'right': right}
    scalars = {'outgoing': outgoing}
    return ((torch.empty(tuple(metadata["left"].shape), dtype=_mindclade_dtype(metadata["left"].dtype), device=metadata["left"].device) if need_left_grad else None), (torch.empty(tuple(metadata["right"].shape), dtype=_mindclade_dtype(metadata["right"].dtype), device=metadata["right"].device) if need_right_grad else None))


def _mindclade_required_setup_context_4(ctx, inputs, output):
    output_values = (output,)
    ctx.set_materialize_grads(False)
    ctx.save_for_backward(inputs[0], inputs[1], inputs[2])
    ctx._mindclade_saved_scalars_4 = (inputs[3],)


def _mindclade_required_backward_4(ctx, *grad_outputs):
    if torch.is_grad_enabled():
        raise RuntimeError('mindclade::triangle_multiplication does not support double backward')
    saved_tensor_0, saved_tensor_1, saved_tensor_2 = ctx.saved_tensors
    saved_scalar_0, = ctx._mindclade_saved_scalars_4
    output_gradient_output = grad_outputs[0]
    if output_gradient_output is None:
        raise RuntimeError('mindclade::triangle_multiplication requires a gradient for output output')
    raw = torch.ops.mindclade._triangle_multiplication_bwd(
        output_gradient_output,
        saved_tensor_0,
        saved_tensor_1,
        saved_tensor_2,
        saved_scalar_0,
        ctx.needs_input_grad[0],
        ctx.needs_input_grad[1],
    )
    raw_values = raw
    return (
        raw_values[0] if ctx.needs_input_grad[0] else None,
        raw_values[1] if ctx.needs_input_grad[1] else None,
        None,
        None,
    )


def register_python_kernels() -> None:
    global _REGISTERED
    if _REGISTERED:
        return
    torch.library.register_fake('mindclade::outer_product_mean')(_mindclade_fake_0)
    torch.library.register_fake('mindclade::_outer_product_mean_fwd')(_mindclade_fake_0)
    torch.library.register_fake('mindclade::_outer_product_mean_bwd')(_mindclade_backward_fake_0)
    torch.library.register_autograd('mindclade::outer_product_mean', _mindclade_required_backward_0, setup_context=_mindclade_required_setup_context_0)
    torch.library.register_fake('mindclade::pair_weighted_average')(_mindclade_fake_1)
    torch.library.register_fake('mindclade::_pair_weighted_average_fwd')(_mindclade_fake_1)
    torch.library.register_fake('mindclade::_pair_weighted_average_bwd')(_mindclade_backward_fake_1)
    torch.library.register_autograd('mindclade::pair_weighted_average', _mindclade_required_backward_1, setup_context=_mindclade_required_setup_context_1)
    torch.library.register_fake('mindclade::transition')(_mindclade_fake_2)
    torch.library.register_fake('mindclade::_transition_fwd')(_mindclade_fake_2)
    torch.library.register_fake('mindclade::_transition_bwd')(_mindclade_backward_fake_2)
    torch.library.register_autograd('mindclade::transition', _mindclade_required_backward_2, setup_context=_mindclade_required_setup_context_2)
    torch.library.register_fake('mindclade::triangle_attention')(_mindclade_fake_3)
    torch.library.register_fake('mindclade::_triangle_attention_fwd')(_mindclade_fake_3)
    torch.library.register_fake('mindclade::_triangle_attention_bwd')(_mindclade_backward_fake_3)
    torch.library.register_autograd('mindclade::triangle_attention', _mindclade_required_backward_3, setup_context=_mindclade_required_setup_context_3)
    torch.library.register_fake('mindclade::triangle_multiplication')(_mindclade_fake_4)
    torch.library.register_fake('mindclade::_triangle_multiplication_fwd')(_mindclade_fake_4)
    torch.library.register_fake('mindclade::_triangle_multiplication_bwd')(_mindclade_backward_fake_4)
    torch.library.register_autograd('mindclade::triangle_multiplication', _mindclade_required_backward_4, setup_context=_mindclade_required_setup_context_4)
    _REGISTERED = True
