# Copyright (c) 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

"""Explicit, process-isolated reference runtime for source development.

This module never registers operators at import time. Enabling it is irreversible
for the current process and mutually exclusive with loading a native bundle.
Every operator remains available only through ``torch.ops.mindclade``.
"""

from __future__ import annotations

import importlib
import os
from threading import Lock
from typing import Any

_ENABLE_ENV = "MINDCLADE_NATIVE_REFERENCE_RUNTIME"
_LOCK = Lock()
_LIBRARY: Any | None = None

_OPERATORS = (
    (
        "outer_product_mean",
        "outer_product_mean(Tensor left, Tensor right, Tensor mask, float epsilon) -> Tensor",
        "kernels.pairformer.outer_product_mean.tilelang",
        "outer_product_mean_reference",
    ),
    (
        "pair_weighted_average",
        "pair_weighted_average(Tensor value, Tensor weights, Tensor mask, float epsilon) -> Tensor",
        "kernels.pairformer.pair_weighted_average.tilelang",
        "_reference",
    ),
    (
        "triangle_attention",
        "triangle_attention(Tensor q, Tensor k, Tensor v, Tensor bias, Tensor mask, float scale) -> Tensor",
        "kernels.pairformer.triangle_attention.tilelang",
        "triangle_attention_reference",
    ),
    (
        "triangle_multiplication",
        "triangle_multiplication(Tensor left, Tensor right, Tensor mask, bool outgoing) -> Tensor",
        "kernels.pairformer.triangle_multiplication.tilelang",
        "reference",
    ),
    (
        "transition",
        "transition(Tensor gate, Tensor value, Tensor output_weight, Tensor output_bias, Tensor mask) -> Tensor",
        "kernels.pairformer.transition.tilelang",
        "transition_reference",
    ),
)


def _operator_exists(torch: Any, name: str) -> bool:
    try:
        getattr(torch.ops.mindclade, name).default
    except AttributeError:
        return False
    return True


def enable_reference_runtime() -> tuple[Any, ...]:
    """Register the five unqualified references under ``torch.ops.mindclade``.

    The caller must set ``MINDCLADE_NATIVE_REFERENCE_RUNTIME=1`` explicitly.
    A process that enables this mode must not subsequently load a native bundle.
    """

    global _LIBRARY
    if os.environ.get(_ENABLE_ENV) != "1":
        raise RuntimeError(f"reference runtime requires explicit {_ENABLE_ENV}=1")

    import torch

    with _LOCK:
        if _LIBRARY is not None:
            return tuple(getattr(torch.ops.mindclade, name).default for name, *_ in _OPERATORS)
        occupied = [name for name, *_ in _OPERATORS if _operator_exists(torch, name)]
        if occupied:
            raise RuntimeError(
                "reference runtime cannot coexist with registered native schemas: "
                + ", ".join(sorted(occupied))
            )

        library = torch.library.Library("mindclade", "DEF")
        implementations: list[tuple[str, Any]] = []
        for name, schema, module_name, symbol in _OPERATORS:
            implementation = getattr(importlib.import_module(module_name), symbol)
            if not callable(implementation):
                raise RuntimeError(f"reference implementation is not callable: {module_name}.{symbol}")
            library.define(schema)
            implementations.append((name, implementation))
        for name, implementation in implementations:
            library.impl(name, implementation, "CompositeImplicitAutograd")
        _LIBRARY = library
        return tuple(getattr(torch.ops.mindclade, name).default for name, *_ in _OPERATORS)


def reference_runtime_enabled() -> bool:
    """Return whether this process owns the explicit reference registrations."""

    return _LIBRARY is not None
