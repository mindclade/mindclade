from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from kernels.native.python.qualification import (
    QualificationConfig,
    canonical_receipt,
    receipt_digest,
    select_compiled_artifact,
    select_specialization,
)


_DIGEST = "sha256:" + "0" * 64


def test_config_is_bounded_and_hardware_specific():
    config = QualificationConfig(
        operator="triangle_attention",
        profile="b1_n64_h8_d32_fp16",
        target="sm90",
        artifact_digest=_DIGEST,
        source_digest=_DIGEST,
        atol=1e-3,
        rtol=1e-3,
    )
    assert config.target == "sm90"
    with pytest.raises(ValueError, match="target"):
        QualificationConfig(
            operator="triangle_attention",
            profile="profile",
            target="auto",
            artifact_digest=_DIGEST,
            source_digest=_DIGEST,
            atol=0,
            rtol=0,
        )


def test_receipt_serialization_is_canonical_and_digest_stable():
    receipt = {"z": 1, "a": {"b": True}}
    assert canonical_receipt(receipt) == b'{"a":{"b":true},"z":1}\n'
    assert receipt_digest(receipt) == receipt_digest(json.loads(canonical_receipt(receipt)))


def test_offline_selection_is_exact_and_receipt_bound():
    arguments = {"batch": 1, "n": 64, "dtype": "float16"}
    profiles = [{"name": "b1_n64_fp16", "arguments": arguments}]
    assert select_specialization(profiles, arguments) == "b1_n64_fp16"
    with pytest.raises(LookupError, match="exactly one"):
        select_specialization(profiles, {**arguments, "n": 65})

    receipt = {
        "artifact_sha256": _DIGEST,
        "compiler": "tilelang",
        "compiler_version": "0.1.13",
        "output": "triangle_attention.b1_n64_fp16.cuda.tilelang-source",
        "profile": "b1_n64_fp16",
        "qualified_name": "mindclade::triangle_attention",
        "source_sha256": _DIGEST,
        "target": "cuda",
    }
    assert select_compiled_artifact(
        [receipt],
        qualified_name="mindclade::triangle_attention",
        profile="b1_n64_fp16",
        target="cuda",
        source_digest=_DIGEST,
    ) is receipt
    with pytest.raises(RuntimeError, match="0.1.13"):
        select_compiled_artifact(
            [{**receipt, "compiler_version": "0.1.14"}],
            qualified_name="mindclade::triangle_attention",
            profile="b1_n64_fp16",
            target="cuda",
            source_digest=_DIGEST,
        )


def test_performance_policy_covers_every_declared_profile_without_fake_baselines():
    manifests = Path(__file__).resolve().parents[1] / "manifests"
    policy = json.loads((manifests / "performance_policy.json").read_text())
    assert policy["max_regression_percent"] == 5.0
    assert policy["minimum_iterations"] >= 100
    for target in ("sm90", "sm100"):
        profiles = json.loads((manifests / f"tilelang_profiles.{target}.json").read_text())
        declared = {
            operator: sorted(profile["name"] for profile in values)
            for operator, values in profiles.items()
        }
        assert policy["targets"][target] == declared
        assert policy["baselines"][target] == {
            "status": "UNMEASURED",
            "receipt_digest": None,
        }


def test_benchmark_and_qualification_schemas_accept_bounded_evidence():
    manifests = Path(__file__).resolve().parents[1] / "manifests"
    benchmark_schema = json.loads((manifests / "benchmark.schema.json").read_text())
    qualification_schema = json.loads((manifests / "qualification.schema.json").read_text())
    Draft202012Validator.check_schema(benchmark_schema)
    Draft202012Validator.check_schema(qualification_schema)
    Draft202012Validator(benchmark_schema).validate(
        {
            "schema_version": 1,
            "operator": "mindclade::triangle_attention",
            "profile": "b1_n64_h8_d32_fp16",
            "target": "sm90",
            "artifact_digest": _DIGEST,
            "source_digest": _DIGEST,
            "evidence_class": "UNSIGNED_CANDIDATE",
            "hardware": {"compute_capability": "9.0", "device_name": "H100"},
            "toolchain": {"cuda": "12.8", "torch": "2.10.0"},
            "measurement": {"iterations": 100, "latency_us": 10.0, "warmup": 10},
            "numerical": {"atol": 0.001, "rtol": 0.001},
            "opcheck": {},
        }
    )
    Draft202012Validator(qualification_schema).validate(
        {
            "schema_version": 1,
            "benchmark_receipt_digest": _DIGEST,
            "bundle_digest": _DIGEST,
            "operator": "mindclade::triangle_attention",
            "profile": "b1_n64_h8_d32_fp16",
            "target": "sm90",
            "review": {"independent": True, "revision": "0" * 40},
            "status": "CANDIDATE",
        }
    )
