"""Exact native support-envelope contracts."""

from __future__ import annotations

from dataclasses import dataclass
import re

from .errors import KernelContractError
from .expressions import (
    BoolExpr,
    EvaluationContext,
    Expr,
    ExprDomain,
    ExpressionEvaluationError,
    render as render_expression,
)
from .output import ContractModel, _unique

_TOKEN = re.compile(r"^[A-Za-z][A-Za-z0-9_.+-]{0,127}$")
_ARGUMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
_CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_MAX_MESSAGE = 512


def _v1(value: object, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value != 1:
        raise KernelContractError(f"{label} version must be exactly integer 1")


def _strict_bool(value: object, label: str) -> None:
    if type(value) is not bool:
        raise KernelContractError(f"{label} must be a bool")


def _token(value: object, label: str) -> str:
    if not isinstance(value, str) or _TOKEN.fullmatch(value) is None:
        raise KernelContractError(f"{label} must be a bounded capability token")
    return value


def _token_tuple(
    value: object,
    label: str,
    *,
    nonempty: bool,
) -> tuple[str, ...]:
    if not isinstance(value, tuple) or (nonempty and not value):
        qualifier = "non-empty " if nonempty else ""
        raise KernelContractError(f"{label} must be a {qualifier}tuple")
    normalized = tuple(sorted(_token(item, f"{label} value") for item in value))
    _unique(normalized, label)
    return normalized


def _message(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > _MAX_MESSAGE
        or any(ord(character) < 32 and character not in "\t" for character in value)
    ):
        raise KernelContractError(
            f"{label} must be a non-empty bounded message without control characters"
        )
    return value


@dataclass(frozen=True, slots=True)
class DimensionConstraint(ContractModel):
    predicate: BoolExpr
    code: str
    message: str
    version: int = 1

    def __post_init__(self) -> None:
        _v1(self.version, "DimensionConstraint")
        if not isinstance(self.predicate, Expr) or self.predicate.domain is not ExprDomain.BOOL:
            raise KernelContractError("capability predicate must be a typed boolean expression")
        if not isinstance(self.code, str) or _CODE.fullmatch(self.code) is None:
            raise KernelContractError("constraint code must use uppercase letters, digits, and underscores")
        _message(self.message, "constraint message")

    def render(self) -> str:
        return f"{self.code}: {self.message} [{render_expression(self.predicate)}]"


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
        if not isinstance(self.argument, str) or _ARGUMENT.fullmatch(self.argument) is None:
            raise KernelContractError("tensor capability argument must be an identifier")
        _v1(self.version, "TensorCapabilityConstraint")
        for label, values in (
            ("dtypes", self.dtypes),
            ("layouts", self.layouts),
            ("devices", self.devices),
        ):
            normalized = _token_tuple(
                values,
                f"tensor capability {label}",
                nonempty=False,
            )
            object.__setattr__(self, label, normalized)
        if not isinstance(self.ranks, tuple):
            raise KernelContractError("tensor capability ranks must be a tuple")
        if any(isinstance(rank, bool) or not isinstance(rank, int) or rank < 0 for rank in self.ranks):
            raise KernelContractError("tensor capability ranks must be non-negative integers")
        normalized_ranks = tuple(sorted(self.ranks))
        _unique(normalized_ranks, "tensor capability ranks")
        object.__setattr__(self, "ranks", normalized_ranks)
        if not any((self.dtypes, self.layouts, self.devices, self.ranks)):
            raise KernelContractError(
                "tensor capability constraint must restrict dtype, layout, device, or rank"
            )


@dataclass(frozen=True, slots=True)
class CapabilityRequest:
    architecture: str
    dtype: str
    layout: str
    mode: str
    graph_capture: bool
    training: bool
    metadata: EvaluationContext

    def __post_init__(self) -> None:
        for label in ("architecture", "dtype", "layout", "mode"):
            _token(getattr(self, label), f"capability request {label}")
        _strict_bool(self.graph_capture, "capability request graph_capture")
        _strict_bool(self.training, "capability request training")
        if not isinstance(self.metadata, EvaluationContext):
            raise KernelContractError("capability request metadata must be an EvaluationContext")


@dataclass(frozen=True, slots=True)
class CapabilityViolation(ContractModel):
    code: str
    message: str
    version: int = 1

    def __post_init__(self) -> None:
        if not isinstance(self.code, str) or _CODE.fullmatch(self.code) is None:
            raise KernelContractError("capability violation code is invalid")
        _message(self.message, "capability violation message")
        _v1(self.version, "CapabilityViolation")


@dataclass(frozen=True, slots=True)
class CapabilityDecision(ContractModel):
    supported: bool
    violations: tuple[CapabilityViolation, ...]
    version: int = 1

    def __post_init__(self) -> None:
        _strict_bool(self.supported, "capability decision supported")
        if not isinstance(self.violations, tuple) or not all(
            isinstance(violation, CapabilityViolation) for violation in self.violations
        ):
            raise KernelContractError(
                "capability decision violations must contain CapabilityViolation"
            )
        _v1(self.version, "CapabilityDecision")
        if self.supported is bool(self.violations):
            raise KernelContractError(
                "capability decision is supported exactly when violations are empty"
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
        _v1(self.version, "CapabilityEnvelope")
        for label, values in (
            ("architectures", self.architectures),
            ("dtypes", self.dtypes),
            ("layouts", self.layouts),
            ("modes", self.modes),
        ):
            normalized = _token_tuple(values, f"capability {label}", nonempty=True)
            object.__setattr__(self, label, normalized)
        if not isinstance(self.constraints, tuple) or not all(
            isinstance(constraint, DimensionConstraint) for constraint in self.constraints
        ):
            raise KernelContractError(
                "capability constraints must be a tuple of DimensionConstraint"
            )
        ordered_constraints = tuple(sorted(self.constraints, key=lambda item: item.code))
        object.__setattr__(self, "constraints", ordered_constraints)
        _unique(tuple(constraint.code for constraint in ordered_constraints), "constraint codes")
        if not isinstance(self.tensor_constraints, tuple) or not all(
            isinstance(constraint, TensorCapabilityConstraint)
            for constraint in self.tensor_constraints
        ):
            raise KernelContractError(
                "tensor_constraints must be a tuple of TensorCapabilityConstraint"
            )
        ordered_tensor_constraints = tuple(
            sorted(self.tensor_constraints, key=lambda item: item.argument)
        )
        object.__setattr__(self, "tensor_constraints", ordered_tensor_constraints)
        _unique(
            tuple(constraint.argument for constraint in ordered_tensor_constraints),
            "tensor capability argument identities",
        )
        _strict_bool(self.graph_capture_safe, "capability graph_capture_safe")
        _strict_bool(self.training_capable, "capability training_capable")

    def evaluate(self, request: CapabilityRequest) -> CapabilityDecision:
        if not isinstance(request, CapabilityRequest):
            raise KernelContractError("capability request must be a CapabilityRequest")
        violations: list[CapabilityViolation] = []
        for field, supported, code in (
            ("architecture", self.architectures, "UNSUPPORTED_ARCHITECTURE"),
            ("dtype", self.dtypes, "UNSUPPORTED_DTYPE"),
            ("layout", self.layouts, "UNSUPPORTED_LAYOUT"),
            ("mode", self.modes, "UNSUPPORTED_MODE"),
        ):
            value = getattr(request, field)
            if value not in supported:
                violations.append(
                    CapabilityViolation(
                        code,
                        f"requested {field} {value!r} is outside {list(supported)!r}",
                    )
                )
        if request.graph_capture and not self.graph_capture_safe:
            violations.append(
                CapabilityViolation(
                    "GRAPH_CAPTURE_UNSAFE",
                    "requested graph capture is outside this capability envelope",
                )
            )
        if request.training and not self.training_capable:
            violations.append(
                CapabilityViolation(
                    "TRAINING_UNSUPPORTED",
                    "requested training is outside this capability envelope",
                )
            )
        for constraint in self.tensor_constraints:
            metadata = request.metadata.tensors.get(constraint.argument)
            if metadata is None:
                violations.append(
                    CapabilityViolation(
                        "TENSOR_ARGUMENT_MISSING",
                        f"tensor metadata is missing argument {constraint.argument!r}",
                    )
                )
                continue
            for label, actual, supported, code in (
                ("dtype", metadata.dtype, constraint.dtypes, "TENSOR_DTYPE_UNSUPPORTED"),
                ("layout", metadata.layout, constraint.layouts, "TENSOR_LAYOUT_UNSUPPORTED"),
                (
                    "device",
                    metadata.device.split(":", 1)[0],
                    constraint.devices,
                    "TENSOR_DEVICE_UNSUPPORTED",
                ),
                ("rank", len(metadata.shape), constraint.ranks, "TENSOR_RANK_UNSUPPORTED"),
            ):
                if supported and actual not in supported:
                    violations.append(
                        CapabilityViolation(
                            code,
                            f"tensor {constraint.argument!r} {label} {actual!r} "
                            f"is outside {list(supported)!r}",
                        )
                    )
        for constraint in self.constraints:
            try:
                satisfied = constraint.predicate.evaluate(request.metadata)
            except ExpressionEvaluationError as exc:
                violations.append(
                    CapabilityViolation(
                        constraint.code,
                        f"{constraint.message}; evaluation failed: {exc}",
                    )
                )
            else:
                if not satisfied:
                    violations.append(
                        CapabilityViolation(constraint.code, constraint.message)
                    )
        return CapabilityDecision(not violations, tuple(violations))

    def render(self) -> str:
        axes = (
            f"architectures={list(self.architectures)!r}; "
            f"dtypes={list(self.dtypes)!r}; layouts={list(self.layouts)!r}; "
            f"modes={list(self.modes)!r}; graph_capture_safe={self.graph_capture_safe}; "
            f"training_capable={self.training_capable}"
        )
        tensors = "; ".join(
            f"{item.argument}(dtypes={list(item.dtypes)!r}, "
            f"layouts={list(item.layouts)!r}, devices={list(item.devices)!r}, "
            f"ranks={list(item.ranks)!r})"
            for item in self.tensor_constraints
        )
        constraints = "; ".join(item.render() for item in self.constraints)
        return f"CapabilityEnvelope({axes}; tensors=[{tensors}]; constraints=[{constraints}])"
