from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "tools/repo"))

from dependency_policy import validate_dependency_graph  # noqa: E402
from owner_policy import (  # noqa: E402
    load_yaml_or_json,
    validate_component_document,
    validate_owners,
)
from path_policy import (  # noqa: E402
    PolicyError,
    discover_actual_paths,
    normalize_path,
    validate_manifest,
    validate_populated_paths,
)
from render_repository_tree import (  # noqa: E402
    BEGIN_MARKER,
    END_MARKER,
    render_fenced,
    render_tree,
    replace_generated_region,
)
from verify_repository_path_manifest import validate_declared_targets  # noqa: E402


class RepositoryPolicyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = json.loads(
            (REPO_ROOT / "docs/architecture/repository-path-manifest.yaml").read_text(
                encoding="utf-8"
            )
        )

    def test_manifest_is_semantically_valid(self) -> None:
        self.assertEqual(validate_manifest(self.manifest), [])
        self.assertEqual(len(self.manifest["paths"]), 2487)
        wave_one = [entry for entry in self.manifest["paths"] if entry["activation_wave"] == "1"]
        self.assertEqual(len(wave_one), 386)
        for entry in wave_one:
            with self.subTest(path=entry["path"]):
                status = entry["status"]
                self.assertIn(status, {"target", "active", "generated"})
                if status == "target":
                    self.assertEqual(entry["build_targets"], [])
                    self.assertEqual(entry["test_targets"], [])
                else:
                    self.assertTrue(entry["build_targets"])
                    self.assertTrue(entry["test_targets"])
                if entry["source_authority"] == "reviewed-generated":
                    self.assertEqual(status, "generated")
                if entry["source_authority"] == "hand-authored":
                    self.assertEqual(status, "active")

    def test_target_validation_never_falls_back_to_bazelisk(self) -> None:
        manifest = {
            "paths": [
                {
                    "path": "README.md",
                    "status": "active",
                    "build_targets": ["//:wave0"],
                    "test_targets": [],
                }
            ]
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "BUILD.bazel").write_text('filegroup(name = "wave0")\n', encoding="utf-8")
            with patch("verify_repository_path_manifest.shutil.which", return_value=None):
                errors = validate_declared_targets(manifest, root)
        self.assertEqual(
            errors,
            ["cannot prove target source membership without the pinned direct Bazel: //:wave0"],
        )

    def test_schema_validates_manifest(self) -> None:
        schema = json.loads(
            (REPO_ROOT / "docs/architecture/repository-path-manifest.schema.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertEqual(validate_manifest(self.manifest), [])
        invalid = json.loads(json.dumps(self.manifest))
        invalid["paths"][0]["unexpected"] = True
        invalid["paths"][1]["kind"] = "mystery"
        errors = validate_manifest(invalid)
        self.assertTrue(any("unexpected" in error for error in errors))
        self.assertTrue(any("mystery" in error for error in errors))

    def test_wave_zero_tool_inventory_and_labels(self) -> None:
        entries = {entry["path"]: entry for entry in self.manifest["paths"]}
        for path in (
            "tools/dev/bootstrap.py",
            "tools/dev/doctor.py",
            "tools/licenses/scan_licenses.py",
            "tools/licenses/generate_notices.py",
            "tools/generators/stub_catalog.yaml",
        ):
            self.assertEqual(entries[path]["status"], "active")
            self.assertEqual(entries[path]["build_targets"], ["//:wave0_governance_sources"])
            self.assertEqual(entries[path]["test_targets"], ["//:wave0_tests"])

    def test_path_specific_waves_and_semantic_owners(self) -> None:
        entries = {entry["path"]: entry for entry in self.manifest["paths"]}
        expected_waves = {
            "protocols/proto/mindclade/common/v1/identifiers.proto": "1",
            "data/contracts/source.py": "2S",
            "services/control_plane/cmd/control-plane/main.go": "2P",
            "protocols/schemas/feature_contract/feature_contract.schema.json": "3",
            "runtime/dispatch/execution_target.py": "4",
            "runtime/distributed/topology/topology_manifest.py": "5",
            "kernels/attention/benchmarks/benchmark_attention.py": "6",
            "agents/contracts/agent.py": "7",
            "sdk/typescript/src/client.ts": "8",
            "runtime/BUILD.bazel": "2S",
            "services/BUILD.bazel": "2P",
            "workers/BUILD.bazel": "2P",
            "sdk/BUILD.bazel": "2P",
            "tests/BUILD.bazel": "1",
            "deploy/BUILD.bazel": "1",
            "kits/BUILD.bazel": "7",
            "apps/console/BUILD.bazel": "7",
            "protocols/generated/python/BUILD.bazel": "1",
            "protocols/generated/rust/BUILD.bazel": "1",
            "protocols/generated/typescript/BUILD.bazel": "1",
            "kernels/tests/test_registry.py": "6",
            "kernels/tests/test_dispatch_fallback.py": "6",
            "kernels/pairformer/triangle_attention/dispatch.py": "6",
            "data/connectors/pdb/connector.py": "2S",
            "data/connectors/uniprot/connector.py": "8",
            "data/connectors/rnacentral/connector.py": "8",
            "data/connectors/ccd/connector.py": "8",
            "data/transforms/contracts/profiles/fitted.py": "3",
            "data/transforms/optimization/fusion.py": "6",
            "evaluation/suites/structure/structure_evaluator.py": "2S",
            "evaluation/suites/complexes/complex_evaluator.py": "8",
            "evaluation/suites/design/design_evaluator.py": "8",
            "evaluation/suites/safety/safety_evaluator.py": "8",
            "inference/batching/dynamic_batcher.py": "4",
            "inference/compilation/compiled_variant_cache.py": "6",
            "inference/ranking/candidate_ranker.py": "8",
            "training/providers/pytorch/native_engine.py": "2S",
            "training/providers/pytorch/fsdp2_adapter.py": "5",
            "training/providers/pytorch/dtensor_adapter.py": "5",
            "training/providers/pytorch/dcp_adapter.py": "5",
            "training/providers/pytorch/nccl_adapter.py": "5",
            "training/tasks/contrastive/task.py": "8",
            "training/tasks/flow/task.py": "8",
            "training/tasks/distillation/task.py": "8",
            "training/evaluation/snapshot.py": "2S",
            "training/evaluation/scheduling.py": "4",
            "training/evaluation/leases.py": "4",
            "training/evaluation/state.py": "4",
            "training/qualification/checkpointing/partial_load.py": "5",
            "training/qualification/recovery/resume_parity.py": "2S",
            "training/qualification/recovery/preemption.py": "5",
            "training/qualification/recovery/stale_attempt.py": "4",
            "protocols/schemas/step_capsule/step_capsule.schema.json": "5",
            "research/fixtures/synthetic_structure.cif": "8",
            "workers/inference_worker/python/batch_execution.py": "4",
            "protocols/proto/mindclade/inference/v1/inference_stream.proto": "4",
            "protocols/generated/rust/inference/v1/inference_request.rs": "8",
        }
        for path, wave in expected_waves.items():
            with self.subTest(path=path):
                self.assertEqual(entries[path]["activation_wave"], wave)
        self.assertEqual(
            entries["protocols/proto/mindclade/common/v1/identifiers.proto"]["owner"],
            "contract-governance",
        )
        self.assertEqual(
            entries["protocols/proto/mindclade/common/v1/identifiers.proto"]["component"],
            "proto-common-v1",
        )
        self.assertEqual(
            entries["evaluation/contracts/suite_contract.py"]["owner"], "evaluation-science"
        )
        self.assertEqual(
            entries["inference/contracts/request_contract.py"]["owner"], "inference-systems"
        )
        self.assertEqual(entries["training/core/trainer/trainer.py"]["owner"], "training-systems")
        self.assertEqual(entries["component.yaml"]["component"], "mindclade")
        self.assertEqual(entries["component.yaml"]["owner"], "product-engineering")
        expected_component_roots = {
            "libs/python/component.yaml": "libs-python",
            "bio/component.yaml": "bio",
            "runtime/component.yaml": "runtime",
            "models/component.yaml": "models",
            "kits/component.yaml": "kits",
            "deploy/component.yaml": "deploy",
            "services/control_plane/component.yaml": "services-control-plane",
            "workers/inference_worker/component.yaml": "workers-inference-worker",
            "sdk/python/component.yaml": "sdk-python",
            "apps/console/component.yaml": "apps-console",
        }
        for path, component in expected_component_roots.items():
            with self.subTest(component_path=path):
                self.assertEqual(entries[path]["component"], component)
        self.assertEqual(entries["bio/sequences/python/identity.py"]["component"], "bio")

    def test_build_and_schema_fixture_kinds_are_semantic(self) -> None:
        entries = {entry["path"]: entry for entry in self.manifest["paths"]}
        build_paths = [
            path
            for path in entries
            if Path(path).name in {"BUILD", "BUILD.bazel", "MODULE.bazel"}
            or Path(path).suffix == ".bzl"
        ]
        self.assertTrue(build_paths)
        self.assertTrue(all(entries[path]["kind"] == "build" for path in build_paths))
        self.assertEqual(
            entries["protocols/schemas/artifact_manifest/positive.json"]["kind"],
            "fixture",
        )
        self.assertEqual(
            entries["protocols/schemas/artifact_manifest/negative_missing_digest.json"]["kind"],
            "fixture",
        )
        self.assertEqual(
            entries["protocols/schemas/artifact_manifest/artifact_manifest.schema.json"]["kind"],
            "schema",
        )
        ratification = entries["docs/adr/connected-ratification.v1.schema.json"]
        self.assertEqual(ratification["kind"], "schema")
        self.assertEqual(ratification["status"], "active")
        self.assertEqual(ratification["activation_wave"], "0")
        founder_adr = entries["docs/adr/0008-founder-bootstrap-public-estate-transition.md"]
        founder_schema = entries["docs/governance/founder-bootstrap-exception.v1.schema.json"]
        founder_record = entries["docs/governance/exceptions/FBE-0001.yaml"]
        self.assertEqual(founder_adr["kind"], "documentation")
        self.assertEqual(founder_schema["kind"], "schema")
        self.assertEqual(founder_record["kind"], "configuration")
        self.assertEqual(
            {entry["status"] for entry in (founder_adr, founder_schema, founder_record)},
            {"active"},
        )
        self.assertEqual(
            {entry["activation_wave"] for entry in (founder_adr, founder_schema, founder_record)},
            {"0"},
        )
        self.assertEqual(
            entries["protocols/generated/typescript/package.json"]["kind"],
            "configuration",
        )
        self.assertEqual(
            entries["protocols/generated/typescript/package.json"]["source_authority"],
            "hand-authored",
        )
        self.assertEqual(
            entries["protocols/generated/rust/lib.rs"]["source_authority"],
            "reviewed-generated",
        )

    def test_authority_display_order_round_trips(self) -> None:
        paths = [entry["path"] for entry in self.manifest["paths"]]
        rendered = render_tree(paths)
        from path_policy import extract_authority_paths

        self.assertEqual(extract_authority_paths(f"```text\n{rendered}```\n"), paths)

    def test_component_schema_validation_is_full_and_fail_closed(self) -> None:
        schema = json.loads(
            (REPO_ROOT / "tools/repo/component.schema.json").read_text(encoding="utf-8")
        )
        component = load_yaml_or_json(REPO_ROOT / "component.yaml")
        self.assertEqual(validate_component_document(component, schema), [])
        invalid = json.loads(json.dumps(component))
        invalid["status"]["readiness"] = "DONE"
        invalid["metadata"]["unexpected"] = True
        self.assertTrue(
            any(
                "status/readiness" in error
                for error in validate_component_document(invalid, schema)
            )
        )
        self.assertTrue(
            any("unexpected" in error for error in validate_component_document(invalid, schema))
        )

    def test_codeowners_uses_last_matching_rule_for_each_active_path(self) -> None:
        manifest = json.loads(json.dumps(self.manifest))
        for entry in manifest["paths"]:
            entry["status"] = "target"
        readme = next(entry for entry in manifest["paths"] if entry["path"] == "README.md")
        readme["status"] = "active"
        with tempfile.TemporaryDirectory() as directory:
            codeowners = Path(directory) / "CODEOWNERS"
            codeowners.write_text(
                "* @mindclade/product-engineering\n"
                "/README.md @mindclade/developer-platform\n"
                "/README.md @mindclade/product-engineering\n",
                encoding="utf-8",
            )
            gaps = validate_owners(manifest, [], codeowners)
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0]["type"], "codeowners_path_owner_mismatch")
        self.assertEqual(gaps[0]["path"], "README.md")

    def test_normalization_rejects_tokens_and_parent_escape(self) -> None:
        for path in ("/absolute", "a/../b", "a/{b}.py", "a/<domain>.py", "a\\b"):
            with self.subTest(path=path), self.assertRaises(PolicyError):
                normalize_path(path)

    def test_populated_target_is_premature_and_unknown_is_rejected(self) -> None:
        manifest = json.loads(json.dumps(self.manifest))
        entry = manifest["paths"][0]
        entry["status"] = "target"
        entry["activation_criterion"] = "test"
        entry["build_targets"] = []
        entry["test_targets"] = []
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / entry["path"]
            target.parent.mkdir(parents=True)
            target.write_text("target", encoding="utf-8")
            (root / "unknown.txt").write_text("unknown", encoding="utf-8")
            drift = validate_populated_paths(manifest, root, allow_missing_active=True)
        self.assertEqual(drift["premature_paths"], [entry["path"]])
        self.assertEqual(drift["unknown_paths"], ["unknown.txt"])

    def test_path_discovery_falls_back_when_git_is_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "known.txt").write_text("known", encoding="utf-8")
            ignored = root / "__pycache__/ignored.pyc"
            ignored.parent.mkdir()
            ignored.write_bytes(b"ignored")
            with patch("path_policy.subprocess.run", side_effect=FileNotFoundError):
                paths = discover_actual_paths(root)
        self.assertEqual(paths, ["known.txt"])

    def test_graph_rejects_cycle_and_backward_compile_edge(self) -> None:
        components = [
            {
                "name": "contracts",
                "path": "protocols",
                "owner": "architecture",
                "dependencies": [
                    {
                        "component": "service",
                        "kind": "compile-api",
                        "visibility": "private",
                        "owner": "architecture",
                        "justification": "invalid fixture",
                        "scope": "normal",
                    }
                ],
            },
            {
                "name": "service",
                "path": "services/control_plane",
                "owner": "product-engineering",
                "dependencies": [
                    {
                        "component": "contracts",
                        "kind": "compile-api",
                        "visibility": "component",
                        "owner": "product-engineering",
                        "justification": "contract use",
                        "scope": "normal",
                    }
                ],
            },
        ]
        errors, _ = validate_dependency_graph(components)
        self.assertTrue(any("backward" in error for error in errors))
        self.assertTrue(any("cycle" in error for error in errors))

    def test_renderer_replaces_only_the_generated_region(self) -> None:
        paths = ["a/one.txt", "a/two.txt", "root.txt"]
        document = f"before\n{BEGIN_MARKER}\nstale\n{END_MARKER}\nafter\n"
        rendered = replace_generated_region(document, paths)
        self.assertTrue(rendered.startswith("before\n"))
        self.assertTrue(rendered.endswith("\nafter\n"))
        self.assertIn(render_fenced(paths), rendered)

    def test_stub_catalog_has_all_normative_profiles(self) -> None:
        catalog = json.loads(
            (REPO_ROOT / "tools/generators/stub_catalog.yaml").read_text(encoding="utf-8")
        )
        self.assertEqual(
            set(catalog["profiles"]),
            {
                "governed_component",
                "python_library",
                "rust_crate",
                "go_package",
                "typescript_package",
                "protobuf_event",
                "json_schema",
                "service_worker_image",
                "deployment_package",
                "documentation_index",
            },
        )


if __name__ == "__main__":
    unittest.main()
