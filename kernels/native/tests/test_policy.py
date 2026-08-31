# Copyright (c) 2026 Mindclade. All rights reserved.
# Proprietary and confidential. Unauthorized use, copying, or distribution is prohibited.

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class NativeModulePolicyTest(unittest.TestCase):
    def test_component_uses_proposed_target_metadata(self) -> None:
        component = (ROOT / "component.yaml").read_text(encoding="utf-8")
        for line in (
            "apiVersion: mindclade.dev/v1",
            "  lifecycle: proposed",
            "  maturity: target",
            "  owner: ml-systems-performance",
            "  production_authority: false",
            "    wave: 6",
            "    gate: JIT-06",
            "  readiness: TARGET",
            "  kernel_k0: not-achieved",
            "  declared_operations: 4",
            "  unqualified_operations: 4",
            "  qualified_operations: 0",
            "  active_operations: 0",
        ):
            self.assertIn(line, component)

    def test_bazel_has_one_real_target_per_test_file(self) -> None:
        build = (ROOT / "BUILD.bazel").read_text(encoding="utf-8")
        expected = {
            name: f"tests/{name}.py"
            for name in (
                "test_abi_compatibility",
                "test_autograd",
                "test_build_policy",
                "test_cmake_policy",
                "test_codegen",
                "test_codegen_drift",
                "test_discovery",
                "test_export",
                "test_fake_tensor",
                "test_loader_policy",
                "test_manifest",
                "test_namespace",
                "test_opcheck",
                "test_policy",
                "test_qualification",
                "test_reference_runtime",
                "test_schema_manifest",
            )
        }
        blocks = re.findall(r"(?ms)^py_test[(]\n(.*?)^[)]$", build)
        actual = {}
        for block in blocks:
            name_match = re.search(
                r'(?m)^\s+name = "([^"]+)",$', block
            )
            source_match = re.search(
                r'"(tests/test_[^"]+[.]py)"', block
            )
            self.assertIsNotNone(name_match, block)
            self.assertIsNotNone(source_match, block)
            actual[name_match.group(1)] = source_match.group(1)
        self.assertEqual(actual, expected)
        self.assertNotIn('glob(["tests/', build)

    def test_current_registry_has_zero_qualified_operations(self) -> None:
        manifest = json.loads(
            (ROOT / "stable_abi" / "abi_manifest.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(manifest["qualified_operations"], [])
        self.assertEqual(manifest["active_operations"], [])
        self.assertFalse(manifest["production_authority"])

    def test_sm90_profiles_cover_declared_unqualified_operations(self) -> None:
        profiles = json.loads(
            (ROOT / "manifests" / "tilelang_profiles.sm90.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            profiles,
            {
                "mindclade::outer_product_mean": [
                    {
                        "arguments": {
                            "batch_size": 1,
                            "dtype": "float16",
                            "left_channels": 64,
                            "nodes": 32,
                            "right_channels": 64,
                            "sequence_length": 64,
                            "threads": 128,
                        },
                        "name": "b1_s64_n32_cl64_cr64_fp16",
                    }
                ],
                "mindclade::pair_weighted_average": [
                    {
                        "arguments": {
                            "batch_size": 1,
                            "block_sources": 64,
                            "channels": 64,
                            "dtype": "float16",
                            "heads": 8,
                            "mask_dtype": "float32",
                            "num_residues": 64,
                            "threads": 128,
                        },
                        "name": "b1_n64_h8_c64_fp16",
                    }
                ],
                "mindclade::triangle_attention": [
                    {
                        "arguments": {
                            "batch": 1,
                            "dtype": "float16",
                            "head_dim": 32,
                            "heads": 4,
                            "n": 32,
                            "threads": 64,
                        },
                        "name": "b1_n32_h4_d32_fp16",
                    },
                    {
                        "arguments": {
                            "batch": 1,
                            "dtype": "float16",
                            "head_dim": 32,
                            "heads": 8,
                            "n": 64,
                            "threads": 128,
                        },
                        "name": "b1_n64_h8_d32_fp16",
                    },
                    {
                        "arguments": {
                            "batch": 1,
                            "dtype": "bfloat16",
                            "head_dim": 64,
                            "heads": 8,
                            "n": 128,
                            "threads": 128,
                        },
                        "name": "b1_n128_h8_d64_bf16",
                    },
                    {
                        "arguments": {
                            "batch": 2,
                            "dtype": "float32",
                            "head_dim": 64,
                            "heads": 8,
                            "n": 64,
                            "threads": 128,
                        },
                        "name": "b2_n64_h8_d64_fp32",
                    },
                ],
                "mindclade::triangle_multiplication": [
                    {
                        "arguments": {
                            "batch": 1,
                            "block_channels": 64,
                            "channels": 64,
                            "dtype": "float16",
                            "outgoing": False,
                            "residues": 64,
                            "threads": 128,
                        },
                        "name": "b1_n64_c64_incoming_fp16",
                    },
                    {
                        "arguments": {
                            "batch": 1,
                            "block_channels": 64,
                            "channels": 64,
                            "dtype": "float16",
                            "outgoing": True,
                            "residues": 64,
                            "threads": 128,
                        },
                        "name": "b1_n64_c64_outgoing_fp16",
                    },
                ],
            },
        )

    def test_bazel_separates_hermetic_and_torch_test_authority(self) -> None:
        build = (ROOT / "BUILD.bazel").read_text(encoding="utf-8")
        suites = {}
        for block in re.findall(
            r"(?ms)^test_suite[(]\n(.*?)^[)]$", build
        ):
            name_match = re.search(
                r'(?m)^\s+name = "([^"]+)",$', block
            )
            self.assertIsNotNone(name_match, block)
            suites[name_match.group(1)] = {
                name
                for name in re.findall(
                    r'(?m)^\s+":(test_[^"]+)",$', block
                )
            }

        self.assertEqual(
            suites["policy_tests"],
            {
                "test_abi_compatibility",
                "test_build_policy",
                "test_cmake_policy",
                "test_codegen",
                "test_codegen_drift",
                "test_discovery",
                "test_manifest",
                "test_policy",
                "test_schema_manifest",
            },
        )
        self.assertEqual(
            suites["torch_runtime_tests"],
            {
                "test_autograd",
                "test_export",
                "test_fake_tensor",
                "test_loader_policy",
                "test_namespace",
                "test_opcheck",
            },
        )
        self.assertIn("requires-hermetic-torch-2.10", build)
        self.assertIn("license-reviewed hermetic Torch >=2.10", build)

    def test_documentation_states_the_single_operator_namespace(self) -> None:
        docs = (
            ROOT / "README.md",
            ROOT / "IMPLEMENTATION_STATUS.md",
            ROOT / "MIGRATION.md",
            ROOT / "cuda" / "README.md",
            ROOT / "tilelang" / "README.md",
        )
        namespace = re.compile(
            r"torch[.]ops[.]([A-Za-z_][A-Za-z0-9_]*)"
        )
        observed = set()
        for path in docs:
            text = path.read_text(encoding="utf-8")
            self.assertIn("torch.ops.mindclade.", text, path)
            observed.update(namespace.findall(text))
        self.assertEqual(observed, {"mindclade"})

    def test_no_document_claims_kernel_k0_or_production_authority(self) -> None:
        status = (ROOT / "IMPLEMENTATION_STATUS.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("kernel-k0 | not achieved", status)
        self.assertIn("Production authority | false", status)
        self.assertIn("Qualified operations | 0", status)


if __name__ == "__main__":
    unittest.main()
