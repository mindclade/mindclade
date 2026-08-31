from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent
REPOSITORY_ROOT = PACKAGE_ROOT.parents[2]


def version_tuple(value: str) -> tuple[int, ...]:
    match = re.match(r"^(\d+(?:\.\d+)*)", value)
    if match is None:
        raise AssertionError(f"version has no numeric prefix: {value}")
    return tuple(int(part) for part in match.group(1).split("."))


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

    def test_package_uses_nix_closure_without_nvshmem_source_patch(self) -> None:
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


if __name__ == "__main__":
    unittest.main()
