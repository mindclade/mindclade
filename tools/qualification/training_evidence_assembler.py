#!/usr/bin/env python3.12
"""Assemble six protected qualification receipts into Stage 5 v2 evidence."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import cast

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.ci.evidence_bundle import canonical_json as signed_payload_json
from tools.ci.evidence_bundle import validate_trusted_context

type JsonScalar = bool | float | int | str | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]
type JsonObject = dict[str, JsonValue]

EVIDENCE_SCHEMA = "mindclade.training-vertical-evidence/v2"
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
TARGET_RE = re.compile(r"^//[A-Za-z0-9_./-]*:[A-Za-z0-9_.+-]+$")
RESULT_PATH_RE = re.compile(r"^build/evidence/[A-Za-z0-9._/-]+\.json$")
BUILDKITE_IDENTITY_RE = re.compile(r"^buildkite://[a-z0-9][a-z0-9._/-]{7,255}$")
PRINCIPAL_IDENTITY_RE = re.compile(r"^principal://[a-z0-9][a-z0-9._/-]{7,255}$")
APPROVAL_ID_RE = re.compile(r"^[a-z][a-z0-9._-]{7,127}$")
UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
SDK_LANGUAGES = frozenset({"go", "python", "rust", "typescript"})
APPROVED_REVIEWER_IDENTITIES = frozenset({"principal://mindclade/reviewers/contract-governance"})
PROTECTED_CONTEXT_PRODUCER_IDENTITY = "principal://mindclade/ci/protected-dispatch"
PROTECTED_CONTEXT_PAYLOAD_TYPE = (
    "application/vnd.mindclade.protected-trusted-context.v1+json"
)
APPROVAL_PAYLOAD_TYPE = "application/vnd.mindclade.training-evidence-approval.v1+json"
RATIFICATION_BINDING_FIELDS = frozenset(
    {
        "candidate_descriptor_digest",
        "codegen_toolchain_digest",
        "event_registry_digest",
        "generated_manifest_digest",
        "grpc_implementation_digest",
        "migration_set_digest",
        "openapi_projection_digest",
        "sdk_package_digests",
        "sdk_rpc_coverage_digest",
        "source_revision",
    }
)
PROTECTED_CONTEXT_FIELDS = frozenset(
    {
        "context_digest",
        "execution_tier",
        "launcher_identity",
        "pipeline_class",
        "pipeline_definition_revision",
        "protected_build_identity",
        "source_revision",
        "source_trust",
    }
)
ASSEMBLED_CHECK_FIELDS = frozenset(
    {"producer_identity", "receipt_digest", "result_artifact_digest", "status"}
)
ASSEMBLED_APPROVAL_FIELDS = frozenset(
    {"approval_digest", "approval_id", "approved_at", "reviewer_identity"}
)


@dataclass(frozen=True)
class ReceiptContract:
    schema_version: str
    result_schema_version: str
    binding_fields: frozenset[str]
    required_targets: tuple[str, ...]
    producer_identity: str


@dataclass(frozen=True)
class AttestedArtifact:
    """One canonical JSON payload and its detached DSSE verification material."""

    payload_path: Path
    signature_envelope_path: Path
    public_key_path: Path


@dataclass(frozen=True)
class SignerTrustPolicy:
    """Repository-owned identity-to-key authorization for protected evidence."""

    receipt_signer_key_ids: Mapping[str, frozenset[str]]
    approval_signer_key_ids: Mapping[str, frozenset[str]]
    context_signer_key_ids: Mapping[str, frozenset[str]]


@dataclass(frozen=True)
class VerifiedAttestation:
    payload: bytes
    envelope_digest: str
    key_id: str
    principal_identity: str


RECEIPT_CONTRACTS = {
    "cross_language": ReceiptContract(
        "mindclade.cross-language-conformance/v1",
        "mindclade.cross-language-conformance-result/v1",
        frozenset(
            {
                "candidate_descriptor_digest",
                "codegen_toolchain_digest",
                "generated_manifest_digest",
                "source_revision",
            }
        ),
        (
            "//:all_contract_tests",
            "//tests:generated_clients_test",
            "//tests:generated_go_roundtrip_test",
            "//tests:generated_rust_roundtrip_test",
            "//tests:generated_typescript_roundtrip_test",
            "//tests:wave1_contract_tests",
            "//tools:repository_governance_tests",
            "//tools:training_evidence_test",
        ),
        "principal://mindclade/qualification/cross-language",
    ),
    "database": ReceiptContract(
        "mindclade.protected-fresh-database-qualification/v1",
        "mindclade.protected-fresh-database-qualification-result/v1",
        frozenset({"migration_set_digest", "source_revision"}),
        (
            "//services/control_plane:tests",
            "//tests:artifact_commit_integration_test",
            "//tests:control_worker_integration_test",
            "//tests:local_stack_integration_test",
        ),
        "principal://mindclade/qualification/database",
    ),
    "event": ReceiptContract(
        "mindclade.event-delivery-qualification/v1",
        "mindclade.event-delivery-qualification-result/v1",
        frozenset(
            {
                "candidate_descriptor_digest",
                "codegen_toolchain_digest",
                "event_registry_digest",
                "migration_set_digest",
                "source_revision",
            }
        ),
        (
            "//services/control_plane/internal/platform/eventprojection:event_projection_test",
            "//services/control_plane:control_plane_test",
            "//services/control_plane:jobs_server_test",
        ),
        "principal://mindclade/qualification/event-delivery",
    ),
    "gateway": ReceiptContract(
        "mindclade.gateway-sse-qualification/v1",
        "mindclade.gateway-sse-qualification-result/v1",
        frozenset(
            {
                "candidate_descriptor_digest",
                "codegen_toolchain_digest",
                "openapi_projection_digest",
                "source_revision",
            }
        ),
        (
            "//protocols:openapi_compatibility_test",
            "//protocols:protobuf_compatibility_test",
            "//services/control_plane:control_plane_grpc_registration_test",
        ),
        "principal://mindclade/qualification/gateway-sse",
    ),
    "grpc": ReceiptContract(
        "mindclade.grpc-conformance/v1",
        "mindclade.grpc-conformance-result/v1",
        frozenset(
            {
                "candidate_descriptor_digest",
                "codegen_toolchain_digest",
                "grpc_implementation_digest",
                "source_revision",
            }
        ),
        ("//services/control_plane:control_plane_grpc_registration_test",),
        "principal://mindclade/qualification/grpc",
    ),
    "sdk": ReceiptContract(
        "mindclade.sdk-conformance/v1",
        "mindclade.sdk-conformance-result/v1",
        frozenset(
            {
                "candidate_descriptor_digest",
                "codegen_toolchain_digest",
                "generated_manifest_digest",
                "sdk_package_digests",
                "sdk_rpc_coverage_digest",
                "source_revision",
            }
        ),
        (
            "//internal/sdk/go/mindclade:mindclade_test",
            "//internal/sdk/python:tests",
            "//internal/sdk/rust:mindclade_internal_sdk_test",
            "//internal/sdk/typescript:tests",
        ),
        "principal://mindclade/qualification/sdk",
    ),
}
# Connected authority has not activated producer, reviewer, or protected-context
# signing keys. Caller-provided paths and key IDs never extend these allowlists.
# A future protected source change must add reviewed DER-SPKI SHA-256 key IDs.
GOVERNED_SIGNER_TRUST_POLICY = SignerTrustPolicy(
    receipt_signer_key_ids={name: frozenset() for name in RECEIPT_CONTRACTS},
    approval_signer_key_ids={identity: frozenset() for identity in APPROVED_REVIEWER_IDENTITIES},
    context_signer_key_ids={PROTECTED_CONTEXT_PRODUCER_IDENTITY: frozenset()},
)
RECEIPT_FIELDS = frozenset(
    {
        "bindings",
        "completed_at",
        "executed_bazel_targets",
        "producer_identity",
        "protected_build_identity",
        "receipt_digest",
        "result_artifact_digest",
        "result_artifact_path",
        "required_bazel_targets",
        "schema_version",
        "skipped_required_tests",
        "started_at",
        "status",
    }
)
RESULT_FIELDS = frozenset(
    {
        "bazel_targets",
        "completed_at",
        "failed_tests",
        "protected_build_identity",
        "schema_version",
        "skipped_tests",
        "source_revision",
        "started_at",
        "status",
    }
)
APPROVAL_FIELDS = frozenset(
    {
        "approval_id",
        "approved_at",
        "decision",
        "gate",
        "kind",
        "protected_build_identity",
        "receipt_digests",
        "reviewer_identity",
        "schema_version",
        "source_revision",
    }
)


def canonical_json(value: JsonValue) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def receipt_payload_type(name: str) -> str:
    if name not in RECEIPT_CONTRACTS:
        raise ValueError(f"unsupported qualification receipt name: {name}")
    media_name = name.replace("_", "-")
    return f"application/vnd.mindclade.{media_name}-qualification-receipt.v1+json"


def dsse_pae(payload_type: str, payload: bytes) -> bytes:
    type_bytes = payload_type.encode("utf-8")
    return b" ".join(
        (
            b"DSSEv1",
            str(len(type_bytes)).encode("ascii"),
            type_bytes,
            str(len(payload)).encode("ascii"),
            payload,
        )
    )


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def decode_object(encoded: bytes, label: str) -> JsonObject:
    try:
        value: object = json.loads(
            encoded.decode("utf-8"),
            object_pairs_hook=_unique_object,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot decode {label} as JSON: {error}") from error
    if not isinstance(value, dict):
        raise ValueError(f"{label} must contain one JSON object")
    return cast(JsonObject, value)


def load_object(path: Path) -> JsonObject:
    return decode_object(path.read_bytes(), str(path))


def _decode_base64(value: JsonValue, label: str) -> bytes:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be canonical base64")
    try:
        decoded = base64.b64decode(value, validate=True)
    except ValueError as error:
        raise ValueError(f"{label} must be canonical base64") from error
    if base64.b64encode(decoded).decode("ascii") != value:
        raise ValueError(f"{label} must be canonical base64")
    return decoded


def _validate_signer_trust_policy(policy: SignerTrustPolicy) -> None:
    if set(policy.receipt_signer_key_ids) != set(RECEIPT_CONTRACTS):
        raise ValueError("receipt signer trust policy does not cover the exact six lanes")
    if set(policy.approval_signer_key_ids) != set(APPROVED_REVIEWER_IDENTITIES):
        raise ValueError("approval signer trust policy differs from governed reviewer identities")
    if set(policy.context_signer_key_ids) != {PROTECTED_CONTEXT_PRODUCER_IDENTITY}:
        raise ValueError("protected-context signer trust policy differs from governed identity")

    all_authorizations: list[tuple[str, str]] = []
    for lane, key_ids in sorted(policy.receipt_signer_key_ids.items()):
        if not isinstance(key_ids, frozenset):
            raise ValueError(f"{lane} signer trust policy must be immutable")
        all_authorizations.extend((f"receipt:{lane}", key_id) for key_id in key_ids)
    for identity, key_ids in sorted(policy.approval_signer_key_ids.items()):
        if not isinstance(key_ids, frozenset):
            raise ValueError(f"{identity} signer trust policy must be immutable")
        all_authorizations.extend((f"approval:{identity}", key_id) for key_id in key_ids)
    for identity, key_ids in sorted(policy.context_signer_key_ids.items()):
        if not isinstance(key_ids, frozenset):
            raise ValueError(f"{identity} signer trust policy must be immutable")
        all_authorizations.extend((f"context:{identity}", key_id) for key_id in key_ids)

    key_owners: dict[str, str] = {}
    for owner, key_id in all_authorizations:
        _require_string(key_id, f"{owner} signer key ID", DIGEST_RE)
        previous = key_owners.get(key_id)
        if previous is not None:
            raise ValueError(
                f"signer key {key_id} is authorized for both {previous} and {owner}"
            )
        key_owners[key_id] = owner


def _verify_attestation(
    artifact: AttestedArtifact,
    *,
    label: str,
    payload_type: str,
    principal_identity: str,
    authorized_key_ids: frozenset[str],
    payload: bytes | None = None,
) -> VerifiedAttestation:
    """Verify one exact canonical DSSE/Ed25519 attestation without caller trust."""

    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519

    if not authorized_key_ids:
        raise ValueError(f"{label} signer trust is not activated by connected authority")
    payload = artifact.payload_path.read_bytes() if payload is None else payload
    envelope_bytes = artifact.signature_envelope_path.read_bytes()
    envelope = decode_object(envelope_bytes, f"{label} signature envelope")
    if set(envelope) != {"payloadType", "payload", "signatures"}:
        raise ValueError(f"{label} signature envelope fields differ from DSSE policy")
    if envelope.get("payloadType") != payload_type:
        raise ValueError(f"{label} signature envelope has the wrong payload type")
    if _decode_base64(envelope.get("payload"), f"{label} signature payload") != payload:
        raise ValueError(f"{label} signature does not bind the exact payload bytes")
    raw_signatures = envelope.get("signatures")
    if not isinstance(raw_signatures, list) or len(raw_signatures) != 1:
        raise ValueError(f"{label} must have exactly one qualified signature")
    raw_signature = raw_signatures[0]
    if not isinstance(raw_signature, dict) or set(raw_signature) != {"keyid", "sig"}:
        raise ValueError(f"{label} signature entry fields differ from DSSE policy")
    signature_entry = cast(JsonObject, raw_signature)
    key_id = _require_string(signature_entry.get("keyid"), f"{label} signer key ID", DIGEST_RE)
    if key_id not in authorized_key_ids:
        raise ValueError(f"{label} signer key is not authorized by repository policy")

    try:
        loaded_key = serialization.load_pem_public_key(artifact.public_key_path.read_bytes())
    except (OSError, TypeError, ValueError) as error:
        raise ValueError(f"{label} public key is not valid PEM") from error
    if not isinstance(loaded_key, ed25519.Ed25519PublicKey):
        raise ValueError(f"{label} signer must use Ed25519")
    encoded_key = loaded_key.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    if sha256_bytes(encoded_key) != key_id:
        raise ValueError(f"{label} signer key ID does not bind the supplied public key")
    signature = _decode_base64(signature_entry.get("sig"), f"{label} signature")
    try:
        loaded_key.verify(signature, dsse_pae(payload_type, payload))
    except InvalidSignature as error:
        raise ValueError(f"{label} signature verification failed") from error
    if envelope_bytes != canonical_json(envelope):
        raise ValueError(f"{label} signature envelope is not canonical JSON")
    return VerifiedAttestation(
        payload=payload,
        envelope_digest=sha256_bytes(envelope_bytes),
        key_id=key_id,
        principal_identity=principal_identity,
    )


def _require_string(
    value: JsonValue,
    label: str,
    pattern: re.Pattern[str] | None = None,
) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a non-empty string")
    if pattern is not None and pattern.fullmatch(value) is None:
        raise ValueError(f"{label} has an invalid value")
    return value


def _require_string_array(
    value: JsonValue,
    label: str,
    *,
    nonempty: bool,
    pattern: re.Pattern[str] | None = None,
) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{label} must be a string array")
    result = cast(list[str], value)
    if nonempty and not result:
        raise ValueError(f"{label} must not be empty")
    if result != sorted(set(result)):
        raise ValueError(f"{label} must be sorted and unique")
    if pattern is not None and any(pattern.fullmatch(item) is None for item in result):
        raise ValueError(f"{label} contains an invalid value")
    return result


def _require_utc(value: JsonValue, label: str) -> datetime:
    text = _require_string(value, label, UTC_RE)
    return datetime.fromisoformat(text.removesuffix("Z") + "+00:00")


def _validate_binding(name: str, value: JsonValue, receipt_name: str) -> JsonValue:
    label = f"{receipt_name} receipt binding {name}"
    if name == "source_revision":
        return _require_string(value, label, REVISION_RE)
    if name == "sdk_package_digests":
        if not isinstance(value, dict) or set(value) != set(SDK_LANGUAGES):
            raise ValueError(f"{label} must contain exactly the four SDK languages")
        digests = cast(JsonObject, value)
        for language, digest in sorted(digests.items()):
            _require_string(digest, f"{label}.{language}", DIGEST_RE)
        return digests
    return _require_string(value, label, DIGEST_RE)


def _result_artifact_path(root: Path, value: JsonValue, name: str) -> Path:
    raw = _require_string(value, f"{name} receipt result_artifact_path", RESULT_PATH_RE)
    relative = Path(raw)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"{name} receipt result_artifact_path is not canonical")
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or path.is_symlink() or not path.is_file():
        raise ValueError(f"{name} receipt result artifact is not a repository-owned file")
    return path


def _validate_result_artifact(
    name: str,
    path: Path,
    *,
    contract: ReceiptContract,
    trusted_source_revision: str,
    trusted_build_identity: str,
    started_at: datetime,
    completed_at: datetime,
) -> str:
    encoded = path.read_bytes()
    result = decode_object(encoded, f"{name} result artifact")
    if set(result) != set(RESULT_FIELDS):
        raise ValueError(f"{name} result artifact fields differ from its exact contract")
    if result.get("schema_version") != contract.result_schema_version:
        raise ValueError(f"{name} result artifact has an unsupported schema_version")
    if result.get("status") != "passed":
        raise ValueError(f"{name} result artifact is not passed")
    if result.get("source_revision") != trusted_source_revision:
        raise ValueError(f"{name} result artifact is stale")
    if result.get("protected_build_identity") != trusted_build_identity:
        raise ValueError(f"{name} result artifact is not from the trusted protected build")
    targets = _require_string_array(
        result.get("bazel_targets"),
        f"{name} result artifact bazel_targets",
        nonempty=True,
        pattern=TARGET_RE,
    )
    if targets != list(contract.required_targets):
        raise ValueError(f"{name} result artifact target set differs from policy")
    failed = _require_string_array(
        result.get("failed_tests"), f"{name} result artifact failed_tests", nonempty=False
    )
    skipped = _require_string_array(
        result.get("skipped_tests"), f"{name} result artifact skipped_tests", nonempty=False
    )
    if failed or skipped:
        raise ValueError(f"{name} result artifact contains failed or skipped tests")
    result_started = _require_utc(result.get("started_at"), f"{name} result started_at")
    result_completed = _require_utc(result.get("completed_at"), f"{name} result completed_at")
    if result_started != started_at or result_completed != completed_at:
        raise ValueError(f"{name} receipt timestamps do not bind the result artifact")
    if result_completed < result_started:
        raise ValueError(f"{name} result artifact completed before it started")
    if encoded != canonical_json(result):
        raise ValueError(f"{name} result artifact is not canonical JSON")
    return sha256_bytes(encoded)


def _validate_receipt(
    name: str,
    encoded: bytes,
    path: Path,
    *,
    root: Path,
    trusted_source_revision: str,
    trusted_build_identity: str,
) -> tuple[JsonObject, str, str, datetime, Path]:
    contract = RECEIPT_CONTRACTS[name]
    receipt = decode_object(encoded, f"{name} receipt")
    if set(receipt) != set(RECEIPT_FIELDS):
        raise ValueError(
            f"{name} receipt fields differ: "
            f"missing={sorted(RECEIPT_FIELDS - set(receipt))}, "
            f"unexpected={sorted(set(receipt) - RECEIPT_FIELDS)}"
        )
    if receipt.get("schema_version") != contract.schema_version:
        raise ValueError(f"{name} receipt has an unsupported schema_version")
    if receipt.get("status") != "passed":
        raise ValueError(f"{name} receipt is not passed")
    producer_identity = _require_string(
        receipt.get("producer_identity"),
        f"{name} receipt producer_identity",
        PRINCIPAL_IDENTITY_RE,
    )
    if producer_identity != contract.producer_identity:
        raise ValueError(f"{name} receipt producer_identity differs from policy")
    build_identity = _require_string(
        receipt.get("protected_build_identity"),
        f"{name} receipt protected_build_identity",
        BUILDKITE_IDENTITY_RE,
    )
    if build_identity != trusted_build_identity:
        raise ValueError(f"{name} receipt is not from the trusted protected build")
    started_at = _require_utc(receipt.get("started_at"), f"{name} receipt started_at")
    completed_at = _require_utc(receipt.get("completed_at"), f"{name} receipt completed_at")
    if completed_at < started_at:
        raise ValueError(f"{name} receipt completed before it started")
    required_targets = _require_string_array(
        receipt.get("required_bazel_targets"),
        f"{name} receipt required_bazel_targets",
        nonempty=True,
        pattern=TARGET_RE,
    )
    executed_targets = _require_string_array(
        receipt.get("executed_bazel_targets"),
        f"{name} receipt executed_bazel_targets",
        nonempty=True,
        pattern=TARGET_RE,
    )
    if executed_targets != required_targets:
        raise ValueError(f"{name} receipt did not execute its exact required target set")
    if executed_targets != list(contract.required_targets):
        raise ValueError(f"{name} receipt target set differs from policy")
    skipped = _require_string_array(
        receipt.get("skipped_required_tests"),
        f"{name} receipt skipped_required_tests",
        nonempty=False,
    )
    if skipped:
        raise ValueError(f"{name} receipt skipped required tests")

    bindings_value = receipt.get("bindings")
    if not isinstance(bindings_value, dict):
        raise ValueError(f"{name} receipt bindings must be an object")
    bindings = cast(JsonObject, bindings_value)
    if set(bindings) != set(contract.binding_fields):
        raise ValueError(
            f"{name} receipt binding fields differ: "
            f"missing={sorted(contract.binding_fields - set(bindings))}, "
            f"unexpected={sorted(set(bindings) - contract.binding_fields)}"
        )
    for binding_name, value in sorted(bindings.items()):
        _validate_binding(binding_name, value, name)
    if bindings.get("source_revision") != trusted_source_revision:
        raise ValueError(f"{name} receipt is stale or bound to another source revision")

    result_path = _result_artifact_path(root, receipt.get("result_artifact_path"), name)
    expected_result_digest = _validate_result_artifact(
        name,
        result_path,
        contract=contract,
        trusted_source_revision=trusted_source_revision,
        trusted_build_identity=trusted_build_identity,
        started_at=started_at,
        completed_at=completed_at,
    )
    result_digest = _require_string(
        receipt.get("result_artifact_digest"),
        f"{name} receipt result_artifact_digest",
        DIGEST_RE,
    )
    if result_digest != expected_result_digest:
        raise ValueError(f"{name} receipt does not bind its exact result artifact")

    receipt_digest = _require_string(
        receipt.get("receipt_digest"), f"{name} receipt receipt_digest", DIGEST_RE
    )
    unsigned = dict(receipt)
    unsigned.pop("receipt_digest")
    if receipt_digest != sha256_bytes(canonical_json(cast(JsonValue, unsigned))):
        raise ValueError(f"{name} receipt_digest does not bind canonical receipt content")
    if encoded != canonical_json(receipt):
        raise ValueError(f"{name} receipt is not canonical JSON")
    return bindings, receipt_digest, result_digest, completed_at, result_path


def _validate_approval(
    encoded: bytes,
    *,
    approval_attestation_digest: str,
    authenticated_reviewer: str,
    receipt_digests: Mapping[str, str],
    producer_identities: set[str],
    latest_completion: datetime,
    trusted_source_revision: str,
    trusted_build_identity: str,
) -> JsonObject:
    approval = decode_object(encoded, "Stage 5 approval")
    if set(approval) != set(APPROVAL_FIELDS):
        raise ValueError(
            "Stage 5 approval fields differ: "
            f"missing={sorted(APPROVAL_FIELDS - set(approval))}, "
            f"unexpected={sorted(set(approval) - APPROVAL_FIELDS)}"
        )
    if approval.get("schema_version") != "mindclade.training-evidence-approval/v1":
        raise ValueError("Stage 5 approval has an unsupported schema_version")
    if (
        approval.get("kind") != "QualificationApproval"
        or approval.get("gate") != "stage-5-contract-ratification"
        or approval.get("decision") != "approved"
    ):
        raise ValueError("Stage 5 approval does not authorize the ratification gate")
    approval_id = _require_string(
        approval.get("approval_id"), "Stage 5 approval_id", APPROVAL_ID_RE
    )
    reviewer = _require_string(
        approval.get("reviewer_identity"),
        "Stage 5 reviewer_identity",
        PRINCIPAL_IDENTITY_RE,
    )
    if reviewer not in APPROVED_REVIEWER_IDENTITIES:
        raise ValueError("Stage 5 reviewer_identity is not authorized by policy")
    if reviewer != authenticated_reviewer:
        raise ValueError("Stage 5 reviewer identity is not authenticated by its signer")
    if reviewer in producer_identities:
        raise ValueError("Stage 5 reviewer is not independent of receipt producers")
    if approval.get("source_revision") != trusted_source_revision:
        raise ValueError("Stage 5 approval is stale or bound to another source revision")
    if approval.get("protected_build_identity") != trusted_build_identity:
        raise ValueError("Stage 5 approval is not bound to the trusted protected build")
    approved_at = _require_utc(approval.get("approved_at"), "Stage 5 approved_at")
    if approved_at < latest_completion:
        raise ValueError("Stage 5 approval predates a qualification receipt")
    raw_digests = approval.get("receipt_digests")
    if not isinstance(raw_digests, dict) or set(raw_digests) != set(RECEIPT_CONTRACTS):
        raise ValueError("Stage 5 approval does not bind the exact six receipt names")
    approval_digests = cast(JsonObject, raw_digests)
    for name, digest in sorted(approval_digests.items()):
        _require_string(digest, f"Stage 5 approval receipt {name}", DIGEST_RE)
    if approval_digests != receipt_digests:
        raise ValueError("Stage 5 approval is bound to different qualification receipts")
    if encoded != canonical_json(approval):
        raise ValueError("Stage 5 approval is not canonical JSON")
    return {
        "approval_digest": approval_attestation_digest,
        "approval_id": approval_id,
        "approved_at": cast(str, approval["approved_at"]),
        "reviewer_identity": reviewer,
    }


def _protected_context(
    artifact: AttestedArtifact,
    *,
    trust_policy: SignerTrustPolicy,
) -> JsonObject:
    attestation = _verify_attestation(
        artifact,
        label="protected trusted context",
        payload_type=PROTECTED_CONTEXT_PAYLOAD_TYPE,
        principal_identity=PROTECTED_CONTEXT_PRODUCER_IDENTITY,
        authorized_key_ids=trust_policy.context_signer_key_ids[
            PROTECTED_CONTEXT_PRODUCER_IDENTITY
        ],
    )
    context = decode_object(attestation.payload, "protected trusted context")
    if attestation.payload != signed_payload_json(context):
        raise ValueError("protected trusted context is not canonical signed-payload JSON")
    context_digest = sha256_bytes(attestation.payload)
    pipeline_definition_revision = _require_string(
        context.get("pipeline_definition_revision"),
        "trusted context pipeline_definition_revision",
        REVISION_RE,
    )
    validate_trusted_context(
        cast(Mapping[str, object], context),
        context_digest=context_digest,
        pipeline_definition_revision=pipeline_definition_revision,
    )
    if (
        context.get("pipeline_class") != "protected"
        or context.get("execution_tier") != "trusted"
        or context.get("source_trust") != "protected"
    ):
        raise ValueError("Stage 5 requires a protected/trusted/protected pipeline context")
    repository = _require_string(context.get("repository"), "trusted context repository")
    # The authenticated context digest identifies the exact protected dispatch. It
    # cannot be replaced by a caller-supplied Buildkite URI at assembly time.
    protected_build_identity = (
        f"buildkite://{repository}/contexts/{context_digest.removeprefix('sha256:')}"
    )
    _require_string(
        protected_build_identity,
        "derived protected build identity",
        BUILDKITE_IDENTITY_RE,
    )
    result: JsonObject = {
        "context_digest": context_digest,
        "execution_tier": cast(str, context["execution_tier"]),
        "launcher_identity": cast(str, context["launcher_identity"]),
        "pipeline_class": cast(str, context["pipeline_class"]),
        "pipeline_definition_revision": pipeline_definition_revision,
        "protected_build_identity": protected_build_identity,
        "source_revision": cast(str, context["source_revision"]),
        "source_trust": cast(str, context["source_trust"]),
    }
    if set(result) != set(PROTECTED_CONTEXT_FIELDS):
        raise AssertionError("internal protected context projection is incomplete")
    return result


def _owned_attested_artifact(
    root: Path,
    artifact: AttestedArtifact,
    label: str,
) -> AttestedArtifact:
    public_key = artifact.public_key_path.resolve()
    if not public_key.is_file():
        raise ValueError(f"{label} public key must be an existing regular file")
    return AttestedArtifact(
        payload_path=_repository_evidence_path(
            root,
            artifact.payload_path,
            label,
            must_exist=True,
        ),
        signature_envelope_path=_repository_evidence_path(
            root,
            artifact.signature_envelope_path,
            f"{label} signature envelope",
            must_exist=True,
        ),
        public_key_path=public_key,
    )


def assemble_evidence(
    receipt_artifacts: Mapping[str, AttestedArtifact],
    *,
    root: Path,
    approval_artifact: AttestedArtifact,
    trusted_context_artifact: AttestedArtifact,
    trust_policy: SignerTrustPolicy = GOVERNED_SIGNER_TRUST_POLICY,
) -> JsonObject:
    """Validate exact independent receipts and return ratifier-compatible evidence."""

    root = root.resolve()
    _validate_signer_trust_policy(trust_policy)
    if set(receipt_artifacts) != set(RECEIPT_CONTRACTS):
        raise ValueError(
            "qualification receipt set differs: "
            f"missing={sorted(set(RECEIPT_CONTRACTS) - set(receipt_artifacts))}, "
            f"unexpected={sorted(set(receipt_artifacts) - set(RECEIPT_CONTRACTS))}"
        )
    owned_receipts = {
        name: _owned_attested_artifact(root, artifact, f"{name} receipt")
        for name, artifact in receipt_artifacts.items()
    }
    approval_artifact = _owned_attested_artifact(root, approval_artifact, "Stage 5 approval")
    trusted_context_artifact = _owned_attested_artifact(
        root,
        trusted_context_artifact,
        "protected trusted context",
    )
    protected_context = _protected_context(
        trusted_context_artifact,
        trust_policy=trust_policy,
    )
    trusted_source_revision = cast(str, protected_context["source_revision"])
    protected_build_identity = cast(str, protected_context["protected_build_identity"])
    evidence_inputs = [
        path
        for artifact in [*owned_receipts.values(), approval_artifact, trusted_context_artifact]
        for path in (artifact.payload_path, artifact.signature_envelope_path)
    ]
    if len(set(evidence_inputs)) != len(evidence_inputs):
        raise ValueError("protected payloads and signature envelopes must be distinct files")

    merged_bindings: JsonObject = {}
    receipt_digests: dict[str, str] = {}
    receipt_results: dict[str, str] = {}
    receipt_producers: dict[str, str] = {}
    receipt_signer_key_ids: set[str] = set()
    producer_identities: set[str] = set()
    receipt_completions: list[datetime] = []
    result_paths: set[Path] = set()
    for name, artifact in sorted(owned_receipts.items()):
        contract = RECEIPT_CONTRACTS[name]
        attestation = _verify_attestation(
            artifact,
            label=f"{name} receipt",
            payload_type=receipt_payload_type(name),
            principal_identity=contract.producer_identity,
            authorized_key_ids=trust_policy.receipt_signer_key_ids[name],
        )
        bindings, _, result_digest, completed_at, result_path = _validate_receipt(
            name,
            attestation.payload,
            artifact.payload_path,
            root=root,
            trusted_source_revision=trusted_source_revision,
            trusted_build_identity=protected_build_identity,
        )
        producer_identity = attestation.principal_identity
        if producer_identity in producer_identities:
            raise ValueError("qualification receipts do not have independent producer identities")
        if result_path in result_paths:
            raise ValueError("qualification receipts must bind distinct result artifacts")
        result_paths.add(result_path)
        receipt_signer_key_ids.add(attestation.key_id)
        producer_identities.add(producer_identity)
        receipt_completions.append(completed_at)
        for binding_name, value in sorted(bindings.items()):
            previous = merged_bindings.get(binding_name)
            if previous is not None and previous != value:
                raise ValueError(f"qualification receipts disagree on binding {binding_name}")
            merged_bindings[binding_name] = value
        receipt_digests[name] = attestation.envelope_digest
        receipt_producers[name] = producer_identity
        receipt_results[name] = result_digest

    if len(set(receipt_digests.values())) != len(RECEIPT_CONTRACTS):
        raise ValueError("qualification receipts must have distinct signed attestations")
    if len(set(receipt_results.values())) != len(RECEIPT_CONTRACTS):
        raise ValueError("qualification receipts must bind distinct result artifacts")
    if set(merged_bindings) != set(RATIFICATION_BINDING_FIELDS):
        raise ValueError(
            "qualification receipts do not cover the exact ratification bindings: "
            f"missing={sorted(RATIFICATION_BINDING_FIELDS - set(merged_bindings))}, "
            f"unexpected={sorted(set(merged_bindings) - RATIFICATION_BINDING_FIELDS)}"
        )
    if merged_bindings.get("source_revision") != trusted_source_revision:
        raise ValueError("qualification receipts do not share the trusted source revision")
    approval_payload = approval_artifact.payload_path.read_bytes()
    untrusted_approval = decode_object(approval_payload, "Stage 5 approval")
    reviewer_identity = _require_string(
        untrusted_approval.get("reviewer_identity"),
        "Stage 5 reviewer_identity",
        PRINCIPAL_IDENTITY_RE,
    )
    if reviewer_identity not in APPROVED_REVIEWER_IDENTITIES:
        raise ValueError("Stage 5 reviewer_identity is not authorized by policy")
    approval_attestation = _verify_attestation(
        approval_artifact,
        label="Stage 5 approval",
        payload_type=APPROVAL_PAYLOAD_TYPE,
        principal_identity=reviewer_identity,
        authorized_key_ids=trust_policy.approval_signer_key_ids[reviewer_identity],
        payload=approval_payload,
    )
    if approval_attestation.key_id in receipt_signer_key_ids:
        raise ValueError("Stage 5 reviewer signing key is not independent of receipt producers")
    approval = _validate_approval(
        approval_attestation.payload,
        approval_attestation_digest=approval_attestation.envelope_digest,
        authenticated_reviewer=approval_attestation.principal_identity,
        receipt_digests=receipt_digests,
        producer_identities=producer_identities,
        latest_completion=max(receipt_completions),
        trusted_source_revision=trusted_source_revision,
        trusted_build_identity=protected_build_identity,
    )
    checks: JsonObject = {
        name: {
            "producer_identity": receipt_producers[name],
            "receipt_digest": receipt_digest,
            "result_artifact_digest": receipt_results[name],
            "status": "passed",
        }
        for name, receipt_digest in sorted(receipt_digests.items())
    }
    evidence: JsonObject = {
        **merged_bindings,
        "approval": approval,
        "checks": checks,
        "protected_context": protected_context,
        "schema_version": EVIDENCE_SCHEMA,
        "status": "passed",
    }
    return evidence


def validate_assembled_evidence_payload(
    evidence: JsonObject,
    *,
    expected_source_revision: str,
    encoded: bytes | None = None,
) -> frozenset[str]:
    """Validate the unsigned payload shape without claiming protected authorization.

    Signature, trust-root, and ratification-decision verification intentionally remain
    the responsibility of the protected Stage 5 ratifier. This helper only lets local
    readiness reporting describe a structurally valid candidate payload.
    """

    expected_fields = {
        *RATIFICATION_BINDING_FIELDS,
        "approval",
        "checks",
        "protected_context",
        "schema_version",
        "status",
    }
    if set(evidence) != expected_fields:
        raise ValueError("training evidence payload fields differ from the v2 contract")
    if evidence.get("schema_version") != EVIDENCE_SCHEMA or evidence.get("status") != "passed":
        raise ValueError("training evidence payload is not a passed v2 payload")
    if evidence.get("source_revision") != expected_source_revision:
        raise ValueError("training evidence payload is stale")
    for name in sorted(RATIFICATION_BINDING_FIELDS - {"source_revision"}):
        _validate_binding(name, evidence.get(name), "training evidence")

    raw_checks = evidence.get("checks")
    if not isinstance(raw_checks, dict) or set(raw_checks) != set(RECEIPT_CONTRACTS):
        raise ValueError("training evidence checks differ from the exact six-check contract")
    checks = cast(JsonObject, raw_checks)
    for name, raw_check in sorted(checks.items()):
        if not isinstance(raw_check, dict) or set(raw_check) != set(ASSEMBLED_CHECK_FIELDS):
            raise ValueError(f"training evidence {name} check fields differ from policy")
        check = cast(JsonObject, raw_check)
        if check.get("status") != "passed":
            raise ValueError(f"training evidence {name} check is not passed")
        if check.get("producer_identity") != RECEIPT_CONTRACTS[name].producer_identity:
            raise ValueError(f"training evidence {name} producer differs from policy")
        _require_string(check.get("receipt_digest"), f"{name} receipt digest", DIGEST_RE)
        _require_string(
            check.get("result_artifact_digest"),
            f"{name} result artifact digest",
            DIGEST_RE,
        )

    raw_approval = evidence.get("approval")
    if not isinstance(raw_approval, dict) or set(raw_approval) != set(ASSEMBLED_APPROVAL_FIELDS):
        raise ValueError("training evidence approval fields differ from policy")
    approval = cast(JsonObject, raw_approval)
    _require_string(approval.get("approval_digest"), "approval digest", DIGEST_RE)
    _require_string(approval.get("approval_id"), "approval id", APPROVAL_ID_RE)
    _require_utc(approval.get("approved_at"), "approval timestamp")
    reviewer = _require_string(
        approval.get("reviewer_identity"), "reviewer identity", PRINCIPAL_IDENTITY_RE
    )
    if reviewer not in APPROVED_REVIEWER_IDENTITIES:
        raise ValueError("training evidence reviewer is not authorized by policy")

    raw_context = evidence.get("protected_context")
    if not isinstance(raw_context, dict) or set(raw_context) != set(PROTECTED_CONTEXT_FIELDS):
        raise ValueError("training evidence protected_context fields differ from policy")
    context = cast(JsonObject, raw_context)
    if (
        context.get("source_revision") != expected_source_revision
        or context.get("pipeline_class") != "protected"
        or context.get("execution_tier") != "trusted"
        or context.get("source_trust") != "protected"
    ):
        raise ValueError("training evidence protected_context is inconsistent")
    _require_string(context.get("context_digest"), "protected context digest", DIGEST_RE)
    _require_string(
        context.get("protected_build_identity"),
        "protected build identity",
        BUILDKITE_IDENTITY_RE,
    )
    _require_string(
        context.get("pipeline_definition_revision"),
        "pipeline definition revision",
        REVISION_RE,
    )
    _require_string(context.get("launcher_identity"), "launcher identity", BUILDKITE_IDENTITY_RE)
    if encoded is not None and encoded != signed_payload_json(evidence):
        raise ValueError("training evidence payload is not canonical signed-payload JSON")
    return frozenset(
        target for contract in RECEIPT_CONTRACTS.values() for target in contract.required_targets
    )


def parse_receipt(value: str) -> tuple[str, Path]:
    name, separator, path = value.partition("=")
    if not separator or not name or not path:
        raise argparse.ArgumentTypeError("receipts must use NAME=PATH")
    if name not in RECEIPT_CONTRACTS:
        raise argparse.ArgumentTypeError(f"unsupported receipt name: {name}")
    return name, Path(path)


def _exact_named_paths(
    raw_values: Sequence[tuple[str, Path]],
    label: str,
) -> dict[str, Path]:
    values = dict(raw_values)
    if len(values) != len(raw_values):
        raise ValueError(f"duplicate {label} receipt name")
    if set(values) != set(RECEIPT_CONTRACTS):
        raise ValueError(
            f"{label} receipt set differs: "
            f"missing={sorted(set(RECEIPT_CONTRACTS) - set(values))}, "
            f"unexpected={sorted(set(values) - set(RECEIPT_CONTRACTS))}"
        )
    return values


def _repository_evidence_path(root: Path, path: Path, label: str, *, must_exist: bool) -> Path:
    candidate = path if path.is_absolute() else root / path
    resolved = candidate.resolve()
    evidence_root = (root / "build/evidence").resolve()
    if not resolved.is_relative_to(evidence_root) or resolved.suffix != ".json":
        raise ValueError(f"{label} must be a JSON file under build/evidence")
    if must_exist and (resolved.is_symlink() or not resolved.is_file()):
        raise ValueError(f"{label} must be an existing regular evidence file")
    if not must_exist and resolved.exists():
        raise ValueError(f"{label} already exists and cannot be overwritten")
    return resolved


def _git_revision(root: Path) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    revision = completed.stdout.strip()
    if REVISION_RE.fullmatch(revision) is None:
        raise ValueError("Git did not return an exact lowercase revision")
    return revision


def _require_clean_worktree(root: Path) -> None:
    completed = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    if completed.stdout:
        raise ValueError("protected evidence assembly requires a clean Git worktree")


def atomic_write_evidence(path: Path, value: JsonObject) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent, prefix=f".{path.name}.", delete=False
        ) as handle:
            temporary = Path(handle.name)
            handle.write(signed_payload_json(value))
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError as error:
            raise ValueError("evidence output already exists and cannot be overwritten") from error
        temporary.unlink()
        temporary = None
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--trusted-context", type=Path, required=True)
    parser.add_argument("--trusted-context-signature", type=Path, required=True)
    parser.add_argument("--trusted-context-public-key", type=Path, required=True)
    parser.add_argument("--receipt", action="append", type=parse_receipt, required=True)
    parser.add_argument(
        "--receipt-signature", action="append", type=parse_receipt, required=True
    )
    parser.add_argument(
        "--receipt-public-key", action="append", type=parse_receipt, required=True
    )
    parser.add_argument("--approval", type=Path, required=True)
    parser.add_argument("--approval-signature", type=Path, required=True)
    parser.add_argument("--approval-public-key", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    root = cast(Path, args.root).resolve()
    try:
        _require_clean_worktree(root)
        receipt_paths = _exact_named_paths(
            cast(list[tuple[str, Path]], args.receipt),
            "payload",
        )
        receipt_signatures = _exact_named_paths(
            cast(list[tuple[str, Path]], args.receipt_signature),
            "signature",
        )
        receipt_public_keys = _exact_named_paths(
            cast(list[tuple[str, Path]], args.receipt_public_key),
            "public-key",
        )
        output = _repository_evidence_path(
            root, cast(Path, args.output), "evidence output", must_exist=False
        )
        receipt_artifacts = {
            name: AttestedArtifact(
                payload_path=receipt_paths[name],
                signature_envelope_path=receipt_signatures[name],
                public_key_path=receipt_public_keys[name],
            )
            for name in RECEIPT_CONTRACTS
        }
        evidence = assemble_evidence(
            receipt_artifacts,
            root=root,
            approval_artifact=AttestedArtifact(
                payload_path=cast(Path, args.approval),
                signature_envelope_path=cast(Path, args.approval_signature),
                public_key_path=cast(Path, args.approval_public_key),
            ),
            trusted_context_artifact=AttestedArtifact(
                payload_path=cast(Path, args.trusted_context),
                signature_envelope_path=cast(Path, args.trusted_context_signature),
                public_key_path=cast(Path, args.trusted_context_public_key),
            ),
        )
        if evidence.get("source_revision") != _git_revision(root):
            raise ValueError("trusted source revision does not match checked-out HEAD")
        atomic_write_evidence(output, evidence)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        raise SystemExit(f"training evidence assembly failed: {error}") from error
    print(output.relative_to(root))
    print(sha256_bytes(output.read_bytes()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
