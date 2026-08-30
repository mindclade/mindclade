from __future__ import annotations

import hashlib
import json
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
        baseline = repository / "protocols/compatibility/baselines/json-schema.lock.json"
        expected = {
            str(path.relative_to(repository)): "sha256:"
            + hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted((repository / "protocols/schemas").glob("**/*.schema.json"))
        }
        self.assertEqual(
            json.loads(baseline.read_text()),
            {"schema_version": "mindclade.json-schema-baseline/v1", "sources": expected},
        )


if __name__ == "__main__":
    unittest.main()
