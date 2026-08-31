from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import socket
import subprocess
import sys
import time
import unittest
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from jsonschema import Draft202012Validator

from artifact_contract import (
    ArtifactError,
    canonical_json,
    load_object,
    sha256_bytes,
    sha256_file,
    validate_runtime_manifest,
)

PACKAGE_ROOT = Path(__file__).resolve().parent
REPOSITORY_ROOT = PACKAGE_ROOT.parents[2]


@dataclass(frozen=True)
class ProbeContext:
    world_size: int
    local_world_size: int
    node_count: int
    physical_host_id: str
    topology_digest: str
    gpu_sku: str


def fingerprint_digest(inputs: Mapping[str, Any]) -> str:
    return sha256_bytes(canonical_json(inputs).rstrip(b"\n"))


def jit_cache_path(root: Path, fingerprint: str) -> Path:
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", fingerprint):
        raise ValueError("DeepEP fingerprint must be canonical")
    return root / fingerprint.removeprefix("sha256:")


def version_tuple(value: str) -> tuple[int, ...]:
    match = re.match(r"^(\d+(?:\.\d+)*)", value)
    if match is None:
        raise AssertionError(f"version has no numeric prefix: {value}")
    return tuple(int(part) for part in match.group(1).split("."))


def _required_integer(environment: Mapping[str, str], name: str) -> int:
    value = environment.get(name, "")
    if re.fullmatch(r"[1-9][0-9]*", value) is None:
        raise RuntimeError(f"{name} must be a positive integer")
    return int(value)


def _required_rank(environment: Mapping[str, str], name: str) -> int:
    value = environment.get(name, "")
    if re.fullmatch(r"0|[1-9][0-9]*", value) is None:
        raise RuntimeError(f"{name} must be a non-negative integer")
    return int(value)


def _required_string(
    environment: Mapping[str, str], name: str, pattern: str, description: str
) -> str:
    value = environment.get(name, "")
    if re.fullmatch(pattern, value) is None:
        raise RuntimeError(f"{name} must be {description}")
    return value


def _strict_environment_integer(environment: Mapping[str, str], name: str) -> int:
    value = environment.get(name, "0")
    if re.fullmatch(r"[+-]?[0-9]+", value) is None:
        raise RuntimeError(f"{name} must be an integer")
    return int(value, 10)


def validate_probe_environment(scope: str, environment: Mapping[str, str]) -> ProbeContext:
    world_size = _required_integer(environment, "WORLD_SIZE")
    local_world_size = _required_integer(environment, "LOCAL_WORLD_SIZE")
    node_count = _required_integer(environment, "MINDCLADE_DEEPEP_NNODES")
    physical_host_id = _required_string(
        environment,
        "MINDCLADE_PHYSICAL_HOST_ID",
        r"[A-Za-z0-9][A-Za-z0-9._:/-]{7,255}",
        "a trusted physical host or cloud instance identity",
    )
    topology_digest = _required_string(
        environment,
        "MINDCLADE_TOPOLOGY_DIGEST",
        r"sha256:[0-9a-f]{64}",
        "a canonical topology digest",
    )
    gpu_sku = _required_string(
        environment,
        "MINDCLADE_GPU_SKU",
        r"H100|H200",
        "H100 or H200",
    )
    if world_size < 2 or local_world_size < 2:
        raise RuntimeError("DeepEP qualification requires at least two GPU ranks")
    if scope == "intra-node":
        if node_count != 1 or world_size != local_world_size:
            raise RuntimeError("intra-node qualification must run entirely on one node")
    elif scope == "multi-node":
        protected = {
            "MINDCLADE_EXECUTION_TIER": "trusted",
            "MINDCLADE_PIPELINE_CLASS": "gpu",
            "MINDCLADE_SOURCE_TRUST": "protected",
        }
        mismatches = [
            f"{name}={environment.get(name, '')!r}"
            for name, expected in protected.items()
            if environment.get(name) != expected
        ]
        if mismatches:
            raise RuntimeError(
                "multi-node qualification requires protected GPU context: " + ", ".join(mismatches)
            )
        source_revision = environment.get("MINDCLADE_SOURCE_REVISION", "")
        definition_revision = environment.get("MINDCLADE_PIPELINE_DEFINITION_REVISION", "")
        if not re.fullmatch(r"[0-9a-f]{40}", source_revision):
            raise RuntimeError("multi-node qualification requires a canonical source revision")
        if source_revision != definition_revision:
            raise RuntimeError("multi-node qualification requires a revision-identical definition")
        context_digest = environment.get("MINDCLADE_CONTEXT_DIGEST", "")
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", context_digest):
            raise RuntimeError("multi-node qualification requires a canonical context digest")
        if node_count < 2 or world_size <= local_world_size:
            raise RuntimeError("multi-node qualification requires ranks on at least two nodes")
        _required_string(
            environment,
            "MINDCLADE_RDMA_DEVICE_IDS",
            r"[A-Za-z0-9._:/-]+(?:,[A-Za-z0-9._:/-]+)*",
            "a canonical comma-separated RDMA device identity list",
        )
        _required_string(
            environment,
            "MINDCLADE_IBGDA_MODE",
            r"driver-regkeys|gdrcopy",
            "driver-regkeys or gdrcopy",
        )
    else:
        raise RuntimeError(f"unsupported DeepEP qualification scope: {scope}")
    return ProbeContext(
        world_size=world_size,
        local_world_size=local_world_size,
        node_count=node_count,
        physical_host_id=physical_host_id,
        topology_digest=topology_digest,
        gpu_sku=gpu_sku,
    )


def _nvshmem_digest() -> str:
    result = subprocess.run(
        ["nvshmem-info", "-a"],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "no diagnostic output"
        raise RuntimeError(f"nvshmem-info -a failed: {detail}")
    return "sha256:" + hashlib.sha256(result.stdout.encode("utf-8")).hexdigest()


def _deep_ep_source_record() -> dict[str, Any]:
    source_lock = load_object(
        REPOSITORY_ROOT / "third_party/source_mirrors/sources.lock.json", "source lock"
    )
    entries = source_lock.get("entries")
    if not isinstance(entries, list):
        raise RuntimeError("source lock entries are malformed")
    records = [entry for entry in entries if isinstance(entry, dict) and entry.get("name") == "deep-ep"]
    if len(records) != 1:
        raise RuntimeError("source lock must contain exactly one DeepEP record")
    return cast(dict[str, Any], records[0])


def _load_locked_runtime_manifest(environment: Mapping[str, str]) -> tuple[dict[str, Any], str]:
    raw_path = environment.get("MINDCLADE_DEEPEP_RUNTIME_MANIFEST", "")
    if not raw_path:
        raise RuntimeError("qualification requires MINDCLADE_DEEPEP_RUNTIME_MANIFEST")
    manifest_path = Path(raw_path).resolve()
    if re.fullmatch(r"/nix/store/[a-z0-9]{32}-.+", str(manifest_path)) is None:
        raise RuntimeError("DeepEP runtime manifest must be an immutable Nix store path")
    try:
        manifest = load_object(manifest_path, "Nix runtime manifest")
        fingerprint = validate_runtime_manifest(manifest)
    except ArtifactError as error:
        raise RuntimeError(str(error)) from error
    if manifest.get("distribution") != {"mode": "hermetic-nix", "requirements": []}:
        raise RuntimeError("GPU qualification requires the hermetic Nix distribution")
    declared_fingerprint = environment.get("MINDCLADE_DEEPEP_JIT_FINGERPRINT", "")
    if declared_fingerprint != fingerprint:
        raise RuntimeError("Nix runtime fingerprint environment does not match its manifest")
    locks = manifest.get("locks")
    if not isinstance(locks, Mapping):
        raise RuntimeError("runtime manifest lock projection is malformed")
    lock_paths = {
        "flake": REPOSITORY_ROOT / "flake.lock",
        "package_definition": PACKAGE_ROOT / "package.nix",
        "patches": REPOSITORY_ROOT / "third_party/patches/patches.lock.json",
        "python": REPOSITORY_ROOT / "uv.lock",
        "sources": REPOSITORY_ROOT / "third_party/source_mirrors/sources.lock.json",
    }
    for name, path in lock_paths.items():
        if locks.get(name) != sha256_file(path):
            raise RuntimeError(f"runtime manifest {name} lock does not match the source tree")
    record = _deep_ep_source_record()
    artifact = manifest.get("artifact")
    if not isinstance(artifact, Mapping):
        raise RuntimeError("runtime manifest artifact identity is malformed")
    if artifact.get("upstream_commit") != record["upstream"]["revision"]:
        raise RuntimeError("runtime manifest upstream commit does not match the source lock")
    if artifact.get("version") != record["build_authority"]["version"]:
        raise RuntimeError("runtime manifest version does not match the source lock")
    return manifest, fingerprint


def _verify_nvcc(manifest: Mapping[str, Any], environment: Mapping[str, str]) -> str:
    toolchain = manifest["toolchain"]
    assert isinstance(toolchain, Mapping)
    expected_nvcc = str(toolchain["nvcc"])
    expected_cuda_home = str(toolchain["cuda_home"])
    if environment.get("EP_JIT_NVCC_COMPILER") != expected_nvcc:
        raise RuntimeError("EP_JIT_NVCC_COMPILER is outside the locked toolchain")
    if environment.get("CUDA_HOME") != expected_cuda_home:
        raise RuntimeError("CUDA_HOME is outside the locked toolchain")
    if Path(expected_nvcc).resolve().is_file() is False:
        raise RuntimeError("locked NVCC compiler is missing")
    result = subprocess.run(
        [expected_nvcc, "--version"], check=False, capture_output=True, text=True, timeout=30
    )
    if result.returncode != 0:
        raise RuntimeError("locked NVCC compiler cannot report its version")
    match = re.search(r"V([0-9]+(?:\.[0-9]+){2})", result.stdout + result.stderr)
    expected_version = str(manifest["runtime_profile"]["nvcc"]).split("-")[0]
    if match is None or match.group(1) != expected_version:
        raise RuntimeError("locked NVCC binary version does not match the runtime manifest")
    return match.group(1)


def run_gpu_probe(scope: str, evidence_path: Path) -> None:
    if platform.system() != "Linux":
        raise RuntimeError("DeepEP GPU qualification requires Linux")
    if _strict_environment_integer(os.environ, "EP_SUPPRESS_NCCL_CHECK") != 0:
        raise RuntimeError("qualification forbids every nonzero EP_SUPPRESS_NCCL_CHECK value")
    if _strict_environment_integer(os.environ, "EP_DISABLE_GIN") != 0:
        raise RuntimeError("qualification requires the DeepEP v2 NCCL Gin backend")

    runtime_manifest, jit_fingerprint = _load_locked_runtime_manifest(os.environ)
    jit_cache = Path(os.environ.get("EP_JIT_CACHE_DIR", "")).resolve()
    if jit_cache != jit_cache_path(jit_cache.parents[0], jit_fingerprint).resolve():
        raise RuntimeError("EP_JIT_CACHE_DIR does not match the DeepEP JIT fingerprint")
    source_revision = _required_string(
        os.environ,
        "MINDCLADE_SOURCE_REVISION",
        r"[0-9a-f]{40}",
        "a canonical source revision",
    )

    evidence_root = (REPOSITORY_ROOT / "build/evidence").resolve()
    resolved_evidence = evidence_path.resolve()
    if not resolved_evidence.is_relative_to(evidence_root):
        raise RuntimeError(f"evidence output must be under {evidence_root}")

    probe_context = validate_probe_environment(scope, os.environ)
    rank = _required_rank(os.environ, "RANK")
    local_rank = _required_rank(os.environ, "LOCAL_RANK")
    if rank >= probe_context.world_size or local_rank >= probe_context.local_world_size:
        raise RuntimeError("RANK or LOCAL_RANK is outside the declared world")

    import torch
    import torch.distributed as dist
    import deep_ep
    from deep_ep import ElasticBuffer
    from deep_ep import __version__ as deep_ep_version
    from deep_ep.utils.math import per_token_cast_back, per_token_cast_to_fp8

    artifact = runtime_manifest["artifact"]
    runtime_profile = runtime_manifest["runtime_profile"]
    package_root = Path(os.environ.get("MINDCLADE_DEEPEP_PACKAGE_ROOT", "")).resolve()
    module_path = Path(deep_ep.__file__).resolve()
    if package_root == Path("/") or not module_path.is_relative_to(package_root):
        raise RuntimeError("imported DeepEP module is outside the locked Nix package")
    embedded_manifest_path = module_path.parent / "mindclade-runtime.json"
    if load_object(embedded_manifest_path, "embedded runtime manifest") != runtime_manifest:
        raise RuntimeError("imported DeepEP runtime manifest differs from the Nix authority")
    if deep_ep_version != artifact["version"]:
        raise RuntimeError("imported DeepEP version differs from the locked artifact")
    if importlib.metadata.version("deep-ep") != artifact["version"]:
        raise RuntimeError("installed DeepEP metadata differs from the locked artifact")
    if torch.__version__.split("+")[0] != runtime_profile["torch"]:
        raise RuntimeError("imported Torch version differs from the locked runtime")
    if torch.version.cuda != runtime_profile["cuda"]:
        raise RuntimeError("Torch CUDA version differs from the locked runtime")
    loaded_nccl = tuple(torch.cuda.nccl.version())
    if loaded_nccl != version_tuple(runtime_profile["nccl"]):
        raise RuntimeError("loaded NCCL version differs from the locked runtime")
    nvcc_version = _verify_nvcc(runtime_manifest, os.environ)

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is unavailable")
    if torch.cuda.device_count() < probe_context.local_world_size:
        raise RuntimeError("LOCAL_WORLD_SIZE exceeds visible CUDA devices")

    torch.cuda.set_device(local_rank)
    device = torch.device("cuda", local_rank)
    capability = torch.cuda.get_device_capability(device)
    if capability < (9, 0):
        raise RuntimeError(f"DeepEP v2 qualification requires SM90 or newer, found {capability}")

    dist.init_process_group("nccl", device_id=device)
    started = time.perf_counter()
    try:
        tokens = 8
        hidden = 128
        num_topk = 1
        num_experts = probe_context.world_size
        destination_expert = (rank + 1) % probe_context.world_size
        x = (
            torch.arange(tokens * hidden, dtype=torch.float32, device=device)
            .reshape(tokens, hidden)
            .add(rank * tokens * hidden)
            .to(torch.bfloat16)
        )
        topk_idx = torch.full(
            (tokens, num_topk), destination_expert, dtype=torch.int64, device=device
        )
        topk_weights = torch.ones((tokens, num_topk), dtype=torch.float32, device=device)
        buffer = ElasticBuffer(
            dist.group.WORLD,
            num_max_tokens_per_rank=tokens,
            hidden=hidden,
            num_topk=num_topk,
            use_fp8_dispatch=False,
            explicitly_destroy=True,
        )
        if not buffer.runtime.is_gin_enabled():
            raise RuntimeError("DeepEP ElasticBuffer did not obtain NCCL Gin resources")
        num_sms = buffer.get_theoretical_num_sms(num_experts, num_topk)
        recv_x, _, _, handle, dispatch_event = buffer.dispatch(
            x,
            topk_idx=topk_idx,
            topk_weights=topk_weights,
            num_experts=num_experts,
            num_max_tokens_per_rank=tokens,
            num_sms=num_sms,
            async_with_compute_stream=True,
        )
        dispatch_event.current_stream_wait()
        cached_recv_x, _, _, _, cached_event = buffer.dispatch(
            x,
            handle=handle,
            num_sms=num_sms,
            async_with_compute_stream=True,
        )
        cached_event.current_stream_wait()
        torch.testing.assert_close(cached_recv_x, recv_x, rtol=0, atol=0)
        combined_x, _, combine_event = buffer.combine(
            recv_x,
            handle=handle,
            num_sms=num_sms,
            async_with_compute_stream=True,
        )
        combine_event.current_stream_wait()
        torch.cuda.synchronize(device)
        torch.testing.assert_close(combined_x, x, rtol=0, atol=0)
        buffer.destroy()

        fp8_buffer = ElasticBuffer(
            dist.group.WORLD,
            num_max_tokens_per_rank=tokens,
            hidden=hidden,
            num_topk=num_topk,
            use_fp8_dispatch=True,
            explicitly_destroy=True,
        )
        if not fp8_buffer.runtime.is_gin_enabled():
            raise RuntimeError("DeepEP FP8 ElasticBuffer did not obtain NCCL Gin resources")
        fp8_x = per_token_cast_to_fp8(x)
        recv_fp8, _, _, fp8_handle, fp8_event = fp8_buffer.dispatch(
            fp8_x,
            topk_idx=topk_idx,
            topk_weights=topk_weights,
            num_experts=num_experts,
            num_max_tokens_per_rank=tokens,
            num_sms=num_sms,
            async_with_compute_stream=True,
        )
        fp8_event.current_stream_wait()
        source_rank = (rank - 1) % probe_context.world_size
        expected_x = (
            torch.arange(tokens * hidden, dtype=torch.float32, device=device)
            .reshape(tokens, hidden)
            .add(source_rank * tokens * hidden)
            .to(torch.bfloat16)
        )
        expected_fp8 = per_token_cast_to_fp8(expected_x)
        if not torch.equal(recv_fp8[0][:tokens], expected_fp8[0]):
            raise AssertionError("FP8 dispatch payload differs from the next-rank reference")
        if not torch.equal(recv_fp8[1][:tokens], expected_fp8[1]):
            raise AssertionError("FP8 dispatch scale differs from the next-rank reference")
        cached_fp8, _, _, _, cached_fp8_event = fp8_buffer.dispatch(
            fp8_x,
            handle=fp8_handle,
            num_sms=num_sms,
            async_with_compute_stream=True,
        )
        cached_fp8_event.current_stream_wait()
        torch.testing.assert_close(
            per_token_cast_back(cached_fp8[0][:tokens], cached_fp8[1][:tokens]),
            per_token_cast_back(recv_fp8[0][:tokens], recv_fp8[1][:tokens]),
            rtol=0,
            atol=0,
        )
        fp8_buffer.destroy()
        torch.cuda.synchronize(device)

        elapsed = time.perf_counter() - started
        local_runtime: dict[str, Any] = {
            "capability": list(capability),
            "device": torch.cuda.get_device_name(device),
            "elapsed_seconds": elapsed,
            "host": socket.gethostname(),
            "physical_host_id": probe_context.physical_host_id,
            "topology_digest": probe_context.topology_digest,
            "gpu_sku": probe_context.gpu_sku,
            "local_rank": local_rank,
            "rank": rank,
        }
        if probe_context.gpu_sku not in local_runtime["device"]:
            raise RuntimeError("declared GPU SKU does not match the visible device")
        runtimes: list[dict[str, Any] | None] = [None] * probe_context.world_size
        dist.all_gather_object(runtimes, local_runtime)
        if any(runtime is None for runtime in runtimes):
            raise RuntimeError("runtime evidence is missing from one or more ranks")
        materialized_runtimes = [runtime for runtime in runtimes if runtime is not None]
        physical_hosts = sorted(
            {str(runtime["physical_host_id"]) for runtime in materialized_runtimes}
        )
        if len(physical_hosts) != probe_context.node_count:
            raise RuntimeError("trusted physical host identities do not prove node separation")
        if {runtime["topology_digest"] for runtime in materialized_runtimes} != {
            probe_context.topology_digest
        }:
            raise RuntimeError("ranks do not share one qualified topology manifest")

        nvshmem_digest = _nvshmem_digest()
        nvshmem_digests: list[str | None] = [None] * probe_context.world_size
        dist.all_gather_object(nvshmem_digests, nvshmem_digest)
        if any(digest is None for digest in nvshmem_digests):
            raise RuntimeError("NVSHMEM verification result is missing from one or more ranks")
        if local_rank == 0:
            evidence = {
                "claim": "unsigned-source-probe",
                "conclusion": "PASS",
                "node_count": probe_context.node_count,
                "physical_hosts": physical_hosts,
                "production_authority": False,
                "runtime": {
                    "cuda": torch.version.cuda,
                    "deep_ep": deep_ep_version,
                    "nccl": list(torch.cuda.nccl.version()),
                    "nvcc": nvcc_version,
                    "nvshmem_info_sha256": sorted(
                        {digest for digest in nvshmem_digests if digest is not None}
                    ),
                    "torch": torch.__version__,
                },
                "runtime_fingerprint": jit_fingerprint,
                "runtime_manifest_digest": sha256_file(
                    Path(os.environ["MINDCLADE_DEEPEP_RUNTIME_MANIFEST"])
                ),
                "ranks": materialized_runtimes,
                "schema_version": "mindclade.deepep-gpu-probe/v2",
                "scope": scope,
                "source_revision": source_revision,
                "tests": [{
                    "dtype": "bfloat16+fp8",
                    "hidden": hidden,
                    "num_experts": num_experts,
                    "num_topk": num_topk,
                    "route": "next-rank",
                    "tokens_per_rank": tokens,
                    "cached_handle": True,
                    "asynchronous_events": True,
                    "deterministic": True,
                }],
                "topology_digest": probe_context.topology_digest,
                "world_size": probe_context.world_size,
            }
            if scope == "multi-node":
                evidence["network"] = {
                    "ibgda_mode": os.environ["MINDCLADE_IBGDA_MODE"],
                    "rdma_device_ids": os.environ["MINDCLADE_RDMA_DEVICE_IDS"].split(","),
                    "transport": "nccl-gin",
                }
            evidence_schema = load_object(PACKAGE_ROOT / "gpu-evidence.schema.json", "schema")
            Draft202012Validator(evidence_schema).validate(evidence)
            resolved_evidence.parent.mkdir(parents=True, exist_ok=True)
            resolved_evidence.write_text(
                json.dumps(evidence, sort_keys=True, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )
        dist.barrier()
    finally:
        dist.destroy_process_group()


class DeepEpPackagePolicyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.package = (PACKAGE_ROOT / "package.nix").read_text(encoding="utf-8")
        cls.readme = (PACKAGE_ROOT / "README.md").read_text(encoding="utf-8")
        lock = json.loads(
            (REPOSITORY_ROOT / "third_party/source_mirrors/sources.lock.json").read_text(
                encoding="utf-8"
            )
        )
        records = [entry for entry in lock["entries"] if entry["name"] == "deep-ep"]
        if len(records) != 1:
            raise AssertionError(f"expected one DeepEP record, found {len(records)}")
        cls.record = records[0]

    def test_modern_source_and_submodule_are_immutable(self) -> None:
        self.assertEqual(
            self.record["review_reference"],
            "docs/adr/0013-deepep-package-and-qualification-boundary.md",
        )
        self.assertEqual(self.record["status"], "intake-only")
        self.assertEqual(self.record["upstream"]["version_line"], "2.x")
        self.assertRegex(self.record["upstream"]["revision"], r"^[0-9a-f]{40}$")
        self.assertRegex(
            self.record["build_authority"]["source_nar_hash"],
            r"^sha256-[A-Za-z0-9+/]{43}=$",
        )
        self.assertFalse(self.record["archive"]["submodules_included"])
        self.assertEqual(len(self.record["submodules"]), 1)
        self.assertEqual(self.record["submodules"][0]["path"], "third-party/fmt")
        self.assertRegex(self.record["submodules"][0]["revision"], r"^[0-9a-f]{40}$")
        self.assertEqual(
            self.record["build_authority"]["version"],
            "2.1.0+" + self.record["upstream"]["revision"][:7],
        )
        self.assertIn("fetchSubmodules = true;", self.package)

    def test_runtime_profile_meets_modern_upstream_minimums(self) -> None:
        profile = self.record["build_authority"]["runtime_profile"]
        self.assertGreaterEqual(version_tuple(profile["nvshmem"]), (3, 3, 9))
        self.assertGreaterEqual(
            version_tuple(profile["nccl"]),
            version_tuple(self.record["vllm_compatibility"]["minimum_nccl"]),
        )
        self.assertGreaterEqual(version_tuple(profile["torch"]), (2, 10))
        self.assertGreaterEqual(version_tuple(profile["cuda"]), (12, 3))
        self.assertGreaterEqual(version_tuple(profile["nvcc"]), (12, 3))

    def test_jit_fingerprint_is_canonical_and_versioned(self) -> None:
        inputs = {
            "schema_version": "mindclade.deepep-runtime-fingerprint/v2",
            "source": self.record["upstream"]["revision"],
            "toolchain_outputs": ["/nix/store/" + "a" * 32 + "-nvcc"],
        }
        fingerprint = fingerprint_digest(inputs)
        self.assertRegex(fingerprint, r"^sha256:[0-9a-f]{64}$")
        self.assertEqual(
            jit_cache_path(Path("/cache"), fingerprint).name,
            fingerprint.removeprefix("sha256:"),
        )
        self.assertNotEqual(fingerprint, fingerprint_digest(inputs | {"source": "b" * 40}))

    def test_runtime_manifest_recomputes_its_locked_identity(self) -> None:
        store = "/nix/store/" + "a" * 32 + "-deepep-toolchain"
        inputs = {"schema_version": "mindclade.deepep-runtime-fingerprint/v2"}
        manifest = {
            "schema_version": "mindclade.deepep-runtime-manifest/v2",
            "production_authority": False,
            "distribution": {"mode": "hermetic-nix", "requirements": []},
            "fingerprint": {"algorithm": "sha256", "value": fingerprint_digest(inputs)},
            "fingerprint_inputs": inputs,
            "toolchain": {
                "cuda_home": store,
                "nccl_root": store,
                "nvcc": store + "/bin/nvcc",
                "nvshmem_root": store,
            },
        }
        self.assertEqual(validate_runtime_manifest(manifest), fingerprint_digest(inputs))
        manifest["fingerprint"]["value"] = "sha256:" + "0" * 64
        with self.assertRaisesRegex(ArtifactError, "canonical inputs"):
            validate_runtime_manifest(manifest)

    def test_package_uses_nix_closure_without_nvshmem_source_patch(self) -> None:
        self.assertIn("pythonPackages.buildPythonPackage.override", self.package)
        self.assertNotIn("pythonPackages.deep-ep", self.package)
        self.assertNotIn("overrideAttrs", self.package)
        self.assertIn("cudaPackages.libnvshmem", self.package)
        self.assertIn("EP_NCCL_ROOT_DIR", self.package)
        self.assertIn("NVSHMEM_DIR", self.package)
        self.assertNotIn("fetchpatch", self.package)
        self.assertNotIn("eep_nvshmem.patch", self.package)
        self.assertNotIn("nvshmem.patch", self.package)
        self.assertIn("propagatedBuildInputs", self.package)
        self.assertIn("EP_JIT_NVCC_COMPILER", self.package)
        self.assertIn("standaloneImportTest", self.package)
        self.assertIn("artifactBundle", self.package)
        patch_lock = json.loads(
            (REPOSITORY_ROOT / "third_party/patches/patches.lock.json").read_text(encoding="utf-8")
        )
        entries = [
            entry for entry in patch_lock["entries"] if entry["applies_to"]["name"] == "deep-ep"
        ]
        self.assertEqual(len(entries), 4)
        for entry in entries:
            patch_path = REPOSITORY_ROOT / entry["path"]
            self.assertTrue(patch_path.is_file())
            self.assertEqual(entry["sha256"], sha256_file(patch_path))
            self.assertNotIn("nvshmem", entry["name"].lower())

    def test_wheel_is_fail_closed_to_the_matching_nix_closure(self) -> None:
        self.assertEqual(
            self.record["wheel"],
            {
                "distribution": "nix-closure-bound",
                "external_install_supported": False,
                "platform": "linux_x86_64",
                "python_abi": "cp312",
            },
        )
        self.assertIn('mkRuntimeManifest "nix-closure" [ ]', self.package)
        self.assertNotIn("portable-nvidia-wheels", self.package)

    def test_artifact_contracts_are_explicitly_non_production(self) -> None:
        runtime_schema = load_object(PACKAGE_ROOT / "runtime-manifest.schema.json", "schema")
        evidence_schema = load_object(PACKAGE_ROOT / "gpu-evidence.schema.json", "schema")
        Draft202012Validator.check_schema(runtime_schema)
        Draft202012Validator.check_schema(evidence_schema)
        self.assertEqual(
            runtime_schema["properties"]["production_authority"], {"const": False}
        )
        self.assertEqual(
            evidence_schema["properties"]["production_authority"], {"const": False}
        )

    def test_documentation_preserves_the_privileged_host_boundary(self) -> None:
        for text in (
            "nvshmem-info -a",
            "EP_JIT_NVCC_COMPILER",
            "/etc/modprobe.d/nvidia.conf",
            "gdrdrv",
            "never edits",
            "no production, GPU, RDMA, or network qualification",
        ):
            self.assertIn(text, self.readme)

    def test_gpu_probe_is_fail_closed_by_scope(self) -> None:
        common = {
            "MINDCLADE_GPU_SKU": "H100",
            "MINDCLADE_PHYSICAL_HOST_ID": "instance-001",
            "MINDCLADE_TOPOLOGY_DIGEST": "sha256:" + "d" * 64,
        }
        intra = common | {
            "LOCAL_WORLD_SIZE": "2",
            "MINDCLADE_DEEPEP_NNODES": "1",
            "WORLD_SIZE": "2",
        }
        self.assertEqual(
            validate_probe_environment("intra-node", intra),
            ProbeContext(2, 2, 1, "instance-001", "sha256:" + "d" * 64, "H100"),
        )
        with self.assertRaisesRegex(RuntimeError, "protected GPU context"):
            validate_probe_environment(
                "multi-node",
                common
                | {
                    "LOCAL_WORLD_SIZE": "2",
                    "MINDCLADE_DEEPEP_NNODES": "2",
                    "WORLD_SIZE": "4",
                },
            )
        multi = common | {
            "MINDCLADE_CONTEXT_DIGEST": "sha256:" + "c" * 64,
            "MINDCLADE_EXECUTION_TIER": "trusted",
            "MINDCLADE_IBGDA_MODE": "driver-regkeys",
            "LOCAL_WORLD_SIZE": "2",
            "MINDCLADE_DEEPEP_NNODES": "2",
            "MINDCLADE_PIPELINE_CLASS": "gpu",
            "MINDCLADE_PIPELINE_DEFINITION_REVISION": "a" * 40,
            "MINDCLADE_RDMA_DEVICE_IDS": "mlx5_0,mlx5_1",
            "MINDCLADE_SOURCE_REVISION": "a" * 40,
            "MINDCLADE_SOURCE_TRUST": "protected",
            "WORLD_SIZE": "4",
        }
        self.assertEqual(
            validate_probe_environment("multi-node", multi),
            ProbeContext(4, 2, 2, "instance-001", "sha256:" + "d" * 64, "H100"),
        )
        with self.assertRaisesRegex(RuntimeError, "positive integer"):
            validate_probe_environment("intra-node", intra | {"WORLD_SIZE": "01"})

    def test_every_nonzero_gin_disable_value_is_rejected(self) -> None:
        for value in ("1", "01", "-1", "+2"):
            self.assertNotEqual(
                _strict_environment_integer({"EP_DISABLE_GIN": value}, "EP_DISABLE_GIN"),
                0,
            )
        with self.assertRaisesRegex(RuntimeError, "must be an integer"):
            _strict_environment_integer({"EP_DISABLE_GIN": "true"}, "EP_DISABLE_GIN")


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments or arguments[0] != "gpu-smoke":
        unittest.main(argv=[sys.argv[0], *arguments])
        return 0
    parser = argparse.ArgumentParser(description="Run fail-closed DeepEP GPU communication probe")
    parser.add_argument("gpu-smoke", nargs="?")
    parser.add_argument("--scope", choices=("intra-node", "multi-node"), required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    options = parser.parse_args(arguments)
    run_gpu_probe(options.scope, options.evidence)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
