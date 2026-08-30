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


def _operator() -> loader._ManifestOperator:
    return loader._ManifestOperator(
        name="example_op",
        qualified_name="mindclade::example_op",
        schema="example_op(Tensor input) -> Tensor",
        version=1,
        devices=("cuda",),
        autograd_mode="not_supported",
    )


def test_target_public_api_contains_no_operator_aliases():
    manifest = json.loads(
        (ROOT / "generated" / "native_ops.json").read_text(encoding="utf-8")
    )
    assert manifest["operators"] == []
    aliases = (
        "outer_product_mean",
        "triangle_attention",
        "triangle_multiplication",
    )
    assert not any(name in vars(native) for name in aliases)
    assert not any(name in vars(native_python) for name in aliases)


def test_other_namespace_registration_is_rejected():
    operator = _operator()
    before = frozenset({"aten::existing"})
    after = before | {
        operator.qualified_name,
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
        {operator.qualified_name, "mindclade::rogue"}
    )
    with pytest.raises(
        loader.NativeOperatorRegistrationError, match="unexpected"
    ):
        loader._reconcile_dispatcher((operator,), snapshot)


def test_preexisting_mindclade_namespace_is_rejected():
    operator = _operator()
    before = frozenset({"mindclade::preexisting"})
    after = before | {operator.qualified_name}
    with pytest.raises(
        loader.NativeBundleStateError,
        match="before verified loading",
    ):
        loader._require_new_operator_set(
            before, after, (operator,)
        )
