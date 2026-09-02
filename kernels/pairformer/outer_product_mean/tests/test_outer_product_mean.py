from __future__ import annotations

import pytest

torch = pytest.importorskip("torch")

import kernels.pairformer.outer_product_mean.dispatch as dispatch_module
from kernels.api import AutogradPolicy
from kernels.pairformer.outer_product_mean.dispatch import (
    FallbackPolicy,
    NativeOperatorUnavailable,
    outer_product_mean,
)
from kernels.pairformer.outer_product_mean.reference import (
    outer_product_mean_reference,
    outer_product_mean_with_normalizer,
)
from kernels.pairformer.outer_product_mean.spec import IMPLEMENTATION_SPECS, KERNEL_SPEC
from kernels.pairformer.outer_product_mean.tilelang import build_normalizer_program


def _inputs(*, requires_grad: bool = False):
    torch.manual_seed(7)
    left = torch.randn(1, 3, 2, 4, dtype=torch.float64, requires_grad=requires_grad)
    right = torch.randn(1, 3, 2, 5, dtype=torch.float64, requires_grad=requires_grad)
    mask = torch.rand(1, 3, 2, dtype=torch.float64, requires_grad=requires_grad)
    return left, right, mask


def test_required_contract_has_named_gradients_and_programs() -> None:
    assert KERNEL_SPEC.autograd_policy is AutogradPolicy.REQUIRED
    assert KERNEL_SPEC.composite is None
    assert KERNEL_SPEC.facade_outputs == ("output",)
    assert tuple(output.name for output in KERNEL_SPEC.forward.outputs) == (
        "output",
        "normalizer",
    )
    assert all(output.saved_for_backward for output in KERNEL_SPEC.forward.outputs)
    assert tuple(node.name for node in KERNEL_SPEC.forward.program_group.nodes) == (
        "normalizer",
        "numerator",
    )
    assert {node.name for node in KERNEL_SPEC.backward.program_group.nodes} == {
        "dleft",
        "dright",
        "dmask",
    }
    assert {gradient.input_name for gradient in KERNEL_SPEC.backward.gradients} == {
        "left",
        "right",
        "mask",
    }
    assert all(gradient.optional for gradient in KERNEL_SPEC.backward.gradients)
    assert KERNEL_SPEC.backward.supports_double_backward is False


def test_candidate_matrix_is_independent_by_architecture_and_dtype() -> None:
    assert {
        (spec.envelope.architectures, spec.envelope.dtypes)
        for spec in IMPLEMENTATION_SPECS
    } == {
        (("sm90a",), ("float16",)),
        (("sm90a",), ("bfloat16",)),
        (("sm100a",), ("float16",)),
        (("sm100a",), ("bfloat16",)),
    }
    assert all(spec.envelope.training_capable for spec in IMPLEMENTATION_SPECS)
    assert all(not spec.envelope.graph_capture_safe for spec in IMPLEMENTATION_SPECS)


def test_reference_matches_direct_formula_and_exposes_fp32_normalizer() -> None:
    left, right, mask = _inputs()
    output, normalizer = outer_product_mean_with_normalizer(left, right, mask)
    numerator = torch.einsum(
        "...sic,...sjd->...ijcd",
        left * mask.unsqueeze(-1),
        right * mask.unsqueeze(-1),
    )
    expected_normalizer = torch.einsum("...si,...sj->...ij", mask, mask)
    expected = numerator / expected_normalizer.clamp_min(1.0e-6)[..., None, None]
    torch.testing.assert_close(output, expected)
    torch.testing.assert_close(normalizer, expected_normalizer.float())
    assert normalizer.dtype == torch.float32


def test_reference_first_order_gradients_cover_every_declared_input() -> None:
    left, right, mask = _inputs(requires_grad=True)
    loss = outer_product_mean_reference(left, right, mask).square().sum()
    gradients = torch.autograd.grad(loss, (left, right, mask))
    assert all(gradient is not None for gradient in gradients)
    assert all(torch.isfinite(gradient).all() for gradient in gradients)


def test_fallback_is_explicit_and_native_saved_state_stays_private(monkeypatch) -> None:
    left, right, mask = _inputs()
    monkeypatch.setattr(dispatch_module, "_native_operator", lambda: None)
    with pytest.raises(NativeOperatorUnavailable):
        outer_product_mean(left, right, mask)
    expected = outer_product_mean_reference(left, right, mask)
    actual = outer_product_mean(
        left, right, mask, fallback=FallbackPolicy.REFERENCE
    )
    torch.testing.assert_close(actual, expected)

    normalizer = torch.ones(1, 2, 2, dtype=torch.float32)
    monkeypatch.setattr(
        dispatch_module,
        "_native_operator",
        lambda: lambda *_args: (expected, normalizer),
    )
    native = outer_product_mean(left, right, mask)
    assert native is expected


def test_builder_rejects_unqualified_architecture_before_tilelang_import() -> None:
    with pytest.raises(ValueError, match="sm90a or sm100a"):
        build_normalizer_program(architecture="sm80")
