#!/usr/bin/env python3.12
"""Run non-connected Wave 0 repository diagnostics."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class Check:
    name: str
    command: tuple[str, ...]


@dataclass(frozen=True)
class Result:
    name: str
    status: str
    detail: str


QUICK_CHECKS = (
    Check("toolchain", (sys.executable, "tools/dev/bootstrap.py")),
    Check("cargo-lock", ("cargo", "metadata", "--locked", "--no-deps", "--format-version=1")),
    Check("go-module", ("go", "list", "-mod=readonly", "-m")),
    Check("pnpm-manifest", ("pnpm", "run", "check")),
    Check("uv-lock", ("uv", "lock", "--check")),
    Check("buf-modules", ("buf", "config", "ls-modules")),
    Check("buf-lint-config", ("buf", "config", "ls-lint-rules")),
    Check("buf-breaking-config", ("buf", "config", "ls-breaking-rules")),
    Check("required-check", (sys.executable, "tools/ci/required_check.py", "--self-test")),
    Check("buildkite-model", (sys.executable, ".buildkite/pipeline.py", "--check")),
)

FULL_CHECKS = (
    Check("bazel", ("bazel", "test", "--config=ci", "//:wave0_tests")),
    Check("nix-flake", ("nix", "flake", "check", "path:.", "--no-build")),
)


def safe_environment() -> dict[str, str]:
    environment = dict(os.environ)
    environment.update(
        {
            "LANG": "C",
            "LC_ALL": "C",
            "TZ": "UTC",
            "PYTHONHASHSEED": "0",
        }
    )
    return environment


def run_check(root: Path, check: Check) -> Result:
    command = check.command
    if command[0] == "bazel":
        command = (
            command[0],
            "--nohome_rc",
            "--noworkspace_rc",
            f"--output_user_root={root / 'build/bazel-user-root'}",
            f"--bazelrc={root / '.bazelrc'}",
            *command[1:],
        )
    try:
        completed = subprocess.run(
            command,
            cwd=root,
            env=safe_environment(),
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=300,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as error:
        return Result(check.name, "error", str(error))
    lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    detail = lines[-1] if lines else f"exit {completed.returncode}"
    return Result(check.name, "pass" if completed.returncode == 0 else "fail", detail[:500])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    checks = QUICK_CHECKS if args.quick else (*QUICK_CHECKS, *FULL_CHECKS)
    results = [run_check(args.root.resolve(), check) for check in checks]
    if args.json:
        print(
            json.dumps(
                {
                    "schema_version": "repository-doctor.v1",
                    "results": [asdict(result) for result in results],
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
    else:
        for result in results:
            print(f"{result.status:5} {result.name:20} {result.detail}")
    return 0 if all(result.status == "pass" for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
