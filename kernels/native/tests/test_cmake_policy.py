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

    def test_schema_only_definition_is_not_applied_to_gpu_registry(self) -> None:
        policy = (ROOT / "cmake" / "MindcladeTorchStable.cmake").read_text(
            encoding="utf-8"
        )
        cuda = (ROOT / "cuda" / "CMakeLists.txt").read_text(encoding="utf-8")
        common = policy.split(
            "function(_mindclade_apply_native_common_target_policy", 1
        )[1].split("endfunction()", 1)[0]
        gpu = policy.split(
            "function(mindclade_apply_gpu_registry_target_policy", 1
        )[1].split("endfunction()", 1)[0]
        schema = policy.split("function(mindclade_apply_native_target_policy", 1)[
            1
        ].split("endfunction()", 1)[0]
        self.assertNotIn("MINDCLADE_NATIVE_SCHEMA_ONLY", common)
        self.assertNotIn("MINDCLADE_NATIVE_SCHEMA_ONLY", gpu)
        self.assertIn("MINDCLADE_NATIVE_SCHEMA_ONLY=1", schema)
        self.assertIn(
            "mindclade_apply_gpu_registry_target_policy(mindclade_native_cuda_registry)",
            cuda,
        )
        self.assertNotIn(
            "mindclade_apply_native_target_policy(mindclade_native_cuda_registry)",
            cuda,
        )

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

    def test_generated_inventory_is_the_private_symbol_authority(self) -> None:
        root = (ROOT / "CMakeLists.txt").read_text(encoding="utf-8")
        generated = (ROOT / "generated" / "native_ops.generated.cmake").read_text(
            encoding="utf-8"
        )
        self.assertIn("include(generated/native_ops.generated.cmake)", root)
        self.assertIn("MINDCLADE_TILELANG_REQUIRED_PRIVATE_SYMBOLS", generated)
        self.assertNotIn(
            "set(MINDCLADE_TILELANG_REQUIRED_PRIVATE_SYMBOLS", root
        )

    def test_private_symbols_require_a_qualified_bridge_before_definition(self) -> None:
        root = (ROOT / "CMakeLists.txt").read_text(encoding="utf-8")
        cuda = (ROOT / "cuda" / "CMakeLists.txt").read_text(encoding="utf-8")
        self.assertIn("MINDCLADE_NATIVE_PROGRAM_GROUP_BRIDGE_LIBRARY", root)
        self.assertIn("MINDCLADE_NATIVE_PROGRAM_GROUP_BRIDGE_LIBRARY_SHA256", root)
        branch = cuda.split(
            "if(MINDCLADE_TILELANG_REQUIRED_PRIVATE_SYMBOLS)", 1
        )[1]
        for token in (
            "IS_ABSOLUTE",
            "EXISTS",
            "IS_DIRECTORY",
            "SHA256",
            "mindclade_native_program_group_bridge UNKNOWN IMPORTED",
            "IMPORTED_LOCATION",
            "PRIVATE mindclade_native_program_group_bridge",
            "PRIVATE MINDCLADE_PROGRAM_GROUP_BRIDGE_V1=1",
        ):
            self.assertIn(token, branch)
        self.assertEqual(cuda.count("MINDCLADE_PROGRAM_GROUP_BRIDGE_V1=1"), 1)
        self.assertNotIn("MINDCLADE_NATIVE_SCHEMA_ONLY", cuda)

    def test_cmake_does_not_invent_dependency_authority(self) -> None:
        combined = "\n".join(
            path.read_text(encoding="utf-8") for path in CMAKE_FILES
        )
        for token in ("FetchContent", "ExternalProject", "find_package(Torch"):
            self.assertNotIn(token, combined)


if __name__ == "__main__":
    unittest.main()
