#!/usr/bin/env python3.12
"""Build the deterministic greenfield ``repository_drift.v1`` evidence artifact."""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import re
import subprocess
import sys
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any, Protocol, TypeGuard, cast

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils
from dependency_policy import validate_dependency_graph
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError
from owner_policy import discover_components, parse_yaml_or_json, validate_owners
from path_policy import (
    ANCHOR_COMMIT,
    discover_actual_paths,
    load_manifest,
    path_set_sha256,
    validate_manifest,
    validate_populated_paths,
)

SCHEMA_VERSION = "repository_drift.v1"
OBSERVATION_SCOPES = {"commit", "working-tree"}
REQUIRED_OPERATIONAL_REFERENCES = {
    "bootstrap",
    "github-config",
    "gitops",
    "infrastructure-live",
    "organization-workflows",
}
DEFAULT_EVIDENCE_EXCLUSIONS = {"docs/architecture/repository-drift-baseline.md"}
OPERATIONAL_TARGET_AUTHORITY = (
    "docs/architecture/blueprint/appendices/A03-repository-estate-and-trust-boundaries.md"
)
CANONICAL_OPERATIONAL_REMOTES = {
    "bootstrap": "https://github.com/mindclade/bootstrap.git",
    "github-config": "https://github.com/mindclade/github-config.git",
    "gitops": "https://github.com/mindclade/gitops.git",
    "infrastructure-live": "https://github.com/mindclade/infrastructure-live.git",
    "organization-workflows": "https://github.com/mindclade/.github.git",
}
OPERATIONAL_COMPONENT_NAMES = {
    "bootstrap": "bootstrap",
    "github-config": "github-config",
    "gitops": "gitops",
    "infrastructure-live": "infrastructure-live",
    "organization-workflows": "dot-github",
}
OPERATIONAL_PROJECT_SLUGS = {
    name: remote.removeprefix("https://github.com/").removesuffix(".git")
    for name, remote in CANONICAL_OPERATIONAL_REMOTES.items()
}
OPERATIONAL_TREE_HEADINGS = {
    "Organization `.github`": ("organization-workflows", ".github"),
    "`github-config`": ("github-config", "github-config"),
    "`bootstrap`": ("bootstrap", "bootstrap"),
    "`infrastructure-live`": ("infrastructure-live", "infrastructure-live"),
    "`gitops`": ("gitops", "gitops"),
}
OPERATIONAL_RULESETS = {
    "bootstrap": "infrastructure-source",
    "github-config": "governance-source",
    "gitops": "deployment-source",
    "infrastructure-live": "infrastructure-source",
    "organization-workflows": "governance-source",
}
CONNECTED_OBSERVATION_RECEIPT_VERSION = "mindclade.connected-observation-receipt.v1"
CONNECTED_OBSERVATION_PAYLOAD_VERSION = "mindclade.connected-observation.v1"
CONNECTED_OBSERVATION_PAYLOAD_TYPE = "application/vnd.mindclade.connected-observation.v1+json"
CONNECTED_OBSERVATION_SIGNING_PREFIX = CONNECTED_OBSERVATION_PAYLOAD_TYPE.encode("ascii") + b"\0"
CONNECTED_OBSERVATION_ALGORITHM = "ECDSA_P256_SHA256"
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
REVISION_PATTERN = re.compile(r"^[0-9a-f]{40}$")


class _Validator(Protocol):
    def iter_errors(self, instance: object) -> Iterable[ValidationError]: ...


class GitReader(Protocol):
    """Read immutable Git facts; tests inject a data-only implementation."""

    def __call__(self, path: Path, *args: str) -> str: ...


def _is_string_list(value: object) -> TypeGuard[list[str]]:
    return isinstance(value, list) and all(
        isinstance(item, str) for item in cast(list[object], value)
    )


def _string_mapping(value: object) -> Mapping[str, object] | None:
    if not isinstance(value, Mapping) or not all(
        isinstance(key, str) for key in cast(Mapping[object, object], value)
    ):
        return None
    return cast(Mapping[str, object], value)


def validate_report_document(report: Mapping[str, Any], schema: Mapping[str, Any]) -> list[str]:
    """Validate the JSON Schema contract and repository-specific report semantics."""

    errors: list[str] = []
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as error:
        return [f"invalid report schema: {error.message}"]
    validator = Draft202012Validator(schema)
    for error in cast(_Validator, validator).iter_errors(report):
        location = "/".join(str(part) for part in error.absolute_path) or "$"
        errors.append(f"schema {location}: {error.message}")
    if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
        errors.append("report schema does not declare JSON Schema 2020-12")

    canonical_observed_commit: str | None = None
    repository = report.get("canonical_repository")
    if isinstance(repository, Mapping):
        repository = cast(Mapping[str, Any], repository)
        observed_value = repository.get("observed_commit")
        canonical_observed_commit = observed_value if isinstance(observed_value, str) else None
        exclusions = repository.get("evidence_outputs_excluded")
        if _is_string_list(exclusions) and exclusions != sorted(set(exclusions)):
            errors.append(
                "canonical_repository.evidence_outputs_excluded must be sorted and unique"
            )

    actual = report.get("actual_paths")
    if _is_string_list(actual) and actual != sorted(set(actual)):
        errors.append("actual_paths must be sorted and unique")

    drift = report.get("drift")
    if isinstance(drift, Mapping):
        drift = cast(Mapping[str, object], drift)
        for field in (
            "unknown_paths",
            "premature_paths",
            "missing_active_paths",
            "restricted_artifacts",
            "oversized_files",
        ):
            value = drift.get(field)
            if _is_string_list(value) and value != sorted(set(value)):
                errors.append(f"drift.{field} must be a sorted unique array")

    references = report.get("reference_sources")
    names: list[str] = []
    if isinstance(references, list):
        for reference in cast(list[object], references):
            if isinstance(reference, Mapping):
                reference = cast(Mapping[str, object], reference)
                name = str(reference.get("name", ""))
                names.append(name)
                if name in REQUIRED_OPERATIONAL_REFERENCES:
                    expected_remote = CANONICAL_OPERATIONAL_REMOTES[name]
                    if reference.get("remote") != expected_remote:
                        errors.append(
                            f"reference_sources {name} does not bind canonical remote "
                            f"{expected_remote}"
                        )
                    if reference.get("revision_selection") == "declared" and (
                        reference.get("checkout_head") is not None
                        or reference.get("working_tree_state") != "excluded"
                    ):
                        errors.append(
                            f"reference_sources {name} must exclude volatile checkout state "
                            "when a declared revision is inspected"
                        )
                    if reference.get("revision_selection") == "head" and (
                        reference.get("checkout_head") != reference.get("revision")
                        or reference.get("working_tree_state") not in {"clean", "dirty"}
                    ):
                        errors.append(
                            f"reference_sources {name} HEAD selection is not bound to "
                            "checkout state"
                        )
                    inventory = _string_mapping(reference.get("observed_vs_target_inventory"))
                    if inventory is not None:
                        for field in ("missing_paths", "extra_paths", "conflicts"):
                            value = inventory.get(field)
                            if _is_string_list(value) and value != sorted(set(value)):
                                errors.append(
                                    f"reference_sources {name} inventory {field} must be "
                                    "sorted and unique"
                                )
                        dispositions = inventory.get("dispositions")
                        if isinstance(dispositions, list):
                            canonical = [
                                json.dumps(item, sort_keys=True, separators=(",", ":"))
                                for item in cast(list[object], dispositions)
                            ]
                            if canonical != sorted(set(canonical)):
                                errors.append(
                                    f"reference_sources {name} inventory dispositions must be "
                                    "sorted and unique"
                                )
                    component = _string_mapping(reference.get("component_metadata"))
                    for field, control in (
                        ("default_branch", "default_branch"),
                        ("branch_protection", "branch_protection"),
                    ):
                        control_value = _string_mapping(reference.get(field))
                        if control_value is None:
                            continue
                        observation = _string_mapping(control_value.get("observation"))
                        if observation is None or observation.get("status") != "PASS":
                            continue
                        subject = _string_mapping(observation.get("subject"))
                        verification = _string_mapping(observation.get("verification"))
                        target = control_value.get("target")
                        if field == "default_branch":
                            expected_ref = "refs/heads/main"
                            expected_value = target
                            if observation.get("observed") != target:
                                errors.append(
                                    f"reference_sources {name} qualified default branch does not "
                                    "match its target"
                                )
                        else:
                            protection_target = _string_mapping(target)
                            expected_ref = (
                                protection_target.get("ref")
                                if protection_target is not None
                                else None
                            )
                            expected_value = (
                                protection_target.get("ruleset")
                                if protection_target is not None
                                else None
                            )
                        expected_subject = {
                            "repository": (
                                component.get("project_slug") if component is not None else None
                            ),
                            "revision": reference.get("revision"),
                            "ref": expected_ref,
                            "control": control,
                            "expected_value": expected_value,
                        }
                        if subject is None or any(
                            subject.get(key) != expected
                            for key, expected in expected_subject.items()
                        ):
                            errors.append(
                                f"reference_sources {name} qualified {field} receipt has the wrong "
                                "subject"
                            )
                        if observation.get("revision") != reference.get("revision"):
                            errors.append(
                                f"reference_sources {name} qualified {field} receipt is stale"
                            )
                        if (
                            verification is None
                            or verification.get("verifier_source_revision")
                            != canonical_observed_commit
                        ):
                            errors.append(
                                f"reference_sources {name} qualified {field} receipt is not bound "
                                "to the observed verifier revision"
                            )
                    source_checks_value = reference.get("source_checks")
                    if isinstance(source_checks_value, list):
                        for raw_check in cast(list[object], source_checks_value):
                            check = _string_mapping(raw_check)
                            if check is None or check.get("qualification") != "VERIFIED":
                                continue
                            subject = _string_mapping(check.get("subject"))
                            verification = _string_mapping(check.get("verification"))
                            expected_subject = {
                                "repository": (
                                    component.get("project_slug") if component is not None else None
                                ),
                                "revision": reference.get("revision"),
                                "check": check.get("command"),
                            }
                            if subject is None or any(
                                subject.get(key) != expected
                                for key, expected in expected_subject.items()
                            ):
                                errors.append(
                                    f"reference_sources {name} verified source check has the "
                                    "wrong subject"
                                )
                            if (
                                verification is None
                                or verification.get("verifier_source_revision")
                                != canonical_observed_commit
                            ):
                                errors.append(
                                    f"reference_sources {name} verified source check is not bound "
                                    "to the observed verifier revision"
                                )
        if names != sorted(set(names)):
            errors.append("reference_sources must be sorted by unique name")

    missing_references = report.get("missing_reference_sources")
    if _is_string_list(missing_references) and missing_references != sorted(
        set(missing_references)
    ):
        errors.append("missing_reference_sources must be a sorted unique string array")
    readiness = _string_mapping(report.get("readiness"))
    if readiness is not None and readiness.get("label") == "WAVE-0":
        reference_values = cast(list[object], references) if isinstance(references, list) else []
        if set(names) != REQUIRED_OPERATIONAL_REFERENCES:
            errors.append("WAVE-0 readiness requires the exact five operational references")
        canonical = _string_mapping(report.get("canonical_repository"))
        if (
            canonical is None
            or canonical.get("observation_scope") != "commit"
            or canonical.get("working_tree_state") != "clean"
            or canonical.get("observed_commit") != canonical.get("base_commit")
        ):
            errors.append("WAVE-0 readiness requires a clean commit-bound canonical observation")
        for raw_reference in reference_values:
            reference = _string_mapping(raw_reference)
            if reference is None:
                continue
            name = str(reference.get("name", ""))
            if name not in REQUIRED_OPERATIONAL_REFERENCES:
                continue
            for field, nested_field in (
                ("component_metadata", "status"),
                ("observed_vs_target_inventory", "status"),
            ):
                value = _string_mapping(reference.get(field))
                if value is None or value.get(nested_field) != "PASS":
                    errors.append(f"WAVE-0 readiness requires {name} {field} PASS")
            for field in ("default_branch", "branch_protection"):
                value = _string_mapping(reference.get(field))
                observation = (
                    _string_mapping(value.get("observation")) if value is not None else None
                )
                if observation is None or observation.get("status") != "PASS":
                    errors.append(f"WAVE-0 readiness requires {name} {field} PASS")
                elif observation.get("signature_verification") != "PASS":
                    errors.append(f"WAVE-0 readiness requires signed {name} {field} evidence")
            source_checks = reference.get("source_checks")
            if not isinstance(source_checks, list) or not source_checks:
                errors.append(f"WAVE-0 readiness requires {name} immutable source checks")
            else:
                checks = [_string_mapping(check) for check in cast(list[object], source_checks)]
                if any(
                    check is None
                    or check.get("qualification") != "VERIFIED"
                    or check.get("status") != "PASS"
                    or check.get("scope") != "immutable-head"
                    for check in checks
                ):
                    errors.append(
                        f"WAVE-0 readiness requires every {name} source check to PASS at "
                        "immutable HEAD"
                    )
    return sorted(set(errors))


def _git(path: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=path, check=False, capture_output=True, text=True)
    return result.stdout if result.returncode == 0 else ""


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _required_mapping(value: object, description: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{description} must be an object")
    return cast(Mapping[str, Any], value)


def _required_nonempty_string(value: object, description: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{description} must be a non-empty string")
    return value


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def canonical_json_bytes(value: object, *, terminal_newline: bool = True) -> bytes:
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return encoded + (b"\n" if terminal_newline else b"")


def _load_canonical_json_object(path: Path, description: str) -> tuple[dict[str, Any], bytes]:
    raw = path.read_bytes()
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_json_keys,
            parse_constant=lambda token: (_ for _ in ()).throw(
                ValueError(f"non-finite JSON value: {token}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise ValueError(f"{description} is not strict JSON: {error}") from error
    if not isinstance(value, dict):
        raise ValueError(f"{description} must be a JSON object")
    typed = cast(dict[str, Any], value)
    if raw != canonical_json_bytes(typed):
        raise ValueError(f"{description} must use canonical JSON with one terminal newline")
    return typed, raw


def _require_exact_keys(value: Mapping[str, Any], expected: set[str], description: str) -> None:
    actual = set(value)
    if actual != expected:
        raise ValueError(
            f"{description} keys differ: missing={sorted(expected - actual)!r}, "
            f"extra={sorted(actual - expected)!r}"
        )


def _load_connected_observation_verifier(
    public_key_path: Path,
    key_version: str,
    trust_record_paths: Sequence[Path],
    verifier_source_revision: str,
) -> tuple[ec.EllipticCurvePublicKey, dict[str, Any]]:
    if not key_version or re.fullmatch(r"[A-Za-z0-9._:/-]+", key_version) is None:
        raise ValueError("connected observation key version is invalid")
    if REVISION_PATTERN.fullmatch(verifier_source_revision) is None:
        raise ValueError("connected observation verifier source revision is invalid")
    if len(trust_record_paths) != 2 or len(set(trust_record_paths)) != 2:
        raise ValueError("connected observation verification requires exactly two trust records")

    public_key_bytes = public_key_path.read_bytes()
    try:
        loaded_key = serialization.load_pem_public_key(public_key_bytes)
    except (TypeError, ValueError) as error:
        raise ValueError("connected observation public key is not valid PEM") from error
    if not isinstance(loaded_key, ec.EllipticCurvePublicKey):
        raise ValueError("connected observation public key must be ECDSA P-256")
    if loaded_key.curve.name != "secp256r1":
        raise ValueError("connected observation public key must be ECDSA P-256")
    canonical_key = loaded_key.public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    if public_key_bytes != canonical_key:
        raise ValueError("connected observation public key must use canonical SPKI PEM")

    trust_digests: list[str] = []
    for index, path in enumerate(trust_record_paths, start=1):
        _, raw = _load_canonical_json_object(path, f"connected observation trust record {index}")
        trust_digests.append(hashlib.sha256(raw).hexdigest())
    if len(set(trust_digests)) != 2:
        raise ValueError("connected observation trust records must be distinct")
    return loaded_key, {
        "verifier": "mindclade-connected-observation-verifier",
        "verifier_version": "1",
        "verifier_source_revision": verifier_source_revision,
        "algorithm": CONNECTED_OBSERVATION_ALGORITHM,
        "key_version": key_version,
        "public_key_sha256": hashlib.sha256(public_key_bytes).hexdigest(),
        "trust_record_sha256": sorted(trust_digests),
    }


def _verify_connected_observation_receipt(
    path: Path,
    public_key: ec.EllipticCurvePublicKey,
    verification: Mapping[str, Any],
) -> dict[str, Any]:
    envelope, raw = _load_canonical_json_object(path, f"connected observation receipt {path}")
    _require_exact_keys(
        envelope,
        {"schema_version", "payload_type", "payload", "signature"},
        "connected observation receipt",
    )
    if envelope["schema_version"] != CONNECTED_OBSERVATION_RECEIPT_VERSION:
        raise ValueError(f"connected observation receipt {path} has the wrong schema version")
    if envelope["payload_type"] != CONNECTED_OBSERVATION_PAYLOAD_TYPE:
        raise ValueError(f"connected observation receipt {path} has the wrong payload type")

    payload = _required_mapping(envelope["payload"], "connected observation payload")
    kind = _required_nonempty_string(payload.get("kind"), "connected observation kind")
    common_fields = {
        "schema_version",
        "kind",
        "repository",
        "revision",
        "status",
        "finding",
    }
    kind_fields = {
        "default_branch": {"ref", "expected_value", "observed"},
        "branch_protection": {
            "ref",
            "expected_value",
            "observed",
            "policy_revision",
            "policy_content_sha256",
        },
        "source_check": {"scope", "check"},
    }
    if kind not in kind_fields:
        raise ValueError(f"connected observation receipt {path} has an invalid kind")
    _require_exact_keys(payload, common_fields | kind_fields[kind], "connected observation payload")
    if payload["schema_version"] != CONNECTED_OBSERVATION_PAYLOAD_VERSION:
        raise ValueError(f"connected observation receipt {path} has the wrong payload schema")
    if payload["status"] != "PASS":
        raise ValueError(f"connected observation receipt {path} is not a PASS observation")
    repository = _required_nonempty_string(payload["repository"], "receipt repository")
    if re.fullmatch(r"mindclade/[A-Za-z0-9._-]+", repository) is None:
        raise ValueError(f"connected observation receipt {path} has an invalid repository")
    revision = _required_nonempty_string(payload["revision"], "receipt revision")
    if REVISION_PATTERN.fullmatch(revision) is None:
        raise ValueError(f"connected observation receipt {path} has an invalid revision")
    _required_nonempty_string(payload["finding"], "receipt finding")
    if kind in {"default_branch", "branch_protection"}:
        if payload["ref"] != "refs/heads/main":
            raise ValueError(f"connected observation receipt {path} is not bound to main")
        _required_nonempty_string(payload["expected_value"], "receipt expected value")
        _required_nonempty_string(payload["observed"], "receipt observed value")
    if kind == "branch_protection":
        policy_revision = _required_nonempty_string(
            payload["policy_revision"], "receipt policy revision"
        )
        if REVISION_PATTERN.fullmatch(policy_revision) is None or not SHA256_PATTERN.fullmatch(
            str(payload["policy_content_sha256"])
        ):
            raise ValueError(f"connected observation receipt {path} has invalid policy binding")
    if kind == "source_check":
        if payload["scope"] != "immutable-head":
            raise ValueError(f"connected observation receipt {path} has a mutable check scope")
        _required_nonempty_string(payload["check"], "receipt source check")

    signature = _required_mapping(envelope["signature"], "connected observation signature")
    _require_exact_keys(
        signature,
        {"algorithm", "key_version", "signature_base64"},
        "connected observation signature",
    )
    if signature["algorithm"] != CONNECTED_OBSERVATION_ALGORITHM:
        raise ValueError(f"connected observation receipt {path} has an invalid algorithm")
    if signature["key_version"] != verification["key_version"]:
        raise ValueError(f"connected observation receipt {path} uses an untrusted key version")
    encoded_signature = _required_nonempty_string(
        signature["signature_base64"], "connected observation signature"
    )
    try:
        signature_bytes = base64.b64decode(encoded_signature, validate=True)
    except (binascii.Error, ValueError) as error:
        raise ValueError(f"connected observation receipt {path} has invalid base64") from error
    if base64.b64encode(signature_bytes).decode("ascii") != encoded_signature:
        raise ValueError(f"connected observation receipt {path} has non-canonical base64")
    try:
        r_value, s_value = utils.decode_dss_signature(signature_bytes)
    except ValueError as error:
        raise ValueError(f"connected observation receipt {path} has invalid DER ECDSA") from error
    if utils.encode_dss_signature(r_value, s_value) != signature_bytes:
        raise ValueError(f"connected observation receipt {path} has non-canonical DER ECDSA")
    signed_bytes = CONNECTED_OBSERVATION_SIGNING_PREFIX + canonical_json_bytes(
        payload, terminal_newline=False
    )
    try:
        public_key.verify(signature_bytes, signed_bytes, ec.ECDSA(hashes.SHA256()))
    except InvalidSignature as error:
        raise ValueError(
            f"connected observation receipt {path} signature verification failed"
        ) from error
    return {
        "payload": dict(payload),
        "evidence_sha256": hashlib.sha256(raw).hexdigest(),
        "verification": {
            **dict(verification),
            "signature_sha256": hashlib.sha256(signature_bytes).hexdigest(),
        },
    }


def _parse_tree_body(body: str, description: str) -> list[str]:
    stack: list[str] = []
    paths: list[str] = []
    for line_number, line in enumerate(body.splitlines(), start=1):
        match = re.fullmatch(r"(?P<prefix>(?:│   |    )*)(?:├── |└── )(?P<name>.+)", line)
        if match is None:
            raise ValueError(f"{description} has an invalid tree line {line_number}: {line!r}")
        depth = len(match.group("prefix")) // 4
        if depth > len(stack):
            raise ValueError(f"{description} skips a tree parent at line {line_number}")
        stack = stack[:depth]
        raw_name = match.group("name")
        name = raw_name.split("  # ", 1)[0] if "  # " in raw_name else raw_name
        if not name:
            raise ValueError(f"{description} has an empty tree entry at line {line_number}")
        is_directory = name.endswith("/")
        leaf = name[:-1] if is_directory else name
        candidate = PurePosixPath(*stack, leaf)
        if (
            not leaf
            or "\\" in leaf
            or candidate.is_absolute()
            or any(part in {"", ".", ".."} for part in candidate.parts)
        ):
            raise ValueError(f"{description} has a non-canonical path at line {line_number}")
        if is_directory:
            stack.append(leaf)
        else:
            paths.append(candidate.as_posix())
    if len(paths) != len(set(paths)):
        raise ValueError(f"{description} contains duplicate file paths")
    return paths


def extract_operational_targets(authority_path: Path) -> dict[str, dict[str, Any]]:
    """Extract the five exact operational file inventories declared by Appendix A3."""

    text = authority_path.read_text(encoding="utf-8")
    authority_sha256 = hashlib.sha256(authority_path.read_bytes()).hexdigest()
    pattern = re.compile(
        r"#### (?P<heading>[^\n]+) canonical file tree\n\n"
        r"```text\n(?P<root>[^\n]+)/\n(?P<body>.*?)\n```",
        re.DOTALL,
    )
    targets: dict[str, dict[str, Any]] = {}
    for match in pattern.finditer(text):
        heading = match.group("heading")
        definition = OPERATIONAL_TREE_HEADINGS.get(heading)
        if definition is None:
            continue
        name, expected_root = definition
        observed_root = match.group("root")
        if observed_root != expected_root:
            raise ValueError(
                f"Appendix A3 {name} tree root is {observed_root!r}, expected {expected_root!r}"
            )
        paths = _parse_tree_body(match.group("body"), f"Appendix A3 {name} tree")
        targets[name] = {
            "authority_path": OPERATIONAL_TARGET_AUTHORITY,
            "authority_sha256": authority_sha256,
            "section": f"{heading} canonical file tree",
            "target_root": expected_root,
            "paths": paths,
        }
    if set(targets) != REQUIRED_OPERATIONAL_REFERENCES:
        missing = sorted(REQUIRED_OPERATIONAL_REFERENCES - set(targets))
        extra = sorted(set(targets) - REQUIRED_OPERATIONAL_REFERENCES)
        raise ValueError(
            f"Appendix A3 operational target inventory mismatch: missing={missing!r}, "
            f"extra={extra!r}"
        )
    return targets


def _component_metadata(name: str, revision: str, text: str) -> dict[str, Any]:
    if not text:
        raise ValueError(f"reference source {name!r} lacks component.yaml at {revision}")
    try:
        document = _required_mapping(
            parse_yaml_or_json(text), f"reference source {name!r} component.yaml"
        )
    except ValueError as error:
        raise ValueError(
            f"reference source {name!r} has invalid component.yaml: {error}"
        ) from error
    metadata = _required_mapping(document.get("metadata"), f"{name} component metadata")
    annotations_value = metadata.get("annotations", {})
    annotations = _required_mapping(annotations_value, f"{name} component annotations")
    spec = _required_mapping(document.get("spec"), f"{name} component spec")
    release = _required_mapping(spec.get("release"), f"{name} component release")
    metadata_name = _required_nonempty_string(metadata.get("name"), f"{name} component name")
    if metadata_name != OPERATIONAL_COMPONENT_NAMES[name]:
        raise ValueError(
            f"reference source {name!r} component identity is {metadata_name!r}, "
            f"expected {OPERATIONAL_COMPONENT_NAMES[name]!r}"
        )
    project_slug = _required_nonempty_string(
        annotations.get("github.com/project-slug"), f"{name} component project slug"
    )
    if project_slug != OPERATIONAL_PROJECT_SLUGS[name]:
        raise ValueError(
            f"reference source {name!r} component project slug is {project_slug!r}, "
            f"expected {OPERATIONAL_PROJECT_SLUGS[name]!r}"
        )
    trust_tier = spec.get("trust_tier") or annotations.get("mindclade.dev/trust-tier")
    recovery_tier = spec.get("recovery_tier") or annotations.get("mindclade.dev/recovery-tier")
    evidence_value = release.get("evidence", [])
    if not isinstance(evidence_value, list) or not all(
        isinstance(item, str) and item for item in cast(list[object], evidence_value)
    ):
        raise ValueError(f"{name} component release evidence must be a string array")
    immutable = release.get("immutable")
    if immutable is not True:
        raise ValueError(f"{name} component release must declare immutable: true")
    return {
        "status": "PASS",
        "path": "component.yaml",
        "revision": revision,
        "content_sha256": _sha256_text(text),
        "api_version": _required_nonempty_string(
            document.get("apiVersion"), f"{name} component apiVersion"
        ),
        "metadata_name": metadata_name,
        "project_slug": project_slug,
        "owner": _required_nonempty_string(spec.get("owner"), f"{name} component owner"),
        "repository_class": _required_nonempty_string(
            spec.get("repository_class"), f"{name} component repository_class"
        ),
        "trust_tier": _required_nonempty_string(trust_tier, f"{name} component trust_tier"),
        "recovery_tier": _required_nonempty_string(
            recovery_tier, f"{name} component recovery_tier"
        ),
        "release": {
            "strategy": _required_nonempty_string(
                release.get("strategy"), f"{name} component release strategy"
            ),
            "artifact": _required_nonempty_string(
                release.get("artifact"), f"{name} component release artifact"
            ),
            "immutable": True,
            "evidence": sorted(cast(list[str], evidence_value)),
        },
    }


def _unqualified_observation(
    name: str,
    kind: str,
    *,
    local_observed: str | None = None,
    revision: str | None,
) -> dict[str, Any]:
    if kind == "default branch" and revision is not None:
        return {
            "status": "INCONCLUSIVE",
            "source": "local-checkout",
            "observed": local_observed,
            "revision": revision,
            "evidence_sha256": None,
            "signature_verification": "NOT_VERIFIED",
            "finding": (
                "The local checkout branch is recorded but does not prove the remote default "
                "branch or its live enforcement."
            ),
        }
    if kind == "default branch":
        return {
            "status": "INCONCLUSIVE",
            "source": "not-observed",
            "observed": None,
            "revision": None,
            "evidence_sha256": None,
            "signature_verification": "NOT_VERIFIED",
            "finding": (
                f"No cryptographically verified, subject-bound {name} default-branch receipt "
                "format and trust root exist in Wave 0; the volatile local checkout is excluded."
            ),
        }
    return {
        "status": "INCONCLUSIVE",
        "source": "not-observed",
        "revision": None,
        "evidence_sha256": None,
        "signature_verification": "NOT_VERIFIED",
        "finding": (
            f"No cryptographically verified, subject-bound {name} branch-protection receipt "
            "format and trust root exist in Wave 0; desired-state files are not treated as live "
            "enforcement evidence."
        ),
    }


def _inventory_dispositions(
    missing: Sequence[str], extra: Sequence[str], conflicts: Sequence[str]
) -> list[dict[str, str]]:
    dispositions = [
        {
            "classification": "missing",
            "path": path,
            "disposition": "unresolved",
            "rationale": "The Appendix A3 target path is absent from the immutable source tree.",
        }
        for path in missing
    ]
    dispositions.extend(
        {
            "classification": "extra",
            "path": path,
            "disposition": "unresolved",
            "rationale": "The immutable source path is absent from the Appendix A3 target tree.",
        }
        for path in extra
    )
    dispositions.extend(
        {
            "classification": "conflict",
            "path": path,
            "disposition": "unresolved",
            "rationale": "The target and immutable source disagree on a file/directory boundary.",
        }
        for path in conflicts
    )
    return sorted(dispositions, key=lambda item: (item["classification"], item["path"]))


def _observed_vs_target_inventory(
    name: str,
    revision: str,
    target: Mapping[str, Any],
    git_reader: GitReader,
    path: Path,
) -> dict[str, Any]:
    target_paths = sorted(set(cast(Sequence[str], target["paths"])))
    observed_output = git_reader(path, "ls-tree", "-r", "--name-only", revision)
    observed_paths = sorted({line for line in observed_output.splitlines() if line})
    missing = sorted(set(target_paths) - set(observed_paths))
    extra = sorted(set(observed_paths) - set(target_paths))
    conflicts = sorted(
        {
            f"{target_path} <> {observed_path}"
            for target_path in target_paths
            for observed_path in observed_paths
            if target_path.startswith(observed_path + "/")
            or observed_path.startswith(target_path + "/")
        }
    )
    dispositions = _inventory_dispositions(missing, extra, conflicts)
    return {
        "status": "PASS" if not dispositions else "FAIL",
        "target_authority": {
            "path": str(target["authority_path"]),
            "content_sha256": str(target["authority_sha256"]),
            "section": str(target["section"]),
            "root": str(target["target_root"]),
            "path_count": len(target_paths),
            "path_set_sha256": path_set_sha256(target_paths),
        },
        "observed": {
            "revision": revision,
            "path_count": len(observed_paths),
            "path_set_sha256": path_set_sha256(observed_paths),
        },
        "missing_paths": missing,
        "extra_paths": extra,
        "conflicts": conflicts,
        "dispositions": dispositions,
    }


def _content_snapshot_sha256(
    root: Path, paths: Sequence[str], excluded_paths: Sequence[str]
) -> str:
    """Hash path/content pairs without allowing evidence outputs to hash themselves."""

    excluded = set(excluded_paths)
    digest = hashlib.sha256()
    for relative in sorted(set(paths) - excluded):
        file_path = root / relative
        if not file_path.is_file():
            raise ValueError(f"repository path disappeared while hashing: {relative}")
        content_digest = hashlib.sha256(file_path.read_bytes()).hexdigest()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(content_digest.encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _resolve_reference_revision(
    name: str,
    path: Path,
    declared_revision: str | None,
    git_reader: GitReader,
) -> tuple[str, str | None, str]:
    if declared_revision is None:
        checkout_head = git_reader(path, "rev-parse", "HEAD").strip()
        if re.fullmatch(r"[0-9a-f]{40}", checkout_head) is None:
            raise ValueError(f"reference source {name!r} has no immutable checkout HEAD: {path}")
        return checkout_head, checkout_head, "head"
    if re.fullmatch(r"[0-9a-f]{40}", declared_revision) is None:
        raise ValueError(f"reference source {name!r} has an invalid declared revision")
    resolved = git_reader(path, "rev-parse", "--verify", f"{declared_revision}^{{commit}}").strip()
    if resolved != declared_revision:
        raise ValueError(
            f"reference source {name!r} cannot resolve declared revision {declared_revision}"
        )
    return declared_revision, None, "declared"


def inspect_reference(
    name: str,
    path: Path,
    revision: str,
    checkout_head: str | None,
    revision_selection: str,
    target: Mapping[str, Any],
    github_config_path: Path,
    github_config_revision: str,
    source_checks: Sequence[Mapping[str, str]] = (),
    *,
    connected_receipts: Sequence[Mapping[str, Any]] = (),
    git_reader: GitReader = _git,
) -> dict[str, Any]:
    remote = git_reader(path, "remote", "get-url", "origin").strip()
    expected_remote = CANONICAL_OPERATIONAL_REMOTES[name]
    if remote != expected_remote:
        raise ValueError(
            f"reference source {name!r} remote is {remote!r}, expected {expected_remote!r}"
        )
    component_text = git_reader(path, "show", f"{revision}:component.yaml")
    local_branch = (
        git_reader(path, "branch", "--show-current").strip() or None
        if checkout_head is not None
        else None
    )
    default_branch = {
        "target": "main",
        "observation": _unqualified_observation(
            name,
            "default branch",
            local_observed=local_branch,
            revision=checkout_head,
        ),
    }
    receipts_by_kind: dict[str, list[Mapping[str, Any]]] = {}
    for receipt in connected_receipts:
        payload = _required_mapping(receipt.get("payload"), "verified receipt payload")
        receipts_by_kind.setdefault(str(payload.get("kind", "")), []).append(receipt)
    for singleton_kind in ("default_branch", "branch_protection"):
        if len(receipts_by_kind.get(singleton_kind, ())) > 1:
            raise ValueError(f"reference source {name!r} has duplicate {singleton_kind} receipts")

    default_receipts = receipts_by_kind.get("default_branch", [])
    if default_receipts:
        receipt = default_receipts[0]
        payload = _required_mapping(receipt["payload"], "default-branch receipt payload")
        if (
            payload["repository"] != OPERATIONAL_PROJECT_SLUGS[name]
            or payload["revision"] != revision
            or payload["expected_value"] != "main"
            or payload["observed"] != "main"
        ):
            raise ValueError(f"reference source {name!r} default-branch receipt subject drift")
        default_branch["observation"] = {
            "status": "PASS",
            "source": "cryptographically-verified-receipt",
            "observed": "main",
            "revision": revision,
            "evidence_sha256": receipt["evidence_sha256"],
            "signature_verification": "PASS",
            "finding": payload["finding"],
            "subject": {
                "repository": OPERATIONAL_PROJECT_SLUGS[name],
                "revision": revision,
                "ref": "refs/heads/main",
                "control": "default_branch",
                "expected_value": "main",
            },
            "verification": receipt["verification"],
        }
    ruleset = OPERATIONAL_RULESETS[name]
    policy_path = f"config/rulesets/{ruleset}.yaml"
    policy_text = git_reader(github_config_path, "show", f"{github_config_revision}:{policy_path}")
    if not policy_text:
        raise ValueError(
            f"reference source {name!r} cannot bind target protection policy "
            f"{policy_path!r} at {github_config_revision}"
        )
    branch_protection = {
        "target": {
            "ref": "refs/heads/main",
            "ruleset": ruleset,
            "policy_path": policy_path,
            "policy_revision": github_config_revision,
            "policy_content_sha256": _sha256_text(policy_text),
        },
        "observation": _unqualified_observation(
            name,
            "branch protection",
            revision=revision,
        ),
    }
    protection_receipts = receipts_by_kind.get("branch_protection", [])
    if protection_receipts:
        receipt = protection_receipts[0]
        payload = _required_mapping(receipt["payload"], "branch-protection receipt payload")
        protection_target = cast(Mapping[str, Any], branch_protection["target"])
        if (
            payload["repository"] != OPERATIONAL_PROJECT_SLUGS[name]
            or payload["revision"] != revision
            or payload["ref"] != protection_target["ref"]
            or payload["expected_value"] != protection_target["ruleset"]
            or payload["observed"] != protection_target["ruleset"]
            or payload["policy_revision"] != protection_target["policy_revision"]
            or payload["policy_content_sha256"] != protection_target["policy_content_sha256"]
        ):
            raise ValueError(f"reference source {name!r} branch-protection receipt subject drift")
        branch_protection["observation"] = {
            "status": "PASS",
            "source": "cryptographically-verified-receipt",
            "revision": revision,
            "evidence_sha256": receipt["evidence_sha256"],
            "signature_verification": "PASS",
            "finding": payload["finding"],
            "subject": {
                "repository": OPERATIONAL_PROJECT_SLUGS[name],
                "revision": revision,
                "ref": protection_target["ref"],
                "control": "branch_protection",
                "expected_value": protection_target["ruleset"],
            },
            "verification": receipt["verification"],
        }

    verified_source_checks: list[dict[str, Any]] = []
    seen_check_commands: set[str] = set()
    for receipt in receipts_by_kind.get("source_check", []):
        payload = _required_mapping(receipt["payload"], "source-check receipt payload")
        command = str(payload["check"])
        if command in seen_check_commands:
            raise ValueError(f"reference source {name!r} has duplicate receipt for {command!r}")
        seen_check_commands.add(command)
        if (
            payload["repository"] != OPERATIONAL_PROJECT_SLUGS[name]
            or payload["revision"] != revision
        ):
            raise ValueError(f"reference source {name!r} source-check receipt subject drift")
        verified_source_checks.append(
            {
                "qualification": "VERIFIED",
                "status": "PASS",
                "scope": "immutable-head",
                "command": command,
                "finding": payload["finding"],
                "evidence_sha256": receipt["evidence_sha256"],
                "subject": {
                    "repository": OPERATIONAL_PROJECT_SLUGS[name],
                    "revision": revision,
                    "check": command,
                },
                "verification": receipt["verification"],
            }
        )
    return {
        "name": name,
        "role": "reference_only",
        "revision": revision,
        "revision_selection": revision_selection,
        "checkout_head": checkout_head,
        "remote": remote,
        "remote_status": "PASS",
        "working_tree_state": (
            "dirty" if git_reader(path, "status", "--porcelain=v1").strip() else "clean"
        )
        if checkout_head is not None
        else "excluded",
        "dirty_state_excluded": True,
        "component_metadata": _component_metadata(name, revision, component_text),
        "default_branch": default_branch,
        "branch_protection": branch_protection,
        "observed_vs_target_inventory": _observed_vs_target_inventory(
            name, revision, target, git_reader, path
        ),
        "source_checks": sorted(
            [
                *({"qualification": "ASSERTED", **dict(check)} for check in source_checks),
                *verified_source_checks,
            ],
            key=lambda check: (
                check.get("qualification", ""),
                check.get("status", ""),
                check.get("scope", ""),
                check.get("command", ""),
                check.get("finding", ""),
            ),
        ),
    }


def build_report(
    root: Path,
    manifest_path: Path,
    component_schema: Path,
    references: Sequence[tuple[str, Path]],
    reference_checks: Mapping[str, Sequence[Mapping[str, str]]] | None = None,
    reference_revisions: Mapping[str, str] | None = None,
    *,
    observation_scope: str = "working-tree",
    excluded_evidence_paths: Sequence[str] = (),
    operational_targets: Mapping[str, Mapping[str, Any]] | None = None,
    reference_receipt_paths: Mapping[str, Sequence[Path]] | None = None,
    connected_observation_public_key: Path | None = None,
    connected_observation_key_version: str | None = None,
    connected_observation_trust_records: Sequence[Path] = (),
    git_reader: GitReader = _git,
) -> dict[str, Any]:
    if observation_scope not in OBSERVATION_SCOPES:
        raise ValueError(f"invalid observation scope: {observation_scope!r}")
    base_commit = git_reader(root, "rev-parse", "--verify", "HEAD").strip()
    if re.fullmatch(r"[0-9a-f]{40}", base_commit) is None:
        raise ValueError(f"canonical repository is not an initialized Git worktree: {root}")
    worktree_state = "dirty" if git_reader(root, "status", "--porcelain=v1").strip() else "clean"
    if observation_scope == "commit" and worktree_state != "clean":
        raise ValueError("commit observation requires a clean canonical repository worktree")
    normalized_exclusions = sorted(
        DEFAULT_EVIDENCE_EXCLUSIONS
        | {str(Path(path).as_posix()) for path in excluded_evidence_paths}
    )
    manifest = load_manifest(manifest_path)
    manifest_errors = validate_manifest(manifest)
    if manifest_errors:
        raise ValueError("invalid path manifest:\n" + "\n".join(manifest_errors))
    actual = discover_actual_paths(root)
    drift = validate_populated_paths(manifest, root)
    component_errors, components = discover_components(root, component_schema)
    if component_errors:
        raise ValueError("invalid component metadata:\n" + "\n".join(component_errors))
    ownership_gaps = validate_owners(manifest, components, root / ".github/CODEOWNERS")
    graph_errors, edges = validate_dependency_graph(components)
    if graph_errors:
        raise ValueError("invalid dependency graph:\n" + "\n".join(graph_errors))

    actual_set = set(actual)
    contracts = [
        {
            "path": path,
            "authority": "monorepo",
            "kind": "protobuf" if path.endswith(".proto") else "json-schema",
        }
        for path in actual
        if path.endswith(".proto") or path.endswith(".schema.json")
    ]
    deployables = [
        {"path": path, "authority": "monorepo-build"}
        for path in actual
        if "/cmd/" in f"/{path}/" and Path(path).name in {"main.go", "main.py", "main.rs"}
    ]
    generated = sorted(
        entry["path"]
        for entry in manifest["paths"]
        if entry.get("source_authority") == "reviewed-generated" and entry["path"] in actual_set
    )
    vendor = sorted(path for path in actual if path.startswith("third_party/"))
    research = sorted(path for path in actual if path.startswith("research/"))
    blocking_drift = sum(
        len(drift[key])
        for key in (
            "unknown_paths",
            "premature_paths",
            "missing_active_paths",
            "restricted_artifacts",
            "oversized_files",
        )
    )
    authority = manifest["metadata"]["authority"]
    reconciliation = manifest["metadata"]["reconciliation"]
    checks = reference_checks or {}
    declared_revisions = reference_revisions or {}
    reference_names = [name for name, _ in references]
    if len(reference_names) != len(set(reference_names)):
        raise ValueError("reference source names must be unique")
    unexpected_references = set(reference_names) - REQUIRED_OPERATIONAL_REFERENCES
    if unexpected_references:
        raise ValueError(f"unknown reference-only sources: {sorted(unexpected_references)!r}")
    unknown_check_sources = set(checks) - set(reference_names)
    if unknown_check_sources:
        raise ValueError(
            f"reference checks name unknown sources: {sorted(unknown_check_sources)!r}"
        )
    unknown_revision_sources = set(declared_revisions) - set(reference_names)
    if unknown_revision_sources:
        raise ValueError(
            f"reference revisions name unknown sources: {sorted(unknown_revision_sources)!r}"
        )
    receipt_paths = reference_receipt_paths or {}
    unknown_receipt_sources = set(receipt_paths) - set(reference_names)
    if unknown_receipt_sources:
        raise ValueError(
            f"connected receipts name unknown sources: {sorted(unknown_receipt_sources)!r}"
        )
    receipt_configuration_present = bool(receipt_paths)
    ancillary_receipt_configuration = (
        connected_observation_public_key is not None
        or connected_observation_key_version is not None
        or bool(connected_observation_trust_records)
    )
    if receipt_configuration_present != ancillary_receipt_configuration:
        raise ValueError(
            "connected receipt paths, public key, key version, and two trust records must be "
            "provided together"
        )
    verified_receipts: dict[str, list[dict[str, Any]]] = {}
    if receipt_configuration_present:
        if observation_scope != "commit":
            raise ValueError("connected receipts require a clean commit-bound observation")
        public_key, verification = _load_connected_observation_verifier(
            cast(Path, connected_observation_public_key),
            cast(str, connected_observation_key_version),
            connected_observation_trust_records,
            base_commit,
        )
        seen_receipt_paths: set[Path] = set()
        for name, paths in receipt_paths.items():
            for path in paths:
                resolved_path = path.resolve()
                if resolved_path in seen_receipt_paths:
                    raise ValueError(f"connected receipt path is duplicated: {path}")
                seen_receipt_paths.add(resolved_path)
                verified_receipts.setdefault(name, []).append(
                    _verify_connected_observation_receipt(path, public_key, verification)
                )
    target_inventories = (
        dict(operational_targets)
        if operational_targets is not None
        else extract_operational_targets(root / OPERATIONAL_TARGET_AUTHORITY)
    )
    if set(target_inventories) != REQUIRED_OPERATIONAL_REFERENCES:
        raise ValueError("operational target inventories must cover the exact five sources")
    reference_paths = dict(references)
    resolved_revisions = {
        name: _resolve_reference_revision(name, path, declared_revisions.get(name), git_reader)
        for name, path in references
    }
    github_config_path = reference_paths.get("github-config")
    if github_config_path is None:
        raise ValueError(
            "github-config is required to bind the target branch-protection policy digests"
        )
    github_config_revision = resolved_revisions["github-config"][0]
    reference_reports = sorted(
        (
            inspect_reference(
                name,
                path,
                *resolved_revisions[name],
                target_inventories[name],
                github_config_path,
                github_config_revision,
                checks.get(name, ()),
                connected_receipts=verified_receipts.get(name, ()),
                git_reader=git_reader,
            )
            for name, path in references
            if name in REQUIRED_OPERATIONAL_REFERENCES
        ),
        key=lambda item: item["name"],
    )
    operational_references = [
        reference for reference in reference_reports if reference["name"] != "legacy-monorepo"
    ]
    missing_reference_sources = sorted(REQUIRED_OPERATIONAL_REFERENCES - set(reference_names))
    source_check_failures = sum(
        check["qualification"] != "VERIFIED"
        or check["status"] != "PASS"
        or check["scope"] != "immutable-head"
        for reference in operational_references
        for check in reference["source_checks"]
    )
    source_checks_missing = len(missing_reference_sources) + sum(
        not reference["source_checks"] for reference in operational_references
    )
    operational_metadata_failures = sum(
        reference["component_metadata"]["status"] != "PASS" or reference["remote_status"] != "PASS"
        for reference in operational_references
    )
    default_branch_observations_incomplete = sum(
        reference["default_branch"]["observation"]["status"] != "PASS"
        for reference in operational_references
    )
    branch_protection_observations_incomplete = sum(
        reference["branch_protection"]["observation"]["status"] != "PASS"
        for reference in operational_references
    )
    operational_inventory_failures = sum(
        reference["observed_vs_target_inventory"]["status"] != "PASS"
        for reference in operational_references
    )
    readiness = (
        "WAVE-0"
        if blocking_drift == 0
        and not ownership_gaps
        and source_check_failures == 0
        and source_checks_missing == 0
        and operational_metadata_failures == 0
        and default_branch_observations_incomplete == 0
        and branch_protection_observations_incomplete == 0
        and operational_inventory_failures == 0
        and observation_scope == "commit"
        and worktree_state == "clean"
        else "INCONCLUSIVE"
    )
    report = {
        "schema_version": SCHEMA_VERSION,
        "generator": {"name": "tools/repo/build_repository_drift_report.py", "version": "1"},
        "canonical_repository": {
            "name": "mindclade",
            "url": "https://github.com/mindclade/mindclade",
            "anchor_commit": ANCHOR_COMMIT,
            "observation_scope": observation_scope,
            "base_commit": base_commit,
            "observed_commit": base_commit if observation_scope == "commit" else None,
            "working_tree_state": worktree_state,
            "path_set_sha256": path_set_sha256(actual),
            "content_snapshot_sha256": _content_snapshot_sha256(
                root, actual, normalized_exclusions
            ),
            "evidence_outputs_excluded": normalized_exclusions,
        },
        "target_authority": {
            "source": authority["source"],
            "source_sha256": authority["sha256"],
            "blueprint_sha256": authority["blueprint_sha256"],
            "original_file_count": authority["original_file_count"],
            "reconciliation_version": reconciliation["version"],
            "canonical_file_count": reconciliation["canonical_file_count"],
            "canonical_path_set_sha256": reconciliation["canonical_path_set_sha256"],
        },
        "summary": {
            "canonical_target_paths": len(manifest["paths"]),
            "populated_paths": len(actual),
            "unknown_paths": len(drift["unknown_paths"]),
            "premature_paths": len(drift["premature_paths"]),
            "missing_active_paths": len(drift["missing_active_paths"]),
            "component_count": len(components),
            "dependency_edge_count": len(edges),
            "source_check_failures": source_check_failures,
            "source_checks_missing": source_checks_missing,
            "operational_metadata_failures": operational_metadata_failures,
            "default_branch_observations_incomplete": (default_branch_observations_incomplete),
            "branch_protection_observations_incomplete": (
                branch_protection_observations_incomplete
            ),
            "operational_inventory_failures": operational_inventory_failures,
        },
        "actual_paths": actual,
        "drift": drift,
        "components": components,
        "dependency_edges": edges,
        "ownership_gaps": ownership_gaps,
        "contract_authorities": sorted(contracts, key=lambda item: item["path"]),
        "deployables": sorted(deployables, key=lambda item: item["path"]),
        "artifact_release_authorities": [],
        "duplicate_systems": [],
        "boundaries": {
            "generated_paths": generated,
            "third_party_paths": vendor,
            "research_paths": research,
            "legacy_code_imported": False,
            "product_graph_empty": not any(
                path.split("/", 1)[0]
                in {
                    "protocols",
                    "libs",
                    "bio",
                    "data",
                    "runtime",
                    "kernels",
                    "models",
                    "training",
                    "evaluation",
                    "inference",
                    "agents",
                    "services",
                    "workers",
                    "sdk",
                    "kits",
                    "apps",
                    "deploy",
                }
                for path in actual
            ),
        },
        "reference_sources": reference_reports,
        "missing_reference_sources": missing_reference_sources,
        "migration_dispositions": [],
        "readiness": {
            "label": readiness,
            "reason": (
                "Wave 0 repository governance has no blocking source drift."
                if readiness == "WAVE-0"
                else (
                    "Source drift, ownership, or operational source qualification evidence "
                    "remains incomplete; no connected qualification is inferred."
                )
            ),
        },
    }
    schema_path = Path(__file__).with_name("repository_drift.v1.schema.json")
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    schema_errors = validate_report_document(report, schema)
    if schema_errors:
        raise ValueError("invalid generated report:\n" + "\n".join(schema_errors))
    return report


def render_markdown(report: Mapping[str, Any]) -> str:
    summary = report["summary"]
    references = report["reference_sources"]
    rows = (
        "\n".join(
            f"| `{item['name']}` | `{item['revision']}` | "
            f"`{item['remote']}` | {item['working_tree_state']}; immutable object inspected; "
            f"selection={item['revision_selection']}; checkout HEAD="
            f"`{item['checkout_head'] or 'excluded'}`; "
            "checks retain their listed scopes |"
            for item in references
        )
        or "| _none_ | _none_ | _none_ | _none_ |"
    )
    check_rows = [
        (
            f"| `{item['name']}` | `{check['qualification']}` | `{check['status']}` | "
            f"`{check['scope']}` | "
            f"`{check['command']}` | {check['finding']} |"
        )
        for item in references
        for check in item.get("source_checks", [])
    ]
    checks = "\n".join(check_rows) or "| _none_ | _none_ | _none_ | _none_ | _none_ | _none_ |"
    estate_rows = (
        "\n".join(
            (
                f"| `{item['name']}` | `{item['component_metadata']['owner']}` | "
                f"`{item['component_metadata']['repository_class']}` | "
                f"`{item['component_metadata']['trust_tier']}` / "
                f"`{item['component_metadata']['recovery_tier']}` | "
                f"`{item['default_branch']['observation']['status']}` | "
                f"`{item['branch_protection']['observation']['status']}` | "
                f"`{item['observed_vs_target_inventory']['status']}` "
                f"({item['observed_vs_target_inventory']['target_authority']['path_count']} "
                "target / "
                f"{item['observed_vs_target_inventory']['observed']['path_count']} observed) |"
            )
            for item in references
        )
        or "| _none_ | _none_ | _none_ | _none_ | _none_ | _none_ | _none_ |"
    )
    canonical = report["canonical_repository"]
    observed_commit = canonical["observed_commit"] or "not commit-bound"
    excluded = canonical["evidence_outputs_excluded"]
    exclusion_text = ", ".join(f"`{path}`" for path in excluded) or "none"
    missing_reference_text = (
        ", ".join(f"`{name}`" for name in report["missing_reference_sources"]) or "none"
    )
    return f"""# Repository drift baseline

This Wave 0 source baseline is generated from repository facts and awaits independent architecture
approval. It does not claim live GitHub, cloud, Kubernetes, or production qualification. Legacy and
operational repositories are inputs for comparison only and are not migration sources.

## Canonical repository

- Anchor commit: `{canonical["anchor_commit"]}`
- Observation scope: `{canonical["observation_scope"]}`
- Base commit: `{canonical["base_commit"]}`
- Observed immutable commit: `{observed_commit}`
- Working tree state: `{canonical["working_tree_state"]}`
- Populated path-set SHA-256: `{canonical["path_set_sha256"]}`
- Content snapshot SHA-256: `{canonical["content_snapshot_sha256"]}`
- Evidence outputs excluded from content snapshot: {exclusion_text}
- Canonical target paths: {summary["canonical_target_paths"]}
- Populated paths: {summary["populated_paths"]}
- Unknown paths: {summary["unknown_paths"]}
- Premature target paths: {summary["premature_paths"]}
- Missing active paths: {summary["missing_active_paths"]}
- Failed or incomplete operational source checks: {summary["source_check_failures"]}
- Operational sources without a check: {summary["source_checks_missing"]}
- Operational metadata failures: {summary["operational_metadata_failures"]}
- Default-branch observations incomplete: {summary["default_branch_observations_incomplete"]}
- Branch-protection observations incomplete: {summary["branch_protection_observations_incomplete"]}
- Appendix A3 inventory failures: {summary["operational_inventory_failures"]}
- Readiness: `{report["readiness"]["label"]}`

The repository Markdown evidence is a worktree-scoped observation and is excluded from its own
content digest. Once committed, CI regenerates the JSON report from that clean commit using commit
scope.

## Reference-only sources

- Required operational sources not observed: {missing_reference_text}

| Source | Immutable revision | Canonical remote | Working tree and evidence scope |
|---|---|---|---|
{rows}

## Operational estate contract

Component metadata is read from each immutable source revision. The default-branch and protection
columns require signed connected observations; a local checkout or desired-state ruleset is never
promoted into live enforcement evidence. Inventory compares immutable Git trees with the exact
Appendix A3 repository trees.

| Source | Owner | Class | Trust / recovery | Default | Protection | A3 tree |
|---|---|---|---|---|---|---|
{estate_rows}

## Source validation observations

These observations retain their actual execution scope. A check on a dirty working tree is not
evidence that the immutable HEAD passed.

| Source | Qualification | Status | Scope | Command | Finding |
|---|---|---|---|---|---|
{checks}

## Greenfield disposition

- Product dependency graph: empty until a later wave activates real product targets.
- Legacy code and history imported: no.
- Migration dispositions: none.
- Existing drift may be refreshed only through architecture review; presubmit rejects new or
  worsened drift.
"""


def _parse_reference(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("reference must be NAME=PATH")
    name, path = value.split("=", 1)
    if not name or not path:
        raise argparse.ArgumentTypeError("reference must be NAME=PATH")
    return name, Path(path)


def _parse_reference_revision(value: str) -> tuple[str, str]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("reference revision must be NAME=SHA")
    name, revision = value.split("=", 1)
    if not name or re.fullmatch(r"[0-9a-f]{40}", revision) is None:
        raise argparse.ArgumentTypeError("reference revision must be NAME=SHA")
    return name, revision


def _parse_reference_check(value: str) -> tuple[str, dict[str, str]]:
    if "=" not in value:
        raise argparse.ArgumentTypeError(
            "reference check must be NAME=STATUS|SCOPE|COMMAND|FINDING"
        )
    name, encoded = value.split("=", 1)
    parts = encoded.split("|", 3)
    if len(parts) != 4 or not name or not all(parts):
        raise argparse.ArgumentTypeError(
            "reference check must be NAME=STATUS|SCOPE|COMMAND|FINDING"
        )
    status, scope, command, finding = parts
    if status not in {"PASS", "FAIL", "BLOCKED", "NOT_RUN"}:
        raise argparse.ArgumentTypeError("reference check status is invalid")
    if scope not in {"immutable-head", "working-tree"}:
        raise argparse.ArgumentTypeError("reference check scope is invalid")
    return name, {"status": status, "scope": scope, "command": command, "finding": finding}


def _parse_reference_receipt(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("reference receipt must be NAME=PATH")
    name, path = value.split("=", 1)
    if not name or not path:
        raise argparse.ArgumentTypeError("reference receipt must be NAME=PATH")
    return name, Path(path)


def _canonical_items(value: object) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {
        json.dumps(item, sort_keys=True, separators=(",", ":"))
        for item in cast(list[object], value)
    }


def find_new_drift_categories(
    report: Mapping[str, object], baseline: Mapping[str, object]
) -> list[str]:
    """Return fact inventories that grew or changed beyond an approved baseline."""

    findings: list[str] = []
    drift_categories = (
        "unknown_paths",
        "premature_paths",
        "missing_active_paths",
        "restricted_artifacts",
        "oversized_files",
    )
    report_drift = _string_mapping(report.get("drift"))
    baseline_drift = _string_mapping(baseline.get("drift"))
    if report_drift is not None and baseline_drift is not None:
        for key in drift_categories:
            if _canonical_items(report_drift.get(key)) - _canonical_items(baseline_drift.get(key)):
                findings.append(f"drift.{key}")

    inventory_fields = (
        "actual_paths",
        "components",
        "dependency_edges",
        "ownership_gaps",
        "contract_authorities",
        "deployables",
        "artifact_release_authorities",
        "duplicate_systems",
        "migration_dispositions",
    )
    for field in inventory_fields:
        if _canonical_items(report.get(field)) - _canonical_items(baseline.get(field)):
            findings.append(field)

    report_boundaries = _string_mapping(report.get("boundaries"))
    baseline_boundaries = _string_mapping(baseline.get("boundaries"))
    if report_boundaries is not None and baseline_boundaries is not None:
        for field in ("generated_paths", "third_party_paths", "research_paths"):
            if _canonical_items(report_boundaries.get(field)) - _canonical_items(
                baseline_boundaries.get(field)
            ):
                findings.append(f"boundaries.{field}")
        if report_boundaries.get("legacy_code_imported") is True and not baseline_boundaries.get(
            "legacy_code_imported"
        ):
            findings.append("boundaries.legacy_code_imported")
        if (
            report_boundaries.get("product_graph_empty") is False
            and baseline_boundaries.get("product_graph_empty") is not False
        ):
            findings.append("boundaries.product_graph_empty")

    def reference_facts(document: Mapping[str, object]) -> dict[str, Mapping[str, object]]:
        references = document.get("reference_sources")
        if not isinstance(references, list):
            return {}
        values: dict[str, Mapping[str, object]] = {}
        for item in cast(list[object], references):
            reference = _string_mapping(item)
            if reference is not None:
                values[str(reference.get("name", ""))] = reference
        return values

    report_references = reference_facts(report)
    baseline_references = reference_facts(baseline)
    if set(report_references) != set(baseline_references):
        findings.append("reference_sources.names")
    reference_fields = (
        "revision",
        "revision_selection",
        "checkout_head",
        "remote",
        "remote_status",
        "component_metadata",
        "default_branch",
        "branch_protection",
        "observed_vs_target_inventory",
        "source_checks",
        "working_tree_state",
        "dirty_state_excluded",
    )
    for name in sorted(set(report_references) & set(baseline_references)):
        for field in reference_fields:
            if report_references[name].get(field) != baseline_references[name].get(field):
                findings.append(f"reference_sources.{field}")
    return sorted(set(findings))


def validate_approved_baseline(
    baseline: Mapping[str, object],
    report: Mapping[str, object],
    schema: Mapping[str, Any],
) -> list[str]:
    """Require an actual commit-bound estate observation, never a synthetic test golden."""

    errors = validate_report_document(baseline, schema)
    readiness = _string_mapping(baseline.get("readiness"))
    wave_zero_baseline = readiness is not None and readiness.get("label") == "WAVE-0"
    repository = _string_mapping(baseline.get("canonical_repository"))
    if repository is None:
        return sorted({*errors, "approved baseline has no canonical repository object"})
    if repository.get("observation_scope") != "commit":
        errors.append("approved baseline must use commit observation scope")
    if repository.get("working_tree_state") != "clean":
        errors.append("approved baseline must observe a clean canonical worktree")
    if repository.get("observed_commit") != repository.get("base_commit"):
        errors.append("approved baseline observed commit must equal its base commit")

    current_repository = _string_mapping(report.get("canonical_repository"))
    if current_repository is not None and repository.get("anchor_commit") != current_repository.get(
        "anchor_commit"
    ):
        errors.append("approved baseline uses a different greenfield anchor")
    if wave_zero_baseline and repository != current_repository:
        errors.append("approved WAVE-0 baseline is not the freshly verified commit observation")
    if baseline.get("target_authority") != report.get("target_authority"):
        errors.append("approved baseline uses a different target authority")
    if wave_zero_baseline and baseline.get("reference_sources") != report.get("reference_sources"):
        errors.append("approved WAVE-0 baseline does not match freshly verified receipts")

    references = baseline.get("reference_sources")
    if not isinstance(references, list):
        errors.append("approved baseline reference sources must be an array")
    else:
        typed_references = cast(list[object], references)
        mapped_references = [
            reference
            for item in typed_references
            if (reference := _string_mapping(item)) is not None
        ]
        names = {str(reference.get("name", "")) for reference in mapped_references}
        if not REQUIRED_OPERATIONAL_REFERENCES.issubset(names):
            errors.append("approved baseline must observe all five operational sources")
        for reference in mapped_references:
            if reference.get("name") in REQUIRED_OPERATIONAL_REFERENCES:
                name = str(reference.get("name"))
                remote = reference.get("remote")
                if remote != CANONICAL_OPERATIONAL_REMOTES[name]:
                    errors.append(
                        f"approved baseline source {name} does not use its canonical remote"
                    )
                if reference.get("remote_status") != "PASS":
                    errors.append(f"approved baseline source {name} remote did not pass")
                if reference.get("revision_selection") != "declared":
                    errors.append(
                        f"approved baseline source {name} must use an explicitly declared revision"
                    )
                component = _string_mapping(reference.get("component_metadata"))
                if component is None or component.get("status") != "PASS":
                    errors.append(f"approved baseline source {name} lacks bound component metadata")
                inventory = _string_mapping(reference.get("observed_vs_target_inventory"))
                if inventory is None or inventory.get("status") != "PASS":
                    errors.append(f"approved baseline source {name} has target inventory drift")
                for field in ("default_branch", "branch_protection"):
                    value = _string_mapping(reference.get(field))
                    observation = (
                        _string_mapping(value.get("observation")) if value is not None else None
                    )
                    if (
                        observation is None
                        or observation.get("status") != "PASS"
                        or observation.get("signature_verification") != "PASS"
                    ):
                        errors.append(
                            f"approved baseline source {name} lacks signed {field} PASS evidence"
                        )
    return sorted(set(errors))


def report_exit_code(report: Mapping[str, object], *, allow_inconclusive: bool) -> int:
    readiness = _string_mapping(report.get("readiness"))
    if readiness is not None and readiness.get("label") == "WAVE-0":
        return 0
    return 0 if allow_inconclusive else 3


# Two lines of the baseline describe the moment it was generated rather than the
# observation it records: the commit HEAD was on, and whether the tree was dirty.
# Committing the file necessarily changes both -- the write happens before the
# commit that contains it, and the tree is dirty at that instant and clean
# afterwards -- so comparing them made the baseline report itself stale forever,
# on any clean checkout, no matter what the observation said. The staleness check
# is about drift in the observation, so it compares everything else exactly.
_GENERATION_MOMENT_FIELDS = ("- Base commit: ", "- Working tree state: ")


def _observation_differs(committed: str, rendered: str) -> bool:
    def observation(text: str) -> list[str]:
        return [
            line for line in text.splitlines() if not line.startswith(_GENERATION_MOMENT_FIELDS)
        ]

    return observation(committed) != observation(rendered)


def write_report_outputs(
    output_json: Path,
    output_markdown: Path,
    json_text: str,
    markdown_text: str,
    *,
    check: bool,
) -> list[str]:
    """Emit the CI JSON artifact and write or verify the reviewed Markdown baseline."""

    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json_text, encoding="utf-8")
    if check:
        if not output_markdown.exists() or _observation_differs(
            output_markdown.read_text(encoding="utf-8"), markdown_text
        ):
            return [str(output_markdown)]
        return []
    output_markdown.parent.mkdir(parents=True, exist_ok=True)
    output_markdown.write_text(markdown_text, encoding="utf-8")
    return []


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--component-schema", type=Path, required=True)
    parser.add_argument("--reference-source", action="append", type=_parse_reference, default=[])
    parser.add_argument(
        "--reference-revision", action="append", type=_parse_reference_revision, default=[]
    )
    parser.add_argument(
        "--reference-check", action="append", type=_parse_reference_check, default=[]
    )
    parser.add_argument(
        "--reference-receipt", action="append", type=_parse_reference_receipt, default=[]
    )
    parser.add_argument("--connected-observation-public-key", type=Path)
    parser.add_argument("--connected-observation-key-version")
    parser.add_argument(
        "--connected-observation-trust-record", action="append", type=Path, default=[]
    )
    parser.add_argument("--approved-baseline", type=Path)
    parser.add_argument(
        "--observation-scope", choices=sorted(OBSERVATION_SCOPES), default="working-tree"
    )
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-markdown", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    parser.add_argument(
        "--allow-inconclusive",
        action="store_true",
        help=(
            "allow an observational INCONCLUSIVE report to exit zero; such an artifact is not "
            "qualifying evidence"
        ),
    )
    args = parser.parse_args(argv)
    reference_checks: dict[str, list[dict[str, str]]] = {}
    for name, check in args.reference_check:
        reference_checks.setdefault(name, []).append(check)
    reference_receipts: dict[str, list[Path]] = {}
    for name, path in args.reference_receipt:
        reference_receipts.setdefault(name, []).append(path)
    reference_revisions: dict[str, str] = {}
    for name, revision in args.reference_revision:
        if name in reference_revisions:
            parser.error(f"duplicate reference revision for {name}")
        reference_revisions[name] = revision
    repository_root = args.repository_root.resolve()
    evidence_outputs: list[str] = []
    for output in (args.output_json, args.output_markdown):
        try:
            evidence_outputs.append(output.resolve().relative_to(repository_root).as_posix())
        except ValueError:
            continue
    report = build_report(
        repository_root,
        args.manifest.resolve(),
        args.component_schema.resolve(),
        args.reference_source,
        reference_checks,
        reference_revisions,
        observation_scope=args.observation_scope,
        excluded_evidence_paths=evidence_outputs,
        reference_receipt_paths=reference_receipts,
        connected_observation_public_key=args.connected_observation_public_key,
        connected_observation_key_version=args.connected_observation_key_version,
        connected_observation_trust_records=args.connected_observation_trust_record,
    )
    json_text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    markdown_text = render_markdown(report)
    stale = write_report_outputs(
        args.output_json,
        args.output_markdown,
        json_text,
        markdown_text,
        check=args.check,
    )
    if args.check and stale:
        print("stale repository drift outputs: " + ", ".join(stale), file=sys.stderr)
        return 1
    if args.approved_baseline:
        baseline_value = json.loads(args.approved_baseline.read_text(encoding="utf-8"))
        if not isinstance(baseline_value, Mapping):
            print("approved baseline must be a JSON object", file=sys.stderr)
            return 2
        baseline = cast(Mapping[str, Any], baseline_value)
        schema = json.loads(
            Path(__file__).with_name("repository_drift.v1.schema.json").read_text(encoding="utf-8")
        )
        baseline_errors = validate_approved_baseline(baseline, report, schema)
        if baseline_errors:
            print("invalid approved baseline:\n" + "\n".join(baseline_errors), file=sys.stderr)
            return 2
        new_drift = find_new_drift_categories(report, baseline)
        if new_drift:
            print(
                "repository drift worsened relative to approved baseline: " + ", ".join(new_drift),
                file=sys.stderr,
            )
            return 2
    print(f"repository drift report: {report['readiness']['label']}")
    exit_code = report_exit_code(report, allow_inconclusive=args.allow_inconclusive)
    if exit_code:
        print(
            "repository drift is INCONCLUSIVE; use --allow-inconclusive only for an "
            "explicitly non-qualifying source observation",
            file=sys.stderr,
        )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
