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
_ARGUMENT = re.compile(rf"^(?P<kind>Tensor\?|Tensor|float|int|bool) (?P<name>{_VALUE_NAME})$")
_RETURN = re.compile(rf"^(?P<kind>Tensor\?|Tensor) (?P<name>{_VALUE_NAME})$")

_CPP_ARGUMENT_TYPES = {
    "Tensor": "const torch::stable::Tensor&",
    "Tensor?": "const std::optional<torch::stable::Tensor>&",
    "float": "double",
    "int": "int64_t",
    "bool": "bool",
}

_CPP_RETURN_TYPES = {
    "Tensor": "torch::stable::Tensor",
    "Tensor?": "std::optional<torch::stable::Tensor>",
}

# Keep this policy static: generated surfaces must not change because a host
# Python release adds a keyword. This is the Python 3.11 keyword set plus the
# complete C++17 keyword set, including alternative operator tokens.
_PYTHON_RESERVED_NAMES = frozenset(
    {
        "False", "None", "True", "and", "as", "assert", "async", "await",
        "break", "class", "continue", "def", "del", "elif", "else", "except",
        "finally", "for", "from", "global", "if", "import", "in", "is",
        "lambda", "nonlocal", "not", "or", "pass", "raise", "return", "try",
        "while", "with", "yield",
    }
)
_CPP17_RESERVED_NAMES = frozenset(
    {
        "alignas", "alignof", "and", "and_eq", "asm", "auto", "bitand",
        "bitor", "bool", "break", "case", "catch", "char", "char16_t",
        "char32_t", "class", "compl", "const", "constexpr", "const_cast",
        "continue", "decltype", "default", "delete", "do", "double",
        "dynamic_cast", "else", "enum", "explicit", "export", "extern",
        "false", "float", "for", "friend", "goto", "if", "inline", "int",
        "long", "mutable", "namespace", "new", "noexcept", "not", "not_eq",
        "nullptr", "operator", "or", "or_eq", "private", "protected", "public",
        "register", "reinterpret_cast", "return", "short", "signed", "sizeof",
        "static", "static_assert", "static_cast", "struct", "switch", "template",
        "this", "thread_local", "throw", "true", "try", "typedef", "typeid",
        "typename", "union", "unsigned", "using", "virtual", "void", "volatile",
        "wchar_t", "while", "xor", "xor_eq",
    }
)
_RESERVED_NAMES = _PYTHON_RESERVED_NAMES | _CPP17_RESERVED_NAMES


def _reject_reserved_name(name: str, *, label: str, schema: str) -> None:
    if name in _RESERVED_NAMES:
        raise ValueError(f"reserved {label} name {name!r} in {schema!r}")


class _ValueType:
    """Shared normalized type predicates for schema arguments and returns."""

    kind: str

    @property
    def normalized_kind(self) -> str:
        return self.kind.removesuffix("?")

    @property
    def is_optional(self) -> bool:
        return self.kind.endswith("?")

    @property
    def type_identity(self) -> tuple[str, bool]:
        return (self.normalized_kind, self.is_optional)

    @property
    def is_tensor(self) -> bool:
        return self.normalized_kind == "Tensor"

    @property
    def is_bool(self) -> bool:
        return self.normalized_kind == "bool"

    @property
    def is_scalar(self) -> bool:
        return self.normalized_kind in {"float", "int", "bool"}


@dataclass(frozen=True, slots=True)
class Argument(_ValueType):
    kind: str
    name: str

    @property
    def cpp_type(self) -> str:
        return _CPP_ARGUMENT_TYPES[self.kind]


@dataclass(frozen=True, slots=True)
class Return(_ValueType):
    kind: str
    name: str

    @property
    def cpp_type(self) -> str:
        return _CPP_RETURN_TYPES[self.kind]


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
        return f"std::tuple<{members}>"

    @property
    def cpp_parameters(self) -> str:
        return ", ".join(f"{item.cpp_type} {item.name}" for item in self.args)

    @property
    def argument_names(self) -> tuple[str, ...]:
        return tuple(item.name for item in self.args)

    @property
    def return_names(self) -> tuple[str, ...]:
        return tuple(item.name for item in self.returns)

    def argument_by_name(self, name: str) -> Argument:
        """Return one exact named argument without changing schema ABI order."""

        for argument in self.args:
            if argument.name == name:
                return argument
        raise KeyError(f"schema {self.name!r} has no argument named {name!r}")

    def return_by_name(self, name: str) -> Return:
        """Return one exact named result without changing schema ABI order."""

        for returned in self.returns:
            if returned.name == name:
                return returned
        raise KeyError(f"schema {self.name!r} has no return named {name!r}")

    def has_exact_signature(self, other: object) -> bool:
        """Compare ordered named I/O types while intentionally ignoring op names."""

        if not isinstance(other, ParsedSchema):
            return False
        arguments = tuple((item.name, item.type_identity) for item in self.args)
        other_arguments = tuple((item.name, item.type_identity) for item in other.args)
        returns = tuple((item.name, item.type_identity) for item in self.returns)
        other_returns = tuple((item.name, item.type_identity) for item in other.returns)
        return arguments == other_arguments and returns == other_returns


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
    operator_name = match.group("name")
    _reject_reserved_name(operator_name, label="operator", schema=schema)

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
        _reject_reserved_name(name, label="argument", schema=schema)
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
        _reject_reserved_name(name, label="return", schema=schema)
        if name in return_names:
            raise ValueError(f"duplicate return name {name!r} in {schema!r}")
        return_names.add(name)
        returns.append(Return(parsed.group("kind"), name))

    result = ParsedSchema(operator_name, tuple(arguments), tuple(returns))
    if result.canonical != schema:
        raise ValueError(f"operator schema is not canonical: expected {result.canonical!r}")
    return result
