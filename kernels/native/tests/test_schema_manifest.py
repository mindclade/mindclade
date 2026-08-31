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


def _with_backward_bindings(manifest: dict) -> dict:
    manifest["operators"][0]["backward"] = {
        "type": "BackwardSpec",
        "schema": (
            "_fixture_op_bwd(Tensor grad_output, Tensor? grad_aux, Tensor x, "
            "Tensor output, bool need_x_grad) -> Tensor grad_x"
        ),
        "builder": "kernels.family_a.fixture_op.tilelang:build_backward",
        "symbol": "mindclade_tilelang_fixture_op_bwd_launch",
        "argument_bindings": [
            {
                "type": "BackwardArgumentBinding",
                "provider_argument": "grad_output",
                "source": "output_gradient",
                "source_name": "output",
                "missing": "zero",
                "version": 1,
            },
            {
                "type": "BackwardArgumentBinding",
                "provider_argument": "grad_aux",
                "source": "output_gradient",
                "source_name": "auxiliary",
                "missing": "pass_none",
                "version": 1,
            },
            {
                "type": "BackwardArgumentBinding",
                "provider_argument": "need_x_grad",
                "source": "needs_input_grad",
                "source_name": "x",
                "missing": "error",
                "version": 1,
            },
            {
                "type": "BackwardArgumentBinding",
                "provider_argument": "output",
                "source": "forward_output",
                "source_name": "output",
                "missing": "error",
                "version": 1,
            },
            {
                "type": "BackwardArgumentBinding",
                "provider_argument": "x",
                "source": "operator_argument",
                "source_name": "x",
                "missing": "error",
                "version": 1,
            },
        ],
        "gradients": [
            {
                "type": "GradientSpec",
                "input_name": "x",
                "output_name": "grad_x",
                "optional": False,
                "accumulation_dtype": None,
                "version": 1,
            }
        ],
        "supports_double_backward": False,
        "program_group": None,
        "version": 1,
    }
    return manifest


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


def test_schema_accepts_exact_named_backward_argument_bindings(tmp_path: Path):
    manifest = _with_backward_bindings(_fixture_manifest(tmp_path))
    _validator().validate(manifest)


@pytest.mark.parametrize(
    ("field", "invalid"),
    (
        ("source", "runtime_lookup"),
        ("missing", "materialize_implicitly"),
        ("type", "PositionalBackwardBinding"),
        ("version", 2),
    ),
)
def test_schema_rejects_invalid_named_backward_binding_values(
    tmp_path: Path, field: str, invalid: object
):
    manifest = _with_backward_bindings(_fixture_manifest(tmp_path))
    manifest["operators"][0]["backward"]["argument_bindings"][0][field] = invalid
    with pytest.raises(jsonschema.ValidationError):
        _validator().validate(manifest)


def test_schema_rejects_unknown_named_backward_binding_fields(tmp_path: Path):
    manifest = _with_backward_bindings(_fixture_manifest(tmp_path))
    binding = manifest["operators"][0]["backward"]["argument_bindings"][0]
    binding["runtime_expression"] = "ctx.saved_tensors[0]"
    with pytest.raises(jsonschema.ValidationError):
        _validator().validate(manifest)


def test_schema_rejects_missing_named_backward_binding_fields(tmp_path: Path):
    manifest = _with_backward_bindings(_fixture_manifest(tmp_path))
    binding = manifest["operators"][0]["backward"]["argument_bindings"][0]
    del binding["source_name"]
    with pytest.raises(jsonschema.ValidationError):
        _validator().validate(manifest)
