#!/usr/bin/env python3.12
"""Prove the per-language SDK API reference is derived, drift-checked, and honest."""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from render_sdk_api_reference import (
    COVERAGE_PATH,
    LANGUAGE_DIRECTORIES,
    ReferenceError,
    load_coverage,
    output_path,
    render_language,
    run,
)

REPOSITORY = Path(__file__).resolve().parents[3]


class SdkApiReferenceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.coverage = load_coverage(REPOSITORY)

    def test_committed_references_are_current(self) -> None:
        """`just docs` must fail the moment a reference stops matching the projection."""

        self.assertEqual(run(REPOSITORY, sorted(LANGUAGE_DIRECTORIES), check=True), 0)

    def test_every_language_covers_every_declared_rpc(self) -> None:
        """A reference that omitted an RPC would understate the supported surface."""

        methods = {str(rpc["full_name"]) for rpc in self.coverage["rpcs"]}
        self.assertEqual(len(methods), len(self.coverage["rpcs"]))
        for language in LANGUAGE_DIRECTORIES:
            rendered = render_language(self.coverage, language)
            for rpc in self.coverage["rpcs"]:
                self.assertIn(f"`{rpc['method']}`", rendered, f"{language} omits {rpc['method']}")

    def test_raw_only_rpcs_are_named_with_their_reason(self) -> None:
        """The one intentional escape hatch must never read as an ergonomic method."""

        raw_only = [rpc for rpc in self.coverage["rpcs"] if rpc["classification"] == "raw-only"]
        self.assertTrue(raw_only, "the projection no longer declares a raw-only RPC")
        for language in LANGUAGE_DIRECTORIES:
            rendered = render_language(self.coverage, language)
            for rpc in raw_only:
                self.assertIn("raw generated transport only", rendered)
                self.assertIn(str(rpc["reason"]), rendered)

    def test_streaming_rpcs_are_not_described_as_unary(self) -> None:
        """A facade must never present a server stream as an ordinary call."""

        streaming = [rpc for rpc in self.coverage["rpcs"] if rpc["server_streaming"]]
        self.assertTrue(streaming, "the projection no longer declares a server stream")
        for language in LANGUAGE_DIRECTORIES:
            rendered = render_language(self.coverage, language)
            for rpc in streaming:
                row = next(
                    line
                    for line in rendered.splitlines()
                    if line.startswith(f"| `{rpc['method']}` |")
                )
                self.assertIn("server stream", row)

    def test_reference_binds_the_candidate_descriptor_digest(self) -> None:
        for language in LANGUAGE_DIRECTORIES:
            self.assertIn(
                str(self.coverage["descriptor_digest"]),
                render_language(self.coverage, language),
            )

    def test_check_detects_a_tampered_reference(self) -> None:
        """The drift gate must reject a hand-edited reference, not just a missing one."""

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / COVERAGE_PATH.parent).mkdir(parents=True, exist_ok=True)
            shutil.copy(REPOSITORY / COVERAGE_PATH, root / COVERAGE_PATH)
            self.assertEqual(run(root, ["go"], check=False), 0)
            self.assertEqual(run(root, ["go"], check=True), 0)

            destination = output_path(root, "go")
            destination.write_text(
                destination.read_text(encoding="utf-8").replace("| unary |", "| stream |", 1),
                encoding="utf-8",
            )
            self.assertEqual(run(root, ["go"], check=True), 1)

    def test_missing_reference_fails_the_check(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / COVERAGE_PATH.parent).mkdir(parents=True, exist_ok=True)
            shutil.copy(REPOSITORY / COVERAGE_PATH, root / COVERAGE_PATH)
            self.assertEqual(run(root, ["go"], check=True), 1)

    def test_wrong_projection_schema_is_refused(self) -> None:
        """A stale or foreign projection must not silently render a reference."""

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / COVERAGE_PATH.parent).mkdir(parents=True, exist_ok=True)
            payload = json.loads((REPOSITORY / COVERAGE_PATH).read_text(encoding="utf-8"))
            payload["schema_version"] = "mindclade.internal-sdk-rpc-coverage-projection/v1"
            (root / COVERAGE_PATH).write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(ReferenceError):
                load_coverage(root)


if __name__ == "__main__":
    unittest.main()
