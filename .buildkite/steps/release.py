"""Activation-gated protected release pipeline."""

from __future__ import annotations

from pipeline_model import Step


def steps() -> list[Step]:
    return [
        Step(
            key="release-not-activated",
            label=":no_entry: Release pipeline is not activated",
            command="echo 'Release evidence graph is not activated' >&2; exit 78",
            timeout_minutes=5,
        )
    ]
