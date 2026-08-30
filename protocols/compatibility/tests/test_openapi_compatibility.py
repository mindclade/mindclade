from __future__ import annotations

import json
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
        baseline = repository / "protocols/compatibility/baselines/openapi.lock.json"
        self.assertEqual(
            json.loads(baseline.read_text()),
            {"schema_version": "mindclade.openapi-baseline/v1", "sources": {}},
        )


if __name__ == "__main__":
    unittest.main()
