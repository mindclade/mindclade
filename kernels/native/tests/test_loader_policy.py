# Copyright (c) 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

from dataclasses import replace
import ctypes
import hashlib
import json
from pathlib import Path

import pytest

from kernels.native.python import loader
from kernels.native.python.capability_index import (
    CapabilityRequest,
    DispatchReceipt,
    NativeCapabilityTable,
    NativeCapabilityTableIdentity,
    VerifiedCapabilityIndex,
)


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
                "implementation_digest": operator["implementation_digest"],
            }
            for operator in operators
        ),
        key=lambda item: item["source"],
    )
    value = {
        "schema_version": 4,
        "generator": {
            "id": "kernels.native.codegen.generate",
            "version": 8,
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
            "program_group": None,
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
        "implementation_digest": "sha256:" + "3" * 64,
        "implementation_candidates": [],
        "operator_schema": "sample(Tensor x) -> Tensor output",
        "facade_outputs": ["output"],
        "fake": None,
        "forward": {
            "schema": forward_schema,
            "symbol": forward_symbol,
            "program_group": None,
        },
        "backward": backward,
        "autograd_policy": autograd_policy,
        "composite": composite,
        "effects": {},
        "launch": {},
        "backend": "tilelang",
        "version": 1,
        "devices": ["cuda"],
        "registrations": registrations,
        "launcher_plans": {"forward": None, "backward": None},
    }


def _implementation_candidate() -> dict:
    envelope = {
        "type": "CapabilityEnvelope",
        "architectures": ["sm90"],
        "dtypes": ["float32"],
        "layouts": ["contiguous"],
        "modes": ["default"],
        "constraints": [
            {
                "type": "DimensionConstraint",
                "predicate": {"node": "bool_literal", "value": True},
                "code": "VALID",
                "message": "fixture capability",
                "version": 1,
            }
        ],
        "graph_capture_safe": False,
        "training_capable": False,
        "tensor_constraints": [
            {
                "type": "TensorCapabilityConstraint",
                "argument": "x",
                "dtypes": ["float32"],
                "layouts": ["contiguous"],
                "devices": ["cuda"],
                "ranks": [1],
                "version": 1,
            }
        ],
        "version": 1,
    }
    return {
        "name": "portable",
        "version": 1,
        "tier": "portable",
        "priority": 0,
        "requires": ["cuda"],
        "envelope": envelope,
        "envelope_digest": _digest(loader._canonical_json(envelope)),
        "promoted": False,
        "selectable": False,
    }


def _tensor_parameter(position: int, name: str, access: str) -> dict:
    return {
        "type": "ProgramParameterSpec",
        "position": position,
        "name": name,
        "kind": "tensor",
        "access": access,
        "shape": {"node": "shape_of", "argument": "x"},
        "dtype": {"node": "dtype_ref", "argument": "x"},
        "device": {"node": "constant_device", "value": "cuda"},
        "scalar_type": None,
        "optional": False,
        "version": 1,
    }


def _stream_parameter(position: int) -> dict:
    return {
        "type": "ProgramParameterSpec",
        "position": position,
        "name": "stream",
        "kind": "stream",
        "access": "read",
        "shape": None,
        "dtype": None,
        "device": None,
        "scalar_type": None,
        "optional": False,
        "version": 1,
    }


def _binding(parameter: str, source: str, source_name: str | None) -> dict:
    return {
        "type": "ProgramBindingSpec",
        "parameter": parameter,
        "source": source,
        "source_name": source_name,
        "version": 1,
    }


def _program_group() -> dict:
    return {
        "type": "ProgramGroupSpec",
        "nodes": [
            {
                "type": "ProgramNodeSpec",
                "name": "produce",
                "builder": "kernels.testing.sample.tilelang:build_produce",
                "symbol": "mindclade_tilelang_sample_produce_launch",
                "entry_symbol": "call",
                "entry_abi": "tilelang_0_1_13_host_call",
                "parameters": [
                    _tensor_parameter(0, "x", "read"),
                    _tensor_parameter(1, "scratch", "write"),
                    _stream_parameter(2),
                ],
                "bindings": [
                    _binding("scratch", "workspace", "scratch"),
                    _binding("stream", "current_stream", None),
                    _binding("x", "operator_argument", "x"),
                ],
                "depends_on": [],
                "return_abi": "status_i32_zero_success",
                "artifact_boundary": "node_content_addressed_dso",
                "version": 1,
            },
            {
                "type": "ProgramNodeSpec",
                "name": "consume",
                "builder": "kernels.testing.sample.tilelang:build_consume",
                "symbol": "mindclade_tilelang_sample_consume_launch",
                "entry_symbol": "call",
                "entry_abi": "tilelang_0_1_13_host_call",
                "parameters": [
                    _tensor_parameter(0, "scratch", "read"),
                    _tensor_parameter(1, "y", "write"),
                    _stream_parameter(2),
                ],
                "bindings": [
                    _binding("scratch", "workspace", "scratch"),
                    _binding("stream", "current_stream", None),
                    _binding("y", "provider_output", "output"),
                ],
                "depends_on": ["produce"],
                "return_abi": "status_i32_zero_success",
                "artifact_boundary": "node_content_addressed_dso",
                "version": 1,
            },
        ],
        "workspaces": [
            {
                "type": "WorkspaceSpec",
                "name": "scratch",
                "shape": {
                    "node": "shape_tuple",
                    "dimensions": [
                        {"node": "dim_ref", "argument": "x", "axis": 0}
                    ],
                },
                "dtype": {"node": "constant_dtype", "value": "float32"},
                "zero_initialize": False,
                "lifetime": "program_group",
                "version": 1,
            }
        ],
        "selector_bindings": [],
        "version": 1,
    }


def _launcher_plan() -> dict:
    group = _program_group()
    return {
        "phase": "forward",
        "logical_symbol": "mindclade_tilelang_sample_fwd_launch",
        "bridge_requirement": "mindclade_node_launch_v1",
        "execution_order": [node["name"] for node in group["nodes"]],
        "adapter_symbol_prefixes": [node["symbol"] for node in group["nodes"]],
        "selector_bindings": group["selector_bindings"],
        "nodes": [
            {
                key: node[key]
                for key in (
                    "name", "symbol", "entry_symbol", "entry_abi",
                    "return_abi", "artifact_boundary", "depends_on",
                    "parameters", "bindings",
                )
            }
            for node in group["nodes"]
        ],
        "workspaces": [
            {
                key: workspace[key]
                for key in (
                    "name", "shape", "dtype", "zero_initialize", "lifetime"
                )
            }
            for workspace in group["workspaces"]
        ],
    }


def _operator_with_launcher_plan() -> dict:
    operator = _operator()
    operator["forward"]["program_group"] = _program_group()
    operator["launcher_plans"]["forward"] = _launcher_plan()
    return operator


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


def _program_bundle(
    tmp_path: Path,
) -> tuple[loader.NativeBundleDescriptor, Path]:
    descriptor, library = _bundle(tmp_path)
    manifest_contents = _manifest([_operator_with_launcher_plan()])
    (Path(descriptor.bundle_root) / descriptor.manifest_path).write_bytes(
        manifest_contents
    )
    program_root = Path(descriptor.bundle_root) / "programs"
    program_root.mkdir()
    programs: list[loader.NativeProgramLibrary] = []
    for name in ("produce", "consume"):
        contents = f"test-only-{name}-dso".encode()
        relative = f"programs/{name}.so"
        (Path(descriptor.bundle_root) / relative).write_bytes(contents)
        programs.append(
            loader.NativeProgramLibrary(
                library_path=relative,
                library_sha256=_digest(contents),
                adapter_symbol=f"mindclade_tilelang_sample_{name}_launch",
            )
        )
    return (
        replace(
            descriptor,
            native_manifest_sha256=_digest(manifest_contents),
            activation_policy=loader.BundleActivationPolicy.PRODUCTION,
            program_libraries=tuple(programs),
        ),
        library,
    )


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


def test_nonempty_python_index_requires_verified_native_table(
    monkeypatch, tmp_path
):
    descriptor, _ = _bundle(tmp_path)
    descriptor = replace(
        descriptor,
        activation_policy=loader.BundleActivationPolicy.PRODUCTION,
    )
    index = VerifiedCapabilityIndex(
        capabilities=(object(),),
        revoked_capability_digests=frozenset(),
        rollbacks=(),
        evidence_class="PRODUCTION_K4_K5",
        signer_key_id="protected.release",
        subject_digest="sha256:" + "1" * 64,
        production_eligible=True,
    )
    request = CapabilityRequest(
        operation="mindclade::triangle_attention",
        architecture="sm90a",
        dtype="bfloat16",
        layout="contiguous",
        mode="starting_node",
        workload_digest="sha256:" + "2" * 64,
        training=True,
    )
    called = False

    def load(_path):
        nonlocal called
        called = True

    monkeypatch.setattr(loader, "_load_torch_library", load)
    with pytest.raises(
        loader.NativeBundleVerificationError,
        match="verified generated native capability table",
    ):
        loader.load_native_library(
            descriptor,
            signature_verifier=lambda value, _payload: _trust(value),
            capability_index=index,
            capability_request=request,
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


def test_program_group_dsos_are_verified_resolved_and_cached_once(
    monkeypatch, tmp_path
):
    descriptor, bridge_library = _program_bundle(tmp_path)
    events: list[str] = []
    callbacks: dict[str, object] = {}
    callback_type = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_void_p)

    class FakeProgramLibrary:
        def __init__(self, path: Path):
            self.path = path

        def __getattr__(self, symbol: str):
            events.append(f"dlsym:{symbol}")
            callback = callback_type(lambda _launch: 0)
            callbacks[symbol] = callback
            return callback

    def open_program(path: Path):
        events.append(f"open:{path.name}")
        return FakeProgramLibrary(path)

    monkeypatch.setattr(loader, "_open_program_library", open_program)
    monkeypatch.setattr(
        loader,
        "_load_torch_library",
        lambda path: events.append(f"bridge:{path.name}"),
    )
    expected_names = frozenset(
        registration["qualified_name"]
        for registration in _operator_with_launcher_plan()["registrations"]
    )
    baseline = frozenset({"aten::existing"})
    snapshots = iter(
        (baseline, baseline | expected_names, baseline | expected_names)
    )
    monkeypatch.setattr(loader, "_dispatcher_snapshot", lambda: next(snapshots))
    monkeypatch.setattr(
        loader,
        "register_packaged_python_kernels",
        lambda: events.append("register"),
    )
    monkeypatch.setattr(
        loader,
        "_reconcile_dispatcher",
        lambda _operators, _snapshot: events.append("reconcile"),
    )
    monkeypatch.setattr(
        loader, "reconcile_signed_native_capability_table", lambda *_args: None
    )
    monkeypatch.setattr(
        loader,
        "reconcile_exported_native_capability_identity",
        lambda *_args, **_kwargs: None,
    )
    identity = NativeCapabilityTableIdentity(
        row_count=0,
        rows_digest="sha256:" + "0" * 64,
        table_digest="sha256:" + "1" * 64,
    )
    monkeypatch.setattr(
        loader, "_exported_native_capability_identity", lambda _path: identity
    )
    receipt = DispatchReceipt(
        operation="mindclade::sample",
        implementation="portable",
        workload_digest="sha256:" + "2" * 64,
        capability_digest="sha256:" + "3" * 64,
        artifact_digest="sha256:" + "4" * 64,
        release_receipt_digest="sha256:" + "5" * 64,
        selection_reason="test-only exact selection",
    )
    monkeypatch.setattr(
        loader, "select_capability", lambda *_args, **_kwargs: receipt
    )
    original_parse = loader._parse_manifest

    def parse_once(contents, activation):
        events.append("parse")
        return original_parse(contents, activation)

    monkeypatch.setattr(loader, "_parse_manifest", parse_once)
    index = VerifiedCapabilityIndex(
        capabilities=(),
        revoked_capability_digests=frozenset(),
        rollbacks=(),
        evidence_class="PRODUCTION_K4_K5",
        signer_key_id="protected.release",
        subject_digest="sha256:" + "6" * 64,
        production_eligible=True,
    )
    request = CapabilityRequest(
        operation="mindclade::sample",
        architecture="sm90a",
        dtype="float32",
        layout="contiguous",
        mode="default",
        workload_digest="sha256:" + "2" * 64,
        training=False,
    )
    table = NativeCapabilityTable(rows=(), identity=identity)

    def verifier(value, _payload):
        events.append("verify")
        return _trust(value)

    loaded = loader.load_native_library(
        descriptor,
        signature_verifier=verifier,
        capability_index=index,
        capability_request=request,
        native_capability_table=table,
    )
    assert loaded == bridge_library
    assert events == [
        "parse",
        "verify",
        "open:produce.so",
        "dlsym:mindclade_tilelang_sample_produce_launch",
        "open:consume.so",
        "dlsym:mindclade_tilelang_sample_consume_launch",
        "bridge:libmindclade_ops.so",
        "register",
        "reconcile",
    ]
    assert loader._LOADED_BUNDLE is not None
    assert tuple(
        item.descriptor.adapter_symbol
        for item in loader._LOADED_BUNDLE.program_libraries
    ) == (
        "mindclade_tilelang_sample_produce_launch",
        "mindclade_tilelang_sample_consume_launch",
    )
    assert all(
        item.function_address != 0
        for item in loader._LOADED_BUNDLE.program_libraries
    )

    assert loader.load_native_library(
        descriptor,
        signature_verifier=verifier,
        capability_index=index,
        capability_request=request,
        native_capability_table=table,
    ) == bridge_library
    assert events.count("parse") == 1
    assert sum(event.startswith("open:") for event in events) == 2
    assert sum(event.startswith("dlsym:") for event in events) == 2


def test_program_group_dso_projection_mismatch_fails_before_trust(tmp_path):
    descriptor, _ = _program_bundle(tmp_path)
    descriptor = replace(
        descriptor, program_libraries=descriptor.program_libraries[:-1]
    )
    verified = False

    def verifier(value, _payload):
        nonlocal verified
        verified = True
        return _trust(value)

    with pytest.raises(
        loader.NativeBundleVerificationError,
        match="per-node program libraries",
    ):
        loader._verify_bundle(descriptor, verifier)
    assert verified is False


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


def test_v3_loader_retains_only_immutable_launcher_projection():
    operator = loader._parse_manifest(
        _manifest([_operator_with_launcher_plan()]),
        loader.BundleActivationPolicy.PRODUCTION,
    )[0]
    plan = operator.forward_launcher_plan
    assert plan is not None
    assert plan.phase == "forward"
    assert plan.execution_order == ("produce", "consume")
    assert plan.adapter_symbol_prefixes == tuple(node.symbol for node in plan.nodes)
    assert plan.workspaces[0].shape_json == loader._canonical_json(
        _program_group()["workspaces"][0]["shape"]
    )
    assert not hasattr(plan.nodes[0], "builder")
    assert operator.backward_launcher_plan is None


def test_v4_loader_retains_selector_only_provider_arguments_exactly():
    selector = {
        "type": "ProgramSelectorBinding",
        "provider_argument": "outgoing",
        "selector_key": "mode",
        "scalar_type": "bool",
        "cases": [[False, "incoming"], [True, "outgoing"]],
        "version": 1,
    }
    operator = _operator_with_launcher_plan()
    operator["forward"]["schema"] = (
        "_sample_fwd(Tensor x, bool outgoing) -> Tensor"
    )
    for registration in operator["registrations"]:
        if registration["kind"] == "forward":
            registration["schema"] = operator["forward"]["schema"]
    operator["forward"]["program_group"]["selector_bindings"] = [selector]
    operator["launcher_plans"]["forward"]["selector_bindings"] = [selector]
    parsed = loader._parse_manifest(
        _manifest([operator]), loader.BundleActivationPolicy.PRODUCTION
    )[0]
    assert parsed.forward_launcher_plan is not None
    assert parsed.forward_launcher_plan.selector_bindings[0].cases == (
        (False, "incoming"),
        (True, "outgoing"),
    )

    invalid = _operator_with_launcher_plan()
    invalid["forward"]["program_group"]["selector_bindings"] = [selector]
    invalid["launcher_plans"]["forward"]["selector_bindings"] = [selector]
    with pytest.raises(
        loader.NativeBundleVerificationError,
        match="not a bool provider argument",
    ):
        loader._parse_manifest(
            _manifest([invalid]), loader.BundleActivationPolicy.PRODUCTION
        )


@pytest.mark.parametrize(
    ("case", "message"),
    (
        ("noncanonical", "canonical execution order"),
        ("cycle", "dependency cycle"),
        ("duplicate", "duplicate node names"),
        ("undeclared", "undeclared workspace"),
        ("multiple_writers", "multiple writers"),
        ("no_writer", "requires a writer"),
        ("node_lifetime", "must have one using node"),
        ("plan_mismatch", "does not exactly match"),
        ("malformed_expression", "malformed expression"),
        ("deep_expression", "maximum depth"),
    ),
)
def test_v3_loader_rejects_invalid_launcher_topology_and_workspace_dataflow(
    case: str, message: str
):
    operator = _operator_with_launcher_plan()
    group = operator["forward"]["program_group"]
    plan = operator["launcher_plans"]["forward"]
    if case == "noncanonical":
        group["nodes"].reverse()
    elif case == "cycle":
        group["nodes"][0]["depends_on"] = ["consume"]
    elif case == "duplicate":
        group["nodes"][1]["name"] = "produce"
    elif case == "undeclared":
        group["nodes"][0]["bindings"][0]["source_name"] = "missing"
    elif case == "multiple_writers":
        group["nodes"][1]["parameters"][0]["access"] = "write"
    elif case == "no_writer":
        group["nodes"][0]["parameters"][1]["access"] = "read"
    elif case == "node_lifetime":
        group["workspaces"][0]["lifetime"] = "node"
    elif case == "plan_mismatch":
        plan["workspaces"][0]["zero_initialize"] = True
    elif case == "malformed_expression":
        group["workspaces"][0]["shape"] = {
            "node": "shape_tuple",
            "dimensions": [{"argument": "x", "axis": 0}],
        }
    elif case == "deep_expression":
        expression = {"node": "shape_of", "argument": "x"}
        for _ in range(40):
            expression = {"node": "concat_shape", "parts": [expression]}
        group["workspaces"][0]["shape"] = expression
    with pytest.raises(loader.NativeBundleVerificationError, match=message):
        loader._parse_manifest(
            _manifest([operator]), loader.BundleActivationPolicy.PRODUCTION
        )


@pytest.mark.parametrize(
    ("field", "invalid", "message"),
    (
        ("bridge_requirement", "other_bridge", "bridge_requirement"),
        ("phase", "backward", "phase"),
        ("logical_symbol", "other_launch", "logical_symbol"),
        (
            "adapter_symbol_prefixes",
            ["mindclade_tilelang_sample_consume_launch"],
            "adapter_symbol_prefixes",
        ),
    ),
)
def test_v3_loader_rejects_launcher_identity_drift(
    field: str, invalid: object, message: str
):
    operator = _operator_with_launcher_plan()
    operator["launcher_plans"]["forward"][field] = invalid
    with pytest.raises(loader.NativeBundleVerificationError, match=message):
        loader._parse_manifest(
            _manifest([operator]), loader.BundleActivationPolicy.PRODUCTION
        )


@pytest.mark.parametrize(
    ("field", "invalid", "domain"),
    (
        ("shape", [], "expression object"),
        ("dtype", [], "expression object"),
        ("shape", {"node": "constant_dtype", "value": "float32"}, "shape-domain"),
        ("dtype", {"node": "shape_of", "argument": "x"}, "dtype-domain"),
    ),
)
def test_v3_loader_rejects_wrong_workspace_expression_domains(
    field: str, invalid: object, domain: str
):
    operator = _operator_with_launcher_plan()
    operator["forward"]["program_group"]["workspaces"][0][field] = invalid
    with pytest.raises(loader.NativeBundleVerificationError, match=domain):
        loader._parse_manifest(
            _manifest([operator]), loader.BundleActivationPolicy.PRODUCTION
        )


def test_loader_source_has_no_authoring_or_execution_plane_imports():
    source = Path(loader.__file__).read_text(encoding="utf-8")
    for prohibited in (
        "kernels.api",
        "tilelang",
        "kernels.planning",
        "kernels.tuning",
        "kernels.benchmarks",
    ):
        assert f"import {prohibited}" not in source
        assert f"from {prohibited}" not in source


def test_v6_loader_retains_builder_free_unselectable_implementation_projection():
    operator = _operator()
    operator["implementation_candidates"] = [_implementation_candidate()]
    parsed = loader._parse_manifest(
        _manifest([operator]), loader.BundleActivationPolicy.PRODUCTION
    )[0]
    candidate = parsed.implementation_candidates[0]
    assert candidate.name == "portable"
    assert candidate.promoted is False
    assert candidate.selectable is False
    assert candidate.envelope.architectures == ("sm90",)
    assert candidate.envelope.constraints[0].predicate_json == b'{"node":"bool_literal","value":true}'
    assert not hasattr(candidate, "builder")


@pytest.mark.parametrize("field", ["promoted", "selectable"])
def test_v6_loader_rejects_candidate_activation_claims(field: str):
    operator = _operator()
    candidate = _implementation_candidate()
    candidate[field] = True
    operator["implementation_candidates"] = [candidate]
    with pytest.raises(loader.NativeBundleVerificationError, match="cannot be promoted or selectable"):
        loader._parse_manifest(
            _manifest([operator]), loader.BundleActivationPolicy.PRODUCTION
        )


def test_v6_loader_rejects_candidate_envelope_digest_drift():
    operator = _operator()
    candidate = _implementation_candidate()
    candidate["envelope"]["modes"] = ["changed"]
    operator["implementation_candidates"] = [candidate]
    with pytest.raises(loader.NativeBundleVerificationError, match="digest mismatch"):
        loader._parse_manifest(
            _manifest([operator]), loader.BundleActivationPolicy.PRODUCTION
        )
