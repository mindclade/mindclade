"""Pairformer triangle-multiplication facade, contract, reference, and builder."""

from .dispatch import NativeOperatorUnavailable, ReferenceFallback, triangle_multiplication
from .reference import triangle_multiplication_reference
from .spec import KERNEL_SPEC
from .tilelang import build_tilelang_program

__all__ = (
    "KERNEL_SPEC",
    "NativeOperatorUnavailable",
    "ReferenceFallback",
    "build_tilelang_program",
    "triangle_multiplication",
    "triangle_multiplication_reference",
)
