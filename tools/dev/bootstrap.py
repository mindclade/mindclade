#!/usr/bin/env python3.12
"""Verify the pinned local Wave 0 toolchain without acquiring credentials."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class Tool:
    name: str
    executable: str
    arguments: tuple[str, ...]
    version_pattern: str


@dataclass(frozen=True)
class Result:
    name: str
    status: str
    observed: str
    requirement: str


TOOLS = (
    Tool("Bazel", "bazel", ("version",), r"\bBuild label: 9\.1\.1\b"),
    Tool("uv", "uv", ("--version",), r"\buv 0\.12\.5\b"),
    Tool("Go", "go", ("version",), r"\bgo1\.26(?:\.[0-9]+)?\b"),
    Tool("Rust", "rustc", ("--version",), r"\brustc 1\.97\.1\b"),
    Tool("Node", "node", ("--version",), r"^v26\.[0-9]+\.[0-9]+$"),
    Tool("pnpm", "pnpm", ("--version",), r"^11\.22\.0$"),
    Tool("Buf", "buf", ("--version",), r"^1\.72\.0$"),
    Tool("Nix", "nix", ("--version",), r"\b2\.35\.[0-9]+\b"),
    Tool("just", "just", ("--version",), r"\bjust 1\.[0-9]+\.[0-9]+\b"),
    Tool("actionlint", "actionlint", ("--version",), r"\b1\.7\.[0-9]+\b"),
    Tool("Buildifier", "buildifier", ("--version",), r"\b8\.5\.1\b"),
    Tool(
        "golangci-lint",
        "golangci-lint",
        ("--version",),
        r"\bgolangci-lint has version 2\.13\.1\b",
    ),
    Tool("nixfmt", "nixfmt", ("--version",), r"\b1\.4\.0\b"),
    Tool("ruff", "ruff", ("--version",), r"^ruff 0\.16\.4$"),
    Tool("pyright", "pyright", ("--version",), r"^pyright 1\.1\.412$"),
    Tool("ShellCheck", "shellcheck", ("--version",), r"\bversion: 0\.11\.0\b"),
    Tool("shfmt", "shfmt", ("--version",), r"^v3\.13\.1$"),
)


def inspect(tool: Tool, root: Path) -> Result:
    path = shutil.which(tool.executable)
    if path is None:
        return Result(tool.name, "missing", "", tool.version_pattern)
    command = [path, *tool.arguments]
    if tool.name == "Bazel":
        command = [
            path,
            "--nohome_rc",
            "--noworkspace_rc",
            f"--output_user_root={root.resolve() / 'build/bazel-user-root'}",
            f"--bazelrc={root.resolve() / '.bazelrc'}",
            *tool.arguments,
        ]
    try:
        completed = subprocess.run(
            command,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return Result(tool.name, "error", str(error), tool.version_pattern)
    output = completed.stdout.strip()
    lines = output.splitlines()
    observed = next(
        (line for line in lines if re.search(tool.version_pattern, line)),
        lines[0] if lines else "",
    )
    matches = completed.returncode == 0 and re.search(tool.version_pattern, output)
    status = "pass" if matches else "mismatch"
    return Result(tool.name, status, observed, tool.version_pattern)


def python_result() -> Result:
    observed = ".".join(str(part) for part in sys.version_info[:3])
    status = "pass" if sys.version_info[:2] == (3, 12) else "mismatch"
    return Result("Python", status, observed, "3.12.x")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    required = ("flake.lock", "uv.lock", "Cargo.lock", "go.sum", "pnpm-lock.yaml")
    missing_files = [path for path in required if not (args.root / path).is_file()]
    results = [python_result(), *(inspect(tool, args.root) for tool in TOOLS)]
    if args.json:
        print(
            json.dumps(
                {
                    "schema_version": "toolchain-bootstrap.v1",
                    "results": [asdict(result) for result in results],
                    "missing_lockfiles": missing_files,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
    else:
        for result in results:
            print(f"{result.status:8} {result.name:12} {result.observed or 'not found'}")
        for path in missing_files:
            print(f"missing  lockfile     {path}")
    return 0 if not missing_files and all(result.status == "pass" for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
