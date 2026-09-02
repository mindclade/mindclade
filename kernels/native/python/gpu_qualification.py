# Copyright (c) 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

"""Source-only Pairformer GPU qualification and tuning contracts.

This module validates bounded offline plans and converts externally produced GPU
observations into unsigned, content-addressed candidate receipts. It never
compiles, tunes, signs, promotes, or selects a runtime capability.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
from importlib import metadata
import json
import math
from pathlib import Path
import re
import statistics
import subprocess
from typing import Any


_OPERATIONS = (
    "mindclade::outer_product_mean",
    "mindclade::pair_weighted_average",
    "mindclade::transition",
    "mindclade::triangle_attention",
    "mindclade::triangle_multiplication",
)
_LANES = ("sm90a", "sm100a")
_PINNED_TOOLCHAIN = {
    "tilelang": "0.1.13",
    "cuda": "12.9",
    "nvcc": "12.9.86",
    "pytorch": "2.10.0",
}
_PLAN_KEYS = frozenset(
    {"schema_version", "status", "lane_order", "toolchain", "protocols", "lanes"}
)
_LANE_KEYS = frozenset(
    {
        "architecture",
        "compute_capability",
        "independent",
        "evidence_reuse",
        "allowed_gpu_skus",
        "profiles_manifest",
        "features",
        "candidate_spaces",
    }
)
_FEATURE_KEYS = frozenset({"tma", "wgmma", "tcgen05", "cluster_launch"})
_SCHEDULE_KEYS = frozenset(
    {
        "id",
        "block_m",
        "block_n",
        "block_k",
        "threads",
        "num_stages",
        "vector_width",
        "use_tma",
        "use_wgmma",
        "use_tcgen05",
        "cluster_m",
        "cluster_n",
        "persistent",
        "split_k",
    }
)
_OBSERVATION_KEYS = frozenset(
    {
        "schema_version",
        "operation",
        "profile",
        "architecture",
        "schedule_id",
        "toolchain",
        "hardware",
        "checks",
        "execution",
        "numerical",
        "benchmark",
    }
)
_CHECKS = (
    "forward_reference",
    "backward_reference",
    "all_named_gradients",
    "opcheck",
    "torch_compile",
    "non_default_stream",
    "cuda_graph_capture",
    "workspace_stable",
    "determinism",
    "nan_inf_policy",
)
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_IDENTIFIER_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


class GPUQualificationError(RuntimeError):
    """A source plan, observed environment, or evidence bundle is invalid."""


def _canonical_json(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError) as exc:
        raise GPUQualificationError("value is not canonical JSON data") from exc


def _digest(value: object) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(value)).hexdigest()


def _require_digest(value: object, label: str) -> str:
    if not isinstance(value, str) or _DIGEST_RE.fullmatch(value) is None:
        raise GPUQualificationError(f"{label} must be sha256:<64 lowercase hex>")
    return value


def _object(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise GPUQualificationError(f"{label} must be an object with string keys")
    return value


def _exact_keys(value: Mapping[str, object], expected: frozenset[str], label: str) -> None:
    if frozenset(value) != expected:
        raise GPUQualificationError(f"{label} has missing or unknown fields")


@dataclass(frozen=True, slots=True)
class ScheduleCandidate:
    id: str
    block_m: int
    block_n: int
    block_k: int
    threads: int
    num_stages: int
    vector_width: int
    use_tma: bool
    use_wgmma: bool
    use_tcgen05: bool
    cluster_m: int
    cluster_n: int
    persistent: bool
    split_k: int

    @classmethod
    def from_data(cls, value: object, *, lane: str, operation: str) -> "ScheduleCandidate":
        raw = _object(value, f"{lane}/{operation} candidate")
        _exact_keys(raw, _SCHEDULE_KEYS, f"{lane}/{operation} candidate")
        identifier = raw["id"]
        if not isinstance(identifier, str) or _IDENTIFIER_RE.fullmatch(identifier) is None:
            raise GPUQualificationError("candidate id must be lower_snake_case")
        integer_bounds = {
            "block_m": (16, 256),
            "block_n": (16, 256),
            "block_k": (8, 128),
            "threads": (64, 512),
            "num_stages": (1, 8),
            "vector_width": (1, 16),
            "cluster_m": (1, 4),
            "cluster_n": (1, 4),
            "split_k": (1, 8),
        }
        integers: dict[str, int] = {}
        for field, (minimum, maximum) in integer_bounds.items():
            item = raw[field]
            if type(item) is not int or not minimum <= item <= maximum:
                raise GPUQualificationError(f"candidate {field} is outside bounded range")
            integers[field] = item
        booleans: dict[str, bool] = {}
        for field in ("use_tma", "use_wgmma", "use_tcgen05", "persistent"):
            item = raw[field]
            if type(item) is not bool:
                raise GPUQualificationError(f"candidate {field} must be boolean")
            booleans[field] = item
        if integers["threads"] % 32 != 0:
            raise GPUQualificationError("candidate threads must be warp-aligned")
        if not booleans["use_tma"]:
            raise GPUQualificationError("Pairformer architecture candidates must use TMA")
        if lane == "sm90a" and (not booleans["use_wgmma"] or booleans["use_tcgen05"]):
            raise GPUQualificationError("sm90a candidates require WGMMA and prohibit TCGEN05")
        if lane == "sm100a" and (booleans["use_wgmma"] or not booleans["use_tcgen05"]):
            raise GPUQualificationError("sm100a candidates require TCGEN05 and are independently tuned")
        return cls(id=identifier, **integers, **booleans)

    @property
    def digest(self) -> str:
        return _digest({field: getattr(self, field) for field in self.__dataclass_fields__})


@dataclass(frozen=True, slots=True)
class ArchitectureLane:
    architecture: str
    compute_capability: str
    allowed_gpu_skus: tuple[str, ...]
    profiles_manifest: str
    features: tuple[tuple[str, bool], ...]
    candidate_spaces: tuple[tuple[str, tuple[ScheduleCandidate, ...]], ...]

    def candidates(self, operation: str) -> tuple[ScheduleCandidate, ...]:
        return dict(self.candidate_spaces)[operation]


@dataclass(frozen=True, slots=True)
class QualificationPlan:
    lanes: tuple[ArchitectureLane, ...]
    protocols: Mapping[str, object]
    digest: str

    def lane(self, architecture: str) -> ArchitectureLane:
        matches = [lane for lane in self.lanes if lane.architecture == architecture]
        if len(matches) != 1:
            raise GPUQualificationError(f"unknown architecture lane {architecture!r}")
        return matches[0]


def load_plan(path: Path) -> QualificationPlan:
    raw_value = json.loads(path.read_text(encoding="utf-8"))
    raw = _object(raw_value, "qualification plan")
    _exact_keys(raw, _PLAN_KEYS, "qualification plan")
    if raw["schema_version"] != 1 or raw["status"] != "SOURCE_ONLY_UNQUALIFIED":
        raise GPUQualificationError("qualification plan status/version is unsupported")
    if raw["lane_order"] != list(_LANES):
        raise GPUQualificationError("qualification lanes must be SM90a-first and independently SM100a")
    if raw["toolchain"] != _PINNED_TOOLCHAIN:
        raise GPUQualificationError("qualification toolchain pins drifted")
    protocols = _object(raw["protocols"], "protocols")
    if frozenset(protocols) != {"numerical", "execution", "benchmark"}:
        raise GPUQualificationError("qualification protocols are incomplete")
    numerical = _object(protocols["numerical"], "numerical protocol")
    if frozenset(numerical) != {
        "reviewed_envelope_required",
        "reject_nan_inf",
        "required_results",
    } or numerical.get("reviewed_envelope_required") is not True or numerical.get(
        "reject_nan_inf"
    ) is not True or numerical.get("required_results") != [
        "forward",
        "saved_outputs",
        "all_named_gradients",
    ]:
        raise GPUQualificationError("numerical protocol must fail closed")
    execution = _object(protocols["execution"], "execution protocol")
    required_execution = {
        "non_default_stream": True,
        "cuda_graph_capture": True,
        "cuda_graph_replays": 10,
        "workspace_stability": True,
        "workspace_growth_bytes_max": 0,
        "deterministic_repetitions": 10,
    }
    if dict(execution) != required_execution:
        raise GPUQualificationError("execution protocol drifted")
    benchmark = _object(protocols["benchmark"], "benchmark protocol")
    if frozenset(benchmark) != {
        "warmup",
        "measurements",
        "timing",
        "interleave",
        "raw_samples_required",
        "reviewed_baseline_required",
        "max_regression_percent",
    } or (
        benchmark.get("warmup") != 20
        or benchmark.get("measurements") != 100
        or benchmark.get("timing") != "cuda_events"
        or benchmark.get("interleave") != "candidate_baseline_alternating"
        or benchmark.get("raw_samples_required") is not True
        or benchmark.get("reviewed_baseline_required") is not True
        or benchmark.get("max_regression_percent") != 5.0
    ):
        raise GPUQualificationError("benchmark protocol drifted")
    raw_lanes = _object(raw["lanes"], "lanes")
    if frozenset(raw_lanes) != frozenset(_LANES):
        raise GPUQualificationError("lane mapping is not canonical")
    lanes: list[ArchitectureLane] = []
    candidate_digests: dict[str, set[str]] = {}
    for lane_name in _LANES:
        lane_raw = _object(raw_lanes[lane_name], lane_name)
        _exact_keys(lane_raw, _LANE_KEYS, lane_name)
        if lane_raw["architecture"] != lane_name:
            raise GPUQualificationError("lane architecture mismatch")
        if lane_raw["independent"] is not True or lane_raw["evidence_reuse"] is not False:
            raise GPUQualificationError("architecture evidence reuse is prohibited")
        expected_cc = "9.0" if lane_name == "sm90a" else "10.0"
        if lane_raw["compute_capability"] != expected_cc:
            raise GPUQualificationError("lane compute capability mismatch")
        skus = lane_raw["allowed_gpu_skus"]
        if not isinstance(skus, list) or not skus or any(not isinstance(item, str) for item in skus):
            raise GPUQualificationError("lane GPU SKU allowlist is invalid")
        features_raw = _object(lane_raw["features"], f"{lane_name} features")
        _exact_keys(features_raw, _FEATURE_KEYS, f"{lane_name} features")
        if any(type(value) is not bool for value in features_raw.values()):
            raise GPUQualificationError("lane features must be boolean")
        expected_features = {
            "tma": True,
            "wgmma": lane_name == "sm90a",
            "tcgen05": lane_name == "sm100a",
            "cluster_launch": True,
        }
        if dict(features_raw) != expected_features:
            raise GPUQualificationError("lane features do not match architecture")
        spaces_raw = _object(lane_raw["candidate_spaces"], f"{lane_name} candidate spaces")
        if frozenset(spaces_raw) != frozenset(_OPERATIONS):
            raise GPUQualificationError("candidate-space operation inventory is not canonical")
        spaces: list[tuple[str, tuple[ScheduleCandidate, ...]]] = []
        lane_digests: set[str] = set()
        for operation in _OPERATIONS:
            candidates_raw = spaces_raw[operation]
            if not isinstance(candidates_raw, list) or not 2 <= len(candidates_raw) <= 8:
                raise GPUQualificationError("candidate spaces must contain 2..8 schedules")
            candidates = tuple(
                ScheduleCandidate.from_data(item, lane=lane_name, operation=operation)
                for item in candidates_raw
            )
            if len({candidate.id for candidate in candidates}) != len(candidates):
                raise GPUQualificationError("candidate ids collide")
            if not any(candidate.cluster_m * candidate.cluster_n > 1 for candidate in candidates):
                raise GPUQualificationError("each operation requires a cluster-launch candidate")
            lane_digests.update(candidate.digest for candidate in candidates)
            spaces.append((operation, candidates))
        candidate_digests[lane_name] = lane_digests
        lanes.append(
            ArchitectureLane(
                architecture=lane_name,
                compute_capability=expected_cc,
                allowed_gpu_skus=tuple(skus),
                profiles_manifest=str(lane_raw["profiles_manifest"]),
                features=tuple(sorted((str(key), bool(value)) for key, value in features_raw.items())),
                candidate_spaces=tuple(spaces),
            )
        )
    if candidate_digests["sm90a"].intersection(candidate_digests["sm100a"]):
        raise GPUQualificationError("SM100a must not reuse SM90a schedule identities")
    return QualificationPlan(lanes=tuple(lanes), protocols=protocols, digest=_digest(raw))


def validate_profile_inventories(plan: QualificationPlan, repository_root: Path) -> None:
    """Bind each lane to the explicit checked-in workload profile inventory."""

    root = repository_root.resolve(strict=True)
    for lane in plan.lanes:
        path = (root / lane.profiles_manifest).resolve(strict=True)
        if root not in path.parents:
            raise GPUQualificationError("profile manifest escapes repository root")
        value = json.loads(path.read_text(encoding="utf-8"))
        profiles = _object(value, f"{lane.architecture} profiles")
        if frozenset(profiles) != frozenset(_OPERATIONS):
            raise GPUQualificationError("profile operation inventory is not canonical")
        for operation in _OPERATIONS:
            entries = profiles[operation]
            if not isinstance(entries, list) or not entries:
                raise GPUQualificationError("profile inventory must be nonempty")
            names: list[str] = []
            for entry_value in entries:
                entry = _object(entry_value, f"{operation} profile")
                if frozenset(entry) != {"name", "arguments"}:
                    raise GPUQualificationError("profile entry fields drifted")
                name = entry["name"]
                arguments = _object(entry["arguments"], f"{operation} arguments")
                if not isinstance(name, str) or _IDENTIFIER_RE.fullmatch(name) is None:
                    raise GPUQualificationError("profile name is invalid")
                if arguments.get("architecture") != lane.architecture:
                    raise GPUQualificationError("profile architecture crosses lanes")
                if arguments.get("dtype") not in {"float16", "bfloat16"}:
                    raise GPUQualificationError("profile dtype is unsupported")
                names.append(name)
            if len(names) != len(set(names)):
                raise GPUQualificationError("profile names are not unique")


@dataclass(frozen=True, slots=True)
class ObservedEnvironment:
    architecture: str
    compute_capability: str
    gpu_sku: str
    tilelang: str
    cuda: str
    nvcc: str
    pytorch: str


def assert_pinned_environment(lane: ArchitectureLane, observed: ObservedEnvironment) -> None:
    if observed.architecture != lane.architecture or observed.compute_capability != lane.compute_capability:
        raise GPUQualificationError("observed GPU architecture does not match the exact lane")
    if observed.gpu_sku not in lane.allowed_gpu_skus:
        raise GPUQualificationError("observed GPU SKU is not qualified for this lane")
    for field, expected in _PINNED_TOOLCHAIN.items():
        if getattr(observed, field) != expected:
            raise GPUQualificationError(f"observed {field} does not match the pinned toolchain")


def detect_environment(architecture: str) -> ObservedEnvironment:
    try:
        import torch
    except ImportError as exc:
        raise GPUQualificationError("PyTorch 2.10.0 is required") from exc
    try:
        tilelang_version = metadata.version("tilelang")
    except metadata.PackageNotFoundError as exc:
        raise GPUQualificationError("TileLang 0.1.13 is required") from exc
    if not torch.cuda.is_available():
        raise GPUQualificationError("an exact NVIDIA GPU lane is required")
    major, minor = torch.cuda.get_device_capability()
    try:
        nvcc_output = subprocess.run(
            ["nvcc", "--version"], check=True, capture_output=True, text=True, timeout=15
        ).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        raise GPUQualificationError("pinned nvcc 12.9.86 is required") from exc
    match = re.search(r"V(\d+\.\d+\.\d+)", nvcc_output)
    if match is None:
        raise GPUQualificationError("nvcc version output is not recognized")
    return ObservedEnvironment(
        architecture=architecture,
        compute_capability=f"{major}.{minor}",
        gpu_sku=torch.cuda.get_device_name(),
        tilelang=tilelang_version,
        cuda=str(torch.version.cuda),
        nvcc=match.group(1),
        pytorch=str(torch.__version__).split("+", 1)[0],
    )


def build_candidate_receipt(
    plan: QualificationPlan,
    observation_value: object,
    *,
    artifact_digest: str,
    source_digest: str,
    numerical_envelope_digest: str,
) -> dict[str, object]:
    """Validate complete GPU observations and emit an unsigned candidate only."""

    artifact_digest = _require_digest(artifact_digest, "artifact_digest")
    source_digest = _require_digest(source_digest, "source_digest")
    numerical_envelope_digest = _require_digest(
        numerical_envelope_digest, "numerical_envelope_digest"
    )
    observation = _object(observation_value, "observation")
    _exact_keys(observation, _OBSERVATION_KEYS, "observation")
    if observation["schema_version"] != 1:
        raise GPUQualificationError("observation schema version is unsupported")
    operation = observation["operation"]
    if operation not in _OPERATIONS:
        raise GPUQualificationError("observation operation is unsupported")
    profile = observation["profile"]
    if not isinstance(profile, str) or _IDENTIFIER_RE.fullmatch(profile) is None:
        raise GPUQualificationError("observation profile is invalid")
    architecture = observation["architecture"]
    lane = plan.lane(str(architecture))
    schedule_id = observation["schedule_id"]
    schedules = [item for item in lane.candidates(str(operation)) if item.id == schedule_id]
    if len(schedules) != 1:
        raise GPUQualificationError("observation schedule is not a declared candidate")
    toolchain = _object(observation["toolchain"], "observation toolchain")
    hardware = _object(observation["hardware"], "observation hardware")
    if frozenset(toolchain) != frozenset(_PINNED_TOOLCHAIN):
        raise GPUQualificationError("observation toolchain fields drifted")
    if frozenset(hardware) != {"compute_capability", "gpu_sku"}:
        raise GPUQualificationError("observation hardware fields drifted")
    assert_pinned_environment(
        lane,
        ObservedEnvironment(
            architecture=lane.architecture,
            compute_capability=str(hardware["compute_capability"]),
            gpu_sku=str(hardware["gpu_sku"]),
            tilelang=str(toolchain["tilelang"]),
            cuda=str(toolchain["cuda"]),
            nvcc=str(toolchain["nvcc"]),
            pytorch=str(toolchain["pytorch"]),
        ),
    )
    checks = _object(observation["checks"], "observation checks")
    if frozenset(checks) != frozenset(_CHECKS) or any(
        value is not True for value in checks.values()
    ):
        raise GPUQualificationError("every qualification protocol check must pass explicitly")
    execution_observation = _object(observation["execution"], "observation execution")
    if frozenset(execution_observation) != {
        "non_default_stream_id",
        "cuda_graph_replays",
        "workspace_peak_bytes",
        "workspace_growth_bytes",
        "determinism_repetitions",
    }:
        raise GPUQualificationError("execution observation fields drifted")
    stream_id = execution_observation["non_default_stream_id"]
    if not isinstance(stream_id, str) or not stream_id:
        raise GPUQualificationError("non-default stream identity is missing")
    if execution_observation["cuda_graph_replays"] != 10:
        raise GPUQualificationError("CUDA graph replay count does not match protocol")
    peak_bytes = execution_observation["workspace_peak_bytes"]
    growth_bytes = execution_observation["workspace_growth_bytes"]
    if type(peak_bytes) is not int or peak_bytes < 0 or growth_bytes != 0:
        raise GPUQualificationError("workspace allocation is unstable")
    if execution_observation["determinism_repetitions"] != 10:
        raise GPUQualificationError("determinism repetition count does not match protocol")
    numerical = _object(observation["numerical"], "observation numerical")
    if frozenset(numerical) != {
        "envelope_digest",
        "passed",
        "max_errors",
        "nan_count",
        "inf_count",
    }:
        raise GPUQualificationError("numerical observation fields drifted")
    if numerical["envelope_digest"] != numerical_envelope_digest or numerical["passed"] is not True:
        raise GPUQualificationError("reviewed numerical envelope did not pass")
    if numerical["nan_count"] != 0 or numerical["inf_count"] != 0:
        raise GPUQualificationError("numerical observation contains NaN or Inf")
    max_errors = _object(numerical["max_errors"], "numerical max_errors")
    if not max_errors or any(
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(float(value))
        or float(value) < 0
        for value in max_errors.values()
    ):
        raise GPUQualificationError("numerical max errors are invalid")
    benchmark = _object(observation["benchmark"], "observation benchmark")
    if frozenset(benchmark) != {
        "warmup",
        "candidate_samples_us",
        "baseline_samples_us",
        "baseline_digest",
        "performance_passed",
    }:
        raise GPUQualificationError("benchmark observation fields drifted")
    if benchmark["warmup"] != 20:
        raise GPUQualificationError("benchmark warmup does not match protocol")
    candidate_samples = benchmark["candidate_samples_us"]
    baseline_samples = benchmark["baseline_samples_us"]
    baseline_digest = _require_digest(benchmark["baseline_digest"], "baseline_digest")
    if benchmark["performance_passed"] is not True:
        raise GPUQualificationError("reviewed performance comparison did not pass")
    if not isinstance(candidate_samples, list) or not isinstance(baseline_samples, list):
        raise GPUQualificationError("benchmark samples must be retained arrays")
    if len(candidate_samples) != 100 or len(baseline_samples) != 100:
        raise GPUQualificationError("benchmark requires exactly 100 interleaved samples")
    for sample in [*candidate_samples, *baseline_samples]:
        if not isinstance(sample, (int, float)) or isinstance(sample, bool) or not math.isfinite(float(sample)) or sample <= 0:
            raise GPUQualificationError("benchmark samples must be finite positive values")
    candidate_values = [float(value) for value in candidate_samples]
    baseline_values = [float(value) for value in baseline_samples]
    candidate_median = statistics.median(candidate_values)
    baseline_median = statistics.median(baseline_values)
    regression_percent = (candidate_median / baseline_median - 1.0) * 100.0
    if regression_percent > 5.0:
        raise GPUQualificationError("candidate exceeds the 5 percent regression gate")
    body: dict[str, object] = {
        "schema_version": 1,
        "evidence_class": "UNSIGNED_GPU_CANDIDATE",
        "qualification_status": "UNQUALIFIED_CANDIDATE",
        "promotion_eligible": False,
        "operation": operation,
        "profile": profile,
        "architecture": lane.architecture,
        "plan_digest": plan.digest,
        "schedule_id": schedules[0].id,
        "schedule_digest": schedules[0].digest,
        "artifact_digest": artifact_digest,
        "source_digest": source_digest,
        "numerical_envelope_digest": numerical_envelope_digest,
        "toolchain": dict(toolchain),
        "hardware": dict(hardware),
        "checks": dict(checks),
        "execution": dict(execution_observation),
        "max_errors": dict(max_errors),
        "benchmark": {
            "warmup": 20,
            "measurements": 100,
            "candidate_median_us": candidate_median,
            "candidate_mean_us": statistics.fmean(candidate_values),
            "candidate_p95_us": sorted(candidate_values)[94],
            "baseline_median_us": baseline_median,
            "baseline_digest": baseline_digest,
            "regression_percent": regression_percent,
            "raw_samples_digest": _digest(
                {"candidate_us": candidate_values, "baseline_us": baseline_values}
            ),
        },
    }
    body["receipt_digest"] = _digest(body)
    return body


def build_tuning_decision(
    candidate_receipts: tuple[Mapping[str, object], ...],
) -> dict[str, object]:
    """Select a deterministic offline winner without qualifying or promoting it."""

    if not 2 <= len(candidate_receipts) <= 8:
        raise GPUQualificationError("tuning requires 2..8 candidate receipts")
    identities: set[tuple[object, ...]] = set()
    schedules: set[str] = set()
    ranked: list[tuple[float, str, Mapping[str, object]]] = []
    for receipt in candidate_receipts:
        if receipt.get("evidence_class") != "UNSIGNED_GPU_CANDIDATE" or receipt.get(
            "promotion_eligible"
        ) is not False:
            raise GPUQualificationError("tuning input is not an unqualified candidate")
        declared_digest = receipt.get("receipt_digest")
        body = dict(receipt)
        body.pop("receipt_digest", None)
        if declared_digest != _digest(body):
            raise GPUQualificationError("tuning candidate receipt digest mismatch")
        identity = (
            receipt.get("operation"),
            receipt.get("profile"),
            receipt.get("architecture"),
            receipt.get("plan_digest"),
            receipt.get("artifact_digest"),
            receipt.get("source_digest"),
            receipt.get("numerical_envelope_digest"),
        )
        identities.add(identity)
        schedule_digest = _require_digest(receipt.get("schedule_digest"), "schedule_digest")
        if schedule_digest in schedules:
            raise GPUQualificationError("tuning candidate schedule is duplicated")
        schedules.add(schedule_digest)
        benchmark = _object(receipt.get("benchmark"), "candidate benchmark")
        latency = benchmark.get("candidate_median_us")
        if not isinstance(latency, (int, float)) or isinstance(latency, bool) or latency <= 0:
            raise GPUQualificationError("candidate median latency is invalid")
        ranked.append((float(latency), schedule_digest, receipt))
    if len(identities) != 1:
        raise GPUQualificationError("tuning candidates do not share one exact workload identity")
    ranked.sort(key=lambda item: (item[0], item[1]))
    winner = ranked[0][2]
    body = {
        "schema_version": 1,
        "evidence_class": "UNSIGNED_TUNING_DECISION",
        "qualification_status": "UNQUALIFIED_CANDIDATE",
        "promotion_eligible": False,
        "operation": winner["operation"],
        "profile": winner["profile"],
        "architecture": winner["architecture"],
        "plan_digest": winner["plan_digest"],
        "candidate_receipt_digests": sorted(
            str(receipt["receipt_digest"]) for receipt in candidate_receipts
        ),
        "winner_receipt_digest": winner["receipt_digest"],
        "winner_schedule_digest": winner["schedule_digest"],
        "selection": "minimum_median_us_then_schedule_digest",
    }
    body["receipt_digest"] = _digest(body)
    return body


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pairformer GPU qualification contracts")
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--lane", choices=_LANES)
    parser.add_argument("--verify-environment", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    plan = load_plan(args.plan)
    validate_profile_inventories(plan, Path.cwd())
    if args.verify_environment:
        if args.lane is None:
            parser.error("--verify-environment requires --lane")
        observed = detect_environment(args.lane)
        assert_pinned_environment(plan.lane(args.lane), observed)
        if args.output is not None:
            body: dict[str, object] = {
                "schema_version": 1,
                "evidence_class": "GPU_PREFLIGHT_ONLY",
                "qualification_status": "UNQUALIFIED",
                "promotion_eligible": False,
                "plan_digest": plan.digest,
                "environment": {
                    field: getattr(observed, field)
                    for field in observed.__dataclass_fields__
                },
            }
            body["receipt_digest"] = _digest(body)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps(body, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
                encoding="utf-8",
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
