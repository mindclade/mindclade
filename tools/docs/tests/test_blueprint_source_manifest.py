"""Tests for the ordered source and immutable-provenance contract."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
TOOLS_DOCS = REPOSITORY_ROOT / "tools" / "docs"
sys.path.insert(0, str(TOOLS_DOCS))

from render_architecture_blueprint import BlueprintError, load_manifest, safe_path  # noqa: E402
from validate_blueprint_sources import (  # noqa: E402
    sha256_file,
    validate_blueprint,
    validate_generated_tree,
    validate_manifest_schema,
    validate_markdown_contract,
)


class BlueprintSourceManifestTest(unittest.TestCase):
    manifest_path = REPOSITORY_ROOT / "docs" / "architecture" / "blueprint" / "manifest.yaml"

    def test_manifest_and_sources_validate(self) -> None:
        self.assertEqual(validate_blueprint(self.manifest_path), [])

    def test_manifest_has_exact_ordered_source_counts(self) -> None:
        manifest = load_manifest(self.manifest_path)
        self.assertEqual(
            [item["number"] for item in manifest["sources"]["sections"]], list(range(1, 19))
        )
        self.assertEqual(
            [item["number"] for item in manifest["sources"]["appendices"]], list(range(1, 41))
        )
        paths = [
            item["path"]
            for group in (manifest["sources"]["sections"], manifest["sources"]["appendices"])
            for item in group
        ]
        self.assertEqual(len(paths), 58)
        self.assertEqual(len(set(paths)), 58)

    def test_manifest_records_render_and_repository_tree_contracts(self) -> None:
        manifest = load_manifest(self.manifest_path)
        self.assertEqual(validate_manifest_schema(manifest), [])
        self.assertEqual(
            manifest["heading_anchor_expectations"],
            {
                "source_heading_level": 2,
                "section_heading_template": "## {number}. {title}",
                "appendix_heading_template": "## Appendix A{number} — {title}",
                "anchor_algorithm": "gfm",
                "reject_duplicate_anchors": True,
            },
        )
        self.assertEqual(manifest["repository_path_manifest"], "../repository-path-manifest.yaml")

    def test_generated_tree_matches_repository_path_manifest(self) -> None:
        manifest = load_manifest(self.manifest_path)
        appendix = self.manifest_path.parent / "appendices/A06-authoritative-repository-tree.md"
        self.assertEqual(
            validate_generated_tree(
                self.manifest_path,
                manifest,
                appendix.read_text(encoding="utf-8"),
            ),
            [],
        )

    def test_markdown_contract_rejects_duplicate_anchor_placeholder_and_broken_link(self) -> None:
        errors = validate_markdown_contract(
            "# Example\n\n[missing](#absent)\n\n## Repeat\n\n## Repeat\n\nTODO\n",
            "fixture",
        )
        self.assertTrue(any("duplicate Markdown anchor" in error for error in errors))
        self.assertTrue(any("unresolved placeholder marker" in error for error in errors))
        self.assertTrue(any("broken Markdown anchor" in error for error in errors))

    def test_provenance_checksums_are_exact(self) -> None:
        manifest = load_manifest(self.manifest_path)
        for spec in manifest["provenance"].values():
            path = self.manifest_path.parent / spec["path"]
            self.assertEqual(sha256_file(path), spec["sha256"])

    def test_schema_is_well_formed_json(self) -> None:
        schema = json.loads(
            (TOOLS_DOCS / "blueprint_manifest.schema.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            schema["$id"],
            "https://schemas.mindclade.dev/architecture/blueprint-manifest.v1.schema.json",
        )

    def test_manifest_paths_cannot_escape_blueprint_root(self) -> None:
        with self.assertRaises(BlueprintError):
            safe_path(self.manifest_path.parent, "../../../../outside.md")


if __name__ == "__main__":
    unittest.main()
