"""Closed-world discovery for canonical operation-local kernel specifications."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
import hashlib
from pathlib import Path
import re

from kernels.api import ExprDomain, ImplementationSpec, KernelSpec
from kernels.native.codegen.parse_literal_ast import parse_kernel_declarations_source
from kernels.native.codegen.schema import parse_schema

_PATH_SEGMENT = re.compile(r"[a-z][a-z0-9_]*")
_SCHEMA_ROOT = re.compile(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*\(")
_PYTHON_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_NATIVE_SYMBOL = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


@dataclass(frozen=True, slots=True)
class DiscoveredKernelSpec:
    """One validated semantic specification and its declaration-file identity."""

    spec: KernelSpec
    implementations: tuple[ImplementationSpec, ...]
    declaration_sha256: str

    @property
    def qualified_name(self) -> str:
        return self.spec.qualified_name


def _normalize_source(kernels_root: Path, source: str | Path) -> tuple[Path, str]:
    if not isinstance(source, (str, Path)):
        raise TypeError("declared spec inventory entries must be strings or pathlib.Path values")
    source_text = str(source)
    if not source_text:
        raise ValueError("declared spec inventory paths must not be empty")
    if "\\" in source_text:
        raise ValueError(f"declared spec inventory path is not canonical POSIX: {source_text!r}")

    raw = Path(source_text)
    if raw.is_absolute():
        raise ValueError(f"declared spec inventory path must be repository-relative: {source_text}")
    if raw.as_posix() != source_text or any(part in {"", ".", ".."} for part in raw.parts):
        raise ValueError(f"declared spec inventory path is not canonical: {source_text}")
    if (
        len(raw.parts) != 3
        or raw.parts[2] != "spec.py"
        or _PATH_SEGMENT.fullmatch(raw.parts[0]) is None
        or _PATH_SEGMENT.fullmatch(raw.parts[1]) is None
    ):
        raise ValueError(
            f"{source_text}: declarations must be exactly <family>/<operation>/spec.py"
        )
    if raw.parts[0] == "native":
        raise ValueError("operation declarations cannot live in kernels/native")

    candidate = kernels_root / raw
    current = kernels_root
    for part in raw.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"declared spec path must not traverse a symlink: {source_text}")
    try:
        resolved = candidate.resolve(strict=True)
    except (FileNotFoundError, RuntimeError) as exc:
        raise ValueError(f"declared spec does not exist: {source_text}") from exc
    try:
        relative = resolved.relative_to(kernels_root)
    except ValueError as exc:
        raise ValueError(f"declared spec escapes kernels root: {source_text}") from exc
    if relative.as_posix() != source_text:
        raise ValueError(f"declared spec resolves noncanonically: {source_text}")
    if not resolved.is_file():
        raise ValueError(f"declared spec is not a regular file: {source_text}")
    return resolved, source_text


def _schema_root(schema: str, *, label: str, source: str) -> str:
    match = _SCHEMA_ROOT.match(schema)
    if match is None:
        raise ValueError(f"{source}: {label} is not a canonical operator schema")
    return match.group(1)


def _validate_spec_identity(spec: KernelSpec, relative: str) -> None:
    family, operation, _ = relative.split("/")
    if spec.namespace != "mindclade" or spec.qualified_name != f"mindclade::{spec.name}":
        raise ValueError(f"{relative}: namespace must be exactly 'mindclade'")
    if spec.source != relative:
        raise ValueError(
            f"{relative}: KernelSpec source must equal its explicit inventory path, "
            f"got {spec.source!r}"
        )
    if spec.family != family:
        raise ValueError(
            f"{relative}: KernelSpec family {spec.family!r} must match directory {family!r}"
        )
    if spec.name != operation:
        raise ValueError(
            f"{relative}: KernelSpec name {spec.name!r} must match directory {operation!r}"
        )

    semantic_root = _schema_root(
        spec.operator_schema,
        label="operator_schema",
        source=relative,
    )
    if semantic_root != operation:
        raise ValueError(
            f"{relative}: semantic provider root {semantic_root!r} must equal {operation!r}"
        )
    forward_root = _schema_root(
        spec.forward.schema,
        label="forward schema",
        source=relative,
    )
    if forward_root != f"_{operation}_fwd":
        raise ValueError(
            f"{relative}: forward provider root must be _{operation}_fwd, "
            f"got {forward_root!r}"
        )
    if spec.backward is not None:
        backward_root = _schema_root(
            spec.backward.schema,
            label="backward schema",
            source=relative,
        )
        if backward_root != f"_{operation}_bwd":
            raise ValueError(
                f"{relative}: backward provider root must be _{operation}_bwd, "
                f"got {backward_root!r}"
            )


def _program_contracts(spec: KernelSpec) -> Iterator[tuple[str, object]]:
    yield "forward", spec.forward
    if spec.backward is not None:
        yield "backward", spec.backward


def _builder_identities(spec: KernelSpec) -> Iterator[tuple[str, str]]:
    for phase, contract in _program_contracts(spec):
        yield f"{phase}.builder", contract.builder
        group = contract.program_group
        if group is not None:
            for node in group.nodes:
                yield f"{phase}.program_group.{node.name}.builder", node.builder


def _symbol_identities(spec: KernelSpec) -> Iterator[tuple[str, str]]:
    for phase, contract in _program_contracts(spec):
        yield f"{phase}.symbol", contract.symbol
        group = contract.program_group
        if group is not None:
            for node in group.nodes:
                yield f"{phase}.program_group.{node.name}.symbol", node.symbol


def _validate_builder_locality(spec: KernelSpec, relative: str) -> None:
    family, operation, _ = relative.split("/")
    expected_module = f"kernels.{family}.{operation}.tilelang"
    for label, identity in _builder_identities(spec):
        if identity.count(":") != 1:
            raise ValueError(f"{relative}: {label} must be one module:function identity")
        module, function = identity.split(":", 1)
        if module != expected_module:
            raise ValueError(
                f"{relative}: {label} module must be {expected_module!r}, got {module!r}"
            )
        if _PYTHON_IDENTIFIER.fullmatch(function) is None:
            raise ValueError(f"{relative}: {label} function is not a Python identifier")


def _validate_implementations(
    spec: KernelSpec,
    implementations: tuple[ImplementationSpec, ...],
    relative: str,
) -> tuple[ImplementationSpec, ...]:
    expected_module = f"kernels.{spec.family}.{spec.name}.tilelang"
    semantic = parse_schema(spec.operator_schema)
    tensor_arguments = {argument.name for argument in semantic.args if argument.is_tensor}
    identities: set[tuple[str, int]] = set()
    for implementation in implementations:
        if implementation.operation != spec.qualified_name:
            raise ValueError(
                f"{relative}: implementation operation must equal {spec.qualified_name!r}"
            )
        if implementation.family != spec.family:
            raise ValueError(
                f"{relative}: implementation family must equal {spec.family!r}"
            )
        if implementation.backend != spec.backend:
            raise ValueError(
                f"{relative}: implementation backend must equal {spec.backend!r}"
            )
        module, separator, function = implementation.builder.partition(":")
        if separator != ":" or module != expected_module or _PYTHON_IDENTIFIER.fullmatch(function) is None:
            raise ValueError(
                f"{relative}: implementation builder must be operation-local in {expected_module!r}"
            )
        identity = (implementation.name, implementation.version)
        if identity in identities:
            raise ValueError(f"{relative}: duplicate implementation identity {identity!r}")
        identities.add(identity)
        envelope = implementation.envelope
        for constraint in envelope.constraints:
            if constraint.predicate.domain is not ExprDomain.BOOL:
                raise ValueError(
                    f"{relative}: capability constraint {constraint.code!r} must be boolean"
                )
        unknown_arguments = sorted(
            item.argument
            for item in envelope.tensor_constraints
            if item.argument not in tensor_arguments
        )
        if unknown_arguments:
            raise ValueError(
                f"{relative}: tensor capability constraints reference non-Tensor "
                f"arguments: {unknown_arguments}"
            )
    return tuple(sorted(implementations, key=lambda item: (item.name, item.version)))


def _claim_unique(
    seen: dict[str, str],
    *,
    identity: str,
    kind: str,
    source: str,
) -> None:
    previous = seen.get(identity)
    if previous is not None:
        raise ValueError(
            f"duplicate {kind} {identity!r}: declared by {previous} and {source}"
        )
    seen[identity] = source


def discover_specs(
    kernels_root: Path,
    source_files: Iterable[str | Path],
) -> list[DiscoveredKernelSpec]:
    """Parse and validate only the explicit repository-relative spec inventory."""

    if not isinstance(kernels_root, Path):
        raise TypeError("kernels_root must be pathlib.Path")
    if kernels_root.is_symlink():
        raise ValueError(f"kernels root must not be a symlink: {kernels_root}")
    try:
        root = kernels_root.resolve(strict=True)
    except (FileNotFoundError, RuntimeError) as exc:
        raise ValueError(f"kernels root does not exist: {kernels_root}") from exc
    if not root.is_dir():
        raise ValueError(f"kernels root is not a directory: {kernels_root}")

    normalized: dict[str, Path] = {}
    for source in source_files:
        path, relative = _normalize_source(root, source)
        if relative in normalized:
            raise ValueError(f"duplicate declared spec path: {relative}")
        normalized[relative] = path

    discovered: list[DiscoveredKernelSpec] = []
    for relative in sorted(normalized):
        path = normalized[relative]
        raw = path.read_bytes()
        try:
            source_text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"{relative}: declaration source must be UTF-8") from exc
        spec, implementations = parse_kernel_declarations_source(
            source_text, filename=relative
        )
        _validate_spec_identity(spec, relative)
        implementations = _validate_implementations(spec, implementations, relative)
        discovered.append(
            DiscoveredKernelSpec(
                spec=spec,
                implementations=implementations,
                declaration_sha256="sha256:" + hashlib.sha256(raw).hexdigest(),
            )
        )

    qualified_names: dict[str, str] = {}
    builders: dict[str, str] = {}
    symbols: dict[str, str] = {}
    for item in discovered:
        source = item.spec.source
        _claim_unique(
            qualified_names,
            identity=item.qualified_name,
            kind="qualified operator",
            source=source,
        )
        for _label, identity in _builder_identities(item.spec):
            _claim_unique(builders, identity=identity, kind="builder", source=source)
        for label, identity in _symbol_identities(item.spec):
            if _NATIVE_SYMBOL.fullmatch(identity) is None:
                raise ValueError(f"{source}: {label} is not a native symbol identifier")
            _claim_unique(symbols, identity=identity, kind="symbol", source=source)

    for item in discovered:
        _validate_builder_locality(item.spec, item.spec.source)
    return sorted(discovered, key=lambda item: (item.qualified_name, item.spec.source))
