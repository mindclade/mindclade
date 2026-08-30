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
    source = operation / "tilelang.py"
    source.write_text(
        '''from kernels.native.tilelang.decorator import mindclade_kernel
@mindclade_kernel(
    name="fixture_op",
    schema="fixture_op(Tensor x) -> Tensor",
    family="family_a",
    fake={"module": "kernels.family_a.fixture_op.tilelang", "symbol": "fake"},
    autograd={"mode": "not_supported"},
)
def build_tilelang_program(*, target, m):
    raise NotImplementedError
''',
        encoding="utf-8",
    )
    return json.loads(render_all(native_root, source_files=[source])["native_ops.json"])


def test_generated_manifest_validates_against_strict_v2_schema():
    schema = json.loads(
        (ROOT / "manifests" / "native_ops.schema.json").read_text(encoding="utf-8")
    )
    manifest = json.loads(
        (ROOT / "generated" / "native_ops.json").read_text(encoding="utf-8")
    )
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.Draft202012Validator(schema).validate(manifest)


def test_schema_rejects_additional_properties_recursively(tmp_path: Path):
    schema = json.loads(
        (ROOT / "manifests" / "native_ops.schema.json").read_text(encoding="utf-8")
    )
    validator = jsonschema.Draft202012Validator(schema)
    manifest = _fixture_manifest(tmp_path)
    manifest["unexpected"] = True
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(manifest)
    manifest = _fixture_manifest(tmp_path / "nested")
    manifest["operators"][0]["fake"]["unexpected"] = True
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(manifest)


def test_schema_rejects_any_non_mindclade_operator_identity(tmp_path: Path):
    schema = json.loads(
        (ROOT / "manifests" / "native_ops.schema.json").read_text(encoding="utf-8")
    )
    manifest = _fixture_manifest(tmp_path)
    manifest["operators"][0]["namespace"] = "other"
    manifest["operators"][0]["qualified_name"] = "other::fixture_op"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(schema).validate(manifest)
