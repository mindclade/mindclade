"""Typed callable program-group and workspace contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import heapq
import re

from .errors import KernelContractError
from .expressions import DTypeExpr, DeviceExpr, Expr, ExprDomain, ShapeExpr
from .output import ContractModel

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
_C_SYMBOL = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,255}$")
_SELECTOR_VALUE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_BUILDER = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*:"
    r"[A-Za-z_][A-Za-z0-9_]{0,127}$"
)
_MAX_PARAMETERS = 256


def _strict_version(value: object, label: str) -> None:
    if type(value) is not int or value != 1:
        raise KernelContractError(f"{label} version must be the integer 1")


def _identifier(value: object, label: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise KernelContractError(f"{label} must be a C identifier")
    return value


def _expression(value: object, domain: ExprDomain, label: str) -> Expr:
    if not isinstance(value, Expr) or value.domain is not domain:
        raise KernelContractError(f"{label} must be a {domain.value} expression")
    return value


class WorkspaceLifetime(StrEnum):
    NODE = "node"
    PROGRAM_GROUP = "program_group"


class WorkspaceAccess(StrEnum):
    READ = "read"
    WRITE = "write"
    READ_WRITE = "read_write"


class ProgramParameterKind(StrEnum):
    TENSOR = "tensor"
    SCALAR = "scalar"
    STREAM = "stream"


class ProgramBindingSource(StrEnum):
    OPERATOR_ARGUMENT = "operator_argument"
    OUTPUT_GRADIENT = "output_gradient"
    FORWARD_OUTPUT = "forward_output"
    PROVIDER_OUTPUT = "provider_output"
    WORKSPACE = "workspace"
    GRADIENT_REQUEST = "gradient_request"
    CURRENT_STREAM = "current_stream"


class ScalarABIType(StrEnum):
    BOOL = "bool"
    INT64 = "int64"
    FLOAT64 = "float64"


class ProgramReturnABI(StrEnum):
    STATUS_I32_ZERO_SUCCESS = "status_i32_zero_success"


class ProgramEntryABI(StrEnum):
    TILELANG_0_1_13_HOST_CALL = "tilelang_0_1_13_host_call"


class ProgramArtifactBoundary(StrEnum):
    NODE_CONTENT_ADDRESSED_DSO = "node_content_addressed_dso"


@dataclass(frozen=True, slots=True)
class WorkspaceSpec(ContractModel):
    name: str
    shape: ShapeExpr
    dtype: DTypeExpr
    zero_initialize: bool = False
    lifetime: WorkspaceLifetime = WorkspaceLifetime.PROGRAM_GROUP
    version: int = 1

    def __post_init__(self) -> None:
        _strict_version(self.version, "WorkspaceSpec")
        _identifier(self.name, "workspace name")
        _expression(self.shape, ExprDomain.SHAPE, "workspace shape")
        _expression(self.dtype, ExprDomain.DTYPE, "workspace dtype")
        if type(self.zero_initialize) is not bool:
            raise KernelContractError("workspace zero_initialize must be bool")
        if not isinstance(self.lifetime, WorkspaceLifetime):
            raise KernelContractError("workspace lifetime must be WorkspaceLifetime")


@dataclass(frozen=True, slots=True)
class ProgramParameterSpec(ContractModel):
    position: int
    name: str
    kind: ProgramParameterKind
    access: WorkspaceAccess
    shape: ShapeExpr | None = None
    dtype: DTypeExpr | None = None
    device: DeviceExpr | None = None
    scalar_type: ScalarABIType | None = None
    optional: bool = False
    version: int = 1

    def __post_init__(self) -> None:
        _strict_version(self.version, "ProgramParameterSpec")
        if type(self.position) is not int or not 0 <= self.position < _MAX_PARAMETERS:
            raise KernelContractError(
                f"program parameter position must be in [0, {_MAX_PARAMETERS - 1}]"
            )
        _identifier(self.name, "program parameter name")
        if not isinstance(self.kind, ProgramParameterKind):
            raise KernelContractError("program parameter kind must be ProgramParameterKind")
        if not isinstance(self.access, WorkspaceAccess):
            raise KernelContractError("program parameter access must be WorkspaceAccess")
        if type(self.optional) is not bool:
            raise KernelContractError("program parameter optional must be bool")

        tensor_metadata = (self.shape, self.dtype, self.device)
        if self.kind is ProgramParameterKind.TENSOR:
            if any(value is None for value in tensor_metadata):
                raise KernelContractError(
                    "tensor program parameters require shape, dtype, and device expressions"
                )
            _expression(self.shape, ExprDomain.SHAPE, "program parameter shape")
            _expression(self.dtype, ExprDomain.DTYPE, "program parameter dtype")
            _expression(self.device, ExprDomain.DEVICE, "program parameter device")
            if self.scalar_type is not None:
                raise KernelContractError("tensor program parameters cannot declare scalar_type")
            return
        if any(value is not None for value in tensor_metadata):
            raise KernelContractError(
                "non-tensor program parameters cannot declare tensor metadata"
            )
        if self.kind is ProgramParameterKind.SCALAR:
            if not isinstance(self.scalar_type, ScalarABIType):
                raise KernelContractError("scalar program parameters require ScalarABIType")
            return
        if self.scalar_type is not None:
            raise KernelContractError("stream program parameters cannot declare scalar_type")
        if self.access is not WorkspaceAccess.READ or self.optional:
            raise KernelContractError("stream program parameters must be required read-only values")


@dataclass(frozen=True, slots=True)
class ProgramBindingSpec(ContractModel):
    parameter: str
    source: ProgramBindingSource
    source_name: str | None = None
    version: int = 1

    def __post_init__(self) -> None:
        _strict_version(self.version, "ProgramBindingSpec")
        _identifier(self.parameter, "program binding parameter")
        if not isinstance(self.source, ProgramBindingSource):
            raise KernelContractError("program binding source must be ProgramBindingSource")
        if self.source is ProgramBindingSource.CURRENT_STREAM:
            if self.source_name is not None:
                raise KernelContractError("current-stream binding cannot declare source_name")
        else:
            _identifier(self.source_name, "program binding source_name")


@dataclass(frozen=True, slots=True)
class ProgramSelectorBinding(ContractModel):
    provider_argument: str
    selector_key: str
    scalar_type: ScalarABIType
    cases: tuple[tuple[bool, str], ...]
    version: int = 1

    def __post_init__(self) -> None:
        _strict_version(self.version, "ProgramSelectorBinding")
        _identifier(self.provider_argument, "selector provider_argument")
        if self.selector_key != "mode":
            raise KernelContractError("callable ABI v1 supports only the mode selector key")
        if self.scalar_type is not ScalarABIType.BOOL:
            raise KernelContractError("callable ABI v1 selector arguments must be BOOL")
        if not isinstance(self.cases, tuple):
            raise KernelContractError("selector cases must be a tuple")
        expected = ((False, "incoming"), (True, "outgoing"))
        if self.cases != expected:
            raise KernelContractError(
                "BOOL mode selector cases must be canonical and total: "
                "((False, 'incoming'), (True, 'outgoing'))"
            )
        if any(_SELECTOR_VALUE.fullmatch(value) is None for _case, value in self.cases):
            raise KernelContractError("selector case values must be canonical mode tokens")


@dataclass(frozen=True, slots=True)
class ProgramNodeSpec(ContractModel):
    name: str
    builder: str
    symbol: str
    entry_symbol: str
    entry_abi: ProgramEntryABI
    parameters: tuple[ProgramParameterSpec, ...]
    bindings: tuple[ProgramBindingSpec, ...]
    depends_on: tuple[str, ...] = ()
    return_abi: ProgramReturnABI = ProgramReturnABI.STATUS_I32_ZERO_SUCCESS
    artifact_boundary: ProgramArtifactBoundary = (
        ProgramArtifactBoundary.NODE_CONTENT_ADDRESSED_DSO
    )
    version: int = 1

    def __post_init__(self) -> None:
        _strict_version(self.version, "ProgramNodeSpec")
        _identifier(self.name, "program node name")
        if not isinstance(self.builder, str) or _BUILDER.fullmatch(self.builder) is None:
            raise KernelContractError(
                "program node builder must be an operation-local tilelang module:function"
            )
        if not isinstance(self.symbol, str) or _C_SYMBOL.fullmatch(self.symbol) is None:
            raise KernelContractError("program node adapter symbol must be a C symbol")
        if not isinstance(self.entry_symbol, str) or _C_SYMBOL.fullmatch(self.entry_symbol) is None:
            raise KernelContractError("program node entry_symbol must be a C symbol")
        if self.symbol == self.entry_symbol:
            raise KernelContractError("program node adapter and raw entry symbols must differ")
        if not isinstance(self.entry_abi, ProgramEntryABI):
            raise KernelContractError("program node entry_abi must be ProgramEntryABI")
        if not isinstance(self.return_abi, ProgramReturnABI):
            raise KernelContractError("program node return_abi must be ProgramReturnABI")
        if not isinstance(self.artifact_boundary, ProgramArtifactBoundary):
            raise KernelContractError(
                "program node artifact_boundary must be ProgramArtifactBoundary"
            )
        if not isinstance(self.parameters, tuple) or not self.parameters:
            raise KernelContractError("program node parameters must be a non-empty tuple")
        if not isinstance(self.bindings, tuple) or not self.bindings:
            raise KernelContractError("program node bindings must be a non-empty tuple")
        if not isinstance(self.depends_on, tuple):
            raise KernelContractError("program node dependencies must be a tuple")

        parameters = tuple(sorted(self.parameters, key=lambda value: value.position))
        positions = tuple(value.position for value in parameters)
        if positions != tuple(range(len(parameters))):
            raise KernelContractError("program node parameter positions must be contiguous from zero")
        parameter_names = tuple(value.name for value in parameters)
        if len(parameter_names) != len(set(parameter_names)):
            raise KernelContractError("program node parameter names must be unique")
        bindings = tuple(sorted(self.bindings, key=lambda value: value.parameter))
        bound_names = tuple(value.parameter for value in bindings)
        if len(bound_names) != len(set(bound_names)):
            raise KernelContractError("program node parameters must have exactly one binding")
        if set(bound_names) != set(parameter_names):
            raise KernelContractError("program node bindings must cover every parameter exactly")
        dependencies = tuple(sorted(self.depends_on))
        if len(dependencies) != len(set(dependencies)):
            raise KernelContractError("program node dependencies must be unique")
        if self.name in dependencies:
            raise KernelContractError("program node cannot depend on itself")

        by_name = {value.name: value for value in parameters}
        stream_bindings = 0
        optional_provider_outputs: list[str] = []
        gradient_request_sources: list[str] = []
        for binding in bindings:
            parameter = by_name[binding.parameter]
            source = binding.source
            if source is ProgramBindingSource.CURRENT_STREAM:
                stream_bindings += 1
                if parameter.kind is not ProgramParameterKind.STREAM:
                    raise KernelContractError("current-stream binding requires a stream parameter")
            elif parameter.kind is ProgramParameterKind.STREAM:
                raise KernelContractError("stream parameter must bind CURRENT_STREAM")
            elif source is ProgramBindingSource.GRADIENT_REQUEST:
                gradient_request_sources.append(binding.source_name or "")
                if (
                    parameter.kind is not ProgramParameterKind.SCALAR
                    or parameter.scalar_type is not ScalarABIType.BOOL
                    or parameter.access is not WorkspaceAccess.READ
                ):
                    raise KernelContractError(
                        "gradient-request binding requires a read-only bool scalar parameter"
                    )
            elif source in {
                ProgramBindingSource.OUTPUT_GRADIENT,
                ProgramBindingSource.FORWARD_OUTPUT,
            }:
                if (
                    parameter.kind is not ProgramParameterKind.TENSOR
                    or parameter.access is not WorkspaceAccess.READ
                ):
                    raise KernelContractError(
                        f"{source.value} binding requires a read-only tensor parameter"
                    )
            elif source is ProgramBindingSource.PROVIDER_OUTPUT:
                if (
                    parameter.kind is not ProgramParameterKind.TENSOR
                    or parameter.access not in {WorkspaceAccess.WRITE, WorkspaceAccess.READ_WRITE}
                ):
                    raise KernelContractError(
                        "provider-output binding requires a writable tensor parameter"
                    )
                if parameter.optional:
                    optional_provider_outputs.append(binding.source_name or "")
            elif source is ProgramBindingSource.WORKSPACE:
                if parameter.kind is not ProgramParameterKind.TENSOR:
                    raise KernelContractError("workspace binding requires a tensor parameter")
        if stream_bindings != 1:
            raise KernelContractError("program node requires exactly one CURRENT_STREAM binding")
        if optional_provider_outputs:
            request_sources = set(gradient_request_sources)
            if len(gradient_request_sources) != 1 or len(request_sources) != 1:
                raise KernelContractError(
                    "optional provider outputs require one shared GRADIENT_REQUEST bool binding"
                )

        object.__setattr__(self, "parameters", parameters)
        object.__setattr__(self, "bindings", bindings)
        object.__setattr__(self, "depends_on", dependencies)

    @property
    def workspace_accesses(self) -> tuple[tuple[str, WorkspaceAccess], ...]:
        parameters = {value.name: value for value in self.parameters}
        return tuple(
            sorted(
                (
                    binding.source_name or "",
                    parameters[binding.parameter].access,
                )
                for binding in self.bindings
                if binding.source is ProgramBindingSource.WORKSPACE
            )
        )


def _topological_nodes(nodes: tuple[ProgramNodeSpec, ...]) -> tuple[ProgramNodeSpec, ...]:
    by_name = {node.name: node for node in nodes}
    if len(by_name) != len(nodes):
        raise KernelContractError("program-group node names must be unique")
    indegree = {name: 0 for name in by_name}
    children = {name: [] for name in by_name}
    for node in nodes:
        for dependency in node.depends_on:
            if dependency not in by_name:
                raise KernelContractError(
                    f"program node {node.name!r} has unknown dependency {dependency!r}"
                )
            indegree[node.name] += 1
            children[dependency].append(node.name)
    ready = [name for name, degree in indegree.items() if degree == 0]
    heapq.heapify(ready)
    ordered: list[ProgramNodeSpec] = []
    while ready:
        name = heapq.heappop(ready)
        ordered.append(by_name[name])
        for child in sorted(children[name]):
            indegree[child] -= 1
            if indegree[child] == 0:
                heapq.heappush(ready, child)
    if len(ordered) != len(nodes):
        raise KernelContractError("program-group dependencies must be acyclic")
    return tuple(ordered)


def _transitive_dependencies(nodes: tuple[ProgramNodeSpec, ...]) -> dict[str, set[str]]:
    ancestors: dict[str, set[str]] = {}
    for node in nodes:
        values = set(node.depends_on)
        for dependency in node.depends_on:
            values.update(ancestors[dependency])
        ancestors[node.name] = values
    return ancestors


@dataclass(frozen=True, slots=True)
class ProgramGroupSpec(ContractModel):
    nodes: tuple[ProgramNodeSpec, ...]
    workspaces: tuple[WorkspaceSpec, ...] = ()
    selector_bindings: tuple[ProgramSelectorBinding, ...] = ()
    version: int = 1

    def __post_init__(self) -> None:
        _strict_version(self.version, "ProgramGroupSpec")
        if not isinstance(self.nodes, tuple) or not self.nodes:
            raise KernelContractError("program group nodes must be a non-empty tuple")
        if not isinstance(self.workspaces, tuple):
            raise KernelContractError("program group workspaces must be a tuple")
        if not isinstance(self.selector_bindings, tuple):
            raise KernelContractError("program group selector_bindings must be a tuple")
        selector_bindings = tuple(
            sorted(self.selector_bindings, key=lambda value: value.provider_argument)
        )
        selector_arguments = tuple(value.provider_argument for value in selector_bindings)
        selector_keys = tuple(value.selector_key for value in selector_bindings)
        if len(selector_arguments) != len(set(selector_arguments)):
            raise KernelContractError("selector provider arguments must be unique")
        if len(selector_keys) != len(set(selector_keys)):
            raise KernelContractError("program-group selector keys must be unique")
        workspaces = tuple(sorted(self.workspaces, key=lambda value: value.name))
        workspace_names = tuple(value.name for value in workspaces)
        if len(workspace_names) != len(set(workspace_names)):
            raise KernelContractError("program-group workspace names must be unique")
        nodes = _topological_nodes(self.nodes)

        adapter_symbols = tuple(node.symbol for node in nodes)
        if len(adapter_symbols) != len(set(adapter_symbols)):
            raise KernelContractError("program-group adapter symbols must be unique")

        declared = set(workspace_names)
        uses: dict[str, list[tuple[str, WorkspaceAccess]]] = {
            name: [] for name in workspace_names
        }
        for node in nodes:
            for workspace, access in node.workspace_accesses:
                if workspace not in declared:
                    raise KernelContractError(
                        f"program node {node.name!r} uses undeclared workspace {workspace!r}"
                    )
                uses[workspace].append((node.name, access))
        unused = sorted(name for name, values in uses.items() if not values)
        if unused:
            raise KernelContractError(f"program-group workspaces are unused: {unused}")

        ancestors = _transitive_dependencies(nodes)
        by_workspace = {workspace.name: workspace for workspace in workspaces}
        for name, values in uses.items():
            workspace = by_workspace[name]
            users = {node for node, _access in values}
            if workspace.lifetime is WorkspaceLifetime.NODE and len(users) != 1:
                raise KernelContractError(
                    f"node-lifetime workspace {name!r} must have exactly one user"
                )
            writers = [
                node
                for node, access in values
                if access in {WorkspaceAccess.WRITE, WorkspaceAccess.READ_WRITE}
            ]
            if len(writers) > 1:
                raise KernelContractError(f"workspace {name!r} has multiple writers")
            if not writers and not workspace.zero_initialize:
                raise KernelContractError(
                    f"workspace {name!r} requires a writer or deterministic zero initialization"
                )
            if writers:
                writer = writers[0]
                for reader, access in values:
                    if reader == writer or access is WorkspaceAccess.WRITE:
                        continue
                    if writer not in ancestors[reader]:
                        raise KernelContractError(
                            f"workspace reader {reader!r} must transitively depend on writer {writer!r}"
                        )

        object.__setattr__(self, "nodes", nodes)
        object.__setattr__(self, "workspaces", workspaces)
        object.__setattr__(self, "selector_bindings", selector_bindings)

    def topological_order(self) -> tuple[str, ...]:
        return tuple(node.name for node in self.nodes)
