#!/usr/bin/env python3.12
"""Build a fail-closed report from the governed integration-criterion map."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from training_evidence_assembler import (
    GOVERNED_SIGNER_TRUST_POLICY,
    RECEIPT_CONTRACTS,
    AttestedArtifact,
    SignerTrustPolicy,
    receipt_signer_trust_activated,
    validate_assembled_evidence_payload,
    validate_receipt_internal_consistency,
    verify_receipt_attestation,
)

type JsonScalar = bool | float | int | str | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]
type JsonObject = dict[str, JsonValue]

CHECKBOX_RE = re.compile(r"^- \[(?P<checked>[ x])\] (?P<text>.+)$")
QUEUE_RE = re.compile(r"^(?P<number>[0-9]+)\. (?P<text>.+)$")
BAZEL_TARGET_RE = re.compile(r"^//(?P<package>[A-Za-z0-9_./-]*):(?P<target>[A-Za-z0-9_.+-]+)$")
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
SCHEMA_VERSION_RE = re.compile(r"^mindclade\.[a-z0-9.-]+/v[1-9][0-9]*$")
CRITERION_ID_RE = re.compile(
    r"^(?:adapted-execution-checklist|stages-and-exit-criteria|completion-work-queue)-[0-9]{2}$"
)
OWNER_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")
QUALIFICATION_CLASSES = frozenset({"source", "protected", "connected", "scientific"})
KNOWN_OWNERS = frozenset(
    {
        "agent-platform",
        "architecture",
        "computational-biology",
        "contract-governance",
        "data-platform",
        "developer-experience",
        "developer-platform",
        "evaluation-science",
        "inference-systems",
        "ml-systems-performance",
        "model-architecture",
        "platform-control-plane",
        "platform-operations",
        "product-engineering",
        "research",
        "security",
        "training-systems",
    }
)
CRITERION_MAP_SCHEMA = "mindclade.authoritative-integration-criterion-map/v1"
READINESS_SCHEMA = "mindclade.authoritative-integration-readiness/v3"
REHEARSAL_SCHEMA = "mindclade.training-vertical-rehearsal/v1"
TRAINING_EVIDENCE_SCHEMA = "mindclade.training-vertical-evidence/v2"
DEFAULT_MAPPING_PATH = Path(__file__).with_name("authoritative-integration-criteria.v1.json")
REHEARSAL_FIELDS = frozenset(
    {"bindings", "checks", "ratification", "receipt_digest", "schema_version", "status"}
)
REHEARSAL_BINDING_FIELDS = frozenset(
    {
        "candidate_artifact_digest",
        "candidate_descriptor_digest",
        "codegen_toolchain_digest",
        "event_registry_digest",
        "event_registry_source_digest",
        "fresh_database_integration_receipt_digest",
        "generated_manifest_digest",
        "grpc_implementation_digest",
        "migration_set_digest",
        "openapi_projection_digest",
        "sdk_package_digests",
        "sdk_rpc_coverage_digest",
        "source_revision",
        "source_tree_digest",
    }
)
REHEARSAL_CHECK_TARGETS = {
    "cross_language": "//:all_contract_tests",
    "database": "//services/control_plane:control_plane_test",
    "event": "//services/control_plane/internal/platform/eventprojection:event_projection_test",
    "gateway": "//services/control_plane:control_plane_grpc_registration_test",
    "grpc": "//services/control_plane:control_plane_grpc_registration_test",
    "sdk": "//:all_contract_tests",
}
# Qualification is a four-step proof: the receipt exists at its declared path, its
# `receipt_digest` recomputes over its canonical content, its `result_artifact_path`
# is a repository-owned file whose digest matches `result_artifact_digest`, and a
# signer key authorized by repository-owned policy signed those exact bytes. The
# first three steps are enforced fail-closed by the governed receipt validators, so
# reaching any state below means they held. Only the fourth step distinguishes them.
QUALIFICATION_NO_RECEIPT = "no-receipt"
# The receipt contract carries no result artifact, so this report cannot obtain
# execution proof from it. Source rehearsal assertions and the unsigned assembled
# Stage 5 payload both land here; neither is a protected qualification.
QUALIFICATION_EXECUTION_PROOF_UNAVAILABLE = "execution-proof-unavailable"
# Evidence is present and internally consistent, but connected authority has not
# activated any signer key for this lane, so no signature can verify yet. This is
# strictly weaker than verification and never contributes to completion.
QUALIFICATION_SIGNATURE_PENDING = "signature-pending-connected-authority"
# Signer trust is activated but no detached attestation was supplied.
QUALIFICATION_SIGNATURE_UNATTESTED = "signature-unattested"
QUALIFICATION_VERIFIED = "verified"
QUALIFICATION_STATES = frozenset(
    {
        QUALIFICATION_NO_RECEIPT,
        QUALIFICATION_EXECUTION_PROOF_UNAVAILABLE,
        QUALIFICATION_SIGNATURE_PENDING,
        QUALIFICATION_SIGNATURE_UNATTESTED,
        QUALIFICATION_VERIFIED,
    }
)
SIGNATURE_PENDING_STATUS = "evidence-consistent-signature-pending"


@dataclass(frozen=True)
class ValidatedReceipt:
    digest: str
    payload: JsonObject
    bound_targets: frozenset[str]
    verification_class: str
    qualification_state: str
    execution_proof: bool
    signer_key_id: str | None


@dataclass(frozen=True)
class ReceiptInputs:
    """Everything one governed receipt verifier may consider, and nothing else."""

    name: str
    path: Path
    encoded: bytes
    payload: JsonObject
    expected_revision: str
    root: Path
    attestation: AttestedArtifact | None
    trust_policy: SignerTrustPolicy


def canonical_json(value: JsonValue) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def digest_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def load_object(path: Path) -> JsonObject:
    value: object = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain one JSON object")
    raw = cast(dict[object, object], value)
    if any(not isinstance(key, str) for key in raw):
        raise ValueError(f"{path} must contain one JSON object")
    return cast(JsonObject, value)


def plan_criteria(source: str) -> list[tuple[str, bool, str]]:
    """Extract the three governed criterion collections from the plan."""

    criteria: list[tuple[str, bool, str]] = []
    current_id = ""
    current_checked = False
    current_text: list[str] = []
    section = ""

    def finish() -> None:
        nonlocal current_id, current_text
        if current_id:
            criteria.append((current_id, current_checked, " ".join(current_text)))
        current_id, current_text = "", []

    counters: dict[str, int] = {}
    for line in source.splitlines():
        if line.startswith("## "):
            finish()
            section = line.removeprefix("## ").strip().lower().replace(" ", "-")
            continue
        checkbox = CHECKBOX_RE.fullmatch(line)
        queued = QUEUE_RE.fullmatch(line) if section == "completion-work-queue" else None
        if checkbox is not None or queued is not None:
            finish()
            if checkbox is not None:
                counters[section] = counters.get(section, 0) + 1
                current_id = f"{section}-{counters[section]:02d}"
                current_checked = checkbox.group("checked") == "x"
                current_text = [checkbox.group("text")]
            else:
                assert queued is not None
                current_id = f"completion-work-queue-{int(queued.group('number')):02d}"
                current_checked = False
                current_text = [queued.group("text")]
            continue
        if current_id and (line.startswith("  ") or line.strip() == ""):
            if line.strip():
                current_text.append(line.strip())
            continue
        if current_id:
            finish()
    finish()
    return criteria


def _string(value: JsonValue, label: str, pattern: re.Pattern[str] | None = None) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a non-empty string")
    if pattern is not None and pattern.fullmatch(value) is None:
        raise ValueError(f"{label} has an invalid value: {value!r}")
    return value


def _string_list(
    value: JsonValue,
    label: str,
    *,
    nonempty: bool = False,
    pattern: re.Pattern[str] | None = None,
) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{label} must be a string array")
    result = cast(list[str], value)
    if nonempty and not result:
        raise ValueError(f"{label} must not be empty")
    if result != sorted(set(result)):
        raise ValueError(f"{label} must be sorted and unique")
    if pattern is not None:
        for item in result:
            if pattern.fullmatch(item) is None:
                raise ValueError(f"{label} contains an invalid value: {item!r}")
    return result


def _target_exists(root: Path, label: str) -> bool:
    match = BAZEL_TARGET_RE.fullmatch(label)
    if match is None:
        return False
    package = match.group("package")
    build_root = root / package if package else root
    build_file = next(
        (path for path in (build_root / "BUILD.bazel", build_root / "BUILD") if path.is_file()),
        None,
    )
    if build_file is None:
        return False
    target = re.escape(match.group("target"))
    return (
        re.search(
            rf"\bname\s*=\s*['\"]{target}['\"]",
            build_file.read_text(encoding="utf-8"),
        )
        is not None
    )


def load_criterion_map(
    mapping_path: Path,
    plan: Sequence[tuple[str, bool, str]],
    root: Path,
) -> dict[str, JsonObject]:
    """Validate the exact criterion map and every declared Bazel label."""

    mapping = load_object(mapping_path)
    if set(mapping) != {"criteria", "schema_version"}:
        raise ValueError("criterion map fields must be exactly criteria and schema_version")
    if mapping.get("schema_version") != CRITERION_MAP_SCHEMA:
        raise ValueError("criterion map has an unsupported schema_version")
    raw_entries = mapping.get("criteria")
    if not isinstance(raw_entries, list):
        raise ValueError("criterion map criteria must be an array")

    entries: dict[str, JsonObject] = {}
    expected_fields = {
        "bazel_targets",
        "criterion",
        "criterion_id",
        "dependencies",
        "owner",
        "qualification_class",
        "receipt_name",
        "receipt_schema_version",
        "required_digests",
        "stage",
    }
    for index, raw in enumerate(raw_entries):
        if not isinstance(raw, dict):
            raise ValueError(f"criterion map entry {index} must be an object")
        entry = cast(JsonObject, raw)
        if set(entry) != expected_fields:
            raise ValueError(f"criterion map entry {index} fields differ from the contract")
        criterion_id = _string(
            entry.get("criterion_id"), f"criterion map entry {index} id", CRITERION_ID_RE
        )
        if criterion_id in entries:
            raise ValueError(f"duplicate criterion mapping: {criterion_id}")
        _string(entry.get("criterion"), f"criterion {criterion_id} text")
        _string(entry.get("stage"), f"criterion {criterion_id} stage")
        owner = _string(entry.get("owner"), f"criterion {criterion_id} owner", OWNER_RE)
        if owner not in KNOWN_OWNERS:
            raise ValueError(f"criterion {criterion_id} has unknown manifest owner: {owner}")
        qualification_class = _string(
            entry.get("qualification_class"),
            f"criterion {criterion_id} qualification_class",
        )
        if qualification_class not in QUALIFICATION_CLASSES:
            raise ValueError(
                f"criterion {criterion_id} has invalid qualification_class: {qualification_class}"
            )
        _string(entry.get("receipt_name"), f"criterion {criterion_id} receipt_name")
        _string(
            entry.get("receipt_schema_version"),
            f"criterion {criterion_id} receipt_schema_version",
            SCHEMA_VERSION_RE,
        )
        targets = _string_list(
            entry.get("bazel_targets"),
            f"criterion {criterion_id} bazel_targets",
            nonempty=True,
            pattern=BAZEL_TARGET_RE,
        )
        missing_targets = [target for target in targets if not _target_exists(root, target)]
        if missing_targets:
            raise ValueError(
                f"criterion {criterion_id} declares missing Bazel targets: {missing_targets}"
            )
        _string_list(
            entry.get("required_digests"),
            f"criterion {criterion_id} required_digests",
            nonempty=True,
        )
        _string_list(entry.get("dependencies"), f"criterion {criterion_id} dependencies")
        entries[criterion_id] = entry

    plan_by_id = {criterion_id: text for criterion_id, _, text in plan}
    if len(plan_by_id) != len(plan):
        raise ValueError("the authoritative plan contains duplicate criterion IDs")
    if set(entries) != set(plan_by_id):
        raise ValueError(
            "criterion map does not exactly cover the authoritative plan: "
            f"unmapped={sorted(set(plan_by_id) - set(entries))}, "
            f"obsolete={sorted(set(entries) - set(plan_by_id))}"
        )
    for criterion_id, text in plan_by_id.items():
        if entries[criterion_id].get("criterion") != text:
            raise ValueError(f"criterion mapping is stale for {criterion_id}")
    for criterion_id, entry in entries.items():
        dependencies = cast(list[str], entry["dependencies"])
        unknown = sorted(set(dependencies) - set(entries))
        if unknown:
            raise ValueError(f"criterion {criterion_id} has unknown dependencies: {unknown}")
        if criterion_id in dependencies:
            raise ValueError(f"criterion {criterion_id} depends on itself")
    _validate_dependency_cycles(entries)
    return entries


def _validate_dependency_cycles(entries: Mapping[str, JsonObject]) -> None:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(criterion_id: str) -> None:
        if criterion_id in visiting:
            raise ValueError(f"criterion dependency cycle contains {criterion_id}")
        if criterion_id in visited:
            return
        visiting.add(criterion_id)
        dependencies = cast(list[str], entries[criterion_id]["dependencies"])
        for dependency in dependencies:
            visit(dependency)
        visiting.remove(criterion_id)
        visited.add(criterion_id)

    for criterion_id in sorted(entries):
        visit(criterion_id)


def _receipt_bindings(receipt: JsonObject) -> JsonObject:
    if receipt.get("schema_version") == TRAINING_EVIDENCE_SCHEMA:
        return {
            key: value
            for key, value in receipt.items()
            if key not in {"checks", "schema_version", "status"}
        }
    bindings = receipt.get("bindings")
    if isinstance(bindings, dict):
        return cast(JsonObject, bindings)
    return receipt


def _validate_receipt_digest(receipt: JsonObject, path: Path) -> str:
    receipt_digest = receipt.get("receipt_digest")
    if receipt_digest is None:
        return digest_bytes(path.read_bytes())
    if not isinstance(receipt_digest, str) or DIGEST_RE.fullmatch(receipt_digest) is None:
        raise ValueError(f"{path} receipt_digest is not canonical")
    unsigned = dict(receipt)
    unsigned.pop("receipt_digest")
    if receipt_digest != digest_bytes(canonical_json(cast(JsonValue, unsigned))):
        raise ValueError(f"{path} receipt_digest does not bind its canonical content")
    return receipt_digest


def _validate_required_bindings(
    receipt: JsonObject,
    path: Path,
    required_digests: Sequence[str],
) -> None:
    bindings = _receipt_bindings(receipt)
    for name in required_digests:
        value = bindings.get(name)
        if name == "sdk_package_digests":
            if not isinstance(value, dict) or set(value) != {
                "go",
                "python",
                "rust",
                "typescript",
            }:
                raise ValueError(f"{path} has an incomplete sdk_package_digests binding")
            for language, digest in value.items():
                if not isinstance(digest, str) or DIGEST_RE.fullmatch(digest) is None:
                    raise ValueError(f"{path} has invalid {language} SDK digest")
        elif not isinstance(value, str) or DIGEST_RE.fullmatch(value) is None:
            raise ValueError(f"{path} is missing canonical digest binding {name}")


def _validate_rehearsal(inputs: ReceiptInputs) -> ValidatedReceipt:
    path = inputs.path
    receipt = inputs.payload
    expected_revision = inputs.expected_revision
    if set(receipt) != set(REHEARSAL_FIELDS):
        raise ValueError(f"{path} fields differ from the exact rehearsal contract")
    if receipt.get("status") != "passed":
        raise ValueError(f"{path} is not passed")
    ratification = receipt.get("ratification")
    if (
        not isinstance(ratification, dict)
        or set(ratification) != {"authorized", "reason"}
        or ratification.get("authorized") is not False
        or not isinstance(ratification.get("reason"), str)
        or not ratification.get("reason")
    ):
        raise ValueError(f"{path} is not explicitly and exactly non-ratifying")

    raw_bindings = receipt.get("bindings")
    if not isinstance(raw_bindings, dict) or set(raw_bindings) != set(REHEARSAL_BINDING_FIELDS):
        raise ValueError(f"{path} rehearsal bindings differ from the producer contract")
    bindings = cast(JsonObject, raw_bindings)
    if bindings.get("source_revision") != expected_revision:
        raise ValueError(f"{path} is stale or bound to a different source revision")
    _validate_required_bindings(
        receipt,
        path,
        sorted(REHEARSAL_BINDING_FIELDS - {"source_revision"}),
    )

    raw_checks = receipt.get("checks")
    if not isinstance(raw_checks, dict) or set(raw_checks) != set(REHEARSAL_CHECK_TARGETS):
        raise ValueError(f"{path} rehearsal checks differ from the exact six-check contract")
    checks = cast(JsonObject, raw_checks)
    bound_targets: set[str] = set()
    for name, expected_target in sorted(REHEARSAL_CHECK_TARGETS.items()):
        raw_check = checks[name]
        if (
            not isinstance(raw_check, dict)
            or set(raw_check) != {"bazel_target", "status"}
            or raw_check.get("status") != "passed"
            or raw_check.get("bazel_target") != expected_target
        ):
            raise ValueError(f"{path} rehearsal check {name} differs from policy")
        bound_targets.add(expected_target)
    if path.read_bytes() != canonical_json(receipt):
        raise ValueError(f"{path} is not canonical JSON")
    return ValidatedReceipt(
        digest=_validate_receipt_digest(receipt, path),
        payload=receipt,
        bound_targets=frozenset(bound_targets),
        # `training_rehearsal.py` records caller-provided passed-check assertions;
        # it is not a BEP/result-artifact verifier and cannot prove execution.
        verification_class="source-assertion-validated",
        qualification_state=QUALIFICATION_EXECUTION_PROOF_UNAVAILABLE,
        execution_proof=False,
        signer_key_id=None,
    )


def _validate_training_payload(inputs: ReceiptInputs) -> ValidatedReceipt:
    bound_targets = validate_assembled_evidence_payload(
        inputs.payload,
        expected_source_revision=inputs.expected_revision,
        encoded=inputs.encoded,
    )
    return ValidatedReceipt(
        digest=digest_bytes(inputs.encoded),
        payload=inputs.payload,
        bound_targets=bound_targets,
        # The detached signature and ratification authority are deliberately not
        # inputs to this source-readiness report. A valid payload is not a
        # protected qualification by itself, and its per-lane result artifacts are
        # referenced by digest only, so this report cannot re-prove execution.
        verification_class="protected-payload-unverified",
        qualification_state=QUALIFICATION_EXECUTION_PROOF_UNAVAILABLE,
        execution_proof=False,
        signer_key_id=None,
    )


def _receipt_signature_state(inputs: ReceiptInputs) -> tuple[str, str | None]:
    """Resolve step four: does a repository-authorized key sign these exact bytes?"""

    if not receipt_signer_trust_activated(inputs.name, inputs.trust_policy):
        # Zero signer keys are authorized until connected authority activates them
        # in reviewed protected source. Supplying attestation material cannot change
        # that, so the receipt is consistent evidence and nothing more.
        return QUALIFICATION_SIGNATURE_PENDING, None
    if inputs.attestation is None:
        return QUALIFICATION_SIGNATURE_UNATTESTED, None
    # A supplied attestation that fails to verify is an integrity violation, not a
    # reportable state: `verify_receipt_attestation` raises and the report fails closed.
    attestation = verify_receipt_attestation(
        inputs.name,
        inputs.attestation,
        payload=inputs.encoded,
        trust_policy=inputs.trust_policy,
    )
    return QUALIFICATION_VERIFIED, attestation.key_id


def _validate_qualification_receipt(inputs: ReceiptInputs) -> ValidatedReceipt:
    consistent = validate_receipt_internal_consistency(
        inputs.name,
        inputs.encoded,
        inputs.path,
        root=inputs.root,
        trusted_source_revision=inputs.expected_revision,
    )
    qualification_state, signer_key_id = _receipt_signature_state(inputs)
    return ValidatedReceipt(
        digest=consistent.receipt_digest,
        payload=inputs.payload,
        bound_targets=consistent.required_targets,
        # The receipt binds its own canonical content and an existing result artifact
        # of the exact declared digest. That proves execution was recorded; it does
        # not prove who recorded it, which is what the signature step is for.
        verification_class="protected-receipt-result-verified",
        qualification_state=qualification_state,
        execution_proof=True,
        signer_key_id=signer_key_id,
    )


type ReceiptVerifier = Callable[[ReceiptInputs], ValidatedReceipt]
RECEIPT_VERIFIERS: Mapping[tuple[str, str], ReceiptVerifier] = {
    ("training_rehearsal", REHEARSAL_SCHEMA): _validate_rehearsal,
    ("training_vertical", TRAINING_EVIDENCE_SCHEMA): _validate_training_payload,
    **{
        (name, contract.schema_version): _validate_qualification_receipt
        for name, contract in RECEIPT_CONTRACTS.items()
    },
}


def validate_receipt(
    path: Path,
    *,
    receipt_name: str,
    expected_schema: str,
    expected_revision: str,
    required_digests: Sequence[str],
    root: Path,
    attestation: AttestedArtifact | None = None,
    trust_policy: SignerTrustPolicy = GOVERNED_SIGNER_TRUST_POLICY,
) -> ValidatedReceipt:
    # Step one: the receipt must exist at its declared path as a regular file.
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{path} is not an existing regular receipt file")
    if attestation is not None and receipt_name not in RECEIPT_CONTRACTS:
        raise ValueError(f"no governed receipt signer is registered for {receipt_name}")
    receipt = load_object(path)
    if receipt.get("schema_version") != expected_schema:
        raise ValueError(f"{path} schema_version is not the required {expected_schema}")
    verifier = RECEIPT_VERIFIERS.get((receipt_name, expected_schema))
    if verifier is None:
        raise ValueError(
            f"no governed receipt verifier is registered for {receipt_name} ({expected_schema})"
        )
    validated = verifier(
        ReceiptInputs(
            name=receipt_name,
            path=path,
            encoded=path.read_bytes(),
            payload=receipt,
            expected_revision=expected_revision,
            root=root,
            attestation=attestation,
            trust_policy=trust_policy,
        )
    )
    if validated.qualification_state not in QUALIFICATION_STATES:
        raise ValueError(f"{path} produced an ungoverned qualification state")
    _validate_required_bindings(validated.payload, path, required_digests)
    return validated


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
        raise ValueError("Git did not return an exact lowercase source revision")
    return revision


def parse_receipt(value: str) -> tuple[str, Path]:
    name, separator, path = value.partition("=")
    if not separator or not name or not path:
        raise argparse.ArgumentTypeError("receipts must use NAME=PATH")
    return name, Path(path)


def _receipt_attestations(
    receipt_paths: Mapping[str, Path],
    signature_paths: Mapping[str, Path],
    public_key_paths: Mapping[str, Path],
) -> dict[str, AttestedArtifact]:
    if set(signature_paths) != set(public_key_paths):
        raise ValueError("receipt signatures and public keys must be declared in exact pairs")
    undeclared = sorted(set(signature_paths) - set(receipt_paths))
    if undeclared:
        raise ValueError(f"receipt attestations name undeclared receipts: {undeclared}")
    return {
        name: AttestedArtifact(
            payload_path=receipt_paths[name],
            signature_envelope_path=signature_paths[name],
            public_key_path=public_key_paths[name],
        )
        for name in sorted(signature_paths)
    }


def build_report(
    plan_path: Path,
    rehearsal_path: Path,
    *,
    mapping_path: Path = DEFAULT_MAPPING_PATH,
    root: Path | None = None,
    receipt_paths: Mapping[str, Path] | None = None,
    receipt_signature_paths: Mapping[str, Path] | None = None,
    receipt_public_key_paths: Mapping[str, Path] | None = None,
    expected_source_revision: str | None = None,
    # Repository-owned signer trust is the default and the only trust the command
    # line can select. The parameter exists so isolated tests can prove the verified
    # path without waiting on connected authority to activate a real key.
    trust_policy: SignerTrustPolicy = GOVERNED_SIGNER_TRUST_POLICY,
) -> JsonObject:
    root = (root or plan_path.resolve().parents[2]).resolve()
    plan_source = plan_path.read_text(encoding="utf-8")
    criteria = plan_criteria(plan_source)
    if len(criteria) < 30:
        raise ValueError(f"readiness plan extraction is incomplete: only {len(criteria)} criteria")
    entries = load_criterion_map(mapping_path, criteria, root)
    checked_out_revision = _git_revision(root)
    if expected_source_revision is not None and expected_source_revision != checked_out_revision:
        raise ValueError("expected source revision does not match checked-out HEAD")
    expected_revision = checked_out_revision
    if REVISION_RE.fullmatch(expected_revision) is None:
        raise ValueError("expected source revision must be an exact lowercase Git revision")

    paths = dict(receipt_paths or {})
    if "training_rehearsal" in paths and paths["training_rehearsal"] != rehearsal_path:
        raise ValueError("training_rehearsal receipt was provided twice with different paths")
    paths["training_rehearsal"] = rehearsal_path
    used_receipts = {cast(str, entry["receipt_name"]) for entry in entries.values()}
    unexpected_receipts = sorted(set(paths) - used_receipts)
    if unexpected_receipts:
        raise ValueError(f"readiness receipts are not mapped to criteria: {unexpected_receipts}")
    attestations = _receipt_attestations(
        paths,
        dict(receipt_signature_paths or {}),
        dict(receipt_public_key_paths or {}),
    )

    validated: dict[tuple[str, str, tuple[str, ...]], ValidatedReceipt] = {}
    evidence_by_id: dict[str, dict[str, object]] = {}
    for criterion_id, checked, text in criteria:
        entry = entries[criterion_id]
        receipt_name = cast(str, entry["receipt_name"])
        expected_schema = cast(str, entry["receipt_schema_version"])
        required_digests = cast(list[str], entry["required_digests"])
        receipt_path = paths.get(receipt_name)
        evidence_present = receipt_path is not None
        validated_receipt: ValidatedReceipt | None = None
        if receipt_path is not None:
            key = (receipt_name, expected_schema, tuple(required_digests))
            if key not in validated:
                validated[key] = validate_receipt(
                    receipt_path,
                    receipt_name=receipt_name,
                    expected_schema=expected_schema,
                    expected_revision=expected_revision,
                    required_digests=required_digests,
                    root=root,
                    attestation=attestations.get(receipt_name),
                    trust_policy=trust_policy,
                )
            validated_receipt = validated[key]
        targets = cast(list[str], entry["bazel_targets"])
        bound_targets: frozenset[str] = (
            validated_receipt.bound_targets if validated_receipt is not None else frozenset()
        )
        target_binding_validated = set(targets).issubset(bound_targets)
        qualification_class = cast(str, entry["qualification_class"])
        verification_class = (
            validated_receipt.verification_class if validated_receipt is not None else None
        )
        qualification_state = (
            validated_receipt.qualification_state
            if validated_receipt is not None
            else QUALIFICATION_NO_RECEIPT
        )
        # Qualification is exactly the four-step receipt proof, and its last step is a
        # signature by a key that repository-owned policy authorizes. Source rehearsal
        # assertions and unsigned protected payloads never reach it.
        qualification_verified = qualification_state == QUALIFICATION_VERIFIED
        evidence_verified = (
            validated_receipt is not None and target_binding_validated and qualification_verified
        )
        evidence_by_id[criterion_id] = {
            "checked": checked,
            "criterion": text,
            "evidence_present": evidence_present,
            "evidence_verified": evidence_verified,
            "qualification_class": qualification_class,
            "qualification_state": qualification_state,
            "qualification_verified": qualification_verified,
            "receipt": validated_receipt,
            "target_binding_validated": target_binding_validated,
            "verification_class": verification_class,
        }

    completion_by_id: dict[str, bool] = {}

    def completion_verified(criterion_id: str) -> bool:
        if criterion_id in completion_by_id:
            return completion_by_id[criterion_id]
        state = evidence_by_id[criterion_id]
        documentary_check_required = not criterion_id.startswith("completion-work-queue-")
        documentary_complete = bool(state["checked"]) or not documentary_check_required
        dependencies = cast(list[str], entries[criterion_id]["dependencies"])
        complete = (
            bool(state["evidence_verified"])
            and documentary_complete
            and all(completion_verified(dependency) for dependency in dependencies)
        )
        completion_by_id[criterion_id] = complete
        return complete

    for criterion_id in entries:
        completion_verified(criterion_id)

    records: list[JsonValue] = []
    summary: dict[str, int] = {}
    for criterion_id, checked, text in criteria:
        entry = entries[criterion_id]
        state = evidence_by_id[criterion_id]
        validated_receipt = cast(ValidatedReceipt | None, state["receipt"])
        dependencies = cast(list[str], entry["dependencies"])
        required_digests = cast(list[str], entry["required_digests"])
        incomplete_dependencies = [
            dependency for dependency in dependencies if not completion_by_id[dependency]
        ]
        qualification_class = cast(str, state["qualification_class"])
        qualification_state = cast(str, state["qualification_state"])
        evidence_present = bool(state["evidence_present"])
        evidence_verified = bool(state["evidence_verified"])
        target_binding_validated = bool(state["target_binding_validated"])
        if completion_by_id[criterion_id]:
            status = "completion-verified"
        elif qualification_state == QUALIFICATION_SIGNATURE_PENDING and target_binding_validated:
            # Distinct from both "no evidence" and "verified": the receipt exists,
            # recomputes, binds its result artifact, and covers this criterion's
            # targets, but no signer key is activated yet. Completion still requires
            # the trusted signature, so this branch can never imply completion.
            status = SIGNATURE_PENDING_STATUS
        elif qualification_class == "protected":
            status = "pending-protected-qualification"
        elif qualification_class == "connected":
            status = "pending-connected-qualification"
        elif qualification_class == "scientific":
            status = "pending-scientific-qualification"
        elif evidence_present and not target_binding_validated:
            status = "receipt-target-binding-incomplete"
        elif evidence_present and not evidence_verified:
            status = "receipt-validated-execution-unverified"
        elif checked and not evidence_verified:
            status = "plan-checked-evidence-unverified"
        elif not evidence_present:
            status = "candidate-evidence-incomplete"
        elif incomplete_dependencies:
            status = "blocked-by-evidence-dependency"
        else:
            status = "evidence-verified-plan-unchecked"
        summary[status] = summary.get(status, 0) + 1
        records.append(
            cast(
                JsonValue,
                {
                    "bazel_targets": entry["bazel_targets"],
                    "criterion": text,
                    "criterion_id": criterion_id,
                    "completion_verified": completion_by_id[criterion_id],
                    "dependencies": dependencies,
                    "documentary_check_required": not criterion_id.startswith(
                        "completion-work-queue-"
                    ),
                    "evidence_verified": evidence_verified,
                    "incomplete_dependencies": incomplete_dependencies,
                    "owner": entry["owner"],
                    "plan_checked": checked,
                    "qualification_class": qualification_class,
                    "qualification_state": qualification_state,
                    "qualification_verified": bool(state["qualification_verified"]),
                    "receipt": {
                        "digest": (
                            validated_receipt.digest if validated_receipt is not None else None
                        ),
                        "name": entry["receipt_name"],
                        "execution_proof_available": (
                            validated_receipt is not None and validated_receipt.execution_proof
                        ),
                        "present": evidence_present,
                        "producer_available": entry["receipt_name"] == "training_rehearsal",
                        "bound_bazel_targets": (
                            sorted(validated_receipt.bound_targets)
                            if validated_receipt is not None
                            else []
                        ),
                        "schema_version": entry["receipt_schema_version"],
                        "signature_verified": qualification_state == QUALIFICATION_VERIFIED,
                        "signer_key_id": (
                            validated_receipt.signer_key_id
                            if validated_receipt is not None
                            else None
                        ),
                        "validated": validated_receipt is not None,
                        "verification_class": state["verification_class"],
                    },
                    "required_digests": required_digests,
                    "stage": entry["stage"],
                    "status": status,
                    "target_binding_validated": target_binding_validated,
                },
            )
        )
    summary_json: JsonObject = {key: summary[key] for key in sorted(summary)}
    report: JsonObject = {
        "criteria": records,
        "criterion_map_digest": digest_bytes(mapping_path.read_bytes()),
        "plan_digest": digest_bytes(plan_source.encode()),
        "ratification_authorized": False,
        "schema_version": READINESS_SCHEMA,
        # False while connected authority has activated no signer key, which is why
        # every internally consistent receipt reports only as signature-pending.
        "signer_trust_activated": any(
            receipt_signer_trust_activated(name, trust_policy) for name in sorted(RECEIPT_CONTRACTS)
        ),
        "source_revision": expected_revision,
        "summary": summary_json,
    }
    report["report_digest"] = digest_bytes(canonical_json(report))
    return report


def atomic_write(path: Path, value: JsonObject) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=path.parent, prefix=f".{path.name}.", delete=False
    ) as handle:
        temporary = Path(handle.name)
        handle.write(canonical_json(value))
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--criterion-map", type=Path, default=DEFAULT_MAPPING_PATH)
    parser.add_argument("--rehearsal", type=Path, required=True)
    parser.add_argument("--receipt", action="append", type=parse_receipt, default=[])
    parser.add_argument("--receipt-signature", action="append", type=parse_receipt, default=[])
    parser.add_argument("--receipt-public-key", action="append", type=parse_receipt, default=[])
    parser.add_argument("--expected-source-revision")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    def exact_named_paths(raw_values: list[tuple[str, Path]], label: str) -> dict[str, Path]:
        values = dict(raw_values)
        if len(values) != len(raw_values):
            raise SystemExit(f"readiness report failed: duplicate {label} name")
        return values

    receipts = exact_named_paths(cast(list[tuple[str, Path]], args.receipt), "receipt")
    signatures = exact_named_paths(
        cast(list[tuple[str, Path]], args.receipt_signature), "receipt signature"
    )
    public_keys = exact_named_paths(
        cast(list[tuple[str, Path]], args.receipt_public_key), "receipt public key"
    )
    try:
        report = build_report(
            cast(Path, args.plan),
            cast(Path, args.rehearsal),
            mapping_path=cast(Path, args.criterion_map),
            root=cast(Path, args.root),
            receipt_paths=receipts,
            receipt_signature_paths=signatures,
            receipt_public_key_paths=public_keys,
            expected_source_revision=cast(str | None, args.expected_source_revision),
        )
        atomic_write(cast(Path, args.output), report)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        raise SystemExit(f"readiness report failed: {error}") from error
    print(cast(Path, args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
