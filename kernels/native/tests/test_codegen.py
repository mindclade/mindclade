import json
from pathlib import Path

from kernels.api import content_digest
from kernels.native.codegen.generate import GENERATED_FILENAMES, render_all, write_outputs


def _fixture_native_root(tmp_path: Path, *, fake: bool = True) -> tuple[Path, str]:
    kernels_root = tmp_path / "kernels"
    native_root = kernels_root / "native"
    native_root.mkdir(parents=True)
    operation = kernels_root / "pairformer" / "fixture_op"
    operation.mkdir(parents=True)
    fake_value = '"kernels.pairformer.fixture_op.reference:fake"' if fake else "None"
    (operation / "spec.py").write_text(
        f'''from kernels.api import (
    AutogradPolicy, ConstantDType, EffectSpec, ForwardSpec, KernelSpec,
    LaunchContract, OutputSpec, ShapeOf, SameAsInputDevice,
)
KERNEL_SPEC: KernelSpec = KernelSpec(
    name="fixture_op", namespace="mindclade", family="pairformer",
    source="pairformer/fixture_op/spec.py",
    operator_schema="fixture_op(Tensor x, int width) -> Tensor output",
    facade_outputs=("output",), fake={fake_value},
    forward=ForwardSpec(
        schema="_fixture_op_fwd(Tensor x, int width) -> Tensor output",
        builder="kernels.pairformer.fixture_op.tilelang:build_tilelang_program",
        symbol="mindclade_tilelang_fixture_op_fwd_launch",
        outputs=(OutputSpec(
            name="output", shape=ShapeOf(argument="x"),
            dtype=ConstantDType(value="float32"),
            device=SameAsInputDevice(argument="x"), semantic_axes=("element",),
            visible_in_facade=True, saved_for_backward=False,
        ),),
    ), backward=None, autograd_policy=AutogradPolicy.NONE,
    effects=EffectSpec(), launch=LaunchContract(graph_capture_safe=False),
)
''',
        encoding="utf-8",
    )
    return native_root, "pairformer/fixture_op/spec.py"


def test_render_is_deterministic_and_write_emits_exact_surfaces(tmp_path: Path):
    native_root, source = _fixture_native_root(tmp_path)
    first = render_all(native_root, source_files=[source])
    assert first == render_all(native_root, source_files=[source])
    output = tmp_path / "output"
    write_outputs(first, output)
    assert set(GENERATED_FILENAMES) == {path.name for path in output.iterdir()}
    assert all((output / name).read_text(encoding="utf-8") == first[name] for name in first)


def test_generated_schema_registry_and_build_inventories_are_v3(tmp_path: Path):
    native_root, source = _fixture_native_root(tmp_path)
    rendered = render_all(native_root, source_files=[source])
    definitions = rendered["registration.generated.cpp"]
    implementations = rendered["operation_registry.generated.cpp"]
    assert definitions.index('m.def("fixture_op(') < definitions.index('m.def("_fixture_op_fwd(')
    assert 'm.impl("fixture_op"' in implementations
    assert 'm.impl("_fixture_op_fwd"' in implementations
    assert "mindclade_tilelang_fixture_op_fwd_launch" in implementations
    assert "MINDCLADE_KERNEL_SPEC_SOURCES" in rendered["native_ops.generated.bzl"]
    assert "//kernels/pairformer/fixture_op:spec.py" in rendered["native_ops.generated.bzl"]
    assert "MINDCLADE_TILELANG_KERNEL_SOURCES" in rendered["native_ops.generated.cmake"]


def test_manifest_has_exact_operator_keys_and_recomputable_digests(tmp_path: Path):
    native_root, source = _fixture_native_root(tmp_path)
    manifest = json.loads(render_all(native_root, source_files=[source])["native_ops.json"])
    assert manifest["schema_version"] == 3
    assert manifest["generator"] == {"id": "kernels.native.codegen.generate", "version": 3}
    operator = manifest["operators"][0]
    assert set(operator) == {
        "name", "qualified_name", "namespace", "family", "source", "spec_sha256",
        "kernel_spec_digest", "operator_schema", "facade_outputs", "fake", "forward",
        "backward", "autograd_policy", "composite", "effects", "launch", "backend",
        "version", "devices", "registrations",
    }
    assert [entry["kind"] for entry in operator["registrations"]] == ["semantic", "forward"]
    without_digest = dict(manifest)
    assert without_digest.pop("manifest_digest") == content_digest(without_digest)
    assert operator["forward"]["outputs"][0]["shape"]["node"] == "shape_of"


def test_declarative_fake_and_explicit_non_differentiability_are_generated(tmp_path: Path):
    native_root, source = _fixture_native_root(tmp_path, fake=False)
    python = render_all(native_root, source_files=[source])["python_registration_generated.py"]
    assert "torch.empty(" in python
    assert "_mindclade_dtype(" in python
    assert "float32" in python
    assert "mindclade::fixture_op is non-differentiable" in python
    assert "importlib" not in python


def test_empty_inventory_emits_no_operation_labels_or_symbols(tmp_path: Path):
    native_root = tmp_path / "kernels" / "native"
    native_root.mkdir(parents=True)
    rendered = render_all(native_root, source_files=[])
    assert json.loads(rendered["native_ops.json"])["operators"] == []
    assert "//kernels/" not in rendered["native_ops.generated.bzl"]
    assert "/pairformer/" not in rendered["native_ops.generated.cmake"]
    assert "m.def(" not in rendered["registration.generated.cpp"]
    assert "m.impl(" not in rendered["operation_registry.generated.cpp"]
