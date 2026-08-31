"""Reviewed numerical acceptance contracts."""

from __future__ import annotations

import math
from dataclasses import dataclass

from .errors import KernelContractError
from .output import ContractModel, _nonempty, _unique


def _finite_nonnegative(value: float | None, label: str) -> None:
    if value is not None and (not math.isfinite(value) or value < 0):
        raise KernelContractError(f"{label} must be finite and non-negative")


@dataclass(frozen=True, slots=True)
class TensorTolerance(ContractModel):
    output_name: str
    dtype: str
    max_abs: float
    max_rel: float | None = None
    mean_abs: float | None = None
    max_ulp: int | None = None
    version: int = 1

    def __post_init__(self) -> None:
        _nonempty(self.output_name, "tolerance output_name")
        _nonempty(self.dtype, "tolerance dtype")
        if self.version != 1:
            raise KernelContractError(f"unsupported TensorTolerance version: {self.version}")
        _finite_nonnegative(self.max_abs, "max_abs")
        _finite_nonnegative(self.max_rel, "max_rel")
        _finite_nonnegative(self.mean_abs, "mean_abs")
        if self.max_ulp is not None and self.max_ulp < 0:
            raise KernelContractError("max_ulp must be non-negative")


@dataclass(frozen=True, slots=True)
class NumericalEnvelope(ContractModel):
    name: str
    version: int
    tolerances: tuple[TensorTolerance, ...]
    reject_nan: bool = True
    reject_inf: bool = True
    accumulation_contract: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        _nonempty(self.name, "numerical envelope name")
        if self.version < 1:
            raise KernelContractError("numerical envelope version must be positive")
        if not self.tolerances:
            raise KernelContractError("numerical envelope must contain tolerances")
        identities = tuple(
            f"{tolerance.output_name}:{tolerance.dtype}" for tolerance in self.tolerances
        )
        _unique(identities, "numerical tolerance identities")
        accumulator_names: list[str] = []
        for name, dtype in self.accumulation_contract:
            _nonempty(name, "accumulation contract name")
            _nonempty(dtype, "accumulation contract dtype")
            accumulator_names.append(name)
        _unique(tuple(accumulator_names), "accumulation contract names")
