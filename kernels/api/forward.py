"""Raw forward provider contract."""

from __future__ import annotations

from dataclasses import dataclass

from .errors import KernelContractError
from .output import ContractModel, OutputSpec, _nonempty, _unique
from .program_group import ProgramGroupSpec


@dataclass(frozen=True, slots=True)
class ForwardSpec(ContractModel):
    schema: str
    builder: str
    symbol: str
    outputs: tuple[OutputSpec, ...]
    program_group: ProgramGroupSpec | None = None
    version: int = 1

    def __post_init__(self) -> None:
        _nonempty(self.schema, "forward schema")
        _nonempty(self.builder, "forward builder")
        _nonempty(self.symbol, "forward symbol")
        if self.version != 1:
            raise KernelContractError(f"unsupported ForwardSpec version: {self.version}")
        if ":" not in self.builder:
            raise KernelContractError("forward builder must be a module:function identity")
        if not self.outputs:
            raise KernelContractError("forward outputs must not be empty")
        _unique(tuple(output.name for output in self.outputs), "forward output names")
