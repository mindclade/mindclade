"""Deterministic build-time view over import-free discovered declarations."""

from __future__ import annotations

from collections.abc import Iterable
import re

from kernels.api import KernelSpec
from kernels.native.codegen.discover import DiscoveredKernelSpec
from kernels.native.tilelang.model import NAMESPACE

_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")


def registry(discovered: Iterable[DiscoveredKernelSpec]) -> tuple[KernelSpec, ...]:
    """Unwrap and validate canonical API specs in stable operator order.

    Accepting discovery results rather than bare specs keeps declaration-file
    identity attached to the only supported source inventory.
    """

    specs: list[KernelSpec] = []
    names: set[str] = set()
    sources: set[str] = set()
    for entry in discovered:
        if not isinstance(entry, DiscoveredKernelSpec):
            raise TypeError("registry accepts only DiscoveredKernelSpec entries")
        if _DIGEST.fullmatch(entry.declaration_sha256) is None:
            raise ValueError(
                f"{entry.spec.source}: declaration digest must use sha256:<64 lowercase hex>"
            )
        spec = entry.spec
        if not isinstance(spec, KernelSpec):
            raise TypeError("discovered entry does not contain kernels.api.KernelSpec")
        if spec.namespace != NAMESPACE or spec.qualified_name != f"{NAMESPACE}::{spec.name}":
            raise ValueError("registry accepts only mindclade namespace specifications")
        if spec.qualified_name in names:
            raise ValueError(f"duplicate kernel name: {spec.qualified_name}")
        if spec.source in sources:
            raise ValueError(f"duplicate kernel declaration source: {spec.source}")
        names.add(spec.qualified_name)
        sources.add(spec.source)
        specs.append(spec)
    return tuple(sorted(specs, key=lambda spec: (spec.qualified_name, spec.source)))
