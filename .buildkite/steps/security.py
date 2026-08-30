"""Protected security pipeline."""

from __future__ import annotations

from pipeline_model import Step


def steps() -> list[Step]:
    return [
        Step(
            key="pipeline-plan",
            label=":git: Resolve exact security plan",
            command="just ci-plan",
            timeout_minutes=10,
            artifact_paths=(
                "build/evidence/pipeline-plan.v1.json",
                "build/evidence/trusted-context.v1.json",
                "build/evidence/immutable-launcher.v1.json",
                "build/evidence/cache-boundary.v1.json",
            ),
        ),
        Step(
            key="security",
            label=":shield: Security policy",
            command="just security",
            timeout_minutes=60,
            depends_on=("pipeline-plan",),
            artifact_paths=(
                "build/evidence/license-inventory.v1.json",
                "build/evidence/secret-scan.v1.json",
            ),
        ),
        Step(
            key="security-evidence",
            label=":page_facing_up: Security evidence",
            command=(
                "buildkite-agent artifact download 'build/evidence/*' . "
                "--step pipeline-plan && "
                "buildkite-agent artifact download 'build/evidence/*' . "
                "--step security && just ci-evidence"
            ),
            timeout_minutes=10,
            depends_on=("pipeline-plan", "security"),
            artifact_paths=("build/evidence/*",),
        ),
    ]
