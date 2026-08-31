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
        "pairformer/outer_product_mean/spec.py",
    ),
    (
        "pair_weighted_average",
        "tilelang",
        "pairformer/pair_weighted_average/spec.py",
    ),
    (
        "transition",
        "tilelang",
        "pairformer/transition/spec.py",
    ),
    (
        "triangle_attention",
        "tilelang",
        "pairformer/triangle_attention/spec.py",
    ),
    (
        "triangle_multiplication",
        "tilelang",
        "pairformer/triangle_multiplication/spec.py",
    ),
)


def test_target_manifest_declares_exact_unqualified_fake_contracts():
    manifest = json.loads(
        (ROOT / "generated" / "native_ops.json").read_text(encoding="utf-8")
    )
    operators = manifest["operators"]
    assert tuple(
        (operator["name"], operator["backend"], operator["source"])
        for operator in operators
    ) == EXPECTED_DECLARED_TILELANG_OPERATORS
    assert tuple(operator["fake"] for operator in operators) == (
        None,
        None,
        None,
        "kernels.pairformer.triangle_attention.reference:fake",
        "kernels.pairformer.triangle_multiplication.reference:fake",
    )
    assert all("qualification" not in operator for operator in operators)


def test_declared_operator_requires_meta_registration(monkeypatch):
    semantic = loader._ManifestRegistration(
        qualified_name="mindclade::example_op",
        schema="example_op(Tensor input) -> Tensor output",
        kind="semantic",
        implementation_symbol="mindclade_tilelang_example_op_fwd_launch",
    )
    forward = loader._ManifestRegistration(
        qualified_name="mindclade::_example_op_fwd",
        schema="_example_op_fwd(Tensor input) -> Tensor output",
        kind="forward",
        implementation_symbol="mindclade_tilelang_example_op_fwd_launch",
    )
    operator = loader._ManifestOperator(
        name="example_op",
        qualified_name="mindclade::example_op",
        version=1,
        devices=("cuda",),
        autograd_policy="none",
        registrations=(semantic, forward),
    )
    monkeypatch.setattr(
        loader,
        "_dispatcher_schema",
        lambda name: {
            item.qualified_name: loader._qualified_schema(item.schema)
            for item in operator.registrations
        }[name],
    )
    monkeypatch.setattr(
        loader,
        "_public_operator_overloads",
        lambda _name: ("default",),
    )
    monkeypatch.setattr(
        loader,
        "_dispatcher_has_kernel",
        lambda _name, key: key == "CUDA",
    )
    with pytest.raises(
        loader.NativeOperatorRegistrationError, match="Meta"
    ):
        loader._reconcile_dispatcher(
            (operator,), frozenset(
                item.qualified_name for item in operator.registrations
            )
        )
