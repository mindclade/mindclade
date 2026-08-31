"""Stable build-plane constants and the canonical kernel contract re-export.

``kernels.api.KernelSpec`` is the sole declaration authority. This module
exists only to keep native build metadata in one place; it must not grow a
second operator model.
"""

from kernels.api import KernelSpec

NAMESPACE = "mindclade"
BACKEND = "tilelang"
GENERATOR_ID = "kernels.native.codegen.generate"
GENERATOR_VERSION = 4
REGISTRATION_MODE = "build_time_generated"

__all__ = [
    "BACKEND",
    "GENERATOR_ID",
    "GENERATOR_VERSION",
    "KernelSpec",
    "NAMESPACE",
    "REGISTRATION_MODE",
]
