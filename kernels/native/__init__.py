# Copyright (c) 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

"""Verified runtime integration for Mindclade native operators.

Operator callables are intentionally not re-exported from Python. Activated
operators are available only through torch.ops.mindclade.
"""

from .python import (
    BundleActivationPolicy,
    BundleTrustDecision,
    CapabilityIndexError,
    CapabilityRequest,
    DispatchReceipt,
    NativeCapabilityRow,
    NativeCapabilityTable,
    NativeCapabilityTableIdentity,
    NativeBundleDescriptor,
    NativeBundleError,
    NativeBundleLoadError,
    NativeBundleStateError,
    NativeBundleVerificationError,
    NativeOperatorRegistrationError,
    VerifiedCapabilityIndex,
    load_native_capability_table,
    load_native_capability_table_identity,
    load_native_library,
    load_signed_capability_index,
    reconcile_exported_native_capability_identity,
    reconcile_signed_native_capability_table,
)

__all__ = [
    "BundleActivationPolicy",
    "BundleTrustDecision",
    "CapabilityIndexError",
    "CapabilityRequest",
    "DispatchReceipt",
    "NativeCapabilityRow",
    "NativeCapabilityTable",
    "NativeCapabilityTableIdentity",
    "NativeBundleDescriptor",
    "NativeBundleError",
    "NativeBundleLoadError",
    "NativeBundleStateError",
    "NativeBundleVerificationError",
    "NativeOperatorRegistrationError",
    "VerifiedCapabilityIndex",
    "load_native_capability_table",
    "load_native_capability_table_identity",
    "load_native_library",
    "load_signed_capability_index",
    "reconcile_exported_native_capability_identity",
    "reconcile_signed_native_capability_table",
]
