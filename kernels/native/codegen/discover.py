from __future__ import annotations

import ast
import hashlib
from pathlib import Path
from typing import Any, Iterable

from kernels.native.codegen.schema import parse_schema
from kernels.native.tilelang.model import AutogradPolicy, CallableRef, KernelSpec

_DECORATOR_NAME = "mindclade_kernel"
_BUILDER_NAME = "build_tilelang_program"
_REQUIRED = {"name", "schema", "family", "fake", "autograd"}
_ALLOWED = _REQUIRED | {
    "namespace",
    "backend",
    "version",
    "launch_symbol",
    "devices",
}


def _decorator_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _literal(node: ast.AST) -> Any:
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError) as exc:
        raise ValueError("kernel decorator arguments must be Python literals") from exc


def _normalize_source(kernels_root: Path, source: str | Path) -> tuple[Path, str]:
    raw = Path(source)
    if ".." in raw.parts:
        raise ValueError(f"kernel source must not contain '..': {source}")
    candidate = raw if raw.is_absolute() else kernels_root / raw
    try:
        lexical_relative = candidate.relative_to(kernels_root)
    except ValueError as exc:
        raise ValueError(f"declared kernel source escapes kernels root: {candidate}") from exc
    current = kernels_root
    for part in lexical_relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"declared kernel source must not traverse a symlink: {candidate}")
    try:
        resolved = candidate.resolve(strict=True)
    except (FileNotFoundError, RuntimeError) as exc:
        raise ValueError(f"declared kernel source does not exist: {candidate}") from exc
    try:
        relative = resolved.relative_to(kernels_root)
    except ValueError as exc:
        raise ValueError(f"declared kernel source escapes kernels root: {candidate}") from exc

    if not resolved.is_file():
        raise ValueError(f"declared kernel source is not a regular file: {candidate}")
    if len(relative.parts) != 3 or relative.parts[2] != "tilelang.py":
        raise ValueError(
            f"{candidate}: @mindclade_kernel must be colocated at "
            "kernels/<family>/<operation>/tilelang.py"
        )
    if relative.parts[0] == "native":
        raise ValueError("operation declarations cannot live in kernels/native")
    return resolved, relative.as_posix()


def _declaration(tree: ast.Module, path: Path) -> tuple[ast.FunctionDef, ast.Call]:
    declarations: list[tuple[ast.AST, ast.Call]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if isinstance(decorator, ast.Call) and _decorator_name(decorator.func) == _DECORATOR_NAME:
                declarations.append((node, decorator))
    if len(declarations) != 1:
        raise ValueError(
            f"{path}: each declared source must contain exactly one @{_DECORATOR_NAME}; "
            f"found {len(declarations)}"
        )
    node, decorator = declarations[0]
    if not isinstance(node, ast.FunctionDef) or node not in tree.body:
        raise ValueError(f"{path}: kernel declaration must decorate one top-level synchronous function")
    if node.name != _BUILDER_NAME:
        raise ValueError(f"{path}: declared builder function must be named {_BUILDER_NAME!r}")
    return node, decorator


def _extract_from_file(path: Path, relative: str) -> KernelSpec:
    raw = path.read_bytes()
    try:
        source_text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{path}: kernel source must be UTF-8") from exc
    try:
        tree = ast.parse(source_text, filename=str(path))
    except SyntaxError as exc:
        raise ValueError(f"{path}: kernel source is not valid Python: {exc.msg}") from exc
    _, decorator = _declaration(tree, path)
    if decorator.args:
        raise ValueError(f"{path}: @{_DECORATOR_NAME} accepts keyword arguments only")

    values: dict[str, Any] = {}
    for keyword in decorator.keywords:
        if keyword.arg is None or keyword.arg not in _ALLOWED:
            raise ValueError(f"{path}: unsupported @{_DECORATOR_NAME} field {keyword.arg!r}")
        if keyword.arg in values:
            raise ValueError(f"{path}: duplicate @{_DECORATOR_NAME} field {keyword.arg!r}")
        values[keyword.arg] = _literal(keyword.value)
    missing = sorted(_REQUIRED - values.keys())
    if missing:
        raise ValueError(f"{path}: missing kernel fields: {', '.join(missing)}")

    devices = values.get("devices", ("cuda",))
    if not isinstance(devices, (tuple, list)) or not all(isinstance(device, str) for device in devices):
        raise ValueError(f"{path}: devices must be a literal tuple/list of strings")

    family, operation, _ = relative.split("/")
    spec = KernelSpec(
        name=values["name"],
        schema=values["schema"],
        family=values["family"],
        source=relative,
        source_sha256="sha256:" + hashlib.sha256(raw).hexdigest(),
        fake=CallableRef.from_mapping(values["fake"], field="fake"),
        autograd=AutogradPolicy.from_mapping(values["autograd"]),
        namespace=values.get("namespace", "mindclade"),
        backend=values.get("backend", "tilelang"),
        version=values.get("version", 1),
        launch_symbol=values.get("launch_symbol"),
        devices=tuple(devices),
    )
    if spec.family != family:
        raise ValueError(
            f"{path}: decorator family {spec.family!r} must match colocated family {family!r}"
        )
    if spec.name != operation:
        raise ValueError(
            f"{path}: decorator name {spec.name!r} must match operation directory {operation!r}"
        )
    parsed = parse_schema(spec.schema)
    if parsed.name != spec.name:
        raise ValueError(f"{path}: schema name {parsed.name!r} does not match {spec.name!r}")
    return spec


def discover_specs(
    kernels_root: Path,
    source_files: Iterable[str | Path],
) -> list[KernelSpec]:
    """Validate only the explicit build-declared source inventory."""

    if kernels_root.is_symlink():
        raise ValueError(f"kernels root must not be a symlink: {kernels_root}")
    try:
        root = kernels_root.resolve(strict=True)
    except (FileNotFoundError, RuntimeError) as exc:
        raise ValueError(f"kernels directory does not exist: {kernels_root}") from exc
    if not root.is_dir():
        raise ValueError(f"kernels root is not a directory: {kernels_root}")

    normalized: dict[str, Path] = {}
    for source in source_files:
        path, relative = _normalize_source(root, source)
        if relative in normalized:
            raise ValueError(f"duplicate declared source input: {relative}")
        normalized[relative] = path

    specs = [_extract_from_file(normalized[relative], relative) for relative in sorted(normalized)]
    seen: set[str] = set()
    for spec in specs:
        if spec.qualified_name in seen:
            raise ValueError(f"duplicate kernel name: {spec.qualified_name}")
        seen.add(spec.qualified_name)
        if spec.namespace != "mindclade" or spec.qualified_name != f"mindclade::{spec.name}":
            raise ValueError("all generated Torch operators must belong only to namespace 'mindclade'")
    return sorted(specs, key=lambda spec: spec.qualified_name)
