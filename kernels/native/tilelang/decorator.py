from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import Any, TypeVar

from kernels.native.tilelang.model import (
    AutogradPolicy,
    BACKEND,
    CallableRef,
    KernelSpec,
    NAMESPACE,
)

F = TypeVar("F", bound=Callable[..., Any])
_ZERO_DIGEST = "sha256:" + "0" * 64


def mindclade_kernel(
    *,
    name: str,
    schema: str,
    family: str,
    fake: Mapping[str, object],
    autograd: Mapping[str, object],
    namespace: str = NAMESPACE,
    backend: str = BACKEND,
    version: int = 1,
    launch_symbol: str | None = None,
    devices: Iterable[str] = ("cuda",),
) -> Callable[[F], F]:
    """Validate and attach non-authoritative developer metadata.

    Build authority comes only from literal AST declarations in explicitly
    declared Bazel source inputs. Executing this decorator never discovers or
    registers an operator.
    """

    validated = KernelSpec(
        name=name,
        schema=schema,
        family=family,
        source=f"{family}/{name}/tilelang.py",
        source_sha256=_ZERO_DIGEST,
        fake=CallableRef.from_mapping(fake, field="fake"),
        autograd=AutogradPolicy.from_mapping(autograd),
        namespace=namespace,
        backend=backend,
        version=version,
        launch_symbol=launch_symbol,
        devices=tuple(devices),
    )
    metadata = {
        "name": validated.name,
        "schema": validated.schema,
        "family": validated.family,
        "fake": validated.fake.to_manifest(),
        "autograd": validated.autograd.to_manifest(),
        "namespace": validated.namespace,
        "backend": validated.backend,
        "version": validated.version,
        "launch_symbol": validated.launch_symbol,
        "devices": validated.devices,
    }

    def decorate(function: F) -> F:
        setattr(function, "__mindclade_kernel__", metadata)
        return function

    return decorate
