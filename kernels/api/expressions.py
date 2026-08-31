"""Restricted, deterministic expressions for kernel metadata contracts.

The expression language is data, not executable Python.  It deliberately has no
callback, attribute lookup, import, ``eval``, or ``exec`` facility.  The same
validated tree drives build manifests, Python boundary validators, native host
validators, FakeTensor metadata, and capability explanations.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
import hashlib
import json
import math
import re
from types import MappingProxyType
from typing import ClassVar, Generic, TypeAlias, TypeVar, cast

from kernels.api.errors import (
    ExpressionCodegenError,
    ExpressionDecodeError,
    ExpressionEvaluationError,
    ExpressionValidationError,
)

JsonScalar: TypeAlias = None | bool | int | float | str
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
ScalarValue: TypeAlias = bool | int | float | str

_MAX_INT = 2**63 - 1
_MIN_INT = -(2**63)
_MAX_STRING_LENGTH = 256
_MAX_JSON_LENGTH = 1_048_576
_MAX_DEPTH = 64
_MAX_OPERANDS = 4_096
_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")


class ExprDomain(StrEnum):
    INT = "int"
    BOOL = "bool"
    FLOAT = "float"
    STRING = "string"
    DTYPE = "dtype"
    DEVICE = "device"


class ScalarType(StrEnum):
    INT = "int"
    BOOL = "bool"
    FLOAT = "float"
    STRING = "string"


_ValueT_co = TypeVar("_ValueT_co", covariant=True)
_SelectT = TypeVar("_SelectT")


class Expr(Generic[_ValueT_co], ABC):
    """Base class for every serializable expression node."""

    @property
    @abstractmethod
    def domain(self) -> ExprDomain:
        """Return the statically validated value domain."""

    @abstractmethod
    def evaluate(self, context: EvaluationContext) -> _ValueT_co:
        """Evaluate deterministically against validated metadata."""

    @abstractmethod
    def to_data(self) -> dict[str, JsonValue]:
        """Return the canonical JSON-compatible node object."""

    @abstractmethod
    def render(self) -> str:
        """Render a stable, human-readable explanation."""

    @abstractmethod
    def to_python(self) -> str:
        """Generate a side-effect-free Python expression string."""

    @abstractmethod
    def to_native_host(self) -> str:
        """Generate an expression for the native host-validator subset."""

    def canonical_json(self) -> str:
        return canonical_json(self)

    def digest(self) -> str:
        return content_digest(self)


IntExpr: TypeAlias = Expr[int]
BoolExpr: TypeAlias = Expr[bool]
DTypeExpr: TypeAlias = Expr[str]
DeviceExpr: TypeAlias = Expr[str]
ShapeExpr: TypeAlias = tuple[IntExpr, ...]


def _validated_name(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or _NAME.fullmatch(value) is None:
        raise ExpressionValidationError(
            f"{field_name} must be a valid declarative argument identifier"
        )
    return value


def _validated_int(value: object, *, field_name: str, nonnegative: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ExpressionValidationError(f"{field_name} must be an integer, not bool")
    if value < _MIN_INT or value > _MAX_INT:
        raise ExpressionValidationError(f"{field_name} must fit a signed 64-bit integer")
    if nonnegative and value < 0:
        raise ExpressionValidationError(f"{field_name} must be nonnegative")
    return value


def _validated_text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value or len(value) > _MAX_STRING_LENGTH:
        raise ExpressionValidationError(
            f"{field_name} must be a nonempty string of at most {_MAX_STRING_LENGTH} characters"
        )
    return value


def _validated_float(value: object, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, float) or not math.isfinite(value):
        raise ExpressionValidationError(f"{field_name} must be a finite float")
    return value


def _validated_scalar(value: object, *, field_name: str) -> ScalarValue:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return _validated_int(value, field_name=field_name)
    if isinstance(value, float):
        return _validated_float(value, field_name=field_name)
    if isinstance(value, str):
        if len(value) > _MAX_STRING_LENGTH:
            raise ExpressionValidationError(
                f"{field_name} must be at most {_MAX_STRING_LENGTH} characters"
            )
        return value
    raise ExpressionValidationError(f"{field_name} must be a bool, int, finite float, or string")


def _scalar_domain(value: ScalarValue) -> ExprDomain:
    if isinstance(value, bool):
        return ExprDomain.BOOL
    if isinstance(value, int):
        return ExprDomain.INT
    if isinstance(value, float):
        return ExprDomain.FLOAT
    return ExprDomain.STRING


def _require_expression(value: object, *, field_name: str) -> Expr[object]:
    if not isinstance(value, Expr):
        raise ExpressionValidationError(f"{field_name} must be an expression node")
    return value


def _require_domain(value: object, domain: ExprDomain, *, field_name: str) -> Expr[object]:
    expression = _require_expression(value, field_name=field_name)
    if expression.domain != domain:
        raise ExpressionValidationError(
            f"{field_name} must have {domain.value} domain, got {expression.domain.value}"
        )
    return expression


def _json_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=True)


def _cpp_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=True)


def _lookup_tensor(context: EvaluationContext, argument: str) -> TensorMetadata:
    try:
        return context.tensors[argument]
    except KeyError as exc:
        raise ExpressionEvaluationError(f"tensor metadata is missing argument {argument!r}") from exc


def _lookup_scalar(context: EvaluationContext, argument: str, expected: ScalarType) -> ScalarValue:
    try:
        value = context.scalars[argument]
    except KeyError as exc:
        raise ExpressionEvaluationError(f"scalar metadata is missing argument {argument!r}") from exc
    actual = _scalar_domain(value)
    expected_domain = ExprDomain(expected.value)
    if actual != expected_domain:
        raise ExpressionEvaluationError(
            f"scalar {argument!r} must be {expected.value}, got {actual.value}"
        )
    return value


@dataclass(frozen=True, slots=True)
class TensorMetadata:
    shape: tuple[int, ...]
    dtype: str
    device: str

    def __post_init__(self) -> None:
        if not isinstance(self.shape, tuple):
            raise ExpressionValidationError("tensor shape must be a tuple")
        for axis, dimension in enumerate(self.shape):
            _validated_int(dimension, field_name=f"shape[{axis}]", nonnegative=True)
        _validated_text(self.dtype, field_name="dtype")
        _validated_text(self.device, field_name="device")


@dataclass(frozen=True, slots=True)
class EvaluationContext:
    tensors: Mapping[str, TensorMetadata]
    scalars: Mapping[str, ScalarValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.tensors, Mapping):
            raise ExpressionValidationError("tensors must be a mapping")
        if not isinstance(self.scalars, Mapping):
            raise ExpressionValidationError("scalars must be a mapping")
        tensors: dict[str, TensorMetadata] = {}
        for name, metadata in sorted(self.tensors.items()):
            _validated_name(name, field_name="tensor argument")
            if not isinstance(metadata, TensorMetadata):
                raise ExpressionValidationError(f"tensor {name!r} must contain TensorMetadata")
            tensors[name] = metadata
        scalars: dict[str, ScalarValue] = {}
        for name, value in sorted(self.scalars.items()):
            _validated_name(name, field_name="scalar argument")
            scalars[name] = _validated_scalar(value, field_name=f"scalar {name!r}")
        object.__setattr__(self, "tensors", MappingProxyType(tensors))
        object.__setattr__(self, "scalars", MappingProxyType(scalars))


@dataclass(frozen=True, slots=True)
class IntLiteral(Expr[int]):
    value: int

    def __post_init__(self) -> None:
        _validated_int(self.value, field_name="integer literal")

    @property
    def domain(self) -> ExprDomain:
        return ExprDomain.INT

    def evaluate(self, context: EvaluationContext) -> int:
        del context
        return self.value

    def to_data(self) -> dict[str, JsonValue]:
        return {"node": "int_literal", "value": self.value}

    def render(self) -> str:
        return str(self.value)

    def to_python(self) -> str:
        return str(self.value)

    def to_native_host(self) -> str:
        return f"INT64_C({self.value})" if self.value >= 0 else f"-INT64_C({-self.value})"


@dataclass(frozen=True, slots=True)
class BoolLiteral(Expr[bool]):
    value: bool

    def __post_init__(self) -> None:
        if not isinstance(self.value, bool):
            raise ExpressionValidationError("boolean literal must be bool")

    @property
    def domain(self) -> ExprDomain:
        return ExprDomain.BOOL

    def evaluate(self, context: EvaluationContext) -> bool:
        del context
        return self.value

    def to_data(self) -> dict[str, JsonValue]:
        return {"node": "bool_literal", "value": self.value}

    def render(self) -> str:
        return "true" if self.value else "false"

    def to_python(self) -> str:
        return "True" if self.value else "False"

    def to_native_host(self) -> str:
        return "true" if self.value else "false"


@dataclass(frozen=True, slots=True)
class FloatLiteral(Expr[float]):
    value: float

    def __post_init__(self) -> None:
        _validated_float(self.value, field_name="float literal")

    @property
    def domain(self) -> ExprDomain:
        return ExprDomain.FLOAT

    def evaluate(self, context: EvaluationContext) -> float:
        del context
        return self.value

    def to_data(self) -> dict[str, JsonValue]:
        return {"node": "float_literal", "value": self.value}

    def render(self) -> str:
        return repr(self.value)

    def to_python(self) -> str:
        return repr(self.value)

    def to_native_host(self) -> str:
        return repr(self.value)


@dataclass(frozen=True, slots=True)
class StringLiteral(Expr[str]):
    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str) or len(self.value) > _MAX_STRING_LENGTH:
            raise ExpressionValidationError(
                f"string literal must be a string of at most {_MAX_STRING_LENGTH} characters"
            )

    @property
    def domain(self) -> ExprDomain:
        return ExprDomain.STRING

    def evaluate(self, context: EvaluationContext) -> str:
        del context
        return self.value

    def to_data(self) -> dict[str, JsonValue]:
        return {"node": "string_literal", "value": self.value}

    def render(self) -> str:
        return _json_string(self.value)

    def to_python(self) -> str:
        return _json_string(self.value)

    def to_native_host(self) -> str:
        return _cpp_string(self.value)


@dataclass(frozen=True, slots=True)
class DimRef(Expr[int]):
    argument: str
    axis: int

    def __post_init__(self) -> None:
        _validated_name(self.argument, field_name="dimension argument")
        _validated_int(self.axis, field_name="dimension axis")

    @property
    def domain(self) -> ExprDomain:
        return ExprDomain.INT

    def evaluate(self, context: EvaluationContext) -> int:
        metadata = _lookup_tensor(context, self.argument)
        try:
            return metadata.shape[self.axis]
        except IndexError as exc:
            raise ExpressionEvaluationError(
                f"axis {self.axis} is outside rank {len(metadata.shape)} for {self.argument!r}"
            ) from exc

    def to_data(self) -> dict[str, JsonValue]:
        return {"argument": self.argument, "axis": self.axis, "node": "dim_ref"}

    def render(self) -> str:
        return f"dim({self.argument}, {self.axis})"

    def to_python(self) -> str:
        return f"metadata[{_json_string(self.argument)}].shape[{self.axis}]"

    def to_native_host(self) -> str:
        return f"metadata.dim({_cpp_string(self.argument)}, {self.axis})"


@dataclass(frozen=True, slots=True)
class RankRef(Expr[int]):
    argument: str

    def __post_init__(self) -> None:
        _validated_name(self.argument, field_name="rank argument")

    @property
    def domain(self) -> ExprDomain:
        return ExprDomain.INT

    def evaluate(self, context: EvaluationContext) -> int:
        return len(_lookup_tensor(context, self.argument).shape)

    def to_data(self) -> dict[str, JsonValue]:
        return {"argument": self.argument, "node": "rank_ref"}

    def render(self) -> str:
        return f"rank({self.argument})"

    def to_python(self) -> str:
        return f"len(metadata[{_json_string(self.argument)}].shape)"

    def to_native_host(self) -> str:
        return f"metadata.rank({_cpp_string(self.argument)})"


@dataclass(frozen=True, slots=True)
class DTypeRef(Expr[str]):
    argument: str

    def __post_init__(self) -> None:
        _validated_name(self.argument, field_name="dtype argument")

    @property
    def domain(self) -> ExprDomain:
        return ExprDomain.DTYPE

    def evaluate(self, context: EvaluationContext) -> str:
        return _lookup_tensor(context, self.argument).dtype

    def to_data(self) -> dict[str, JsonValue]:
        return {"argument": self.argument, "node": "dtype_ref"}

    def render(self) -> str:
        return f"dtype({self.argument})"

    def to_python(self) -> str:
        return f"metadata[{_json_string(self.argument)}].dtype"

    def to_native_host(self) -> str:
        return f"metadata.dtype({_cpp_string(self.argument)})"


@dataclass(frozen=True, slots=True)
class DeviceRef(Expr[str]):
    argument: str

    def __post_init__(self) -> None:
        _validated_name(self.argument, field_name="device argument")

    @property
    def domain(self) -> ExprDomain:
        return ExprDomain.DEVICE

    def evaluate(self, context: EvaluationContext) -> str:
        return _lookup_tensor(context, self.argument).device

    def to_data(self) -> dict[str, JsonValue]:
        return {"argument": self.argument, "node": "device_ref"}

    def render(self) -> str:
        return f"device({self.argument})"

    def to_python(self) -> str:
        return f"metadata[{_json_string(self.argument)}].device"

    def to_native_host(self) -> str:
        return f"metadata.device({_cpp_string(self.argument)})"


@dataclass(frozen=True, slots=True)
class SameAsInputDType(DTypeRef):
    def to_data(self) -> dict[str, JsonValue]:
        return {"argument": self.argument, "node": "same_as_input_dtype"}

    def render(self) -> str:
        return f"same_dtype({self.argument})"


@dataclass(frozen=True, slots=True)
class SameAsInputDevice(DeviceRef):
    def to_data(self) -> dict[str, JsonValue]:
        return {"argument": self.argument, "node": "same_as_input_device"}

    def render(self) -> str:
        return f"same_device({self.argument})"


@dataclass(frozen=True, slots=True)
class ConstantDType(Expr[str]):
    value: str

    def __post_init__(self) -> None:
        _validated_text(self.value, field_name="constant dtype")

    @property
    def domain(self) -> ExprDomain:
        return ExprDomain.DTYPE

    def evaluate(self, context: EvaluationContext) -> str:
        del context
        return self.value

    def to_data(self) -> dict[str, JsonValue]:
        return {"node": "constant_dtype", "value": self.value}

    def render(self) -> str:
        return f"dtype({_json_string(self.value)})"

    def to_python(self) -> str:
        return _json_string(self.value)

    def to_native_host(self) -> str:
        return _cpp_string(self.value)


@dataclass(frozen=True, slots=True)
class ConstantDevice(Expr[str]):
    value: str

    def __post_init__(self) -> None:
        _validated_text(self.value, field_name="constant device")

    @property
    def domain(self) -> ExprDomain:
        return ExprDomain.DEVICE

    def evaluate(self, context: EvaluationContext) -> str:
        del context
        return self.value

    def to_data(self) -> dict[str, JsonValue]:
        return {"node": "constant_device", "value": self.value}

    def render(self) -> str:
        return f"device({_json_string(self.value)})"

    def to_python(self) -> str:
        return _json_string(self.value)

    def to_native_host(self) -> str:
        return _cpp_string(self.value)


@dataclass(frozen=True, slots=True)
class ScalarRef(Expr[ScalarValue]):
    argument: str
    value_type: ScalarType

    def __post_init__(self) -> None:
        _validated_name(self.argument, field_name="scalar argument")
        if not isinstance(self.value_type, ScalarType):
            raise ExpressionValidationError("scalar value_type must be a ScalarType")

    @property
    def domain(self) -> ExprDomain:
        return ExprDomain(self.value_type.value)

    def evaluate(self, context: EvaluationContext) -> ScalarValue:
        return _lookup_scalar(context, self.argument, self.value_type)

    def to_data(self) -> dict[str, JsonValue]:
        return {
            "argument": self.argument,
            "node": "scalar_ref",
            "value_type": self.value_type.value,
        }

    def render(self) -> str:
        return f"scalar({self.argument}: {self.value_type.value})"

    def to_python(self) -> str:
        return f"scalars[{_json_string(self.argument)}]"

    def to_native_host(self) -> str:
        return f"metadata.scalar_{self.value_type.value}({_cpp_string(self.argument)})"


@dataclass(frozen=True, slots=True)
class _BinaryInt(Expr[int], ABC):
    lhs: IntExpr
    rhs: IntExpr
    _node: ClassVar[str]
    _symbol: ClassVar[str]

    def __post_init__(self) -> None:
        _require_domain(self.lhs, ExprDomain.INT, field_name=f"{self._node}.lhs")
        _require_domain(self.rhs, ExprDomain.INT, field_name=f"{self._node}.rhs")

    @property
    def domain(self) -> ExprDomain:
        return ExprDomain.INT

    @abstractmethod
    def _apply(self, lhs: int, rhs: int) -> int:
        pass

    def evaluate(self, context: EvaluationContext) -> int:
        lhs = self.lhs.evaluate(context)
        rhs = self.rhs.evaluate(context)
        try:
            return self._apply(lhs, rhs)
        except ZeroDivisionError as exc:
            raise ExpressionEvaluationError(f"{self._node} divisor must be nonzero") from exc

    def to_data(self) -> dict[str, JsonValue]:
        return {"lhs": self.lhs.to_data(), "node": self._node, "rhs": self.rhs.to_data()}

    def render(self) -> str:
        return f"({self.lhs.render()} {self._symbol} {self.rhs.render()})"

    def to_python(self) -> str:
        return f"({self.lhs.to_python()} {self._symbol} {self.rhs.to_python()})"

    def to_native_host(self) -> str:
        return f"({self.lhs.to_native_host()} {self._symbol} {self.rhs.to_native_host()})"


@dataclass(frozen=True, slots=True)
class Add(_BinaryInt):
    _node: ClassVar[str] = "add"
    _symbol: ClassVar[str] = "+"

    def _apply(self, lhs: int, rhs: int) -> int:
        return lhs + rhs


@dataclass(frozen=True, slots=True)
class Subtract(_BinaryInt):
    _node: ClassVar[str] = "subtract"
    _symbol: ClassVar[str] = "-"

    def _apply(self, lhs: int, rhs: int) -> int:
        return lhs - rhs


@dataclass(frozen=True, slots=True)
class Multiply(_BinaryInt):
    _node: ClassVar[str] = "multiply"
    _symbol: ClassVar[str] = "*"

    def _apply(self, lhs: int, rhs: int) -> int:
        return lhs * rhs


@dataclass(frozen=True, slots=True)
class FloorDiv(_BinaryInt):
    _node: ClassVar[str] = "floor_div"
    _symbol: ClassVar[str] = "//"

    def _apply(self, lhs: int, rhs: int) -> int:
        return lhs // rhs

    def to_native_host(self) -> str:
        return (
            f"mindclade_floor_div({self.lhs.to_native_host()}, {self.rhs.to_native_host()})"
        )


@dataclass(frozen=True, slots=True)
class Modulo(_BinaryInt):
    _node: ClassVar[str] = "modulo"
    _symbol: ClassVar[str] = "%"

    def _apply(self, lhs: int, rhs: int) -> int:
        return lhs % rhs

    def to_native_host(self) -> str:
        return f"mindclade_mod({self.lhs.to_native_host()}, {self.rhs.to_native_host()})"


@dataclass(frozen=True, slots=True)
class Minimum(_BinaryInt):
    _node: ClassVar[str] = "minimum"
    _symbol: ClassVar[str] = "min"

    def _apply(self, lhs: int, rhs: int) -> int:
        return min(lhs, rhs)

    def render(self) -> str:
        return f"min({self.lhs.render()}, {self.rhs.render()})"

    def to_python(self) -> str:
        return f"min({self.lhs.to_python()}, {self.rhs.to_python()})"

    def to_native_host(self) -> str:
        return f"std::min({self.lhs.to_native_host()}, {self.rhs.to_native_host()})"


@dataclass(frozen=True, slots=True)
class Maximum(_BinaryInt):
    _node: ClassVar[str] = "maximum"
    _symbol: ClassVar[str] = "max"

    def _apply(self, lhs: int, rhs: int) -> int:
        return max(lhs, rhs)

    def render(self) -> str:
        return f"max({self.lhs.render()}, {self.rhs.render()})"

    def to_python(self) -> str:
        return f"max({self.lhs.to_python()}, {self.rhs.to_python()})"

    def to_native_host(self) -> str:
        return f"std::max({self.lhs.to_native_host()}, {self.rhs.to_native_host()})"


@dataclass(frozen=True, slots=True)
class CeilDiv(_BinaryInt):
    _node: ClassVar[str] = "ceil_div"
    _symbol: ClassVar[str] = "ceildiv"

    def _apply(self, lhs: int, rhs: int) -> int:
        if rhs <= 0:
            raise ExpressionEvaluationError("ceil_div divisor must be positive")
        return -(-lhs // rhs)

    def render(self) -> str:
        return f"ceil_div({self.lhs.render()}, {self.rhs.render()})"

    def to_python(self) -> str:
        lhs = self.lhs.to_python()
        rhs = self.rhs.to_python()
        return f"(-(-({lhs}) // ({rhs})))"

    def to_native_host(self) -> str:
        return f"mindclade_ceil_div({self.lhs.to_native_host()}, {self.rhs.to_native_host()})"


@dataclass(frozen=True, slots=True)
class RoundUp(Expr[int]):
    value: IntExpr
    multiple: IntExpr

    def __post_init__(self) -> None:
        _require_domain(self.value, ExprDomain.INT, field_name="round_up.value")
        _require_domain(self.multiple, ExprDomain.INT, field_name="round_up.multiple")

    @property
    def domain(self) -> ExprDomain:
        return ExprDomain.INT

    def evaluate(self, context: EvaluationContext) -> int:
        value = self.value.evaluate(context)
        multiple = self.multiple.evaluate(context)
        if multiple <= 0:
            raise ExpressionEvaluationError("round_up multiple must be positive")
        return -(-value // multiple) * multiple

    def to_data(self) -> dict[str, JsonValue]:
        return {
            "multiple": self.multiple.to_data(),
            "node": "round_up",
            "value": self.value.to_data(),
        }

    def render(self) -> str:
        return f"round_up({self.value.render()}, {self.multiple.render()})"

    def to_python(self) -> str:
        value = self.value.to_python()
        multiple = self.multiple.to_python()
        return f"((-(-({value}) // ({multiple}))) * ({multiple}))"

    def to_native_host(self) -> str:
        return (
            f"mindclade_round_up({self.value.to_native_host()}, "
            f"{self.multiple.to_native_host()})"
        )


@dataclass(frozen=True, slots=True)
class _Comparison(Expr[bool], ABC):
    lhs: Expr[object]
    rhs: Expr[object]
    _node: ClassVar[str]
    _symbol: ClassVar[str]
    _ordered: ClassVar[bool] = False

    def __post_init__(self) -> None:
        lhs = _require_expression(self.lhs, field_name=f"{self._node}.lhs")
        rhs = _require_expression(self.rhs, field_name=f"{self._node}.rhs")
        if self._ordered:
            numeric = {ExprDomain.INT, ExprDomain.FLOAT}
            if lhs.domain not in numeric or rhs.domain not in numeric:
                raise ExpressionValidationError(
                    f"{self._node} requires integer or float operands"
                )
        elif lhs.domain != rhs.domain:
            raise ExpressionValidationError(
                f"{self._node} operands must have matching domains, got "
                f"{lhs.domain.value} and {rhs.domain.value}"
            )

    @property
    def domain(self) -> ExprDomain:
        return ExprDomain.BOOL

    @abstractmethod
    def _apply(self, lhs: object, rhs: object) -> bool:
        pass

    def evaluate(self, context: EvaluationContext) -> bool:
        lhs = self.lhs.evaluate(context)
        rhs = self.rhs.evaluate(context)
        try:
            return self._apply(lhs, rhs)
        except TypeError as exc:
            raise ExpressionEvaluationError(
                f"{self._node} operands cannot be compared"
            ) from exc

    def to_data(self) -> dict[str, JsonValue]:
        return {"lhs": self.lhs.to_data(), "node": self._node, "rhs": self.rhs.to_data()}

    def render(self) -> str:
        return f"({self.lhs.render()} {self._symbol} {self.rhs.render()})"

    def to_python(self) -> str:
        return f"({self.lhs.to_python()} {self._symbol} {self.rhs.to_python()})"

    def to_native_host(self) -> str:
        return f"({self.lhs.to_native_host()} {self._symbol} {self.rhs.to_native_host()})"


@dataclass(frozen=True, slots=True)
class Eq(_Comparison):
    _node: ClassVar[str] = "eq"
    _symbol: ClassVar[str] = "=="

    def _apply(self, lhs: object, rhs: object) -> bool:
        return lhs == rhs


@dataclass(frozen=True, slots=True)
class NotEqual(_Comparison):
    _node: ClassVar[str] = "not_equal"
    _symbol: ClassVar[str] = "!="

    def _apply(self, lhs: object, rhs: object) -> bool:
        return lhs != rhs


@dataclass(frozen=True, slots=True)
class LessThan(_Comparison):
    _node: ClassVar[str] = "less_than"
    _symbol: ClassVar[str] = "<"
    _ordered: ClassVar[bool] = True

    def _apply(self, lhs: object, rhs: object) -> bool:
        return cast(bool, lhs < rhs)  # type: ignore[operator]


@dataclass(frozen=True, slots=True)
class LessEqual(_Comparison):
    _node: ClassVar[str] = "less_equal"
    _symbol: ClassVar[str] = "<="
    _ordered: ClassVar[bool] = True

    def _apply(self, lhs: object, rhs: object) -> bool:
        return cast(bool, lhs <= rhs)  # type: ignore[operator]


@dataclass(frozen=True, slots=True)
class GreaterThan(_Comparison):
    _node: ClassVar[str] = "greater_than"
    _symbol: ClassVar[str] = ">"
    _ordered: ClassVar[bool] = True

    def _apply(self, lhs: object, rhs: object) -> bool:
        return cast(bool, lhs > rhs)  # type: ignore[operator]


@dataclass(frozen=True, slots=True)
class GreaterEqual(_Comparison):
    _node: ClassVar[str] = "greater_equal"
    _symbol: ClassVar[str] = ">="
    _ordered: ClassVar[bool] = True

    def _apply(self, lhs: object, rhs: object) -> bool:
        return cast(bool, lhs >= rhs)  # type: ignore[operator]


@dataclass(frozen=True, slots=True)
class And(Expr[bool]):
    operands: tuple[BoolExpr, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.operands, tuple) or not 1 <= len(self.operands) <= _MAX_OPERANDS:
            raise ExpressionValidationError(
                f"and operands must be a tuple containing 1..{_MAX_OPERANDS} expressions"
            )
        for index, operand in enumerate(self.operands):
            _require_domain(operand, ExprDomain.BOOL, field_name=f"and.operands[{index}]")

    @property
    def domain(self) -> ExprDomain:
        return ExprDomain.BOOL

    def evaluate(self, context: EvaluationContext) -> bool:
        return all(operand.evaluate(context) for operand in self.operands)

    def to_data(self) -> dict[str, JsonValue]:
        return {"node": "and", "operands": [operand.to_data() for operand in self.operands]}

    def render(self) -> str:
        return "(" + " and ".join(operand.render() for operand in self.operands) + ")"

    def to_python(self) -> str:
        return "(" + " and ".join(operand.to_python() for operand in self.operands) + ")"

    def to_native_host(self) -> str:
        return "(" + " && ".join(operand.to_native_host() for operand in self.operands) + ")"


@dataclass(frozen=True, slots=True)
class Or(Expr[bool]):
    operands: tuple[BoolExpr, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.operands, tuple) or not 1 <= len(self.operands) <= _MAX_OPERANDS:
            raise ExpressionValidationError(
                f"or operands must be a tuple containing 1..{_MAX_OPERANDS} expressions"
            )
        for index, operand in enumerate(self.operands):
            _require_domain(operand, ExprDomain.BOOL, field_name=f"or.operands[{index}]")

    @property
    def domain(self) -> ExprDomain:
        return ExprDomain.BOOL

    def evaluate(self, context: EvaluationContext) -> bool:
        return any(operand.evaluate(context) for operand in self.operands)

    def to_data(self) -> dict[str, JsonValue]:
        return {"node": "or", "operands": [operand.to_data() for operand in self.operands]}

    def render(self) -> str:
        return "(" + " or ".join(operand.render() for operand in self.operands) + ")"

    def to_python(self) -> str:
        return "(" + " or ".join(operand.to_python() for operand in self.operands) + ")"

    def to_native_host(self) -> str:
        return "(" + " || ".join(operand.to_native_host() for operand in self.operands) + ")"


@dataclass(frozen=True, slots=True)
class Not(Expr[bool]):
    operand: BoolExpr

    def __post_init__(self) -> None:
        _require_domain(self.operand, ExprDomain.BOOL, field_name="not.operand")

    @property
    def domain(self) -> ExprDomain:
        return ExprDomain.BOOL

    def evaluate(self, context: EvaluationContext) -> bool:
        return not self.operand.evaluate(context)

    def to_data(self) -> dict[str, JsonValue]:
        return {"node": "not", "operand": self.operand.to_data()}

    def render(self) -> str:
        return f"not ({self.operand.render()})"

    def to_python(self) -> str:
        return f"(not ({self.operand.to_python()}))"

    def to_native_host(self) -> str:
        return f"(!({self.operand.to_native_host()}))"


def _member_sort_key(value: ScalarValue) -> tuple[str, str]:
    return (_scalar_domain(value).value, json.dumps(value, sort_keys=True, ensure_ascii=True))


@dataclass(frozen=True, slots=True)
class InSet(Expr[bool]):
    value: Expr[object]
    members: tuple[ScalarValue, ...]

    def __post_init__(self) -> None:
        expression = _require_expression(self.value, field_name="in_set.value")
        if not isinstance(self.members, tuple) or len(self.members) > _MAX_OPERANDS:
            raise ExpressionValidationError(
                f"in_set members must be a tuple with at most {_MAX_OPERANDS} values"
            )
        normalized = tuple(
            sorted(
                (_validated_scalar(member, field_name="in_set member") for member in self.members),
                key=_member_sort_key,
            )
        )
        if any(_scalar_domain(member) != expression.domain for member in normalized):
            raise ExpressionValidationError(
                f"in_set members must all have {expression.domain.value} domain"
            )
        if len(set((_member_sort_key(member) for member in normalized))) != len(normalized):
            raise ExpressionValidationError("in_set members must be unique")
        object.__setattr__(self, "members", normalized)

    @property
    def domain(self) -> ExprDomain:
        return ExprDomain.BOOL

    def evaluate(self, context: EvaluationContext) -> bool:
        return self.value.evaluate(context) in self.members

    def to_data(self) -> dict[str, JsonValue]:
        return {"members": list(self.members), "node": "in_set", "value": self.value.to_data()}

    def render(self) -> str:
        members = ", ".join(json.dumps(member, ensure_ascii=True) for member in self.members)
        return f"({self.value.render()} in {{{members}}})"

    def to_python(self) -> str:
        members = ", ".join(repr(member) for member in self.members)
        if len(self.members) == 1:
            members += ","
        return f"({self.value.to_python()} in ({members}))"

    def to_native_host(self) -> str:
        if not self.members:
            return "false"
        lhs = self.value.to_native_host()
        comparisons: list[str] = []
        for member in self.members:
            if isinstance(member, bool):
                rendered = "true" if member else "false"
            elif isinstance(member, str):
                rendered = _cpp_string(member)
            else:
                rendered = repr(member)
            comparisons.append(f"({lhs} == {rendered})")
        return "(" + " || ".join(comparisons) + ")"


@dataclass(frozen=True, slots=True)
class Select(Expr[_SelectT], Generic[_SelectT]):
    condition: BoolExpr
    when_true: Expr[_SelectT]
    when_false: Expr[_SelectT]

    def __post_init__(self) -> None:
        _require_domain(self.condition, ExprDomain.BOOL, field_name="select.condition")
        true_expression = _require_expression(self.when_true, field_name="select.when_true")
        false_expression = _require_expression(self.when_false, field_name="select.when_false")
        if true_expression.domain != false_expression.domain:
            raise ExpressionValidationError(
                "select branches must have matching domains, got "
                f"{true_expression.domain.value} and {false_expression.domain.value}"
            )

    @property
    def domain(self) -> ExprDomain:
        return self.when_true.domain

    def evaluate(self, context: EvaluationContext) -> _SelectT:
        branch = self.when_true if self.condition.evaluate(context) else self.when_false
        return branch.evaluate(context)

    def to_data(self) -> dict[str, JsonValue]:
        return {
            "condition": self.condition.to_data(),
            "node": "select",
            "when_false": self.when_false.to_data(),
            "when_true": self.when_true.to_data(),
        }

    def render(self) -> str:
        return (
            f"({self.when_true.render()} if {self.condition.render()} "
            f"else {self.when_false.render()})"
        )

    def to_python(self) -> str:
        return (
            f"({self.when_true.to_python()} if {self.condition.to_python()} "
            f"else {self.when_false.to_python()})"
        )

    def to_native_host(self) -> str:
        return (
            f"({self.condition.to_native_host()} ? {self.when_true.to_native_host()} "
            f": {self.when_false.to_native_host()})"
        )


# Readability aliases only; they do not introduce alternate node types or serialization forms.
Sub = Subtract
Mul = Multiply
Mod = Modulo
Min = Minimum
Max = Maximum


def canonical_data(value: object) -> JsonValue:
    """Normalize expression and contract data into one canonical JSON domain."""

    if isinstance(value, Expr):
        return value.to_data()
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return _validated_int(value, field_name="canonical integer")
    if isinstance(value, float):
        return _validated_float(value, field_name="canonical float")
    if isinstance(value, str):
        if len(value) > _MAX_STRING_LENGTH:
            raise ExpressionValidationError(
                f"canonical string must be at most {_MAX_STRING_LENGTH} characters"
            )
        return value
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise ExpressionValidationError("canonical mapping keys must be strings")
        return {
            key: canonical_data(value[key])
            for key in sorted(value)
        }
    if isinstance(value, Sequence):
        return [canonical_data(item) for item in value]
    raise ExpressionValidationError(
        f"unsupported canonical value type: {type(value).__name__}"
    )


def canonical_json(value: object) -> str:
    return json.dumps(
        canonical_data(value),
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def content_digest(value: object) -> str:
    payload = canonical_json(value).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def evaluate(expression: Expr[_SelectT], context: EvaluationContext) -> _SelectT:
    _require_expression(expression, field_name="expression")
    if not isinstance(context, EvaluationContext):
        raise ExpressionEvaluationError("context must be an EvaluationContext")
    return expression.evaluate(context)


def render(expression: Expr[object]) -> str:
    _require_expression(expression, field_name="expression")
    return expression.render()


def generate_python_validator(expression: Expr[object]) -> str:
    _require_expression(expression, field_name="expression")
    return expression.to_python()


def generate_native_host_validator(expression: Expr[object]) -> str:
    _require_expression(expression, field_name="expression")
    try:
        return expression.to_native_host()
    except (NotImplementedError, TypeError) as exc:
        raise ExpressionCodegenError(
            f"{type(expression).__name__} is not supported by native host validation"
        ) from exc


def _exact_object(
    value: object,
    *,
    node: str,
    fields: frozenset[str],
) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ExpressionDecodeError(f"{node} must be a JSON object")
    if not all(isinstance(key, str) for key in value):
        raise ExpressionDecodeError(f"{node} object keys must be strings")
    actual = set(value)
    expected = set(fields) | {"node"}
    if actual != expected:
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        raise ExpressionDecodeError(
            f"{node} fields do not match the contract; missing={missing}, unknown={unknown}"
        )
    return cast(Mapping[str, object], value)


def _decode_sequence(value: object, *, field_name: str) -> Sequence[object]:
    if not isinstance(value, list):
        raise ExpressionDecodeError(f"{field_name} must be a JSON array")
    if len(value) > _MAX_OPERANDS:
        raise ExpressionDecodeError(f"{field_name} exceeds the {_MAX_OPERANDS} item limit")
    return value


def _decode_expression(value: object, *, depth: int) -> Expr[object]:
    if depth > _MAX_DEPTH:
        raise ExpressionDecodeError(f"expression exceeds maximum depth {_MAX_DEPTH}")
    if not isinstance(value, Mapping) or not isinstance(value.get("node"), str):
        raise ExpressionDecodeError("expression node must be an object with a string 'node'")
    node = cast(str, value["node"])

    try:
        if node == "int_literal":
            obj = _exact_object(value, node=node, fields=frozenset({"value"}))
            return cast(Expr[object], IntLiteral(cast(int, obj["value"])))
        if node == "bool_literal":
            obj = _exact_object(value, node=node, fields=frozenset({"value"}))
            return cast(Expr[object], BoolLiteral(cast(bool, obj["value"])))
        if node == "float_literal":
            obj = _exact_object(value, node=node, fields=frozenset({"value"}))
            return cast(Expr[object], FloatLiteral(cast(float, obj["value"])))
        if node == "string_literal":
            obj = _exact_object(value, node=node, fields=frozenset({"value"}))
            return cast(Expr[object], StringLiteral(cast(str, obj["value"])))
        if node == "dim_ref":
            obj = _exact_object(value, node=node, fields=frozenset({"argument", "axis"}))
            return cast(Expr[object], DimRef(cast(str, obj["argument"]), cast(int, obj["axis"])))
        if node in {"rank_ref", "dtype_ref", "device_ref", "same_as_input_dtype", "same_as_input_device"}:
            obj = _exact_object(value, node=node, fields=frozenset({"argument"}))
            reference_types = {
                "rank_ref": RankRef,
                "dtype_ref": DTypeRef,
                "device_ref": DeviceRef,
                "same_as_input_dtype": SameAsInputDType,
                "same_as_input_device": SameAsInputDevice,
            }
            return cast(Expr[object], reference_types[node](cast(str, obj["argument"])))
        if node in {"constant_dtype", "constant_device"}:
            obj = _exact_object(value, node=node, fields=frozenset({"value"}))
            constant_types = {"constant_dtype": ConstantDType, "constant_device": ConstantDevice}
            return cast(Expr[object], constant_types[node](cast(str, obj["value"])))
        if node == "scalar_ref":
            obj = _exact_object(
                value, node=node, fields=frozenset({"argument", "value_type"})
            )
            raw_type = obj["value_type"]
            if not isinstance(raw_type, str):
                raise ExpressionDecodeError("scalar_ref.value_type must be a string")
            try:
                value_type = ScalarType(raw_type)
            except ValueError as exc:
                raise ExpressionDecodeError(
                    f"unsupported scalar_ref.value_type {raw_type!r}"
                ) from exc
            return cast(
                Expr[object], ScalarRef(cast(str, obj["argument"]), value_type=value_type)
            )
        if node in {
            "add",
            "subtract",
            "multiply",
            "floor_div",
            "ceil_div",
            "modulo",
            "minimum",
            "maximum",
            "eq",
            "not_equal",
            "less_than",
            "less_equal",
            "greater_than",
            "greater_equal",
        }:
            obj = _exact_object(value, node=node, fields=frozenset({"lhs", "rhs"}))
            lhs = _decode_expression(obj["lhs"], depth=depth + 1)
            rhs = _decode_expression(obj["rhs"], depth=depth + 1)
            binary_types = {
                "add": Add,
                "subtract": Subtract,
                "multiply": Multiply,
                "floor_div": FloorDiv,
                "ceil_div": CeilDiv,
                "modulo": Modulo,
                "minimum": Minimum,
                "maximum": Maximum,
                "eq": Eq,
                "not_equal": NotEqual,
                "less_than": LessThan,
                "less_equal": LessEqual,
                "greater_than": GreaterThan,
                "greater_equal": GreaterEqual,
            }
            return cast(Expr[object], binary_types[node](lhs, rhs))
        if node == "round_up":
            obj = _exact_object(value, node=node, fields=frozenset({"value", "multiple"}))
            return cast(
                Expr[object],
                RoundUp(
                    _decode_expression(obj["value"], depth=depth + 1),
                    _decode_expression(obj["multiple"], depth=depth + 1),
                ),
            )
        if node in {"and", "or"}:
            obj = _exact_object(value, node=node, fields=frozenset({"operands"}))
            operands = tuple(
                _decode_expression(item, depth=depth + 1)
                for item in _decode_sequence(obj["operands"], field_name=f"{node}.operands")
            )
            operation_type = And if node == "and" else Or
            return cast(Expr[object], operation_type(operands))
        if node == "not":
            obj = _exact_object(value, node=node, fields=frozenset({"operand"}))
            return cast(
                Expr[object], Not(_decode_expression(obj["operand"], depth=depth + 1))
            )
        if node == "in_set":
            obj = _exact_object(value, node=node, fields=frozenset({"value", "members"}))
            members = tuple(
                _validated_scalar(member, field_name="in_set member")
                for member in _decode_sequence(obj["members"], field_name="in_set.members")
            )
            return cast(
                Expr[object],
                InSet(_decode_expression(obj["value"], depth=depth + 1), members),
            )
        if node == "select":
            obj = _exact_object(
                value,
                node=node,
                fields=frozenset({"condition", "when_true", "when_false"}),
            )
            return cast(
                Expr[object],
                Select(
                    _decode_expression(obj["condition"], depth=depth + 1),
                    _decode_expression(obj["when_true"], depth=depth + 1),
                    _decode_expression(obj["when_false"], depth=depth + 1),
                ),
            )
    except ExpressionDecodeError:
        raise
    except ExpressionValidationError as exc:
        raise ExpressionDecodeError(f"invalid {node} node: {exc}") from exc

    raise ExpressionDecodeError(f"unsupported expression node {node!r}")


def expression_from_data(value: object) -> Expr[object]:
    """Decode a whitelisted JSON-compatible expression object."""

    return _decode_expression(value, depth=0)


def _pairs_without_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ExpressionDecodeError(f"duplicate JSON object key {key!r}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> object:
    raise ExpressionDecodeError(f"non-finite JSON number {value!r} is forbidden")


def expression_from_json(payload: str) -> Expr[object]:
    """Decode canonical expression JSON without executing source text."""

    if not isinstance(payload, str):
        raise ExpressionDecodeError("expression JSON must be a string")
    if len(payload.encode("utf-8")) > _MAX_JSON_LENGTH:
        raise ExpressionDecodeError(f"expression JSON exceeds {_MAX_JSON_LENGTH} bytes")
    try:
        value = json.loads(
            payload,
            object_pairs_hook=_pairs_without_duplicates,
            parse_constant=_reject_json_constant,
        )
    except ExpressionDecodeError:
        raise
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise ExpressionDecodeError(f"invalid expression JSON: {exc}") from exc
    return expression_from_data(value)
