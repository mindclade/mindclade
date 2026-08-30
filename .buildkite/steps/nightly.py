"""Protected continuous and nightly qualification pipeline."""

from __future__ import annotations

from pipeline_model import Step


def steps() -> list[Step]:
    return [
        Step(
            key="pipeline-plan",
            label=":git: Resolve exact protected plan",
            command="just ci-plan",
            timeout_minutes=10,
            artifact_paths=(
                "build/evidence/pipeline-plan.v1.json",
                "build/evidence/trusted-context.v1.json",
            ),
        ),
        Step(
            key="full-cpu",
            label=":bazel: Full CPU qualification",
            command="just ci-nightly",
            timeout_minutes=120,
            depends_on=("pipeline-plan",),
            artifact_paths=("build/evidence/*",),
        ),
        Step(
            key="nightly-security",
            label=":shield: Security and dependency qualification",
            command="just security",
            timeout_minutes=45,
            depends_on=("pipeline-plan",),
            artifact_paths=(
                "build/evidence/license-inventory.v1.json",
                "build/evidence/secret-scan.v1.json",
            ),
        ),
        Step(
            key="nightly-evidence",
            label=":page_facing_up: Nightly evidence",
            command=(
                "buildkite-agent artifact download 'build/evidence/*' . "
                "--step pipeline-plan && "
                "buildkite-agent artifact download 'build/evidence/*' . "
                "--step full-cpu && "
                "buildkite-agent artifact download 'build/evidence/*' . "
                "--step nightly-security && just ci-evidence"
            ),
            timeout_minutes=10,
            depends_on=("pipeline-plan", "full-cpu", "nightly-security"),
            artifact_paths=("build/evidence/*",),
        ),
    ]
