"""Buildkite adapter for the canonical repository affected-target selector."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType


def _load_selector() -> ModuleType:
    root = Path(__file__).resolve().parents[2]
    source = root / "tools/ci/affected_targets.py"
    spec = importlib.util.spec_from_file_location("mindclade_affected_targets", source)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load affected-target selector: {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def select(changed_paths: list[str]) -> list[str]:
    module = _load_selector()
    return list(module.targets_for_paths(changed_paths))
