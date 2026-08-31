"""Exact native support-envelope contracts."""

from __future__ import annotations

from dataclasses import dataclass

from .errors import KernelContractError
from .expressions import BoolExpr, Expr
from .output import ContractModel, _nonempty, _unique


@dataclass(frozen=True, slots=True)
class DimensionConstraint(ContractModel):
    predicate: BoolExpr
    code: str
    message: str
    version: int = 1

    def __post_init__(self) -> None:
        if self.version != 1:
            raise KernelContractError(f"unsupported DimensionConstraint version: {self.version}")
        if not isinstance(self.predicate, Expr):
            raise KernelContractError("capability predicate must be a typed boolean expression")
        _nonempty(self.code, "constraint code")
        _nonempty(self.message, "constraint message")
        if not self.code.replace("_", "").isalnum() or self.code != self.code.upper():
            raise KernelContractError("constraint code must use uppercase letters, digits, and underscores")


@dataclass(frozen=True, slots=True)
class TensorCapabilityConstraint(ContractModel):
    """Argument-specific tensor restrictions within one implementation envelope."""

    argument: str
    dtypes: tuple[str, ...] = ()
    layouts: tuple[str, ...] = ()
    devices: tuple[str, ...] = ()
    ranks: tuple[int, ...] = ()
    version: int = 1

    def __post_init__(self) -> None:
        _nonempty(self.argument, "tensor capability argument")
        if self.version != 1:
            raise KernelContractError(
                f"unsupported TensorCapabilityConstraint version: {self.version}"
            )
        for label, values in (
            ("dtypes", self.dtypes),
            ("layouts", self.layouts),
            ("devices", self.devices),
        ):
            for value in values:
                _nonempty(value, f"tensor capability {label} value")
            _unique(values, f"tensor capability {label}")
        if any(isinstance(rank, bool) or not isinstance(rank, int) or rank < 0 for rank in self.ranks):
            raise KernelContractError("tensor capability ranks must be non-negative integers")
        if len(self.ranks) != len(set(self.ranks)):
            raise KernelContractError("tensor capability ranks must not contain duplicates")
        if not any((self.dtypes, self.layouts, self.devices, self.ranks)):
            raise KernelContractError(
                "tensor capability constraint must restrict dtype, layout, device, or rank"
            )


@dataclass(frozen=True, slots=True)
class CapabilityEnvelope(ContractModel):
    architectures: tuple[str, ...]
    dtypes: tuple[str, ...]
    layouts: tuple[str, ...]
    modes: tuple[str, ...]
    constraints: tuple[DimensionConstraint, ...]
    graph_capture_safe: bool
    training_capable: bool
    tensor_constraints: tuple[TensorCapabilityConstraint, ...] = ()
    version: int = 1

    def __post_init__(self) -> None:
        if self.version != 1:
            raise KernelContractError(f"unsupported CapabilityEnvelope version: {self.version}")
        for label, values in (
            ("architectures", self.architectures),
            ("dtypes", self.dtypes),
            ("layouts", self.layouts),
            ("modes", self.modes),
        ):
            if not values:
                raise KernelContractError(f"capability {label} must not be empty")
            for value in values:
                _nonempty(value, f"capability {label} value")
            _unique(values, f"capability {label}")
        _unique(tuple(constraint.code for constraint in self.constraints), "constraint codes")
        _unique(
            tuple(constraint.argument for constraint in self.tensor_constraints),
            "tensor capability argument identities",
        )
