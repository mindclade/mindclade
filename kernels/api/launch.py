"""Host-launch behavior and determinism contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .errors import KernelContractError
from .output import ContractModel


class DeterminismClass(StrEnum):
    DETERMINISTIC = "deterministic"
    CONDITIONALLY_DETERMINISTIC = "conditionally_deterministic"
    NONDETERMINISTIC = "nondeterministic"


@dataclass(frozen=True, slots=True)
class LaunchContract(ContractModel):
    current_stream_only: bool = True
    global_synchronization: bool = False
    hidden_device_allocation: bool = False
    graph_capture_safe: bool = True
    determinism: DeterminismClass = DeterminismClass.DETERMINISTIC
    version: int = 1

    def __post_init__(self) -> None:
        if self.version != 1:
            raise KernelContractError(f"unsupported LaunchContract version: {self.version}")
        if self.current_stream_only and self.global_synchronization:
            raise KernelContractError("current-stream-only launch cannot globally synchronize")
        if self.graph_capture_safe and self.global_synchronization:
            raise KernelContractError("graph-capture-safe launch cannot globally synchronize")
        if self.graph_capture_safe and self.hidden_device_allocation:
            raise KernelContractError("graph-capture-safe launch cannot allocate hidden device memory")
