from __future__ import annotations

import pytest

torch = pytest.importorskip("torch")

from kernels.pairformer.triangle_multiplication.tilelang import fake, reference


def _loop_reference(left, right, mask, outgoing):
    result = torch.zeros_like(left)
    n = left.shape[-2]
    for i in range(n):
        for j in range(n):
            for k in range(n):
                if outgoing:
                    result[..., i, j, :] += (
                        left[..., i, k, :]
                        * mask[..., i, k, None]
                        * right[..., j, k, :]
                        * mask[..., j, k, None]
                    )
                else:
                    result[..., i, j, :] += (
                        left[..., k, i, :]
                        * mask[..., k, i, None]
                        * right[..., k, j, :]
                        * mask[..., k, j, None]
                    )
    return result * mask[..., None]


@pytest.mark.parametrize("outgoing", [False, True])
def test_reference_matches_direct_contraction(outgoing):
    generator = torch.Generator().manual_seed(7)
    left = torch.randn((2, 3, 3, 4), dtype=torch.float64, generator=generator)
    right = torch.randn((2, 3, 3, 4), dtype=torch.float64, generator=generator)
    mask = torch.tensor(
        [[[1, 1, 0], [1, 1, 1], [0, 1, 1]], [[1, 0, 1], [0, 1, 1], [1, 1, 1]]],
        dtype=torch.float64,
    )
    torch.testing.assert_close(
        reference(left, right, mask, outgoing),
        _loop_reference(left, right, mask, outgoing),
    )


@pytest.mark.parametrize("outgoing", [False, True])
def test_reference_gradcheck(outgoing):
    left = torch.randn((1, 2, 2, 2), dtype=torch.float64, requires_grad=True)
    right = torch.randn((1, 2, 2, 2), dtype=torch.float64, requires_grad=True)
    mask = torch.ones((1, 2, 2), dtype=torch.float64)
    assert torch.autograd.gradcheck(
        lambda lhs, rhs: reference(lhs, rhs, mask, outgoing),
        (left, right),
    )


def test_fake_preserves_metadata_and_rejects_invalid_shapes():
    left = torch.empty((2, 3, 3, 4), device="meta")
    mask = torch.empty((2, 3, 3), device="meta")
    output = fake(left, left, mask, True)
    assert output.shape == left.shape
    assert output.dtype == left.dtype
    with pytest.raises(ValueError, match="square"):
        fake(torch.empty((2, 3, 4, 5)), torch.empty((2, 3, 4, 5)), torch.empty((2, 3, 4)), True)
