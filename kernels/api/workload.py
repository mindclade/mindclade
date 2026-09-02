"""Canonical operation workload identity."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import TypeAlias

from .errors import KernelContractError
from .expressions import DTypeExpr, Expr, ExprDomain, IntExpr
from .output import ContractModel, _nonempty, _unique

ScalarValue: TypeAlias = int | float | bool | str

_WORKLOAD_NAME = re.compile(r"[a-z][a-z0-9_]{0,63}")
_LAYOUT = re.compile(r"[a-z][a-z0-9_]{0,31}")


def _strict_v1(value: object, label: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value != 1:
        raise KernelContractError(f"{label} version must be exactly integer 1")


def _workload_name(value: object, label: str) -> None:
    if not isinstance(value, str) or _WORKLOAD_NAME.fullmatch(value) is None:
        raise KernelContractError(f"{label} must be a canonical lower_snake_case name")


@dataclass(frozen=True, slots=True)
class WorkloadDimensionBinding(ContractModel):
    name: str
    value: IntExpr
    version: int = 1

    def __post_init__(self) -> None:
        _strict_v1(self.version, "WorkloadDimensionBinding")
        _workload_name(self.name, "workload dimension name")
        if not isinstance(self.value, Expr) or self.value.domain is not ExprDomain.INT:
            raise KernelContractError("workload dimension value must be a typed integer expression")


@dataclass(frozen=True, slots=True)
class WorkloadAttributeBinding(ContractModel):
    name: str
    value: Expr[object]
    version: int = 1

    def __post_init__(self) -> None:
        _strict_v1(self.version, "WorkloadAttributeBinding")
        _workload_name(self.name, "workload attribute name")
        if not isinstance(self.value, Expr) or self.value.domain not in {
            ExprDomain.BOOL,
            ExprDomain.INT,
            ExprDomain.FLOAT,
            ExprDomain.STRING,
        }:
            raise KernelContractError(
                "workload attribute value must be a typed bool/int/float/string expression"
            )


@dataclass(frozen=True, slots=True)
class RuntimeWorkloadSpec(ContractModel):
    dimensions: tuple[WorkloadDimensionBinding, ...]
    input_dtype: DTypeExpr
    layout: str
    mode_selector: str | None = None
    attributes: tuple[WorkloadAttributeBinding, ...] = ()
    canonicalization_version: int = 1
    version: int = 1

    def __post_init__(self) -> None:
        _strict_v1(self.version, "RuntimeWorkloadSpec")
        _strict_v1(self.canonicalization_version, "runtime workload canonicalization")
        if not isinstance(self.dimensions, tuple) or not self.dimensions:
            raise KernelContractError("runtime workload dimensions must be a non-empty tuple")
        if not all(isinstance(value, WorkloadDimensionBinding) for value in self.dimensions):
            raise KernelContractError("runtime workload dimensions must contain bindings")
        if not isinstance(self.attributes, tuple) or not all(
            isinstance(value, WorkloadAttributeBinding) for value in self.attributes
        ):
            raise KernelContractError("runtime workload attributes must be a tuple of bindings")
        if not isinstance(self.input_dtype, Expr) or self.input_dtype.domain is not ExprDomain.DTYPE:
            raise KernelContractError("runtime workload input_dtype must be a typed dtype expression")
        if not isinstance(self.layout, str) or _LAYOUT.fullmatch(self.layout) is None:
            raise KernelContractError("runtime workload layout must be a canonical identifier")
        if self.mode_selector is not None:
            _workload_name(self.mode_selector, "runtime workload mode_selector")
        dimensions = tuple(sorted(self.dimensions, key=lambda value: value.name))
        attributes = tuple(sorted(self.attributes, key=lambda value: value.name))
        _unique(tuple(value.name for value in dimensions), "runtime workload dimension names")
        _unique(tuple(value.name for value in attributes), "runtime workload attribute names")
        overlap = sorted(
            {value.name for value in dimensions}.intersection(value.name for value in attributes)
        )
        if overlap:
            raise KernelContractError(
                f"runtime workload dimension and attribute names overlap: {overlap}"
            )
        object.__setattr__(self, "dimensions", dimensions)
        object.__setattr__(self, "attributes", attributes)


@dataclass(frozen=True, slots=True)
class WorkloadSpec(ContractModel):
    operation: str
    dimensions: tuple[tuple[str, int], ...]
    input_dtype: str
    output_dtype: str
    layout: str
    mode: str
    attributes: tuple[tuple[str, ScalarValue], ...] = ()
    version: int = 1

    def __post_init__(self) -> None:
        for label in ("operation", "input_dtype", "output_dtype", "layout", "mode"):
            _nonempty(getattr(self, label), f"workload {label}")
        if self.version < 1:
            raise KernelContractError("workload version must be positive")
        dimension_names: list[str] = []
        for name, value in self.dimensions:
            _nonempty(name, "workload dimension name")
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise KernelContractError(f"workload dimension {name!r} must be a non-negative integer")
            dimension_names.append(name)
        _unique(tuple(dimension_names), "workload dimension names")
        attribute_names: list[str] = []
        for name, value in self.attributes:
            _nonempty(name, "workload attribute name")
            if not isinstance(value, (int, float, bool, str)):
                raise KernelContractError(f"unsupported scalar attribute type for {name!r}")
            attribute_names.append(name)
        _unique(tuple(attribute_names), "workload attribute names")
        object.__setattr__(self, "dimensions", tuple(sorted(self.dimensions)))
        object.__setattr__(self, "attributes", tuple(sorted(self.attributes, key=lambda item: item[0])))
