"""Mutation, aliasing, RNG, and atomic effect contracts."""

from __future__ import annotations

from dataclasses import dataclass

from .errors import KernelContractError
from .output import ContractModel, _nonempty, _unique


@dataclass(frozen=True, slots=True)
class EffectSpec(ContractModel):
    mutates_inputs: tuple[str, ...] = ()
    aliases_outputs: tuple[tuple[str, str], ...] = ()
    uses_rng: bool = False
    uses_atomics: bool = False
    version: int = 1

    def __post_init__(self) -> None:
        if self.version != 1:
            raise KernelContractError(f"unsupported EffectSpec version: {self.version}")
        for name in self.mutates_inputs:
            _nonempty(name, "mutated input")
        _unique(self.mutates_inputs, "mutates_inputs")
        output_names: list[str] = []
        for output_name, input_name in self.aliases_outputs:
            _nonempty(output_name, "aliased output")
            _nonempty(input_name, "aliased input")
            output_names.append(output_name)
        _unique(tuple(output_names), "aliased outputs")
