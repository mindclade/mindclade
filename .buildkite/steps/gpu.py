"""Activation-gated GPU qualification pipeline."""

from __future__ import annotations

from pipeline_model import Step


def steps() -> list[Step]:
    return [
        Step(
            key="gpu-activation-gate",
            label=":no_entry: Verify GPU activation evidence",
            command="just require-activation gpu",
            timeout_minutes=10,
        ),
        Step(
            key="gpu-qualification",
            label=":gpu: GPU qualification",
            command="just ci-gpu",
            timeout_minutes=240,
            depends_on=("gpu-activation-gate",),
            artifact_paths=("build/evidence/gpu-*",),
        ),
    ]
