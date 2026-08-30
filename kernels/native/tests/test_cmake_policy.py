# Copyright (c) 2026 Mindclade. All rights reserved.
# Proprietary and confidential. Unauthorized use, copying, or distribution is prohibited.

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CMAKE_FILES = (
    ROOT / "CMakeLists.txt",
    ROOT / "cmake" / "MindcladeTorchStable.cmake",
    ROOT / "cuda" / "CMakeLists.txt",
    ROOT / "stable_abi" / "CMakeLists.txt",
)


class CMakePolicyTest(unittest.TestCase):
    def test_configure_does_not_mutate_source(self) -> None:
        forbidden = (
            "execute_process(",
            "configure_file(",
            "file(WRITE",
            "file(APPEND",
        )
        for path in CMAKE_FILES:
            text = path.read_text(encoding="utf-8")
            for token in forbidden:
                self.assertNotIn(token, text, path)

    def test_schema_target_is_a_real_installable_shared_library(self) -> None:
        stable = (ROOT / "stable_abi" / "CMakeLists.txt").read_text(
            encoding="utf-8"
        )
        self.assertIn("add_library(", stable)
        self.assertIn("mindclade_native_schema", stable)
        self.assertIn("SHARED", stable)
        self.assertIn("mindclade_apply_native_target_policy", stable)
        self.assertIn("install(", stable)
        self.assertIn("EXPORT MindcladeNativeTargets", stable)

    def test_strict_target_policy_and_abi_are_explicit(self) -> None:
        policy = (ROOT / "cmake" / "MindcladeTorchStable.cmake").read_text(
            encoding="utf-8"
        )
        for token in (
            '"2.10"',
            "cxx_std_17",
            "/W4",
            "/WX",
            "-Wall",
            "-Wextra",
            "-Wpedantic",
            "-Werror",
            "CXX_VISIBILITY_PRESET hidden",
        ):
            self.assertIn(token, policy)

    def test_gpu_intake_is_off_and_fail_closed(self) -> None:
        root = (ROOT / "CMakeLists.txt").read_text(encoding="utf-8")
        cuda = (ROOT / "cuda" / "CMakeLists.txt").read_text(encoding="utf-8")
        self.assertIn("MINDCLADE_NATIVE_ENABLE_GPU", root)
        self.assertIn("OFF", root)
        for token in (
            "MINDCLADE_NATIVE_GPU_QUALIFICATION_MANIFEST",
            "MINDCLADE_NATIVE_GPU_QUALIFICATION_SHA256",
            "MINDCLADE_NATIVE_GPU_ARTIFACT",
            "MINDCLADE_NATIVE_GPU_ARTIFACT_SHA256",
            "file(",
            "SHA256",
            "qualified_operations",
            "GREATER 0",
            "torch.ops.mindclade.<name>",
        ):
            self.assertIn(token, cuda)

    def test_cmake_does_not_invent_dependency_authority(self) -> None:
        combined = "\n".join(
            path.read_text(encoding="utf-8") for path in CMAKE_FILES
        )
        for token in ("FetchContent", "ExternalProject", "find_package(Torch"):
            self.assertNotIn(token, combined)


if __name__ == "__main__":
    unittest.main()
