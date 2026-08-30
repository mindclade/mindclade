import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import kernels.native.tilelang.build as build
from kernels.native.tilelang.build import compile_all


def _fixture_source(tmp_path: Path) -> tuple[Path, Path]:
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
    return native_root, source


def _profiles():
    return {
        "mindclade::fixture_op": [
            {"name": "m16", "arguments": {"m": 16}},
        ]
    }


def test_offline_builder_invokes_compile_and_captures_nonempty_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    native_root, source = _fixture_source(tmp_path)
    calls: list[tuple[str, int]] = []

    class Program:
        def compile(self):
            calls.append(("compile", 16))
            return self

        def get_kernel_source(self):
            return 'extern "C" __global__ void fixture_op() {}\n'

    def builder(*, target: str, m: int):
        assert target == "cuda-sm90"
        assert m == 16
        return Program()

    original_import = build.importlib.import_module
    monkeypatch.setattr(
        build.importlib,
        "import_module",
        lambda name: SimpleNamespace(__version__="test-pinned")
        if name == "tilelang"
        else original_import(name),
    )
    monkeypatch.setattr(build, "_resolve_builder", lambda spec, kernels_root: builder)
    output = tmp_path / "compiled"
    receipts = compile_all(
        native_root,
        output,
        source_files=[source],
        profiles=_profiles(),
        target="cuda-sm90",
    )
    assert calls == [("compile", 16)]
    assert len(receipts) == 1
    artifact = output / receipts[0].output
    assert artifact.read_bytes()
    assert receipts[0].artifact_sha256 == (
        "sha256:" + hashlib.sha256(artifact.read_bytes()).hexdigest()
    )
    document = json.loads((output / "build_receipts.json").read_text(encoding="utf-8"))
    assert document["receipts"][0]["qualified_name"] == "mindclade::fixture_op"


def test_offline_builder_requires_exact_bounded_profile_inventory(tmp_path: Path):
    native_root, source = _fixture_source(tmp_path)
    with pytest.raises(ValueError, match="inventory mismatch"):
        compile_all(
            native_root,
            tmp_path / "compiled",
            source_files=[source],
            profiles={},
            target="cuda-sm90",
        )


def test_offline_builder_fails_closed_when_tilelang_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    native_root, source = _fixture_source(tmp_path)

    def missing(name: str):
        if name == "tilelang":
            raise ModuleNotFoundError(name)
        raise AssertionError(name)

    monkeypatch.setattr(build.importlib, "import_module", missing)
    with pytest.raises(RuntimeError, match="TileLang is required"):
        compile_all(
            native_root,
            tmp_path / "compiled",
            source_files=[source],
            profiles=_profiles(),
            target="cuda-sm90",
        )
