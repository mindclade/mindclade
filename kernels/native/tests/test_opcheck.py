# Copyright (c) 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

from pathlib import Path
import json

import pytest

from kernels.native.python import loader


ROOT = Path(__file__).resolve().parents[1]

EXPECTED_DECLARED_TILELANG_OPERATORS = (
    (
        "outer_product_mean",
        "tilelang",
        "pairformer/outer_product_mean/tilelang.py",
    ),
    (
        "pair_weighted_average",
        "tilelang",
        "pairformer/pair_weighted_average/tilelang.py",
    ),
    (
        "triangle_attention",
        "tilelang",
        "pairformer/triangle_attention/tilelang.py",
    ),
    (
        "triangle_multiplication",
        "tilelang",
        "pairformer/triangle_multiplication/tilelang.py",
    ),
)


def _operator() -> loader._ManifestOperator:
    return loader._ManifestOperator(
        name="example_op",
        qualified_name="mindclade::example_op",
        schema="example_op(Tensor input) -> Tensor",
        version=1,
        devices=("cuda",),
        autograd_mode="not_supported",
    )


def test_declared_unqualified_inventory_makes_no_opcheck_claim():
    manifest = json.loads(
        (ROOT / "generated" / "native_ops.json").read_text(encoding="utf-8")
    )
    operators = manifest["operators"]
    assert tuple(
        (operator["name"], operator["backend"], operator["source"])
        for operator in operators
    ) == EXPECTED_DECLARED_TILELANG_OPERATORS
    assert all("qualification" not in operator for operator in operators)
    assert all("opcheck" not in operator for operator in operators)


def test_exact_dispatcher_schema_is_required(monkeypatch):
    operator = _operator()
    monkeypatch.setattr(
        loader,
        "_dispatcher_schema",
        lambda _name: (
            "mindclade::example_op("
            "Tensor input, bool changed) -> Tensor"
        ),
    )
    with pytest.raises(
        loader.NativeOperatorRegistrationError,
        match="schema mismatch",
    ):
        loader._reconcile_dispatcher(
            (operator,), frozenset({operator.qualified_name})
        )


def test_default_overload_is_the_only_allowed(monkeypatch):
    operator = _operator()
    monkeypatch.setattr(
        loader,
        "_dispatcher_schema",
        lambda _name: loader._expected_schema(operator),
    )
    monkeypatch.setattr(
        loader,
        "_public_operator_overloads",
        lambda _name: ("default", "extra"),
    )
    with pytest.raises(
        loader.NativeOperatorRegistrationError,
        match="undeclared overloads",
    ):
        loader._reconcile_dispatcher(
            (operator,), frozenset({operator.qualified_name})
        )


def test_declared_cuda_dispatch_is_required(monkeypatch):
    operator = _operator()
    monkeypatch.setattr(
        loader,
        "_dispatcher_schema",
        lambda _name: loader._expected_schema(operator),
    )
    monkeypatch.setattr(
        loader,
        "_public_operator_overloads",
        lambda _name: ("default",),
    )
    monkeypatch.setattr(
        loader,
        "_dispatcher_has_kernel",
        lambda _name, key: key == "Meta",
    )
    with pytest.raises(
        loader.NativeOperatorRegistrationError, match="CUDA"
    ):
        loader._reconcile_dispatcher(
            (operator,), frozenset({operator.qualified_name})
        )
