# Copyright (c) 2026 Mindclade. All rights reserved.
# Proprietary and confidential. Unauthorized use, copying, or distribution is prohibited.

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "stable_abi" / "abi_manifest.json"


class AbiCompatibilityPolicyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    def test_target_metadata_is_unqualified(self) -> None:
        self.assertEqual(self.manifest["lifecycle"], "proposed")
        self.assertEqual(self.manifest["readiness"], "TARGET")
        self.assertEqual(self.manifest["activation_wave"], 6)
        self.assertEqual(self.manifest["activation_gate"], "JIT-06")
        self.assertFalse(self.manifest["production_authority"])
        self.assertEqual(self.manifest["qualified_operations"], [])
        self.assertEqual(self.manifest["active_operations"], [])
        self.assertEqual(
            self.manifest["qualification"]["kernel_k0"],
            "not-achieved",
        )

    def test_torch_stable_abi_contract_is_2_10(self) -> None:
        abi = self.manifest["torch_stable_abi"]
        self.assertEqual(abi, {"version": "2.10", "major": 2, "minor": 10})

    def test_only_mindclade_dispatcher_namespace_is_allowed(self) -> None:
        self.assertEqual(self.manifest["operator_namespace"], "mindclade")
        self.assertEqual(
            self.manifest["registration_contract"],
            "torch.ops.mindclade.<name>",
        )
        self.assertEqual(self.manifest["alternate_public_namespaces"], [])

    def test_every_future_manifest_operation_uses_the_single_contract(self) -> None:
        for operation in self.manifest["qualified_operations"]:
            name = operation["name"]
            self.assertRegex(name, r"^[a-z][a-z0-9_]*$")
            self.assertEqual(
                operation["torch_operator"],
                f"torch.ops.mindclade.{name}",
            )
            self.assertEqual(
                operation["registration_namespace"],
                "mindclade",
            )

    def test_cpp_registration_macros_cannot_name_an_alternate_namespace(self) -> None:
        macro = re.compile(
            r"TORCH_LIBRARY(?:_IMPL)?[(][ 	]*([A-Za-z_][A-Za-z0-9_]*)"
        )
        for path in sorted(ROOT.rglob("*.cpp")):
            text = path.read_text(encoding="utf-8")
            for namespace in macro.findall(text):
                self.assertEqual(namespace, "mindclade", path)

    def test_tensor_bridge_uses_only_approved_stable_headers(self) -> None:
        header = (ROOT / "stable_abi" / "tensor_bridge.h").read_text(encoding="utf-8")
        source = (ROOT / "stable_abi" / "tensor_bridge.cpp").read_text(encoding="utf-8")
        combined = header + source
        self.assertIn("torch/csrc/stable/tensor.h", combined)
        self.assertIn("torch/csrc/stable/ops.h", combined)
        self.assertIn("torch/csrc/inductor/aoti_torch/c/shim.h", combined)
        for forbidden in ("<ATen/", "<torch/extension.h>", "c10::cuda", "cudaDeviceSynchronize"):
            self.assertNotIn(forbidden, combined)
        for required in (
            "require_cuda_contiguous_tensor",
            "current_cuda_stream",
            "allocate_cuda_tensor",
            "allocate_workspace",
            "kNegativeInfinity",
        ):
            self.assertIn(required, combined)

    def test_callable_node_abi_is_c_compatible_and_stable_only(self) -> None:
        abi = (ROOT / "stable_abi" / "node_launch_abi.h").read_text(
            encoding="utf-8"
        )
        bridge = "\n".join(
            (ROOT / "stable_abi" / name).read_text(encoding="utf-8")
            for name in ("node_launch_bridge.h", "node_launch_bridge.cpp")
        )
        for token in (
            "MINDCLADE_NODE_LAUNCH_ABI_VERSION",
            "MindcladeNodeTensorV1",
            "MindcladeNodeValueV1",
            "MindcladeNodeLaunchV1",
            "MindcladeNodeAdapterV1",
            "STATUS_SUCCESS_V1",
            "specialization_digest[32]",
            "static_assert(sizeof(MindcladeNodeLaunchV1) == 48",
            "alignof(MindcladeNodeLaunchV1) == 8",
        ):
            self.assertIn(token, abi)
        self.assertNotIn("torch::", abi)
        self.assertNotIn("ATen", abi)
        self.assertIn("torch/csrc/stable/tensor.h", bridge)
        self.assertNotIn("<ATen/", bridge)
        self.assertNotIn("cudaDeviceSynchronize", bridge)
        capability = (ROOT / "stable_abi" / "qualified_capability_table.h").read_text(
            encoding="utf-8"
        )
        self.assertIn("uint8_t specialization_digest[32]", capability)


if __name__ == "__main__":
    unittest.main()
