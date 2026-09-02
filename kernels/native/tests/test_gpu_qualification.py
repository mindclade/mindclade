from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

from jsonschema import Draft202012Validator
import pytest

from kernels.native.python.gpu_qualification import (
    GPUQualificationError,
    ObservedEnvironment,
    assert_pinned_environment,
    build_candidate_receipt,
    build_tuning_decision,
    load_plan,
    validate_profile_inventories,
)


ROOT = Path(__file__).resolve().parents[3]
PLAN_PATH = ROOT / "kernels/native/manifests/pairformer_gpu_qualification.json"
SCHEMA_PATH = ROOT / "kernels/native/manifests/pairformer_gpu_qualification.schema.json"
DIGEST = "sha256:" + "1" * 64


def _plan():
    return load_plan(PLAN_PATH)


def _environment(architecture: str) -> ObservedEnvironment:
    if architecture == "sm90a":
        compute_capability = "9.0"
        gpu_sku = "NVIDIA H100 80GB HBM3"
    else:
        compute_capability = "10.0"
        gpu_sku = "NVIDIA B200"
    return ObservedEnvironment(
        architecture=architecture,
        compute_capability=compute_capability,
        gpu_sku=gpu_sku,
        tilelang="0.1.13",
        cuda="12.9",
        nvcc="12.9.86",
        pytorch="2.10.0",
    )


def _observation() -> dict[str, object]:
    return {
        "schema_version": 1,
        "operation": "mindclade::triangle_attention",
        "profile": "b1_n64_h8_d32_bf16",
        "architecture": "sm90a",
        "schedule_id": "triangle_attention_sm90a_tma",
        "toolchain": {
            "tilelang": "0.1.13",
            "cuda": "12.9",
            "nvcc": "12.9.86",
            "pytorch": "2.10.0",
        },
        "hardware": {
            "compute_capability": "9.0",
            "gpu_sku": "NVIDIA H100 80GB HBM3",
        },
        "checks": {
            "forward_reference": True,
            "backward_reference": True,
            "all_named_gradients": True,
            "opcheck": True,
            "torch_compile": True,
            "non_default_stream": True,
            "cuda_graph_capture": True,
            "workspace_stable": True,
            "determinism": True,
            "nan_inf_policy": True,
        },
        "execution": {
            "non_default_stream_id": "cuda_stream_test_only_7",
            "cuda_graph_replays": 10,
            "workspace_peak_bytes": 1048576,
            "workspace_growth_bytes": 0,
            "determinism_repetitions": 10,
        },
        "numerical": {
            "envelope_digest": DIGEST,
            "passed": True,
            "nan_count": 0,
            "inf_count": 0,
            "max_errors": {
                "output": 0.001,
                "grad_q": 0.002,
                "grad_k": 0.002,
                "grad_v": 0.001,
                "grad_bias": 0.003,
            },
        },
        "benchmark": {
            "warmup": 20,
            "candidate_samples_us": [10.0 + index / 1000 for index in range(100)],
            "baseline_samples_us": [12.0 + index / 1000 for index in range(100)],
            "baseline_digest": "sha256:" + "2" * 64,
            "performance_passed": True,
        },
    }


def test_plan_schema_and_profile_inventories_are_exact():
    schema = json.loads(SCHEMA_PATH.read_text())
    value = json.loads(PLAN_PATH.read_text())
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(value)
    plan = _plan()
    validate_profile_inventories(plan, ROOT)
    assert tuple(lane.architecture for lane in plan.lanes) == ("sm90a", "sm100a")


def test_candidate_spaces_are_bounded_and_architecture_independent():
    plan = _plan()
    sm90a = plan.lane("sm90a")
    sm100a = plan.lane("sm100a")
    assert len(sm90a.candidate_spaces) == len(sm100a.candidate_spaces) == 5
    sm90a_digests = {
        candidate.digest
        for _operation, candidates in sm90a.candidate_spaces
        for candidate in candidates
    }
    sm100a_digests = {
        candidate.digest
        for _operation, candidates in sm100a.candidate_spaces
        for candidate in candidates
    }
    assert sm90a_digests.isdisjoint(sm100a_digests)
    for operation, candidates in sm90a.candidate_spaces:
        assert 2 <= len(candidates) <= 8, operation
        assert all(candidate.use_tma and candidate.use_wgmma for candidate in candidates)
        assert all(not candidate.use_tcgen05 for candidate in candidates)
        assert any(candidate.cluster_m * candidate.cluster_n > 1 for candidate in candidates)
    for operation, candidates in sm100a.candidate_spaces:
        assert 2 <= len(candidates) <= 8, operation
        assert all(candidate.use_tma and candidate.use_tcgen05 for candidate in candidates)
        assert all(not candidate.use_wgmma for candidate in candidates)
        assert any(candidate.cluster_m * candidate.cluster_n > 1 for candidate in candidates)


def test_toolchain_and_hardware_assertions_fail_closed():
    lane = _plan().lane("sm90a")
    assert_pinned_environment(lane, _environment("sm90a"))
    with pytest.raises(GPUQualificationError, match="pytorch"):
        assert_pinned_environment(
            lane, replace(_environment("sm90a"), pytorch="2.10.1")
        )
    with pytest.raises(GPUQualificationError, match="architecture"):
        assert_pinned_environment(lane, _environment("sm100a"))


def test_candidate_receipt_is_content_addressed_but_never_promotable():
    receipt = build_candidate_receipt(
        _plan(),
        _observation(),
        artifact_digest=DIGEST,
        source_digest=DIGEST,
        numerical_envelope_digest=DIGEST,
    )
    assert receipt == build_candidate_receipt(
        _plan(),
        _observation(),
        artifact_digest=DIGEST,
        source_digest=DIGEST,
        numerical_envelope_digest=DIGEST,
    )
    assert receipt["evidence_class"] == "UNSIGNED_GPU_CANDIDATE"
    assert receipt["qualification_status"] == "UNQUALIFIED_CANDIDATE"
    assert receipt["promotion_eligible"] is False
    assert receipt["benchmark"]["measurements"] == 100
    assert receipt["receipt_digest"].startswith("sha256:")


def test_receipt_rejects_missing_protocol_evidence_and_benchmark_theater():
    observation = _observation()
    observation["checks"]["cuda_graph_capture"] = False
    with pytest.raises(GPUQualificationError, match="every qualification"):
        build_candidate_receipt(
            _plan(), observation,
            artifact_digest=DIGEST, source_digest=DIGEST,
            numerical_envelope_digest=DIGEST,
        )


def test_tuning_decision_is_deterministic_and_never_promotable():
    first = build_candidate_receipt(
        _plan(), _observation(), artifact_digest=DIGEST,
        source_digest=DIGEST, numerical_envelope_digest=DIGEST,
    )
    second_observation = _observation()
    second_observation["schedule_id"] = "triangle_attention_sm90a_cluster"
    second_observation["benchmark"]["candidate_samples_us"] = [
        9.0 + index / 1000 for index in range(100)
    ]
    second = build_candidate_receipt(
        _plan(), second_observation, artifact_digest=DIGEST,
        source_digest=DIGEST, numerical_envelope_digest=DIGEST,
    )
    decision = build_tuning_decision((first, second))
    assert decision["winner_receipt_digest"] == second["receipt_digest"]
    assert decision["selection"] == "minimum_median_us_then_schedule_digest"
    assert decision["promotion_eligible"] is False
    assert decision["qualification_status"] == "UNQUALIFIED_CANDIDATE"
    observation = _observation()
    observation["benchmark"]["candidate_samples_us"] = [10.0]
    with pytest.raises(GPUQualificationError, match="exactly 100"):
        build_candidate_receipt(
            _plan(), observation,
            artifact_digest=DIGEST, source_digest=DIGEST,
            numerical_envelope_digest=DIGEST,
        )
    observation = _observation()
    observation["numerical"]["envelope_digest"] = "sha256:" + "2" * 64
    with pytest.raises(GPUQualificationError, match="reviewed numerical"):
        build_candidate_receipt(
            _plan(), observation,
            artifact_digest=DIGEST, source_digest=DIGEST,
            numerical_envelope_digest=DIGEST,
        )
