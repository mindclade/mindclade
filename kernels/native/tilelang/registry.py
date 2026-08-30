from __future__ import annotations

from collections.abc import Iterable

from kernels.native.tilelang.model import KernelSpec, NAMESPACE


def registry(specs: Iterable[KernelSpec]) -> tuple[KernelSpec, ...]:
    """Return a deterministic validated build-time registry.

    This helper deliberately accepts specs rather than discovering files or
    loading modules. Runtime discovery is not part of the native contract.
    """

    ordered = tuple(sorted(specs, key=lambda spec: spec.qualified_name))
    names: set[str] = set()
    for spec in ordered:
        if spec.namespace != NAMESPACE or spec.qualified_name != f"{NAMESPACE}::{spec.name}":
            raise ValueError("registry accepts only mindclade namespace specifications")
        if spec.qualified_name in names:
            raise ValueError(f"duplicate kernel name: {spec.qualified_name}")
        names.add(spec.qualified_name)
    return ordered
