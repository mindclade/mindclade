from __future__ import annotations

import importlib
import os
import subprocess
import sys
import unittest
from pathlib import Path


def root() -> Path:
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "protocols" / "generated").is_dir():
            return candidate
    raise RuntimeError("cannot locate generated protocol bindings")


class GeneratedClientsContractTest(unittest.TestCase):
    def test_generated_bindings_are_current_and_compilable(self) -> None:
        repository = root()
        subprocess.run(
            [sys.executable, "tools/codegen/verify_generated_drift.py", "--root", "."],
            cwd=repository,
            check=True,
        )
        sys.path.insert(0, str(repository / "protocols/generated/python"))
        module = importlib.import_module("common.v1.identifiers_pb2")
        self.assertEqual(module.Identifiers(tenant_id="tenant").tenant_id, "tenant")
        if "TEST_SRCDIR" not in os.environ:
            subprocess.run(
                ["go", "test", "./protocols/generated/go/..."], cwd=repository, check=True
            )
            subprocess.run(
                ["cargo", "test", "--locked", "-p", "mindclade-protocols"],
                cwd=repository,
                check=True,
            )
        self.assertIn(
            "export interface",
            (repository / "protocols/generated/typescript/common/v1/identifiers_pb.ts").read_text(),
        )


if __name__ == "__main__":
    unittest.main()
