"""Named gradient contracts."""

from __future__ import annotations

from dataclasses import dataclass

from .errors import KernelContractError
from .output import ContractModel, _nonempty


@dataclass(frozen=True, slots=True)
class GradientSpec(ContractModel):
    """Maps one semantic input to one provider-backward output by name."""

    input_name: str
    output_name: str
    optional: bool = False
    accumulation_dtype: str | None = None
    version: int = 1

    def __post_init__(self) -> None:
        _nonempty(self.input_name, "gradient input_name")
        _nonempty(self.output_name, "gradient output_name")
        if self.version != 1:
            raise KernelContractError(f"unsupported GradientSpec version: {self.version}")
        if self.accumulation_dtype is not None:
            _nonempty(self.accumulation_dtype, "gradient accumulation_dtype")
