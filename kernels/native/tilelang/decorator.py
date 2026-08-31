"""Fail-closed tombstone for the retired decorator declaration surface."""

from typing import NoReturn


def mindclade_kernel(*_args: object, **_kwargs: object) -> NoReturn:
    """Reject decorator metadata in favor of canonical ``spec.py`` contracts."""

    raise RuntimeError(
        "@mindclade_kernel is retired; declare one literal kernels.api.KernelSpec "
        "as KERNEL_SPEC in kernels/<family>/<operation>/spec.py"
    )


__all__ = ["mindclade_kernel"]
