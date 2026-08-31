"""Raw backward provider contract."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .errors import KernelContractError
from .gradient import GradientSpec
from .output import ContractModel, _nonempty, _unique
from .program_group import ProgramGroupSpec


class BackwardArgumentSource(StrEnum):
    OUTPUT_GRADIENT = "output_gradient"
    OPERATOR_ARGUMENT = "operator_argument"
    FORWARD_OUTPUT = "forward_output"
    NEEDS_INPUT_GRAD = "needs_input_grad"


class MissingGradientPolicy(StrEnum):
    ERROR = "error"
    ZERO = "zero"
    PASS_NONE = "pass_none"


@dataclass(frozen=True, slots=True)
class BackwardArgumentBinding(ContractModel):
    """Bind one named provider parameter to one named autograd value source."""

    provider_argument: str
    source: BackwardArgumentSource
    source_name: str
    missing: MissingGradientPolicy = MissingGradientPolicy.ERROR
    version: int = 1

    def __post_init__(self) -> None:
        _nonempty(self.provider_argument, "backward provider_argument")
        _nonempty(self.source_name, "backward source_name")
        if self.version != 1:
            raise KernelContractError(
                f"unsupported BackwardArgumentBinding version: {self.version}"
            )
        if (
            self.source is not BackwardArgumentSource.OUTPUT_GRADIENT
            and self.missing is not MissingGradientPolicy.ERROR
        ):
            raise KernelContractError(
                "missing-gradient policy applies only to output-gradient bindings"
            )


@dataclass(frozen=True, slots=True)
class BackwardSpec(ContractModel):
    schema: str
    builder: str
    symbol: str
    argument_bindings: tuple[BackwardArgumentBinding, ...]
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
        if not self.argument_bindings:
            raise KernelContractError("backward argument_bindings must not be empty")
        ordered_bindings = tuple(
            sorted(self.argument_bindings, key=lambda binding: binding.provider_argument)
        )
        object.__setattr__(self, "argument_bindings", ordered_bindings)
        _unique(
            tuple(binding.provider_argument for binding in ordered_bindings),
            "backward provider argument bindings",
        )
        if not self.gradients:
            raise KernelContractError("backward gradients must not be empty")
        _unique(tuple(item.input_name for item in self.gradients), "gradient input mappings")
        _unique(tuple(item.output_name for item in self.gradients), "gradient output mappings")
