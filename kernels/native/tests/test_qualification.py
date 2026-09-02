from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from kernels.native.python.qualification import (
    K4QualificationReceipt,
    K5ReleaseReceipt,
    PRODUCTION_EVIDENCE,
    TEST_ONLY_EVIDENCE,
    QualificationConfig,
    canonical_receipt,
    receipt_digest,
    select_compiled_artifact,
    select_specialization,
    sign_receipt,
    verify_signed_receipt,
)
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


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


def test_signed_k4_receipt_is_content_addressed_and_test_only():
    key = Ed25519PrivateKey.from_private_bytes(bytes(range(1, 33)))
    receipt = K4QualificationReceipt(
        operation="mindclade::outer_product_mean",
        architecture="sm90a",
        workload_digest=_DIGEST,
        specialization_digest=_DIGEST,
        dimensions=(("residues", 64),),
        attributes=(),
        hardware_fingerprint_digest=_DIGEST,
        compile_environment_digest=_DIGEST,
        runtime_compatibility_digest=_DIGEST,
        numerical_receipt_digest=_DIGEST,
        performance_receipt_digest=_DIGEST,
        benchmark_protocol_digest=_DIGEST,
        raw_samples_digest=_DIGEST,
        forward_artifact_digest=_DIGEST,
        backward_artifact_digest=_DIGEST,
        native_manifest_schema_version=4,
        native_manifest_generator_version=8,
        build_receipt_schema_version=4,
        autograd_policy="required",
        status="TEST_ONLY",
        evidence_class=TEST_ONLY_EVIDENCE,
    )
    signed = sign_receipt(
        receipt, private_key=key, key_id="test-only.qualifier"
    )
    payload = verify_signed_receipt(
        signed,
        trust_roots={"test-only.qualifier": key.public_key()},
        expected_evidence_class=TEST_ONLY_EVIDENCE,
    )
    assert signed.receipt_digest == signed.signature.subject_digest
    assert payload["status"] == "TEST_ONLY"
    for field, obsolete in (
        ("native_manifest_schema_version", 3),
        ("native_manifest_generator_version", 7),
        ("build_receipt_schema_version", 3),
    ):
        with pytest.raises(ValueError, match="obsolete executable ABI receipt"):
            replace(receipt, **{field: obsolete})


def test_test_key_cannot_sign_production_and_required_bwd_is_atomic():
    key = Ed25519PrivateKey.from_private_bytes(bytes(range(1, 33)))
    with pytest.raises(ValueError, match="atomic FWD\\+BWD"):
        K5ReleaseReceipt(
            release_id="release.test",
            operation="mindclade::outer_product_mean",
            operation_version=1,
            implementation="outer_product_mean_tiled",
            implementation_version=1,
            tier="specialized",
            priority=1,
            architecture="sm90a",
            dtype="bfloat16",
            layout="contiguous",
            mode="training",
            workload_digest=_DIGEST,
            specialization_digest=_DIGEST,
            dimensions=(("residues", 64),),
            attributes=(),
            schedule_digest=_DIGEST,
            numerical_envelope_digest=_DIGEST,
            k0_receipt_digest=_DIGEST,
            k1_receipt_digest=_DIGEST,
            k2_receipt_digest=_DIGEST,
            k3_receipt_digest=_DIGEST,
            k4_receipt_digest=_DIGEST,
            bundle_digest=_DIGEST,
            native_manifest_digest=_DIGEST,
            library_digest=_DIGEST,
            executable_plan_digest=_DIGEST,
            forward_artifact_digest=_DIGEST,
            backward_artifact_digest=None,
            runtime_compatibility_digest=_DIGEST,
            compile_environment_digest=_DIGEST,
            sbom_digest=_DIGEST,
            provenance_digest=_DIGEST,
            qualification_identity="qualification.test",
            repository_revision="a" * 40,
            native_manifest_schema_version=4,
            native_manifest_generator_version=8,
            build_receipt_schema_version=4,
            autograd_policy="required",
            status="PASS",
            evidence_class=PRODUCTION_EVIDENCE,
        )
    production_k4 = K4QualificationReceipt(
        operation="mindclade::outer_product_mean",
        architecture="sm90a",
        workload_digest=_DIGEST,
        specialization_digest=_DIGEST,
        dimensions=(("residues", 64),),
        attributes=(),
        hardware_fingerprint_digest=_DIGEST,
        compile_environment_digest=_DIGEST,
        runtime_compatibility_digest=_DIGEST,
        numerical_receipt_digest=_DIGEST,
        performance_receipt_digest=_DIGEST,
        benchmark_protocol_digest=_DIGEST,
        raw_samples_digest=_DIGEST,
        forward_artifact_digest=_DIGEST,
        backward_artifact_digest=_DIGEST,
        native_manifest_schema_version=4,
        native_manifest_generator_version=8,
        build_receipt_schema_version=4,
        autograd_policy="required",
        status="PASS",
        evidence_class=PRODUCTION_EVIDENCE,
    )
    with pytest.raises(ValueError, match="test-only key"):
        sign_receipt(
            production_k4,
            private_key=key,
            key_id="test-only.qualifier",
        )
