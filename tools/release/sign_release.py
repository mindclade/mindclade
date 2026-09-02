#!/usr/bin/env python3.12
"""Attach and record a verified external KMS/HSM release signature."""

from __future__ import annotations

import argparse
import base64
import binascii
import fcntl
import json
import os
import re
from collections.abc import Mapping, Sequence
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

try:
    from .build_release_manifest import (
        JsonObject,
        atomic_write_json,
        canonical_json,
        load_object,
        sha256_digest,
        unsigned_payload,
        validate_digest,
        validate_payload_digest,
    )
except ImportError:
    from build_release_manifest import (
        JsonObject,
        atomic_write_json,
        canonical_json,
        load_object,
        sha256_digest,
        unsigned_payload,
        validate_digest,
        validate_payload_digest,
    )

KEY_ID_RE = re.compile(r"^(?:gcp-kms|pkcs11-hsm)://[A-Za-z0-9][A-Za-z0-9._:/-]{15,511}$")
IDENTITY_RE = re.compile(r"^principal://[a-z0-9][a-z0-9._/-]{7,255}$")
APPROVAL_ID_RE = re.compile(r"^[a-z][a-z0-9._-]{7,127}$")
REASON_RE = re.compile(r"^[a-z][a-z0-9_-]{2,63}$")
UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
GENESIS_DIGEST = "sha256:" + "0" * 64
TRANSPARENCY_EVENTS = {"release-signed", "release-revoked", "rollback-selected"}


def _require_exact_keys(value: Mapping[str, object], expected: set[str], label: str) -> None:
    observed = set(value)
    if observed != expected:
        raise ValueError(
            f"{label} fields mismatch: missing={sorted(expected - observed)}, "
            f"unexpected={sorted(observed - expected)}"
        )


def manifest_bindings(manifest: JsonObject) -> tuple[str, str, str]:
    spec = manifest.get("spec")
    if not isinstance(spec, dict):
        raise ValueError("manifest spec must be an object")
    subject = spec.get("subject")
    source = spec.get("source")
    qualification = spec.get("qualification")
    if (
        not isinstance(subject, dict)
        or not isinstance(source, dict)
        or not isinstance(qualification, dict)
    ):
        raise ValueError("manifest subject, source, and qualification bindings are required")
    subject_digest = subject.get("digest")
    source_revision = source.get("revision")
    policy_digest = qualification.get("policy_digest")
    if not all(
        isinstance(value, str) for value in (subject_digest, source_revision, policy_digest)
    ):
        raise ValueError("manifest release bindings must be strings")
    return subject_digest, source_revision, policy_digest


def _validate_approval(
    approval: JsonObject,
    expected_gate: str,
    subject_digest: str,
    source_revision: str,
    policy_digest: str,
) -> None:
    _require_exact_keys(
        approval,
        {
            "schema_version",
            "kind",
            "gate",
            "approval_id",
            "decision",
            "reviewer_identity",
            "subject_digest",
            "source_revision",
            "qualification_policy_digest",
            "evidence_digest",
            "approved_at",
        },
        f"{expected_gate} approval",
    )
    if approval.get("schema_version") != "mindclade.release-approval/v1":
        raise ValueError(f"{expected_gate} approval schema is unsupported")
    if approval.get("kind") != "QualificationApproval" or approval.get("gate") != expected_gate:
        raise ValueError(f"{expected_gate} approval gate or kind mismatch")
    if approval.get("decision") != "approved":
        raise ValueError(f"{expected_gate} approval decision is not approved")
    approval_id = approval.get("approval_id")
    reviewer = approval.get("reviewer_identity")
    approved_at = approval.get("approved_at")
    if not isinstance(approval_id, str) or not APPROVAL_ID_RE.fullmatch(approval_id):
        raise ValueError(f"{expected_gate} approval ID is invalid")
    if not isinstance(reviewer, str) or not IDENTITY_RE.fullmatch(reviewer):
        raise ValueError(f"{expected_gate} reviewer identity is invalid")
    if not isinstance(approved_at, str) or not UTC_RE.fullmatch(approved_at):
        raise ValueError(f"{expected_gate} approval timestamp is invalid")
    if approval.get("subject_digest") != subject_digest:
        raise ValueError(f"{expected_gate} approval subject mismatch")
    if approval.get("source_revision") != source_revision:
        raise ValueError(f"{expected_gate} approval source revision mismatch")
    if approval.get("qualification_policy_digest") != policy_digest:
        raise ValueError(f"{expected_gate} approval policy mismatch")
    evidence_digest = approval.get("evidence_digest")
    if not isinstance(evidence_digest, str):
        raise ValueError(f"{expected_gate} approval evidence digest is missing")
    validate_digest(evidence_digest, f"{expected_gate} approval evidence")


def validate_approvals(manifest: JsonObject, k4_path: Path, k5_path: Path) -> dict[str, JsonObject]:
    subject_digest, source_revision, policy_digest = manifest_bindings(manifest)
    approvals = {"K4": load_object(k4_path), "K5": load_object(k5_path)}
    for gate, approval in approvals.items():
        _validate_approval(approval, gate, subject_digest, source_revision, policy_digest)

    spec = manifest.get("spec")
    qualification = spec.get("qualification") if isinstance(spec, dict) else None
    refs = qualification.get("approval_refs") if isinstance(qualification, dict) else None
    if not isinstance(refs, list) or len(refs) != 2:
        raise ValueError("manifest must bind exactly one K4 and one K5 approval")
    observed_refs: dict[str, str] = {}
    for item in refs:
        if not isinstance(item, dict):
            raise ValueError("manifest approval reference must be an object")
        _require_exact_keys(item, {"gate", "record_digest"}, "approval reference")
        gate = item.get("gate")
        digest = item.get("record_digest")
        if gate not in {"K4", "K5"} or not isinstance(digest, str) or gate in observed_refs:
            raise ValueError("manifest approval reference is invalid or duplicated")
        observed_refs[gate] = validate_digest(digest, f"{gate} approval reference")
    expected_refs = {
        gate: sha256_digest(canonical_json(approval)) for gate, approval in approvals.items()
    }
    if observed_refs != expected_refs:
        raise ValueError("manifest approval reference digest mismatch")

    reviewers = [str(approval["reviewer_identity"]) for approval in approvals.values()]
    approval_ids = [str(approval["approval_id"]) for approval in approvals.values()]
    if len(set(reviewers)) != 2 or len(set(approval_ids)) != 2:
        raise ValueError("K4 and K5 require independent reviewer identities and approval IDs")
    return approvals


def load_public_key(path: Path) -> ec.EllipticCurvePublicKey:
    if path.is_symlink() or not path.is_file():
        raise ValueError("public key must be a regular file")
    key = serialization.load_pem_public_key(path.read_bytes())
    if not isinstance(key, ec.EllipticCurvePublicKey) or not isinstance(key.curve, ec.SECP256R1):
        raise ValueError("verification key must be ECDSA P-256")
    return key


def validate_external_signature(
    manifest: JsonObject,
    envelope: JsonObject,
    public_key: ec.EllipticCurvePublicKey,
    expected_key_id: str,
    approvals: Mapping[str, JsonObject],
) -> None:
    _require_exact_keys(
        envelope,
        {
            "schema_version",
            "kind",
            "algorithm",
            "key_id",
            "key_protection",
            "signer_identity",
            "payload_digest",
            "signed_at",
            "signature",
        },
        "external signature envelope",
    )
    if envelope.get("schema_version") != "mindclade.external-signature/v1":
        raise ValueError("external signature schema is unsupported")
    if envelope.get("kind") != "ExternalSignature":
        raise ValueError("external signature kind is unsupported")
    if envelope.get("algorithm") != "ecdsa-p256-sha256":
        raise ValueError("external signature algorithm is unsupported")
    key_id = envelope.get("key_id")
    if key_id != expected_key_id or not isinstance(key_id, str) or not KEY_ID_RE.fullmatch(key_id):
        raise ValueError("external signature key identity is not an approved KMS/HSM URI")
    if envelope.get("key_protection") != "HSM":
        raise ValueError("external signing key must declare HSM protection")
    signer = envelope.get("signer_identity")
    if not isinstance(signer, str) or not IDENTITY_RE.fullmatch(signer):
        raise ValueError("external signer identity is invalid")
    reviewers = {str(approval["reviewer_identity"]) for approval in approvals.values()}
    if signer in reviewers:
        raise ValueError("release signer must be independent of K4 and K5 reviewers")
    signed_at = envelope.get("signed_at")
    if not isinstance(signed_at, str) or not UTC_RE.fullmatch(signed_at):
        raise ValueError("external signature timestamp is invalid")
    payload = canonical_json(unsigned_payload(manifest))
    expected_digest = sha256_digest(payload)
    if envelope.get("payload_digest") != expected_digest:
        raise ValueError("external signature payload digest mismatch")
    encoded = envelope.get("signature")
    if not isinstance(encoded, str):
        raise ValueError("external signature bytes are missing")
    try:
        decoded = base64.b64decode(encoded, validate=True)
    except binascii.Error as error:
        raise ValueError("external signature is not canonical base64") from error
    if base64.b64encode(decoded).decode("ascii") != encoded:
        raise ValueError("external signature is not canonical base64")
    try:
        public_key.verify(decoded, payload, ec.ECDSA(hashes.SHA256()))
    except InvalidSignature as error:
        raise ValueError("external release signature is invalid") from error


def signature_digest(envelope: JsonObject) -> str:
    return sha256_digest(canonical_json(envelope))


def _parse_transparency_bytes(data: bytes) -> list[JsonObject]:
    if not data:
        return []
    if not data.endswith(b"\n"):
        raise ValueError("transparency log has an incomplete final record")
    entries: list[JsonObject] = []
    previous_digest = GENESIS_DIGEST
    for sequence, raw_line in enumerate(data.splitlines(), start=1):
        if not raw_line:
            raise ValueError("transparency log contains an empty record")
        try:
            value = json.loads(raw_line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("transparency log contains invalid JSON") from error
        if not isinstance(value, dict) or canonical_json(value) != raw_line:
            raise ValueError("transparency records must be canonical JSON objects")
        entry: JsonObject = value
        _require_exact_keys(
            entry,
            {
                "schema_version",
                "kind",
                "sequence",
                "previous_entry_digest",
                "event",
                "release_payload_digest",
                "subject_digest",
                "related_release_payload_digest",
                "actor_identity",
                "reason_code",
                "signature_digest",
                "recorded_at",
                "entry_digest",
            },
            "transparency record",
        )
        if entry.get("schema_version") != "mindclade.release-transparency/v1":
            raise ValueError("transparency schema is unsupported")
        if entry.get("kind") != "ReleaseTransparencyRecord":
            raise ValueError("transparency record kind is unsupported")
        if type(entry.get("sequence")) is not int or entry["sequence"] != sequence:
            raise ValueError("transparency sequence is not contiguous")
        if entry.get("previous_entry_digest") != previous_digest:
            raise ValueError("transparency hash chain is broken")
        if entry.get("event") not in TRANSPARENCY_EVENTS:
            raise ValueError("transparency event is unsupported")
        for field in ("release_payload_digest", "subject_digest"):
            value_digest = entry.get(field)
            if not isinstance(value_digest, str):
                raise ValueError(f"transparency {field} is missing")
            validate_digest(value_digest, f"transparency {field}")
        for field in ("related_release_payload_digest", "signature_digest"):
            value_digest = entry.get(field)
            if value_digest is not None:
                if not isinstance(value_digest, str):
                    raise ValueError(f"transparency {field} must be a digest or null")
                validate_digest(value_digest, f"transparency {field}")
        actor = entry.get("actor_identity")
        if not isinstance(actor, str) or not IDENTITY_RE.fullmatch(actor):
            raise ValueError("transparency actor identity is invalid")
        reason = entry.get("reason_code")
        if reason is not None and (not isinstance(reason, str) or not REASON_RE.fullmatch(reason)):
            raise ValueError("transparency reason code is invalid")
        recorded_at = entry.get("recorded_at")
        if not isinstance(recorded_at, str) or not UTC_RE.fullmatch(recorded_at):
            raise ValueError("transparency timestamp is invalid")
        claimed_digest = entry.get("entry_digest")
        unsigned_entry = dict(entry)
        unsigned_entry.pop("entry_digest")
        expected_digest = sha256_digest(canonical_json(unsigned_entry))
        if claimed_digest != expected_digest:
            raise ValueError("transparency entry digest mismatch")
        previous_digest = expected_digest
        entries.append(entry)
    return entries


def load_transparency_log(path: Path) -> list[JsonObject]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"transparency log must be a regular file: {path}")
    return _parse_transparency_bytes(path.read_bytes())


def append_transparency_event(
    path: Path,
    *,
    event: str,
    release_payload_digest: str,
    subject_digest: str,
    actor_identity: str,
    recorded_at: str,
    related_release_payload_digest: str | None = None,
    reason_code: str | None = None,
    signature_record_digest: str | None = None,
) -> JsonObject:
    if event not in TRANSPARENCY_EVENTS:
        raise ValueError("transparency event is unsupported")
    validate_digest(release_payload_digest, "release payload")
    validate_digest(subject_digest, "release subject")
    if related_release_payload_digest is not None:
        validate_digest(related_release_payload_digest, "related release payload")
    if signature_record_digest is not None:
        validate_digest(signature_record_digest, "signature record")
    if not IDENTITY_RE.fullmatch(actor_identity):
        raise ValueError("transparency actor identity is invalid")
    if not UTC_RE.fullmatch(recorded_at):
        raise ValueError("transparency timestamp is invalid")
    if reason_code is not None and not REASON_RE.fullmatch(reason_code):
        raise ValueError("transparency reason code is invalid")
    if not path.parent.is_dir() or path.is_symlink():
        raise ValueError("transparency log parent must exist and path must not be a symlink")

    flags = os.O_RDWR | os.O_CREAT | os.O_APPEND
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, "r+b") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        stream.seek(0)
        entries = _parse_transparency_bytes(stream.read())
        previous_digest = entries[-1]["entry_digest"] if entries else GENESIS_DIGEST
        entry: JsonObject = {
            "schema_version": "mindclade.release-transparency/v1",
            "kind": "ReleaseTransparencyRecord",
            "sequence": len(entries) + 1,
            "previous_entry_digest": previous_digest,
            "event": event,
            "release_payload_digest": release_payload_digest,
            "subject_digest": subject_digest,
            "related_release_payload_digest": related_release_payload_digest,
            "actor_identity": actor_identity,
            "reason_code": reason_code,
            "signature_digest": signature_record_digest,
            "recorded_at": recorded_at,
        }
        entry["entry_digest"] = sha256_digest(canonical_json(entry))
        stream.seek(0, os.SEEK_END)
        stream.write(canonical_json(entry) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())
        return entry


def verify_transparency(
    entries: Sequence[JsonObject],
    release_payload_digest: str,
    signature_record_digest: str,
) -> None:
    signing_entries = [
        entry
        for entry in entries
        if entry.get("event") == "release-signed"
        and entry.get("release_payload_digest") == release_payload_digest
        and entry.get("signature_digest") == signature_record_digest
    ]
    if len(signing_entries) != 1:
        raise ValueError("release signature has no unique transparency record")
    if any(
        entry.get("event") == "release-revoked"
        and entry.get("release_payload_digest") == release_payload_digest
        for entry in entries
    ):
        raise ValueError("release payload is revoked")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--input", type=Path, required=True)
    result.add_argument("--output", type=Path, required=True)
    result.add_argument("--external-signature", type=Path, required=True)
    result.add_argument("--public-key", type=Path, required=True)
    result.add_argument("--key-id", required=True)
    result.add_argument("--k4-approval", type=Path, required=True)
    result.add_argument("--k5-approval", type=Path, required=True)
    result.add_argument("--transparency-log", type=Path, required=True)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        manifest = load_object(args.input)
        release_digest = validate_payload_digest(manifest)
        approvals = validate_approvals(manifest, args.k4_approval, args.k5_approval)
        envelope = load_object(args.external_signature)
        validate_external_signature(
            manifest, envelope, load_public_key(args.public_key), args.key_id, approvals
        )
        integrity = manifest.get("integrity")
        if not isinstance(integrity, dict):
            raise ValueError("manifest integrity must be an object")
        if integrity.get("signatures"):
            raise ValueError("manifest is already signed")
        integrity["signatures"] = [envelope]
        atomic_write_json(args.output, manifest)
        subject_digest, _, _ = manifest_bindings(manifest)
        append_transparency_event(
            args.transparency_log,
            event="release-signed",
            release_payload_digest=release_digest,
            subject_digest=subject_digest,
            actor_identity=str(envelope["signer_identity"]),
            recorded_at=str(envelope["signed_at"]),
            signature_record_digest=signature_digest(envelope),
        )
    except (OSError, TypeError, ValueError) as error:
        raise SystemExit(f"release signature attachment failed: {error}") from error
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
