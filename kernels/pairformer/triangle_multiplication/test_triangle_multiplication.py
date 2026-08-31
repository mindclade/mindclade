from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

torch = pytest.importorskip("torch")

from kernels.api import AutogradPolicy, ShapeOf
from kernels.pairformer.triangle_multiplication import dispatch as dispatch_module
from kernels.pairformer.triangle_multiplication.dispatch import (
    NativeOperatorUnavailable,
    ReferenceFallback,
    triangle_multiplication,
)
from kernels.pairformer.triangle_multiplication.reference import (
    composite_backward,
    fake,
    setup_context,
    triangle_multiplication_reference,
)
from kernels.pairformer.triangle_multiplication.spec import KERNEL_SPEC
from kernels.pairformer.triangle_multiplication.tilelang import build_tilelang_program


def _loop_reference(left, right, mask, outgoing):
    result = torch.zeros_like(left)
    n = left.shape[-2]
    for i in range(n):
        for j in range(n):
            for k in range(n):
                if outgoing:
                    result[..., i, j, :] += (
                        left[..., i, k, :] * mask[..., i, k, None]
                        * right[..., j, k, :] * mask[..., j, k, None]
                    )
                else:
                    result[..., i, j, :] += (
                        left[..., k, i, :] * mask[..., k, i, None]
                        * right[..., k, j, :] * mask[..., k, j, None]
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
        triangle_multiplication_reference(left, right, mask, outgoing),
        _loop_reference(left, right, mask, outgoing),
    )


@pytest.mark.parametrize("outgoing", [False, True])
def test_reference_gradcheck(outgoing):
    left = torch.randn((1, 2, 2, 2), dtype=torch.float64, requires_grad=True)
    right = torch.randn((1, 2, 2, 2), dtype=torch.float64, requires_grad=True)
    mask = torch.ones((1, 2, 2), dtype=torch.float64)
    assert torch.autograd.gradcheck(
        lambda lhs, rhs: triangle_multiplication_reference(lhs, rhs, mask, outgoing),
        (left, right),
    )


def test_fake_preserves_metadata_and_rejects_invalid_shapes():
    left = torch.empty((2, 3, 3, 4), device="meta")
    mask = torch.empty((2, 3, 3), device="meta")
    output = fake(left, left, mask, True)
    assert output.shape == left.shape
    assert output.dtype == left.dtype
    with pytest.raises(ValueError, match="square"):
        fake(
            torch.empty((2, 3, 4, 5)),
            torch.empty((2, 3, 4, 5)),
            torch.empty((2, 3, 4)),
            True,
        )


def test_composite_backward_covers_left_and_right():
    left = torch.randn((1, 2, 2, 2), dtype=torch.float64, requires_grad=True)
    right = torch.randn((1, 2, 2, 2), dtype=torch.float64, requires_grad=True)
    mask = torch.ones((1, 2, 2), dtype=torch.float64)
    output = triangle_multiplication_reference(left, right, mask, True)
    grad_output = torch.randn_like(output)
    expected = torch.autograd.grad(output, (left, right), grad_output)

    class Context:
        needs_input_grad = (True, True, False, False)

        def save_for_backward(self, *tensors):
            self.saved_tensors = tensors

    context = Context()
    setup_context(context, (left, right, mask, True), output)
    actual = composite_backward(context, grad_output)
    torch.testing.assert_close(actual[0], expected[0])
    torch.testing.assert_close(actual[1], expected[1])
    assert actual[2:] == (None, None)


def test_spec_is_composite_unpromoted_and_reference_digest_is_exact():
    source = Path(__file__).resolve().parent / "spec.py"
    parsed = KERNEL_SPEC
    assert parsed == KERNEL_SPEC
    assert parsed.autograd_policy is AutogradPolicy.COMPOSITE
    assert parsed.backward is None
    assert parsed.forward.symbol == "mindclade_tilelang_triangle_multiplication_fwd_launch"
    assert isinstance(parsed.forward.outputs[0].shape, ShapeOf)
    assert parsed.launch.graph_capture_safe is False
    assert parsed.effects.mutates_inputs == ()
    assert parsed.composite is not None
    assert "promotion=unpromoted" in parsed.composite.runtime_envelope
    digest = "sha256:" + hashlib.sha256(source.with_name("reference.py").read_bytes()).hexdigest()
    assert parsed.composite.source_digest == digest
    assert tuple(item.input_name for item in parsed.composite.gradients) == ("left", "right")


def test_facade_normalizes_mask_before_native_dispatch(monkeypatch):
    left = torch.randn((2, 3, 3, 4), dtype=torch.float32)
    right = torch.randn_like(left)
    mask = torch.ones((2, 3, 3), dtype=torch.bool)
    captured = {}

    def native(left_, right_, mask_, outgoing_):
        captured.update(left=left_, right=right_, mask=mask_, outgoing=outgoing_)
        return left_.clone()

    monkeypatch.setattr(dispatch_module, "_native_operator", lambda: native)
    output = triangle_multiplication(left, right, mask, True)
    assert output.shape == left.shape
    assert captured["mask"].dtype == left.dtype
    assert captured["mask"].is_contiguous()


def test_reference_fallback_requires_explicit_caller_policy(monkeypatch):
    left = torch.randn((1, 2, 2, 2))
    right = torch.randn_like(left)
    mask = torch.ones((1, 2, 2), dtype=torch.bool)
    monkeypatch.setattr(dispatch_module, "_native_operator", lambda: None)
    with pytest.raises(NativeOperatorUnavailable):
        triangle_multiplication(left, right, mask, True)
    expected = triangle_multiplication_reference(left, right, mask, True)
    actual = triangle_multiplication(
        left, right, mask, True, fallback=ReferenceFallback.REFERENCE
    )
    torch.testing.assert_close(actual, expected)


def test_builder_does_not_advertise_architecture_specific_targets():
    with pytest.raises(ValueError, match="architecture-specific promotion is not declared"):
        build_tilelang_program(
            target="cuda-sm90",
            batch=1,
            residues=32,
            channels=64,
            outgoing=True,
        )
