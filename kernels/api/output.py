"""Output and canonical contract primitives for Mindclade kernels."""

from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from enum import Enum
from typing import Any

from .errors import KernelContractError
from .expressions import DTypeExpr, DeviceExpr, Expr, ShapeExpr, canonical_data, content_digest


def _nonempty(value: str, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise KernelContractError(f"{label} must be a non-empty string")
    return value


def _unique(values: tuple[str, ...], label: str) -> None:
    if len(values) != len(set(values)):
        raise KernelContractError(f"{label} must not contain duplicates")


def _canonical(value: Any) -> Any:
    if isinstance(value, ContractModel):
        return value.to_canonical()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, tuple):
        return [_canonical(item) for item in value]
    if isinstance(value, list):
        return [_canonical(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _canonical(value[key]) for key in sorted(value, key=str)}
    if is_dataclass(value):
        return {
            field.name: _canonical(getattr(value, field.name))
            for field in fields(value)
        }
    return canonical_data(value)


class ContractModel:
    """Common canonical serialization and identity for immutable contracts."""

    def to_canonical(self) -> dict[str, Any]:
        if not is_dataclass(self):
            raise TypeError("ContractModel implementations must be dataclasses")
        return {
            "type": type(self).__name__,
            **{
                field.name: _canonical(getattr(self, field.name))
                for field in fields(self)
            },
        }

    @property
    def digest(self) -> str:
        return content_digest(self.to_canonical())


@dataclass(frozen=True, slots=True)
class InitializationSpec(ContractModel):
    """Defines deterministic initialization for outputs or padded regions."""

    mode: str
    value: int | float | bool | None = None
    version: int = 1

    def __post_init__(self) -> None:
        if self.version != 1:
            raise KernelContractError(f"unsupported InitializationSpec version: {self.version}")
        if self.mode not in {"zero", "value", "uninitialized"}:
            raise KernelContractError(f"unsupported initialization mode: {self.mode}")
        if self.mode == "value" and self.value is None:
            raise KernelContractError("value initialization requires an explicit value")
        if self.mode != "value" and self.value is not None:
            raise KernelContractError(f"{self.mode} initialization cannot carry a value")


@dataclass(frozen=True, slots=True)
class OutputSpec(ContractModel):
    """Declarative metadata for one semantic/provider output."""

    name: str
    shape: ShapeExpr
    dtype: DTypeExpr
    device: DeviceExpr
    semantic_axes: tuple[str, ...]
    visible_in_facade: bool
    saved_for_backward: bool
    initialization: InitializationSpec | None = None
    version: int = 1

    def __post_init__(self) -> None:
        _nonempty(self.name, "output name")
        if self.version != 1:
            raise KernelContractError(f"unsupported OutputSpec version: {self.version}")
        if not isinstance(self.shape, (Expr, tuple)):
            raise KernelContractError("output shape must be a typed shape expression")
        if isinstance(self.shape, tuple) and not all(isinstance(item, Expr) for item in self.shape):
            raise KernelContractError("every output shape dimension must be a typed expression")
        if not isinstance(self.dtype, Expr):
            raise KernelContractError("output dtype must be a typed dtype expression")
        if not isinstance(self.device, Expr):
            raise KernelContractError("output device must be a typed device expression")
        if not self.semantic_axes:
            raise KernelContractError("output semantic_axes must not be empty")
        for axis in self.semantic_axes:
            _nonempty(axis, "semantic axis")
        _unique(self.semantic_axes, "output semantic_axes")
        if isinstance(self.shape, tuple) and len(self.shape) != len(self.semantic_axes):
            raise KernelContractError("output shape rank must match semantic_axes")
