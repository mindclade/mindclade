"""Import-free parser for canonical operation-local ``spec.py`` declarations.

This module interprets a deliberately tiny Python AST subset.  It never imports
the operation being parsed and never compiles or executes its source.  Approved
``kernels.api`` imports are resolved against an explicit in-process whitelist;
all other names, calls, attributes, statements, and expression forms fail
closed.
"""

from __future__ import annotations

import ast
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum, EnumType
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import TypeAlias, cast


class LiteralAstError(ValueError):
    """A declarative source file contains syntax outside the approved subset."""


_MAX_SOURCE_BYTES = 1_048_576
_MAX_DEPTH = 64
_MAX_CONTAINER_ITEMS = 4_096
_DEFAULT_DECLARATION = "KERNEL_SPEC"
_SUPPORTED_SCHEMA_VERSIONS = frozenset({1})

_CONSTRUCTOR_NAMES = frozenset(
    {
        "Add",
        "And",
        "BackwardArgumentBinding",
        "BackwardSpec",
        "BoolLiteral",
        "Broadcastable",
        "CapabilityEnvelope",
        "CeilDiv",
        "CompileEnvironment",
        "CompositeAutogradSpec",
        "ConcatShape",
        "ConstantDType",
        "ConstantDevice",
        "DeviceCapabilities",
        "DeviceRef",
        "DimRef",
        "DimensionConstraint",
        "DTypeRef",
        "EffectSpec",
        "Eq",
        "FloatLiteral",
        "FloorDiv",
        "ForwardSpec",
        "GradientSpec",
        "GreaterEqual",
        "GreaterThan",
        "ImplementationSpec",
        "InitializationSpec",
        "InSet",
        "IntLiteral",
        "IsFinite",
        "KernelSpec",
        "LaunchContract",
        "LessEqual",
        "LessThan",
        "Maximum",
        "Minimum",
        "Modulo",
        "Multiply",
        "Not",
        "NotEqual",
        "NumericalEnvelope",
        "Or",
        "OutputSpec",
        "ProgramGroupSpec",
        "ProgramNodeSpec",
        "QualifiedCapability",
        "RankRef",
        "RoundUp",
        "RuntimeCompatibility",
        "SameAsInputDType",
        "SameAsInputDevice",
        "ScalarRef",
        "ScheduleSpec",
        "Select",
        "ShapeOf",
        "ShapePrefix",
        "ShapeTuple",
        "SpecializationSpec",
        "StringLiteral",
        "Subtract",
        "TensorTolerance",
        "TensorCapabilityConstraint",
        "WorkloadSpec",
        "WorkspaceSpec",
        "WorkspaceUseSpec",
    }
)
_ENUM_NAMES = frozenset(
    {
        "AutogradPolicy",
        "BackwardArgumentSource",
        "DeterminismClass",
        "ImplementationTier",
        "MissingGradientPolicy",
        "ScalarType",
        "WorkspaceAccess",
        "WorkspaceLifetime",
    }
)
_APPROVED_NAMES = _CONSTRUCTOR_NAMES | _ENUM_NAMES

LiteralValue: TypeAlias = None | bool | int | float | str
ContainerValue: TypeAlias = tuple[object, ...] | list[object] | dict[str, object]


@dataclass(frozen=True, slots=True)
class _ConstructorBinding:
    canonical_name: str
    constructor: type[object]


@dataclass(frozen=True, slots=True)
class _EnumBinding:
    canonical_name: str
    enum_type: EnumType


_Binding: TypeAlias = _ConstructorBinding | _EnumBinding


@lru_cache(maxsize=1)
def _approved_bindings() -> Mapping[str, _Binding]:
    # Importing the side-effect-free contract package is permitted.  The parsed
    # operation package and its spec.py module are never imported.
    import kernels.api as kernel_api

    bindings: dict[str, _Binding] = {}
    for name in sorted(_CONSTRUCTOR_NAMES):
        value = getattr(kernel_api, name, None)
        if not isinstance(value, type) or issubclass(value, Enum):
            raise RuntimeError(f"approved constructor {name!r} is missing from kernels.api")
        bindings[name] = _ConstructorBinding(name, value)
    for name in sorted(_ENUM_NAMES):
        value = getattr(kernel_api, name, None)
        if not isinstance(value, EnumType):
            raise RuntimeError(f"approved enum {name!r} is missing from kernels.api")
        bindings[name] = _EnumBinding(name, value)
    return MappingProxyType(bindings)


class _LiteralEvaluator:
    def __init__(
        self,
        *,
        filename: str,
        bindings: Mapping[str, _Binding],
        supported_versions: frozenset[int],
    ) -> None:
        self._filename = filename
        self._bindings = bindings
        self._supported_versions = supported_versions

    def fail(self, node: ast.AST, message: str) -> LiteralAstError:
        line = getattr(node, "lineno", 1)
        column = getattr(node, "col_offset", 0) + 1
        return LiteralAstError(f"{self._filename}:{line}:{column}: {message}")

    def evaluate(self, node: ast.expr, *, depth: int = 0) -> object:
        if depth > _MAX_DEPTH:
            raise self.fail(node, f"literal expression exceeds maximum depth {_MAX_DEPTH}")

        if isinstance(node, ast.Constant):
            value = node.value
            if value is None or isinstance(value, (bool, int, str)):
                return value
            if isinstance(value, float):
                if value != value or value in {float("inf"), float("-inf")}:
                    raise self.fail(node, "non-finite float literals are forbidden")
                return value
            raise self.fail(node, f"unsupported literal type {type(value).__name__}")

        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = self.evaluate(node.operand, depth=depth + 1)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise self.fail(node, "unary signs apply only to numeric literals")
            return value if isinstance(node.op, ast.UAdd) else -value

        if isinstance(node, ast.Tuple):
            self._check_container_size(node, node.elts)
            return tuple(self.evaluate(item, depth=depth + 1) for item in node.elts)

        if isinstance(node, ast.List):
            self._check_container_size(node, node.elts)
            return [self.evaluate(item, depth=depth + 1) for item in node.elts]

        if isinstance(node, ast.Dict):
            self._check_container_size(node, node.keys)
            result: dict[str, object] = {}
            for key_node, value_node in zip(node.keys, node.values, strict=True):
                if key_node is None:
                    raise self.fail(node, "dictionary unpacking is forbidden")
                key = self.evaluate(key_node, depth=depth + 1)
                if not isinstance(key, str):
                    raise self.fail(key_node, "declarative dictionary keys must be strings")
                if key in result:
                    raise self.fail(key_node, f"duplicate dictionary key {key!r}")
                result[key] = self.evaluate(value_node, depth=depth + 1)
            return result

        if isinstance(node, ast.Attribute):
            return self._enum_member(node)

        if isinstance(node, ast.Call):
            return self._constructor_call(node, depth=depth)

        if isinstance(node, ast.Name):
            binding = self._bindings.get(node.id)
            if binding is not None:
                raise self.fail(
                    node,
                    f"approved symbol {node.id!r} must be used as a constructor or enum member",
                )
            raise self.fail(node, f"unbound or runtime-dependent name {node.id!r}")

        raise self.fail(node, f"unsupported expression node {type(node).__name__}")

    def _check_container_size(self, node: ast.AST, values: object) -> None:
        if not isinstance(values, list) or len(values) > _MAX_CONTAINER_ITEMS:
            raise self.fail(node, f"container exceeds {_MAX_CONTAINER_ITEMS} items")

    def _enum_member(self, node: ast.Attribute) -> Enum:
        if not isinstance(node.value, ast.Name):
            raise self.fail(node, "dynamic or chained attribute access is forbidden")
        binding = self._bindings.get(node.value.id)
        if not isinstance(binding, _EnumBinding):
            raise self.fail(node, "attribute access is permitted only on an approved enum")
        try:
            return cast(Enum, binding.enum_type.__members__[node.attr])
        except KeyError as exc:
            raise self.fail(
                node,
                f"{binding.canonical_name} has no approved member {node.attr!r}",
            ) from exc

    def _constructor_call(self, node: ast.Call, *, depth: int) -> object:
        if not isinstance(node.func, ast.Name):
            raise self.fail(node.func, "constructor target must be one imported approved name")
        binding = self._bindings.get(node.func.id)
        if not isinstance(binding, _ConstructorBinding):
            raise self.fail(node.func, f"call target {node.func.id!r} is not an approved constructor")
        if node.args:
            raise self.fail(node, "declarative constructors accept keyword arguments only")
        if len(node.keywords) > _MAX_CONTAINER_ITEMS:
            raise self.fail(node, f"constructor exceeds {_MAX_CONTAINER_ITEMS} keyword arguments")

        values: dict[str, object] = {}
        for keyword in node.keywords:
            if keyword.arg is None:
                raise self.fail(keyword.value, "keyword unpacking is forbidden")
            if keyword.arg in values:
                raise self.fail(keyword.value, f"duplicate constructor field {keyword.arg!r}")
            values[keyword.arg] = self.evaluate(keyword.value, depth=depth + 1)
        try:
            value = binding.constructor(**values)
        except Exception as exc:
            raise self.fail(
                node,
                f"invalid {binding.canonical_name} declaration: {exc}",
            ) from exc
        self._check_schema_version(node, binding.canonical_name, value)
        return value

    def _check_schema_version(self, node: ast.AST, name: str, value: object) -> None:
        if not hasattr(value, "version"):
            return
        version = getattr(value, "version")
        if isinstance(version, bool) or not isinstance(version, int):
            raise self.fail(node, f"{name} version must be an integer")
        if version not in self._supported_versions:
            supported = ", ".join(str(item) for item in sorted(self._supported_versions))
            raise self.fail(
                node,
                f"unsupported {name} schema version {version}; supported versions: {supported}",
            )


def _module_bindings(tree: ast.Module, *, filename: str) -> tuple[Mapping[str, _Binding], list[ast.stmt]]:
    approved = _approved_bindings()
    local: dict[str, _Binding] = {}
    declarations: list[ast.stmt] = []

    for index, statement in enumerate(tree.body):
        if (
            index == 0
            and isinstance(statement, ast.Expr)
            and isinstance(statement.value, ast.Constant)
            and isinstance(statement.value.value, str)
        ):
            continue
        if isinstance(statement, ast.ImportFrom):
            if statement.level != 0:
                raise LiteralAstError(
                    f"{filename}:{statement.lineno}:{statement.col_offset + 1}: relative imports are forbidden"
                )
            if statement.module == "__future__":
                names = {alias.name for alias in statement.names}
                if names != {"annotations"} or any(alias.asname for alias in statement.names):
                    raise LiteralAstError(
                        f"{filename}:{statement.lineno}:{statement.col_offset + 1}: "
                        "only 'from __future__ import annotations' is approved"
                    )
                continue
            if statement.module != "kernels.api":
                raise LiteralAstError(
                    f"{filename}:{statement.lineno}:{statement.col_offset + 1}: "
                    "only explicit imports from kernels.api are approved"
                )
            for alias in statement.names:
                if alias.name == "*" or alias.name not in _APPROVED_NAMES:
                    raise LiteralAstError(
                        f"{filename}:{statement.lineno}:{statement.col_offset + 1}: "
                        f"unsupported kernels.api import {alias.name!r}"
                    )
                local_name = alias.asname or alias.name
                if local_name in local:
                    raise LiteralAstError(
                        f"{filename}:{statement.lineno}:{statement.col_offset + 1}: "
                        f"duplicate imported binding {local_name!r}"
                    )
                local[local_name] = approved[alias.name]
            continue
        if isinstance(statement, ast.Import):
            raise LiteralAstError(
                f"{filename}:{statement.lineno}:{statement.col_offset + 1}: arbitrary imports are forbidden"
            )
        declarations.append(statement)
    return MappingProxyType(local), declarations


def _declaration_value(
    statements: list[ast.stmt],
    *,
    filename: str,
    declaration_name: str,
    bindings: Mapping[str, _Binding],
) -> ast.expr:
    if len(statements) != 1:
        raise LiteralAstError(
            f"{filename}: canonical spec.py must contain exactly one {declaration_name} declaration"
        )
    statement = statements[0]
    if isinstance(statement, ast.Assign):
        if len(statement.targets) != 1 or not isinstance(statement.targets[0], ast.Name):
            raise LiteralAstError(
                f"{filename}:{statement.lineno}:{statement.col_offset + 1}: "
                "declaration target must be one simple name"
            )
        target = statement.targets[0]
        value = statement.value
    elif isinstance(statement, ast.AnnAssign):
        if not isinstance(statement.target, ast.Name) or statement.value is None:
            raise LiteralAstError(
                f"{filename}:{statement.lineno}:{statement.col_offset + 1}: "
                "annotated declaration target must be one initialized simple name"
            )
        if not isinstance(statement.annotation, ast.Name):
            raise LiteralAstError(
                f"{filename}:{statement.lineno}:{statement.col_offset + 1}: "
                "declaration annotation must be an imported contract name"
            )
        annotation_binding = bindings.get(statement.annotation.id)
        if (
            not isinstance(annotation_binding, _ConstructorBinding)
            or annotation_binding.canonical_name != "KernelSpec"
        ):
            raise LiteralAstError(
                f"{filename}:{statement.annotation.lineno}:"
                f"{statement.annotation.col_offset + 1}: declaration annotation must "
                "resolve to an explicitly imported kernels.api.KernelSpec binding"
            )
        target = statement.target
        value = statement.value
    else:
        raise LiteralAstError(
            f"{filename}:{statement.lineno}:{statement.col_offset + 1}: "
            f"unsupported top-level statement {type(statement).__name__}"
        )
    if target.id != declaration_name:
        raise LiteralAstError(
            f"{filename}:{target.lineno}:{target.col_offset + 1}: "
            f"declaration must be named {declaration_name!r}, got {target.id!r}"
        )
    return value


def _validated_versions(versions: frozenset[int]) -> frozenset[int]:
    if not versions or any(isinstance(item, bool) or not isinstance(item, int) or item < 1 for item in versions):
        raise ValueError("supported_versions must contain positive integer schema versions")
    return versions


def parse_literal_source(
    source: str,
    *,
    filename: str = "<spec.py>",
    declaration_name: str = _DEFAULT_DECLARATION,
    supported_versions: frozenset[int] = _SUPPORTED_SCHEMA_VERSIONS,
) -> object:
    """Parse one declarative assignment without importing or executing it."""

    if not isinstance(source, str):
        raise TypeError("source must be a UTF-8 decoded string")
    if len(source.encode("utf-8")) > _MAX_SOURCE_BYTES:
        raise LiteralAstError(f"{filename}: source exceeds {_MAX_SOURCE_BYTES} bytes")
    if "\x00" in source:
        raise LiteralAstError(f"{filename}: source contains a null byte")
    if not declaration_name.isidentifier() or declaration_name.startswith("_"):
        raise ValueError("declaration_name must be a public Python identifier")
    versions = _validated_versions(supported_versions)
    try:
        tree = ast.parse(source, filename=filename, mode="exec", type_comments=False)
    except SyntaxError as exc:
        line = exc.lineno or 1
        column = exc.offset or 1
        raise LiteralAstError(f"{filename}:{line}:{column}: invalid Python syntax: {exc.msg}") from exc
    bindings, statements = _module_bindings(tree, filename=filename)
    value_node = _declaration_value(
        statements,
        filename=filename,
        declaration_name=declaration_name,
        bindings=bindings,
    )
    return _LiteralEvaluator(
        filename=filename,
        bindings=bindings,
        supported_versions=versions,
    ).evaluate(value_node)


def parse_kernel_spec_source(
    source: str,
    *,
    filename: str = "<spec.py>",
    supported_versions: frozenset[int] = _SUPPORTED_SCHEMA_VERSIONS,
):
    """Parse and require one canonical :class:`kernels.api.KernelSpec`."""

    from kernels.api import KernelSpec

    value = parse_literal_source(
        source,
        filename=filename,
        supported_versions=supported_versions,
    )
    if not isinstance(value, KernelSpec):
        raise LiteralAstError(f"{filename}: KERNEL_SPEC must construct kernels.api.KernelSpec")
    return value


def parse_literal_file(
    path: Path,
    *,
    declaration_name: str = _DEFAULT_DECLARATION,
    supported_versions: frozenset[int] = _SUPPORTED_SCHEMA_VERSIONS,
) -> object:
    """Read and parse one regular, non-symlink canonical ``spec.py`` file."""

    if not isinstance(path, Path):
        raise TypeError("path must be pathlib.Path")
    if path.name != "spec.py":
        raise LiteralAstError(f"{path}: canonical declaration filename must be spec.py")
    if path.is_symlink():
        raise LiteralAstError(f"{path}: declaration file must not be a symlink")
    if not path.is_file():
        raise LiteralAstError(f"{path}: declaration file must be a regular file")
    raw = path.read_bytes()
    if len(raw) > _MAX_SOURCE_BYTES:
        raise LiteralAstError(f"{path}: source exceeds {_MAX_SOURCE_BYTES} bytes")
    try:
        source = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise LiteralAstError(f"{path}: declaration source must be UTF-8") from exc
    return parse_literal_source(
        source,
        filename=str(path),
        declaration_name=declaration_name,
        supported_versions=supported_versions,
    )


def parse_kernel_spec_file(
    path: Path,
    *,
    supported_versions: frozenset[int] = _SUPPORTED_SCHEMA_VERSIONS,
):
    """Read, parse, and require one canonical KernelSpec file."""

    from kernels.api import KernelSpec

    value = parse_literal_file(path, supported_versions=supported_versions)
    if not isinstance(value, KernelSpec):
        raise LiteralAstError(f"{path}: KERNEL_SPEC must construct kernels.api.KernelSpec")
    return value
