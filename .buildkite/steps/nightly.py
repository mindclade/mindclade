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
                "build/evidence/immutable-launcher.v1.json",
                "build/evidence/cache-boundary.v2.json",
            ),
        ),
        Step(
            key="source-check",
            label=":white_check_mark: Canonical source checks",
            command="just ci-source-check",
            timeout_minutes=120,
            depends_on=("pipeline-plan",),
            artifact_paths=("build/evidence/source-check.v1.json",),
        ),
        Step(
            key="fresh-db-integration",
            label=":postgres: Fresh-database runtime qualification",
            command="just integration-ci",
            timeout_minutes=120,
            depends_on=("source-check",),
            artifact_paths=(
                "build/evidence/integration-ci.v1.json",
                "build/evidence/training-vertical-rehearsal.v1.json",
                "build/evidence/authoritative-integration-readiness.v1.json",
            ),
        ),
        Step(
            key="connected-governance",
            label=":classical_building: Connected repository governance",
            command="just governance-ci",
            timeout_minutes=30,
            depends_on=("pipeline-plan",),
            artifact_paths=("build/evidence/repository_drift.v1.json",),
        ),
        Step(
            key="affected-tests",
            label=":bazel: Revision-bound affected tests",
            command=(
                "buildkite-agent artifact download "
                "'build/evidence/pipeline-plan.v1.json' . --step pipeline-plan && "
                "just test-planned"
            ),
            timeout_minutes=60,
            depends_on=("pipeline-plan",),
            artifact_paths=("build/evidence/bazel-native-agreement.v2.json",),
        ),
        Step(
            key="wave1-full",
            label=":bazel: Full Wave 1 qualification",
            command="just ci-wave1",
            timeout_minutes=120,
            depends_on=("pipeline-plan",),
            artifact_paths=("build/evidence/wave1-full.v1.json",),
        ),
        Step(
            key="cacheless-reproducibility",
            label=":repeat: Cacheless Wave 1 reproducibility canary",
            command="just ci-cacheless-canary",
            timeout_minutes=120,
            depends_on=("pipeline-plan",),
            artifact_paths=("build/evidence/cacheless-reproducibility.v1.json",),
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
                "--step source-check && "
                "buildkite-agent artifact download 'build/evidence/*' . "
                "--step fresh-db-integration && "
                "buildkite-agent artifact download 'build/evidence/*' . "
                "--step connected-governance && "
                "buildkite-agent artifact download 'build/evidence/*' . "
                "--step affected-tests && "
                "buildkite-agent artifact download 'build/evidence/*' . "
                "--step wave1-full && "
                "buildkite-agent artifact download 'build/evidence/*' . "
                "--step cacheless-reproducibility && "
                "buildkite-agent artifact download 'build/evidence/*' . "
                "--step nightly-security && just ci-evidence"
            ),
            timeout_minutes=10,
            depends_on=(
                "pipeline-plan",
                "source-check",
                "fresh-db-integration",
                "connected-governance",
                "affected-tests",
                "wave1-full",
                "cacheless-reproducibility",
                "nightly-security",
            ),
            artifact_paths=("build/evidence/*",),
        ),
    ]
