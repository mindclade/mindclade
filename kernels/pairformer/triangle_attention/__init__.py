# Copyright (c) 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

"""Operation-local triangle-attention contract and reference implementation."""

from kernels.pairformer.triangle_attention.tilelang import (
    TRIANGLE_ATTENTION_PROFILES,
    backward,
    build_tilelang_program,
    fake,
    setup_context,
    triangle_attention_reference,
)

__all__ = (
    "TRIANGLE_ATTENTION_PROFILES",
    "backward",
    "build_tilelang_program",
    "fake",
    "setup_context",
    "triangle_attention_reference",
)
