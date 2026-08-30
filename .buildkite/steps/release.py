"""Activation-gated protected release pipeline."""

from __future__ import annotations

from pipeline_model import Step


def steps() -> list[Step]:
    return [
        Step(
            key="release-activation-gate",
            label=":no_entry: Verify release activation evidence",
            command="just require-activation release",
            timeout_minutes=10,
        ),
        Step(
            key="release-qualification",
            label=":package: Build immutable release inputs",
            command="just ci-release",
            timeout_minutes=180,
            depends_on=("release-activation-gate",),
            artifact_paths=("build/evidence/release-*",),
        ),
    ]
