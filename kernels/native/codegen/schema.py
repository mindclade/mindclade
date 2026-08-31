"""Bounded parser for the Mindclade PyTorch Stable-ABI schema subset."""

from __future__ import annotations

from dataclasses import dataclass
import re

_MAX_SCHEMA_LENGTH = 4096
_MAX_ARGUMENTS = 64
_MAX_RETURNS = 16
_OPERATOR_NAME = r"_?[a-z][a-z0-9_]{0,62}"
_VALUE_NAME = r"[A-Za-z_][A-Za-z0-9_]{0,63}"
_SCHEMA = re.compile(
    rf"^(?P<name>{_OPERATOR_NAME})\((?P<args>[^()]*)\) -> (?P<returns>.+)$"
)
_ARGUMENT = re.compile(rf"^(?P<kind>Tensor|float|int|bool) (?P<name>{_VALUE_NAME})$")
_RETURN = re.compile(rf"^(?P<kind>Tensor) (?P<name>{_VALUE_NAME})$")

_CPP_TYPES = {
    "Tensor": "const torch::stable::Tensor&",
    "float": "double",
    "int": "int64_t",
    "bool": "bool",
}


@dataclass(frozen=True, slots=True)
class Argument:
    kind: str
    name: str

    @property
    def cpp_type(self) -> str:
        return _CPP_TYPES[self.kind]


@dataclass(frozen=True, slots=True)
class Return:
    kind: str
    name: str

    @property
    def cpp_type(self) -> str:
        return "torch::stable::Tensor"


@dataclass(frozen=True, slots=True)
class ParsedSchema:
    name: str
    args: tuple[Argument, ...]
    returns: tuple[Return, ...]

    @property
    def canonical(self) -> str:
        arguments = ", ".join(f"{item.kind} {item.name}" for item in self.args)
        returned = ", ".join(f"{item.kind} {item.name}" for item in self.returns)
        if len(self.returns) > 1:
            returned = f"({returned})"
        return f"{self.name}({arguments}) -> {returned}"

    @property
    def cpp_return_type(self) -> str:
        if len(self.returns) == 1:
            return self.returns[0].cpp_type
        members = ", ".join(item.cpp_type for item in self.returns)
        return f"torch::stable::std::tuple<{members}>"

    @property
    def cpp_parameters(self) -> str:
        return ", ".join(f"{item.cpp_type} {item.name}" for item in self.args)

    @property
    def argument_names(self) -> tuple[str, ...]:
        return tuple(item.name for item in self.args)

    @property
    def return_names(self) -> tuple[str, ...]:
        return tuple(item.name for item in self.returns)


def _bounded_parts(value: str, *, maximum: int, label: str) -> list[str]:
    parts = [] if not value else value.split(", ")
    if not parts or len(parts) > maximum:
        raise ValueError(f"{label} must contain 1-{maximum} canonical entries")
    return parts


def parse_schema(schema: str) -> ParsedSchema:
    """Parse only the explicitly supported canonical Stable-ABI schema subset."""

    if not isinstance(schema, str) or not schema or len(schema) > _MAX_SCHEMA_LENGTH:
        raise ValueError("operator schema must be a nonempty bounded string")
    if any(ord(character) < 32 for character in schema):
        raise ValueError("operator schema must not contain control characters")
    match = _SCHEMA.fullmatch(schema)
    if match is None:
        raise ValueError(f"invalid or unsupported operator schema: {schema!r}")

    raw_arguments = match.group("args")
    argument_parts = [] if not raw_arguments else raw_arguments.split(", ")
    if len(argument_parts) > _MAX_ARGUMENTS:
        raise ValueError(f"operator schema exceeds the {_MAX_ARGUMENTS}-argument limit")
    arguments: list[Argument] = []
    names: set[str] = set()
    for raw in argument_parts:
        parsed = _ARGUMENT.fullmatch(raw)
        if parsed is None:
            raise ValueError(f"unsupported argument syntax {raw!r} in {schema!r}")
        name = parsed.group("name")
        if name in names:
            raise ValueError(f"duplicate argument name {name!r} in {schema!r}")
        names.add(name)
        arguments.append(Argument(parsed.group("kind"), name))

    raw_returns = match.group("returns")
    if raw_returns.startswith("(") and raw_returns.endswith(")"):
        return_parts = _bounded_parts(
            raw_returns[1:-1], maximum=_MAX_RETURNS, label="tuple return"
        )
        if len(return_parts) < 2:
            raise ValueError("parenthesized return must contain at least two values")
    else:
        return_parts = [raw_returns]
    returns: list[Return] = []
    return_names: set[str] = set()
    for raw in return_parts:
        parsed = _RETURN.fullmatch(raw)
        if parsed is None:
            raise ValueError(f"unsupported return syntax {raw!r} in {schema!r}")
        name = parsed.group("name")
        if name in return_names:
            raise ValueError(f"duplicate return name {name!r} in {schema!r}")
        return_names.add(name)
        returns.append(Return(parsed.group("kind"), name))

    result = ParsedSchema(match.group("name"), tuple(arguments), tuple(returns))
    if result.canonical != schema:
        raise ValueError(f"operator schema is not canonical: expected {result.canonical!r}")
    return result
