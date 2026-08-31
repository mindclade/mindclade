from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import cast

from tools.codegen.generate_schemas import baseline_document


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
        manifest = json.loads(
            (repository / "docs/architecture/repository-path-manifest.yaml").read_text()
        )
        declared_schemas = {
            entry["path"]
            for entry in manifest["paths"]
            if entry["kind"] == "schema"
            and entry["status"] == "active"
            and entry["path"].startswith("protocols/schemas/")
        }
        declared_fixtures = {
            entry["path"]
            for entry in manifest["paths"]
            if entry["kind"] == "fixture"
            and entry["status"] == "active"
            and entry["path"].startswith("protocols/schemas/")
        }
        schema_paths = sorted((repository / "protocols/schemas").glob("*/*.schema.json"))
        fixture_paths = sorted(
            path
            for path in (repository / "protocols/schemas").glob("*/*.json")
            if not path.name.endswith(".schema.json")
        )
        self.assertEqual(
            {str(path.relative_to(repository)) for path in schema_paths},
            declared_schemas,
        )
        self.assertEqual(
            {str(path.relative_to(repository)) for path in fixture_paths},
            declared_fixtures,
        )
        self.assertEqual(
            {
                contract["name"]
                for contract in matrix["contracts"]
                if contract["compatibility"] == "schema-versioned"
            },
            {path.parent.name for path in schema_paths},
        )

        validated_catalog = cast(dict[str, object], baseline_document(repository)["catalog"])
        self.assertEqual(set(validated_catalog), {path.parent.name for path in schema_paths})
        for schema_path in schema_paths:
            schema = json.loads(schema_path.read_text())
            directory = schema_path.parent
            positive_fixtures = list(directory.glob("positive.json"))
            negative_fixtures = list(directory.glob("negative_*.json"))
            self.assertEqual(len(positive_fixtures), 1, directory.name)
            self.assertEqual(len(negative_fixtures), 1, directory.name)
            self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")


if __name__ == "__main__":
    unittest.main()
