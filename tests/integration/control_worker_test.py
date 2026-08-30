#!/usr/bin/env python3.12
"""Run the named PostgreSQL command-to-fenced-completion kernel journey."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import unittest

REQUIRED = {"TestPostgresKernelJourney"}
PASS_LINE = re.compile(r"^--- PASS: (?P<name>\S+)(?: \([^)]*\))?$")


class ControlWorkerIntegrationTest(unittest.TestCase):
    def test_postgres_kernel_journey(self) -> None:
        dsn = os.environ.get("MINDCLADE_TEST_POSTGRES_DSN", "")
        required = os.environ.get("MINDCLADE_REQUIRE_POSTGRES_INTEGRATION") == "1"
        if not dsn:
            if required:
                self.fail("MINDCLADE_TEST_POSTGRES_DSN is required by the integration gate")
            self.skipTest("local PostgreSQL integration was not requested")
        environment = os.environ.copy()
        environment["MINDCLADE_REQUIRE_POSTGRES_INTEGRATION"] = "1"
        if len(sys.argv) != 2:
            self.fail("expected exactly one Bazel-provided Go test binary")
        completed = subprocess.run(
            [
                sys.argv[1],
                "-test.v",
                "-test.run",
                "^TestPostgresKernelJourney$",
            ],
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            timeout=180,
        )
        passed: set[str] = set()
        for line in completed.stdout.splitlines():
            match = PASS_LINE.fullmatch(line)
            if match is not None and match.group("name") in REQUIRED:
                passed.add(match.group("name"))
        if completed.returncode != 0 or passed != REQUIRED:
            self.fail(
                f"PostgreSQL kernel journey did not pass exactly: {sorted(REQUIRED - passed)}\n"
                f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
            )


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
