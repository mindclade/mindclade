import math

import pytest
import torch

from kernels.pairformer.outer_product_mean.tilelang import (
    QUALIFIED_NAME,
    backward,
    build_tilelang_program,
    fake,
    outer_product_mean_reference,
    setup_context,
)


def _manual_reference(left, right, mask, epsilon):
    batch_shape = left.shape[:-3]
    sequence_length, nodes = left.shape[-3:-1]
    padded = (1,) * (len(batch_shape) - (mask.ndim - 2)) + tuple(mask.shape)
    expanded_mask = mask.reshape(padded).expand(
        batch_shape + (sequence_length, nodes)
    )
    output = left.new_zeros(
        batch_shape
        + (nodes, nodes, left.shape[-1], right.shape[-1])
    )
    for left_node in range(nodes):
        for right_node in range(nodes):
            weights = (
                expanded_mask[..., :, left_node]
                * expanded_mask[..., :, right_node]
            )
            denominator = weights.sum(dim=-1).clamp_min(epsilon)
            values = (
                left[..., :, left_node, :, None]
                * right[..., :, right_node, None, :]
                * weights[..., :, None, None]
            )
            output[..., left_node, right_node, :, :] = (
                values.sum(dim=-3) / denominator[..., None, None]
            )
    return output


def test_reference_matches_explicit_formula_with_broadcast_mask():
    torch.manual_seed(7)
    left = torch.randn(2, 3, 4, 2, 3, dtype=torch.float64)
    right = torch.randn(2, 3, 4, 2, 2, dtype=torch.float64)
    mask = torch.rand(2, 1, 4, 2, dtype=torch.float64)
    actual = outer_product_mean_reference(left, right, mask, 1e-8)
    expected = _manual_reference(left, right, mask, 1e-8)
    assert actual.shape == (2, 3, 2, 2, 3, 2)
    torch.testing.assert_close(actual, expected, rtol=1e-12, atol=1e-12)


def test_zero_mask_is_zero_safe_and_finite():
    left = torch.randn(2, 3, 2, dtype=torch.float32)
    right = torch.randn(2, 3, 4, dtype=torch.float32)
    mask = torch.zeros(2, 3, dtype=torch.float32)
    output = outer_product_mean_reference(left, right, mask, 1e-6)
    assert output.shape == (3, 3, 2, 4)
    assert torch.count_nonzero(output) == 0
    assert torch.isfinite(output).all()


def test_reference_gradcheck():
    torch.manual_seed(11)
    left = torch.randn(2, 2, 2, dtype=torch.float64, requires_grad=True)
    right = torch.randn(2, 2, 3, dtype=torch.float64, requires_grad=True)
    mask = torch.rand(2, 2, dtype=torch.float64, requires_grad=True)
    assert torch.autograd.gradcheck(
        lambda l, r, m: outer_product_mean_reference(
            l, r, m, 1e-6, _check_values=False
        ),
        (left, right, mask),
        eps=1e-6,
        atol=1e-5,
        rtol=1e-4,
    )


def test_registered_backward_matches_reference_autograd():
    torch.manual_seed(13)
    left = torch.randn(2, 2, 2, dtype=torch.float64, requires_grad=True)
    right = torch.randn(2, 2, 3, dtype=torch.float64, requires_grad=True)
    mask = torch.rand(2, 2, dtype=torch.float64, requires_grad=True)
    output = outer_product_mean_reference(left, right, mask, 1e-6)
    grad_output = torch.randn_like(output)
    expected = torch.autograd.grad(output, (left, right, mask), grad_output)

    class Context:
        needs_input_grad = (True, True, True, False)

        def save_for_backward(self, *tensors):
            self.saved_tensors = tensors

    context = Context()
    setup_context(context, (left, right, mask, 1e-6), output)
    actual = backward(context, grad_output)
    for actual_gradient, expected_gradient in zip(actual[:3], expected):
        torch.testing.assert_close(
            actual_gradient, expected_gradient, rtol=1e-12, atol=1e-12
        )
    assert actual[3] is None


def test_fake_validates_and_returns_exact_meta_shape():
    left = torch.empty(2, 1, 4, 3, 5, device="meta")
    right = torch.empty(2, 1, 4, 3, 7, device="meta")
    mask = torch.empty(1, 1, 4, 3, device="meta")
    output = fake(left, right, mask, 1e-6)
    assert output.device.type == "meta"
    assert output.shape == (2, 1, 3, 3, 5, 7)
    assert output.dtype == left.dtype


@pytest.mark.parametrize("epsilon", [0.0, -1.0, math.inf, math.nan])
def test_invalid_epsilon_fails_closed(epsilon):
    left = torch.ones(2, 3, 2)
    right = torch.ones(2, 3, 2)
    mask = torch.ones(2, 3)
    with pytest.raises(ValueError, match="epsilon"):
        outer_product_mean_reference(left, right, mask, epsilon)


def test_invalid_shape_dtype_and_profile_fail_closed():
    left = torch.ones(2, 3, 2)
    right = torch.ones(4, 3, 2)
    mask = torch.ones(2, 3)
    with pytest.raises(RuntimeError, match="sequence"):
        fake(left, right, mask, 1e-6)
    with pytest.raises(RuntimeError, match="floating"):
        fake(left.to(torch.int64), left, mask, 1e-6)
    with pytest.raises(ValueError, match="target"):
        build_tilelang_program(
            target="cpu",
            batch_size=1,
            sequence_length=2,
            nodes=3,
            left_channels=2,
            right_channels=2,
            dtype="float32",
            threads=128,
        )


def test_declaration_metadata_uses_only_mindclade_identity():
    metadata = build_tilelang_program.__mindclade_kernel__
    assert QUALIFIED_NAME == "mindclade::outer_product_mean"
    assert metadata["namespace"] == "mindclade"
    assert metadata["name"] == "outer_product_mean"
    assert metadata["schema"] == (
        "outer_product_mean(Tensor left, Tensor right, Tensor mask, float epsilon) -> Tensor"
    )
    assert metadata["autograd"]["mode"] == "registered"
