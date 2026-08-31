# Copyright (c) 2026 Mindclade. All rights reserved.
# Proprietary and confidential. Unauthorized use, copying, or distribution is prohibited.

import pytest

torch = pytest.importorskip("torch")

from kernels.pairformer.transition.tilelang import (
    backward,
    fake,
    setup_context,
    transition_reference,
)


def test_reference_matches_decomposed_swiglu_projection() -> None:
    generator = torch.Generator().manual_seed(17)
    gate = torch.randn(2, 5, 8, generator=generator)
    value = torch.randn(2, 5, 8, generator=generator)
    weight = torch.randn(8, 4, generator=generator)
    bias = torch.randn(4, generator=generator)
    mask = torch.tensor(
        [[True, True, False, True, False], [True, False, True, True, True]]
    )
    expected = (
        (torch.nn.functional.silu(gate.float()) * value.float())
        @ weight.float()
        + bias.float()
    ) * mask.unsqueeze(-1)
    actual = transition_reference(gate, value, weight, bias, mask)
    torch.testing.assert_close(actual, expected.to(actual.dtype))


def test_all_masked_rows_are_exact_zero() -> None:
    gate = torch.randn(1, 3, 8)
    value = torch.randn_like(gate)
    weight = torch.randn(8, 4)
    bias = torch.randn(4)
    output = transition_reference(
        gate, value, weight, bias, torch.zeros(1, 3, dtype=torch.bool)
    )
    assert torch.count_nonzero(output).item() == 0


def test_fake_shape_and_contract() -> None:
    gate = torch.empty(2, 7, 16)
    value = torch.empty_like(gate)
    weight = torch.empty(16, 6)
    bias = torch.empty(6)
    mask = torch.empty(2, 7, dtype=torch.bool)
    assert fake(gate, value, weight, bias, mask).shape == (2, 7, 6)
    with pytest.raises(ValueError, match="mask"):
        fake(gate, value, weight, bias, torch.empty(2, 8))


def test_reference_first_order_gradients() -> None:
    gate = torch.randn(1, 2, 3, dtype=torch.float64, requires_grad=True)
    value = torch.randn(1, 2, 3, dtype=torch.float64, requires_grad=True)
    weight = torch.randn(3, 2, dtype=torch.float64, requires_grad=True)
    bias = torch.randn(2, dtype=torch.float64, requires_grad=True)
    mask = torch.ones(1, 2, dtype=torch.bool)
    assert torch.autograd.gradcheck(
        lambda g, v, w, b: transition_reference(g, v, w, b, mask),
        (gate, value, weight, bias),
        eps=1e-6,
        atol=1e-5,
        rtol=1e-4,
    )


def test_autograd_callables_are_explicit() -> None:
    assert callable(setup_context)
    assert callable(backward)
