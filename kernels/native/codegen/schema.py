from __future__ import annotations

from dataclasses import dataclass
import re

_MAX_SCHEMA_LENGTH = 2048
_MAX_ARGUMENTS = 32
_OPERATOR_NAME = r"[a-z][a-z0-9_]{0,63}"
_ARGUMENT_NAME = r"[A-Za-z_][A-Za-z0-9_]{0,63}"
_SCHEMA = re.compile(
    rf"^(?P<name>{_OPERATOR_NAME})\((?P<args>[^()]*)\) -> (?P<ret>Tensor)$"
)
_ARGUMENT = re.compile(rf"^(?P<kind>Tensor|float|int|bool) (?P<name>{_ARGUMENT_NAME})$")

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
class ParsedSchema:
    name: str
    args: tuple[Argument, ...]
    return_kind: str

    @property
    def canonical(self) -> str:
        arguments = ", ".join(f"{argument.kind} {argument.name}" for argument in self.args)
        return f"{self.name}({arguments}) -> {self.return_kind}"

    @property
    def cpp_return_type(self) -> str:
        return "torch::stable::Tensor"

    @property
    def cpp_parameters(self) -> str:
        return ", ".join(f"{argument.cpp_type} {argument.name}" for argument in self.args)


def parse_schema(schema: str) -> ParsedSchema:
    """Parse the deliberately small, stable native Torch schema subset.

    The parser accepts only its canonical spelling. Defaults, aliases, lists,
    optionals, overloads, multiple returns, and namespaced definitions require
    an explicit ABI revision rather than permissive parsing here.
    """

    if not isinstance(schema, str) or not schema or len(schema) > _MAX_SCHEMA_LENGTH:
        raise ValueError("operator schema must be a nonempty string of at most 2048 characters")
    if any(ord(character) < 32 for character in schema):
        raise ValueError("operator schema must not contain control characters")
    match = _SCHEMA.fullmatch(schema)
    if match is None:
        raise ValueError(f"invalid or unsupported operator schema: {schema!r}")

    raw_arguments = match.group("args")
    parts = [] if not raw_arguments else raw_arguments.split(", ")
    if len(parts) > _MAX_ARGUMENTS:
        raise ValueError(f"operator schema exceeds the {_MAX_ARGUMENTS}-argument limit")

    arguments: list[Argument] = []
    names: set[str] = set()
    for raw in parts:
        argument_match = _ARGUMENT.fullmatch(raw)
        if argument_match is None:
            raise ValueError(f"unsupported argument syntax {raw!r} in {schema!r}")
        name = argument_match.group("name")
        if name in names:
            raise ValueError(f"duplicate argument name {name!r} in {schema!r}")
        names.add(name)
        arguments.append(Argument(argument_match.group("kind"), name))

    parsed = ParsedSchema(match.group("name"), tuple(arguments), match.group("ret"))
    if parsed.canonical != schema:
        raise ValueError(f"operator schema is not canonical: expected {parsed.canonical!r}")
    return parsed
