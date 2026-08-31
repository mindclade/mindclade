"""Raw backward provider contract."""

from __future__ import annotations

from dataclasses import dataclass

from .errors import KernelContractError
from .gradient import GradientSpec
from .output import ContractModel, _nonempty, _unique
from .program_group import ProgramGroupSpec


@dataclass(frozen=True, slots=True)
class BackwardSpec(ContractModel):
    schema: str
    builder: str
    symbol: str
    gradients: tuple[GradientSpec, ...]
    supports_double_backward: bool
    program_group: ProgramGroupSpec | None = None
    version: int = 1

    def __post_init__(self) -> None:
        _nonempty(self.schema, "backward schema")
        _nonempty(self.builder, "backward builder")
        _nonempty(self.symbol, "backward symbol")
        if self.version != 1:
            raise KernelContractError(f"unsupported BackwardSpec version: {self.version}")
        if ":" not in self.builder:
            raise KernelContractError("backward builder must be a module:function identity")
        if not self.gradients:
            raise KernelContractError("backward gradients must not be empty")
        _unique(tuple(item.input_name for item in self.gradients), "gradient input mappings")
        _unique(tuple(item.output_name for item in self.gradients), "gradient output mappings")
