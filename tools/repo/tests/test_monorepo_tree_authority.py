from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "tools/repo"))

from path_policy import (  # noqa: E402
    AUTHORITY_DIRECTORY_COUNT,
    AUTHORITY_FILE_COUNT,
    AUTHORITY_SHA256,
    CANONICAL_FILE_COUNT,
    extract_authority_paths,
    path_set_sha256,
    reconcile_authority_paths,
    sha256_file,
    validate_manifest,
)


def _provenance(name: str) -> Path:
    candidates = (
        REPO_ROOT / "docs/architecture/blueprint/provenance" / name,
        REPO_ROOT.parent / name,
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise AssertionError(f"missing immutable provenance source {name}")


def _explicit_directory_count(markdown: str) -> int:
    match = re.search(r"```text\nmindclade/\n(?P<body>.*?)\n```", markdown, re.DOTALL)
    if match is None:
        raise AssertionError("mindclade tree is absent")
    count = 0
    for line in match.group("body").splitlines():
        name = re.sub(r"^((?:│   |    )*)(?:├── |└── )", "", line)
        name = name.split("  # ", 1)[0]
        count += name.endswith("/")
    return count


class MonorepoTreeAuthorityTest(unittest.TestCase):
    def setUp(self) -> None:
        self.authority_path = _provenance("MONOREPO_TREE.md")
        self.authority_text = self.authority_path.read_text(encoding="utf-8")
        self.manifest = json.loads(
            (REPO_ROOT / "docs/architecture/repository-path-manifest.yaml").read_text(
                encoding="utf-8"
            )
        )

    def test_immutable_authority_checksum_and_counts(self) -> None:
        self.assertEqual(sha256_file(self.authority_path), AUTHORITY_SHA256)
        paths = extract_authority_paths(self.authority_text)
        self.assertEqual(len(paths), AUTHORITY_FILE_COUNT)
        self.assertEqual(_explicit_directory_count(self.authority_text), AUTHORITY_DIRECTORY_COUNT)
        self.assertEqual(len(paths), len(set(paths)))

    def test_inline_directory_annotation_is_not_a_file(self) -> None:
        paths = extract_authority_paths(self.authority_text)
        self.assertIn("training/studies/definition.py", paths)
        self.assertNotIn("training/studies/  # scientific HPO; separate from systems tuning", paths)
        self.assertFalse(any("#" in path for path in paths))

    def test_blueprint_appendix_a6_has_exact_path_parity(self) -> None:
        blueprint = _provenance("MINDCLADE_MONOREPO_BLUEPRINT_v3.4.0_OPTIMIZED.md").read_text(
            encoding="utf-8"
        )
        start = blueprint.index("## Appendix A6 —")
        end = blueprint.index("### A6.1 ", start)
        self.assertEqual(
            extract_authority_paths(self.authority_text),
            extract_authority_paths(blueprint[start:end]),
        )

    def test_closed_reconciliation_equals_canonical_manifest(self) -> None:
        original = extract_authority_paths(self.authority_text)
        canonical = reconcile_authority_paths(original)
        manifest_paths = [entry["path"] for entry in self.manifest["paths"]]
        self.assertEqual(canonical, manifest_paths)
        self.assertEqual(len(canonical), CANONICAL_FILE_COUNT)
        self.assertEqual(
            path_set_sha256(canonical),
            self.manifest["metadata"]["reconciliation"]["canonical_path_set_sha256"],
        )
        self.assertEqual(validate_manifest(self.manifest), [])


if __name__ == "__main__":
    unittest.main()
