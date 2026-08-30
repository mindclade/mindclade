#!/usr/bin/env python3.12
"""Create a canonical, revision-bound Wave 0 CI plan."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from affected_targets import changed_paths as discover_changed_paths
from affected_targets import normalize_path, targets_for_paths

SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def build_plan(
    *,
    source_revision: str,
    pipeline_definition_revision: str,
    pipeline_class: str,
    changed_files: list[str],
) -> dict[str, Any]:
    if not SHA_PATTERN.fullmatch(source_revision):
        raise ValueError("source revision must be one full lowercase Git SHA")
    if not SHA_PATTERN.fullmatch(pipeline_definition_revision):
        raise ValueError("pipeline definition revision must be one full lowercase Git SHA")
    if pipeline_class not in {"presubmit", "protected", "nightly", "gpu", "release", "security"}:
        raise ValueError(f"unsupported pipeline class: {pipeline_class}")

    paths = sorted({normalize_path(path) for path in changed_files})
    if pipeline_class in {"protected", "nightly"}:
        targets = ["//..."]
    elif pipeline_class == "security":
        targets = []
    else:
        targets = targets_for_paths(paths) or list(targets_for_paths(["BUILD.bazel"]))
    gates = {
        "security": ["dependency-and-license-policy", "secret-scan"],
    }.get(
        pipeline_class,
        [
            "repository-governance",
            "dependency-and-license-policy",
            "secret-scan",
            "bazel-native-agreement",
        ],
    )
    plan: dict[str, Any] = {
        "schema_version": "pipeline-plan.v1",
        "source_revision": source_revision,
        "pipeline_definition_revision": pipeline_definition_revision,
        "pipeline_class": pipeline_class,
        "changed_paths": paths,
        "targets": targets,
        "gates": gates,
    }
    digest = hashlib.sha256(canonical_json(plan)).hexdigest()
    plan["plan_id"] = f"sha256:{digest}"
    return plan


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--pipeline-definition-revision", required=True)
    parser.add_argument("--pipeline-class", default="presubmit")
    parser.add_argument("--changed-file", action="append", default=[])
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--base")
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        paths = (
            args.changed_file
            if args.changed_file
            else discover_changed_paths(args.root.resolve(), args.base, args.head, strict=True)
        )
        if not paths:
            raise ValueError("the exact changed-path set is empty")
        plan = build_plan(
            source_revision=args.source_revision,
            pipeline_definition_revision=args.pipeline_definition_revision,
            pipeline_class=args.pipeline_class,
            changed_files=paths,
        )
    except ValueError as error:
        print(f"invalid pipeline plan: {error}", file=sys.stderr)
        return 2

    rendered = canonical_json(plan)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(rendered)
    else:
        sys.stdout.buffer.write(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
