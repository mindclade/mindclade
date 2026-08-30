from pathlib import Path

import pytest

from kernels.native.codegen.discover import discover_specs


def _write_operation(
    kernels_root: Path,
    family: str,
    name: str,
    *,
    namespace: str = "mindclade",
    body: str | None = None,
) -> Path:
    operation = kernels_root / family / name
    operation.mkdir(parents=True)
    module = f"kernels.{family}.{name}.tilelang"
    source = operation / "tilelang.py"
    source.write_text(
        body
        or f'''from kernels.native.tilelang.decorator import mindclade_kernel

@mindclade_kernel(
    name={name!r},
    schema={f"{name}(Tensor x) -> Tensor"!r},
    family={family!r},
    fake={{"module": {module!r}, "symbol": "fake"}},
    autograd={{"mode": "not_supported"}},
    namespace={namespace!r},
)
def build_tilelang_program(*, target, m):
    raise NotImplementedError
''',
        encoding="utf-8",
    )
    return source


def test_discovers_only_explicit_operation_sources(tmp_path: Path):
    selected = _write_operation(tmp_path, "family_a", "selected")
    _write_operation(tmp_path, "family_a", "not_selected")
    specs = discover_specs(tmp_path, [selected])
    assert [spec.qualified_name for spec in specs] == ["mindclade::selected"]
    assert specs[0].source == "family_a/selected/tilelang.py"
    assert specs[0].source_sha256.startswith("sha256:")


def test_empty_explicit_inventory_is_valid_for_inactive_target(tmp_path: Path):
    assert discover_specs(tmp_path, []) == []


def test_duplicate_operator_names_fail(tmp_path: Path):
    first = _write_operation(tmp_path, "family_a", "dup")
    second = _write_operation(tmp_path, "family_b", "dup")
    with pytest.raises(ValueError, match="duplicate kernel name"):
        discover_specs(tmp_path, [first, second])


def test_declaration_must_be_operation_local(tmp_path: Path):
    bad = tmp_path / "misc" / "kernel.py"
    bad.parent.mkdir(parents=True)
    bad.write_text("def build_tilelang_program(): pass\n", encoding="utf-8")
    with pytest.raises(ValueError, match="must be colocated"):
        discover_specs(tmp_path, [bad])


def test_each_declared_source_requires_exactly_one_declaration(tmp_path: Path):
    source = _write_operation(tmp_path, "family_a", "missing", body="def helper(): pass\n")
    with pytest.raises(ValueError, match="exactly one"):
        discover_specs(tmp_path, [source])


def test_decorator_values_must_be_literals(tmp_path: Path):
    source = _write_operation(
        tmp_path,
        "family_a",
        "dynamic",
        body='''FAKE = {"module": "kernels.family_a.dynamic.tilelang", "symbol": "fake"}
from kernels.native.tilelang.decorator import mindclade_kernel
@mindclade_kernel(name="dynamic", schema="dynamic(Tensor x) -> Tensor", family="family_a", fake=FAKE, autograd={"mode": "not_supported"})
def build_tilelang_program(*, target, m): pass
''',
    )
    with pytest.raises(ValueError, match="must be Python literals"):
        discover_specs(tmp_path, [source])


def test_non_mindclade_namespace_fails_closed(tmp_path: Path):
    source = _write_operation(tmp_path, "family_a", "foreign", namespace="other")
    with pytest.raises(ValueError, match="namespace must be exactly 'mindclade'"):
        discover_specs(tmp_path, [source])


def test_declared_source_cannot_be_a_symlink(tmp_path: Path):
    target = _write_operation(tmp_path, "family_a", "target")
    operation = tmp_path / "family_a" / "linked"
    operation.mkdir(parents=True)
    link = operation / "tilelang.py"
    link.symlink_to(target)
    with pytest.raises(ValueError, match="symlink"):
        discover_specs(tmp_path, [link])
