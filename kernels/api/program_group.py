"""Physical TileLang program DAG and explicit workspace contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re

from .errors import KernelContractError
from .expressions import DTypeExpr, Expr, ExprDomain, ShapeExpr
from .output import ContractModel, _nonempty, _unique

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _v1(value: object, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value != 1:
        raise KernelContractError(f"{label} version must be exactly integer 1")


def _identifier(value: str, label: str) -> None:
    _nonempty(value, label)
    if _IDENTIFIER.fullmatch(value) is None:
        raise KernelContractError(f"{label} must be an identifier")


def _builder_identity(value: str, label: str) -> None:
    _nonempty(value, label)
    if value.count(":") != 1:
        raise KernelContractError(f"{label} must be one module:function identity")
    module, function = value.split(":", 1)
    if not function.isidentifier() or not module or not all(
        component.isidentifier() for component in module.split(".")
    ):
        raise KernelContractError(f"{label} must be one module:function identity")


class WorkspaceLifetime(StrEnum):
    NODE = "node"
    PROGRAM_GROUP = "program_group"


class WorkspaceAccess(StrEnum):
    READ = "read"
    WRITE = "write"
    READ_WRITE = "read_write"


@dataclass(frozen=True, slots=True)
class WorkspaceSpec(ContractModel):
    name: str
    shape: ShapeExpr
    dtype: DTypeExpr
    zero_initialize: bool = False
    lifetime: WorkspaceLifetime = WorkspaceLifetime.PROGRAM_GROUP
    version: int = 1

    def __post_init__(self) -> None:
        _identifier(self.name, "workspace name")
        _v1(self.version, "WorkspaceSpec")
        if not isinstance(self.shape, Expr) or self.shape.domain is not ExprDomain.SHAPE:
            raise KernelContractError("workspace shape must be a SHAPE-domain expression")
        if not isinstance(self.dtype, Expr) or self.dtype.domain is not ExprDomain.DTYPE:
            raise KernelContractError("workspace dtype must be a typed dtype expression")
        if type(self.zero_initialize) is not bool:
            raise KernelContractError("workspace zero_initialize must be a bool")
        if not isinstance(self.lifetime, WorkspaceLifetime):
            raise KernelContractError("workspace lifetime must be a WorkspaceLifetime")


@dataclass(frozen=True, slots=True)
class WorkspaceUseSpec(ContractModel):
    workspace: str
    access: WorkspaceAccess
    version: int = 1

    def __post_init__(self) -> None:
        _identifier(self.workspace, "workspace use")
        if not isinstance(self.access, WorkspaceAccess):
            raise KernelContractError("workspace access must be a WorkspaceAccess")
        _v1(self.version, "WorkspaceUseSpec")


@dataclass(frozen=True, slots=True)
class ProgramNodeSpec(ContractModel):
    name: str
    builder: str
    symbol: str
    depends_on: tuple[str, ...] = ()
    workspace_uses: tuple[WorkspaceUseSpec, ...] = ()
    version: int = 1

    def __post_init__(self) -> None:
        _identifier(self.name, "program node name")
        _builder_identity(self.builder, "program node builder")
        _identifier(self.symbol, "program node symbol")
        _v1(self.version, "ProgramNodeSpec")
        if not isinstance(self.depends_on, tuple) or not all(
            isinstance(item, str) for item in self.depends_on
        ):
            raise KernelContractError("program node dependencies must be a tuple of names")
        for dependency in self.depends_on:
            _identifier(dependency, "program node dependency")
        ordered_dependencies = tuple(sorted(self.depends_on))
        object.__setattr__(self, "depends_on", ordered_dependencies)
        _unique(ordered_dependencies, "program node dependencies")
        if not isinstance(self.workspace_uses, tuple) or not all(
            isinstance(item, WorkspaceUseSpec) for item in self.workspace_uses
        ):
            raise KernelContractError("program node workspace_uses must contain WorkspaceUseSpec")
        ordered_uses = tuple(sorted(self.workspace_uses, key=lambda item: item.workspace))
        object.__setattr__(self, "workspace_uses", ordered_uses)
        _unique(tuple(item.workspace for item in ordered_uses), "program node workspace uses")


@dataclass(frozen=True, slots=True)
class ProgramGroupSpec(ContractModel):
    nodes: tuple[ProgramNodeSpec, ...]
    workspaces: tuple[WorkspaceSpec, ...] = ()
    version: int = 1

    def __post_init__(self) -> None:
        _v1(self.version, "ProgramGroupSpec")
        if not isinstance(self.nodes, tuple) or not self.nodes or not all(
            isinstance(node, ProgramNodeSpec) for node in self.nodes
        ):
            raise KernelContractError("program group must contain at least one node")
        if not isinstance(self.workspaces, tuple) or not all(
            isinstance(workspace, WorkspaceSpec) for workspace in self.workspaces
        ):
            raise KernelContractError("program group workspaces must contain WorkspaceSpec")
        ordered_workspaces = tuple(sorted(self.workspaces, key=lambda item: item.name))
        object.__setattr__(self, "workspaces", ordered_workspaces)
        names = tuple(node.name for node in self.nodes)
        symbols = tuple(node.symbol for node in self.nodes)
        _unique(names, "program node names")
        _unique(symbols, "program node symbols")
        _unique(tuple(workspace.name for workspace in ordered_workspaces), "workspace names")
        known = set(names)
        for node in self.nodes:
            unknown = set(node.depends_on) - known
            if unknown:
                raise KernelContractError(
                    f"program node {node.name!r} has unknown dependencies: {sorted(unknown)}"
                )
            if node.name in node.depends_on:
                raise KernelContractError(f"program node {node.name!r} depends on itself")
        order = self.topological_order()
        by_name = {node.name: node for node in self.nodes}
        object.__setattr__(self, "nodes", tuple(by_name[name] for name in order))
        self._validate_workspace_plan()

    def _validate_workspace_plan(self) -> None:
        declared = {workspace.name: workspace for workspace in self.workspaces}
        users: dict[str, list[tuple[str, WorkspaceAccess]]] = {
            name: [] for name in declared
        }
        for node in self.nodes:
            for use in node.workspace_uses:
                if use.workspace not in declared:
                    raise KernelContractError(
                        f"program node {node.name!r} uses undeclared workspace {use.workspace!r}"
                    )
                users[use.workspace].append((node.name, use.access))
        unused = sorted(name for name, items in users.items() if not items)
        if unused:
            raise KernelContractError(f"program group has unused workspaces: {unused}")

        dependencies = {node.name: set(node.depends_on) for node in self.nodes}

        def transitively_depends(node: str, dependency: str) -> bool:
            pending = list(dependencies[node])
            visited: set[str] = set()
            while pending:
                current = pending.pop()
                if current == dependency:
                    return True
                if current not in visited:
                    visited.add(current)
                    pending.extend(dependencies[current])
            return False

        for name, workspace in declared.items():
            accesses = users[name]
            if workspace.lifetime is WorkspaceLifetime.NODE and len(accesses) != 1:
                raise KernelContractError(
                    f"node-lifetime workspace {name!r} must have exactly one using node"
                )
            writers = [
                node
                for node, access in accesses
                if access in {WorkspaceAccess.WRITE, WorkspaceAccess.READ_WRITE}
            ]
            if len(writers) > 1:
                raise KernelContractError(f"workspace {name!r} has multiple writers")
            if not writers and not workspace.zero_initialize:
                raise KernelContractError(
                    f"non-zero-initialized workspace {name!r} requires a writer"
                )
            if writers:
                writer = writers[0]
                for reader, access in accesses:
                    if reader == writer or access is WorkspaceAccess.WRITE:
                        continue
                    if not transitively_depends(reader, writer):
                        raise KernelContractError(
                            f"workspace reader {reader!r} must transitively depend on "
                            f"writer {writer!r} for {name!r}"
                        )

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
