"""Resolved offline schedule and specialization contracts."""

from __future__ import annotations

from dataclasses import dataclass

from .errors import KernelContractError
from .output import ContractModel, _nonempty
from .workload import WorkloadSpec


@dataclass(frozen=True, slots=True)
class ScheduleSpec(ContractModel):
    block_m: int
    block_n: int
    block_k: int | None
    threads: int
    num_stages: int
    vector_width: int
    use_tma: bool = False
    use_wgmma: bool = False
    persistent: bool = False
    split_k: int = 1
    cluster_m: int = 1
    cluster_n: int = 1
    version: int = 1

    def __post_init__(self) -> None:
        if self.version != 1:
            raise KernelContractError(f"unsupported ScheduleSpec version: {self.version}")
        for label in (
            "block_m",
            "block_n",
            "threads",
            "num_stages",
            "vector_width",
            "split_k",
            "cluster_m",
            "cluster_n",
        ):
            if getattr(self, label) <= 0:
                raise KernelContractError(f"schedule {label} must be positive")
        if self.block_k is not None and self.block_k <= 0:
            raise KernelContractError("schedule block_k must be positive when specified")
        if self.use_wgmma and not self.use_tma:
            raise KernelContractError("WGMMA schedule requires TMA")
        if (self.cluster_m > 1 or self.cluster_n > 1) and not self.use_tma:
            raise KernelContractError("cluster schedule requires TMA")


@dataclass(frozen=True, slots=True)
class SpecializationSpec(ContractModel):
    workload: WorkloadSpec
    schedule: ScheduleSpec
    numerical_envelope: str
    version: int = 1

    def __post_init__(self) -> None:
        _nonempty(self.numerical_envelope, "specialization numerical_envelope")
        if self.version != 1:
            raise KernelContractError(f"unsupported SpecializationSpec version: {self.version}")
