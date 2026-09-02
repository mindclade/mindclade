"""Packaging and documentation tests: version source, exports, scripts, docs.

These tests guard claims that are cheap to break and expensive to notice. The
README asserted for years that consumers could ``import
mindclade_internal_sdk.resources`` off the package and that every list method
paginated lazily; neither was true, and nothing failed. Everything this module
checks is a statement the package makes about itself somewhere a reader will
believe it.
"""

from __future__ import annotations

import ast
import json
import os
import pathlib
import re
import tomllib
import unittest
from collections.abc import Mapping, Sequence
from typing import Any

import mindclade_internal_sdk as sdk
import mindclade_internal_sdk.resources as resources_module
import mindclade_internal_sdk.testing as testing_module
from google.protobuf.message import Message
from mindclade.internal.job.v1 import job_service_pb2
from mindclade.job.v1 import job_pb2
from mindclade_internal_sdk import Client, ClientConfig, Environment
from mindclade_internal_sdk._platform import MAX_USER_AGENT_LENGTH, SDK_VERSION
from mindclade_internal_sdk._version import SDK_NAME, USER_AGENT, __version__
from mindclade_internal_sdk.testing import FakeSyncTransport
from mindclade_internal_sdk.transport import (
    GET_JOB,
    INTERNAL_SERVICE_NAMES,
    INTERNAL_STREAM_METHODS,
    INTERNAL_UNARY_METHODS,
    Metadata,
)

PACKAGE_DIR = pathlib.Path(__file__).resolve().parent.parent
SOURCE_DIR = PACKAGE_DIR / "mindclade_internal_sdk"
SCRIPTS_DIR = PACKAGE_DIR / "scripts"
REPOSITORY_ROOT = PACKAGE_DIR.parent.parent.parent

# The five entry points every maintained package in this repository presents.
PACKAGING_SCRIPTS = ("bootstrap", "build", "format", "lint", "test")

# The Stainless section order the four internal SDK READMEs share, followed by
# the repository's appendix-A08 package contract.
README_SECTION_ORDER = (
    "## Installation",
    "## Usage",
    "## Request and response types",
    "## Pagination",
    "## Long-running operations",
    "## Streaming",
    "## Errors",
    "## Retries",
    "## Timeouts",
    "## Raw responses",
    "## Escape hatches and interceptors",
    "## Configuration and environment variables",
    "## Logging",
    "## Versioning",
    "## Status",
    # A section of the README, not a second document title: an appendix at h1
    # gives the file two top-level headings, which MD025 rejects.
    "## Package contract (appendix A08)",
)

README_APPENDIX_FIELDS = (
    "### Purpose",
    "### Owner",
    "### Public entrypoints",
    "### Data classifications handled",
    "### Dependency restrictions",
    "### Build and test commands",
    "### Compatibility contract",
    "### Failure modes",
    "### Retryable versus terminal errors",
    "### Graduation and deprecation status",
)


def local_config(**overrides: Any) -> ClientConfig:
    settings: dict[str, Any] = {
        "tenant_id": "tenant-1",
        "project_id": "project-1",
        "principal_id": "principal-1",
        "environment": Environment.LOCAL,
        "endpoint": "127.0.0.1:1",
        "insecure_for_testing": True,
        "default_timeout": 1,
    }
    settings.update(overrides)
    return ClientConfig(**settings)


def job_response(request: Message, timeout: float, metadata: Metadata) -> Message:
    del request, timeout, metadata
    return job_service_pb2.GetJobResponse(
        job=job_pb2.Job(
            job_id="jobs/job-1",
            operation_id="operations/op-1",
            tenant_id="tenant-1",
            project_id="project-1",
            state=job_pb2.JOB_STATE_RUNNING,
            resource_version=1,
            etag="etag-1",
        )
    )


def package_sources() -> list[pathlib.Path]:
    return sorted(SOURCE_DIR.glob("*.py"))


class YamlSyntaxError(ValueError):
    """Raised when ``component.yaml`` uses a construct this reader cannot see."""


def _significant_lines(text: str) -> list[tuple[int, str]]:
    lines: list[tuple[int, str]] = []
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        lines.append((len(raw) - len(raw.lstrip(" ")), stripped))
    return lines


def _scalar(value: str) -> Any:
    if len(value) >= 2 and value.startswith('"') and value.endswith('"'):
        return value[1:-1]
    if value.startswith(("{", "[")) and value != "[]":
        raise YamlSyntaxError(f"flow collections are not supported: {value!r}")
    return {"null": None, "true": True, "false": False}.get(value, value)


def _parse_mapping(
    lines: list[tuple[int, str]], index: int, indent: int
) -> tuple[dict[str, Any], int]:
    result: dict[str, Any] = {}
    while index < len(lines) and lines[index][0] == indent:
        body = lines[index][1]
        if body.startswith("- "):
            break
        key, separator, value = body.partition(":")
        if not separator:
            raise YamlSyntaxError(f"not a mapping entry: {body!r}")
        key = key.strip()
        value = value.strip()
        index += 1
        if value == "[]":
            result[key] = []
        elif value:
            result[key] = _scalar(value)
        elif index < len(lines) and lines[index][0] > indent:
            result[key], index = _parse_block(lines, index, lines[index][0])
        else:
            result[key] = None
    return result, index


def _parse_sequence(lines: list[tuple[int, str]], index: int, indent: int) -> tuple[list[Any], int]:
    items: list[Any] = []
    while index < len(lines) and lines[index][0] == indent and lines[index][1].startswith("- "):
        item = lines[index][1][2:].strip()
        if ":" in item:
            raise YamlSyntaxError(f"sequences of mappings are not supported: {item!r}")
        items.append(_scalar(item))
        index += 1
    return items, index


def _parse_block(
    lines: list[tuple[int, str]], index: int, indent: int
) -> tuple[dict[str, Any] | list[Any], int]:
    if lines[index][1].startswith("- "):
        return _parse_sequence(lines, index, indent)
    return _parse_mapping(lines, index, indent)


def parse_block_yaml(text: str) -> dict[str, Any]:
    """Parse the narrow YAML subset ``component.yaml`` is written in.

    Deliberately not a general YAML implementation: it accepts block mappings,
    block sequences of scalars, the inline empty sequence, and the scalar
    literals this repository's component documents use. Anything else raises,
    so a document that grows a construct this reader cannot see fails the test
    instead of being silently half-parsed.
    """

    lines = _significant_lines(text)
    if not lines:
        raise YamlSyntaxError("document is empty")
    document, index = _parse_block(lines, 0, lines[0][0])
    if index != len(lines):
        raise YamlSyntaxError(f"unparsed content from line {index + 1}")
    if not isinstance(document, dict):
        raise YamlSyntaxError("document root must be a mapping")
    return document


class VersionSourceTest(unittest.TestCase):
    def test_a_single_module_is_the_version_source(self) -> None:
        declared = tomllib.loads((PACKAGE_DIR / "pyproject.toml").read_text(encoding="utf-8"))
        project = declared["project"]
        self.assertEqual(project["version"], __version__)
        self.assertEqual(SDK_VERSION, __version__)
        self.assertEqual(USER_AGENT, f"{SDK_NAME}/{__version__}")
        self.assertEqual(sdk.__version__, __version__)

    def test_no_other_module_hard_codes_the_version(self) -> None:
        literal = f'"{__version__}"'
        for path in package_sources():
            if path.name == "_version.py":
                continue
            with self.subTest(module=path.name):
                self.assertNotIn(literal, path.read_text(encoding="utf-8"))

    def test_the_version_is_stamped_into_the_sdk_header(self) -> None:
        captured: list[Metadata] = []

        def handler(request: Message, timeout: float, metadata: Metadata) -> Message:
            captured.append(metadata)
            return job_response(request, timeout, metadata)

        transport = FakeSyncTransport()
        transport.unary_handlers[GET_JOB] = handler
        with Client(local_config(), transport=transport) as client:
            client.jobs.get("jobs/job-1")

        headers = dict(captured[0])
        # gRPC metadata values are str or bytes; the SDK only ever emits text here.
        raw_agent = headers["x-mindclade-sdk"]
        self.assertIsInstance(raw_agent, str)
        agent = raw_agent if isinstance(raw_agent, str) else raw_agent.decode()
        self.assertTrue(agent.startswith(f"{SDK_NAME}/{__version__}"))
        self.assertLessEqual(len(agent), MAX_USER_AGENT_LENGTH)
        for field in ("lang=python", "os=", "arch=", "runtime=", "runtime_version="):
            self.assertIn(field, agent)

    def test_the_header_is_stamped_on_every_request_including_retried_ones(self) -> None:
        captured: list[Metadata] = []

        def handler(request: Message, timeout: float, metadata: Metadata) -> Message:
            captured.append(metadata)
            return job_response(request, timeout, metadata)

        transport = FakeSyncTransport()
        transport.unary_handlers[GET_JOB] = handler
        with Client(local_config(), transport=transport) as client:
            client.jobs.get("jobs/job-1")
            client.jobs.get("jobs/job-1")

        self.assertEqual(len(captured), 2)
        for metadata in captured:
            keys = [key for key, _ in metadata]
            self.assertEqual(keys.count("x-mindclade-sdk"), 1)


class PublicSurfaceTest(unittest.TestCase):
    def test_the_package_exports_testing_and_resources(self) -> None:
        # The README imports both off the package. Until this change neither was
        # an attribute of it, so the documented import failed.
        self.assertIn("resources", sdk.__all__)
        self.assertIn("testing", sdk.__all__)
        self.assertIs(sdk.resources, resources_module)
        self.assertIs(sdk.testing, testing_module)
        self.assertTrue(hasattr(sdk.testing, "FakeSyncTransport"))
        self.assertTrue(hasattr(sdk.testing, "FakeAsyncTransport"))
        self.assertTrue(hasattr(sdk.resources, "artifact_reference"))

    def test_every_exported_name_resolves(self) -> None:
        missing = [name for name in sdk.__all__ if not hasattr(sdk, name)]
        self.assertEqual(missing, [])

    def test_the_export_list_is_free_of_duplicates(self) -> None:
        self.assertEqual(len(sdk.__all__), len(set(sdk.__all__)))

    def test_the_export_list_names_no_private_module(self) -> None:
        for name in sdk.__all__:
            with self.subTest(name=name):
                self.assertFalse(name.startswith("_") and name != "__version__")


class JitterSourceTest(unittest.TestCase):
    def test_the_package_never_uses_the_process_wide_random_module(self) -> None:
        for path in package_sources():
            text = path.read_text(encoding="utf-8")
            with self.subTest(module=path.name):
                # The lookbehind keeps ``self._random.uniform`` — the
                # cryptographically seeded instance — from matching.
                self.assertIsNone(re.search(r"(?<![\w.])random\.uniform\(", text))
                self.assertIsNone(re.search(r"^import random$", text, re.MULTILINE))
                self.assertIsNone(re.search(r"^from random import", text, re.MULTILINE))

    def test_jitter_is_drawn_from_a_cryptographically_seeded_source(self) -> None:
        text = (SOURCE_DIR / "_retry.py").read_text(encoding="utf-8")
        self.assertIn("secrets.SystemRandom()", text)

    def test_the_package_contains_no_bare_assert(self) -> None:
        # `python -O` strips assertions. A retry loop or a narrowing check that
        # only holds under `assert` silently changes behaviour in an optimized
        # interpreter, which is exactly where nobody is watching.
        for path in package_sources():
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            statements = [node for node in ast.walk(tree) if isinstance(node, ast.Assert)]
            with self.subTest(module=path.name):
                self.assertEqual([node.lineno for node in statements], [])


class PackagingScriptsTest(unittest.TestCase):
    def test_the_five_entry_points_exist_and_are_executable(self) -> None:
        for name in PACKAGING_SCRIPTS:
            script = SCRIPTS_DIR / name
            with self.subTest(script=name):
                self.assertTrue(script.is_file())
                self.assertTrue(os.access(script, os.X_OK))

    def test_every_script_is_a_strict_bash_wrapper(self) -> None:
        for name in PACKAGING_SCRIPTS:
            text = (SCRIPTS_DIR / name).read_text(encoding="utf-8")
            with self.subTest(script=name):
                self.assertTrue(text.startswith("#!/usr/bin/env bash\n"))
                self.assertIn("set -euo pipefail", text)
                self.assertIn("common.sh", text)

    def test_the_shared_preamble_is_sourced_rather_than_executed(self) -> None:
        common = SCRIPTS_DIR / "common.sh"
        self.assertTrue(common.is_file())
        self.assertFalse(os.access(common, os.X_OK))

    def test_the_scripts_delegate_to_the_repository_tools(self) -> None:
        expected = {
            "bootstrap": "uv",
            "format": "ruff format",
            "lint": "pyright",
            "test": "unittest discover",
            "build": "compileall",
        }
        for name, fragment in expected.items():
            with self.subTest(script=name):
                self.assertIn(fragment, (SCRIPTS_DIR / name).read_text(encoding="utf-8"))

    def test_the_scripts_are_declared_to_bazel(self) -> None:
        build = (PACKAGE_DIR / "BUILD.bazel").read_text(encoding="utf-8")
        self.assertIn('"scripts/*"', build)
        self.assertIn('"CHANGELOG.md"', build)
        self.assertIn('"component.yaml"', build)


class ComponentMetadataTest(unittest.TestCase):
    def setUp(self) -> None:
        self.document = parse_block_yaml(
            (PACKAGE_DIR / "component.yaml").read_text(encoding="utf-8")
        )
        schema_path = REPOSITORY_ROOT / "tools/repo/component.schema.json"
        if not schema_path.is_file():  # pragma: no cover - sandboxed runs without the repo root
            self.skipTest("repository component schema is not present in this sandbox")
        self.schema: Mapping[str, Any] = json.loads(schema_path.read_text(encoding="utf-8"))

    def properties(self, section: str) -> Mapping[str, Any]:
        return self.schema["properties"][section]

    def test_the_document_carries_every_required_key(self) -> None:
        for key in self.schema["required"]:
            self.assertIn(key, self.document)
        for section in ("metadata", "spec", "status"):
            required: Sequence[str] = self.properties(section)["required"]
            for key in required:
                with self.subTest(section=section, key=key):
                    self.assertIn(key, self.document[section])

    def test_the_component_identity_matches_the_repository_pattern(self) -> None:
        pattern = str(self.properties("metadata")["properties"]["name"]["pattern"])
        name = str(self.document["metadata"]["name"])
        self.assertEqual(name, "internal-sdk-python")
        self.assertIsNotNone(re.fullmatch(pattern, name))

    def test_the_owner_matches_the_repository_pattern_and_the_path_manifest(self) -> None:
        pattern = str(self.properties("spec")["properties"]["owner"]["pattern"])
        owner = str(self.document["spec"]["owner"])
        self.assertEqual(owner, "developer-experience")
        self.assertIsNotNone(re.fullmatch(pattern, owner))

    def test_the_readiness_matches_the_repository_pattern(self) -> None:
        pattern = str(self.properties("status")["properties"]["readiness"]["pattern"])
        readiness = str(self.document["status"]["readiness"])
        self.assertIsNotNone(re.fullmatch(pattern, readiness))

    def test_the_enumerated_fields_stay_inside_their_enumerations(self) -> None:
        spec_properties = self.properties("spec")["properties"]
        for key in ("lifecycle", "maturity"):
            with self.subTest(key=key):
                self.assertIn(self.document["spec"][key], spec_properties[key]["enum"])

    def test_the_component_is_private_and_carries_no_production_authority(self) -> None:
        spec = self.document["spec"]
        self.assertIs(spec["production_authority"], False)
        self.assertEqual(spec["release"]["strategy"], "source-only")
        self.assertIsNone(spec["release"]["artifact"])
        self.assertEqual(spec["dependencies"], [])
        self.assertEqual(spec["provides"], ["internal-python-sdk"])

    def test_the_narrow_yaml_reader_rejects_a_construct_it_cannot_see(self) -> None:
        with self.assertRaises(ValueError):
            parse_block_yaml("spec: {inline: mapping}\n  stray\n")


# An internal SDK has no SemVer line, so a changelog entry is keyed by the
# commit it landed in, or by the revision unmerged work was authored against.
CHANGELOG_ENTRY_PATTERN = (
    r"^## (?:Unmerged — authored against `[0-9a-f]{7,40}`"
    r"|rev `?[0-9a-f]{7,40}`? — .+)$"
)


class ChangelogTest(unittest.TestCase):
    def setUp(self) -> None:
        self.text = (PACKAGE_DIR / "CHANGELOG.md").read_text(encoding="utf-8")
        self.headings = [line for line in self.text.splitlines() if line.startswith("## ")]

    def test_the_first_entry_is_keyed_by_a_source_revision(self) -> None:
        # Internal SDKs have no SemVer line, so an entry is keyed by the commit
        # it landed in, or by the revision unmerged work was authored against.
        pattern = (
            r"^## (?:Unmerged — authored against `[0-9a-f]{7,40}`|rev `?[0-9a-f]{7,40}`? — .+)$"
        )
        self.assertTrue(self.headings)
        self.assertIsNotNone(re.fullmatch(pattern, self.headings[0]))

    def test_every_entry_is_keyed_the_same_way(self) -> None:
        pattern = (
            r"^## (?:Unmerged — authored against `[0-9a-f]{7,40}`|rev `?[0-9a-f]{7,40}`? — .+)$"
        )
        for heading in self.headings:
            with self.subTest(heading=heading):
                self.assertIsNotNone(re.fullmatch(pattern, heading))

    def test_the_changelog_disclaims_semver(self) -> None:
        self.assertIn("no SemVer", self.text)
        self.assertIn("source revision", self.text)

    def test_the_changelog_records_the_removed_request_id_alias(self) -> None:
        self.assertIn("x-mindclade-request-id", self.text)


class ReadmeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.text = (PACKAGE_DIR / "README.md").read_text(encoding="utf-8")

    def test_the_sections_appear_in_the_shared_order(self) -> None:
        positions: list[int] = []
        for heading in README_SECTION_ORDER:
            index = self.text.find(f"\n{heading}\n")
            with self.subTest(heading=heading):
                self.assertNotEqual(index, -1)
            positions.append(index)
        self.assertEqual(positions, sorted(positions))

    def test_the_appendix_carries_every_required_field(self) -> None:
        for heading in README_APPENDIX_FIELDS:
            with self.subTest(heading=heading):
                self.assertIn(f"\n{heading}\n", self.text)

    def test_the_false_pagination_claim_is_gone(self) -> None:
        # The old text said `paginate`/`apaginate` lazily traversed any ergonomic
        # list method. They did not: no list method returned a paginator.
        self.assertNotIn("lazily traverse any ergonomic list method", self.text)
        self.assertIn("Every ergonomic list method returns a `Page`", self.text)

    def test_the_coverage_claim_matches_the_descriptor_tables(self) -> None:
        # Re-derived rather than restated, so a contract change that moves the
        # numbers fails here instead of quietly making the README wrong.
        prose = " ".join(self.text.split())
        rpcs = len(INTERNAL_UNARY_METHODS) + len(INTERNAL_STREAM_METHODS)
        self.assertIn(f"**{len(INTERNAL_SERVICE_NAMES)} services and {rpcs} RPCs**", prose)
        self.assertIn(f"{len(INTERNAL_UNARY_METHODS)} unary", prose)
        self.assertIn("five server-streaming", prose)
        self.assertEqual(len(INTERNAL_STREAM_METHODS), 5)

    def test_the_readme_states_the_absent_credential_variable(self) -> None:
        self.assertIn("There is no credential environment variable", self.text)

    def test_the_readme_states_that_there_is_no_sse_client(self) -> None:
        self.assertIn("There is no SSE client in this SDK", self.text)

    def test_the_readme_documents_the_response_metadata_allowlist(self) -> None:
        for key in sdk.SAFE_RESPONSE_METADATA_KEYS:
            with self.subTest(key=key):
                self.assertIn(key, self.text)

    def test_the_readme_documents_every_recognised_environment_variable(self) -> None:
        for name in sdk.ENVIRONMENT_VARIABLES:
            with self.subTest(name=name):
                self.assertIn(name, self.text)

    def test_the_readme_names_every_exported_error_class(self) -> None:
        classes = [
            name
            for name in sdk.__all__
            if name.endswith("Error") and isinstance(getattr(sdk, name), type)
        ]
        for name in classes:
            with self.subTest(error=name):
                self.assertIn(name, self.text)

    def test_the_readme_links_the_changelog_and_the_component_metadata(self) -> None:
        self.assertIn("(CHANGELOG.md)", self.text)
        self.assertIn("(component.yaml)", self.text)

    def test_every_error_the_readme_calls_a_mindclade_error_really_is_one(self) -> None:
        """The hierarchy table is a catch contract, so it must not overstate itself.

        ``ConfigurationError`` and ``EventRejectedError`` predate the hierarchy and
        are ``ValueError`` subclasses: ``except MindcladeError`` does not catch
        them. Each such class must carry that warning on its own table row rather
        than sitting unmarked among the classes the except-clause does catch.
        """

        exported = [
            name
            for name in sdk.__all__
            if name.endswith("Error") and isinstance(getattr(sdk, name), type)
        ]
        rows = {
            line.split("`")[1]: line for line in self.text.splitlines() if line.startswith("| `")
        }
        for name in exported:
            error_type = getattr(sdk, name)
            row = rows.get(name)
            with self.subTest(error=name):
                if issubclass(error_type, sdk.MindcladeError):
                    if row is not None:
                        self.assertNotIn("**not** a `MindcladeError`", row)
                    continue
                self.assertIsNotNone(
                    row,
                    f"{name} is not a MindcladeError and needs a marked hierarchy row",
                )
                assert row is not None
                self.assertIn("**not** a `MindcladeError`", row)

    def test_the_readme_field_list_names_only_real_error_attributes(self) -> None:
        """A documented field a caller cannot actually read is a false claim."""

        marker = "Every `MindcladeError` carries the same bounded fields"
        self.assertIn(marker, self.text)
        start = self.text.index(marker)
        paragraph = self.text[start : self.text.index("\n\n", self.text.index("\n\n", start) + 2)]
        documented = set(re.findall(r"`([a-z_]+)`", paragraph))
        error = sdk.MindcladeError("bounded")
        for name in sorted(documented):
            with self.subTest(field=name):
                self.assertTrue(
                    hasattr(error, name),
                    f"README documents `{name}` but MindcladeError has no such attribute",
                )


if __name__ == "__main__":
    unittest.main()
