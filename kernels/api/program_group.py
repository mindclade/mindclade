"""Physical TileLang program DAG and explicit workspace contracts."""

from __future__ import annotations

from dataclasses import dataclass

from .errors import KernelContractError
from .expressions import DTypeExpr, Expr, ShapeExpr
from .output import ContractModel, _nonempty, _unique


@dataclass(frozen=True, slots=True)
class WorkspaceSpec(ContractModel):
    name: str
    shape: ShapeExpr
    dtype: DTypeExpr
    zero_initialize: bool = False
    lifetime: str = "program_group"
    version: int = 1

    def __post_init__(self) -> None:
        _nonempty(self.name, "workspace name")
        if self.version != 1:
            raise KernelContractError(f"unsupported WorkspaceSpec version: {self.version}")
        if not isinstance(self.shape, (Expr, tuple)):
            raise KernelContractError("workspace shape must be a typed shape expression")
        if isinstance(self.shape, tuple) and not all(isinstance(item, Expr) for item in self.shape):
            raise KernelContractError("every workspace shape dimension must be a typed expression")
        if not isinstance(self.dtype, Expr):
            raise KernelContractError("workspace dtype must be a typed dtype expression")
        if self.lifetime not in {"node", "program_group"}:
            raise KernelContractError(f"unsupported workspace lifetime: {self.lifetime}")


@dataclass(frozen=True, slots=True)
class ProgramNodeSpec(ContractModel):
    name: str
    builder: str
    symbol: str
    depends_on: tuple[str, ...] = ()
    workspaces: tuple[WorkspaceSpec, ...] = ()
    version: int = 1

    def __post_init__(self) -> None:
        _nonempty(self.name, "program node name")
        _nonempty(self.builder, "program node builder")
        _nonempty(self.symbol, "program node symbol")
        if self.version != 1:
            raise KernelContractError(f"unsupported ProgramNodeSpec version: {self.version}")
        if ":" not in self.builder:
            raise KernelContractError("program node builder must be a module:function identity")
        _unique(self.depends_on, "program node dependencies")
        _unique(tuple(workspace.name for workspace in self.workspaces), "program node workspaces")


@dataclass(frozen=True, slots=True)
class ProgramGroupSpec(ContractModel):
    nodes: tuple[ProgramNodeSpec, ...]
    current_stream_only: bool = True
    global_synchronization: bool = False
    hidden_device_allocation: bool = False
    graph_capture_safe: bool = True
    version: int = 1

    def __post_init__(self) -> None:
        if self.version != 1:
            raise KernelContractError(f"unsupported ProgramGroupSpec version: {self.version}")
        if not self.nodes:
            raise KernelContractError("program group must contain at least one node")
        names = tuple(node.name for node in self.nodes)
        symbols = tuple(node.symbol for node in self.nodes)
        _unique(names, "program node names")
        _unique(symbols, "program node symbols")
        known = set(names)
        for node in self.nodes:
            unknown = set(node.depends_on) - known
            if unknown:
                raise KernelContractError(
                    f"program node {node.name!r} has unknown dependencies: {sorted(unknown)}"
                )
            if node.name in node.depends_on:
                raise KernelContractError(f"program node {node.name!r} depends on itself")
        self.topological_order()
        if self.current_stream_only and self.global_synchronization:
            raise KernelContractError("current-stream program group cannot globally synchronize")
        if self.graph_capture_safe and self.global_synchronization:
            raise KernelContractError("capture-safe program group cannot globally synchronize")
        if self.graph_capture_safe and self.hidden_device_allocation:
            raise KernelContractError("capture-safe program group cannot hide device allocation")

    def topological_order(self) -> tuple[str, ...]:
        """Return a deterministic dependency order, rejecting cycles."""

        pending = {node.name: set(node.depends_on) for node in self.nodes}
        ordered: list[str] = []
        while pending:
            ready = sorted(name for name, dependencies in pending.items() if not dependencies)
            if not ready:
                raise KernelContractError(
                    f"program group dependency cycle: {sorted(pending)}"
                )
            ordered.extend(ready)
            for name in ready:
                del pending[name]
            for dependencies in pending.values():
                dependencies.difference_update(ready)
        return tuple(ordered)
