# Copyright (c) 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

"""Fail-closed CUDA evidence-candidate qualification for Mindclade operators."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import hashlib
import json
import math
from typing import Any

_OPERATORS = frozenset(
    {
        "outer_product_mean",
        "pair_weighted_average",
        "triangle_attention",
        "triangle_multiplication",
        "transition",
    }
)
_TARGET_CAPABILITIES = {"sm90": (9, 0), "sm100": (10, 0)}


def _digest(value: str, label: str) -> str:
    if not isinstance(value, str) or len(value) != 71 or not value.startswith("sha256:"):
        raise ValueError(f"{label} must use sha256:<64 lowercase hex>")
    payload = value.removeprefix("sha256:")
    if any(character not in "0123456789abcdef" for character in payload):
        raise ValueError(f"{label} must use sha256:<64 lowercase hex>")
    return value


@dataclass(frozen=True, slots=True)
class QualificationConfig:
    operator: str
    profile: str
    target: str
    artifact_digest: str
    source_digest: str
    atol: float
    rtol: float
    warmup: int = 10
    iterations: int = 100
    deterministic: bool = True

    def __post_init__(self) -> None:
        if self.operator not in _OPERATORS:
            raise ValueError(f"unsupported Mindclade operator: {self.operator!r}")
        if self.target not in _TARGET_CAPABILITIES:
            raise ValueError("target must be sm90 or sm100")
        if not self.profile or len(self.profile) > 64:
            raise ValueError("profile must be a nonempty bounded identifier")
        _digest(self.artifact_digest, "artifact_digest")
        _digest(self.source_digest, "source_digest")
        if not math.isfinite(self.atol) or self.atol < 0:
            raise ValueError("atol must be finite and nonnegative")
        if not math.isfinite(self.rtol) or self.rtol < 0:
            raise ValueError("rtol must be finite and nonnegative")
        if not 1 <= self.warmup <= 10_000 or not 1 <= self.iterations <= 1_000_000:
            raise ValueError("warmup and iterations are outside bounded ranges")


def canonical_receipt(receipt: Mapping[str, object]) -> bytes:
    """Serialize an evidence candidate canonically for hashing and signing."""

    return (json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n").encode()


def receipt_digest(receipt: Mapping[str, object]) -> str:
    return "sha256:" + hashlib.sha256(canonical_receipt(receipt)).hexdigest()


def select_specialization(
    profiles: tuple[Mapping[str, object], ...] | list[Mapping[str, object]],
    runtime_arguments: Mapping[str, object],
) -> str:
    """Select exactly one predeclared specialization without compiling."""

    matches: list[str] = []
    for profile in profiles:
        if set(profile) != {"name", "arguments"}:
            raise ValueError("profile entries must contain exactly name and arguments")
        name = profile["name"]
        arguments = profile["arguments"]
        if not isinstance(name, str) or not isinstance(arguments, Mapping):
            raise ValueError("profile name and arguments have invalid types")
        if dict(arguments) == dict(runtime_arguments):
            matches.append(name)
    if len(matches) != 1:
        raise LookupError(
            f"offline specialization requires exactly one match, observed {len(matches)}"
        )
    return matches[0]


def select_compiled_artifact(
    receipts: tuple[Mapping[str, object], ...] | list[Mapping[str, object]],
    *,
    qualified_name: str,
    profile: str,
    target: str,
    source_digest: str,
) -> Mapping[str, object]:
    """Bind a profile to one immutable TileLang 0.1.13 build receipt."""

    _digest(source_digest, "source_digest")
    expected = {
        "qualified_name": qualified_name,
        "profile": profile,
        "target": target,
        "source_sha256": source_digest,
    }
    matches = [
        receipt
        for receipt in receipts
        if all(receipt.get(key) == value for key, value in expected.items())
    ]
    if len(matches) != 1:
        raise LookupError(f"compiled artifact requires exactly one match, observed {len(matches)}")
    receipt = matches[0]
    if receipt.get("compiler") != "tilelang" or receipt.get("compiler_version") != "0.1.13":
        raise RuntimeError("compiled artifact does not use the approved TileLang 0.1.13 toolchain")
    artifact_digest = receipt.get("artifact_sha256")
    if not isinstance(artifact_digest, str):
        raise RuntimeError("compiled artifact receipt lacks its digest")
    _digest(artifact_digest, "artifact_sha256")
    output = receipt.get("output")
    if not isinstance(output, str) or not output:
        raise RuntimeError("compiled artifact receipt lacks a bounded output identity")
    return receipt


def _clone_arguments(torch: Any, arguments: tuple[object, ...]) -> tuple[object, ...]:
    return tuple(
        value.detach().clone() if isinstance(value, torch.Tensor) else value
        for value in arguments
    )


def qualify_cuda_operator(
    config: QualificationConfig,
    sample_factory: Callable[[], tuple[object, ...]],
    reference: Callable[..., Any],
) -> dict[str, object]:
    """Exercise one already-loaded CUDA operator and return unsigned evidence.

    Passing this function does not activate an operation or grant production
    authority. Independent review, immutable artifact verification, and signing
    remain external protected gates.
    """

    import torch

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA qualification requires an available NVIDIA GPU")
    device = torch.cuda.current_device()
    capability = torch.cuda.get_device_capability(device)
    expected = _TARGET_CAPABILITIES[config.target]
    if capability != expected:
        raise RuntimeError(
            f"hardware mismatch: target {config.target} requires {expected}, observed {capability}"
        )
    try:
        operation = getattr(torch.ops.mindclade, config.operator).default
    except AttributeError as exc:
        raise RuntimeError(f"torch.ops.mindclade.{config.operator} is not registered") from exc

    arguments = sample_factory()
    if not isinstance(arguments, tuple):
        raise TypeError("sample_factory must return a tuple")
    tensors = [value for value in arguments if isinstance(value, torch.Tensor)]
    if not tensors or any(not tensor.is_cuda for tensor in tensors):
        raise ValueError("every tensor sample must be CUDA-resident")
    if len({tensor.device for tensor in tensors}) != 1:
        raise ValueError("all tensor samples must use one CUDA device")

    previous_determinism = torch.are_deterministic_algorithms_enabled()
    try:
        torch.use_deterministic_algorithms(config.deterministic)
        opcheck = torch.library.opcheck(
            operation,
            arguments,
            test_utils=(
                "test_schema",
                "test_autograd_registration",
                "test_faketensor",
                "test_aot_dispatch_dynamic",
            ),
            raise_exception=True,
        )
        expected_output = reference(*_clone_arguments(torch, arguments))
        actual_output = operation(*_clone_arguments(torch, arguments))
        torch.testing.assert_close(
            actual_output,
            expected_output,
            atol=config.atol,
            rtol=config.rtol,
        )

        compiled = torch.compile(operation, fullgraph=True, dynamic=False)
        compiled_output = compiled(*_clone_arguments(torch, arguments))
        torch.testing.assert_close(
            compiled_output,
            expected_output,
            atol=config.atol,
            rtol=config.rtol,
        )

        stream = torch.cuda.Stream(device=tensors[0].device)
        stream.wait_stream(torch.cuda.current_stream(device=tensors[0].device))
        with torch.cuda.stream(stream):
            for _ in range(config.warmup):
                operation(*arguments)
            start = torch.cuda.Event(enable_timing=True)
            end = torch.cuda.Event(enable_timing=True)
            start.record(stream)
            for _ in range(config.iterations):
                operation(*arguments)
            end.record(stream)
        end.synchronize()
        latency_us = start.elapsed_time(end) * 1_000.0 / config.iterations

        static_arguments = _clone_arguments(torch, arguments)
        graph = torch.cuda.CUDAGraph()
        capture_stream = torch.cuda.Stream(device=tensors[0].device)
        capture_stream.wait_stream(torch.cuda.current_stream(device=tensors[0].device))
        with torch.cuda.stream(capture_stream):
            operation(*static_arguments)
        torch.cuda.current_stream(device=tensors[0].device).wait_stream(capture_stream)
        with torch.cuda.graph(graph, stream=capture_stream):
            graph_output = operation(*static_arguments)
        graph.replay()
        torch.cuda.synchronize(tensors[0].device)
        torch.testing.assert_close(
            graph_output,
            expected_output,
            atol=config.atol,
            rtol=config.rtol,
        )
    finally:
        torch.use_deterministic_algorithms(previous_determinism)

    properties = torch.cuda.get_device_properties(device)
    return {
        "artifact_digest": config.artifact_digest,
        "evidence_class": "UNSIGNED_CANDIDATE",
        "hardware": {
            "compute_capability": f"{capability[0]}.{capability[1]}",
            "device_name": properties.name,
        },
        "measurement": {
            "iterations": config.iterations,
            "latency_us": latency_us,
            "warmup": config.warmup,
        },
        "numerical": {"atol": config.atol, "rtol": config.rtol},
        "operator": f"mindclade::{config.operator}",
        "opcheck": dict(opcheck),
        "profile": config.profile,
        "schema_version": 1,
        "source_digest": config.source_digest,
        "target": config.target,
        "toolchain": {
            "cuda": torch.version.cuda,
            "torch": torch.__version__,
        },
    }
