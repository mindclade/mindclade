from __future__ import annotations

import pytest

torch = pytest.importorskip("torch")

import kernels.pairformer.pair_weighted_average.dispatch as dispatch_module
from kernels.api import AutogradPolicy
from kernels.pairformer.pair_weighted_average.dispatch import (
    FallbackPolicy,
    NativeOperatorUnavailable,
    pair_weighted_average,
)
from kernels.pairformer.pair_weighted_average.reference import (
    pair_weighted_average_reference,
    pair_weighted_average_with_lse,
)
from kernels.pairformer.pair_weighted_average.spec import IMPLEMENTATION_SPECS, KERNEL_SPEC
from kernels.pairformer.pair_weighted_average.tilelang import build_online_forward_program


def _inputs(*, requires_grad: bool = False):
    torch.manual_seed(11)
    value = torch.randn(1, 4, 3, dtype=torch.float64, requires_grad=requires_grad)
    weights = torch.randn(1, 4, 4, 2, dtype=torch.float64, requires_grad=requires_grad)
    mask = torch.tensor([[1.0, 0.0, 1.0, 1.0]], dtype=torch.float32)
    return value, weights, mask


def test_required_contract_has_lse_and_physical_backward_group() -> None:
    assert KERNEL_SPEC.autograd_policy is AutogradPolicy.REQUIRED
    assert KERNEL_SPEC.composite is None
    assert KERNEL_SPEC.facade_outputs == ("output",)
    assert tuple(output.name for output in KERNEL_SPEC.forward.outputs) == ("output", "lse")
    assert all(output.saved_for_backward for output in KERNEL_SPEC.forward.outputs)
    assert tuple(node.name for node in KERNEL_SPEC.forward.program_group.nodes) == ("online_forward",)
    assert {node.name for node in KERNEL_SPEC.backward.program_group.nodes} == {"delta", "dvalue", "dweights"}
    assert tuple(workspace.name for workspace in KERNEL_SPEC.backward.program_group.workspaces) == ("delta",)
    assert all(gradient.optional for gradient in KERNEL_SPEC.backward.gradients)
    assert KERNEL_SPEC.backward.supports_double_backward is False


def test_candidate_matrix_is_independent_by_architecture_and_dtype() -> None:
    assert {(spec.envelope.architectures, spec.envelope.dtypes) for spec in IMPLEMENTATION_SPECS} == {
        (("sm90a",), ("float16",)),
        (("sm90a",), ("bfloat16",)),
        (("sm100a",), ("float16",)),
        (("sm100a",), ("bfloat16",)),
    }
    assert all(spec.envelope.training_capable for spec in IMPLEMENTATION_SPECS)


def test_reference_matches_masked_softmax_and_lse() -> None:
    value, weights, mask = _inputs()
    output, lse = pair_weighted_average_with_lse(value, weights, mask)
    masked = weights.masked_fill(mask[:, None, :, None] == 0, -torch.inf)
    probabilities = torch.softmax(masked, dim=-2)
    expected = torch.einsum("...ijh,...jc->...ihc", probabilities, value)
    expected_lse = torch.logsumexp(masked, dim=-2).float()
    torch.testing.assert_close(output, expected)
    torch.testing.assert_close(lse, expected_lse)
    assert lse.dtype == torch.float32


def test_all_masked_rows_are_zero_with_negative_infinite_lse() -> None:
    value, weights, _mask = _inputs()
    mask = torch.zeros(1, 4, dtype=torch.float32)
    output, lse = pair_weighted_average_with_lse(value, weights, mask)
    assert torch.count_nonzero(output) == 0
    assert torch.isneginf(lse).all()


def test_reference_gradients_cover_value_and_weights() -> None:
    value, weights, mask = _inputs(requires_grad=True)
    loss = pair_weighted_average_reference(value, weights, mask).square().sum()
    grad_value, grad_weights = torch.autograd.grad(loss, (value, weights))
    assert torch.isfinite(grad_value).all()
    assert torch.isfinite(grad_weights).all()
    assert torch.count_nonzero(grad_weights[:, :, 1, :]) == 0


def test_fallback_is_explicit_and_lse_stays_private(monkeypatch) -> None:
    value, weights, mask = _inputs()
    monkeypatch.setattr(dispatch_module, "_native_operator", lambda: None)
    with pytest.raises(NativeOperatorUnavailable):
        pair_weighted_average(value, weights, mask)
    expected = pair_weighted_average_reference(value, weights, mask)
    actual = pair_weighted_average(value, weights, mask, fallback=FallbackPolicy.REFERENCE)
    torch.testing.assert_close(actual, expected)
    lse = torch.zeros(1, 4, 2, dtype=torch.float32)
    monkeypatch.setattr(dispatch_module, "_native_operator", lambda: lambda *_args: (expected, lse))
    assert pair_weighted_average(value, weights, mask) is expected


def test_builder_rejects_unqualified_architecture_before_tilelang_import() -> None:
    with pytest.raises(ValueError, match="sm90a or sm100a"):
        build_online_forward_program(architecture="sm80")
