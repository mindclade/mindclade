#!/usr/bin/env python3.12
"""Render the authoritative heavy CI pipeline as canonical JSON."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

BUILDKITE_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(BUILDKITE_ROOT / "lib"))
sys.path.insert(0, str(BUILDKITE_ROOT / "steps"))

import gpu  # noqa: E402
import nightly  # noqa: E402
import presubmit  # noqa: E402
import release  # noqa: E402
import security  # noqa: E402
from pipeline_model import Step, render_pipeline  # noqa: E402
from trusted_context import TrustedContext  # noqa: E402


def steps_for(pipeline_class: str) -> list[Step]:
    if pipeline_class == "presubmit":
        return presubmit.steps()
    if pipeline_class in {"protected", "nightly"}:
        return nightly.steps()
    if pipeline_class == "gpu":
        return gpu.steps()
    if pipeline_class == "release":
        return release.steps()
    if pipeline_class == "security":
        return security.steps()
    raise ValueError(f"unsupported pipeline class: {pipeline_class}")


def render(context: TrustedContext) -> dict[str, Any]:
    context.validate()
    return render_pipeline(steps_for(context.pipeline_class), context.pipeline_environment())


def self_test() -> None:
    for pipeline_class in ("presubmit", "protected", "nightly", "gpu", "release", "security"):
        value = render(TrustedContext.for_test(pipeline_class))
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"))
        if json.loads(encoded) != value:
            raise AssertionError(f"pipeline {pipeline_class} is not canonically serializable")
        queues = {step["agents"]["queue"] for step in value["steps"]}
        if len(queues) != 1 or next(iter(queues)) not in {
            "mindclade-gpu",
            "mindclade-release",
            "mindclade-trusted-cpu",
            "mindclade-untrusted-cpu",
        }:
            raise AssertionError(f"pipeline {pipeline_class} has an invalid agent queue")
        environment = value["env"]
        for key in (
            "MINDCLADE_LAUNCHER_DIGEST",
            "MINDCLADE_LAUNCHER_IDENTITY",
            "MINDCLADE_LAUNCHER_REVISION",
            "MINDCLADE_PIPELINE_DEFINITION_REVISION",
            "MINDCLADE_SOURCE_REVISION",
            "MINDCLADE_CACHE_MODE",
            "MINDCLADE_CACHE_PLATFORM",
            "MINDCLADE_CACHE_ARCHITECTURE",
            "MINDCLADE_CACHE_TOOLCHAIN_DIGEST",
            "MINDCLADE_CACHE_BUILD_MODE",
            "MINDCLADE_CACHE_CLASSIFICATION",
            "MINDCLADE_CACHE_NAMESPACE_EPOCH",
        ):
            if key not in environment:
                raise AssertionError(f"pipeline {pipeline_class} omits immutable binding {key}")
        invalid_tier = "release" if pipeline_class != "release" else "trusted"
        try:
            render(replace(TrustedContext.for_test(pipeline_class), execution_tier=invalid_tier))
        except ValueError:
            pass
        else:
            raise AssertionError(f"pipeline {pipeline_class} accepted an invalid execution tier")

        if pipeline_class == "gpu":
            by_key = {step["key"]: step for step in value["steps"]}
            multi_node = by_key["gpu-multinode-probe"]
            if multi_node.get("parallelism") != 2:
                raise AssertionError("multi-node GPU probe must reserve two protected agents")
            if multi_node.get("depends_on") != ["gpu-activation-gate"]:
                raise AssertionError("multi-node GPU probe bypasses the activation gate")
            if "MINDCLADE_DEEPEP_RDZV_ID=${BUILDKITE_BUILD_ID}" not in multi_node["command"]:
                raise AssertionError("multi-node GPU probe does not isolate its rendezvous")
            for key in ("gpu-intranode-probe", "gpu-multinode-probe"):
                if (
                    "nix develop --no-accept-flake-config --no-update-lock-file "
                    ".#deepep --command" not in by_key[key]["command"]
                ):
                    raise AssertionError(f"{key} bypasses the pinned DeepEP Nix environment")
    environment_hook = (BUILDKITE_ROOT / "hooks/environment").read_text(encoding="utf-8")
    if "accept-flake-config = false" not in environment_hook:
        raise AssertionError("environment hook permits repository-controlled Nix settings")
    pre_command = (BUILDKITE_ROOT / "hooks/pre-command").read_text(encoding="utf-8")
    protected_fragments = (
        "PROTECTED_DEFINITION_PATHS",
        'git show "${pipeline_revision}:tools/ci/pipeline_plan.py"',
        'git diff --quiet "${pipeline_revision}"',
        "git status --porcelain=v1 --untracked-files=all",
        "git submodule status --recursive",
        "protected-definition roll-forward",
        'nix_value("accept-flake-config") is not False',
    )
    missing = [fragment for fragment in protected_fragments if fragment not in pre_command]
    if missing:
        raise AssertionError(f"pre-command omits protected closure fragments: {missing}")
    if "ALLOW_CI_DEFINITION_CHANGE" in pre_command:
        raise AssertionError("presubmit protected-definition guard has a source-controlled bypass")
    justfile = (BUILDKITE_ROOT.parent / "justfile").read_text(encoding="utf-8")
    dependency_install = "pnpm install --frozen-lockfile --prefer-offline --ignore-scripts"
    if dependency_install not in justfile:
        raise AssertionError("canonical source checks do not hydrate frozen pnpm dependencies")
    workflow_root = BUILDKITE_ROOT.parent / ".github/workflows"
    implementation_pin = "@c097ef86c25991a400050c13e78574e8d3d8c071"
    organization_references: list[str] = []
    for workflow_path in sorted(workflow_root.glob("*.yml")):
        lines = workflow_path.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            if "uses: mindclade/.github/.github/workflows/" not in line:
                continue
            organization_references.append(line.strip())
            if not line.endswith(implementation_pin):
                raise AssertionError(f"{workflow_path.name} uses an unreviewed workflow revision")
            if "reusable-buildkite-dispatch.yml" not in line:
                continue
            for following in lines[index + 1 :]:
                if following.startswith("  ") and not following.startswith("    "):
                    break
                if following.strip().startswith("pipeline_definition_revision:"):
                    raise AssertionError(
                        f"{workflow_path.name} supplies a source-controlled pipeline revision"
                    )
    if len(organization_references) != 12:
        raise AssertionError("organization workflow caller inventory is incomplete")
    permission_boundaries = {
        ("buildkite-dispatch.yml", "verify"): (
            "      actions: read\n      contents: read\n      id-token: write\n"
        ),
        ("codeql.yml", "python"): ("      contents: read\n      security-events: write\n"),
        ("required-check.yml", "buildkite_required"): (
            "      actions: read\n      contents: read\n      id-token: write\n"
        ),
        ("scorecard.yml", "scorecard"): ("      contents: read\n      security-events: write\n"),
    }
    for (workflow_name, job_name), permissions in permission_boundaries.items():
        source = (workflow_root / workflow_name).read_text(encoding="utf-8")
        required_permissions = f"  {job_name}:\n    permissions:\n{permissions}"
        if required_permissions not in source:
            raise AssertionError(
                f"{workflow_name} does not grant the reviewed reusable-workflow permissions"
            )
    loader = (BUILDKITE_ROOT / "pipeline.yml").read_text(encoding="utf-8")
    if "reject-invalid-execution-tier" not in loader:
        raise AssertionError("static pipeline can succeed without a valid execution tier")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.check:
        self_test()
        print("Buildkite pipeline model passed")
        return 0
    try:
        context = TrustedContext.from_environment()
        value = render(context)
    except ValueError as error:
        print(f"pipeline context rejected: {error}", file=sys.stderr)
        return 1
    print(json.dumps(value, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
