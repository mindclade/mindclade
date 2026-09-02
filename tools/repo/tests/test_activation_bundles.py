#!/usr/bin/env python3.12
"""Contract tests for declarative repository activation bundles."""

from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "tools/repo"))

from path_policy import (  # noqa: E402
    ACTIVATION_BUNDLE_MANIFEST_PATH,
    ACTIVATION_BUNDLE_PATH_SET_SHA256,
    ACTIVATION_BUNDLE_PROJECTION,
    ACTIVATION_BUNDLE_PROJECTION_PATH,
    ACTIVATION_BUNDLE_SEQUENCE_SHA256,
    ACTIVATION_BUNDLES,
    ALL_CONTRACT_GRPC_ADDITIONS,
    ALL_CONTRACT_GRPC_PACKAGE_PATHS,
    ALL_CONTRACT_GRPC_PROJECTION_PATHS,
    ALL_CONTRACT_GRPC_SOURCE_PATHS,
    ALL_CONTRACT_PYTHON_STUB_PATHS,
    VERTICAL_EVENT_CONTRACT_ADDITIONS,
    VERTICAL_EVENT_CONTRACTS,
    PolicyError,
    activation_bundle_paths,
    extract_authority_paths,
    load_activation_bundles,
    main,
    reconcile_authority_paths,
    validate_activation_bundle_projection,
)


class ActivationBundlePolicyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.document = json.loads(ACTIVATION_BUNDLE_MANIFEST_PATH.read_text(encoding="utf-8"))

    def _write_document(self, document: object, directory: str) -> Path:
        path = Path(directory) / "activation-bundles.yaml"
        path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
        return path

    def test_reviewed_projection_is_current_and_fully_bound(self) -> None:
        self.assertEqual(validate_activation_bundle_projection(), [])
        self.assertEqual(len(ACTIVATION_BUNDLES), 27)
        self.assertEqual(ACTIVATION_BUNDLE_PROJECTION["bundle_count"], 27)
        self.assertEqual(ACTIVATION_BUNDLE_PROJECTION["path_count"], 911)
        self.assertEqual(
            ACTIVATION_BUNDLE_PROJECTION["source_digest"],
            "sha256:9bf2bec3f980719d23e9730ff6dd0f912564ad023e381ea9c754dffd4465a96b",
        )
        self.assertEqual(
            ACTIVATION_BUNDLE_PROJECTION["path_set_digest"],
            "sha256:24e259349e0f667429fb11cb87bf06cd45fa6443378ef3e40589ce2447fdd5ea",
        )

        paths = [path for bundle in ACTIVATION_BUNDLES for path in bundle.paths]
        self.assertEqual(len(paths), len(set(paths)))
        self.assertEqual(
            {bundle.constant for bundle in ACTIVATION_BUNDLES},
            set(ACTIVATION_BUNDLE_PATH_SET_SHA256),
        )
        for bundle in ACTIVATION_BUNDLES:
            with self.subTest(bundle=bundle.identity):
                self.assertEqual(
                    activation_bundle_paths(bundle.constant),
                    bundle.addition_paths,
                )
                self.assertEqual(len(bundle.paths), bundle.path_count)
                self.assertRegex(bundle.path_set_sha256, r"^[0-9a-f]{64}$")
                self.assertRegex(bundle.sequence_sha256, r"^[0-9a-f]{64}$")
        runtime_consumers = next(
            bundle for bundle in ACTIVATION_BUNDLES if bundle.identity == "sdk-runtime-consumers"
        )
        self.assertEqual(runtime_consumers.path_count, 32)
        self.assertEqual(len(runtime_consumers.addition_paths), 16)
        self.assertEqual(len(runtime_consumers.predeclared_paths), 16)
        stage8_examples = next(
            bundle
            for bundle in ACTIVATION_BUNDLES
            if bundle.identity == "stage8-private-sdk-examples"
        )
        self.assertEqual(stage8_examples.path_count, 19)
        self.assertEqual(len(stage8_examples.addition_paths), 12)
        self.assertEqual(len(stage8_examples.predeclared_paths), 7)

    def test_existing_grpc_and_event_projections_preserve_semantics(self) -> None:
        self.assertEqual(
            ALL_CONTRACT_GRPC_ADDITIONS,
            (
                *ALL_CONTRACT_PYTHON_STUB_PATHS,
                *ALL_CONTRACT_GRPC_SOURCE_PATHS,
                *ALL_CONTRACT_GRPC_PROJECTION_PATHS,
                *ALL_CONTRACT_GRPC_PACKAGE_PATHS,
            ),
        )
        expected_events = tuple(
            path
            for domain, stem in VERTICAL_EVENT_CONTRACTS
            for path in (
                f"protocols/events/mindclade/{domain}/v1/{stem}.proto",
                f"protocols/generated/go/{domain}/v1/{stem}.pb.go",
                f"protocols/generated/python/mindclade/{domain}/v1/{stem}_pb2.py",
                f"protocols/generated/python/mindclade/{domain}/v1/{stem}_pb2.pyi",
                f"protocols/generated/rust/{domain}/v1/{stem}.rs",
                f"protocols/generated/typescript/{domain}/v1/{stem}_pb.ts",
            )
        )
        self.assertEqual(VERTICAL_EVENT_CONTRACT_ADDITIONS, expected_events)
        self.assertEqual(
            ACTIVATION_BUNDLE_SEQUENCE_SHA256["ALL_CONTRACT_GRPC_ADDITIONS"],
            "b178265f274e8f28b3c3422b251b99140a4c0d75ecb04a89beac2474d3b888be",
        )
        self.assertEqual(
            ACTIVATION_BUNDLE_SEQUENCE_SHA256["VERTICAL_EVENT_CONTRACT_ADDITIONS"],
            "a2cb15b1734c3b2444e3b5e20e9184175b5b12b78acee7b017ad2fbe03653656",
        )

    def test_digest_calculation_is_independent_of_projection_implementation(self) -> None:
        all_paths = [path for bundle in ACTIVATION_BUNDLES for path in bundle.paths]
        expected = hashlib.sha256(("\n".join(sorted(all_paths)) + "\n").encode()).hexdigest()
        self.assertEqual(
            ACTIVATION_BUNDLE_PROJECTION["path_set_digest"],
            f"sha256:{expected}",
        )

    def test_duplicate_path_across_bundles_fails_closed(self) -> None:
        invalid = copy.deepcopy(self.document)
        invalid["bundles"][1]["paths"].append(invalid["bundles"][0]["paths"][0])
        with tempfile.TemporaryDirectory() as directory:
            path = self._write_document(invalid, directory)
            with self.assertRaisesRegex(PolicyError, "declared by both"):
                load_activation_bundles(path)

    def test_duplicate_bundle_identity_and_constant_fail_closed(self) -> None:
        for field in ("id", "constant"):
            with self.subTest(field=field):
                invalid = copy.deepcopy(self.document)
                invalid["bundles"][1][field] = invalid["bundles"][0][field]
                with tempfile.TemporaryDirectory() as directory:
                    path = self._write_document(invalid, directory)
                    with self.assertRaisesRegex(
                        PolicyError, f"duplicate activation bundle {field}"
                    ):
                        load_activation_bundles(path)

    def test_noncanonical_and_implicit_paths_fail_closed(self) -> None:
        for invalid_path in ("/absolute", "a/../b", "a/*.py", "a/{domain}.py", "a\\b"):
            with self.subTest(path=invalid_path):
                invalid = copy.deepcopy(self.document)
                invalid["bundles"][0]["paths"][0] = invalid_path
                with tempfile.TemporaryDirectory() as directory:
                    path = self._write_document(invalid, directory)
                    with self.assertRaises(PolicyError):
                        load_activation_bundles(path)

    def test_schema_unknown_field_and_authority_mismatch_fail_closed(self) -> None:
        invalid_field = copy.deepcopy(self.document)
        invalid_field["bundles"][0]["implicit_prefix"] = "internal/sdk/"
        mismatch = copy.deepcopy(self.document)
        mismatch["bundles"][0]["authority"] = "docs/adr/0004-contract-and-codegen-authority.md"
        for invalid, finding in (
            (invalid_field, "implicit_prefix"),
            (mismatch, "authority must match"),
        ):
            with self.subTest(finding=finding), tempfile.TemporaryDirectory() as directory:
                path = self._write_document(invalid, directory)
                with self.assertRaisesRegex(PolicyError, finding):
                    load_activation_bundles(path)

    def test_predeclared_paths_must_be_part_of_the_bundle_surface(self) -> None:
        invalid = copy.deepcopy(self.document)
        bundle = next(bundle for bundle in invalid["bundles"] if "predeclared_paths" in bundle)
        bundle["predeclared_paths"].append("not/in/bundle.txt")
        with tempfile.TemporaryDirectory() as directory:
            path = self._write_document(invalid, directory)
            with self.assertRaisesRegex(PolicyError, "predeclared_paths are absent from paths"):
                load_activation_bundles(path)

    def test_predeclared_paths_must_exist_in_predecessor_authority(self) -> None:
        authority_path = REPO_ROOT / "docs/architecture/blueprint/provenance/MONOREPO_TREE.md"
        source_paths = extract_authority_paths(authority_path.read_text(encoding="utf-8"))
        source_paths.remove("apps/console/BUILD.bazel")
        with self.assertRaisesRegex(
            PolicyError,
            "predeclared paths are absent from source authority",
        ):
            reconcile_authority_paths(source_paths)

    def test_missing_schema_and_unknown_constant_fail_closed(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            self.assertRaisesRegex(PolicyError, "cannot load activation bundle schema"),
        ):
            load_activation_bundles(
                ACTIVATION_BUNDLE_MANIFEST_PATH,
                Path(directory) / "missing.schema.json",
            )
        with self.assertRaisesRegex(PolicyError, "unknown activation bundle constant"):
            activation_bundle_paths("NOT_DECLARED")

    def test_stale_projection_is_rejected_and_cli_reproduces_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            stale = Path(directory) / "stale.json"
            stale.write_text("{}\n", encoding="utf-8")
            self.assertEqual(len(validate_activation_bundle_projection(stale)), 1)

            generated = Path(directory) / "projection.json"
            self.assertEqual(
                main(["--write-activation-projection", "--output", str(generated)]),
                0,
            )
            self.assertEqual(
                json.loads(generated.read_text(encoding="utf-8")),
                ACTIVATION_BUNDLE_PROJECTION,
            )
            self.assertNotEqual(generated, ACTIVATION_BUNDLE_PROJECTION_PATH)


if __name__ == "__main__":
    unittest.main()
