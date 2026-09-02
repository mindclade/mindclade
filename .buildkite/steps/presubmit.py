"""Fast, isolated pull-request pipeline."""

from __future__ import annotations

from pipeline_model import Step


def steps() -> list[Step]:
    return [
        Step(
            key="pipeline-plan",
            label=":git: Resolve exact presubmit plan",
            command="just ci-plan",
            timeout_minutes=10,
            artifact_paths=(
                "build/evidence/pipeline-plan.v1.json",
                "build/evidence/trusted-context.v1.json",
                "build/evidence/immutable-launcher.v1.json",
                "build/evidence/cache-boundary.v2.json",
            ),
        ),
        Step(
            key="governance",
            label=":classical_building: Repository governance",
            command="just governance-ci",
            timeout_minutes=20,
            depends_on=("pipeline-plan",),
            artifact_paths=("build/evidence/repository_drift.v1.json",),
        ),
        Step(
            key="affected-tests",
            label=":bazel: Affected tests",
            command=(
                "buildkite-agent artifact download "
                "'build/evidence/pipeline-plan.v1.json' . --step pipeline-plan && "
                "just test-planned"
            ),
            timeout_minutes=45,
            depends_on=("pipeline-plan",),
            artifact_paths=("build/evidence/bazel-native-agreement.v2.json",),
        ),
        Step(
            key="supply-chain",
            label=":lock: Supply-chain policy",
            command="just security",
            timeout_minutes=25,
            depends_on=("pipeline-plan",),
            artifact_paths=(
                "build/evidence/license-inventory.v1.json",
                "build/evidence/secret-scan.v1.json",
            ),
        ),
        Step(
            key="presubmit-evidence",
            label=":page_facing_up: CI evidence",
            command=(
                "buildkite-agent artifact download 'build/evidence/*' . "
                "--step pipeline-plan && "
                "buildkite-agent artifact download 'build/evidence/*' . "
                "--step governance && "
                "buildkite-agent artifact download 'build/evidence/*' . "
                "--step affected-tests && "
                "buildkite-agent artifact download 'build/evidence/*' . "
                "--step supply-chain && just ci-evidence"
            ),
            timeout_minutes=10,
            depends_on=("pipeline-plan", "governance", "affected-tests", "supply-chain"),
            artifact_paths=("build/evidence/*",),
        ),
    ]
