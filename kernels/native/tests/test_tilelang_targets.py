from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from kernels.native.tilelang.targets import (
    APPROVED_TILELANG_VERSION,
    PORTABLE_CUDA,
    SM90A,
    SM100A,
    TargetCapabilityError,
    capability_manifest,
    normalize_target,
    validate_toolchain,
)


def test_target_normalization_is_explicit_and_deterministic() -> None:
    assert normalize_target("cuda") is PORTABLE_CUDA
    assert normalize_target("sm90a") is SM90A
    assert normalize_target({"kind": "cuda", "arch": "sm_100a"}) is SM100A
    assert SM90A.capability_digest == SM90A.capability_digest


def test_unknown_and_non_cuda_targets_fail_closed() -> None:
    with pytest.raises(TargetCapabilityError, match="unsupported explicit CUDA target"):
        normalize_target("auto")
    with pytest.raises(TargetCapabilityError, match="target kind 'cuda'"):
        normalize_target({"kind": "hip", "arch": "gfx942"})


def test_toolchain_floors_are_architecture_specific() -> None:
    validate_toolchain(SM90A, tilelang_version=APPROVED_TILELANG_VERSION, cuda_version="12.0")
    validate_toolchain(SM100A, tilelang_version=APPROVED_TILELANG_VERSION, cuda_version="12.8")
    with pytest.raises(TargetCapabilityError, match="requires CUDA >= 12.8"):
        validate_toolchain(SM100A, tilelang_version=APPROVED_TILELANG_VERSION, cuda_version="12.7")
    with pytest.raises(TargetCapabilityError, match="TileLang 0.1.13 is required"):
        validate_toolchain(SM90A, tilelang_version="0.1.12")


def test_capability_manifest_has_canonical_identity() -> None:
    manifest = capability_manifest()
    assert manifest["runtime_discovery"] is False
    assert manifest["request_time_compilation"] is False
    assert manifest["semantic_digest"].startswith("sha256:")
    assert len(json.dumps(manifest, sort_keys=True)) > 0


def test_committed_capability_manifest_matches_schema() -> None:
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / "generated/tilelang_capabilities.json").read_text())
    schema = json.loads((root / "manifests/tilelang_capabilities.schema.json").read_text())
    jsonschema.validate(manifest, schema)
    assert manifest == capability_manifest()
