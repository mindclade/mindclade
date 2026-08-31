"""Activation-gated GPU qualification pipeline."""

from __future__ import annotations

from pipeline_model import Step


def steps() -> list[Step]:
    return [Step(
        key="gpu-not-activated",
        label=":no_entry: GPU pipeline is not activated",
        command="echo 'GPU evidence graph is not activated' >&2; exit 78",
        timeout_minutes=5,
    )]
