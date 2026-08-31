from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from kernels.native.codegen.discover import DiscoveredKernelSpec, discover_specs


def _spec_source(
    family: str,
    name: str,
    *,
    namespace: str = "mindclade",
    declared_family: str | None = None,
    declared_name: str | None = None,
    declared_source: str | None = None,
    operator_root: str | None = None,
    forward_root: str | None = None,
    builder: str | None = None,
    symbol: str | None = None,
) -> str:
    spec_family = declared_family or family
    spec_name = declared_name or name
    source = declared_source or f"{spec_family}/{spec_name}/spec.py"
    semantic = operator_root or spec_name
    provider = forward_root or f"_{spec_name}_fwd"
    builder_identity = builder or f"kernels.{spec_family}.{spec_name}.tilelang:build_forward"
    native_symbol = symbol or f"mindclade_tilelang_{spec_name}_fwd_launch"
    return f'''
from kernels.api import (
    AutogradPolicy,
    EffectSpec,
    ForwardSpec,
    KernelSpec,
    LaunchContract,
    OutputSpec,
    SameAsInputDType,
    SameAsInputDevice,
    ShapeOf,
)

KERNEL_SPEC: KernelSpec = KernelSpec(
    name={spec_name!r},
    namespace={namespace!r},
    family={spec_family!r},
    source={source!r},
    operator_schema={f"{semantic}(Tensor x) -> Tensor output"!r},
    facade_outputs=("output",),
    fake=None,
    forward=ForwardSpec(
        schema={f"{provider}(Tensor x) -> Tensor output"!r},
        builder={builder_identity!r},
        symbol={native_symbol!r},
        outputs=(
            OutputSpec(
                name="output",
                shape=ShapeOf(argument="x"),
                dtype=SameAsInputDType(argument="x"),
                device=SameAsInputDevice(argument="x"),
                semantic_axes=("element",),
                visible_in_facade=True,
                saved_for_backward=False,
            ),
        ),
    ),
    backward=None,
    autograd_policy=AutogradPolicy.NONE,
    effects=EffectSpec(),
    launch=LaunchContract(),
)
'''


def _write_operation(
    kernels_root: Path,
    family: str,
    name: str,
    *,
    source: str | None = None,
    tilelang_source: str = "this is deliberately not valid Python !!!",
    **overrides: object,
) -> str:
    operation = kernels_root / family / name
    operation.mkdir(parents=True, exist_ok=True)
    declaration = source or _spec_source(family, name, **overrides)
    (operation / "spec.py").write_text(declaration, encoding="utf-8")
    (operation / "tilelang.py").write_text(tilelang_source, encoding="utf-8")
    return f"{family}/{name}/spec.py"


def test_discovers_only_explicit_specs_without_parsing_or_importing_tilelang(
    tmp_path: Path,
) -> None:
    selected = _write_operation(tmp_path, "family_a", "selected")
    _write_operation(tmp_path, "family_a", "not_selected")
    sentinel = tmp_path / "imported"
    (tmp_path / "family_a" / "selected" / "__init__.py").write_text(
        f"from pathlib import Path\nPath({str(sentinel)!r}).touch()\n",
        encoding="utf-8",
    )

    discovered = discover_specs(tmp_path, [selected])

    assert len(discovered) == 1
    assert isinstance(discovered[0], DiscoveredKernelSpec)
    assert discovered[0].qualified_name == "mindclade::selected"
    assert discovered[0].spec.source == "family_a/selected/spec.py"
    assert not sentinel.exists()


def test_declaration_digest_and_registry_order_are_deterministic(tmp_path: Path) -> None:
    zeta = _write_operation(tmp_path, "family_a", "zeta")
    alpha = _write_operation(tmp_path, "family_a", "alpha")
    expected = hashlib.sha256((tmp_path / alpha).read_bytes()).hexdigest()

    first = discover_specs(tmp_path, [zeta, alpha])
    second = discover_specs(tmp_path, [alpha, zeta])

    assert [item.qualified_name for item in first] == [
        "mindclade::alpha",
        "mindclade::zeta",
    ]
    assert first == second
    assert first[0].declaration_sha256 == f"sha256:{expected}"


def test_empty_explicit_inventory_is_valid_for_inactive_target(tmp_path: Path) -> None:
    assert discover_specs(tmp_path, []) == []


@pytest.mark.parametrize(
    ("source", "message"),
    (
        ("import os\nKERNEL_SPEC = os.environ\n", "arbitrary imports are forbidden"),
        (
            "from kernels.api import KernelSpec\n"
            "KERNEL_SPEC = [KernelSpec() for _ in ()]\n",
            "unsupported expression node ListComp",
        ),
        (
            "from kernels.api import KernelSpec\nKERNEL_SPEC = build_spec()\n",
            "not an approved constructor",
        ),
        (
            "from kernels.api import KernelSpec\n"
            "if True:\n    KERNEL_SPEC = KernelSpec()\n",
            "unsupported top-level statement If",
        ),
    ),
)
def test_unsafe_spec_ast_fails_closed(
    tmp_path: Path,
    source: str,
    message: str,
) -> None:
    declaration = _write_operation(tmp_path, "family_a", "unsafe", source=source)
    with pytest.raises(ValueError, match=message):
        discover_specs(tmp_path, [declaration])


@pytest.mark.parametrize(
    ("inventory", "message"),
    (
        ("family_a/operation/tilelang.py", "exactly <family>/<operation>/spec.py"),
        ("family_a/operation/../operation/spec.py", "not canonical"),
        ("family_a/spec.py", "exactly <family>/<operation>/spec.py"),
        ("Family/operation/spec.py", "exactly <family>/<operation>/spec.py"),
    ),
)
def test_inventory_paths_must_be_canonical_repository_relative_specs(
    tmp_path: Path,
    inventory: str,
    message: str,
) -> None:
    path = tmp_path / inventory
    path.parent.mkdir(parents=True, exist_ok=True)
    if ".." not in inventory:
        path.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        discover_specs(tmp_path, [inventory])


def test_absolute_inventory_path_is_rejected(tmp_path: Path) -> None:
    relative = _write_operation(tmp_path, "family_a", "absolute")
    with pytest.raises(ValueError, match="repository-relative"):
        discover_specs(tmp_path, [tmp_path / relative])


def test_declared_spec_cannot_be_a_symlink(tmp_path: Path) -> None:
    target = _write_operation(tmp_path, "family_a", "target")
    linked = tmp_path / "family_a" / "linked"
    linked.mkdir(parents=True)
    (linked / "spec.py").symlink_to(tmp_path / target)
    with pytest.raises(ValueError, match="symlink"):
        discover_specs(tmp_path, ["family_a/linked/spec.py"])


@pytest.mark.parametrize(
    ("overrides", "message"),
    (
        ({"namespace": "other"}, "namespace must be mindclade"),
        ({"declared_family": "family_b"}, "family"),
        ({"declared_name": "different"}, "source must equal"),
        ({"declared_source": "prefix/family_a/operation/spec.py"}, "source must equal"),
        ({"operator_root": "other"}, "semantic operator name"),
        ({"forward_root": "_other_fwd"}, "forward provider"),
        (
            {"builder": "kernels.family_a.other.tilelang:build_forward"},
            "builder module must be",
        ),
    ),
)
def test_contract_and_locality_mismatches_fail_closed(
    tmp_path: Path,
    overrides: dict[str, object],
    message: str,
) -> None:
    declaration = _write_operation(
        tmp_path,
        "family_a",
        "operation",
        **overrides,
    )
    with pytest.raises(ValueError, match=message):
        discover_specs(tmp_path, [declaration])


def test_duplicate_declared_path_fails(tmp_path: Path) -> None:
    declaration = _write_operation(tmp_path, "family_a", "operation")
    with pytest.raises(ValueError, match="duplicate declared spec path"):
        discover_specs(tmp_path, [declaration, declaration])


def test_duplicate_qualified_operator_fails(tmp_path: Path) -> None:
    first = _write_operation(tmp_path, "family_a", "duplicate")
    second = _write_operation(tmp_path, "family_b", "duplicate")
    with pytest.raises(ValueError, match="duplicate qualified operator"):
        discover_specs(tmp_path, [first, second])


def test_duplicate_builder_fails_before_locality_selection(tmp_path: Path) -> None:
    builder = "kernels.family_a.first.tilelang:build_forward"
    first = _write_operation(tmp_path, "family_a", "first", builder=builder)
    second = _write_operation(tmp_path, "family_b", "second", builder=builder)
    with pytest.raises(ValueError, match="duplicate builder"):
        discover_specs(tmp_path, [first, second])


def test_duplicate_native_symbol_fails(tmp_path: Path) -> None:
    symbol = "mindclade_tilelang_duplicate_fwd_launch"
    first = _write_operation(tmp_path, "family_a", "first", symbol=symbol)
    second = _write_operation(tmp_path, "family_b", "second", symbol=symbol)
    with pytest.raises(ValueError, match="duplicate symbol"):
        discover_specs(tmp_path, [first, second])
