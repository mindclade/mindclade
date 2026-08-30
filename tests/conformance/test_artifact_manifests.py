from __future__ import annotations

import json
import unittest
from pathlib import Path

import jsonschema


def root() -> Path:
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "protocols" / "schemas").is_dir():
            return candidate
    raise RuntimeError("cannot locate protocol sources")


class ArtifactManifestContractTest(unittest.TestCase):
    def test_positive_and_negative_fixtures(self) -> None:
        repository = root()
        matrix = json.loads((repository / "tests/conformance/contract_matrix.yaml").read_text())
        self.assertEqual(matrix["schema_version"], "mindclade.contract-matrix/v1")
        for schema_path in sorted((repository / "protocols/schemas").glob("*/*.schema.json")):
            schema = json.loads(schema_path.read_text())
            directory = schema_path.parent
            jsonschema.Draft202012Validator.check_schema(schema)
            jsonschema.validate(json.loads((directory / "positive.json").read_text()), schema)
            negative = next(directory.glob("negative_*.json"))
            with self.assertRaises(jsonschema.ValidationError):
                jsonschema.validate(json.loads(negative.read_text()), schema)


if __name__ == "__main__":
    unittest.main()
