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
            "  qualified_operations: 0",
            "  active_operations: 0",
        ):
            self.assertIn(line, component)

    def test_bazel_has_one_real_target_per_test_file(self) -> None:
        build = (ROOT / "BUILD.bazel").read_text(encoding="utf-8")
        self.assertEqual(build.count("py_test("), 3)
        self.assertNotIn("pytest", build)
        self.assertNotIn('glob(["tests/', build)
        for name in (
            "test_abi_compatibility",
            "test_cmake_policy",
            "test_policy",
        ):
            self.assertIn(f'name = "{name}"', build)
            self.assertIn(f'srcs = ["tests/{name}.py"]', build)

    def test_current_registry_has_zero_qualified_operations(self) -> None:
        manifest = json.loads(
            (ROOT / "stable_abi" / "abi_manifest.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(manifest["qualified_operations"], [])
        self.assertEqual(manifest["active_operations"], [])
        self.assertFalse(manifest["production_authority"])

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
