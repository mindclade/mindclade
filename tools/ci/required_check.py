#!/usr/bin/env python3.12
"""Validate org-compatible CI evidence plus its detached qualified signature."""

from __future__ import annotations

import argparse
import base64
import binascii
import copy
import json
import re
import subprocess
import sys
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Protocol, cast

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from evidence_bundle import (
    BUILDKITE_UUID_PATTERN,
    CANONICAL_OPERATIONAL_REMOTES,
    CORRELATION_PATTERN,
    DIGEST_PATTERN,
    OPERATIONAL_COMPONENT_NAMES,
    OPERATIONAL_PROJECT_SLUGS,
    OPERATIONAL_RULESETS,
    OPERATIONAL_TARGET_ROOTS,
    ORG_SCHEMA_VERSION,
    REPOSITORY,
    SHA_PATTERN,
    WORKFLOW_PATTERN,
    build_evidence,
    calculate_plan_id,
    canonical_json,
    read_object,
    sha256_bytes,
    validate_trusted_context,
)
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError

SIGNATURE_PAYLOAD_TYPE = "application/vnd.mindclade.ci-evidence.v1+json"
ADR_RATIFICATION_MEDIA_TYPE = "application/vnd.mindclade.adr-connected-ratification.v1+json"
ADR_DECISION_CANONICALIZATION = "adr-decision-v1"
ADR_RATIFICATION_SCHEMA = "connected-ratification.v1.schema.json"
ADR_PENDING_RATIFICATION = "Pending independent review on protected infrastructure"
FOUNDER_BOOTSTRAP_SCHEMA = "docs/governance/founder-bootstrap-exception.v1.schema.json"
FOUNDER_BOOTSTRAP_RECORD = "docs/governance/exceptions/FBE-0001.yaml"
FOUNDER_BOOTSTRAP_EXPIRY = date(2026, 9, 30)
FOUNDER_BOOTSTRAP_ALLOWED_OPERATIONS = (
    "create",
    "adopt",
    "protect",
    "set-non-secret-variable",
    "activate-foundation-identity",
)
FOUNDER_BOOTSTRAP_DENIED_OPERATIONS = (
    "delete",
    "replace",
    "bypass",
    "promote-production",
    "export-secret",
    "force-push",
    "self-extend",
)
MAX_CLOCK_SKEW = timedelta(minutes=5)
ORG_FIELDS = {
    "schema_version",
    "correlation_id",
    "source_revision",
    "base_revision",
    "context_digest",
    "caller_repository",
    "workflow_ref",
    "workflow_revision",
    "pipeline_definition_revision",
    "producer",
    "plan_id",
    "build_id",
    "conclusion",
    "reason_code",
    "checks",
    "started_at",
    "completed_at",
}
REASON_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{2,127}$")
ADR_PATHS = (
    "0001-repository-identity-and-ownership.md",
    "0002-dependency-and-build-law.md",
    "0003-artifact-identity-and-cas.md",
    "0004-contract-and-codegen-authority.md",
    "0005-biological-identity-and-schema-evolution.md",
    "0006-durable-work-and-fencing.md",
    "0007-training-state-progress-and-checkpoint.md",
    "0008-founder-bootstrap-public-estate-transition.md",
)
ADR_METADATA_FIELDS = {
    "status",
    "connected ratification",
    "specification date",
    "effective date",
    "compatibility window",
    "supersedes",
    "superseded by",
    "owners",
    "reviewers",
}
ADR_IMPACT_FIELDS = {
    "affected invariants",
    "affected paths",
    "affected contracts",
    "security and safety impact",
    "migration",
    "rollback",
    "required evidence",
}
ADR_INDEX_REQUIRED_FIELDS = {
    "id",
    "title",
    "status",
    "connectedRatification",
    "path",
    "owners",
    "specificationAccepted",
}
ADR_RATIFICATION_FIELDS = {
    "ratificationSubjectRevision",
    "ratificationDecisionDigest",
    "ratificationReceiptDigest",
    "ratifiedAt",
}
ADR_INDEX_FIELDS = ADR_INDEX_REQUIRED_FIELDS | ADR_RATIFICATION_FIELDS
ADR_MUTABLE_METADATA_PREFIXES = (
    "- Connected ratification: ",
    "- Effective date: ",
)


class EvidenceError(ValueError):
    """Evidence is stale, ambiguous, unsigned, or not bound to its caller."""


class _Validator(Protocol):
    def iter_errors(self, instance: object) -> Iterable[ValidationError]: ...


@dataclass(frozen=True)
class ValidationRequest:
    envelope: Mapping[str, object]
    public_key_pem: bytes
    expected_key_id: str
    context: Mapping[str, object]
    plan: Mapping[str, object]
    plan_digest: str
    expected_source_revision: str
    expected_pipeline_definition_revision: str
    expected_source_trust: str
    expected_execution_tier: str
    expected_correlation_id: str
    expected_context_digest: str
    expected_build_id: str
    max_age: timedelta
    now: datetime
    org_schema: Path | None


def _normalized_owner(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def _parse_adr_index(path: Path) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        identifier = re.fullmatch(r"    - id: (ADR-[0-9]{4})", line)
        if identifier:
            current = {"id": identifier.group(1)}
            entries.append(current)
            continue
        field = re.fullmatch(r"      ([A-Za-z][A-Za-z0-9]*): (.+)", line)
        if current is not None and field:
            name = field.group(1)
            if name in current:
                raise ValueError(f"ADR index entry {current['id']} repeats field {name}")
            current[name] = field.group(2).strip('"')
    return entries


def canonical_adr_decision_bytes(text: str) -> bytes:
    """Apply the ``adr-decision-v1`` LF canonicalization profile."""

    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    retained: list[str] = []
    excluded: dict[str, int] = dict.fromkeys(ADR_MUTABLE_METADATA_PREFIXES, 0)
    metadata = True
    for line in normalized.split("\n"):
        if line.startswith("## "):
            metadata = False
        matched_prefix = next(
            (
                prefix
                for prefix in ADR_MUTABLE_METADATA_PREFIXES
                if metadata and line.startswith(prefix)
            ),
            None,
        )
        if matched_prefix is not None:
            excluded[matched_prefix] += 1
            continue
        retained.append(line)
    if any(count != 1 for count in excluded.values()):
        raise ValueError(
            "ADR decision canonicalization requires exactly one Connected ratification "
            "and one Effective date metadata line"
        )
    canonical = "\n".join(retained).rstrip("\n") + "\n"
    return canonical.encode("utf-8")


def adr_decision_digest(text: str) -> str:
    return sha256_bytes(canonical_adr_decision_bytes(text))


def _load_adr_ratification_schema(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read ADR ratification schema: {error}") from error
    if not isinstance(value, dict):
        raise ValueError("ADR ratification schema root must be an object")
    schema = cast(dict[str, object], value)
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as error:
        raise ValueError(f"ADR ratification schema is invalid: {error.message}") from error
    if schema.get("x-mindclade-media-type") != ADR_RATIFICATION_MEDIA_TYPE:
        raise ValueError("ADR ratification schema has the wrong external media type")
    if schema.get("x-mindclade-decision-canonicalization") != ADR_DECISION_CANONICALIZATION:
        raise ValueError("ADR ratification schema has the wrong decision canonicalization profile")
    if schema.get("additionalProperties") is not False:
        raise ValueError("ADR ratification schema must reject additional properties")
    return schema


def _ratification_projection(entry: Mapping[str, str]) -> dict[str, str]:
    return {
        field: value
        for field, value in entry.items()
        if field == "connectedRatification" or field in ADR_RATIFICATION_FIELDS
    }


def validate_founder_bootstrap_exception(root: Path) -> list[str]:
    errors: list[str] = []
    schema_path = root / FOUNDER_BOOTSTRAP_SCHEMA
    record_path = root / FOUNDER_BOOTSTRAP_RECORD
    try:
        schema_value = json.loads(schema_path.read_text(encoding="utf-8"))
        record_value = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return [f"cannot read founder bootstrap contract: {error}"]
    if not isinstance(schema_value, dict) or not isinstance(record_value, dict):
        return ["founder bootstrap schema and record roots must be objects"]
    schema = cast(dict[str, object], schema_value)
    record = cast(dict[str, object], record_value)
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as error:
        return [f"founder bootstrap schema is invalid: {error.message}"]
    if schema.get("additionalProperties") is not False:
        errors.append("founder bootstrap schema must reject additional properties")
    validator = cast(_Validator, Draft202012Validator(schema))
    schema_errors = sorted(
        validator.iter_errors(record),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    for error in schema_errors:
        location = "/".join(str(part) for part in error.absolute_path) or "<root>"
        errors.append(f"FBE-0001 schema validation at {location}: {error.message}")
    if schema_errors:
        return errors

    metadata = cast(dict[str, object], record["metadata"])
    spec = cast(dict[str, object], record["spec"])
    authority = cast(dict[str, object], spec["authority"])
    profile = cast(dict[str, object], spec["profile"])
    scope = cast(dict[str, object], spec["scope"])
    lifecycle = cast(dict[str, object], spec["lifecycle"])
    permissions = cast(dict[str, object], spec["permissions"])
    guards = cast(dict[str, object], spec["guards"])
    initial_publication = cast(dict[str, object], spec["initialPublication"])
    consumption = cast(dict[str, object], spec["consumption"])
    status = cast(dict[str, object], record["status"])

    immutable_contract = {
        "metadata": metadata,
        "authority": authority,
        "profile": profile,
        "scope": scope,
        "lifecycle": lifecycle,
        "allow": permissions["allow"],
        "deny": permissions["deny"],
        "guards": guards,
        "initialPublication": {
            "target": initial_publication["target"],
            "actor": initial_publication["actor"],
            "maxUses": initial_publication["maxUses"],
            "guards": initial_publication["guards"],
        },
        "consumptionAuthority": consumption["authority"],
    }
    expected_contract = {
        "metadata": {
            "id": "FBE-0001",
            "name": "founder-bootstrap-public-estate-transition",
            "createdOn": "2026-08-30",
            "expiresOn": "2026-09-30",
        },
        "authority": {
            "adr": "ADR-0008",
            "grantedBy": "founder",
            "owners": ["architecture", "security"],
            "independentReviewRequired": True,
            "connectedQualificationRequired": True,
            "selfExtensionAllowed": False,
        },
        "profile": {
            "repository": "mindclade/mindclade",
            "visibility": "public",
            "githubPlan": "free",
            "controlPlane": "repository-level",
            "defaultBranch": "main",
            "privilegedWorkflow": "github-config/.github/workflows/protected-apply.yml",
        },
        "scope": {"sourceWave": "1", "sourceOnly": True, "productionAuthority": False},
        "lifecycle": {
            "from": "BLOCKED",
            "through": "FOUNDER_BOOTSTRAPPED",
            "to": "CONNECTED_QUALIFIED",
        },
        "allow": list(FOUNDER_BOOTSTRAP_ALLOWED_OPERATIONS),
        "deny": list(FOUNDER_BOOTSTRAP_DENIED_OPERATIONS),
        "guards": {
            "singleUse": True,
            "failClosed": True,
            "maxUses": 1,
            "exactRevisionRequired": True,
            "noBypass": True,
            "twoApprovalsAfterProtection": True,
            "nonSecretVariablesOnly": True,
        },
        "initialPublication": {
            "target": {
                "repository": "mindclade/github-config",
                "branch": "main",
                "workflowPath": ".github/workflows/protected-apply.yml",
                "workflowContentDigest": "sha256:d9109bd4227557cb98a032cfaaa4748744ec8c280733f4f13400da340f1c8de9",
            },
            "actor": {"githubLogin": "mindclade-founder"},
            "maxUses": 1,
            "guards": {
                "pullRequestMergeRequired": True,
                "directMainPushAllowed": False,
                "branchProtectionWaiverAllowed": False,
                "independentReviewClaimAllowed": False,
                "productionAuthority": False,
            },
        },
        "consumptionAuthority": "protected-connected-receipt",
    }
    if immutable_contract != expected_contract:
        errors.append("FBE-0001 immutable authority, scope, permissions, or guards drifted")

    phase = status["phase"]
    if phase == "AUTHORIZED_SOURCE_ONLY" and FOUNDER_BOOTSTRAP_EXPIRY < date.today():
        errors.append("FBE-0001 source authorization is expired")
    initial_publication_state = initial_publication["state"]
    initial_publication_receipt = cast(dict[str, object], initial_publication["receipt"])
    if initial_publication_state == "PUBLISHED":
        receipt_digest = initial_publication_receipt["digest"]
        published_at = initial_publication_receipt["publishedAt"]
        pull_request = initial_publication_receipt["pullRequest"]
        pull_request_number = initial_publication_receipt["pullRequestNumber"]
        if not isinstance(receipt_digest, str) or not DIGEST_PATTERN.fullmatch(receipt_digest):
            errors.append("FBE-0001 initial publication requires an immutable receipt digest")
        if not isinstance(published_at, str) or not published_at.endswith("Z"):
            errors.append("FBE-0001 initial publication requires a canonical UTC timestamp")
        if (
            not isinstance(pull_request, str)
            or not isinstance(pull_request_number, int)
            or pull_request != f"https://github.com/mindclade/github-config/pull/{pull_request_number}"
        ):
            errors.append("FBE-0001 initial publication receipt must bind its canonical pull-request URL and number")
    if phase == "CONSUMED" and initial_publication_state != "PUBLISHED":
        errors.append("FBE-0001 cannot be consumed before its initial workflow publication")
    if phase == "CONSUMED":
        receipt_digest = consumption["receiptDigest"]
        consumed_at = consumption["consumedAt"]
        if not isinstance(receipt_digest, str) or not DIGEST_PATTERN.fullmatch(receipt_digest):
            errors.append("FBE-0001 consumed state requires an immutable receipt digest")
        if not isinstance(consumed_at, str) or not consumed_at.endswith("Z"):
            errors.append("FBE-0001 consumed state requires a canonical UTC timestamp")
    return errors


def validate_adrs(root: Path) -> list[str]:
    errors: list[str] = []
    adr_root = root / "docs/adr"
    try:
        ratification_schema = _load_adr_ratification_schema(adr_root / ADR_RATIFICATION_SCHEMA)
    except ValueError as error:
        return [str(error)]
    ratification_validator = cast(_Validator, Draft202012Validator(ratification_schema))
    errors.extend(validate_founder_bootstrap_exception(root))
    actual_paths = sorted(path.name for path in adr_root.glob("*.md"))
    if actual_paths != list(ADR_PATHS):
        errors.append("ADR file set does not match the exact eight Section-14 decisions")
    index_entries = _parse_adr_index(adr_root / "index.yaml")
    index_by_id = {entry.get("id", ""): entry for entry in index_entries}
    if len(index_entries) != len(index_by_id) or len(index_entries) != len(ADR_PATHS):
        errors.append("ADR index must contain exactly eight unique decision IDs")

    discovered_ids: set[str] = set()
    supersession_edges: dict[str, str] = {}
    for filename in ADR_PATHS:
        path = adr_root / filename
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
        heading = re.fullmatch(r"# (ADR-[0-9]{4}): (.+)", lines[0] if lines else "")
        if heading is None:
            errors.append(f"{filename}: heading must contain canonical ADR ID and title")
            continue
        identifier, title = heading.groups()
        if identifier in discovered_ids:
            errors.append(f"{filename}: duplicate ADR ID {identifier}")
        discovered_ids.add(identifier)
        metadata: dict[str, str] = {}
        for line in lines[1:]:
            if line.startswith("## "):
                break
            match = re.fullmatch(r"- ([A-Za-z ]+): (.+)", line)
            if match:
                metadata[match.group(1).lower()] = match.group(2).strip()
        missing_metadata = sorted(ADR_METADATA_FIELDS - set(metadata))
        if missing_metadata:
            errors.append(f"{filename}: missing metadata: {', '.join(missing_metadata)}")
        if metadata.get("status") != "Accepted in blueprint specification":
            errors.append(f"{filename}: status must distinguish specification acceptance")
        for field in ("supersedes", "superseded by"):
            target = metadata.get(field, "")
            if target and target != "None":
                if not re.fullmatch(r"ADR-[0-9]{4}", target):
                    errors.append(f"{filename}: {field} must be None or a canonical ADR ID")
                elif target == identifier:
                    errors.append(f"{filename}: {field} cannot refer to itself")
                elif field == "supersedes":
                    supersession_edges[identifier] = target
        impact_section = text.partition("## Decision record metadata")[2].partition("## Context")[0]
        impact_fields = {
            match.group(1).lower()
            for match in re.finditer(r"^- ([A-Za-z ]+): .+", impact_section, re.MULTILINE)
        }
        missing_impact = sorted(ADR_IMPACT_FIELDS - impact_fields)
        if missing_impact:
            errors.append(f"{filename}: missing impact fields: {', '.join(missing_impact)}")
        for raw_expiry in re.findall(
            r"^- Exception expiry: ([0-9]{4}-[0-9]{2}-[0-9]{2})$",
            text,
            re.MULTILINE,
        ):
            if date.fromisoformat(raw_expiry) < date.today():
                errors.append(f"{filename}: exception expired on {raw_expiry}")

        index = index_by_id.get(identifier)
        if index is None:
            errors.append(f"{filename}: missing from ADR index")
            continue
        expected_path = f"docs/adr/{filename}"
        if index.get("title") != title or index.get("path") != expected_path:
            errors.append(f"{filename}: ADR index title/path drift")
        if index.get("status") != "accepted-in-specification":
            errors.append(f"{filename}: ADR index status drift")
        missing_index_fields = sorted(ADR_INDEX_REQUIRED_FIELDS - set(index))
        unknown_index_fields = sorted(set(index) - ADR_INDEX_FIELDS)
        if missing_index_fields:
            errors.append(
                f"{filename}: ADR index missing fields: {', '.join(missing_index_fields)}"
            )
        if unknown_index_fields:
            errors.append(
                f"{filename}: ADR index contains unknown fields: {', '.join(unknown_index_fields)}"
            )
        ratification_errors = sorted(
            ratification_validator.iter_errors(_ratification_projection(index)),
            key=lambda error: tuple(str(part) for part in error.absolute_path),
        )
        for error in ratification_errors:
            errors.append(f"{filename}: ADR index ratification contract: {error.message}")
        ratification_state = index.get("connectedRatification")
        if ratification_state == "pending":
            if metadata.get("connected ratification") != ADR_PENDING_RATIFICATION:
                errors.append(f"{filename}: pending connected ratification metadata drift")
            if not metadata.get("effective date", "").startswith("Pending connected ratification"):
                errors.append(f"{filename}: pending ADR must not declare an effective date")
        elif ratification_state == "ratified":
            subject_revision = index.get("ratificationSubjectRevision", "")
            decision_digest = index.get("ratificationDecisionDigest", "")
            receipt_digest = index.get("ratificationReceiptDigest", "")
            ratified_at = index.get("ratifiedAt", "")
            if not SHA_PATTERN.fullmatch(subject_revision):
                errors.append(f"{filename}: ratification subject revision is not immutable")
            if not DIGEST_PATTERN.fullmatch(decision_digest):
                errors.append(f"{filename}: ratification decision digest is not canonical")
            if not DIGEST_PATTERN.fullmatch(receipt_digest):
                errors.append(f"{filename}: ratification receipt digest is not canonical")
            ratified_time: datetime | None = None
            try:
                ratified_time = _timestamp(ratified_at, "ratifiedAt")
            except EvidenceError as error:
                errors.append(f"{filename}: {error}")
            if not ratified_at.endswith("Z"):
                errors.append(f"{filename}: ratifiedAt must be canonical UTC")
            try:
                expected_decision_digest = adr_decision_digest(text)
            except ValueError as error:
                errors.append(f"{filename}: {error}")
            else:
                if decision_digest != expected_decision_digest:
                    errors.append(f"{filename}: ratification decision digest does not match ADR")
            if metadata.get("connected ratification") == ADR_PENDING_RATIFICATION:
                errors.append(f"{filename}: ratified ADR still claims pending review")
            effective_date = metadata.get("effective date", "")
            if ratified_time is not None and effective_date != ratified_time.date().isoformat():
                errors.append(f"{filename}: effective date does not match ratifiedAt")
        indexed_owners = index.get("owners", "")
        indexed_owner_set = {
            owner.strip()
            for owner in indexed_owners.removeprefix("[").removesuffix("]").split(",")
            if owner.strip()
        }
        metadata_owner_set = {
            _normalized_owner(owner) for owner in metadata.get("owners", "").split(",")
        }
        if indexed_owner_set != metadata_owner_set:
            errors.append(f"{filename}: ADR index owner drift")

    for source, target in supersession_edges.items():
        if target not in discovered_ids:
            errors.append(f"{source}: supersedes missing decision {target}")
    return errors


def _validate_request(evidence: Mapping[str, object], request: ValidationRequest) -> None:
    validate_evidence(
        evidence,
        envelope=request.envelope,
        public_key_pem=request.public_key_pem,
        expected_key_id=request.expected_key_id,
        context=request.context,
        plan=request.plan,
        plan_digest=request.plan_digest,
        expected_source_revision=request.expected_source_revision,
        expected_pipeline_definition_revision=request.expected_pipeline_definition_revision,
        expected_source_trust=request.expected_source_trust,
        expected_execution_tier=request.expected_execution_tier,
        expected_correlation_id=request.expected_correlation_id,
        expected_context_digest=request.expected_context_digest,
        expected_build_id=request.expected_build_id,
        max_age=request.max_age,
        now=request.now,
        org_schema=request.org_schema,
    )


def _object(value: object, description: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise EvidenceError(f"{description} must be an object")
    return cast(dict[str, object], value)


def _string(value: Mapping[str, object], field: str) -> str:
    candidate = value.get(field)
    if not isinstance(candidate, str) or not candidate:
        raise EvidenceError(f"{field} must be a non-empty string")
    return candidate


def _array(value: Mapping[str, object], field: str) -> list[object]:
    candidate = value.get(field)
    if not isinstance(candidate, list):
        raise EvidenceError(f"{field} must be an array")
    return cast(list[object], candidate)


def _decode_base64(value: str, description: str) -> bytes:
    try:
        return base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as error:
        raise EvidenceError(f"{description} is not canonical base64") from error


def dsse_pae(payload_type: str, payload: bytes) -> bytes:
    type_bytes = payload_type.encode()
    return b" ".join(
        (
            b"DSSEv1",
            str(len(type_bytes)).encode(),
            type_bytes,
            str(len(payload)).encode(),
            payload,
        )
    )


def signer_key_id(public_key: ed25519.Ed25519PublicKey) -> str:
    encoded = public_key.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return sha256_bytes(encoded)


def _timestamp(raw: str, field: str) -> datetime:
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as error:
        raise EvidenceError(f"{field} is not an RFC 3339 timestamp") from error
    if value.tzinfo is None:
        raise EvidenceError(f"{field} does not include a UTC offset")
    return value.astimezone(UTC)


def validate_org_wire_contract(evidence: Mapping[str, object]) -> dict[str, str]:
    """Mirror the pinned 1.0.0 organization schema and Buildkite checks."""
    if set(evidence) != ORG_FIELDS:
        raise EvidenceError("ci-evidence.json contains missing or unknown organization fields")
    if evidence.get("schema_version") != ORG_SCHEMA_VERSION:
        raise EvidenceError("organization evidence schema_version must be 1.0.0")
    if evidence.get("caller_repository") != REPOSITORY:
        raise EvidenceError(f"caller_repository must be {REPOSITORY}")
    if evidence.get("producer") != "buildkite":
        raise EvidenceError("organization evidence producer must be buildkite")
    if evidence.get("conclusion") != "PASS":
        raise EvidenceError("organization evidence conclusion must be PASS")
    if not SHA_PATTERN.fullmatch(_string(evidence, "source_revision")):
        raise EvidenceError("source_revision must be a full lowercase Git SHA")
    if not SHA_PATTERN.fullmatch(_string(evidence, "workflow_revision")):
        raise EvidenceError("workflow_revision must be a full lowercase Git SHA")
    if not SHA_PATTERN.fullmatch(_string(evidence, "pipeline_definition_revision")):
        raise EvidenceError("pipeline_definition_revision must be a full lowercase Git SHA")
    base_revision = evidence.get("base_revision")
    if base_revision is not None and (
        not isinstance(base_revision, str) or not SHA_PATTERN.fullmatch(base_revision)
    ):
        raise EvidenceError("base_revision must be null or a full lowercase Git SHA")
    if not DIGEST_PATTERN.fullmatch(_string(evidence, "context_digest")):
        raise EvidenceError("context_digest must be a canonical SHA-256 digest")
    if not CORRELATION_PATTERN.fullmatch(_string(evidence, "correlation_id")):
        raise EvidenceError("correlation_id does not match the organization contract")
    if not WORKFLOW_PATTERN.fullmatch(_string(evidence, "workflow_ref")):
        raise EvidenceError("workflow_ref does not match the organization contract")
    if not BUILDKITE_UUID_PATTERN.fullmatch(_string(evidence, "build_id")):
        raise EvidenceError("build_id must be a canonical Buildkite UUID")
    if not REASON_PATTERN.fullmatch(_string(evidence, "reason_code")):
        raise EvidenceError("reason_code does not match the organization contract")
    plan_id = _string(evidence, "plan_id")
    if not DIGEST_PATTERN.fullmatch(plan_id):
        raise EvidenceError("plan_id must bind one canonical SHA-256 plan digest")

    checks: dict[str, str] = {}
    entries = _array(evidence, "checks")
    if not entries:
        raise EvidenceError("organization evidence must contain at least one check")
    for index, raw_check in enumerate(entries):
        check = _object(raw_check, f"check {index}")
        if set(check) != {"name", "conclusion", "report_digest"}:
            raise EvidenceError("repository-produced checks may not declare ambiguous report paths")
        name = _string(check, "name")
        if len(name) > 255 or name in checks:
            raise EvidenceError(f"check name is invalid or duplicated: {name}")
        if check.get("conclusion") != "PASS":
            raise EvidenceError(f"check {name} did not pass")
        digest = _string(check, "report_digest")
        if not DIGEST_PATTERN.fullmatch(digest):
            raise EvidenceError(f"check {name} has a non-canonical report digest")
        checks[name] = digest
    _timestamp(_string(evidence, "started_at"), "started_at")
    _timestamp(_string(evidence, "completed_at"), "completed_at")
    return checks


def validate_against_pinned_schema(evidence: Mapping[str, object], schema_path: Path) -> None:
    try:
        schema = read_object(schema_path, "pinned organization evidence schema")
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(evidence)  # pyright: ignore[reportUnknownMemberType]
    except (OSError, json.JSONDecodeError, SchemaError, ValidationError, ValueError) as error:
        raise EvidenceError(f"pinned organization schema rejected evidence: {error}") from error


def validate_signature(
    evidence: Mapping[str, object],
    envelope: Mapping[str, object],
    *,
    public_key_pem: bytes,
    expected_key_id: str,
) -> None:
    if set(envelope) != {"payloadType", "payload", "signatures"}:
        raise EvidenceError("signature envelope contains missing or unknown fields")
    if _string(envelope, "payloadType") != SIGNATURE_PAYLOAD_TYPE:
        raise EvidenceError("signature envelope has the wrong payload type")
    payload = _decode_base64(_string(envelope, "payload"), "signature payload")
    if payload != canonical_json(evidence):
        raise EvidenceError("signature payload does not bind the exact ci-evidence.json")
    signatures = _array(envelope, "signatures")
    if len(signatures) != 1:
        raise EvidenceError("signature envelope must contain exactly one qualified signature")
    signature = _object(signatures[0], "signature")
    if set(signature) != {"keyid", "sig"}:
        raise EvidenceError("signature entry contains missing or unknown fields")
    if _string(signature, "keyid") != expected_key_id:
        raise EvidenceError("signature key ID does not match the qualified signer")
    if not DIGEST_PATTERN.fullmatch(expected_key_id):
        raise EvidenceError("qualified signer key ID must be a canonical SHA-256 digest")
    try:
        loaded_key = serialization.load_pem_public_key(public_key_pem)
    except (TypeError, ValueError) as error:
        raise EvidenceError("qualified signer public key is invalid") from error
    if not isinstance(loaded_key, ed25519.Ed25519PublicKey):
        raise EvidenceError("qualified signer must use the approved Ed25519 profile")
    if signer_key_id(loaded_key) != expected_key_id:
        raise EvidenceError("qualified signer key ID does not match its public key")
    raw_signature = _decode_base64(_string(signature, "sig"), "signature")
    try:
        loaded_key.verify(raw_signature, dsse_pae(SIGNATURE_PAYLOAD_TYPE, payload))
    except InvalidSignature as error:
        raise EvidenceError("qualified evidence signature verification failed") from error


def validate_evidence(
    evidence: Mapping[str, object],
    *,
    envelope: Mapping[str, object],
    public_key_pem: bytes,
    expected_key_id: str,
    context: Mapping[str, object],
    plan: Mapping[str, object],
    plan_digest: str,
    expected_source_revision: str,
    expected_pipeline_definition_revision: str,
    expected_source_trust: str,
    expected_execution_tier: str,
    expected_correlation_id: str,
    expected_context_digest: str,
    expected_build_id: str,
    max_age: timedelta,
    now: datetime,
    org_schema: Path | None = None,
) -> None:
    checks = validate_org_wire_contract(evidence)
    if org_schema is not None:
        validate_against_pinned_schema(evidence, org_schema)
    expected_values = {
        "source_revision": expected_source_revision,
        "pipeline_definition_revision": expected_pipeline_definition_revision,
        "correlation_id": expected_correlation_id,
        "context_digest": expected_context_digest,
        "build_id": expected_build_id,
        "caller_repository": REPOSITORY,
    }
    for field, expected in expected_values.items():
        if evidence.get(field) != expected:
            raise EvidenceError(f"evidence {field} does not match the trusted caller")

    try:
        validate_trusted_context(
            context,
            context_digest=expected_context_digest,
            pipeline_definition_revision=expected_pipeline_definition_revision,
        )
    except ValueError as error:
        raise EvidenceError(str(error)) from error
    context_values = {
        "source_revision": expected_source_revision,
        "correlation_id": expected_correlation_id,
        "source_trust": expected_source_trust,
        "execution_tier": expected_execution_tier,
        "repository": REPOSITORY,
    }
    for field, expected in context_values.items():
        if context.get(field) != expected:
            raise EvidenceError(f"trusted context {field} does not match the required caller")
    for field in ("base_revision", "workflow_ref", "workflow_revision"):
        if evidence.get(field) != context.get(field):
            raise EvidenceError(f"evidence {field} does not match trusted context")

    if plan.get("source_revision") != expected_source_revision:
        raise EvidenceError("plan source revision does not match the trusted caller")
    if plan.get("pipeline_definition_revision") != expected_pipeline_definition_revision:
        raise EvidenceError("plan pipeline revision does not match the trusted caller")
    calculated_plan_id = calculate_plan_id(plan)
    if plan.get("plan_id") != calculated_plan_id or evidence.get("plan_id") != calculated_plan_id:
        raise EvidenceError("evidence does not bind the exact canonical dispatched plan")
    if checks.get("pipeline-plan") != plan_digest:
        raise EvidenceError("pipeline-plan check does not bind the supplied plan bytes")
    gates = plan.get("gates")
    if not isinstance(gates, list):
        raise EvidenceError("plan gates must be a string array")
    untyped_gates = cast(list[object], gates)
    if not all(isinstance(gate, str) for gate in untyped_gates):
        raise EvidenceError("plan gates must be a string array")
    expected_checks = {"pipeline-plan", *cast(list[str], untyped_gates)}
    if set(checks) != expected_checks:
        raise EvidenceError("evidence check set does not match the exact dispatched plan gates")

    started = _timestamp(_string(evidence, "started_at"), "started_at")
    completed = _timestamp(_string(evidence, "completed_at"), "completed_at")
    if completed < started:
        raise EvidenceError("evidence completed_at precedes started_at")
    normalized_now = now.astimezone(UTC)
    if completed > normalized_now + MAX_CLOCK_SKEW:
        raise EvidenceError("evidence completed_at is in the future")
    if normalized_now - completed > max_age:
        raise EvidenceError("evidence is stale")
    validate_signature(
        evidence,
        envelope,
        public_key_pem=public_key_pem,
        expected_key_id=expected_key_id,
    )


def _signed_envelope(
    evidence: Mapping[str, object],
    private_key: ed25519.Ed25519PrivateKey,
    key_id: str,
) -> dict[str, object]:
    payload = canonical_json(evidence)
    signature = private_key.sign(dsse_pae(SIGNATURE_PAYLOAD_TYPE, payload))
    return {
        "payloadType": SIGNATURE_PAYLOAD_TYPE,
        "payload": base64.b64encode(payload).decode(),
        "signatures": [{"keyid": key_id, "sig": base64.b64encode(signature).decode()}],
    }


def _self_test_adr_ratification_contract() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    schema = _load_adr_ratification_schema(repository_root / "docs/adr" / ADR_RATIFICATION_SCHEMA)
    validator = cast(_Validator, Draft202012Validator(schema))
    pending = {"connectedRatification": "pending"}
    ratified = {
        "connectedRatification": "ratified",
        "ratificationSubjectRevision": "a" * 40,
        "ratificationDecisionDigest": "sha256:" + "b" * 64,
        "ratificationReceiptDigest": "sha256:" + "c" * 64,
        "ratifiedAt": "2026-08-30T12:34:56Z",
    }
    if list(validator.iter_errors(pending)) or list(validator.iter_errors(ratified)):
        raise AssertionError("ADR ratification schema rejected a canonical state")
    invalid = (
        {**pending, "ratificationReceiptDigest": "sha256:" + "c" * 64},
        {key: value for key, value in ratified.items() if key != "ratifiedAt"},
        {**ratified, "ratificationSubjectRevision": "A" * 40},
        {**ratified, "ratificationDecisionDigest": "b" * 64},
        {**ratified, "ratifiedAt": "2026-08-30T12:34:56+00:00"},
        {**ratified, "receiptPath": "mutable/path.json"},
        {"connectedRatification": "approved"},
    )
    if any(not list(validator.iter_errors(candidate)) for candidate in invalid):
        raise AssertionError("ADR ratification schema accepted an invalid state")

    source = (
        "# ADR-9999: Canonicalization self-test\r\n"
        "\r\n"
        "- Status: Accepted in blueprint specification\r\n"
        "- Connected ratification: Pending independent review\r\n"
        "- Effective date: Pending connected ratification\r\n"
        "- Specification date: 2026-08-30\r\n"
        "\r\n"
        "## Decision\r\n"
        "\r\n"
        "Keep this exact decision.\r\n"
        "\r\n"
    )
    expected = (
        b"# ADR-9999: Canonicalization self-test\n"
        b"\n"
        b"- Status: Accepted in blueprint specification\n"
        b"- Specification date: 2026-08-30\n"
        b"\n"
        b"## Decision\n"
        b"\n"
        b"Keep this exact decision.\n"
    )
    if canonical_adr_decision_bytes(source) != expected:
        raise AssertionError("adr-decision-v1 canonical bytes are incorrect")
    updated_mutable_lines = source.replace(
        "Pending independent review",
        "Ratified by immutable external receipt",
    ).replace("Pending connected ratification", "2026-08-30")
    if adr_decision_digest(source) != adr_decision_digest(updated_mutable_lines):
        raise AssertionError("mutable ADR ratification lines changed the decision digest")
    if adr_decision_digest(source) == adr_decision_digest(
        source.replace("Keep this exact decision.", "Change this decision.")
    ):
        raise AssertionError("ADR decision content did not change the decision digest")


def _self_test(org_schema: Path | None) -> None:
    _self_test_adr_ratification_contract()
    source_revision = "a" * 40
    pipeline_revision = "b" * 40
    now = datetime.now(UTC).replace(microsecond=0)
    context: dict[str, object] = {
        "correlation_id": "wave0-required-check-self-test",
        "source_revision": source_revision,
        "base_revision": pipeline_revision,
        "repository": REPOSITORY,
        "workflow_ref": ".github/workflows/required-check.yml",
        "workflow_revision": "c" * 40,
        "source_trust": "untrusted",
        "execution_tier": "untrusted",
    }
    context_digest = sha256_bytes(canonical_json(context))
    unsigned_plan: dict[str, object] = {
        "schema_version": "pipeline-plan.v1",
        "source_revision": source_revision,
        "pipeline_definition_revision": pipeline_revision,
        "pipeline_class": "presubmit",
        "changed_paths": ["BUILD.bazel"],
        "targets": ["//:wave0_tests"],
        "gates": ["bazel-native-agreement"],
    }
    plan = {**unsigned_plan, "plan_id": calculate_plan_id(unsigned_plan)}
    private_key = ed25519.Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    public_key_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    key_id = signer_key_id(public_key)
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        context_path = root / "context.json"
        context_path.write_bytes(canonical_json(context))
        plan_path = root / "pipeline-plan.v1.json"
        plan_path.write_bytes(canonical_json(plan))
        report_path = root / "governance.json"
        bazel_receipt_path = root / "bazel-native-agreement.v1.json"
        bazel_receipt_path.write_bytes(
            canonical_json(
                {
                    "conclusion": "PASS",
                    "schema_version": "bazel-native-agreement.v1",
                }
            )
        )
        reference_revisions = {
            "bootstrap": "d" * 40,
            "github-config": "e" * 40,
            "gitops": "f" * 40,
            "infrastructure-live": "1" * 40,
            "organization-workflows": "2" * 40,
        }
        github_config_revision = reference_revisions["github-config"]

        def qualified_observation(
            name: str,
            revision: str,
            *,
            control: str,
            expected_value: str,
            observed: str | None = None,
        ) -> dict[str, object]:
            observation: dict[str, object] = {
                "status": "PASS",
                "source": "cryptographically-verified-receipt",
                "revision": revision,
                "evidence_sha256": "3" * 64,
                "signature_verification": "PASS",
                "finding": "Qualified subject-bound connected observation.",
                "subject": {
                    "repository": OPERATIONAL_PROJECT_SLUGS[name],
                    "revision": revision,
                    "ref": "refs/heads/main",
                    "control": control,
                    "expected_value": expected_value,
                },
                "verification": {
                    "verifier": "mindclade-connected-observation-verifier",
                    "verifier_version": "1",
                    "verifier_source_revision": source_revision,
                    "algorithm": "ECDSA_P256_SHA256",
                    "key_version": "self-test-key-v1",
                    "public_key_sha256": "4" * 64,
                    "signature_sha256": "5" * 64,
                    "trust_record_sha256": ["6" * 64, "7" * 64],
                },
            }
            if observed is not None:
                observation["observed"] = observed
            return observation

        def qualify_reference(reference: dict[str, object]) -> None:
            name_value = reference.get("name")
            if not isinstance(name_value, str):
                raise AssertionError("governance fixture reference has no name")
            name = name_value
            revision = reference_revisions[name]
            ruleset = OPERATIONAL_RULESETS[name]
            reference.update(
                {
                    "revision": revision,
                    "revision_selection": "declared",
                    "checkout_head": None,
                    "remote": CANONICAL_OPERATIONAL_REMOTES[name],
                    "remote_status": "PASS",
                    "working_tree_state": "excluded",
                    "dirty_state_excluded": True,
                }
            )
            component = cast(dict[str, object], reference["component_metadata"])
            component.update(
                {
                    "status": "PASS",
                    "revision": revision,
                    "content_sha256": "8" * 64,
                    "metadata_name": OPERATIONAL_COMPONENT_NAMES[name],
                    "project_slug": OPERATIONAL_PROJECT_SLUGS[name],
                }
            )
            default_branch = cast(dict[str, object], reference["default_branch"])
            default_branch.update(
                {
                    "target": "main",
                    "observation": qualified_observation(
                        name,
                        revision,
                        control="default_branch",
                        expected_value="main",
                        observed="main",
                    ),
                }
            )
            branch_protection = cast(dict[str, object], reference["branch_protection"])
            branch_protection["target"] = {
                "ref": "refs/heads/main",
                "ruleset": ruleset,
                "policy_path": f"config/rulesets/{ruleset}.yaml",
                "policy_revision": github_config_revision,
                "policy_content_sha256": "9" * 64,
            }
            branch_protection["observation"] = qualified_observation(
                name,
                revision,
                control="branch_protection",
                expected_value=ruleset,
            )
            inventory = cast(dict[str, object], reference["observed_vs_target_inventory"])
            target = cast(dict[str, object], inventory["target_authority"])
            target.update(
                {
                    "root": OPERATIONAL_TARGET_ROOTS[name],
                    "path_count": 1,
                    "path_set_sha256": "b" * 64,
                }
            )
            inventory.update(
                {
                    "status": "PASS",
                    "observed": {
                        "revision": revision,
                        "path_count": 1,
                        "path_set_sha256": "b" * 64,
                    },
                    "missing_paths": [],
                    "extra_paths": [],
                    "conflicts": [],
                    "dispositions": [],
                }
            )
            reference["source_checks"] = [
                {
                    "qualification": "VERIFIED",
                    "status": "PASS",
                    "scope": "immutable-head",
                    "command": "qualified source check",
                    "finding": "Self-test qualified immutable source check.",
                    "evidence_sha256": "c" * 64,
                    "subject": {
                        "repository": OPERATIONAL_PROJECT_SLUGS[name],
                        "revision": revision,
                        "check": "qualified source check",
                    },
                    "verification": {
                        "verifier": "mindclade-connected-observation-verifier",
                        "verifier_version": "1",
                        "verifier_source_revision": source_revision,
                        "algorithm": "ECDSA_P256_SHA256",
                        "key_version": "self-test-key-v1",
                        "public_key_sha256": "d" * 64,
                        "signature_sha256": "e" * 64,
                        "trust_record_sha256": ["f" * 64, "0" * 64],
                    },
                }
            ]

        governance_report = read_object(
            Path(__file__).resolve().parents[1] / "repo/tests/golden/repository_drift.v1.json",
            "repository governance self-test fixture",
        )
        canonical_repository = cast(dict[str, object], governance_report["canonical_repository"])
        canonical_repository.update(
            {
                "observation_scope": "commit",
                "base_commit": source_revision,
                "observed_commit": source_revision,
                "working_tree_state": "clean",
            }
        )
        readiness = cast(dict[str, object], governance_report["readiness"])
        readiness.update(
            {
                "label": "WAVE-0",
                "reason": "Self-test source and connected evidence are complete.",
            }
        )
        summary = cast(dict[str, object], governance_report["summary"])
        for field in (
            "branch_protection_observations_incomplete",
            "default_branch_observations_incomplete",
            "missing_active_paths",
            "operational_inventory_failures",
            "operational_metadata_failures",
            "premature_paths",
            "source_check_failures",
            "source_checks_missing",
            "unknown_paths",
        ):
            summary[field] = 0
        reference_values = cast(list[object], governance_report["reference_sources"])
        for raw_reference in reference_values:
            qualify_reference(cast(dict[str, object], raw_reference))
        report_path.write_bytes(canonical_json(governance_report))
        arguments = argparse.Namespace(
            context=context_path,
            context_digest=context_digest,
            pipeline_definition_revision=pipeline_revision,
            plan=plan_path,
            build_id="01234567-89ab-cdef-8123-456789abcdef",
            started_at=(now - timedelta(minutes=2)).isoformat().replace("+00:00", "Z"),
            completed_at=now.isoformat().replace("+00:00", "Z"),
            check=[f"bazel-native-agreement={bazel_receipt_path}"],
        )
        evidence = build_evidence(arguments)
        governance_arguments = argparse.Namespace(
            **{
                **vars(arguments),
                "check": [f"repository-governance={report_path}"],
            }
        )

        try:
            build_evidence(governance_arguments)
        except ValueError as error:
            if "cryptographic verifier is unavailable/not qualified" not in str(error):
                raise AssertionError(
                    "complete qualified governance fixture did not reach the verifier gate"
                ) from error
        else:
            raise AssertionError("synthetic qualified governance fixture produced PASS evidence")

        def assert_governance_rejected(description: str, candidate: dict[str, object]) -> None:
            report_path.write_bytes(canonical_json(candidate))
            try:
                build_evidence(governance_arguments)
            except ValueError:
                return
            raise AssertionError(f"evidence producer accepted {description}")

        candidate = copy.deepcopy(governance_report)
        candidate_readiness = cast(dict[str, object], candidate["readiness"])
        candidate_readiness["label"] = "INCONCLUSIVE"
        assert_governance_rejected("inconclusive governance", candidate)

        candidate = copy.deepcopy(governance_report)
        candidate.pop("generator")
        assert_governance_rejected("schema-incomplete governance", candidate)

        candidate = copy.deepcopy(governance_report)
        summary = cast(dict[str, object], candidate["summary"])
        summary["branch_protection_observations_incomplete"] = 1
        assert_governance_rejected("incomplete branch-protection observations", candidate)

        candidate = copy.deepcopy(governance_report)
        references = cast(list[object], candidate["reference_sources"])
        reference = cast(dict[str, object], references[0])
        reference["remote"] = "https://github.com/mindclade/wrong.git"
        assert_governance_rejected("noncanonical operational remote", candidate)

        candidate = copy.deepcopy(governance_report)
        references = cast(list[object], candidate["reference_sources"])
        reference = cast(dict[str, object], references[0])
        component = cast(dict[str, object], reference["component_metadata"])
        component["revision"] = "8" * 40
        assert_governance_rejected("unbound component metadata", candidate)

        candidate = copy.deepcopy(governance_report)
        references = cast(list[object], candidate["reference_sources"])
        reference = cast(dict[str, object], references[0])
        default_branch = cast(dict[str, object], reference["default_branch"])
        observation = cast(dict[str, object], default_branch["observation"])
        observation["signature_verification"] = "NOT_VERIFIED"
        assert_governance_rejected("unsigned default-branch observation", candidate)

        candidate = copy.deepcopy(governance_report)
        references = cast(list[object], candidate["reference_sources"])
        reference = cast(dict[str, object], references[0])
        protection = cast(dict[str, object], reference["branch_protection"])
        target = cast(dict[str, object], protection["target"])
        target["policy_revision"] = "9" * 40
        assert_governance_rejected("unbound branch-protection policy", candidate)

        candidate = copy.deepcopy(governance_report)
        references = cast(list[object], candidate["reference_sources"])
        reference = cast(dict[str, object], references[0])
        inventory = cast(dict[str, object], reference["observed_vs_target_inventory"])
        inventory["missing_paths"] = ["missing/path"]
        assert_governance_rejected("incomplete operational inventory", candidate)

        candidate = copy.deepcopy(governance_report)
        references = cast(list[object], candidate["reference_sources"])
        reference = cast(dict[str, object], references[0])
        reference["source_checks"] = [
            {
                "qualification": "ASSERTED",
                "status": "PASS",
                "scope": "immutable-head",
                "command": "qualified source check",
                "finding": "An unsigned assertion must not qualify governance.",
            }
        ]
        assert_governance_rejected("asserted operational source check", candidate)

        report_path.write_bytes(canonical_json(governance_report))
        envelope = _signed_envelope(evidence, private_key, key_id)
        request = ValidationRequest(
            envelope=envelope,
            public_key_pem=public_key_pem,
            expected_key_id=key_id,
            context=context,
            plan=plan,
            plan_digest=sha256_bytes(plan_path.read_bytes()),
            expected_source_revision=source_revision,
            expected_pipeline_definition_revision=pipeline_revision,
            expected_source_trust="untrusted",
            expected_execution_tier="untrusted",
            expected_correlation_id="wave0-required-check-self-test",
            expected_context_digest=context_digest,
            expected_build_id="01234567-89ab-cdef-8123-456789abcdef",
            max_age=timedelta(minutes=10),
            now=now,
            org_schema=org_schema,
        )
        _validate_request(evidence, request)

        tampered = dict(evidence)
        tampered["conclusion"] = "FAIL"
        failures: list[tuple[str, Mapping[str, object], ValidationRequest]] = [
            ("tampered evidence", tampered, request),
            (
                "wrong signer",
                evidence,
                replace(request, expected_key_id="sha256:" + "d" * 64),
            ),
            ("stale evidence", evidence, replace(request, now=now + timedelta(hours=1))),
            (
                "wrong source trust",
                evidence,
                replace(request, expected_source_trust="trusted"),
            ),
            (
                "wrong plan",
                evidence,
                replace(request, plan={**plan, "targets": ["//:wrong"]}),
            ),
        ]
        for description, candidate, candidate_request in failures:
            try:
                _validate_request(candidate, candidate_request)
            except EvidenceError:
                continue
            raise AssertionError(f"required check accepted {description}")


def _read_json_object(path: Path, description: str) -> dict[str, object]:
    try:
        return read_object(path, description)
    except (OSError, json.JSONDecodeError, ValueError) as error:
        raise EvidenceError(f"cannot read {description}: {error}") from error


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--python-test", type=Path)
    parser.add_argument("--validate-adrs", type=Path)
    parser.add_argument("--org-schema", type=Path)
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--signature-envelope", type=Path)
    parser.add_argument("--public-key", type=Path)
    parser.add_argument("--expected-signer-key-id")
    parser.add_argument("--context", type=Path)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--source-revision")
    parser.add_argument("--pipeline-definition-revision")
    parser.add_argument("--source-trust")
    parser.add_argument("--execution-tier")
    parser.add_argument("--correlation-id")
    parser.add_argument("--context-digest")
    parser.add_argument("--build-id")
    parser.add_argument("--max-age-seconds", type=int, default=1800)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.self_test:
        try:
            _self_test(args.org_schema)
        except (OSError, EvidenceError, ValueError) as error:
            print(f"required-check self-test failed: {error}", file=sys.stderr)
            return 1
        print("required-check producer, signer, and org-contract self-test passed")
        return 0
    if args.python_test:
        completed = subprocess.run([sys.executable, str(args.python_test)], check=False)
        return completed.returncode
    if args.validate_adrs:
        try:
            errors = validate_adrs(args.validate_adrs.resolve())
        except (OSError, ValueError) as error:
            print(f"ADR validation failed: {error}", file=sys.stderr)
            return 1
        if errors:
            print("ADR validation failed:\n" + "\n".join(errors), file=sys.stderr)
            return 1
        print("ADR validation passed")
        return 0
    required = {
        "evidence": args.evidence,
        "signature-envelope": args.signature_envelope,
        "public-key": args.public_key,
        "expected-signer-key-id": args.expected_signer_key_id,
        "context": args.context,
        "plan": args.plan,
        "source-revision": args.source_revision,
        "pipeline-definition-revision": args.pipeline_definition_revision,
        "source-trust": args.source_trust,
        "execution-tier": args.execution_tier,
        "correlation-id": args.correlation_id,
        "context-digest": args.context_digest,
        "build-id": args.build_id,
    }
    missing = sorted(name for name, value in required.items() if not value)
    if missing or args.max_age_seconds <= 0:
        print(f"missing or invalid required arguments: {', '.join(missing)}", file=sys.stderr)
        return 2
    try:
        evidence_path = cast(Path, args.evidence)
        plan_path = cast(Path, args.plan)
        evidence = _read_json_object(evidence_path, "ci-evidence.json")
        envelope = _read_json_object(cast(Path, args.signature_envelope), "signature envelope")
        context = _read_json_object(cast(Path, args.context), "trusted context")
        plan = _read_json_object(plan_path, "pipeline plan")
        validate_evidence(
            evidence,
            envelope=envelope,
            public_key_pem=cast(Path, args.public_key).read_bytes(),
            expected_key_id=cast(str, args.expected_signer_key_id),
            context=context,
            plan=plan,
            plan_digest=sha256_bytes(plan_path.read_bytes()),
            expected_source_revision=cast(str, args.source_revision),
            expected_pipeline_definition_revision=cast(str, args.pipeline_definition_revision),
            expected_source_trust=cast(str, args.source_trust),
            expected_execution_tier=cast(str, args.execution_tier),
            expected_correlation_id=cast(str, args.correlation_id),
            expected_context_digest=cast(str, args.context_digest),
            expected_build_id=cast(str, args.build_id),
            max_age=timedelta(seconds=args.max_age_seconds),
            now=datetime.now(UTC),
            org_schema=args.org_schema,
        )
    except (OSError, EvidenceError) as error:
        print(f"required check failed: {error}", file=sys.stderr)
        return 1
    print("required check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
