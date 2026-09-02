#!/usr/bin/env python3.12
"""Emit the exact flat ci-evidence.json contract consumed by organization CI."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Protocol, cast

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError

SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
RAW_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
BUILDKITE_UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
CORRELATION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{7,127}$")
WORKFLOW_PATTERN = re.compile(r"^\.github/workflows/[A-Za-z0-9._-]+\.ya?ml$")
LAUNCHER_IDENTITY_PATTERN = re.compile(r"^buildkite://[a-z0-9][a-z0-9._/-]{7,255}$")
REPOSITORY = "mindclade/mindclade"
ORG_SCHEMA_VERSION = "1.0.0"
OPERATIONAL_REFERENCES = {
    "bootstrap",
    "github-config",
    "gitops",
    "infrastructure-live",
    "organization-workflows",
}
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
    "bootstrap": "mindclade/bootstrap",
    "github-config": "mindclade/github-config",
    "gitops": "mindclade/gitops",
    "infrastructure-live": "mindclade/infrastructure-live",
    "organization-workflows": "mindclade/.github",
}
OPERATIONAL_RULESETS = {
    "bootstrap": "infrastructure-source",
    "github-config": "governance-source",
    "gitops": "deployment-source",
    "infrastructure-live": "infrastructure-source",
    "organization-workflows": "governance-source",
}
OPERATIONAL_TARGET_ROOTS = {
    "bootstrap": "bootstrap",
    "github-config": "github-config",
    "gitops": "gitops",
    "infrastructure-live": "infrastructure-live",
    "organization-workflows": ".github",
}
REPOSITORY_DRIFT_SCHEMA = (
    Path(__file__).resolve().parents[1] / "repo/repository_drift.v1.schema.json"
)


class _SchemaValidator(Protocol):
    def iter_errors(self, instance: object) -> Iterable[ValidationError]: ...


def canonical_json(value: object) -> bytes:
    """Match the pinned organization producer's canonical JSON encoding."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sha256_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return f"sha256:{digest.hexdigest()}"


def read_object(path: Path, description: str) -> dict[str, object]:
    value: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{description} must be a JSON object")
    return cast(dict[str, object], value)


def _required_string(value: Mapping[str, object], field: str) -> str:
    candidate = value.get(field)
    if not isinstance(candidate, str) or not candidate:
        raise ValueError(f"trusted context {field} must be a non-empty string")
    return candidate


def calculate_plan_id(plan: Mapping[str, object]) -> str:
    unsigned = dict(plan)
    unsigned.pop("plan_id", None)
    return sha256_bytes(canonical_json(unsigned))


def validate_plan(
    plan: Mapping[str, object],
    *,
    source_revision: str,
    pipeline_definition_revision: str,
) -> str:
    expected_fields = {
        "schema_version",
        "source_revision",
        "pipeline_definition_revision",
        "pipeline_class",
        "changed_paths",
        "targets",
        "gates",
        "plan_id",
    }
    if set(plan) != expected_fields or plan.get("schema_version") != "pipeline-plan.v1":
        raise ValueError("plan does not satisfy the exact pipeline-plan.v1 contract")
    if plan.get("source_revision") != source_revision:
        raise ValueError("plan source revision does not match trusted context")
    if plan.get("pipeline_definition_revision") != pipeline_definition_revision:
        raise ValueError("plan pipeline revision does not match dispatch")
    for field in ("changed_paths", "targets", "gates"):
        items = plan.get(field)
        if not isinstance(items, list):
            raise ValueError(f"plan {field} must be a string array")
        typed_items = cast(list[object], items)
        if not all(isinstance(item, str) for item in typed_items):
            raise ValueError(f"plan {field} must be a string array")
        if field != "targets" and not typed_items:
            raise ValueError(f"plan {field} must not be empty")
    plan_id = plan.get("plan_id")
    if not isinstance(plan_id, str) or plan_id != calculate_plan_id(plan):
        raise ValueError("plan_id does not bind the exact canonical plan")
    return plan_id


def parse_check(raw: str) -> tuple[str, Path]:
    name, separator, path = raw.partition("=")
    if not separator or not name.strip() or not path.strip():
        raise ValueError("checks must use non-empty NAME=PATH values")
    if len(name.strip()) > 255:
        raise ValueError("check name exceeds the organization contract")
    return name.strip(), Path(path)


def _object_field(value: Mapping[str, object], field: str) -> dict[str, object]:
    candidate = value.get(field)
    if not isinstance(candidate, dict):
        raise ValueError(f"check report {field} must be an object")
    return cast(dict[str, object], candidate)


def _array_field(value: Mapping[str, object], field: str) -> list[object]:
    candidate = value.get(field)
    if not isinstance(candidate, list):
        raise ValueError(f"check report {field} must be an array")
    return cast(list[object], candidate)


def _require_empty_array(value: Mapping[str, object], field: str) -> None:
    if _array_field(value, field):
        raise ValueError(f"check report {field} contains blocking findings")


def _require_raw_sha256(value: object, field: str) -> str:
    if not isinstance(value, str) or not RAW_SHA256_PATTERN.fullmatch(value):
        raise ValueError(f"repository governance {field} is not a canonical SHA-256 digest")
    return value


def _validate_repository_report_contract(report: Mapping[str, object]) -> None:
    """Apply the complete report schema before evaluating qualification semantics."""
    try:
        schema = read_object(REPOSITORY_DRIFT_SCHEMA, "repository governance schema")
        Draft202012Validator.check_schema(schema)
    except (OSError, json.JSONDecodeError, SchemaError, ValueError) as error:
        raise ValueError(f"repository governance schema is invalid: {error}") from error
    validation_errors = sorted(
        cast(_SchemaValidator, Draft202012Validator(schema)).iter_errors(report),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if validation_errors:
        error = validation_errors[0]
        location = "/".join(str(part) for part in error.absolute_path) or "$"
        raise ValueError(
            f"repository governance report violates its full schema at {location}: {error.message}"
        )

    canonical = _object_field(report, "canonical_repository")
    for value, field in (
        (canonical.get("evidence_outputs_excluded"), "evidence outputs"),
        (report.get("actual_paths"), "actual paths"),
        (report.get("missing_reference_sources"), "missing reference sources"),
    ):
        if not isinstance(value, list) or not all(
            isinstance(item, str) for item in cast(list[object], value)
        ):
            raise ValueError(f"repository governance {field} must be a string array")
        items = cast(list[str], value)
        if items != sorted(set(items)):
            raise ValueError(f"repository governance {field} must be sorted and unique")


def _validate_connected_observation(
    observation: Mapping[str, object],
    *,
    name: str,
    revision: str,
    source_revision: str,
    control: str,
    expected_value: str,
    require_main: bool,
) -> None:
    if observation.get("status") != "PASS":
        raise ValueError(f"repository governance source {name} observation is not PASS")
    if observation.get("revision") != revision:
        raise ValueError(f"repository governance source {name} observation is not revision-bound")
    if observation.get("signature_verification") != "PASS":
        raise ValueError(
            f"repository governance source {name} observation lacks a qualified signature"
        )
    _require_raw_sha256(observation.get("evidence_sha256"), f"source {name} evidence")
    source = observation.get("source")
    if source != "cryptographically-verified-receipt":
        raise ValueError(
            f"repository governance source {name} observation lacks connected provenance"
        )
    if require_main and observation.get("observed") != "main":
        raise ValueError(f"repository governance source {name} default branch is not main")
    subject = _object_field(observation, "subject")
    if subject != {
        "repository": OPERATIONAL_PROJECT_SLUGS[name],
        "revision": revision,
        "ref": "refs/heads/main",
        "control": control,
        "expected_value": expected_value,
    }:
        raise ValueError(f"repository governance source {name} receipt subject is not exact")
    verification = _object_field(observation, "verification")
    if verification.get("verifier_source_revision") != source_revision:
        raise ValueError(
            f"repository governance source {name} receipt is not verifier-revision-bound"
        )


def _validate_operational_reference(
    name: str,
    reference: Mapping[str, object],
    *,
    github_config_revision: str,
    source_revision: str,
) -> None:
    revision_value = reference.get("revision")
    if not isinstance(revision_value, str) or not SHA_PATTERN.fullmatch(revision_value):
        raise ValueError(f"repository governance source {name} lacks an immutable revision")
    revision = revision_value
    if (
        reference.get("remote_status") != "PASS"
        or reference.get("remote") != CANONICAL_OPERATIONAL_REMOTES[name]
    ):
        raise ValueError(f"repository governance source {name} lacks its canonical remote")
    if reference.get("dirty_state_excluded") is not True:
        raise ValueError(f"repository governance source {name} includes dirty state")
    if (
        reference.get("revision_selection") != "declared"
        or reference.get("checkout_head") is not None
        or reference.get("working_tree_state") != "excluded"
    ):
        raise ValueError(
            f"repository governance source {name} is not isolated from volatile checkout state"
        )

    component = _object_field(reference, "component_metadata")
    if (
        component.get("status") != "PASS"
        or component.get("path") != "component.yaml"
        or component.get("revision") != revision
        or component.get("metadata_name") != OPERATIONAL_COMPONENT_NAMES[name]
        or component.get("project_slug") != OPERATIONAL_PROJECT_SLUGS[name]
    ):
        raise ValueError(
            f"repository governance source {name} component metadata is not identity-bound"
        )
    _require_raw_sha256(component.get("content_sha256"), f"source {name} component metadata")
    release = _object_field(component, "release")
    if release.get("immutable") is not True:
        raise ValueError(f"repository governance source {name} release is not immutable")

    default_branch = _object_field(reference, "default_branch")
    if default_branch.get("target") != "main":
        raise ValueError(f"repository governance source {name} default-branch target is not main")
    _validate_connected_observation(
        _object_field(default_branch, "observation"),
        name=name,
        revision=revision,
        source_revision=source_revision,
        control="default_branch",
        expected_value="main",
        require_main=True,
    )

    branch_protection = _object_field(reference, "branch_protection")
    protection_target = _object_field(branch_protection, "target")
    ruleset = OPERATIONAL_RULESETS[name]
    if (
        protection_target.get("ref") != "refs/heads/main"
        or protection_target.get("ruleset") != ruleset
        or protection_target.get("policy_path") != f"config/rulesets/{ruleset}.yaml"
        or protection_target.get("policy_revision") != github_config_revision
    ):
        raise ValueError(
            f"repository governance source {name} protection target is not policy-bound"
        )
    _require_raw_sha256(
        protection_target.get("policy_content_sha256"), f"source {name} protection policy"
    )
    _validate_connected_observation(
        _object_field(branch_protection, "observation"),
        name=name,
        revision=revision,
        source_revision=source_revision,
        control="branch_protection",
        expected_value=ruleset,
        require_main=False,
    )

    inventory = _object_field(reference, "observed_vs_target_inventory")
    if inventory.get("status") != "PASS":
        raise ValueError(f"repository governance source {name} inventory is not PASS")
    for field in ("missing_paths", "extra_paths", "conflicts", "dispositions"):
        _require_empty_array(inventory, field)
    observed = _object_field(inventory, "observed")
    target = _object_field(inventory, "target_authority")
    if observed.get("revision") != revision:
        raise ValueError(f"repository governance source {name} inventory is not revision-bound")
    if (
        target.get("path")
        != "docs/architecture/blueprint/appendices/A03-repository-estate-and-trust-boundaries.md"
        or target.get("root") != OPERATIONAL_TARGET_ROOTS[name]
        or observed.get("path_count") != target.get("path_count")
        or observed.get("path_set_sha256") != target.get("path_set_sha256")
    ):
        raise ValueError(
            f"repository governance source {name} inventory does not match its target authority"
        )
    _require_raw_sha256(target.get("content_sha256"), f"source {name} inventory authority")
    _require_raw_sha256(target.get("path_set_sha256"), f"source {name} target inventory")
    _require_raw_sha256(observed.get("path_set_sha256"), f"source {name} observed inventory")

    checks = _array_field(reference, "source_checks")
    if not checks:
        raise ValueError(f"repository governance source {name} has no source check")
    for raw_check in checks:
        if not isinstance(raw_check, dict):
            raise ValueError(f"repository governance source {name} check must be an object")
        check = cast(dict[str, object], raw_check)
        if (
            check.get("qualification") != "VERIFIED"
            or check.get("status") != "PASS"
            or check.get("scope") != "immutable-head"
        ):
            raise ValueError(
                f"repository governance source {name} lacks a verified immutable-head PASS"
            )
        _require_raw_sha256(check.get("evidence_sha256"), f"source {name} check evidence")
        command = check.get("command")
        subject = _object_field(check, "subject")
        if subject != {
            "repository": OPERATIONAL_PROJECT_SLUGS[name],
            "revision": revision,
            "check": command,
        }:
            raise ValueError(f"repository governance source {name} check subject is not exact")
        verification = _object_field(check, "verification")
        if verification.get("verifier_source_revision") != source_revision:
            raise ValueError(
                f"repository governance source {name} check is not verifier-revision-bound"
            )


def validate_repository_governance(path: Path, source_revision: str) -> None:
    report = read_object(path, "repository governance report")
    _validate_repository_report_contract(report)
    if report.get("schema_version") != "repository_drift.v1":
        raise ValueError("repository governance report has the wrong schema")
    readiness = _object_field(report, "readiness")
    if readiness.get("label") != "WAVE-0":
        raise ValueError("repository governance report is not WAVE-0 ready")
    canonical = _object_field(report, "canonical_repository")
    if (
        canonical.get("observation_scope") != "commit"
        or canonical.get("base_commit") != source_revision
        or canonical.get("observed_commit") != source_revision
        or canonical.get("working_tree_state") != "clean"
    ):
        raise ValueError("repository governance report is not bound to the clean source commit")

    summary = _object_field(report, "summary")
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
        if summary.get(field) != 0:
            raise ValueError(f"repository governance report has nonzero {field}")
    drift = _object_field(report, "drift")
    for field in (
        "missing_active_paths",
        "oversized_files",
        "premature_paths",
        "restricted_artifacts",
        "unknown_paths",
    ):
        _require_empty_array(drift, field)
    for field in ("duplicate_systems", "missing_reference_sources", "ownership_gaps"):
        _require_empty_array(report, field)

    references = _array_field(report, "reference_sources")
    by_name: dict[str, Mapping[str, object]] = {}
    for raw_reference in references:
        if not isinstance(raw_reference, dict):
            raise ValueError("repository governance reference must be an object")
        reference = cast(dict[str, object], raw_reference)
        name = reference.get("name")
        if not isinstance(name, str) or name in by_name:
            raise ValueError("repository governance references must have unique string names")
        by_name[name] = reference
    if set(by_name) != OPERATIONAL_REFERENCES:
        raise ValueError("repository governance report lacks the exact five operational sources")
    github_config_revision_value = by_name["github-config"].get("revision")
    if not isinstance(github_config_revision_value, str) or not SHA_PATTERN.fullmatch(
        github_config_revision_value
    ):
        raise ValueError("repository governance github-config source lacks an immutable revision")
    for name, reference in by_name.items():
        _validate_operational_reference(
            name,
            reference,
            github_config_revision=github_config_revision_value,
            source_revision=source_revision,
        )


def _validate_launcher_observation(
    path: Path,
    *,
    source_revision: str,
    pipeline_definition_revision: str,
    build_id: str,
    context: Mapping[str, object],
) -> None:
    report = read_object(path, "immutable launcher observation")
    expected_fields = {
        "schema_version",
        "qualification",
        "external_signature_required",
        "source_revision",
        "pipeline_definition_revision",
        "launcher_revision",
        "launcher_digest",
        "launcher_identity",
        "definition_tree_digest",
        "build_id",
    }
    if set(report) != expected_fields:
        raise ValueError("immutable launcher observation contains missing or unknown fields")
    if (
        report.get("schema_version") != "immutable-launcher-observation.v1"
        or report.get("qualification") != "UNSIGNED_OBSERVATION_INPUT"
        or report.get("external_signature_required") is not True
    ):
        raise ValueError("immutable launcher observation falsely claims qualification")
    expected = {
        "source_revision": source_revision,
        "pipeline_definition_revision": pipeline_definition_revision,
        "build_id": build_id,
        "launcher_revision": context.get("launcher_revision"),
        "launcher_digest": context.get("launcher_digest"),
        "launcher_identity": context.get("launcher_identity"),
    }
    for field, value in expected.items():
        if report.get(field) != value:
            raise ValueError(f"immutable launcher observation {field} is not caller-bound")
    if not SHA_PATTERN.fullmatch(_required_string(report, "launcher_revision")):
        raise ValueError("immutable launcher revision is not a full lowercase Git SHA")
    for field in ("launcher_digest", "definition_tree_digest"):
        if not DIGEST_PATTERN.fullmatch(_required_string(report, field)):
            raise ValueError(f"immutable launcher {field} is not a canonical digest")
    if not LAUNCHER_IDENTITY_PATTERN.fullmatch(_required_string(report, "launcher_identity")):
        raise ValueError("immutable launcher identity is not canonical")


def _validate_cache_boundary(
    path: Path,
    *,
    source_revision: str,
    pipeline_class: str,
    context: Mapping[str, object],
) -> None:
    report = read_object(path, "cache boundary")
    v1_fields = {
        "schema_version",
        "qualification",
        "source_revision",
        "cache_mode",
        "cache_used",
        "cache_outputs_are_evidence",
        "public_cache_target_allowlist",
        "namespace",
        "iam_qualification_digest",
        "write_activation_digest",
        "cacheless_canary",
        "poison_recovery",
    }
    if report.get("schema_version") == "cache-boundary.v1":
        if context.get("cache_namespace_epoch") != "disabled-v1":
            raise ValueError("cache boundary v1 requires the disabled-v1 namespace")
        if set(report) != v1_fields:
            raise ValueError("cache boundary v1 contains missing or unknown fields")
        if (
            report.get("qualification") != "UNSIGNED_OBSERVATION_INPUT"
            or report.get("source_revision") != source_revision
            or report.get("cache_mode") != "disabled"
            or report.get("cache_used") is not False
            or report.get("cache_outputs_are_evidence") is not False
            or report.get("public_cache_target_allowlist") != []
            or report.get("iam_qualification_digest") is not None
            or report.get("write_activation_digest") is not None
        ):
            raise ValueError("cache boundary v1 activates or treats cache state as evidence")
        namespace = _object_field(report, "namespace")
        if namespace != {
            "schema_version": "cache-namespace.v1",
            "classification": context.get("cache_classification"),
            "namespace_epoch": context.get("cache_namespace_epoch"),
            "trust_class": context.get("source_trust"),
            "platform": context.get("cache_platform"),
            "architecture": context.get("cache_architecture"),
            "toolchain_digest": context.get("cache_toolchain_digest"),
            "build_mode": pipeline_class,
        }:
            raise ValueError("cache namespace v1 is not bound to the exact trusted context")
        canary = _object_field(report, "cacheless_canary")
        if canary != {
            "required": pipeline_class in {"protected", "nightly"},
            "targets": ["//:wave1_tests"],
            "remote_cache_read": False,
            "remote_cache_write": False,
        }:
            raise ValueError("cacheless reproducibility plan v1 is incomplete")
        if report.get("poison_recovery") != [
            "revoke-affected-namespace",
            "rebuild-with-cache-disabled",
            "compare-clean-output-digests",
            "require-reviewed-reactivation-evidence",
        ]:
            raise ValueError("cache poison-recovery plan v1 is incomplete")
        return
    expected_fields = v1_fields | {
        "endpoint",
        "signer_public_key_digest",
        "audit_sink_digest",
    }
    if set(report) != expected_fields:
        raise ValueError("cache boundary contains missing or unknown fields")
    if report.get("schema_version") != "cache-boundary.v2":
        raise ValueError("cache boundary schema is unsupported")
    mode = report.get("cache_mode")
    qualification = report.get("qualification")
    if (
        report.get("source_revision") != source_revision
        or mode not in {"disabled", "read", "write"}
        or report.get("cache_used") != (mode != "disabled")
        or report.get("cache_outputs_are_evidence") is not False
        or report.get("public_cache_target_allowlist") != []
    ):
        raise ValueError("cache boundary v2 contains inconsistent cache state")
    digest_fields = (
        "iam_qualification_digest",
        "signer_public_key_digest",
        "audit_sink_digest",
    )
    if mode == "disabled":
        if context.get("cache_namespace_epoch") != "disabled-v2":
            raise ValueError("disabled cache v2 requires the disabled-v2 namespace")
        if qualification != "DISABLED" or report.get("endpoint") is not None:
            raise ValueError("disabled cache v2 claims qualification or an endpoint")
        if any(
            report.get(field) is not None for field in (*digest_fields, "write_activation_digest")
        ):
            raise ValueError("disabled cache v2 carries activation evidence")
    else:
        endpoint = report.get("endpoint")
        if not isinstance(endpoint, str) or not re.fullmatch(
            r"https://[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?", endpoint
        ):
            raise ValueError("active cache endpoint is not canonical HTTPS")
        for field in digest_fields:
            if not DIGEST_PATTERN.fullmatch(_required_string(report, field)):
                raise ValueError(f"active cache {field} is not canonical")
        if mode == "read":
            if (
                qualification != "IAM_QUALIFIED"
                or report.get("write_activation_digest") is not None
            ):
                raise ValueError("read cache has invalid qualification")
        elif (
            qualification != "WRITE_ACTIVATED"
            or not DIGEST_PATTERN.fullmatch(_required_string(report, "write_activation_digest"))
            or context.get("source_trust") != "protected"
            or pipeline_class not in {"protected", "nightly"}
        ):
            raise ValueError("write cache lacks protected activation evidence")
    namespace = _object_field(report, "namespace")
    if context.get("cache_build_mode") != pipeline_class:
        raise ValueError("cache build mode does not match the dispatched pipeline class")
    expected_namespace = {
        "schema_version": "cache-namespace.v2",
        "classification": context.get("cache_classification"),
        "namespace_epoch": context.get("cache_namespace_epoch"),
        "trust_class": context.get("source_trust"),
        "system": f"{context.get('cache_architecture')}-{context.get('cache_platform')}",
        "toolchain_digest": context.get("cache_toolchain_digest"),
        "build_mode": pipeline_class,
    }
    if namespace != expected_namespace:
        raise ValueError("cache namespace is not bound to the exact trusted context")
    if not DIGEST_PATTERN.fullmatch(_required_string(namespace, "toolchain_digest")):
        raise ValueError("cache namespace toolchain digest is not canonical")
    canary = _object_field(report, "cacheless_canary")
    if canary != {
        "required": pipeline_class in {"protected", "nightly"},
        "targets": ["//:wave1_tests"],
        "remote_cache_read": False,
        "remote_cache_write": False,
    }:
        raise ValueError("cacheless reproducibility plan is incomplete")
    if report.get("poison_recovery") != [
        "revoke-affected-namespace",
        "rebuild-with-cache-disabled",
        "compare-clean-output-digests",
        "require-reviewed-reactivation-evidence",
    ]:
        raise ValueError("cache poison-recovery plan is incomplete")


def _validate_source_gate(
    path: Path,
    *,
    source_revision: str,
    schema_version: str,
    target: str,
) -> None:
    report = read_object(path, schema_version)
    if report != {
        "schema_version": schema_version,
        "source_revision": source_revision,
        "target": target,
        "conclusion": "PASS",
    }:
        raise ValueError(f"{schema_version} is not an exact revision-bound PASS receipt")


def _validate_license_inventory(path: Path) -> None:
    report = read_object(path, "license inventory")
    if (
        report.get("schema_version") != "license-inventory.v1"
        or report.get("scope") != "resolved-wave0-repository-build-inputs"
    ):
        raise ValueError("license inventory has the wrong contract")
    _require_empty_array(report, "violations")
    if not _array_field(report, "records"):
        raise ValueError("license inventory has no resolved records")
    coverage = _array_field(report, "coverage")
    authorities: set[str] = set()
    for raw in coverage:
        if not isinstance(raw, dict):
            continue
        record = cast(dict[str, object], raw)
        authority = record.get("authority")
        if isinstance(authority, str):
            authorities.add(authority)
    if authorities != {
        "Cargo.lock",
        "MODULE.bazel.lock",
        "flake.lock",
        "go.sum",
        "pnpm-lock.yaml",
        "uv.lock",
    }:
        raise ValueError("license inventory does not cover every Wave 0 dependency authority")


def _validate_secret_scan(path: Path) -> None:
    value: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list) or value:
        raise ValueError("secret scan report is not an empty finding array")


def validate_bazel_receipt(path: Path, context: Mapping[str, object]) -> None:
    report = read_object(path, "Bazel native agreement report")
    if report == {
        "conclusion": "PASS",
        "schema_version": "bazel-native-agreement.v1",
    }:
        if context.get("cache_mode") != "disabled":
            raise ValueError("Bazel native agreement v1 cannot authorize active cache use")
        return
    expected_fields = {
        "schema_version",
        "conclusion",
        "repository",
        "system",
        "nix_toolchain_digest",
        "bazel_resolution_digest",
        "toolchains",
        "agreement_digest",
    }
    if set(report) != expected_fields:
        raise ValueError("Bazel native agreement v2 contains missing or unknown fields")
    if (
        report.get("schema_version") != "bazel-native-agreement.v2"
        or report.get("conclusion") != "PASS"
        or report.get("repository") != REPOSITORY
    ):
        raise ValueError("Bazel native agreement v2 identity is invalid")
    expected_system = f"{context.get('cache_architecture')}-{context.get('cache_platform')}"
    if report.get("system") != expected_system:
        raise ValueError("Bazel native agreement system does not match trusted context")
    if report.get("nix_toolchain_digest") != context.get("cache_toolchain_digest"):
        raise ValueError("Bazel native agreement toolchain does not match trusted context")
    for field in ("nix_toolchain_digest", "bazel_resolution_digest", "agreement_digest"):
        if not DIGEST_PATTERN.fullmatch(_required_string(report, field)):
            raise ValueError(f"Bazel native agreement {field} is not canonical")
    unsigned = {key: value for key, value in report.items() if key != "agreement_digest"}
    if sha256_bytes(canonical_json(unsigned)) != report["agreement_digest"]:
        raise ValueError("Bazel native agreement digest does not bind canonical content")
    toolchains = _array_field(report, "toolchains")
    required = {
        "bazel",
        "cargo",
        "cc",
        "cxx",
        "go",
        "java",
        "just",
        "nix",
        "node",
        "node_runtime",
        "pnpm",
        "python",
        "rustc",
        "rustdoc",
    }
    expected_toolchain_fields = {
        "label",
        "name",
        "observation",
        "observed_path",
        "observed_provider_path",
        "observed_provider_realpath",
        "observed_sha256",
        "observed_store_path",
        "provider_version",
        "toolchain_type",
    }
    names: list[str] = []
    for raw in toolchains:
        if not isinstance(raw, dict):
            raise ValueError("Bazel native agreement toolchain must be an object")
        item = cast(dict[str, object], raw)
        if set(item) != expected_toolchain_fields:
            raise ValueError("Bazel native agreement toolchain fields are not exact")
        name = _required_string(item, "name")
        names.append(name)
        observed_path = _required_string(item, "observed_path")
        observed_store_path = _required_string(item, "observed_store_path")
        if not observed_path.startswith("/nix/store/"):
            raise ValueError(f"Bazel toolchain {name} executable is not Nix-backed")
        if not observed_store_path.startswith("/nix/store/"):
            raise ValueError(f"Bazel toolchain {name} store path is not Nix-backed")
        if not observed_path.startswith(observed_store_path.rstrip("/") + "/"):
            raise ValueError(f"Bazel toolchain {name} executable escapes its store path")
        if not DIGEST_PATTERN.fullmatch(_required_string(item, "observed_sha256")):
            raise ValueError(f"Bazel toolchain {name} digest is not canonical")
        _required_string(item, "label")
        _required_string(item, "observation")
        _required_string(item, "observed_provider_path")
        _required_string(item, "observed_provider_realpath")
        _required_string(item, "toolchain_type")
        provider_version = item.get("provider_version")
        if not isinstance(provider_version, str):
            raise ValueError(f"Bazel toolchain {name} provider version is not a string")
    if names != sorted(required):
        raise ValueError("Bazel native agreement v2 toolchain set is incomplete or unordered")


def _validate_fresh_database_integration(path: Path, source_revision: str) -> None:
    report = read_object(path, "fresh-database integration receipt")
    receipt_digest = report.pop("receipt_digest", None)
    expected_targets = {
        "//services/control_plane:artifacts_server_test",
        "//services/control_plane:control_plane_test",
        "//services/control_plane:jobs_server_test",
        "//services/control_plane/internal/admin:admin_test",
        "//services/control_plane/internal/agents:agents_test",
        "//services/control_plane/internal/datasets:datasets_test",
        "//services/control_plane/internal/evaluations:evaluations_test",
        "//services/control_plane/internal/experiments:experiments_test",
        "//services/control_plane/internal/inference:inference_test",
        "//services/control_plane/internal/models:models_test",
        "//services/control_plane/internal/platform/eventprojection:event_projection_test",
        "//services/control_plane/internal/policies:policies_test",
        "//services/control_plane/internal/training:training_test",
        "//services/control_plane/internal/workflows:workflows_test",
    }
    targets = report.get("required_bazel_targets")
    lifecycle = report.get("database_lifecycle")
    qualification = report.get("qualification")
    canonical_with_newline = canonical_json(report) + b"\n"
    if (
        report.get("schema_version") != "mindclade.fresh-database-integration/v1"
        or report.get("source_revision") != source_revision
        or report.get("status") != "passed"
        or report.get("ratification_authorized") is not False
        or not isinstance(targets, list)
        or set(cast(list[object], targets)) != expected_targets
        or len(cast(list[object], targets)) != len(expected_targets)
        or lifecycle != {"complete_down_up": "passed", "empty_to_all_up": "passed"}
        or qualification
        != {
            "every_domain_repository": "passed",
            "reliability_and_dlq": "passed",
            "required_postgres_mode": True,
            "rls_tenant_isolation": "passed",
            "skipped_required_tests": [],
            "training_ownership_and_fencing": "passed",
        }
        or not isinstance(report.get("migration_set_digest"), str)
        or not DIGEST_PATTERN.fullmatch(cast(str, report["migration_set_digest"]))
        or not isinstance(receipt_digest, str)
        or receipt_digest != sha256_bytes(canonical_with_newline)
    ):
        raise ValueError("fresh-database integration receipt is incomplete or not exact")


def validate_check_report(
    name: str,
    path: Path,
    source_revision: str,
    *,
    pipeline_definition_revision: str,
    pipeline_class: str,
    build_id: str,
    context: Mapping[str, object],
) -> None:
    if name == "repository-governance":
        validate_repository_governance(path, source_revision)
    elif name == "dependency-and-license-policy":
        _validate_license_inventory(path)
    elif name == "secret-scan":
        _validate_secret_scan(path)
    elif name == "bazel-native-agreement":
        validate_bazel_receipt(path, context)
    elif name == "fresh-database-integration":
        _validate_fresh_database_integration(path, source_revision)
    elif name == "immutable-launcher":
        _validate_launcher_observation(
            path,
            source_revision=source_revision,
            pipeline_definition_revision=pipeline_definition_revision,
            build_id=build_id,
            context=context,
        )
    elif name == "cache-boundary":
        _validate_cache_boundary(
            path,
            source_revision=source_revision,
            pipeline_class=pipeline_class,
            context=context,
        )
    elif name == "source-check":
        _validate_source_gate(
            path,
            source_revision=source_revision,
            schema_version="source-check.v1",
            target="just check",
        )
    elif name == "wave1-full":
        _validate_source_gate(
            path,
            source_revision=source_revision,
            schema_version="wave1-full.v1",
            target="//:wave1_tests",
        )
    elif name == "cacheless-reproducibility":
        report = read_object(path, "cacheless-reproducibility.v1")
        first = report.get("first_output_digest")
        second = report.get("second_output_digest")
        if (
            report
            != {
                "cache_mode": "disabled",
                "conclusion": "PASS",
                "first_output_digest": first,
                "independent_output_roots": True,
                "reproducibility_subject": "//services/control_plane:control_plane_test",
                "schema_version": "cacheless-reproducibility.v1",
                "second_output_digest": second,
                "source_revision": source_revision,
                "target": "//:wave1_tests",
            }
            or not isinstance(first, str)
            or not DIGEST_PATTERN.fullmatch(first)
            or first != second
        ):
            raise ValueError("cacheless canary lacks matching independent output digests")
    elif name == "authoritative-integration-readiness":
        report = read_object(path, "mindclade.authoritative-integration-readiness/v2")
        if report.get("schema_version") != "mindclade.authoritative-integration-readiness/v2":
            raise ValueError("authoritative integration readiness report has the wrong schema")
        # This report is an inventory of evidence state, not a stage-completion
        # signal, so PASS here must never be derived from criterion statuses.
        for raw_criterion in _array_field(report, "criteria"):
            if not isinstance(raw_criterion, dict):
                raise ValueError("authoritative integration readiness criterion must be an object")
            status = cast(dict[str, object], raw_criterion).get("status")
            if not isinstance(status, str) or not status:
                raise ValueError(
                    "authoritative integration readiness criterion is missing a status"
                )
    else:
        raise ValueError(f"unsupported planned check: {name}")


def _parse_timestamp(raw: str, field: str) -> datetime:
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{field} must be an RFC 3339 timestamp") from error
    if value.tzinfo is None:
        raise ValueError(f"{field} must include a UTC offset")
    return value


def validate_trusted_context(
    context: Mapping[str, object],
    *,
    context_digest: str,
    pipeline_definition_revision: str,
) -> None:
    required = {
        "correlation_id",
        "source_revision",
        "base_revision",
        "repository",
        "workflow_ref",
        "workflow_revision",
        "source_trust",
        "execution_tier",
        "pipeline_definition_revision",
        "launcher_revision",
        "launcher_digest",
        "launcher_identity",
        "cache_mode",
        "cache_platform",
        "cache_architecture",
        "cache_toolchain_digest",
        "cache_build_mode",
        "pipeline_class",
        "cache_classification",
        "cache_namespace_epoch",
    }
    if set(context) != required:
        raise ValueError("trusted context contains missing or unknown fields")
    source_revision = _required_string(context, "source_revision")
    workflow_revision = _required_string(context, "workflow_revision")
    correlation_id = _required_string(context, "correlation_id")
    if not SHA_PATTERN.fullmatch(source_revision) or not SHA_PATTERN.fullmatch(workflow_revision):
        raise ValueError("trusted context revisions must be full lowercase Git SHAs")
    base_revision = context.get("base_revision")
    if base_revision is not None and (
        not isinstance(base_revision, str) or not SHA_PATTERN.fullmatch(base_revision)
    ):
        raise ValueError("trusted context base_revision must be null or a full Git SHA")
    if context.get("repository") != REPOSITORY:
        raise ValueError(f"trusted context repository must be {REPOSITORY}")
    if not WORKFLOW_PATTERN.fullmatch(_required_string(context, "workflow_ref")):
        raise ValueError("trusted context workflow_ref is invalid")
    if not CORRELATION_PATTERN.fullmatch(correlation_id):
        raise ValueError("trusted context correlation_id is invalid")
    if not SHA_PATTERN.fullmatch(pipeline_definition_revision):
        raise ValueError("pipeline definition revision must be one full lowercase Git SHA")
    if context.get("pipeline_definition_revision") != pipeline_definition_revision:
        raise ValueError("trusted context pipeline definition revision does not match dispatch")
    if not SHA_PATTERN.fullmatch(_required_string(context, "launcher_revision")):
        raise ValueError("trusted context launcher revision must be a full lowercase Git SHA")
    if not DIGEST_PATTERN.fullmatch(_required_string(context, "launcher_digest")):
        raise ValueError("trusted context launcher digest must be canonical")
    if not LAUNCHER_IDENTITY_PATTERN.fullmatch(_required_string(context, "launcher_identity")):
        raise ValueError("trusted context launcher identity must be canonical")
    if context.get("cache_mode") != "disabled":
        raise ValueError("trusted context cannot activate an unqualified remote cache")
    if context.get("cache_build_mode") not in {
        "presubmit",
        "protected",
        "nightly",
        "gpu",
        "release",
        "security",
    }:
        raise ValueError("trusted context cache build mode is not allowlisted")
    if context.get("pipeline_class") != context.get("cache_build_mode"):
        raise ValueError("trusted context pipeline and cache build modes differ")
    expected_tier = {
        "presubmit": "untrusted",
        "protected": "trusted",
        "nightly": "trusted",
        "gpu": "trusted",
        "release": "release",
        "security": "trusted",
    }[cast(str, context.get("pipeline_class"))]
    if context.get("execution_tier") != expected_tier:
        raise ValueError("trusted context pipeline class has the wrong execution tier")
    if context.get("cache_classification") != "private-internal":
        raise ValueError("trusted context public cache is not activated")
    if context.get("cache_namespace_epoch") not in {"disabled-v1", "disabled-v2"}:
        raise ValueError("trusted context cache namespace epoch is not activated")
    for field in ("cache_platform", "cache_architecture"):
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{1,63}", _required_string(context, field)):
            raise ValueError(f"trusted context {field} is not canonical")
    if not DIGEST_PATTERN.fullmatch(_required_string(context, "cache_toolchain_digest")):
        raise ValueError("trusted context cache toolchain digest is not canonical")
    if not DIGEST_PATTERN.fullmatch(context_digest):
        raise ValueError("context digest must be a canonical SHA-256 digest")
    if sha256_bytes(canonical_json(context)) != context_digest:
        raise ValueError("context digest does not bind the exact trusted context")
    source_trust = _required_string(context, "source_trust")
    execution_tier = _required_string(context, "execution_tier")
    if source_trust not in {"untrusted", "trusted", "protected"}:
        raise ValueError("trusted context source_trust is not allowlisted")
    if execution_tier not in {"untrusted", "trusted", "release"}:
        raise ValueError("trusted context execution_tier is not allowlisted")
    if execution_tier == "untrusted" and source_trust not in {
        "untrusted",
        "trusted",
        "protected",
    }:
        raise ValueError("untrusted execution has inconsistent source trust")
    if execution_tier in {"trusted", "release"} and source_trust != "protected":
        raise ValueError("privileged execution requires protected source trust")


def build_evidence(args: argparse.Namespace) -> dict[str, object]:
    context = read_object(args.context, "trusted context")
    validate_trusted_context(
        context,
        context_digest=args.context_digest,
        pipeline_definition_revision=args.pipeline_definition_revision,
    )
    source_revision = _required_string(context, "source_revision")
    plan = read_object(args.plan, "pipeline plan")
    pipeline_class = _required_string(plan, "pipeline_class")
    if context.get("pipeline_class") != pipeline_class:
        raise ValueError("trusted context pipeline class does not match the plan")
    plan_id = validate_plan(
        plan,
        source_revision=source_revision,
        pipeline_definition_revision=args.pipeline_definition_revision,
    )
    if not BUILDKITE_UUID_PATTERN.fullmatch(args.build_id):
        raise ValueError("build-id must be a canonical lowercase Buildkite UUID")

    started_at = _parse_timestamp(args.started_at, "started-at")
    completed_at = _parse_timestamp(args.completed_at, "completed-at")
    if completed_at < started_at:
        raise ValueError("completed-at precedes started-at")

    raw_gates = plan.get("gates")
    if not isinstance(raw_gates, list):
        raise ValueError("plan gates must be a string array")
    untyped_gates = cast(list[object], raw_gates)
    if not all(isinstance(gate, str) for gate in untyped_gates):
        raise ValueError("plan gates must be a string array")
    planned_gates = cast(list[str], untyped_gates)
    if len(planned_gates) != len(set(planned_gates)):
        raise ValueError("plan gates must be unique")

    checks: list[dict[str, object]] = [
        {
            "name": "pipeline-plan",
            "conclusion": "PASS",
            "report_digest": sha256_path(args.plan),
        }
    ]
    names = {"pipeline-plan"}
    for raw in args.check:
        name, path = parse_check(raw)
        if name in names:
            raise ValueError(f"duplicate check name: {name}")
        if not path.is_file():
            raise ValueError(f"check report does not exist: {path}")
        validate_check_report(
            name,
            path,
            source_revision,
            pipeline_definition_revision=args.pipeline_definition_revision,
            pipeline_class=pipeline_class,
            build_id=args.build_id,
            context=context,
        )
        names.add(name)
        checks.append({"name": name, "conclusion": "PASS", "report_digest": sha256_path(path)})

    if names - {"pipeline-plan"} != set(planned_gates):
        raise ValueError("provided check reports do not match the exact planned gate set")

    return {
        "schema_version": ORG_SCHEMA_VERSION,
        "correlation_id": _required_string(context, "correlation_id"),
        "source_revision": source_revision,
        "base_revision": context.get("base_revision"),
        "context_digest": args.context_digest,
        "caller_repository": REPOSITORY,
        "workflow_ref": _required_string(context, "workflow_ref"),
        "workflow_revision": _required_string(context, "workflow_revision"),
        "pipeline_definition_revision": args.pipeline_definition_revision,
        "producer": "buildkite",
        "plan_id": plan_id,
        "build_id": args.build_id,
        "conclusion": "PASS",
        "reason_code": "BUILDKITE_SUCCEEDED",
        "checks": checks,
        "started_at": args.started_at,
        "completed_at": args.completed_at,
    }


def atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        Path(temporary_name).replace(path)
    except BaseException:
        Path(temporary_name).unlink(missing_ok=True)
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--context", type=Path, required=True)
    parser.add_argument("--context-digest", required=True)
    parser.add_argument("--pipeline-definition-revision", required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--build-id", required=True)
    parser.add_argument("--started-at", required=True)
    parser.add_argument("--completed-at", required=True)
    parser.add_argument("--check", action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--digest-output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        evidence = build_evidence(args)
        canonical = canonical_json(evidence)
        atomic_write(args.output, canonical + b"\n")
        digest = (sha256_bytes(canonical) + "\n").encode()
        if args.digest_output:
            atomic_write(args.digest_output, digest)
        else:
            sys.stdout.buffer.write(digest)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"evidence bundle failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
