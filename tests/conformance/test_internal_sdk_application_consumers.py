from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


def repository_root() -> Path:
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "internal/sdk").is_dir() and (candidate / "protocols").is_dir():
            return candidate
    raise RuntimeError("cannot locate repository root")


CONSUMER_SOURCES = {
    "go": (
        Path("tools/mindcladectl/command.go"),
        Path("tools/mindcladectl/live.go"),
        Path("tools/mindcladectl/cmd/main.go"),
    ),
    "python": (
        Path("examples/agent_workflow/simulate.py"),
        Path("examples/sdk/download_artifact.py"),
        Path("examples/sdk/submit_operation.py"),
        Path("workers/training_worker/python/control_plane.py"),
        Path("workers/training_worker/python/main.py"),
    ),
    "rust": (
        Path("workers/ingestion_worker/rust/src/lib.rs"),
        Path("workers/ingestion_worker/rust/src/main.rs"),
        Path("workers/ingestion_worker/rust/src/source_fetch.rs"),
    ),
    "typescript": (
        Path("apps/console/lib/control-plane.ts"),
        Path("apps/console/features/operations/operation-client.ts"),
        Path("apps/console/features/operations/operation-types.ts"),
        Path("examples/sdk/follow_operation.ts"),
    ),
}

DIRECT_GENERATED = {
    ".go": re.compile(r'"github\.com/mindclade/mindclade/protocols/generated/'),
    ".py": re.compile(r"(?m)^\s*(?:from|import)\s+mindclade\."),
    ".rs": re.compile(r"(?m)^\s*(?:pub\s+)?use\s+mindclade_protocols(?:::|\s*;)"),
    ".ts": re.compile(r"protocols/generated/typescript/"),
}

BACKEND_ESCAPE_HATCH = re.compile(
    r"(?:database/sql|cloud\.google\.com/go/(?:pubsub|storage)|google\.cloud\."
    r"(?:pubsub|storage)|psycopg|sqlalchemy|sqlx|tokio_postgres|"
    r"google_cloud_(?:pubsub|storage)|@google-cloud/(?:pubsub|storage))"
)


class InternalSdkApplicationConsumerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repository = repository_root()

    def test_every_runtime_path_imports_only_its_private_sdk(self) -> None:
        expected = {
            "go": "internal/sdk/go/mindclade",
            "python": "mindclade_internal_sdk",
            "rust": "mindclade_internal_sdk",
            "typescript": "@mindclade/internal-sdk",
        }
        for language, paths in CONSUMER_SOURCES.items():
            combined = "\n".join((self.repository / path).read_text() for path in paths)
            with self.subTest(language=language):
                self.assertIn(expected[language], combined)
                for path in paths:
                    source = (self.repository / path).read_text()
                    self.assertIsNone(DIRECT_GENERATED[path.suffix].search(source), path)
                    self.assertIsNone(BACKEND_ESCAPE_HATCH.search(source), path)

    def test_consumer_tests_also_stay_behind_sdk_fake_seams(self) -> None:
        test_paths = (
            Path("examples/agent_workflow/test_simulate.py"),
            Path("examples/sdk/follow_operation.test.ts"),
            Path("examples/sdk/test_sdk_examples.py"),
            Path("tools/mindcladectl/command_test.go"),
            Path("workers/training_worker/tests/test_control_plane.py"),
            Path("workers/ingestion_worker/rust/src/source_fetch.rs"),
            Path("apps/console/tests/operation-flow.test.ts"),
        )
        for path in test_paths:
            source = (self.repository / path).read_text()
            with self.subTest(path=path.as_posix()):
                self.assertIsNone(DIRECT_GENERATED[path.suffix].search(source))
                self.assertIsNone(BACKEND_ESCAPE_HATCH.search(source))

    def test_native_build_graphs_depend_on_sdk_not_generated_transports(self) -> None:
        build_files = (
            Path("examples/BUILD.bazel"),
            Path("tools/mindcladectl/BUILD.bazel"),
            Path("workers/training_worker/BUILD.bazel"),
            Path("workers/ingestion_worker/BUILD.bazel"),
            Path("apps/console/BUILD.bazel"),
        )
        for path in build_files:
            source = (self.repository / path).read_text()
            with self.subTest(path=path.as_posix()):
                self.assertIn("internal/sdk", source)
                self.assertNotIn("protocols/generated", source)

    def test_consumer_packages_are_private_and_provider_independent(self) -> None:
        console = json.loads((self.repository / "apps/console/package.json").read_text())
        self.assertTrue(console["private"])
        self.assertEqual(console["dependencies"], {"@mindclade/internal-sdk": "workspace:*"})
        examples = json.loads((self.repository / "examples/sdk/package.json").read_text())
        self.assertTrue(examples["private"])
        self.assertEqual(examples["dependencies"], {"@mindclade/internal-sdk": "workspace:*"})
        rust_manifest = (self.repository / "workers/ingestion_worker/Cargo.toml").read_text()
        self.assertIn("publish = false", rust_manifest)
        combined = json.dumps([console, examples], sort_keys=True) + rust_manifest
        for provider in ("fern", "oagen", "speakeasy", "stainless"):
            with self.subTest(provider=provider):
                self.assertNotIn(provider, combined.lower())


if __name__ == "__main__":
    unittest.main()
