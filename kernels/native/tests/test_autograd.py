# Copyright (c) 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

from pathlib import Path
import json

import pytest

from kernels.native.python import loader


ROOT = Path(__file__).resolve().parents[1]


def _operator(mode: str) -> loader._ManifestOperator:
    return loader._ManifestOperator(
        name="example_op",
        qualified_name="mindclade::example_op",
        schema="example_op(Tensor input) -> Tensor",
        version=1,
        devices=("cuda",),
        autograd_mode=mode,
    )


def test_target_manifest_advertises_no_autograd_contracts():
    manifest = json.loads(
        (ROOT / "generated" / "native_ops.json").read_text(encoding="utf-8")
    )
    assert manifest["operators"] == []


def test_registered_autograd_dispatch_is_required(monkeypatch):
    operator = _operator("registered")
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
        lambda _name, key: key in {"CUDA", "Meta"},
    )
    with pytest.raises(
        loader.NativeOperatorRegistrationError, match="Autograd"
    ):
        loader._reconcile_dispatcher(
            (operator,), frozenset({operator.qualified_name})
        )


def test_unsupported_autograd_rejects_registration(monkeypatch):
    operator = _operator("not_supported")
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
        lambda _name, key: key in {"CUDA", "Meta", "Autograd"},
    )
    with pytest.raises(
        loader.NativeOperatorRegistrationError,
        match="undeclared Autograd",
    ):
        loader._reconcile_dispatcher(
            (operator,), frozenset({operator.qualified_name})
        )
