# Copyright (c) 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

from pathlib import Path
import json

import pytest

from kernels.native.python import loader


ROOT = Path(__file__).resolve().parents[1]


def test_target_manifest_registers_no_fake_production_operations():
    manifest = json.loads(
        (ROOT / "generated" / "native_ops.json").read_text(encoding="utf-8")
    )
    assert manifest["operators"] == []


def test_declared_operator_requires_meta_registration(monkeypatch):
    operator = loader._ManifestOperator(
        name="example_op",
        qualified_name="mindclade::example_op",
        schema="example_op(Tensor input) -> Tensor",
        version=1,
        devices=("cuda",),
        autograd_mode="not_supported",
    )
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
        lambda _name, key: key == "CUDA",
    )
    with pytest.raises(
        loader.NativeOperatorRegistrationError, match="Meta"
    ):
        loader._reconcile_dispatcher(
            (operator,), frozenset({operator.qualified_name})
        )
