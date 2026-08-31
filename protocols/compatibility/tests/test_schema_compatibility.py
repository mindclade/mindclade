from __future__ import annotations

import unittest
from pathlib import Path

from tools.codegen.generate_schemas import baseline_bytes


def root() -> Path:
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "protocols" / "compatibility" / "baselines").is_dir():
            return candidate
    raise RuntimeError("cannot locate schema compatibility baselines")


class SchemaCompatibilityTest(unittest.TestCase):
    def test_committed_baseline_matches_all_schema_sources(self) -> None:
        repository = root()
        baseline = repository / "protocols/compatibility/baselines/json-schema.lock.json"
        self.assertEqual(baseline.read_bytes(), baseline_bytes(repository))


if __name__ == "__main__":
    unittest.main()
