"""Canonical operation workload identity."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias

from .errors import KernelContractError
from .output import ContractModel, _nonempty, _unique

ScalarValue: TypeAlias = int | float | bool | str


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
