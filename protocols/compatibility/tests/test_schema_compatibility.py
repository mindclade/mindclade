from __future__ import annotations

import sys
import unittest
from pathlib import Path


def root() -> Path:
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "protocols" / "compatibility" / "baselines").is_dir():
            return candidate
    raise RuntimeError("cannot locate schema compatibility baselines")


class SchemaCompatibilityTest(unittest.TestCase):
    def test_committed_baseline_matches_all_schema_sources(self) -> None:
        repository = root()
        sys.path.insert(0, str(repository / "tools" / "codegen"))
        from generate_protocols import rendered_files

        baseline = repository / "protocols/compatibility/baselines/json-schema.lock.json"
        self.assertEqual(baseline.read_bytes(), rendered_files(repository)[baseline].encode("utf-8"))


if __name__ == "__main__":
    unittest.main()
