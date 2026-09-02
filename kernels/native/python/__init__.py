# Copyright (c) 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

"""Lazy public native API; operators remain exclusively under ``torch.ops``.

Build and qualification tools must be importable without importing Torch. The
runtime modules are therefore resolved only when a public attribute is first
requested.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

_CAPABILITY_EXPORTS = frozenset(
    {
        "CapabilityIndexError",
        "CapabilityRequest",
        "DispatchReceipt",
        "NativeCapabilityRow",
        "NativeCapabilityTable",
        "NativeCapabilityTableIdentity",
        "VerifiedCapabilityIndex",
        "load_native_capability_table",
        "load_native_capability_table_identity",
        "load_signed_capability_index",
        "reconcile_exported_native_capability_identity",
        "reconcile_signed_native_capability_table",
    }
)
_LOADER_EXPORTS = frozenset(
    {
        "BundleActivationPolicy",
        "BundleTrustDecision",
        "NativeBundleDescriptor",
        "NativeBundleError",
        "NativeBundleLoadError",
        "NativeBundleStateError",
        "NativeBundleVerificationError",
        "NativeOperatorRegistrationError",
        "load_native_library",
    }
)

__all__ = sorted(_CAPABILITY_EXPORTS | _LOADER_EXPORTS)


def __getattr__(name: str) -> Any:
    if name in _CAPABILITY_EXPORTS:
        module_name = "capability_index"
    elif name in _LOADER_EXPORTS:
        module_name = "loader"
    else:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(f"{__name__}.{module_name}"), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
