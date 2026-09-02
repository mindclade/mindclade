# Copyright (c) 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

"""Public loader API; operators remain exclusively under torch.ops."""

from .capability_index import (
    CapabilityIndexError,
    CapabilityRequest,
    DispatchReceipt,
    NativeCapabilityRow,
    NativeCapabilityTable,
    NativeCapabilityTableIdentity,
    VerifiedCapabilityIndex,
    load_native_capability_table,
    load_native_capability_table_identity,
    load_signed_capability_index,
    reconcile_exported_native_capability_identity,
    reconcile_signed_native_capability_table,
)
from .loader import (
    BundleActivationPolicy,
    BundleTrustDecision,
    NativeBundleDescriptor,
    NativeBundleError,
    NativeBundleLoadError,
    NativeBundleStateError,
    NativeBundleVerificationError,
    NativeOperatorRegistrationError,
    load_native_library,
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
