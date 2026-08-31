from __future__ import annotations

import argparse
import hashlib
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
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

PACKAGE_ROOT = Path(__file__).resolve().parent
REPOSITORY_ROOT = PACKAGE_ROOT.parents[2]


@dataclass(frozen=True)
class DeepEPFingerprint:
    upstream_commit: str
    patch_digest: str
    torch_version: str
    cuda_version: str
    nccl_version: str
    compiler_version: str
    gpu_architecture: str
    build_variant: str

    def digest(self) -> str:
        payload = json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def jit_cache_path(root: Path, fingerprint: DeepEPFingerprint) -> Path:
    return root / fingerprint.digest()


def version_tuple(value: str) -> tuple[int, ...]:
    match = re.match(r"^(\d+(?:\.\d+)*)", value)
    if match is None:
        raise AssertionError(f"version has no numeric prefix: {value}")
    return tuple(int(part) for part in match.group(1).split("."))


def _required_integer(environment: Mapping[str, str], name: str) -> int:
    value = environment.get(name, "")
    if not value.isdecimal() or int(value) < 1:
        raise RuntimeError(f"{name} must be a positive integer")
    return int(value)


def _required_rank(environment: Mapping[str, str], name: str) -> int:
    value = environment.get(name, "")
    if not value.isdecimal():
        raise RuntimeError(f"{name} must be a non-negative integer")
    return int(value)


def validate_probe_environment(scope: str, environment: Mapping[str, str]) -> tuple[int, int, int]:
    world_size = _required_integer(environment, "WORLD_SIZE")
    local_world_size = _required_integer(environment, "LOCAL_WORLD_SIZE")
    node_count = _required_integer(environment, "MINDCLADE_DEEPEP_NNODES")
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
    else:
        raise RuntimeError(f"unsupported DeepEP qualification scope: {scope}")
    return world_size, local_world_size, node_count


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


def run_gpu_probe(scope: str, evidence_path: Path) -> None:
    if platform.system() != "Linux":
        raise RuntimeError("DeepEP GPU qualification requires Linux")
    if os.environ.get("EP_SUPPRESS_NCCL_CHECK") == "1":
        raise RuntimeError("qualification forbids EP_SUPPRESS_NCCL_CHECK=1")
    if os.environ.get("EP_DISABLE_GIN") == "1":
        raise RuntimeError("qualification requires the DeepEP v2 NCCL Gin backend")

    jit_fingerprint = os.environ.get("MINDCLADE_DEEPEP_JIT_FINGERPRINT", "")
    if not re.fullmatch(r"[0-9a-f]{64}", jit_fingerprint):
        raise RuntimeError("qualification requires the Nix-owned DeepEP JIT fingerprint")
    jit_cache = Path(os.environ.get("EP_JIT_CACHE_DIR", "")).resolve()
    if jit_cache.name != jit_fingerprint:
        raise RuntimeError("EP_JIT_CACHE_DIR does not match the DeepEP JIT fingerprint")

    evidence_root = (REPOSITORY_ROOT / "build/evidence").resolve()
    resolved_evidence = evidence_path.resolve()
    if not resolved_evidence.is_relative_to(evidence_root):
        raise RuntimeError(f"evidence output must be under {evidence_root}")

    world_size, local_world_size, node_count = validate_probe_environment(scope, os.environ)
    rank = _required_rank(os.environ, "RANK")
    local_rank = _required_rank(os.environ, "LOCAL_RANK")
    if rank >= world_size or local_rank >= local_world_size:
        raise RuntimeError("RANK or LOCAL_RANK is outside the declared world")

    import torch
    import torch.distributed as dist
    from deep_ep import ElasticBuffer
    from deep_ep import __version__ as deep_ep_version

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is unavailable")
    if torch.cuda.device_count() < local_world_size:
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
        num_experts = world_size
        destination_expert = (rank + 1) % world_size
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
        )
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
        combined_x, _, combine_event = buffer.combine(
            recv_x,
            handle=handle,
            num_sms=num_sms,
            async_with_compute_stream=True,
        )
        combine_event.current_stream_wait()
        torch.cuda.synchronize(device)
        torch.testing.assert_close(combined_x, x, rtol=0, atol=0)

        elapsed = time.perf_counter() - started
        local_runtime: dict[str, Any] = {
            "capability": list(capability),
            "device": torch.cuda.get_device_name(device),
            "elapsed_seconds": elapsed,
            "host": socket.gethostname(),
            "local_rank": local_rank,
            "rank": rank,
        }
        runtimes: list[dict[str, Any] | None] = [None] * world_size
        dist.all_gather_object(runtimes, local_runtime)
        if any(runtime is None for runtime in runtimes):
            raise RuntimeError("runtime evidence is missing from one or more ranks")
        materialized_runtimes = [runtime for runtime in runtimes if runtime is not None]
        if len({runtime["host"] for runtime in materialized_runtimes}) != node_count:
            raise RuntimeError("observed host count does not match MINDCLADE_DEEPEP_NNODES")

        nvshmem_digest = _nvshmem_digest()
        nvshmem_digests: list[str | None] = [None] * world_size
        dist.all_gather_object(nvshmem_digests, nvshmem_digest)
        if any(digest is None for digest in nvshmem_digests):
            raise RuntimeError("NVSHMEM verification result is missing from one or more ranks")
        if local_rank == 0:
            evidence = {
                "claim": "unsigned-source-probe",
                "conclusion": "PASS",
                "jit_fingerprint": jit_fingerprint,
                "node_count": node_count,
                "production_authority": False,
                "runtime": {
                    "cuda": torch.version.cuda,
                    "deep_ep": deep_ep_version,
                    "nccl": list(torch.cuda.nccl.version()),
                    "nvshmem_info_sha256": sorted(
                        {digest for digest in nvshmem_digests if digest is not None}
                    ),
                    "torch": torch.__version__,
                },
                "ranks": materialized_runtimes,
                "schema_version": "mindclade.deepep-gpu-probe/v1",
                "scope": scope,
                "source_revision": os.environ.get("MINDCLADE_SOURCE_REVISION"),
                "test": {
                    "dtype": "bfloat16",
                    "hidden": hidden,
                    "num_experts": num_experts,
                    "num_topk": num_topk,
                    "route": "next-rank",
                    "tokens_per_rank": tokens,
                },
                "world_size": world_size,
            }
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
        profile = self.record["build_authority"]["runtime_profile"]
        fingerprint = DeepEPFingerprint(
            upstream_commit=self.record["upstream"]["revision"],
            patch_digest="sha256:" + "0" * 64,
            torch_version=profile["torch"],
            cuda_version=profile["cuda"],
            nccl_version=profile["nccl"],
            compiler_version=profile["nvcc"],
            gpu_architecture=",".join(self.record["build_authority"]["cuda_capabilities"]),
            build_variant="v2",
        )
        self.assertRegex(fingerprint.digest(), r"^[0-9a-f]{64}$")
        self.assertEqual(jit_cache_path(Path("/cache"), fingerprint).name, fingerprint.digest())

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
        patch_lock = json.loads(
            (REPOSITORY_ROOT / "third_party/patches/patches.lock.json").read_text(encoding="utf-8")
        )
        self.assertEqual(patch_lock["entries"], [])

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
        intra = {
            "LOCAL_WORLD_SIZE": "2",
            "MINDCLADE_DEEPEP_NNODES": "1",
            "WORLD_SIZE": "2",
        }
        self.assertEqual(validate_probe_environment("intra-node", intra), (2, 2, 1))
        with self.assertRaisesRegex(RuntimeError, "protected GPU context"):
            validate_probe_environment(
                "multi-node",
                {
                    "LOCAL_WORLD_SIZE": "2",
                    "MINDCLADE_DEEPEP_NNODES": "2",
                    "WORLD_SIZE": "4",
                },
            )
        multi = {
            "MINDCLADE_CONTEXT_DIGEST": "sha256:" + "c" * 64,
            "MINDCLADE_EXECUTION_TIER": "trusted",
            "LOCAL_WORLD_SIZE": "2",
            "MINDCLADE_DEEPEP_NNODES": "2",
            "MINDCLADE_PIPELINE_CLASS": "gpu",
            "MINDCLADE_PIPELINE_DEFINITION_REVISION": "a" * 40,
            "MINDCLADE_SOURCE_REVISION": "a" * 40,
            "MINDCLADE_SOURCE_TRUST": "protected",
            "WORLD_SIZE": "4",
        }
        self.assertEqual(validate_probe_environment("multi-node", multi), (4, 2, 2))


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
