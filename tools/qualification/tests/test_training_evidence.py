"""Regression tests for rehearsal, readiness, and protected Stage 5 evidence."""

from __future__ import annotations

import base64
import json
import subprocess
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from readiness_report import (
    REHEARSAL_CHECK_TARGETS,
    build_report,
    digest_bytes,
    plan_criteria,
)
from readiness_report import (
    JsonValue as ReadinessJsonValue,
)
from readiness_report import canonical_json as readiness_canonical_json
from training_evidence_assembler import (
    APPROVAL_PAYLOAD_TYPE,
    EVIDENCE_SCHEMA,
    PROTECTED_CONTEXT_PAYLOAD_TYPE,
    PROTECTED_CONTEXT_PRODUCER_IDENTITY,
    RATIFICATION_BINDING_FIELDS,
    RECEIPT_CONTRACTS,
    AttestedArtifact,
    JsonObject,
    SignerTrustPolicy,
    _assemble_evidence,  # pyright: ignore[reportPrivateUsage] - isolated trust fixture seam
    assemble_evidence,
    dsse_pae,
    receipt_payload_type,
    signed_payload_json,
    validate_assembled_evidence_payload,
)
from training_evidence_assembler import (
    JsonValue as AssemblerJsonValue,
)
from training_evidence_assembler import (
    canonical_json as assembler_canonical_json,
)
from training_evidence_assembler import (
    sha256_bytes as assembler_sha256_bytes,
)
from training_rehearsal import (
    POSTGRES_TARGETS,
    build_integration_receipt,
    build_receipt,
    canonical_json,
    sha256_bytes,
)

SOURCE_REVISION = "a" * 40
ALL_BINDINGS: dict[str, object] = {
    "candidate_descriptor_digest": "sha256:" + "1" * 64,
    "codegen_toolchain_digest": "sha256:" + "2" * 64,
    "event_registry_digest": "sha256:" + "3" * 64,
    "generated_manifest_digest": "sha256:" + "4" * 64,
    "grpc_implementation_digest": "sha256:" + "5" * 64,
    "migration_set_digest": "sha256:" + "6" * 64,
    "openapi_projection_digest": "sha256:" + "7" * 64,
    "sdk_package_digests": {
        "go": "sha256:" + "8" * 64,
        "python": "sha256:" + "9" * 64,
        "rust": "sha256:" + "a" * 64,
        "typescript": "sha256:" + "b" * 64,
    },
    "sdk_rpc_coverage_digest": "sha256:" + "c" * 64,
    "source_revision": SOURCE_REVISION,
}


def _repository_data() -> tuple[Path, Path, Path]:
    qualification = Path(__file__).resolve().parents[1]
    root = qualification.parents[1]
    return (
        root,
        root / "docs/architecture/authoritative-contract-integration-plan.md",
        qualification / "authoritative-integration-criteria.v1.json",
    )


def _git_revision(root: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _write_rehearsal(path: Path, *, revision: str) -> None:
    bindings = {
        **ALL_BINDINGS,
        "candidate_artifact_digest": "sha256:" + "d" * 64,
        "event_registry_source_digest": "sha256:" + "e" * 64,
        "fresh_database_integration_receipt_digest": "sha256:" + "f" * 64,
        "source_revision": revision,
        "source_tree_digest": "sha256:" + "0" * 64,
    }
    receipt: dict[str, object] = {
        "bindings": bindings,
        "checks": {
            name: {"bazel_target": target, "status": "passed"}
            for name, target in sorted(REHEARSAL_CHECK_TARGETS.items())
        },
        "ratification": {
            "authorized": False,
            "reason": "local rehearsal assertions do not prove execution or ratification",
        },
        "schema_version": "mindclade.training-vertical-rehearsal/v1",
        "status": "passed",
    }
    receipt["receipt_digest"] = digest_bytes(
        readiness_canonical_json(cast(ReadinessJsonValue, receipt))
    )
    path.write_bytes(readiness_canonical_json(cast(ReadinessJsonValue, receipt)))


def _trusted_context(*, source_trust: str = "protected") -> JsonObject:
    return {
        "base_revision": None,
        "cache_architecture": "x86_64",
        "cache_build_mode": "protected",
        "cache_classification": "private-internal",
        "cache_mode": "disabled",
        "cache_namespace_epoch": "disabled-v1",
        "cache_platform": "linux",
        "cache_toolchain_digest": "sha256:" + "f" * 64,
        "correlation_id": "stage5-contract-qualification",
        "execution_tier": "trusted",
        "launcher_digest": "sha256:" + "e" * 64,
        "launcher_identity": "buildkite://mindclade/protected-launcher",
        "launcher_revision": "d" * 40,
        "pipeline_class": "protected",
        "pipeline_definition_revision": SOURCE_REVISION,
        "repository": "mindclade/mindclade",
        "source_revision": SOURCE_REVISION,
        "source_trust": source_trust,
        "workflow_ref": ".github/workflows/buildkite-dispatch.yml",
        "workflow_revision": SOURCE_REVISION,
    }


def _context_digest(context: JsonObject) -> str:
    return assembler_sha256_bytes(signed_payload_json(context))


def _protected_build_identity(context: JsonObject | None = None) -> str:
    digest = _context_digest(context or _trusted_context()).removeprefix("sha256:")
    return f"buildkite://mindclade/mindclade/contexts/{digest}"


def _receipt(
    name: str,
    root: Path,
    *,
    producer_identity: str | None = None,
    binding_overrides: dict[str, object] | None = None,
) -> dict[str, object]:
    contract = RECEIPT_CONTRACTS[name]
    protected_build_identity = _protected_build_identity()
    bindings: dict[str, object] = {key: ALL_BINDINGS[key] for key in contract.binding_fields}
    bindings.update(binding_overrides or {})
    result_path = root / "build/evidence/results" / f"{name}.json"
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result: dict[str, object] = {
        "bazel_targets": list(contract.required_targets),
        "completed_at": "2026-09-02T12:01:00Z",
        "failed_tests": [],
        "protected_build_identity": protected_build_identity,
        "schema_version": contract.result_schema_version,
        "skipped_tests": [],
        "source_revision": SOURCE_REVISION,
        "started_at": "2026-09-02T12:00:00Z",
        "status": "passed",
    }
    result_path.write_bytes(assembler_canonical_json(cast(AssemblerJsonValue, result)))
    value: dict[str, object] = {
        "bindings": bindings,
        "completed_at": "2026-09-02T12:01:00Z",
        "executed_bazel_targets": list(contract.required_targets),
        "producer_identity": producer_identity or contract.producer_identity,
        "protected_build_identity": protected_build_identity,
        "result_artifact_digest": assembler_sha256_bytes(result_path.read_bytes()),
        "result_artifact_path": result_path.relative_to(root).as_posix(),
        "required_bazel_targets": list(contract.required_targets),
        "schema_version": contract.schema_version,
        "skipped_required_tests": [],
        "started_at": "2026-09-02T12:00:00Z",
        "status": "passed",
    }
    value["receipt_digest"] = assembler_sha256_bytes(
        assembler_canonical_json(cast(AssemblerJsonValue, value))
    )
    return value


def _write_receipts(root: Path) -> dict[str, Path]:
    directory = root / "build/evidence/receipts"
    directory.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    for name in RECEIPT_CONTRACTS:
        path = directory / f"{name}.json"
        path.write_bytes(assembler_canonical_json(cast(AssemblerJsonValue, _receipt(name, root))))
        paths[name] = path
    return paths


def _write_approval(
    root: Path,
    paths: dict[str, Path],
    *,
    receipt_digest_overrides: dict[str, str] | None = None,
    reviewer_identity: str = "principal://mindclade/reviewers/contract-governance",
) -> Path:
    receipt_digests = {
        name: cast(str, json.loads(path.read_text(encoding="utf-8"))["receipt_digest"])
        for name, path in paths.items()
    }
    receipt_digests.update(receipt_digest_overrides or {})
    approval = {
        "approval_id": "stage5-contract-approval-001",
        "approved_at": "2026-09-02T12:02:00Z",
        "decision": "approved",
        "gate": "stage-5-contract-ratification",
        "kind": "QualificationApproval",
        "protected_build_identity": _protected_build_identity(),
        "receipt_digests": receipt_digests,
        "reviewer_identity": reviewer_identity,
        "schema_version": "mindclade.training-evidence-approval/v1",
        "source_revision": SOURCE_REVISION,
    }
    path = root / "build/evidence/approval.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(assembler_canonical_json(cast(AssemblerJsonValue, approval)))
    return path


@dataclass(frozen=True)
class _AttestedFixture:
    receipts: dict[str, AttestedArtifact]
    approval: AttestedArtifact
    context: AttestedArtifact
    trust_policy: SignerTrustPolicy


def _write_signer(
    root: Path,
    name: str,
) -> tuple[ed25519.Ed25519PrivateKey, Path, str]:
    private_key = ed25519.Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    encoded_key = public_key.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    key_id = assembler_sha256_bytes(encoded_key)
    key_path = root / "build/evidence/public-keys" / f"{name}.pem"
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.write_bytes(
        public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    return private_key, key_path, key_id


def _write_signature(
    root: Path,
    name: str,
    payload_path: Path,
    payload_type: str,
    private_key: ed25519.Ed25519PrivateKey,
    key_id: str,
) -> Path:
    payload = payload_path.read_bytes()
    envelope = {
        "payload": base64.b64encode(payload).decode("ascii"),
        "payloadType": payload_type,
        "signatures": [
            {
                "keyid": key_id,
                "sig": base64.b64encode(private_key.sign(dsse_pae(payload_type, payload))).decode(
                    "ascii"
                ),
            }
        ],
    }
    path = root / "build/evidence/signatures" / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(assembler_canonical_json(cast(AssemblerJsonValue, envelope)))
    return path


def _attest_fixture(
    root: Path,
    paths: dict[str, Path],
    approval: Path,
    *,
    context: JsonObject | None = None,
    preserve_approval_receipt_digests: bool = False,
) -> _AttestedFixture:
    receipt_artifacts: dict[str, AttestedArtifact] = {}
    receipt_keys: dict[str, frozenset[str]] = {}
    receipt_attestation_digests: dict[str, str] = {}
    for name, payload_path in sorted(paths.items()):
        private_key, public_key_path, key_id = _write_signer(root, f"receipt-{name}")
        signature_path = _write_signature(
            root,
            f"receipt-{name}",
            payload_path,
            receipt_payload_type(name),
            private_key,
            key_id,
        )
        receipt_artifacts[name] = AttestedArtifact(
            payload_path=payload_path,
            signature_envelope_path=signature_path,
            public_key_path=public_key_path,
        )
        receipt_keys[name] = frozenset({key_id})
        receipt_attestation_digests[name] = assembler_sha256_bytes(signature_path.read_bytes())

    if not preserve_approval_receipt_digests:
        approval_value = json.loads(approval.read_text(encoding="utf-8"))
        approval_value["receipt_digests"] = receipt_attestation_digests
        approval.write_bytes(assembler_canonical_json(cast(AssemblerJsonValue, approval_value)))
    approval_private_key, approval_public_key, approval_key_id = _write_signer(root, "approval")
    approval_signature = _write_signature(
        root,
        "approval",
        approval,
        APPROVAL_PAYLOAD_TYPE,
        approval_private_key,
        approval_key_id,
    )

    context_value = context or _trusted_context()
    context_path = root / "build/evidence/trusted-context.json"
    context_path.write_bytes(signed_payload_json(context_value))
    context_private_key, context_public_key, context_key_id = _write_signer(root, "context")
    context_signature = _write_signature(
        root,
        "context",
        context_path,
        PROTECTED_CONTEXT_PAYLOAD_TYPE,
        context_private_key,
        context_key_id,
    )
    reviewer = "principal://mindclade/reviewers/contract-governance"
    return _AttestedFixture(
        receipts=receipt_artifacts,
        approval=AttestedArtifact(approval, approval_signature, approval_public_key),
        context=AttestedArtifact(context_path, context_signature, context_public_key),
        trust_policy=SignerTrustPolicy(
            receipt_signer_key_ids=receipt_keys,
            approval_signer_key_ids={reviewer: frozenset({approval_key_id})},
            context_signer_key_ids={
                PROTECTED_CONTEXT_PRODUCER_IDENTITY: frozenset({context_key_id})
            },
        ),
    )


def _assemble(
    root: Path,
    paths: dict[str, Path],
    approval: Path,
    *,
    context: JsonObject | None = None,
    preserve_approval_receipt_digests: bool = False,
    governed_trust: bool = False,
) -> JsonObject:
    fixture = _attest_fixture(
        root,
        paths,
        approval,
        context=context,
        preserve_approval_receipt_digests=preserve_approval_receipt_digests,
    )
    if governed_trust:
        return assemble_evidence(
            fixture.receipts,
            root=root,
            approval_artifact=fixture.approval,
            trusted_context_artifact=fixture.context,
        )
    return _assemble_evidence(
        fixture.receipts,
        root=root,
        approval_artifact=fixture.approval,
        trusted_context_artifact=fixture.context,
        trust_policy=fixture.trust_policy,
    )


class TrainingRehearsalTest(unittest.TestCase):
    def test_fresh_database_receipt_is_exact_and_non_ratifying(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            migrations = root / "services/control_plane/migrations"
            migrations.mkdir(parents=True)
            (migrations / "000001.up.sql").write_text("SELECT 1;\n", encoding="utf-8")
            receipt = build_integration_receipt(root, SOURCE_REVISION)
            digest = receipt.pop("receipt_digest")
            self.assertFalse(receipt["ratification_authorized"])
            self.assertEqual(receipt["required_bazel_targets"], list(POSTGRES_TARGETS))
            self.assertEqual(digest, sha256_bytes(canonical_json(receipt)))

    def test_training_receipt_rejects_incomplete_check_set_first(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(ValueError, "missing=.*database"):
                build_receipt(
                    root,
                    "b" * 40,
                    {"grpc": "//services:grpc_test"},
                    root / "receipt.json",
                    {},
                )


class ReadinessReportTest(unittest.TestCase):
    def _fixture(self, directory: str) -> tuple[Path, Path, Path, Path, str]:
        root, actual_plan, actual_mapping = _repository_data()
        revision = _git_revision(root)
        temporary = Path(directory)
        plan = temporary / "plan.md"
        mapping = temporary / "criteria.json"
        rehearsal = temporary / "rehearsal.json"
        plan.write_bytes(actual_plan.read_bytes())
        mapping.write_bytes(actual_mapping.read_bytes())
        _write_rehearsal(rehearsal, revision=revision)
        return root, plan, mapping, rehearsal, revision

    def test_map_covers_plan_without_claiming_completion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, plan, mapping, rehearsal, revision = self._fixture(directory)
            report = build_report(
                plan,
                rehearsal,
                mapping_path=mapping,
                root=root,
                expected_source_revision=revision,
            )
            criteria = cast(list[dict[str, object]], report["criteria"])
            self.assertEqual(len(criteria), 34)
            self.assertEqual(len(plan_criteria(plan.read_text(encoding="utf-8"))), 34)
            self.assertFalse(report["ratification_authorized"])
            self.assertFalse(any(record["completion_verified"] for record in criteria))
            self.assertFalse(any(record["evidence_verified"] for record in criteria))
            stage5 = next(
                record
                for record in criteria
                if record["criterion_id"] == "stages-and-exit-criteria-06"
            )
            self.assertEqual(stage5["status"], "pending-protected-qualification")
            self.assertEqual(len(cast(list[object], stage5["dependencies"])), 16)
            self.assertTrue(
                all(
                    cast(dict[str, object], record["receipt"])["verification_class"]
                    == "source-assertion-validated"
                    for record in criteria
                    if cast(dict[str, object], record["receipt"])["present"]
                )
            )

    def test_stale_mapping_and_missing_target_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, plan, mapping, rehearsal, revision = self._fixture(directory)
            value = json.loads(mapping.read_text(encoding="utf-8"))
            value["criteria"][0]["criterion"] = "stale"
            mapping.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "mapping is stale"):
                build_report(
                    plan,
                    rehearsal,
                    mapping_path=mapping,
                    root=root,
                    expected_source_revision=revision,
                )
            mapping.write_bytes(_repository_data()[2].read_bytes())
            value = json.loads(mapping.read_text(encoding="utf-8"))
            value["criteria"][0]["bazel_targets"] = ["//missing:not_a_target"]
            mapping.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "missing Bazel targets"):
                build_report(
                    plan,
                    rehearsal,
                    mapping_path=mapping,
                    root=root,
                    expected_source_revision=revision,
                )

    def test_expected_revision_and_receipt_digest_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, plan, mapping, rehearsal, revision = self._fixture(directory)
            with self.assertRaisesRegex(ValueError, "checked-out HEAD"):
                build_report(
                    plan,
                    rehearsal,
                    mapping_path=mapping,
                    root=root,
                    expected_source_revision="b" * 40,
                )
            value = json.loads(rehearsal.read_text(encoding="utf-8"))
            value["bindings"]["candidate_descriptor_digest"] = "sha256:" + "d" * 64
            rehearsal.write_bytes(readiness_canonical_json(cast(ReadinessJsonValue, value)))
            with self.assertRaisesRegex(ValueError, "does not bind"):
                build_report(
                    plan,
                    rehearsal,
                    mapping_path=mapping,
                    root=root,
                    expected_source_revision=revision,
                )

    def test_rehearsal_target_assertions_are_exact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, plan, mapping, rehearsal, revision = self._fixture(directory)
            value = json.loads(rehearsal.read_text(encoding="utf-8"))
            value["checks"]["sdk"]["bazel_target"] = "//tests:wave1_contract_tests"
            value.pop("receipt_digest")
            value["receipt_digest"] = digest_bytes(
                readiness_canonical_json(cast(ReadinessJsonValue, value))
            )
            rehearsal.write_bytes(readiness_canonical_json(cast(ReadinessJsonValue, value)))
            with self.assertRaisesRegex(ValueError, "check sdk differs from policy"):
                build_report(
                    plan,
                    rehearsal,
                    mapping_path=mapping,
                    root=root,
                    expected_source_revision=revision,
                )

    def test_unregistered_receipt_verifier_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, plan, mapping, rehearsal, revision = self._fixture(directory)
            receipt = Path(directory) / "cross-language.json"
            receipt.write_text(
                json.dumps(
                    {
                        "schema_version": "mindclade.cross-language-conformance/v1",
                        "status": "passed",
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "no governed receipt verifier"):
                build_report(
                    plan,
                    rehearsal,
                    mapping_path=mapping,
                    root=root,
                    receipt_paths={"cross_language": receipt},
                    expected_source_revision=revision,
                )


class ProtectedEvidenceAssemblerTest(unittest.TestCase):
    def test_assembles_exact_ratifier_payload_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = _write_receipts(root)
            evidence = _assemble(root, paths, _write_approval(root, paths))
            self.assertEqual(evidence["schema_version"], EVIDENCE_SCHEMA)
            self.assertEqual(
                set(evidence),
                {
                    "approval",
                    "checks",
                    "protected_context",
                    "schema_version",
                    "status",
                    *RATIFICATION_BINDING_FIELDS,
                },
            )
            self.assertFalse(signed_payload_json(evidence).endswith(b"\n"))
            self.assertEqual(
                cast(dict[str, str], evidence["protected_context"])["protected_build_identity"],
                _protected_build_identity(),
            )
            checks = cast(dict[str, dict[str, str]], evidence["checks"])
            self.assertEqual(set(checks), set(RECEIPT_CONTRACTS))
            self.assertTrue(
                all(
                    set(check)
                    == {
                        "producer_identity",
                        "receipt_digest",
                        "result_artifact_digest",
                        "status",
                    }
                    for check in checks.values()
                )
            )

    def test_protected_receipt_target_union_reaches_every_mapped_stage5_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = _write_receipts(root)
            evidence = _assemble(root, paths, _write_approval(root, paths))
            bound_targets = validate_assembled_evidence_payload(
                evidence,
                expected_source_revision=SOURCE_REVISION,
                encoded=signed_payload_json(evidence),
            )
            mapping = json.loads(_repository_data()[2].read_text(encoding="utf-8"))
            unreachable = {
                entry["criterion_id"]: sorted(set(entry["bazel_targets"]) - bound_targets)
                for entry in mapping["criteria"]
                if entry["receipt_name"] == "training_vertical"
                and not set(entry["bazel_targets"]).issubset(bound_targets)
            }
            self.assertEqual(unreachable, {})
            self.assertTrue(
                {
                    "//:all_contract_tests",
                    "//tools:repository_governance_tests",
                    "//tools:training_evidence_test",
                }.issubset(bound_targets)
            )

    def test_protected_database_schema_does_not_collide_with_rehearsal(self) -> None:
        self.assertEqual(
            RECEIPT_CONTRACTS["database"].schema_version,
            "mindclade.protected-fresh-database-qualification/v1",
        )

    def test_requires_exact_receipt_set_and_consistent_bindings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = _write_receipts(root)
            approval = _write_approval(root, paths)
            paths.pop("database")
            with self.assertRaisesRegex(ValueError, "receipt set differs"):
                _assemble(root, paths, approval)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = _write_receipts(root)
            paths["gateway"].write_bytes(
                assembler_canonical_json(
                    cast(
                        AssemblerJsonValue,
                        _receipt(
                            "gateway",
                            root,
                            binding_overrides={"candidate_descriptor_digest": "sha256:" + "f" * 64},
                        ),
                    )
                )
            )
            with self.assertRaisesRegex(ValueError, "disagree on binding"):
                _assemble(root, paths, _write_approval(root, paths))

    def test_rejects_wrong_producer_target_and_skipped_tests(self) -> None:
        mutations = (
            ("producer", "producer_identity differs from policy"),
            ("targets", "target set differs from policy"),
            ("skipped", "skipped required tests"),
        )
        for mutation, expected in mutations:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                paths = _write_receipts(root)
                value = _receipt("grpc", root)
                if mutation == "producer":
                    value["producer_identity"] = RECEIPT_CONTRACTS["sdk"].producer_identity
                elif mutation == "targets":
                    value["executed_bazel_targets"] = ["//:all_contract_tests"]
                    value["required_bazel_targets"] = ["//:all_contract_tests"]
                else:
                    value["skipped_required_tests"] = ["grpc_registration"]
                value.pop("receipt_digest")
                value["receipt_digest"] = assembler_sha256_bytes(
                    assembler_canonical_json(cast(AssemblerJsonValue, value))
                )
                paths["grpc"].write_bytes(assembler_canonical_json(cast(AssemblerJsonValue, value)))
                with self.assertRaisesRegex(ValueError, expected):
                    _assemble(root, paths, _write_approval(root, paths))

    def test_rejects_stale_receipt_and_tampered_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = _write_receipts(root)
            paths["database"].write_bytes(
                assembler_canonical_json(
                    cast(
                        AssemblerJsonValue,
                        _receipt(
                            "database",
                            root,
                            binding_overrides={"source_revision": "b" * 40},
                        ),
                    )
                )
            )
            with self.assertRaisesRegex(ValueError, "stale"):
                _assemble(root, paths, _write_approval(root, paths))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = _write_receipts(root)
            result_path = root / "build/evidence/results/grpc.json"
            value = json.loads(result_path.read_text(encoding="utf-8"))
            value["failed_tests"] = ["grpc_registration"]
            result_path.write_bytes(assembler_canonical_json(cast(AssemblerJsonValue, value)))
            with self.assertRaisesRegex(ValueError, "failed or skipped tests"):
                _assemble(root, paths, _write_approval(root, paths))

    def test_rejects_local_rehearsal_bad_approval_and_untrusted_context(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = _write_receipts(root)
            rehearsal = root / "build/evidence/rehearsal.json"
            _write_rehearsal(rehearsal, revision=SOURCE_REVISION)
            paths["cross_language"].write_bytes(rehearsal.read_bytes())
            with self.assertRaisesRegex(ValueError, "receipt fields differ"):
                _assemble(root, paths, _write_approval(root, paths))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = _write_receipts(root)
            approval = _write_approval(
                root,
                paths,
                receipt_digest_overrides={"sdk": "sha256:" + "e" * 64},
            )
            with self.assertRaisesRegex(ValueError, "different qualification receipts"):
                _assemble(
                    root,
                    paths,
                    approval,
                    preserve_approval_receipt_digests=True,
                )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = _write_receipts(root)
            approval = _write_approval(root, paths)
            context = _trusted_context(source_trust="trusted")
            with self.assertRaisesRegex(ValueError, "protected source trust"):
                _assemble(
                    root,
                    paths,
                    approval,
                    context=context,
                )

    def test_requires_authenticated_context_receipts_and_independent_approval(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = _write_receipts(root)
            approval = _write_approval(root, paths)
            with self.assertRaisesRegex(ValueError, "signer trust is not activated"):
                _assemble(root, paths, approval, governed_trust=True)

        for tampered_name in ("context", "receipt", "approval"):
            with self.subTest(tampered=tampered_name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                paths = _write_receipts(root)
                fixture = _attest_fixture(root, paths, _write_approval(root, paths))
                artifact = {
                    "context": fixture.context,
                    "receipt": fixture.receipts["grpc"],
                    "approval": fixture.approval,
                }[tampered_name]
                envelope = json.loads(artifact.signature_envelope_path.read_text(encoding="utf-8"))
                signature = base64.b64decode(envelope["signatures"][0]["sig"])
                envelope["signatures"][0]["sig"] = base64.b64encode(
                    signature[:-1] + bytes([signature[-1] ^ 1])
                ).decode("ascii")
                artifact.signature_envelope_path.write_bytes(
                    assembler_canonical_json(cast(AssemblerJsonValue, envelope))
                )
                with self.assertRaisesRegex(ValueError, "signature verification failed"):
                    _assemble_evidence(
                        fixture.receipts,
                        root=root,
                        approval_artifact=fixture.approval,
                        trusted_context_artifact=fixture.context,
                        trust_policy=fixture.trust_policy,
                    )

    def test_rejects_declarative_reviewer_and_cross_role_signer_key_reuse(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = _write_receipts(root)
            approval = _write_approval(
                root,
                paths,
                reviewer_identity=RECEIPT_CONTRACTS["grpc"].producer_identity,
            )
            with self.assertRaisesRegex(ValueError, "reviewer_identity is not authorized"):
                _assemble(root, paths, approval)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = _write_receipts(root)
            fixture = _attest_fixture(root, paths, _write_approval(root, paths))
            reused_key = next(iter(fixture.trust_policy.receipt_signer_key_ids["cross_language"]))
            policy = SignerTrustPolicy(
                receipt_signer_key_ids=fixture.trust_policy.receipt_signer_key_ids,
                approval_signer_key_ids={
                    "principal://mindclade/reviewers/contract-governance": frozenset({reused_key})
                },
                context_signer_key_ids=fixture.trust_policy.context_signer_key_ids,
            )
            with self.assertRaisesRegex(ValueError, "authorized for both"):
                _assemble_evidence(
                    fixture.receipts,
                    root=root,
                    approval_artifact=fixture.approval,
                    trusted_context_artifact=fixture.context,
                    trust_policy=policy,
                )

    def test_rejects_receipt_outside_evidence_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = _write_receipts(root)
            outside = root / "cross-language.json"
            outside.write_bytes(paths["cross_language"].read_bytes())
            paths["cross_language"] = outside
            with self.assertRaisesRegex(ValueError, "under build/evidence"):
                _assemble(root, paths, _write_approval(root, paths))


if __name__ == "__main__":
    unittest.main()
