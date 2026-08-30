from __future__ import annotations

import base64
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "tools/repo"))

from build_repository_drift_report import (  # noqa: E402
    CANONICAL_OPERATIONAL_REMOTES,
    CONNECTED_OBSERVATION_ALGORITHM,
    CONNECTED_OBSERVATION_PAYLOAD_TYPE,
    CONNECTED_OBSERVATION_PAYLOAD_VERSION,
    CONNECTED_OBSERVATION_RECEIPT_VERSION,
    CONNECTED_OBSERVATION_SIGNING_PREFIX,
    OPERATIONAL_COMPONENT_NAMES,
    OPERATIONAL_PROJECT_SLUGS,
    OPERATIONAL_RULESETS,
    REQUIRED_OPERATIONAL_REFERENCES,
    build_report,
    canonical_json_bytes,
    extract_operational_targets,
    find_new_drift_categories,
    render_markdown,
    report_exit_code,
    validate_approved_baseline,
    validate_report_document,
    write_report_outputs,
)

FIXTURE_REVISIONS = {
    name: f"{index:x}" * 40
    for index, name in enumerate(sorted(REQUIRED_OPERATIONAL_REFERENCES), start=1)
}
CANONICAL_REVISION = "a" * 40


def _write_canonical_json(path: Path, value: object) -> None:
    path.write_bytes(canonical_json_bytes(value))


def _write_signed_receipt(
    path: Path,
    payload: dict[str, Any],
    private_key: ec.EllipticCurvePrivateKey,
    key_version: str,
    *,
    tamper_signature: bool = False,
) -> None:
    signature = private_key.sign(
        CONNECTED_OBSERVATION_SIGNING_PREFIX
        + canonical_json_bytes(payload, terminal_newline=False),
        ec.ECDSA(hashes.SHA256()),
    )
    if tamper_signature:
        signature = signature[:-1] + bytes([signature[-1] ^ 1])
    _write_canonical_json(
        path,
        {
            "payload": payload,
            "payload_type": CONNECTED_OBSERVATION_PAYLOAD_TYPE,
            "schema_version": CONNECTED_OBSERVATION_RECEIPT_VERSION,
            "signature": {
                "algorithm": CONNECTED_OBSERVATION_ALGORITHM,
                "key_version": key_version,
                "signature_base64": base64.b64encode(signature).decode("ascii"),
            },
        },
    )


def _component_document(name: str) -> str:
    trust_and_recovery = ""
    annotations = f"    github.com/project-slug: {OPERATIONAL_PROJECT_SLUGS[name]}\n"
    if name == "gitops":
        annotations += (
            "    mindclade.dev/trust-tier: deployment-control\n"
            "    mindclade.dev/recovery-tier: isolated-git\n"
        )
    else:
        trust_and_recovery = "  trust_tier: fixture-trust\n  recovery_tier: fixture-recovery\n"
    return (
        "apiVersion: mindclade.io/v1alpha1\n"
        "kind: Component\n"
        "metadata:\n"
        f"  name: {OPERATIONAL_COMPONENT_NAMES[name]}\n"
        "  annotations:\n"
        f"{annotations}"
        "spec:\n"
        "  owner: fixture-owner\n"
        "  repository_class: fixture-source\n"
        f"{trust_and_recovery}"
        "  release:\n"
        "    strategy: reviewed-main\n"
        "    artifact: source-commit\n"
        "    immutable: true\n"
        "    evidence: []\n"
    )


class FixtureGitReader:
    def __init__(
        self,
        canonical: Path,
        references: dict[str, Path],
        targets: dict[str, dict[str, Any]],
        *,
        omit_inventory_path: tuple[str, str] | None = None,
        remote_override: tuple[str, str] | None = None,
        checkout_head_override: tuple[str, str] | None = None,
    ) -> None:
        self.canonical = canonical
        self.names_by_path = {path: name for name, path in references.items()}
        self.targets = targets
        self.omit_inventory_path = omit_inventory_path
        self.remote_override = remote_override
        self.checkout_head_override = checkout_head_override

    def __call__(self, path: Path, *args: str) -> str:
        if path == self.canonical:
            if args[:2] == ("rev-parse", "--verify"):
                return CANONICAL_REVISION + "\n"
            if args[:2] == ("status", "--porcelain=v1"):
                return ""
            return ""

        name = self.names_by_path[path]
        if args[:2] == ("rev-parse", "HEAD"):
            if self.checkout_head_override and self.checkout_head_override[0] == name:
                return self.checkout_head_override[1] + "\n"
            return FIXTURE_REVISIONS[name] + "\n"
        if args[:2] == ("rev-parse", "--verify"):
            expected = f"{FIXTURE_REVISIONS[name]}^{{commit}}"
            return FIXTURE_REVISIONS[name] + "\n" if args[2] == expected else ""
        if args[:3] == ("remote", "get-url", "origin"):
            if self.remote_override and self.remote_override[0] == name:
                return self.remote_override[1] + "\n"
            return CANONICAL_OPERATIONAL_REMOTES[name] + "\n"
        if args[:2] == ("status", "--porcelain=v1"):
            return ""
        if args[:2] == ("branch", "--show-current"):
            return "main\n"
        if args and args[0] == "show":
            object_name = args[1]
            if object_name.endswith(":component.yaml"):
                return _component_document(name)
            if path == self.names_by_path_inverse["github-config"]:
                return f"fixture protection policy for {object_name}\n"
            return ""
        if args[:3] == ("ls-tree", "-r", "--name-only"):
            paths = list(self.targets[name]["paths"])
            if self.omit_inventory_path and self.omit_inventory_path[0] == name:
                paths.remove(self.omit_inventory_path[1])
            return "\n".join(paths) + "\n"
        return ""

    @property
    def names_by_path_inverse(self) -> dict[str, Path]:
        return {name: path for path, name in self.names_by_path.items()}


def fixture_report(
    *,
    observation_scope: str = "working-tree",
    reference_status: str | None = None,
    omit_reference: str | None = None,
    omit_inventory_path: tuple[str, str] | None = None,
    remote_override: tuple[str, str] | None = None,
    checkout_head_override: tuple[str, str] | None = None,
    qualified_receipts: bool = False,
    tamper_receipt: bool = False,
) -> dict[str, Any]:
    manifest = json.loads(
        (REPO_ROOT / "docs/architecture/repository-path-manifest.yaml").read_text(encoding="utf-8")
    )
    for entry in manifest["paths"]:
        entry["status"] = "target"
        entry["activation_criterion"] = "Fixture target; not populated."
        entry["build_targets"] = []
        entry["test_targets"] = []
    for path in ("README.md", ".github/CODEOWNERS"):
        entry = next(item for item in manifest["paths"] if item["path"] == path)
        entry["status"] = "active"
        entry.pop("activation_criterion", None)
        entry["build_targets"] = ["//:wave0_governance_sources"]
        entry["test_targets"] = ["//:wave0_tests"]

    targets = extract_operational_targets(
        REPO_ROOT
        / "docs/architecture/blueprint/appendices/A03-repository-estate-and-trust-boundaries.md"
    )
    with tempfile.TemporaryDirectory() as directory:
        base = Path(directory)
        root = base / "canonical"
        root.mkdir()
        (root / "README.md").write_text("greenfield\n", encoding="utf-8")
        (root / ".github").mkdir()
        (root / ".github/CODEOWNERS").write_text(
            "* @mindclade/developer-platform\n", encoding="utf-8"
        )
        external = base / "manifest.json"
        external.write_text(json.dumps(manifest), encoding="utf-8")
        reference_paths: dict[str, Path] = {}
        checks: dict[str, list[dict[str, str]]] = {}
        for name in sorted(REQUIRED_OPERATIONAL_REFERENCES):
            if name == omit_reference:
                continue
            reference = base / name
            reference.mkdir()
            reference_paths[name] = reference
            status = reference_status if name == "bootstrap" and reference_status else "PASS"
            checks[name] = [
                {
                    "status": status,
                    "scope": "immutable-head",
                    "command": "just ci",
                    "finding": "fixture qualification result",
                }
            ]
        receipt_paths: dict[str, list[Path]] = {}
        public_key_path: Path | None = None
        key_version: str | None = None
        trust_record_paths: list[Path] = []
        if qualified_receipts:
            checks = {}
            private_key = ec.generate_private_key(ec.SECP256R1())
            public_key_path = base / "connected-observation-public-key.pem"
            public_key_path.write_bytes(
                private_key.public_key().public_bytes(
                    serialization.Encoding.PEM,
                    serialization.PublicFormat.SubjectPublicKeyInfo,
                )
            )
            key_version = (
                "projects/fixture/locations/global/keyRings/root/cryptoKeys/"
                "connected-observation-evidence/cryptoKeyVersions/1"
            )
            for record_name in ("bootstrap-root", "independent-review"):
                record_path = base / f"{record_name}.json"
                _write_canonical_json(
                    record_path,
                    {
                        "kind": record_name,
                        "schema_version": "mindclade.fixture-trust-record.v1",
                    },
                )
                trust_record_paths.append(record_path)

            tamper_pending = tamper_receipt
            github_config_revision = FIXTURE_REVISIONS["github-config"]
            for name in sorted(reference_paths):
                revision = FIXTURE_REVISIONS[name]
                repository = OPERATIONAL_PROJECT_SLUGS[name]
                ruleset = OPERATIONAL_RULESETS[name]
                policy_path = f"config/rulesets/{ruleset}.yaml"
                policy_text = (
                    f"fixture protection policy for {github_config_revision}:{policy_path}\n"
                )
                payloads = [
                    {
                        "expected_value": "main",
                        "finding": "Fixture default branch was observed at the immutable revision.",
                        "kind": "default_branch",
                        "observed": "main",
                        "ref": "refs/heads/main",
                        "repository": repository,
                        "revision": revision,
                        "schema_version": CONNECTED_OBSERVATION_PAYLOAD_VERSION,
                        "status": "PASS",
                    },
                    {
                        "expected_value": ruleset,
                        "finding": "Fixture protection matched the reviewed policy.",
                        "kind": "branch_protection",
                        "observed": ruleset,
                        "policy_content_sha256": hashlib.sha256(
                            policy_text.encode("utf-8")
                        ).hexdigest(),
                        "policy_revision": github_config_revision,
                        "ref": "refs/heads/main",
                        "repository": repository,
                        "revision": revision,
                        "schema_version": CONNECTED_OBSERVATION_PAYLOAD_VERSION,
                        "status": "PASS",
                    },
                    {
                        "check": "just ci",
                        "finding": "Fixture immutable source check passed.",
                        "kind": "source_check",
                        "repository": repository,
                        "revision": revision,
                        "schema_version": CONNECTED_OBSERVATION_PAYLOAD_VERSION,
                        "scope": "immutable-head",
                        "status": "PASS",
                    },
                ]
                receipt_paths[name] = []
                for index, payload in enumerate(payloads):
                    receipt_path = base / f"{name}-{index}.json"
                    _write_signed_receipt(
                        receipt_path,
                        payload,
                        private_key,
                        key_version,
                        tamper_signature=tamper_pending,
                    )
                    tamper_pending = False
                    receipt_paths[name].append(receipt_path)
        return build_report(
            root,
            external,
            REPO_ROOT / "tools/repo/component.schema.json",
            sorted(reference_paths.items()),
            checks,
            {name: FIXTURE_REVISIONS[name] for name in reference_paths},
            observation_scope=observation_scope,
            operational_targets=targets,
            reference_receipt_paths=receipt_paths,
            connected_observation_public_key=public_key_path,
            connected_observation_key_version=key_version,
            connected_observation_trust_records=trust_record_paths,
            git_reader=FixtureGitReader(
                root,
                reference_paths,
                targets,
                omit_inventory_path=omit_inventory_path,
                remote_override=remote_override,
                checkout_head_override=checkout_head_override,
            ),
        )


class RepositoryDriftReportTest(unittest.TestCase):
    def test_greenfield_report_matches_golden_and_schema(self) -> None:
        report = fixture_report()
        golden = json.loads(
            (REPO_ROOT / "tools/repo/tests/golden/repository_drift.v1.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(report, golden)
        schema = json.loads(
            (REPO_ROOT / "tools/repo/repository_drift.v1.schema.json").read_text(encoding="utf-8")
        )
        self.assertEqual(validate_report_document(report, schema), [])
        invalid = json.loads(json.dumps(report))
        invalid["canonical_repository"]["unexpected"] = True
        invalid["summary"]["populated_paths"] = "two"
        errors = validate_report_document(invalid, schema)
        self.assertTrue(any("unexpected" in error for error in errors))
        self.assertTrue(any("populated_paths" in error for error in errors))

    def test_report_is_deterministic_and_fact_only(self) -> None:
        first = fixture_report()
        second = fixture_report()
        self.assertEqual(
            json.dumps(first, sort_keys=True, separators=(",", ":")),
            json.dumps(second, sort_keys=True, separators=(",", ":")),
        )
        self.assertEqual(first["dependency_edges"], [])
        self.assertEqual(first["migration_dispositions"], [])
        self.assertTrue(first["boundaries"]["product_graph_empty"])
        self.assertFalse(first["boundaries"]["legacy_code_imported"])
        self.assertEqual(first["readiness"]["label"], "INCONCLUSIVE")
        self.assertEqual(first["canonical_repository"]["observation_scope"], "working-tree")
        self.assertIsNone(first["canonical_repository"]["observed_commit"])

    def test_commit_observation_is_bound_to_a_clean_revision(self) -> None:
        report = fixture_report(observation_scope="commit")
        canonical = report["canonical_repository"]
        self.assertEqual(canonical["observation_scope"], "commit")
        self.assertEqual(canonical["working_tree_state"], "clean")
        self.assertEqual(canonical["observed_commit"], canonical["base_commit"])

    def test_source_only_observations_cannot_claim_wave_zero(self) -> None:
        report = fixture_report()
        self.assertEqual(report["summary"]["default_branch_observations_incomplete"], 5)
        self.assertEqual(report["summary"]["branch_protection_observations_incomplete"], 5)
        self.assertEqual(report["readiness"]["label"], "INCONCLUSIVE")
        for reference in report["reference_sources"]:
            self.assertEqual(
                reference["branch_protection"]["observation"]["signature_verification"],
                "NOT_VERIFIED",
            )
        forged = json.loads(json.dumps(report))
        forged["readiness"]["label"] = "WAVE-0"
        forged["reference_sources"][0]["default_branch"]["observation"].update(
            {
                "status": "PASS",
                "signature_verification": "PASS",
                "observed": "main",
                "evidence_sha256": "c" * 64,
            }
        )
        schema = json.loads(
            (REPO_ROOT / "tools/repo/repository_drift.v1.schema.json").read_text(encoding="utf-8")
        )
        errors = validate_report_document(forged, schema)
        self.assertTrue(errors)
        self.assertTrue(any("WAVE-0 readiness requires" in error for error in errors))

    def test_schema_has_a_subject_bound_qualified_receipt_path(self) -> None:
        report = fixture_report(observation_scope="commit")
        verifier_revision = report["canonical_repository"]["observed_commit"]
        for reference in report["reference_sources"]:
            common = {
                "status": "PASS",
                "source": "cryptographically-verified-receipt",
                "revision": reference["revision"],
                "evidence_sha256": "c" * 64,
                "signature_verification": "PASS",
                "finding": "Fixture receipt passed independent cryptographic verification.",
                "verification": {
                    "verifier": "mindclade-connected-observation-verifier",
                    "verifier_version": "1",
                    "verifier_source_revision": verifier_revision,
                    "algorithm": "ECDSA_P256_SHA256",
                    "key_version": "projects/p/locations/l/keyRings/r/cryptoKeys/k/versions/1",
                    "public_key_sha256": "d" * 64,
                    "signature_sha256": "e" * 64,
                    "trust_record_sha256": ["1" * 64, "2" * 64],
                },
            }
            slug = reference["component_metadata"]["project_slug"]
            reference["default_branch"]["observation"] = {
                **common,
                "observed": "main",
                "subject": {
                    "repository": slug,
                    "revision": reference["revision"],
                    "ref": "refs/heads/main",
                    "control": "default_branch",
                    "expected_value": "main",
                },
            }
            protection = reference["branch_protection"]["target"]
            reference["branch_protection"]["observation"] = {
                **common,
                "subject": {
                    "repository": slug,
                    "revision": reference["revision"],
                    "ref": protection["ref"],
                    "control": "branch_protection",
                    "expected_value": protection["ruleset"],
                },
            }
            reference["source_checks"] = [
                {
                    "qualification": "VERIFIED",
                    "status": "PASS",
                    "scope": "immutable-head",
                    "command": check["command"],
                    "finding": "Fixture source-check receipt passed verification.",
                    "evidence_sha256": "f" * 64,
                    "subject": {
                        "repository": slug,
                        "revision": reference["revision"],
                        "check": check["command"],
                    },
                    "verification": common["verification"],
                }
                for check in reference["source_checks"]
            ]
        report["summary"]["default_branch_observations_incomplete"] = 0
        report["summary"]["branch_protection_observations_incomplete"] = 0
        report["summary"]["source_check_failures"] = 0
        report["readiness"] = {
            "label": "WAVE-0",
            "reason": "Fixture qualifying evidence is complete.",
        }
        schema = json.loads(
            (REPO_ROOT / "tools/repo/repository_drift.v1.schema.json").read_text(encoding="utf-8")
        )
        self.assertEqual(validate_report_document(report, schema), [])
        baseline_errors = validate_approved_baseline(report, report, schema)
        self.assertEqual(baseline_errors, [])

    def test_verified_connected_receipts_qualify_wave_zero(self) -> None:
        report = fixture_report(observation_scope="commit", qualified_receipts=True)
        self.assertEqual(report["readiness"]["label"], "WAVE-0")
        self.assertEqual(report["summary"]["default_branch_observations_incomplete"], 0)
        self.assertEqual(report["summary"]["branch_protection_observations_incomplete"], 0)
        self.assertEqual(report["summary"]["source_check_failures"], 0)
        for reference in report["reference_sources"]:
            self.assertEqual(
                reference["default_branch"]["observation"]["signature_verification"],
                "PASS",
            )
            self.assertEqual(
                reference["branch_protection"]["observation"]["signature_verification"],
                "PASS",
            )
            self.assertTrue(
                all(check["qualification"] == "VERIFIED" for check in reference["source_checks"])
            )
        schema = json.loads(
            (REPO_ROOT / "tools/repo/repository_drift.v1.schema.json").read_text(encoding="utf-8")
        )
        self.assertEqual(validate_report_document(report, schema), [])
        self.assertEqual(validate_approved_baseline(report, report, schema), [])

    def test_tampered_connected_receipt_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "signature verification failed"):
            fixture_report(
                observation_scope="commit",
                qualified_receipts=True,
                tamper_receipt=True,
            )

    def test_asserted_operational_source_checks_cannot_qualify_readiness(self) -> None:
        report = fixture_report(reference_status="FAIL")
        self.assertEqual(report["summary"]["source_check_failures"], 5)
        self.assertTrue(
            all(
                check["qualification"] == "ASSERTED"
                for reference in report["reference_sources"]
                for check in reference["source_checks"]
            )
        )
        self.assertEqual(report["readiness"]["label"], "INCONCLUSIVE")
        self.assertEqual(report_exit_code(report, allow_inconclusive=False), 3)
        self.assertEqual(report_exit_code(report, allow_inconclusive=True), 0)

    def test_missing_operational_source_blocks_readiness(self) -> None:
        report = fixture_report(omit_reference="gitops")
        self.assertEqual(report["missing_reference_sources"], ["gitops"])
        self.assertEqual(report["summary"]["source_checks_missing"], 1)
        self.assertEqual(report["readiness"]["label"], "INCONCLUSIVE")

    def test_a3_inventory_drift_is_explicit_and_blocking(self) -> None:
        target = extract_operational_targets(
            REPO_ROOT
            / "docs/architecture/blueprint/appendices/A03-repository-estate-and-trust-boundaries.md"
        )["bootstrap"]["paths"][0]
        report = fixture_report(omit_inventory_path=("bootstrap", target))
        bootstrap = next(
            item for item in report["reference_sources"] if item["name"] == "bootstrap"
        )
        inventory = bootstrap["observed_vs_target_inventory"]
        self.assertEqual(inventory["status"], "FAIL")
        self.assertEqual(inventory["missing_paths"], [target])
        self.assertEqual(inventory["dispositions"][0]["disposition"], "unresolved")
        self.assertEqual(report["summary"]["operational_inventory_failures"], 1)
        self.assertEqual(report["readiness"]["label"], "INCONCLUSIVE")

    def test_operational_component_metadata_normalizes_annotated_tiers(self) -> None:
        report = fixture_report()
        gitops = next(item for item in report["reference_sources"] if item["name"] == "gitops")
        metadata = gitops["component_metadata"]
        self.assertEqual(metadata["metadata_name"], "gitops")
        self.assertEqual(metadata["project_slug"], "mindclade/gitops")
        self.assertEqual(metadata["trust_tier"], "deployment-control")
        self.assertEqual(metadata["recovery_tier"], "isolated-git")

    def test_wrong_operational_remote_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "expected"):
            fixture_report(remote_override=("bootstrap", "https://example.invalid/bootstrap.git"))

    def test_declared_revision_excludes_volatile_checkout_head(self) -> None:
        moving_head = "f" * 40
        report = fixture_report(checkout_head_override=("organization-workflows", moving_head))
        reference = next(
            item for item in report["reference_sources"] if item["name"] == "organization-workflows"
        )
        self.assertEqual(reference["revision"], FIXTURE_REVISIONS["organization-workflows"])
        self.assertEqual(reference["revision_selection"], "declared")
        self.assertIsNone(reference["checkout_head"])
        self.assertEqual(reference["working_tree_state"], "excluded")
        self.assertEqual(reference["default_branch"]["observation"]["source"], "not-observed")
        self.assertEqual(
            reference["component_metadata"]["revision"],
            FIXTURE_REVISIONS["organization-workflows"],
        )

    def test_test_golden_cannot_be_used_as_an_approved_actual_baseline(self) -> None:
        report = fixture_report(observation_scope="commit")
        golden = json.loads(
            (REPO_ROOT / "tools/repo/tests/golden/repository_drift.v1.json").read_text(
                encoding="utf-8"
            )
        )
        schema = json.loads(
            (REPO_ROOT / "tools/repo/repository_drift.v1.schema.json").read_text(encoding="utf-8")
        )
        errors = validate_approved_baseline(golden, report, schema)
        self.assertIn("approved baseline must use commit observation scope", errors)

    def test_approved_baseline_comparison_covers_all_reference_facts(self) -> None:
        baseline = fixture_report(observation_scope="commit")
        report = json.loads(json.dumps(baseline))
        report["actual_paths"].append("tools/new_governance_fact.py")
        report["dependency_edges"].append(
            {
                "source": "component-a",
                "target": "component-b",
                "kind": "build",
                "visibility": "private",
                "owner": "developer-platform",
                "justification": "fixture",
                "scope": "test",
                "exception": None,
            }
        )
        report["reference_sources"][0]["component_metadata"]["owner"] = "changed-owner"
        report["reference_sources"][0]["branch_protection"]["target"]["ruleset"] = (
            "deployment-source"
        )
        self.assertEqual(
            find_new_drift_categories(report, baseline),
            [
                "actual_paths",
                "dependency_edges",
                "reference_sources.branch_protection",
                "reference_sources.component_metadata",
            ],
        )

    def test_markdown_disclaims_connected_qualification(self) -> None:
        markdown = render_markdown(fixture_report())
        self.assertIn("awaits independent architecture", markdown)
        self.assertIn("does not claim live GitHub", markdown)
        self.assertIn("signed connected observations", markdown)
        self.assertIn("Legacy code and history imported: no", markdown)
        self.assertIn("Once committed, CI regenerates", markdown)
        self.assertNotIn("committed Markdown evidence", markdown)

    def test_check_emits_json_artifact_and_verifies_only_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            json_output = root / "artifacts/repository_drift.v1.json"
            markdown_output = root / "repository-drift-baseline.md"
            markdown_output.write_text("current\n", encoding="utf-8")

            self.assertEqual(
                write_report_outputs(
                    json_output,
                    markdown_output,
                    '{"schema_version":"repository_drift.v1"}\n',
                    "current\n",
                    check=True,
                ),
                [],
            )
            self.assertEqual(
                json_output.read_text(encoding="utf-8"),
                '{"schema_version":"repository_drift.v1"}\n',
            )
            self.assertEqual(
                write_report_outputs(
                    json_output,
                    markdown_output,
                    "updated-json\n",
                    "stale\n",
                    check=True,
                ),
                [str(markdown_output)],
            )
            self.assertEqual(json_output.read_text(encoding="utf-8"), "updated-json\n")
            self.assertEqual(markdown_output.read_text(encoding="utf-8"), "current\n")


if __name__ == "__main__":
    unittest.main()
