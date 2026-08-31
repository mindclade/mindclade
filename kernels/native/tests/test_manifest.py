import hashlib
import json
from pathlib import Path

import pytest

from kernels.native.tilelang.manifest import load_manifest, validate_manifest

ROOT = Path(__file__).resolve().parents[1]

EXPECTED_DECLARED_TILELANG_OPERATORS = (
    (
        "outer_product_mean",
        "tilelang",
        "pairformer/outer_product_mean/tilelang.py",
    ),
    (
        "pair_weighted_average",
        "tilelang",
        "pairformer/pair_weighted_average/tilelang.py",
    ),
    (
        "triangle_attention",
        "tilelang",
        "pairformer/triangle_attention/tilelang.py",
    ),
    (
        "triangle_multiplication",
        "tilelang",
        "pairformer/triangle_multiplication/tilelang.py",
    ),
)


def test_manifest_is_strict_closed_world_target_inventory():
    manifest = load_manifest(ROOT)
    assert set(manifest) == {
        "schema_version",
        "generator",
        "source_inventory_sha256",
        "namespace",
        "registration_mode",
        "optimized_math_authority",
        "runtime_discovery",
        "request_time_compilation",
        "operators",
        "semantic_digest",
    }
    assert manifest["schema_version"] == 2
    assert manifest["namespace"] == "mindclade"
    assert manifest["runtime_discovery"] is False
    assert manifest["request_time_compilation"] is False
    operators = manifest["operators"]
    assert tuple(
        (operator["name"], operator["backend"], operator["source"])
        for operator in operators
    ) == EXPECTED_DECLARED_TILELANG_OPERATORS
    assert all("qualification" not in operator for operator in operators)


def test_manifest_semantic_digest_matches_canonical_content():
    manifest = json.loads(
        (ROOT / "generated" / "native_ops.json").read_text(encoding="utf-8")
    )
    digest = manifest.pop("semantic_digest")
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert digest == "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def test_manifest_load_never_regenerates_missing_output(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_manifest(tmp_path)
    assert not (tmp_path / "generated").exists()


def test_manifest_rejects_digest_or_namespace_tampering():
    manifest = json.loads(
        (ROOT / "generated" / "native_ops.json").read_text(encoding="utf-8")
    )
    manifest["namespace"] = "other"
    with pytest.raises(ValueError, match="namespace"):
        validate_manifest(manifest)
