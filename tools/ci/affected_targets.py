#!/usr/bin/env python3.12
"""Select the conservative Bazel test closure for a source change."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path, PurePosixPath

DEFAULT_TARGETS = (
    "//:wave0_tests",
    "//tools:repository_governance_tests",
)

WAVE1_PREFIXES = (
    "protocols/",
    "tests/conformance/",
    "tools/codegen/",
    "third_party/",
)

GLOBAL_PATHS = {
    ".bazelrc",
    ".bazelversion",
    "BUILD.bazel",
    "MODULE.bazel",
    "component.yaml",
    "flake.lock",
    "flake.nix",
    "justfile",
}

GLOBAL_PREFIXES = (
    ".buildkite/",
    ".github/",
    "docs/adr/",
    "docs/architecture/",
    "tools/bazel/",
    "tools/ci/",
    "tools/docs/",
    "tools/repo/",
)


class SelectionError(ValueError):
    """Raised for an unsafe or ambiguous change selection."""


def normalize_path(raw: str) -> str:
    """Return a safe repository-relative POSIX path."""
    value = raw.replace("\\", "/").strip()
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts:
        raise SelectionError(f"unsafe repository path: {raw!r}")
    normalized = path.as_posix()
    if normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def changed_paths(
    root: Path,
    base: str | None,
    head: str,
    *,
    strict: bool = False,
) -> list[str]:
    """Discover changed paths, conservatively returning the global marker."""
    try:
        _git(root, "rev-parse", "--verify", head)
    except (FileNotFoundError, subprocess.CalledProcessError) as error:
        if strict:
            raise SelectionError(f"cannot resolve exact head revision: {head}") from error
        return ["BUILD.bazel"]

    candidate_base = base
    if candidate_base is None:
        candidate_base = os.environ.get("BUILDKITE_PULL_REQUEST_BASE_BRANCH")
    if candidate_base:
        try:
            merge_base = _git(root, "merge-base", candidate_base, head)
        except subprocess.CalledProcessError as error:
            if strict:
                raise SelectionError(
                    f"cannot resolve merge base for {candidate_base} and {head}"
                ) from error
            return ["BUILD.bazel"]
        diff_range = f"{merge_base}..{head}"
    else:
        try:
            parent = _git(root, "rev-parse", f"{head}^")
        except subprocess.CalledProcessError as error:
            if strict:
                raise SelectionError(f"cannot resolve parent for {head}") from error
            return ["BUILD.bazel"]
        diff_range = f"{parent}..{head}"

    output = _git(root, "diff", "--name-only", "--diff-filter=ACDMRTUXB", diff_range)
    return sorted({normalize_path(line) for line in output.splitlines() if line.strip()})


def targets_for_paths(paths: Iterable[str]) -> list[str]:
    """Map changed files to the smallest currently governed test closure.

    Wave 0 has no product packages. Every populated path therefore affects the
    repository-governance closure. Later waves extend this function only when a
    real component and Bazel target are activated.
    """
    normalized = sorted({normalize_path(path) for path in paths})
    if not normalized:
        return []
    if any(path.startswith(WAVE1_PREFIXES) for path in normalized):
        return ["//:wave1_contract_tests"]
    if any(path in GLOBAL_PATHS or path.startswith(GLOBAL_PREFIXES) for path in normalized):
        return [*DEFAULT_TARGETS, "//:wave1_contract_tests"]
    return list(DEFAULT_TARGETS)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--base")
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--changed-file", action="append", default=[])
    parser.add_argument("--format", choices=("lines", "json"), default="lines")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = args.root.resolve()
    try:
        paths = (
            sorted({normalize_path(path) for path in args.changed_file})
            if args.changed_file
            else changed_paths(root, args.base, args.head)
        )
        targets = targets_for_paths(paths)
    except (SelectionError, subprocess.CalledProcessError) as error:
        print(f"affected-target selection failed: {error}", file=sys.stderr)
        return 2

    if args.format == "json":
        print(
            json.dumps(
                {
                    "schema_version": "affected-targets.v1",
                    "changed_paths": paths,
                    "targets": targets,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
    elif targets:
        print("\n".join(targets))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
