# Copyright (c) 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

from pathlib import Path
import json

import pytest

import kernels.native as native
import kernels.native.python as native_python
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


def _operator() -> loader._ManifestOperator:
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
    return loader._ManifestOperator(
        name="example_op",
        qualified_name="mindclade::example_op",
        version=1,
        devices=("cuda",),
        autograd_policy="none",
        registrations=(semantic, forward),
    )


def _registration_names(operator: loader._ManifestOperator) -> frozenset[str]:
    return frozenset(item.qualified_name for item in operator.registrations)


def test_declared_unqualified_operators_have_no_public_api_aliases():
    manifest = json.loads(
        (ROOT / "generated" / "native_ops.json").read_text(encoding="utf-8")
    )
    operators = manifest["operators"]
    assert tuple(
        (operator["name"], operator["backend"], operator["source"])
        for operator in operators
    ) == EXPECTED_DECLARED_TILELANG_OPERATORS
    assert all("qualification" not in operator for operator in operators)
    aliases = tuple(
        operator_name
        for operator_name, _backend, _source in EXPECTED_DECLARED_TILELANG_OPERATORS
    )
    assert not any(name in vars(native) for name in aliases)
    assert not any(name in vars(native_python) for name in aliases)


def test_other_namespace_registration_is_rejected():
    operator = _operator()
    before = frozenset({"aten::existing"})
    after = before | {
        *_registration_names(operator),
        "other_namespace::rogue",
    }
    with pytest.raises(
        loader.NativeOperatorRegistrationError, match="unexpected"
    ):
        loader._require_new_operator_set(
            before, after, (operator,)
        )


def test_undeclared_mindclade_operator_is_rejected():
    operator = _operator()
    snapshot = frozenset(
        {*_registration_names(operator), "mindclade::rogue"}
    )
    with pytest.raises(
        loader.NativeOperatorRegistrationError, match="unexpected"
    ):
        loader._reconcile_dispatcher((operator,), snapshot)


def test_preexisting_mindclade_namespace_is_rejected():
    operator = _operator()
    before = frozenset({"mindclade::preexisting"})
    after = before | _registration_names(operator)
    with pytest.raises(
        loader.NativeBundleStateError,
        match="before verified loading",
    ):
        loader._require_new_operator_set(
            before, after, (operator,)
        )
