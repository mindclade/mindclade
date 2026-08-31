# Copyright (c) 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

from __future__ import annotations

from typing import Any

import pytest
import torch
from torch._subclasses.fake_tensor import FakeTensor, FakeTensorMode

from kernels.pairformer.pair_weighted_average import tilelang as operation


def _naive(
    value: torch.Tensor,
    weights: torch.Tensor,
    mask: torch.Tensor,
    epsilon: float,
) -> torch.Tensor:
    batch_shape = value.shape[:-2]
    residues, channels = value.shape[-2:]
    heads = weights.shape[-1]
    flat_value = value.reshape(-1, residues, channels)
    flat_weights = weights.reshape(-1, residues, residues, heads)
    flat_mask = mask.reshape(-1, residues)
    result = torch.zeros(
        (flat_value.shape[0], residues, heads, channels),
        dtype=value.dtype,
        device=value.device,
    )
    for batch in range(flat_value.shape[0]):
        valid = flat_mask[batch] != 0
        if not valid.any():
            continue
        for destination in range(residues):
            for head in range(heads):
                logits = flat_weights[batch, destination, valid, head]
                maximum = logits.max()
                numerator = torch.exp(logits - maximum)
                probabilities = numerator / numerator.sum().clamp_min(epsilon)
                result[batch, destination, head] = (
                    probabilities[:, None] * flat_value[batch, valid]
                ).sum(dim=0)
    return result.reshape(*batch_shape, residues, heads, channels)


def test_cpu_matches_stable_masked_reference() -> None:
    torch.manual_seed(7)
    value = torch.randn(2, 3, 4, 5, dtype=torch.float64)
    weights = torch.randn(2, 3, 4, 4, 2, dtype=torch.float64)
    weights[..., 0, :] += 10_000.0
    weights[..., 2, :] -= 10_000.0
    mask = torch.tensor(
        [[[1, 0, 1, 1]] * 3, [[0, 1, 1, 0]] * 3],
        dtype=torch.bool,
    )
    actual = operation._reference(value, weights, mask, 1.0e-12)
    expected = _naive(value, weights, mask, 1.0e-12)
    torch.testing.assert_close(actual, expected, rtol=1.0e-12, atol=1.0e-12)


def test_all_masked_rows_are_exact_zero() -> None:
    value = torch.randn(2, 4, 3)
    weights = torch.randn(2, 4, 4, 2)
    mask = torch.zeros(2, 4, dtype=torch.bool)
    output = operation._reference(value, weights, mask, 1.0e-8)
    assert torch.equal(output, torch.zeros_like(output))


def test_reference_gradcheck() -> None:
    torch.manual_seed(11)
    value = torch.randn(2, 3, 2, dtype=torch.float64, requires_grad=True)
    weights = torch.randn(
        2, 3, 3, 2, dtype=torch.float64, requires_grad=True
    )
    mask = torch.tensor([[1, 1, 0], [1, 0, 1]], dtype=torch.bool)
    assert torch.autograd.gradcheck(
        lambda current_value, current_weights: operation._reference(
            current_value, current_weights, mask, 1.0e-12
        ),
        (value, weights),
        eps=1.0e-6,
        atol=1.0e-5,
        rtol=1.0e-4,
    )


class _AutogradContext:
    needs_input_grad = (True, True, False, False)

    def save_for_backward(self, *tensors: torch.Tensor) -> None:
        self.saved_tensors = tensors


def test_registered_backward_matches_recomputation() -> None:
    torch.manual_seed(13)
    value = torch.randn(2, 3, 2, dtype=torch.float64, requires_grad=True)
    weights = torch.randn(
        2, 3, 3, 2, dtype=torch.float64, requires_grad=True
    )
    mask = torch.tensor([[1, 1, 0], [0, 1, 1]], dtype=torch.bool)
    output = operation._reference(value, weights, mask, 1.0e-12)
    grad_output = torch.randn_like(output)
    expected = torch.autograd.grad(
        output, (value, weights), grad_output, retain_graph=True
    )

    context: Any = _AutogradContext()
    operation.setup_context(
        context,
        (value, weights, mask, 1.0e-12),
        output,
    )
    actual = operation.backward(context, grad_output)
    torch.testing.assert_close(actual[0], expected[0])
    torch.testing.assert_close(actual[1], expected[1])
    assert actual[2:] == (None, None)


def test_fake_tensor_shape_and_validation() -> None:
    mode = FakeTensorMode()
    with mode:
        value = torch.empty(2, 4, 5)
        weights = torch.empty(2, 4, 4, 3)
        mask = torch.empty(2, 4, dtype=torch.bool)
        output = operation.fake(value, weights, mask, 1.0e-8)
        assert isinstance(output, FakeTensor)
        assert output.shape == (2, 4, 3, 5)
        assert output.dtype == value.dtype
        with pytest.raises(ValueError, match="source dimension"):
            operation.fake(value, weights, mask[:, :3], 1.0e-8)


def test_literal_registration_contract_and_bounded_profiles() -> None:
    metadata = operation.build_tilelang_program.__mindclade_kernel__
    assert metadata["name"] == "pair_weighted_average"
    assert metadata["schema"] == operation._SCHEMA
    assert metadata["namespace"] == "mindclade"
    assert metadata["autograd"] == {
        "mode": "registered",
        "setup_context": {
            "module": operation._MODULE,
            "symbol": "setup_context",
        },
        "backward": {
            "module": operation._MODULE,
            "symbol": "backward",
        },
    }
    assert operation._TILELANG_VERSION == "0.1.13"
    with pytest.raises(ValueError, match="only target='cuda'"):
        operation.build_tilelang_program(
            target="cpu",
            batch_size=1,
            num_residues=32,
            channels=64,
            heads=4,
        )
    with pytest.raises(ValueError, match="block_sources must be one of"):
        operation.build_tilelang_program(
            target="cuda",
            batch_size=1,
            num_residues=32,
            channels=64,
            heads=4,
            block_sources=7,
        )
