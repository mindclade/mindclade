"""Small validated model for the Buildkite pipeline JSON surface."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

KEY_PATTERN = re.compile(r"^[a-z][a-z0-9-]{1,63}$")


@dataclass(frozen=True)
class Step:
    key: str
    label: str
    command: str
    timeout_minutes: int
    depends_on: tuple[str, ...] = ()
    artifact_paths: tuple[str, ...] = ()
    env: dict[str, str] = field(default_factory=lambda: {})
    parallelism: int | None = None
    soft_fail: bool = False

    def validate(self) -> None:
        if not KEY_PATTERN.fullmatch(self.key):
            raise ValueError(f"invalid Buildkite step key: {self.key!r}")
        if not self.label.strip() or not self.command.strip():
            raise ValueError(f"step {self.key} requires a label and command")
        if not 1 <= self.timeout_minutes <= 240:
            raise ValueError(f"step {self.key} has an invalid timeout")
        if self.key in self.depends_on:
            raise ValueError(f"step {self.key} depends on itself")
        for key in self.depends_on:
            if not KEY_PATTERN.fullmatch(key):
                raise ValueError(f"step {self.key} has an invalid dependency key")
        for key in self.env:
            if not key.startswith("MINDCLADE_"):
                raise ValueError(f"step {self.key} has an ungoverned environment entry")
        if self.parallelism is not None and not 2 <= self.parallelism <= 16:
            raise ValueError(f"step {self.key} has invalid parallelism")

    def as_mapping(self) -> dict[str, Any]:
        self.validate()
        value: dict[str, Any] = {
            "key": self.key,
            "label": self.label,
            "command": self.command,
            "timeout_in_minutes": self.timeout_minutes,
            "retry": {"automatic": [{"exit_status": -1, "limit": 1}]},
        }
        if self.depends_on:
            value["depends_on"] = list(self.depends_on)
        if self.artifact_paths:
            value["artifact_paths"] = list(self.artifact_paths)
        if self.env:
            value["env"] = dict(sorted(self.env.items()))
        if self.parallelism is not None:
            value["parallelism"] = self.parallelism
        if self.soft_fail:
            value["soft_fail"] = True
        return value


def validate_pipeline(steps: Iterable[Step]) -> list[Step]:
    materialized = list(steps)
    if not materialized:
        raise ValueError("pipeline must contain at least one step")
    keys = [step.key for step in materialized]
    if len(keys) != len(set(keys)):
        raise ValueError("pipeline step keys must be unique")
    seen: set[str] = set()
    for step in materialized:
        step.validate()
        missing = set(step.depends_on) - set(keys)
        if missing:
            raise ValueError(f"step {step.key} has unknown dependencies: {sorted(missing)}")
        if set(step.depends_on) - seen:
            raise ValueError(f"step {step.key} depends on a later step")
        seen.add(step.key)
    return materialized


def _agent_queue(environment: dict[str, str]) -> str:
    pipeline_class = environment.get("MINDCLADE_PIPELINE_CLASS")
    execution_tier = environment.get("MINDCLADE_EXECUTION_TIER")
    if pipeline_class == "gpu":
        return "mindclade-gpu"
    if execution_tier == "untrusted":
        return "mindclade-untrusted-cpu"
    if execution_tier == "trusted":
        return "mindclade-trusted-cpu"
    if execution_tier == "release":
        return "mindclade-release"
    raise ValueError("pipeline execution tier has no approved agent queue")


def render_pipeline(steps: Iterable[Step], environment: dict[str, str]) -> dict[str, Any]:
    materialized = validate_pipeline(steps)
    for key in environment:
        if not key.startswith("MINDCLADE_"):
            raise ValueError("pipeline environment contains an ungoverned value")
    queue = _agent_queue(environment)
    rendered_steps: list[dict[str, Any]] = []
    for step in materialized:
        rendered = step.as_mapping()
        rendered["agents"] = {"queue": queue}
        rendered_steps.append(rendered)
    return {
        "env": dict(sorted(environment.items())),
        "steps": rendered_steps,
    }
