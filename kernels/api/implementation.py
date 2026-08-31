"""Build-plane implementation declarations, separate from operation semantics."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .capability import CapabilityEnvelope
from .errors import KernelContractError
from .output import ContractModel, _nonempty, _unique


class ImplementationTier(StrEnum):
    PORTABLE = "portable"
    OPTIMIZED = "optimized"
    SPECIALIZED = "specialized"
    HAND_SPECIALIZED = "hand_specialized"


@dataclass(frozen=True, slots=True)
class ImplementationSpec(ContractModel):
    operation: str
    name: str
    family: str
    backend: str
    builder: str
    version: int
    tier: ImplementationTier
    requires: tuple[str, ...]
    envelope: CapabilityEnvelope
    priority: int = 0

    def __post_init__(self) -> None:
        for label in ("operation", "name", "family", "backend", "builder"):
            _nonempty(getattr(self, label), f"implementation {label}")
        if self.version < 1:
            raise KernelContractError("implementation version must be positive")
        if ":" not in self.builder:
            raise KernelContractError("implementation builder must be a module:function identity")
        _unique(self.requires, "implementation requirements")
