import json
from pathlib import Path

from kernels.native.codegen.generate import (
    GENERATED_FILENAMES,
    render_all,
    write_outputs,
)


def _fixture_native_root(tmp_path: Path) -> tuple[Path, Path]:
    kernels_root = tmp_path / "kernels"
    native_root = kernels_root / "native"
    native_root.mkdir(parents=True)
    operation = kernels_root / "pairformer" / "fixture_op"
    operation.mkdir(parents=True)
    source = operation / "tilelang.py"
    source.write_text(
        '''from kernels.native.tilelang.decorator import mindclade_kernel
@mindclade_kernel(
    name="fixture_op",
    schema="fixture_op(Tensor x, int width) -> Tensor",
    family="pairformer",
    fake={"module": "kernels.pairformer.fixture_op.tilelang", "symbol": "fake"},
    autograd={
        "mode": "registered",
        "setup_context": {"module": "kernels.pairformer.fixture_op.tilelang", "symbol": "setup_context"},
        "backward": {"module": "kernels.pairformer.fixture_op.tilelang", "symbol": "backward"},
    },
)
def build_tilelang_program(*, target, width):
    raise NotImplementedError
''',
        encoding="utf-8",
    )
    return native_root, source


def test_render_is_deterministic_and_write_emits_exact_surfaces(tmp_path: Path):
    native_root, source = _fixture_native_root(tmp_path)
    first = render_all(native_root, source_files=[source])
    second = render_all(native_root, source_files=[source])
    assert first == second
    output = tmp_path / "output"
    write_outputs(first, output)
    assert set(GENERATED_FILENAMES) == {path.name for path in output.iterdir()}
    assert all((output / name).read_text(encoding="utf-8") == first[name] for name in first)


def test_generated_torch_surfaces_are_only_in_mindclade_namespace(tmp_path: Path):
    native_root, source = _fixture_native_root(tmp_path)
    rendered = render_all(native_root, source_files=[source])
    definitions = rendered["registration.generated.cpp"]
    implementations = rendered["operation_registry.generated.cpp"]
    python = rendered["python_registration_generated.py"]
    assert "STABLE_TORCH_LIBRARY(mindclade" in definitions
    assert "STABLE_TORCH_LIBRARY_IMPL(mindclade, CUDA" in implementations
    assert "mindclade::fixture_op" in python
    assert "importlib" not in python
    assert "TORCH_LIBRARY(" not in definitions.replace("STABLE_TORCH_LIBRARY(", "")


def test_manifest_carries_strict_source_identity(tmp_path: Path):
    native_root, source = _fixture_native_root(tmp_path)
    manifest = json.loads(render_all(native_root, source_files=[source])["native_ops.json"])
    assert manifest["schema_version"] == 2
    assert manifest["generator"] == {
        "id": "kernels.native.codegen.generate",
        "version": 2,
    }
    assert manifest["operators"][0]["qualified_name"] == "mindclade::fixture_op"
    assert manifest["operators"][0]["source_sha256"].startswith("sha256:")
    assert "symbol" not in manifest["operators"][0]


def test_empty_inventory_emits_no_operation_labels_or_symbols(tmp_path: Path):
    native_root = tmp_path / "kernels" / "native"
    native_root.mkdir(parents=True)
    rendered = render_all(native_root, source_files=[])
    assert json.loads(rendered["native_ops.json"])["operators"] == []
    assert "//kernels/" not in rendered["native_ops.generated.bzl"]
    assert "/pairformer/" not in rendered["native_ops.generated.cmake"]
    assert "m.def(" not in rendered["registration.generated.cpp"]
    assert "m.impl(" not in rendered["operation_registry.generated.cpp"]
