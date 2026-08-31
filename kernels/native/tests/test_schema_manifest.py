from pathlib import Path
import json

import jsonschema
import pytest

from kernels.native.codegen.generate import render_all

ROOT = Path(__file__).resolve().parents[1]


def _fixture_manifest(tmp_path: Path) -> dict:
    kernels_root = tmp_path / "kernels"
    native_root = kernels_root / "native"
    native_root.mkdir(parents=True)
    operation = kernels_root / "family_a" / "fixture_op"
    operation.mkdir(parents=True)
    (operation / "spec.py").write_text(
        '''from kernels.api import (
    AutogradPolicy, EffectSpec, ForwardSpec, KernelSpec, LaunchContract,
    OutputSpec, SameAsInputDType, SameAsInputDevice, ShapeOf,
)
KERNEL_SPEC: KernelSpec = KernelSpec(
    name="fixture_op", namespace="mindclade", family="family_a",
    source="family_a/fixture_op/spec.py",
    operator_schema="fixture_op(Tensor x) -> Tensor output",
    facade_outputs=("output",), fake="kernels.family_a.fixture_op.reference:fake",
    forward=ForwardSpec(
        schema="_fixture_op_fwd(Tensor x) -> Tensor output",
        builder="kernels.family_a.fixture_op.tilelang:build_tilelang_program",
        symbol="mindclade_tilelang_fixture_op_fwd_launch",
        outputs=(OutputSpec(
            name="output", shape=ShapeOf(argument="x"),
            dtype=SameAsInputDType(argument="x"), device=SameAsInputDevice(argument="x"),
            semantic_axes=("element",), visible_in_facade=True, saved_for_backward=False,
        ),),
    ), backward=None, autograd_policy=AutogradPolicy.NONE,
    effects=EffectSpec(), launch=LaunchContract(graph_capture_safe=False),
)
''', encoding="utf-8")
    return json.loads(render_all(native_root, source_files=["family_a/fixture_op/spec.py"])["native_ops.json"])


def _validator() -> jsonschema.Draft202012Validator:
    schema = json.loads((ROOT / "manifests" / "native_ops.schema.json").read_text())
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(schema)


def test_generated_manifest_validates_against_strict_v3_schema():
    manifest = json.loads((ROOT / "generated" / "native_ops.json").read_text())
    _validator().validate(manifest)


def test_schema_rejects_additional_properties_recursively(tmp_path: Path):
    validator = _validator()
    manifest = _fixture_manifest(tmp_path)
    manifest["unexpected"] = True
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(manifest)
    manifest = _fixture_manifest(tmp_path / "contract")
    manifest["operators"][0]["forward"]["outputs"][0]["shape"]["unexpected"] = True
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(manifest)


def test_schema_rejects_non_mindclade_identity_and_registration_order(tmp_path: Path):
    validator = _validator()
    manifest = _fixture_manifest(tmp_path)
    manifest["operators"][0]["namespace"] = "other"
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(manifest)
    manifest = _fixture_manifest(tmp_path / "order")
    manifest["operators"][0]["registrations"].reverse()
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(manifest)
