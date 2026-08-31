# Copyright (c) 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

from dataclasses import replace
import hashlib
import json
from pathlib import Path

import pytest

from kernels.native.python import loader


def _digest(contents: bytes) -> str:
    return f"sha256:{hashlib.sha256(contents).hexdigest()}"


def _manifest(operators: list[dict] | None = None) -> bytes:
    operators = [] if operators is None else operators
    semantic_input = [
        {
            "qualified_name": operator["qualified_name"],
            "kernel_spec_digest": operator["kernel_spec_digest"],
        }
        for operator in operators
    ]
    source_inventory = sorted(
        (
            {
                "source": operator["source"],
                "spec_sha256": operator["spec_sha256"],
                "kernel_spec_digest": operator["kernel_spec_digest"],
            }
            for operator in operators
        ),
        key=lambda item: item["source"],
    )
    value = {
        "schema_version": 3,
        "generator": {
            "id": "kernels.native.codegen.generate",
            "version": 3,
        },
        "source_inventory_sha256": _digest(
            loader._canonical_json(source_inventory)
        ),
        "namespace": "mindclade",
        "registration_mode": "build_time_generated",
        "optimized_math_authority": "tilelang",
        "runtime_discovery": False,
        "request_time_compilation": False,
        "operators": operators,
        "semantic_digest": _digest(loader._canonical_json(semantic_input)),
    }
    value["manifest_digest"] = _digest(loader._canonical_json(value))
    return loader._canonical_json(value)


def _empty_manifest() -> bytes:
    return _manifest()


def _operator(*, autograd_policy: str = "none") -> dict:
    name = "sample"
    forward_schema = "_sample_fwd(Tensor x) -> Tensor output"
    forward_symbol = "mindclade_tilelang_sample_fwd_launch"
    registrations = [
        {
            "qualified_name": "mindclade::sample",
            "schema": "sample(Tensor x) -> Tensor output",
            "kind": "semantic",
            "implementation_symbol": forward_symbol,
        },
        {
            "qualified_name": "mindclade::_sample_fwd",
            "schema": forward_schema,
            "kind": "forward",
            "implementation_symbol": forward_symbol,
        },
    ]
    backward = None
    composite = None
    if autograd_policy == "required":
        backward_schema = (
            "_sample_bwd(Tensor grad_output, Tensor x) -> Tensor grad_x"
        )
        backward_symbol = "mindclade_tilelang_sample_bwd_launch"
        backward = {
            "schema": backward_schema,
            "symbol": backward_symbol,
        }
        registrations.append(
            {
                "qualified_name": "mindclade::_sample_bwd",
                "schema": backward_schema,
                "kind": "backward",
                "implementation_symbol": backward_symbol,
            }
        )
    elif autograd_policy == "composite":
        composite = {"decomposition": "kernels.sample.reference:backward"}
    return {
        "name": name,
        "qualified_name": "mindclade::sample",
        "namespace": "mindclade",
        "family": "testing",
        "source": "kernels/testing/sample/spec.py",
        "spec_sha256": "sha256:" + "1" * 64,
        "kernel_spec_digest": "sha256:" + "2" * 64,
        "operator_schema": "sample(Tensor x) -> Tensor output",
        "facade_outputs": ["output"],
        "fake": None,
        "forward": {"schema": forward_schema, "symbol": forward_symbol},
        "backward": backward,
        "autograd_policy": autograd_policy,
        "composite": composite,
        "effects": {},
        "launch": {},
        "backend": "tilelang",
        "version": 1,
        "devices": ["cuda"],
        "registrations": registrations,
    }


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


@pytest.mark.parametrize("autograd_policy", ["none", "composite", "required"])
def test_v3_manifest_parses_each_autograd_policy(autograd_policy):
    operators = loader._parse_manifest(
        _manifest([_operator(autograd_policy=autograd_policy)]),
        loader.BundleActivationPolicy.PRODUCTION,
    )
    assert operators[0].autograd_policy == autograd_policy
    expected_kinds = (
        ("semantic", "forward", "backward")
        if autograd_policy == "required"
        else ("semantic", "forward")
    )
    assert tuple(item.kind for item in operators[0].registrations) == expected_kinds


def test_v3_manifest_digest_domains_fail_closed():
    manifest = loader._unique_json_object(
        list(json.loads(_manifest([_operator()])).items())
    )
    manifest["semantic_digest"] = "sha256:" + "f" * 64
    manifest["manifest_digest"] = _digest(
        loader._canonical_json(
            {key: value for key, value in manifest.items() if key != "manifest_digest"}
        )
    )
    with pytest.raises(
        loader.NativeBundleVerificationError, match="semantic digest mismatch"
    ):
        loader._parse_manifest(
            loader._canonical_json(manifest),
            loader.BundleActivationPolicy.PRODUCTION,
        )


def test_v3_required_policy_rejects_missing_backward_registration():
    operator = _operator(autograd_policy="required")
    operator["registrations"] = operator["registrations"][:-1]
    with pytest.raises(
        loader.NativeBundleVerificationError, match="canonically ordered"
    ):
        loader._parse_manifest(
            _manifest([operator]), loader.BundleActivationPolicy.PRODUCTION
        )


def test_reconcile_checks_every_v3_registration(monkeypatch):
    operator = loader._parse_manifest(
        _manifest([_operator(autograd_policy="composite")]),
        loader.BundleActivationPolicy.PRODUCTION,
    )[0]
    schemas = {
        registration.qualified_name: loader._qualified_schema(registration.schema)
        for registration in operator.registrations
    }
    inspected: list[tuple[str, str]] = []
    monkeypatch.setattr(loader, "_dispatcher_schema", schemas.__getitem__)
    monkeypatch.setattr(
        loader, "_public_operator_overloads", lambda _name: ("default",)
    )

    def has_kernel(qualified_name, dispatch_key):
        inspected.append((qualified_name, dispatch_key))
        if dispatch_key in {"CUDA", "Meta"}:
            return True
        return qualified_name == "mindclade::sample" and dispatch_key == "Autograd"

    monkeypatch.setattr(loader, "_dispatcher_has_kernel", has_kernel)
    loader._reconcile_dispatcher(
        (operator,),
        frozenset(registration.qualified_name for registration in operator.registrations),
    )
    assert {
        qualified_name for qualified_name, _dispatch_key in inspected
    } == {"mindclade::sample", "mindclade::_sample_fwd"}
