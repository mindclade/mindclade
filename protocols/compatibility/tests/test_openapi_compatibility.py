from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


def root() -> Path:
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "protocols" / "compatibility" / "baselines").is_dir():
            return candidate
    raise RuntimeError("cannot locate OpenAPI compatibility baselines")


class OpenApiCompatibilityTest(unittest.TestCase):
    def test_committed_baseline_including_explicit_empty_inventory_matches_sources(self) -> None:
        repository = root()
        sys.path.insert(0, str(repository / "tools" / "codegen"))
        from generate_protocols import rendered_files

        baseline = repository / "protocols/compatibility/baselines/openapi.lock.json"
        committed = baseline.read_bytes()
        self.assertIsInstance(json.loads(committed), dict)
        self.assertEqual(committed, rendered_files(repository)[baseline].encode("utf-8"))


if __name__ == "__main__":
    unittest.main()
