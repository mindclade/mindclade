from __future__ import annotations

import importlib
import json
import re
import sys
import unittest
from collections import defaultdict
from pathlib import Path
from typing import Any

PACKAGE_PATTERN = re.compile(r"^package\s+(mindclade\.[A-Za-z0-9_.]+)\s*;", re.MULTILINE)
SERVICE_PATTERN = re.compile(r"^service\s+[A-Za-z][A-Za-z0-9_]*\s*\{", re.MULTILINE)
MESSAGE_PATTERN = re.compile(r"^message\s+([A-Za-z][A-Za-z0-9_]*)\s*\{", re.MULTILINE)
LANGUAGES = {"go", "python", "rust", "typescript"}
CLIENT_SOURCE_ROOTS = ("apps", "services", "tools", "training", "workers")
DIRECT_GENERATED_IMPORTS = {
    ".go": re.compile(
        r"(?m)^\s*(?:[A-Za-z_][A-Za-z0-9_]*\s+)?"
        r'"github\.com/mindclade/mindclade/protocols/generated/'
    ),
    ".py": re.compile(r"(?m)^\s*(?:from|import)\s+mindclade\."),
    ".rs": re.compile(r"(?m)^\s*(?:pub\s+)?use\s+mindclade_protocols(?:::|\s*;)"),
    ".ts": re.compile(r"(?m)^\s*import(?:\s+type)?\s+.*protocols/generated/typescript/"),
}

# Internal SDKs are client-side transport facades. Durable state, event
# delivery, and artifact object storage remain server-side capabilities and
# must never become an SDK escape hatch.
FORBIDDEN_SDK_CAPABILITIES = {
    ".go": re.compile(
        r'(?m)^\s*(?:[A-Za-z_][A-Za-z0-9_]*\s+)?"(?:database/sql|cloud\.google\.com/go/(?:pubsub|storage)(?:/|"))'
    ),
    ".py": re.compile(
        r"(?m)^\s*(?:from|import)\s+(?:google\.cloud\.(?:pubsub|storage)|psycopg|sqlalchemy)(?:\.|\s|$)"
    ),
    ".rs": re.compile(
        r"(?m)^\s*(?:pub\s+)?use\s+(?:sqlx|tokio_postgres|postgres|google_cloud_(?:pubsub|storage))(?:::|\s*;)"
    ),
    ".ts": re.compile(
        r'(?m)^\s*import(?:\s+type)?\s+.*["\'](?:pg|@google-cloud/(?:pubsub|storage))["\']'
    ),
}

HANDWRITTEN_WIRE_DEFINITIONS = {
    ".go": re.compile(r"(?m)^\s*type\s+({names})\s+struct\b"),
    ".py": re.compile(r"(?m)^\s*class\s+({names})\s*(?:\(|:)"),
    ".rs": re.compile(r"(?m)^\s*(?:pub(?:\([^)]*\))?\s+)?struct\s+({names})\b"),
    ".ts": re.compile(
        r"(?m)^\s*(?:export\s+)?(?:declare\s+)?(?:(?:class|interface)\s+({names})\b|type\s+({names})\s*=)"
    ),
}

EXPORTED_SQL_ROW = re.compile(r"(?m)^type\s+([A-Z][A-Za-z0-9_]*(?:Row|SQLRow))\s+struct\b")

PUBSUB_GO_IMPORT = re.compile(
    r'(?m)^\s*(?:[A-Za-z_][A-Za-z0-9_]*\s+)?"cloud\.google\.com/go/pubsub(?:/v[0-9]+)?"'
)


def root() -> Path:
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "protocols/generated/generated-files.manifest.json").is_file():
            return candidate
    raise RuntimeError("cannot locate generated protocol inventory")


def protobuf_sources(repository: Path) -> list[Path]:
    return sorted(
        [
            *(repository / "protocols/proto/mindclade").glob("**/*.proto"),
            *(repository / "protocols/events/mindclade").glob("**/*.proto"),
        ]
    )


def generated_stem(repository: Path, source: Path) -> Path:
    for source_root in (
        repository / "protocols/proto/mindclade",
        repository / "protocols/events/mindclade",
    ):
        if source.is_relative_to(source_root):
            return source.relative_to(source_root).with_suffix("")
    raise AssertionError(f"protobuf source is outside a generated source root: {source}")


def expected_generated_files(repository: Path) -> dict[str, set[str]]:
    expected: dict[str, set[str]] = {language: set() for language in LANGUAGES}
    for source in protobuf_sources(repository):
        stem = generated_stem(repository, source).as_posix()
        go_stem = (
            f"internalrpc/{stem.removeprefix('internal/')}"
            if stem.startswith("internal/")
            else stem
        )
        source_text = source.read_text()
        expected["go"].add(f"protocols/generated/go/{go_stem}.pb.go")
        expected["python"].update(
            {
                f"protocols/generated/python/mindclade/{stem}_pb2.py",
                f"protocols/generated/python/mindclade/{stem}_pb2.pyi",
            }
        )
        expected["rust"].add(f"protocols/generated/rust/{stem}.rs")
        expected["typescript"].add(f"protocols/generated/typescript/{stem}_pb.ts")
        if SERVICE_PATTERN.search(source_text):
            expected["go"].add(f"protocols/generated/go/{go_stem}_grpc.pb.go")
            expected["python"].update(
                {
                    f"protocols/generated/python/mindclade/{stem}_pb2_grpc.py",
                    f"protocols/generated/python/mindclade/{stem}_pb2_grpc.pyi",
                }
            )
            expected["rust"].add(f"protocols/generated/rust/{stem}_grpc.rs")
    return expected


def actual_generated_files(manifest_files: set[str]) -> dict[str, set[str]]:
    return {
        "go": {
            path
            for path in manifest_files
            if path.startswith("protocols/generated/go/") and path.endswith(".pb.go")
        },
        "python": {
            path
            for path in manifest_files
            if path.startswith("protocols/generated/python/mindclade/")
            and path.endswith(("_pb2.py", "_pb2.pyi", "_pb2_grpc.py", "_pb2_grpc.pyi"))
        },
        "rust": {
            path
            for path in manifest_files
            if path.startswith("protocols/generated/rust/")
            and path.endswith(".rs")
            and not path.startswith("protocols/generated/rust/schema/")
            and not path.endswith("/mod.rs")
            and path != "protocols/generated/rust/lib.rs"
        },
        "typescript": {
            path
            for path in manifest_files
            if path.startswith("protocols/generated/typescript/")
            and not path.startswith("protocols/generated/typescript/google/")
            and path.endswith("_pb.ts")
        },
    }


class GeneratedPackageConsumerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repository = root()
        cls.matrix = json.loads(
            (cls.repository / "tests/conformance/contract_matrix.yaml").read_text()
        )
        cls.manifest = json.loads(
            (cls.repository / "protocols/generated/generated-files.manifest.json").read_text()
        )

    def test_every_source_package_has_an_explicit_executable_consumer_profile(self) -> None:
        packages_by_source: dict[str, list[str]] = defaultdict(list)
        for source in protobuf_sources(self.repository):
            match = PACKAGE_PATTERN.search(source.read_text())
            self.assertIsNotNone(match, source)
            assert match is not None
            packages_by_source[match.group(1)].append(
                source.relative_to(self.repository).as_posix()
            )

        declarations = self.matrix["protobuf_packages"]
        declared_by_name = {item["name"]: item for item in declarations}
        self.assertEqual(len(declared_by_name), len(declarations), "duplicate package declaration")
        self.assertEqual(set(declared_by_name), set(packages_by_source))
        self.assertEqual(set(self.matrix["generated_languages"]), LANGUAGES)

        profiles: dict[str, dict[str, dict[str, str]]] = self.matrix["consumer_profiles"]
        build_source = (self.repository / "tests/BUILD.bazel").read_text()
        sys.path.insert(0, str(self.repository / "protocols/generated/python"))
        for package, declaration in declared_by_name.items():
            with self.subTest(package=package):
                self.assertEqual(declaration["compatibility"], "additive-only")
                profile_name = declaration["consumer_profile"]
                self.assertIn(profile_name, profiles)
                profile = profiles[profile_name]
                self.assertEqual(set(profile), LANGUAGES)
                for language, consumer in profile.items():
                    source = self.repository / consumer["source"]
                    self.assertTrue(source.is_file(), f"missing {language} consumer {source}")
                    target = consumer["target"]
                    self.assertRegex(target, r"^//tests:[a-z0-9_]+$")
                    target_name = target.split(":", 1)[1]
                    self.assertRegex(
                        build_source,
                        rf'(?m)^\s*name\s*=\s*"{re.escape(target_name)}",$',
                    )
                    self.assertIn(
                        consumer["mode"],
                        {
                            "native-compile",
                            "wire-roundtrip",
                            "wire-and-protojson-roundtrip",
                        },
                    )

                module = importlib.import_module(declaration["module"])
                message_type: Any = getattr(module, declaration["message"])
                self.assertEqual(message_type.DESCRIPTOR.file.package, package)

    def test_generated_language_estate_exactly_matches_source_inventory(self) -> None:
        expected = expected_generated_files(self.repository)
        actual = actual_generated_files(set(self.manifest["files"]))
        for language in sorted(LANGUAGES):
            with self.subTest(language=language):
                self.assertEqual(actual[language], expected[language])

    def test_generated_event_registry_has_a_runtime_consumer(self) -> None:
        registry = "protocols/generated/python/mindclade/events/registry.py"
        self.assertIn(registry, self.manifest["files"])
        serialization = (self.repository / "libs/python/serialization/protobuf_io.py").read_text()
        self.assertIn("from mindclade.events.registry import", serialization)
        self.assertIn("require_event_registration(", serialization)

    def test_internal_sdk_is_the_owned_client_facade_over_generated_transport(
        self,
    ) -> None:
        sdk = self.repository / "internal/sdk"
        required = {
            "go": sdk / "go/mindclade/BUILD.bazel",
            "python": sdk / "python/BUILD.bazel",
            "rust": sdk / "rust/BUILD.bazel",
            "typescript": sdk / "typescript/BUILD.bazel",
        }
        for language, build in required.items():
            with self.subTest(language=language):
                self.assertTrue(build.is_file(), f"missing {language} internal SDK")
                source = build.read_text()
                self.assertIn("protocols/generated", source)

        go_transport = (sdk / "go/mindclade/transport.go").read_text()
        internal_packages = {
            package.removeprefix("mindclade.internal.").removesuffix(".v1")
            for package in (declaration["name"] for declaration in self.matrix["protobuf_packages"])
            if package.startswith("mindclade.internal.")
        }
        for package in internal_packages:
            with self.subTest(go_transport=package):
                self.assertIn(
                    f"protocols/generated/go/internalrpc/{package}/v1",
                    go_transport,
                )

    def test_client_source_roots_do_not_bypass_the_internal_sdk(self) -> None:
        violations: list[str] = []
        for root_name in CLIENT_SOURCE_ROOTS:
            source_root = self.repository / root_name
            if not source_root.is_dir():
                continue
            for path in sorted(source_root.glob("**/*")):
                matcher = DIRECT_GENERATED_IMPORTS.get(path.suffix)
                if matcher is None or not path.is_file():
                    continue
                relative = path.relative_to(self.repository).as_posix()
                if (
                    relative.startswith("services/control_plane/internal/")
                    or relative.startswith("services/control_plane/cmd/control-plane/")
                    or relative.startswith("services/control_plane/tests/")
                    or relative.startswith("tools/codegen/")
                    or relative.startswith("tools/repo/")
                ):
                    continue
                if matcher.search(path.read_text()):
                    violations.append(relative)
        self.assertEqual(
            violations,
            [],
            "client-side code must import internal/sdk; direct generated imports "
            "are limited to SDK implementations, server adapters, persistence "
            f"mappers, and contract tests: {violations}",
        )

    def test_internal_sdk_cannot_access_durable_backend_capabilities(self) -> None:
        violations: list[str] = []
        sdk_root = self.repository / "internal/sdk"
        for path in sorted(sdk_root.glob("**/*")):
            matcher = FORBIDDEN_SDK_CAPABILITIES.get(path.suffix)
            if matcher is None or not path.is_file():
                continue
            relative = path.relative_to(self.repository).as_posix()
            if matcher.search(path.read_text()):
                violations.append(relative)
        self.assertEqual(
            violations,
            [],
            "internal SDKs may use generated RPC transports only; PostgreSQL, "
            f"Pub/Sub, and GCS clients are server-side capabilities: {violations}",
        )

    def test_backend_implementations_do_not_depend_on_internal_sdk(self) -> None:
        violations: list[str] = []
        backend_roots = (
            self.repository / "services/control_plane",
            self.repository / "libs/go",
        )
        for source_root in backend_roots:
            for path in sorted(source_root.glob("**/*")):
                if path.suffix not in {".go", ".py", ".rs", ".ts"} or not path.is_file():
                    continue
                if "internal/sdk" in path.read_text():
                    violations.append(path.relative_to(self.repository).as_posix())
        self.assertEqual(
            violations,
            [],
            "server implementations, persistence, outbox, and inbox consume "
            f"generated contracts directly and must not import the client SDK: {violations}",
        )

    def test_sql_row_structures_remain_private(self) -> None:
        violations: list[str] = []
        persistence_root = self.repository / "services/control_plane/internal"
        for path in sorted(persistence_root.glob("**/*.go")):
            matches = EXPORTED_SQL_ROW.findall(path.read_text())
            if matches:
                relative = path.relative_to(self.repository).as_posix()
                violations.extend(f"{relative}:{name}" for name in matches)
        self.assertEqual(
            violations,
            [],
            "normalized SQL row structures are private persistence details and "
            f"cannot become exported service contracts: {violations}",
        )

    def test_pubsub_clients_are_confined_to_delivery_runtime_and_wiring(self) -> None:
        allowed = {
            "services/control_plane/cmd/control-plane/main.go",
            "services/control_plane/internal/platform/inbox/inbox_store.go",
            "services/control_plane/internal/platform/outbox/dispatcher.go",
        }
        violations: list[str] = []
        control_plane = self.repository / "services/control_plane"
        for path in sorted(control_plane.glob("**/*.go")):
            relative = path.relative_to(self.repository).as_posix()
            if PUBSUB_GO_IMPORT.search(path.read_text()) and relative not in allowed:
                violations.append(relative)
        self.assertEqual(
            violations,
            [],
            "domain transactions must persist outbox events instead of publishing "
            f"directly to Pub/Sub; provider clients are delivery adapters: {violations}",
        )

    def test_authoritative_wire_models_are_not_handwritten_again(self) -> None:
        authoritative_names = {
            name
            for source in protobuf_sources(self.repository)
            for name in MESSAGE_PATTERN.findall(source.read_text())
        }
        self.assertGreater(
            len(authoritative_names),
            100,
            "authoritative message inventory is unexpectedly incomplete",
        )
        names = "|".join(re.escape(name) for name in sorted(authoritative_names))
        matchers = {
            suffix: re.compile(pattern.pattern.format(names=names), pattern.flags)
            for suffix, pattern in HANDWRITTEN_WIRE_DEFINITIONS.items()
        }
        excluded_parts = {
            ".git",
            ".venv",
            "build",
            "bazel-bin",
            "bazel-mindclade",
            "bazel-out",
            "bazel-testlogs",
            "node_modules",
            "dist",
            "target",
        }
        violations: list[str] = []
        for path in sorted(self.repository.glob("**/*")):
            matcher = matchers.get(path.suffix)
            if matcher is None or not path.is_file():
                continue
            relative = path.relative_to(self.repository)
            if excluded_parts.intersection(relative.parts):
                continue
            if relative.is_relative_to(Path("protocols/generated")):
                continue
            if matcher.search(path.read_text()):
                violations.append(relative.as_posix())
        self.assertEqual(
            violations,
            [],
            "protobuf owns shared resource/event wire models; handwritten "
            f"duplicates are forbidden: {violations}",
        )


if __name__ == "__main__":
    unittest.main()
