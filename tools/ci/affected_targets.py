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

WAVE1_TARGET = "//:wave1_tests"
WAVE2S_TARGET = "//:wave2s_tests"
WAVE2P_TARGET = "//:wave2p_tests"

WAVE1_PREFIXES = (
    "deploy/local/",
    "libs/",
    "protocols/",
    "services/control_plane/",
    "tests/",
    "tests/conformance/",
    "tools/codegen/",
    "tools/qualification/",
    "tools/release/",
    "third_party/",
)

WAVE2S_PREFIXES = (
    "bio/",
    "data/",
    "evaluation/",
    "kernels/",
    "models/",
    "runtime/",
    "training/",
)

WAVE2P_PREFIXES = (
    "protocols/generated/go/inference/v1/",
    "protocols/generated/python/inference/v1/",
    "protocols/proto/mindclade/inference/v1/",
    "sdk/",
    "workers/",
)

WAVE2P_CONTROL_PLANE_PREFIXES = (
    # The control-plane runtime libraries moved out of services/control_plane
    # into libs/go, but they are still what the wave-2 protected control-plane
    # suite exercises, so a change to any of them must keep selecting it.
    "libs/go/eventruntime/",
    "libs/go/fencing/",
    "libs/go/idempotency/",
    "libs/go/inbox/",
    "libs/go/outbox/",
    "libs/go/persistence/",
    "libs/go/pubsubx/",
    "libs/go/servicekit/",
    "libs/go/storage/",
    "services/control_plane/cmd/control-plane/",
    "services/control_plane/internal/policies/",
    "services/control_plane/internal/projects/",
    "services/control_plane/internal/tenants/",
    "services/control_plane/internal/users/",
)

WAVE2P_EXACT_PATHS = {
    "inference/contracts/request_contract.py",
    "inference/contracts/result_contract.py",
    "inference/tests/test_request_contract.py",
    "services/BUILD.bazel",
    "services/README.md",
    "tests/end_to_end/platform_slice_test.py",
}

WAVE2S_EXACT_PATHS = {"tests/end_to_end/scientific_slice_test.py"}
TARGET_ORDER = (*DEFAULT_TARGETS, WAVE1_TARGET, WAVE2S_TARGET, WAVE2P_TARGET)

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
    """Map changed files to the conservative governed test closure.

    Future Wave 2 labels are emitted only for paths already assigned to that
    wave by the repository path authority. Their root suites must be activated
    atomically with the first implementation. Unknown paths broaden to the
    complete active Wave 1 closure; governance independently rejects paths
    absent from the manifest.
    """
    normalized = sorted({normalize_path(path) for path in paths})
    if not normalized:
        return []
    selected: set[str] = set(DEFAULT_TARGETS)
    matched_domain = False
    for path in normalized:
        if path.startswith(WAVE1_PREFIXES):
            selected.add(WAVE1_TARGET)
            matched_domain = True
        if path.startswith(WAVE2S_PREFIXES) or path.startswith("inference/"):
            selected.add(WAVE2S_TARGET)
            matched_domain = True
        if (
            path.startswith(WAVE2P_PREFIXES)
            or path.startswith(WAVE2P_CONTROL_PLANE_PREFIXES)
            or path in WAVE2P_EXACT_PATHS
        ):
            selected.add(WAVE2P_TARGET)
            matched_domain = True
        if path in WAVE2S_EXACT_PATHS:
            selected.add(WAVE2S_TARGET)
            matched_domain = True
        if path in GLOBAL_PATHS or path.startswith(GLOBAL_PREFIXES):
            selected.add(WAVE1_TARGET)
            matched_domain = True
    if not matched_domain:
        selected.add(WAVE1_TARGET)
    return [target for target in TARGET_ORDER if target in selected]


def self_test() -> None:
    cases = {
        "libs/go/audit/writer.go": [*DEFAULT_TARGETS, WAVE1_TARGET],
        "services/control_plane/internal/storage/store.go": [*DEFAULT_TARGETS, WAVE1_TARGET],
        "bio/identity/sequence.py": [*DEFAULT_TARGETS, WAVE2S_TARGET],
        "inference/sampling/deterministic_sampler.py": [*DEFAULT_TARGETS, WAVE2S_TARGET],
        "inference/contracts/request_contract.py": [
            *DEFAULT_TARGETS,
            WAVE2S_TARGET,
            WAVE2P_TARGET,
        ],
        "protocols/proto/mindclade/inference/v1/inference_request.proto": [
            *DEFAULT_TARGETS,
            WAVE1_TARGET,
            WAVE2P_TARGET,
        ],
        "services/control_plane/internal/tenants/tenant_commands.go": [
            *DEFAULT_TARGETS,
            WAVE1_TARGET,
            WAVE2P_TARGET,
        ],
        "workers/inference_worker/python/main.py": [*DEFAULT_TARGETS, WAVE2P_TARGET],
        "BUILD.bazel": [*DEFAULT_TARGETS, WAVE1_TARGET],
        "new/governed/domain/file.py": [*DEFAULT_TARGETS, WAVE1_TARGET],
    }
    for path, expected in cases.items():
        actual = targets_for_paths([path])
        if actual != expected:
            raise AssertionError(
                f"affected target mapping drift for {path}: {actual} != {expected}"
            )
    combined = targets_for_paths(
        ["data/curation/pipeline.py", "workers/inference_worker/python/main.py"]
    )
    if combined != [*DEFAULT_TARGETS, WAVE2S_TARGET, WAVE2P_TARGET]:
        raise AssertionError(f"multi-wave target selection is not conservative: {combined}")
    for invalid in ("", "../escape", "/absolute", "a/../../escape"):
        try:
            normalize_path(invalid)
        except SelectionError:
            continue
        raise AssertionError(f"unsafe path was accepted: {invalid!r}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--base")
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--changed-file", action="append", default=[])
    parser.add_argument("--format", choices=("lines", "json"), default="lines")
    parser.add_argument("--self-test", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.self_test:
        self_test()
        print("affected-target mapping self-test passed")
        return 0
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
