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
        generated_python = repository / "protocols/generated/python"
        modules = sorted(
            ".".join(path.relative_to(generated_python).with_suffix("").parts)
            for path in generated_python.glob("**/*_pb2.py")
        )
        self.assertTrue(modules)
        imported = {name: importlib.import_module(name) for name in modules}
        module = imported["common.v1.identifiers_pb2"]
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
        typescript = (
            repository / "protocols/generated/typescript/common/v1/identifiers_pb.ts"
        ).read_text()
        self.assertIn(
            'export type Identifiers = Message<"mindclade.common.v1.Identifiers"> & {',
            typescript,
        )
        self.assertIn(
            "export const IdentifiersSchema: GenMessage<Identifiers> = /*@__PURE__*/",
            typescript,
        )


if __name__ == "__main__":
    unittest.main()
