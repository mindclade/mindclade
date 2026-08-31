# Copyright (c) 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

"""Pairformer triangle-attention facade, contract, reference, and builder."""

from .dispatch import NativeOperatorUnavailable, ReferenceFallback, triangle_attention
from .reference import triangle_attention_reference
from .spec import KERNEL_SPEC
from .tilelang import TRIANGLE_ATTENTION_PROFILES, build_tilelang_program

__all__ = (
    "KERNEL_SPEC",
    "NativeOperatorUnavailable",
    "ReferenceFallback",
    "TRIANGLE_ATTENTION_PROFILES",
    "build_tilelang_program",
    "triangle_attention",
    "triangle_attention_reference",
)
