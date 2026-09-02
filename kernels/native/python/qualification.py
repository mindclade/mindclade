# Copyright (c) 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

"""Fail-closed CUDA evidence-candidate qualification for Mindclade operators."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import base64
import hashlib
import json
import math
import re
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from .capability_index import canonical_json, subject_digest

_OPERATORS = frozenset(
    {
        "outer_product_mean",
        "pair_weighted_average",
        "triangle_attention",
        "triangle_multiplication",
        "transition",
    }
)
_TARGET_CAPABILITIES = {"sm90": (9, 0), "sm100": (10, 0)}
_KEY_ID_RE = re.compile(r"^[a-z][a-z0-9._:/-]{2,255}$")
_OPERATION_RE = re.compile(r"^mindclade::[a-z][a-z0-9_]{0,63}$")
_ARCHITECTURE_RE = re.compile(r"^sm[0-9]{2,3}a$")
_WORKLOAD_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
PRODUCTION_EVIDENCE = "PRODUCTION_K4_K5"
TEST_ONLY_EVIDENCE = "TEST_ONLY_UNQUALIFIED"


def _digest(value: str, label: str) -> str:
    if not isinstance(value, str) or len(value) != 71 or not value.startswith("sha256:"):
        raise ValueError(f"{label} must use sha256:<64 lowercase hex>")
    payload = value.removeprefix("sha256:")
    if any(character not in "0123456789abcdef" for character in payload):
        raise ValueError(f"{label} must use sha256:<64 lowercase hex>")
    return value


@dataclass(frozen=True, slots=True)
class QualificationConfig:
    operator: str
    profile: str
    target: str
    artifact_digest: str
    source_digest: str
    atol: float
    rtol: float
    warmup: int = 10
    iterations: int = 100
    deterministic: bool = True

    def __post_init__(self) -> None:
        if self.operator not in _OPERATORS:
            raise ValueError(f"unsupported Mindclade operator: {self.operator!r}")
        if self.target not in _TARGET_CAPABILITIES:
            raise ValueError("target must be sm90 or sm100")
        if not self.profile or len(self.profile) > 64:
            raise ValueError("profile must be a nonempty bounded identifier")
        _digest(self.artifact_digest, "artifact_digest")
        _digest(self.source_digest, "source_digest")
        if not math.isfinite(self.atol) or self.atol < 0:
            raise ValueError("atol must be finite and nonnegative")
        if not math.isfinite(self.rtol) or self.rtol < 0:
            raise ValueError("rtol must be finite and nonnegative")
        if not 1 <= self.warmup <= 10_000 or not 1 <= self.iterations <= 1_000_000:
            raise ValueError("warmup and iterations are outside bounded ranges")


def canonical_receipt(receipt: Mapping[str, object]) -> bytes:
    """Serialize an evidence candidate canonically for hashing and signing."""

    return (json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n").encode()


def receipt_digest(receipt: Mapping[str, object]) -> str:
    return "sha256:" + hashlib.sha256(canonical_receipt(receipt)).hexdigest()


def select_specialization(
    profiles: tuple[Mapping[str, object], ...] | list[Mapping[str, object]],
    runtime_arguments: Mapping[str, object],
) -> str:
    """Select exactly one predeclared specialization without compiling."""

    matches: list[str] = []
    for profile in profiles:
        if set(profile) != {"name", "arguments"}:
            raise ValueError("profile entries must contain exactly name and arguments")
        name = profile["name"]
        arguments = profile["arguments"]
        if not isinstance(name, str) or not isinstance(arguments, Mapping):
            raise ValueError("profile name and arguments have invalid types")
        if dict(arguments) == dict(runtime_arguments):
            matches.append(name)
    if len(matches) != 1:
        raise LookupError(
            f"offline specialization requires exactly one match, observed {len(matches)}"
        )
    return matches[0]


def select_compiled_artifact(
    receipts: tuple[Mapping[str, object], ...] | list[Mapping[str, object]],
    *,
    qualified_name: str,
    profile: str,
    target: str,
    source_digest: str,
) -> Mapping[str, object]:
    """Bind a profile to one immutable TileLang 0.1.13 build receipt."""

    _digest(source_digest, "source_digest")
    expected = {
        "qualified_name": qualified_name,
        "profile": profile,
        "target": target,
        "source_sha256": source_digest,
    }
    matches = [
        receipt
        for receipt in receipts
        if all(receipt.get(key) == value for key, value in expected.items())
    ]
    if len(matches) != 1:
        raise LookupError(f"compiled artifact requires exactly one match, observed {len(matches)}")
    receipt = matches[0]
    if receipt.get("compiler") != "tilelang" or receipt.get("compiler_version") != "0.1.13":
        raise RuntimeError("compiled artifact does not use the approved TileLang 0.1.13 toolchain")
    artifact_digest = receipt.get("artifact_sha256")
    if not isinstance(artifact_digest, str):
        raise RuntimeError("compiled artifact receipt lacks its digest")
    _digest(artifact_digest, "artifact_sha256")
    output = receipt.get("output")
    if not isinstance(output, str) or not output:
        raise RuntimeError("compiled artifact receipt lacks a bounded output identity")
    return receipt


def _clone_arguments(torch: Any, arguments: tuple[object, ...]) -> tuple[object, ...]:
    return tuple(
        value.detach().clone() if isinstance(value, torch.Tensor) else value
        for value in arguments
    )


def qualify_cuda_operator(
    config: QualificationConfig,
    sample_factory: Callable[[], tuple[object, ...]],
    reference: Callable[..., Any],
) -> dict[str, object]:
    """Exercise one already-loaded CUDA operator and return unsigned evidence.

    Passing this function does not activate an operation or grant production
    authority. Independent review, immutable artifact verification, and signing
    remain external protected gates.
    """

    import torch

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA qualification requires an available NVIDIA GPU")
    device = torch.cuda.current_device()
    capability = torch.cuda.get_device_capability(device)
    expected = _TARGET_CAPABILITIES[config.target]
    if capability != expected:
        raise RuntimeError(
            f"hardware mismatch: target {config.target} requires {expected}, observed {capability}"
        )
    try:
        operation = getattr(torch.ops.mindclade, config.operator).default
    except AttributeError as exc:
        raise RuntimeError(f"torch.ops.mindclade.{config.operator} is not registered") from exc

    arguments = sample_factory()
    if not isinstance(arguments, tuple):
        raise TypeError("sample_factory must return a tuple")
    tensors = [value for value in arguments if isinstance(value, torch.Tensor)]
    if not tensors or any(not tensor.is_cuda for tensor in tensors):
        raise ValueError("every tensor sample must be CUDA-resident")
    if len({tensor.device for tensor in tensors}) != 1:
        raise ValueError("all tensor samples must use one CUDA device")

    previous_determinism = torch.are_deterministic_algorithms_enabled()
    try:
        torch.use_deterministic_algorithms(config.deterministic)
        opcheck = torch.library.opcheck(
            operation,
            arguments,
            test_utils=(
                "test_schema",
                "test_autograd_registration",
                "test_faketensor",
                "test_aot_dispatch_dynamic",
            ),
            raise_exception=True,
        )
        expected_output = reference(*_clone_arguments(torch, arguments))
        actual_output = operation(*_clone_arguments(torch, arguments))
        torch.testing.assert_close(
            actual_output,
            expected_output,
            atol=config.atol,
            rtol=config.rtol,
        )

        compiled = torch.compile(operation, fullgraph=True, dynamic=False)
        compiled_output = compiled(*_clone_arguments(torch, arguments))
        torch.testing.assert_close(
            compiled_output,
            expected_output,
            atol=config.atol,
            rtol=config.rtol,
        )

        stream = torch.cuda.Stream(device=tensors[0].device)
        stream.wait_stream(torch.cuda.current_stream(device=tensors[0].device))
        with torch.cuda.stream(stream):
            for _ in range(config.warmup):
                operation(*arguments)
            start = torch.cuda.Event(enable_timing=True)
            end = torch.cuda.Event(enable_timing=True)
            start.record(stream)
            for _ in range(config.iterations):
                operation(*arguments)
            end.record(stream)
        end.synchronize()
        latency_us = start.elapsed_time(end) * 1_000.0 / config.iterations

        static_arguments = _clone_arguments(torch, arguments)
        graph = torch.cuda.CUDAGraph()
        capture_stream = torch.cuda.Stream(device=tensors[0].device)
        capture_stream.wait_stream(torch.cuda.current_stream(device=tensors[0].device))
        with torch.cuda.stream(capture_stream):
            operation(*static_arguments)
        torch.cuda.current_stream(device=tensors[0].device).wait_stream(capture_stream)
        with torch.cuda.graph(graph, stream=capture_stream):
            graph_output = operation(*static_arguments)
        graph.replay()
        torch.cuda.synchronize(tensors[0].device)
        torch.testing.assert_close(
            graph_output,
            expected_output,
            atol=config.atol,
            rtol=config.rtol,
        )
    finally:
        torch.use_deterministic_algorithms(previous_determinism)

    properties = torch.cuda.get_device_properties(device)
    return {
        "artifact_digest": config.artifact_digest,
        "evidence_class": "UNSIGNED_CANDIDATE",
        "hardware": {
            "compute_capability": f"{capability[0]}.{capability[1]}",
            "device_name": properties.name,
        },
        "measurement": {
            "iterations": config.iterations,
            "latency_us": latency_us,
            "warmup": config.warmup,
        },
        "numerical": {"atol": config.atol, "rtol": config.rtol},
        "operator": f"mindclade::{config.operator}",
        "opcheck": dict(opcheck),
        "profile": config.profile,
        "schema_version": 1,
        "source_digest": config.source_digest,
        "target": config.target,
        "toolchain": {
            "cuda": torch.version.cuda,
            "torch": torch.__version__,
        },
    }


@dataclass(frozen=True, slots=True)
class DetachedSignature:
    """One detached Ed25519 signature over canonical receipt JSON."""

    algorithm: str
    key_id: str
    subject_digest: str
    signature: str

    def __post_init__(self) -> None:
        if self.algorithm != "ed25519":
            raise ValueError("receipt signature algorithm must be ed25519")
        if not isinstance(self.key_id, str) or _KEY_ID_RE.fullmatch(self.key_id) is None:
            raise ValueError("receipt signer key_id is invalid")
        _digest(self.subject_digest, "subject_digest")
        try:
            decoded = base64.b64decode(self.signature, validate=True)
        except (TypeError, ValueError) as exc:
            raise ValueError("receipt signature must be canonical base64") from exc
        if len(decoded) != 64:
            raise ValueError("receipt signature must be 64 Ed25519 bytes")

    def to_dict(self) -> dict[str, object]:
        return {
            "algorithm": self.algorithm,
            "key_id": self.key_id,
            "subject_digest": self.subject_digest,
            "signature": self.signature,
        }


@dataclass(frozen=True, slots=True)
class SignedReceipt:
    """Immutable content-addressed receipt bytes plus detached signature."""

    payload_json: bytes
    receipt_digest: str
    signature: DetachedSignature

    def __post_init__(self) -> None:
        if not isinstance(self.payload_json, bytes) or not self.payload_json:
            raise ValueError("signed receipt payload must be immutable bytes")
        _digest(self.receipt_digest, "receipt_digest")
        try:
            payload = json.loads(self.payload_json)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("signed receipt payload is not JSON") from exc
        if canonical_json(payload) != self.payload_json:
            raise ValueError("signed receipt payload is not canonical JSON")
        expected = subject_digest(payload)
        if self.receipt_digest != expected or self.signature.subject_digest != expected:
            raise ValueError("signed receipt content identity mismatch")

    def payload(self) -> Mapping[str, object]:
        value = json.loads(self.payload_json)
        if not isinstance(value, Mapping):
            raise ValueError("signed receipt payload must be an object")
        return value

    @property
    def signature_digest(self) -> str:
        return subject_digest(self.signature.to_dict())


def _evidence_class(value: str) -> str:
    if value not in {PRODUCTION_EVIDENCE, TEST_ONLY_EVIDENCE}:
        raise ValueError("evidence_class is unsupported")
    return value


def _operation(value: str) -> str:
    if not isinstance(value, str) or _OPERATION_RE.fullmatch(value) is None:
        raise ValueError("operation must be mindclade::<canonical-name>")
    return value


def _architecture(value: str) -> str:
    if not isinstance(value, str) or _ARCHITECTURE_RE.fullmatch(value) is None:
        raise ValueError("architecture must be an exact smXXa target")
    return value


def _identity(value: str, label: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"^[a-z][a-z0-9._:/+-]{0,255}$", value) is None:
        raise ValueError(f"{label} is not a canonical identity")
    return value


def _version(value: int, label: str) -> int:
    if type(value) is not int or value < 1:
        raise ValueError(f"{label} must be a positive integer")
    return value


def _workload_dimensions(
    value: tuple[tuple[str, int], ...],
) -> tuple[tuple[str, int], ...]:
    if not isinstance(value, tuple) or not 1 <= len(value) <= 64:
        raise ValueError("dimensions must be a nonempty bounded tuple")
    for name, dimension in value:
        if not isinstance(name, str) or _WORKLOAD_NAME_RE.fullmatch(name) is None:
            raise ValueError("dimension name must be canonical lower_snake_case")
        if type(dimension) is not int or not 0 <= dimension <= (1 << 63) - 1:
            raise ValueError("dimension value must be a non-negative int64")
    if value != tuple(sorted(value)) or len({name for name, _ in value}) != len(value):
        raise ValueError("dimensions must have unique names in canonical order")
    return value


def _workload_attributes(
    value: tuple[tuple[str, str, bool | int | float | str], ...],
) -> tuple[tuple[str, str, bool | int | float | str], ...]:
    if not isinstance(value, tuple) or len(value) > 64:
        raise ValueError("attributes must be a bounded tuple")
    expected_types = {
        "bool": bool,
        "int64": int,
        "float64": float,
        "string": str,
    }
    for name, scalar_type, scalar in value:
        if not isinstance(name, str) or _WORKLOAD_NAME_RE.fullmatch(name) is None:
            raise ValueError("attribute name must be canonical lower_snake_case")
        expected = expected_types.get(scalar_type)
        if expected is None or type(scalar) is not expected:
            raise ValueError("attribute value does not match its scalar type")
        if scalar_type == "int64" and not -(1 << 63) <= scalar <= (1 << 63) - 1:
            raise ValueError("attribute int64 is out of range")
        if scalar_type == "float64" and not math.isfinite(scalar):
            raise ValueError("attribute float64 must be finite")
        if scalar_type == "string" and len(scalar.encode("utf-8")) > 1024:
            raise ValueError("attribute string is too large")
    if value != tuple(sorted(value, key=lambda item: item[0])) or len(
        {name for name, _, _ in value}
    ) != len(value):
        raise ValueError("attributes must have unique names in canonical order")
    return value


def _workload_dimensions_data(
    value: tuple[tuple[str, int], ...],
) -> list[dict[str, object]]:
    return [{"name": name, "value": dimension} for name, dimension in value]


def _workload_attributes_data(
    value: tuple[tuple[str, str, bool | int | float | str], ...],
) -> list[dict[str, object]]:
    return [
        {"name": name, "type": scalar_type, "value": scalar}
        for name, scalar_type, scalar in value
    ]


@dataclass(frozen=True, slots=True)
class K4QualificationReceipt:
    operation: str
    architecture: str
    workload_digest: str
    specialization_digest: str
    dimensions: tuple[tuple[str, int], ...]
    attributes: tuple[tuple[str, str, bool | int | float | str], ...]
    hardware_fingerprint_digest: str
    compile_environment_digest: str
    runtime_compatibility_digest: str
    numerical_receipt_digest: str
    performance_receipt_digest: str
    benchmark_protocol_digest: str
    raw_samples_digest: str
    forward_artifact_digest: str
    backward_artifact_digest: str | None
    native_manifest_schema_version: int
    native_manifest_generator_version: int
    build_receipt_schema_version: int
    autograd_policy: str
    status: str
    evidence_class: str
    version: int = 1

    def __post_init__(self) -> None:
        _operation(self.operation)
        _architecture(self.architecture)
        dimensions = _workload_dimensions(self.dimensions)
        attributes = _workload_attributes(self.attributes)
        if {name for name, _ in dimensions}.intersection(
            name for name, _, _ in attributes
        ):
            raise ValueError("dimension and attribute names must be disjoint")
        for label in (
            "workload_digest",
            "specialization_digest",
            "hardware_fingerprint_digest",
            "compile_environment_digest",
            "runtime_compatibility_digest",
            "numerical_receipt_digest",
            "performance_receipt_digest",
            "benchmark_protocol_digest",
            "raw_samples_digest",
            "forward_artifact_digest",
        ):
            _digest(getattr(self, label), label)
        if self.backward_artifact_digest is not None:
            _digest(self.backward_artifact_digest, "backward_artifact_digest")
        if self.autograd_policy not in {"required", "none", "composite"}:
            raise ValueError("autograd_policy is unsupported")
        if self.autograd_policy == "required" and self.backward_artifact_digest is None:
            raise ValueError("K4 REQUIRED evidence must bind atomic FWD+BWD artifacts")
        if self.autograd_policy != "required" and self.backward_artifact_digest is not None:
            raise ValueError("K4 non-REQUIRED evidence must not bind a native BWD artifact")
        if (
            self.native_manifest_schema_version != 4
            or self.native_manifest_generator_version != 8
            or self.build_receipt_schema_version != 4
        ):
            raise ValueError("K4 evidence binds an obsolete executable ABI receipt")
        evidence = _evidence_class(self.evidence_class)
        expected = "PASS" if evidence == PRODUCTION_EVIDENCE else "TEST_ONLY"
        if self.status != expected:
            raise ValueError(f"{evidence} K4 status must be {expected}")
        _version(self.version, "version")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "mindclade.k4-qualification-receipt.v1",
            "version": self.version,
            "operation": self.operation,
            "architecture": self.architecture,
            "workload_digest": self.workload_digest,
            "specialization_digest": self.specialization_digest,
            "dimensions": _workload_dimensions_data(self.dimensions),
            "attributes": _workload_attributes_data(self.attributes),
            "hardware_fingerprint_digest": self.hardware_fingerprint_digest,
            "compile_environment_digest": self.compile_environment_digest,
            "runtime_compatibility_digest": self.runtime_compatibility_digest,
            "numerical_receipt_digest": self.numerical_receipt_digest,
            "performance_receipt_digest": self.performance_receipt_digest,
            "benchmark_protocol_digest": self.benchmark_protocol_digest,
            "raw_samples_digest": self.raw_samples_digest,
            "forward_artifact_digest": self.forward_artifact_digest,
            "backward_artifact_digest": self.backward_artifact_digest,
            "native_manifest_schema_version": self.native_manifest_schema_version,
            "native_manifest_generator_version": self.native_manifest_generator_version,
            "build_receipt_schema_version": self.build_receipt_schema_version,
            "autograd_policy": self.autograd_policy,
            "status": self.status,
            "evidence_class": self.evidence_class,
        }


@dataclass(frozen=True, slots=True)
class K5ReleaseReceipt:
    release_id: str
    operation: str
    operation_version: int
    implementation: str
    implementation_version: int
    tier: str
    priority: int
    architecture: str
    dtype: str
    layout: str
    mode: str
    workload_digest: str
    specialization_digest: str
    dimensions: tuple[tuple[str, int], ...]
    attributes: tuple[tuple[str, str, bool | int | float | str], ...]
    schedule_digest: str
    numerical_envelope_digest: str
    k0_receipt_digest: str
    k1_receipt_digest: str
    k2_receipt_digest: str
    k3_receipt_digest: str
    k4_receipt_digest: str
    bundle_digest: str
    native_manifest_digest: str
    library_digest: str
    executable_plan_digest: str
    forward_artifact_digest: str
    backward_artifact_digest: str | None
    runtime_compatibility_digest: str
    compile_environment_digest: str
    sbom_digest: str
    provenance_digest: str
    qualification_identity: str
    repository_revision: str
    native_manifest_schema_version: int
    native_manifest_generator_version: int
    build_receipt_schema_version: int
    autograd_policy: str
    status: str
    evidence_class: str
    version: int = 1

    def __post_init__(self) -> None:
        _identity(self.release_id, "release_id")
        _operation(self.operation)
        _version(self.operation_version, "operation_version")
        _identity(self.implementation, "implementation")
        _version(self.implementation_version, "implementation_version")
        if self.tier not in {"portable", "optimized", "specialized", "hand_specialized"}:
            raise ValueError("implementation tier is unsupported")
        if type(self.priority) is not int:
            raise ValueError("priority must be integer")
        _architecture(self.architecture)
        dimensions = _workload_dimensions(self.dimensions)
        attributes = _workload_attributes(self.attributes)
        if {name for name, _ in dimensions}.intersection(
            name for name, _, _ in attributes
        ):
            raise ValueError("dimension and attribute names must be disjoint")
        for label in ("dtype", "layout", "mode", "qualification_identity"):
            _identity(getattr(self, label), label)
        if not isinstance(self.repository_revision, str) or re.fullmatch(
            r"(?:[0-9a-f]{40}|[0-9a-f]{64})", self.repository_revision
        ) is None:
            raise ValueError("repository_revision must be immutable")
        if (
            self.native_manifest_schema_version != 4
            or self.native_manifest_generator_version != 8
            or self.build_receipt_schema_version != 4
        ):
            raise ValueError("K5 release binds an obsolete executable ABI receipt")
        for label in (
            "workload_digest",
            "specialization_digest",
            "schedule_digest",
            "numerical_envelope_digest",
            "k0_receipt_digest",
            "k1_receipt_digest",
            "k2_receipt_digest",
            "k3_receipt_digest",
            "k4_receipt_digest",
            "bundle_digest",
            "native_manifest_digest",
            "library_digest",
            "executable_plan_digest",
            "forward_artifact_digest",
            "runtime_compatibility_digest",
            "compile_environment_digest",
            "sbom_digest",
            "provenance_digest",
        ):
            _digest(getattr(self, label), label)
        if self.backward_artifact_digest is not None:
            _digest(self.backward_artifact_digest, "backward_artifact_digest")
        if self.autograd_policy not in {"required", "none", "composite"}:
            raise ValueError("autograd_policy is unsupported")
        if self.autograd_policy == "required" and self.backward_artifact_digest is None:
            raise ValueError("K5 REQUIRED release must bind atomic FWD+BWD artifacts")
        if self.autograd_policy != "required" and self.backward_artifact_digest is not None:
            raise ValueError("K5 non-REQUIRED release must not bind a native BWD artifact")
        evidence = _evidence_class(self.evidence_class)
        expected = "PASS" if evidence == PRODUCTION_EVIDENCE else "TEST_ONLY"
        if self.status != expected:
            raise ValueError(f"{evidence} K5 status must be {expected}")
        _version(self.version, "version")

    def to_dict(self) -> dict[str, object]:
        result = {
            "schema_version": "mindclade.k5-release-receipt.v1",
            "version": self.version,
            **{
                field: getattr(self, field)
                for field in self.__dataclass_fields__
                if field not in {"version", "dimensions", "attributes"}
            },
        }
        result["dimensions"] = _workload_dimensions_data(self.dimensions)
        result["attributes"] = _workload_attributes_data(self.attributes)
        return result


@dataclass(frozen=True, slots=True)
class RevocationReceipt:
    capability_digest: str
    release_receipt_digest: str
    reason_code: str
    revocation_policy_identity: str
    sequence: int
    evidence_class: str
    version: int = 1

    def __post_init__(self) -> None:
        _digest(self.capability_digest, "capability_digest")
        _digest(self.release_receipt_digest, "release_receipt_digest")
        _identity(self.reason_code, "reason_code")
        _identity(self.revocation_policy_identity, "revocation_policy_identity")
        _version(self.sequence, "sequence")
        _evidence_class(self.evidence_class)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "mindclade.capability-revocation-receipt.v1",
            "version": self.version,
            "capability_digest": self.capability_digest,
            "release_receipt_digest": self.release_receipt_digest,
            "reason_code": self.reason_code,
            "revocation_policy_identity": self.revocation_policy_identity,
            "sequence": self.sequence,
            "evidence_class": self.evidence_class,
        }


@dataclass(frozen=True, slots=True)
class RollbackReceipt:
    revoked_capability_digest: str
    replacement_capability_digest: str
    replacement_release_receipt_digest: str
    reason_code: str
    sequence: int
    evidence_class: str
    version: int = 1

    def __post_init__(self) -> None:
        _digest(self.revoked_capability_digest, "revoked_capability_digest")
        _digest(self.replacement_capability_digest, "replacement_capability_digest")
        _digest(self.replacement_release_receipt_digest, "replacement_release_receipt_digest")
        if self.revoked_capability_digest == self.replacement_capability_digest:
            raise ValueError("rollback must select a distinct prior capability")
        _identity(self.reason_code, "reason_code")
        _version(self.sequence, "sequence")
        _evidence_class(self.evidence_class)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "mindclade.capability-rollback-receipt.v1",
            "version": self.version,
            "revoked_capability_digest": self.revoked_capability_digest,
            "replacement_capability_digest": self.replacement_capability_digest,
            "replacement_release_receipt_digest": self.replacement_release_receipt_digest,
            "reason_code": self.reason_code,
            "sequence": self.sequence,
            "evidence_class": self.evidence_class,
        }


def sign_receipt(
    receipt: K4QualificationReceipt | K5ReleaseReceipt | RevocationReceipt | RollbackReceipt,
    *,
    private_key: Ed25519PrivateKey,
    key_id: str,
) -> SignedReceipt:
    """Sign a receipt supplied by a protected qualification lane."""

    if not isinstance(private_key, Ed25519PrivateKey):
        raise TypeError("private_key must be Ed25519PrivateKey")
    if not isinstance(key_id, str) or _KEY_ID_RE.fullmatch(key_id) is None:
        raise ValueError("key_id is invalid")
    payload = receipt.to_dict()
    if payload["evidence_class"] == PRODUCTION_EVIDENCE and key_id.startswith("test-only"):
        raise ValueError("test-only key cannot sign production evidence")
    payload_json = canonical_json(payload)
    digest = subject_digest(payload)
    signature = DetachedSignature(
        algorithm="ed25519",
        key_id=key_id,
        subject_digest=digest,
        signature=base64.b64encode(private_key.sign(payload_json)).decode("ascii"),
    )
    return SignedReceipt(payload_json, digest, signature)


def verify_signed_receipt(
    receipt: SignedReceipt,
    *,
    trust_roots: Mapping[str, Ed25519PublicKey],
    expected_evidence_class: str,
) -> Mapping[str, object]:
    """Verify exact content identity, signer trust, and evidence class."""

    if not isinstance(receipt, SignedReceipt):
        raise TypeError("receipt must be SignedReceipt")
    _evidence_class(expected_evidence_class)
    key = trust_roots.get(receipt.signature.key_id)
    if not isinstance(key, Ed25519PublicKey):
        raise ValueError("receipt signer is not an explicit trusted Ed25519 root")
    try:
        key.verify(base64.b64decode(receipt.signature.signature), receipt.payload_json)
    except InvalidSignature as exc:
        raise ValueError("receipt signature verification failed") from exc
    payload = receipt.payload()
    if payload.get("evidence_class") != expected_evidence_class:
        raise ValueError("receipt evidence class mismatch")
    if expected_evidence_class == PRODUCTION_EVIDENCE and receipt.signature.key_id.startswith("test-only"):
        raise ValueError("test-only signer cannot verify production evidence")
    return payload


def _capability_body(release: Mapping[str, object], signed: SignedReceipt) -> dict[str, object]:
    fields = (
        "operation",
        "operation_version",
        "implementation",
        "implementation_version",
        "tier",
        "priority",
        "architecture",
        "dtype",
        "layout",
        "mode",
        "workload_digest",
        "specialization_digest",
        "dimensions",
        "attributes",
        "schedule_digest",
        "numerical_envelope_digest",
        "runtime_compatibility_digest",
        "compile_environment_digest",
        "bundle_digest",
        "native_manifest_digest",
        "library_digest",
        "executable_plan_digest",
        "forward_artifact_digest",
        "backward_artifact_digest",
        "qualification_identity",
        "repository_revision",
        "native_manifest_schema_version",
        "native_manifest_generator_version",
        "build_receipt_schema_version",
        "autograd_policy",
    )
    body = {field: release[field] for field in fields}
    body.update(
        {
            "release_receipt_digest": signed.receipt_digest,
            "release_signature_digest": signed.signature_digest,
            "k4_receipt_digest": release["k4_receipt_digest"],
        }
    )
    return body


def capability_identity(release: SignedReceipt) -> str:
    """Return the immutable capability identity represented by one K5 receipt."""

    payload = release.payload()
    if payload.get("schema_version") != "mindclade.k5-release-receipt.v1":
        raise ValueError("capability identity requires a K5 release receipt")
    return subject_digest(_capability_body(payload, release))


def build_signed_capability_index(
    *,
    releases: tuple[SignedReceipt, ...],
    k4_receipts: Mapping[str, SignedReceipt],
    revocations: tuple[SignedReceipt, ...] = (),
    rollbacks: tuple[SignedReceipt, ...] = (),
    trust_roots: Mapping[str, Ed25519PublicKey],
    evidence_class: str,
    index_private_key: Ed25519PrivateKey,
    index_key_id: str,
) -> bytes:
    """Build one signed compact index from already signed immutable receipts."""

    evidence = _evidence_class(evidence_class)
    expected_status = "PASS" if evidence == PRODUCTION_EVIDENCE else "TEST_ONLY"
    capability_pairs: list[tuple[dict[str, object], Mapping[str, object]]] = []
    for signed in releases:
        release = verify_signed_receipt(
            signed, trust_roots=trust_roots, expected_evidence_class=evidence
        )
        if release.get("schema_version") != "mindclade.k5-release-receipt.v1":
            raise ValueError("promotion input is not a K5 release receipt")
        if release.get("status") != expected_status:
            raise ValueError("K5 receipt status is not promotable")
        k4_digest = release.get("k4_receipt_digest")
        if not isinstance(k4_digest, str) or k4_digest not in k4_receipts:
            raise ValueError("K5 receipt does not reference supplied K4 evidence")
        k4 = verify_signed_receipt(
            k4_receipts[k4_digest],
            trust_roots=trust_roots,
            expected_evidence_class=evidence,
        )
        if k4_receipts[k4_digest].receipt_digest != k4_digest:
            raise ValueError("K4 evidence map key does not match receipt identity")
        if k4.get("schema_version") != "mindclade.k4-qualification-receipt.v1" or k4.get("status") != expected_status:
            raise ValueError("K4 evidence is not eligible")
        for field in (
            "operation",
            "architecture",
            "workload_digest",
            "specialization_digest",
            "dimensions",
            "attributes",
            "forward_artifact_digest",
            "backward_artifact_digest",
            "native_manifest_schema_version",
            "native_manifest_generator_version",
            "build_receipt_schema_version",
            "autograd_policy",
        ):
            if k4.get(field) != release.get(field):
                raise ValueError(f"K4/K5 binding mismatch for {field}")
        body = _capability_body(release, signed)
        capability_pairs.append(({**body, "capability_digest": subject_digest(body)}, release))

    revocation_items: list[dict[str, object]] = []
    revoked: set[str] = set()
    for signed in revocations:
        value = verify_signed_receipt(
            signed, trust_roots=trust_roots, expected_evidence_class=evidence
        )
        if value.get("schema_version") != "mindclade.capability-revocation-receipt.v1":
            raise ValueError("revocation input has the wrong receipt type")
        capability_digest = _digest(str(value.get("capability_digest")), "capability_digest")
        revoked.add(capability_digest)
        revocation_items.append(
            {
                "capability_digest": capability_digest,
                "revocation_receipt_digest": signed.receipt_digest,
            }
        )
    capabilities = [item for item, _release in capability_pairs if item["capability_digest"] not in revoked]
    capability_ids = {str(item["capability_digest"]) for item in capabilities}
    signed_by_capability = {
        str(item["capability_digest"]): signed
        for (item, _release), signed in zip(capability_pairs, releases, strict=True)
    }
    rollback_items: list[dict[str, object]] = []
    for signed in rollbacks:
        value = verify_signed_receipt(
            signed, trust_roots=trust_roots, expected_evidence_class=evidence
        )
        if value.get("schema_version") != "mindclade.capability-rollback-receipt.v1":
            raise ValueError("rollback input has the wrong receipt type")
        source = _digest(str(value.get("revoked_capability_digest")), "revoked_capability_digest")
        replacement = _digest(str(value.get("replacement_capability_digest")), "replacement_capability_digest")
        if source not in revoked or replacement not in capability_ids:
            raise ValueError("rollback does not select a qualified prior capability")
        if (
            value.get("replacement_release_receipt_digest")
            != signed_by_capability[replacement].receipt_digest
        ):
            raise ValueError("rollback replacement release identity mismatch")
        rollback_items.append(
            {
                "revoked_capability_digest": source,
                "replacement_capability_digest": replacement,
                "rollback_receipt_digest": signed.receipt_digest,
            }
        )
    status = "K5_PASS" if evidence == PRODUCTION_EVIDENCE else "TEST_ONLY"
    for item in capabilities:
        item["status"] = status
    capabilities.sort(key=lambda item: str(item["capability_digest"]))
    revocation_items.sort(key=lambda item: str(item["capability_digest"]))
    rollback_items.sort(
        key=lambda item: (
            str(item["revoked_capability_digest"]),
            str(item["replacement_capability_digest"]),
        )
    )
    index_body: dict[str, object] = {
        "schema_version": 1,
        "evidence_class": evidence,
        "capabilities": capabilities,
        "revocations": revocation_items,
        "rollbacks": rollback_items,
    }
    index = {**index_body, "index_digest": subject_digest(index_body)}
    if evidence == PRODUCTION_EVIDENCE and index_key_id.startswith("test-only"):
        raise ValueError("test-only key cannot sign a production capability index")
    signed_index = sign_receipt_payload(
        index,
        private_key=index_private_key,
        key_id=index_key_id,
    )
    document = {
        "payload_type": "application/vnd.mindclade.qualified-capability-index.v1+json",
        "index": index,
        "signature": signed_index.to_dict(),
    }
    return canonical_json(document)


def sign_receipt_payload(
    payload: Mapping[str, object],
    *,
    private_key: Ed25519PrivateKey,
    key_id: str,
) -> DetachedSignature:
    """Sign a canonical mapping such as the compact capability index."""

    if not isinstance(private_key, Ed25519PrivateKey):
        raise TypeError("private_key must be Ed25519PrivateKey")
    if not isinstance(key_id, str) or _KEY_ID_RE.fullmatch(key_id) is None:
        raise ValueError("key_id is invalid")
    digest = subject_digest(payload)
    return DetachedSignature(
        algorithm="ed25519",
        key_id=key_id,
        subject_digest=digest,
        signature=base64.b64encode(private_key.sign(canonical_json(payload))).decode("ascii"),
    )
