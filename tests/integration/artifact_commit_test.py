#!/usr/bin/env python3.12
"""Require the Bazel-built filesystem-CAS artifact tests to pass."""

from __future__ import annotations

import re
import subprocess
import sys
import unittest

REQUIRED = {
    "TestArtifactFinalizeIsAtomicAndRejectsCorruption",
    "TestArtifactOrphanCleanup",
}
PASS_LINE = re.compile(r"^--- PASS: (?P<name>\S+)(?: \([^)]*\))?$")


def run_go_tests(required: set[str], test_binary: str) -> None:
    expression = "^(" + "|".join(sorted(required)) + ")$"
    completed = subprocess.run(
        [test_binary, "-test.v", "-test.run", expression],
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    passed: set[str] = set()
    for line in completed.stdout.splitlines():
        match = PASS_LINE.fullmatch(line)
        if match is not None and match.group("name") in required:
            passed.add(match.group("name"))
    if completed.returncode != 0 or passed != required:
        missing = sorted(required - passed)
        raise AssertionError(
            f"artifact integration failed; missing passes={missing}\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )


class ArtifactCommitIntegrationTest(unittest.TestCase):
    def test_atomic_finalize_corruption_and_orphan_recovery(self) -> None:
        if len(sys.argv) != 2:
            self.fail("expected exactly one Bazel-provided Go test binary")
        run_go_tests(REQUIRED, sys.argv[1])


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
