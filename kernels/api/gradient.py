"""Named gradient contracts."""

from __future__ import annotations

from dataclasses import dataclass

from .errors import KernelContractError
from .expressions import DTypeExpr, DeviceExpr, Expr, ExprDomain, ShapeExpr
from .output import ContractModel, _nonempty


@dataclass(frozen=True, slots=True)
class GradientSpec(ContractModel):
    """Maps one semantic input to one provider-backward output by name."""

    input_name: str
    output_name: str
    shape: ShapeExpr
    dtype: DTypeExpr
    device: DeviceExpr
    optional: bool = False
    accumulation_dtype: str | None = None
    version: int = 1

    def __post_init__(self) -> None:
        _nonempty(self.input_name, "gradient input_name")
        _nonempty(self.output_name, "gradient output_name")
        if isinstance(self.version, bool) or not isinstance(self.version, int) or self.version != 1:
            raise KernelContractError(f"unsupported GradientSpec version: {self.version}")
        for value, domain, label in (
            (self.shape, ExprDomain.SHAPE, "shape"),
            (self.dtype, ExprDomain.DTYPE, "dtype"),
            (self.device, ExprDomain.DEVICE, "device"),
        ):
            if not isinstance(value, Expr) or value.domain is not domain:
                raise KernelContractError(
                    f"gradient {label} must be a {domain.value}-domain expression"
                )
        if type(self.optional) is not bool:
            raise KernelContractError("gradient optional must be bool")
        if self.accumulation_dtype is not None:
            _nonempty(self.accumulation_dtype, "gradient accumulation_dtype")
