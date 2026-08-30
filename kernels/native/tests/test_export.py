# Copyright (c) 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

from pathlib import Path
import json

from kernels.native.python.loader import (
    BundleActivationPolicy,
    NativeBundleDescriptor,
)


def test_signed_descriptor_payload_binds_plan_and_release_identity(tmp_path):
    descriptor = NativeBundleDescriptor(
        bundle_root=Path(tmp_path).resolve(),
        library_path="lib/libmindclade_ops.so",
        manifest_path="generated/native_ops.json",
        library_sha256="sha256:" + "1" * 64,
        native_manifest_sha256="sha256:" + "2" * 64,
        repository_revision="3" * 40,
        executable_plan_sha256="sha256:" + "4" * 64,
        qualification_identity="target:unqualified",
        trust_policy_identity="trust:test-v1",
        revocation_policy_identity="revocation:test-v1",
        signature_evidence=b"opaque-signature",
        activation_policy=BundleActivationPolicy.TARGET_EMPTY,
    )
    payload = json.loads(descriptor.signature_payload())
    assert payload["executable_plan_sha256"] == "sha256:" + "4" * 64
    assert payload["activation_policy"] == "target_empty"
    assert payload["library_sha256"] == "sha256:" + "1" * 64
    assert payload["native_manifest_sha256"] == "sha256:" + "2" * 64
    assert "bundle_root" not in payload
    assert "signature_evidence" not in payload
