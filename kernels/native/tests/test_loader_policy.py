# Copyright (c) 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

from dataclasses import replace
import hashlib
from pathlib import Path

import pytest

from kernels.native.python import loader


def _digest(contents: bytes) -> str:
    return f"sha256:{hashlib.sha256(contents).hexdigest()}"


def _empty_manifest() -> bytes:
    value = {
        "schema_version": 2,
        "generator": {
            "id": "kernels.native.codegen.generate",
            "version": 2,
        },
        "source_inventory_sha256": "sha256:" + "0" * 64,
        "namespace": "mindclade",
        "registration_mode": "build_time_generated",
        "optimized_math_authority": "tilelang",
        "runtime_discovery": False,
        "request_time_compilation": False,
        "operators": [],
    }
    value["semantic_digest"] = _digest(loader._canonical_json(value))
    return loader._canonical_json(value)


def _bundle(
    tmp_path: Path,
) -> tuple[loader.NativeBundleDescriptor, Path]:
    root = (tmp_path / "bundle").resolve()
    (root / "lib").mkdir(parents=True)
    (root / "generated").mkdir()
    library = root / "lib" / "libmindclade_ops.so"
    library_contents = b"test-only-native-library"
    library.write_bytes(library_contents)
    manifest_contents = _empty_manifest()
    (root / "generated" / "native_ops.json").write_bytes(
        manifest_contents
    )
    descriptor = loader.NativeBundleDescriptor(
        bundle_root=root,
        library_path="lib/libmindclade_ops.so",
        manifest_path="generated/native_ops.json",
        library_sha256=_digest(library_contents),
        native_manifest_sha256=_digest(manifest_contents),
        repository_revision="a" * 40,
        executable_plan_sha256="sha256:" + "b" * 64,
        qualification_identity="target:unqualified",
        trust_policy_identity="trust:test-v1",
        revocation_policy_identity="revocation:test-v1",
        signature_evidence=b"test-signature-evidence",
        activation_policy=loader.BundleActivationPolicy.TARGET_EMPTY,
    )
    return descriptor, library


def _trust(
    descriptor: loader.NativeBundleDescriptor,
) -> loader.BundleTrustDecision:
    return loader.BundleTrustDecision(
        trusted=True,
        revocation_checked=True,
        revoked=False,
        signer_identity="signer:test-v1",
        trust_policy_identity=descriptor.trust_policy_identity,
        revocation_policy_identity=descriptor.revocation_policy_identity,
        qualification_identity=descriptor.qualification_identity,
        signature_evidence_sha256=_digest(
            descriptor.signature_evidence
        ),
    )


@pytest.fixture(autouse=True)
def _reset_loader_state(monkeypatch):
    monkeypatch.setattr(loader, "_LOADED_BUNDLE", None)
    monkeypatch.setattr(loader, "_POISONED_REASON", None)


def _mock_empty_runtime(
    monkeypatch, events: list[str]
) -> None:
    baseline = frozenset({"aten::existing"})
    monkeypatch.setattr(
        loader, "_dispatcher_snapshot", lambda: baseline
    )
    monkeypatch.setattr(
        loader,
        "_load_torch_library",
        lambda _path: events.append("dlopen"),
    )
    monkeypatch.setattr(
        loader,
        "register_packaged_python_kernels",
        lambda: events.append("register"),
    )


def test_verifier_precedes_dlopen_and_env_cannot_override(
    monkeypatch, tmp_path
):
    descriptor, library = _bundle(tmp_path)
    events: list[str] = []
    _mock_empty_runtime(monkeypatch, events)
    monkeypatch.setenv(
        "MINDCLADE_NATIVE_LIBRARY", "/untrusted/override.so"
    )

    def verifier(value, payload):
        assert value is descriptor
        assert payload == descriptor.signature_payload()
        events.append("verify")
        return _trust(value)

    loaded = loader.load_native_library(
        descriptor, signature_verifier=verifier
    )
    assert loaded == library
    assert events == ["verify", "dlopen", "register"]


def test_production_policy_rejects_empty_manifest_before_dlopen(
    monkeypatch, tmp_path
):
    descriptor, _ = _bundle(tmp_path)
    descriptor = replace(
        descriptor,
        activation_policy=loader.BundleActivationPolicy.PRODUCTION,
    )
    called = False

    def load(_path):
        nonlocal called
        called = True

    monkeypatch.setattr(loader, "_load_torch_library", load)
    with pytest.raises(
        loader.NativeBundleVerificationError, match="production"
    ):
        loader.load_native_library(
            descriptor,
            signature_verifier=lambda value, _payload: _trust(value),
        )
    assert called is False


def test_digest_mismatch_is_rejected_before_verification(
    tmp_path,
):
    descriptor, _ = _bundle(tmp_path)
    descriptor = replace(
        descriptor, library_sha256="sha256:" + "f" * 64
    )
    verified = False

    def verifier(value, _payload):
        nonlocal verified
        verified = True
        return _trust(value)

    with pytest.raises(
        loader.NativeBundleVerificationError,
        match="digest mismatch",
    ):
        loader.load_native_library(
            descriptor, signature_verifier=verifier
        )
    assert verified is False


def test_symlinked_library_is_rejected(tmp_path):
    descriptor, library = _bundle(tmp_path)
    target = Path(tmp_path).resolve() / "outside.so"
    target.write_bytes(library.read_bytes())
    library.unlink()
    library.symlink_to(target)
    with pytest.raises(
        loader.NativeBundleVerificationError, match="symlink"
    ):
        loader.load_native_library(
            descriptor,
            signature_verifier=lambda value, _payload: _trust(value),
        )


def test_revoked_bundle_is_rejected_before_dlopen(
    monkeypatch, tmp_path
):
    descriptor, _ = _bundle(tmp_path)
    called = False

    def load(_path):
        nonlocal called
        called = True

    monkeypatch.setattr(loader, "_load_torch_library", load)
    decision = replace(_trust(descriptor), revoked=True)
    with pytest.raises(
        loader.NativeBundleVerificationError, match="revoked"
    ):
        loader.load_native_library(
            descriptor,
            signature_verifier=lambda _value, _payload: decision,
        )
    assert called is False


def test_registration_failure_poisons_process(
    monkeypatch, tmp_path
):
    descriptor, _ = _bundle(tmp_path)
    baseline = frozenset({"aten::existing"})
    monkeypatch.setattr(
        loader, "_dispatcher_snapshot", lambda: baseline
    )
    monkeypatch.setattr(
        loader, "_load_torch_library", lambda _path: None
    )

    def fail_registration():
        raise RuntimeError("registration failed")

    monkeypatch.setattr(
        loader,
        "register_packaged_python_kernels",
        fail_registration,
    )
    with pytest.raises(loader.NativeOperatorRegistrationError):
        loader.load_native_library(
            descriptor,
            signature_verifier=lambda value, _payload: _trust(value),
        )
    with pytest.raises(
        loader.NativeBundleStateError, match="poisoned"
    ):
        loader.load_native_library(
            descriptor,
            signature_verifier=lambda value, _payload: _trust(value),
        )


def test_second_bundle_is_rejected(monkeypatch, tmp_path):
    first, _ = _bundle(tmp_path / "first")
    second, _ = _bundle(tmp_path / "second")
    events: list[str] = []
    _mock_empty_runtime(monkeypatch, events)
    loader.load_native_library(
        first,
        signature_verifier=lambda value, _payload: _trust(value),
    )
    with pytest.raises(
        loader.NativeBundleStateError,
        match="different native bundle",
    ):
        loader.load_native_library(
            second,
            signature_verifier=lambda value, _payload: _trust(value),
        )
