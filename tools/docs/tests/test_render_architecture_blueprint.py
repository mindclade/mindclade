"""Tests for deterministic combined-blueprint rendering."""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
TOOLS_DOCS = REPOSITORY_ROOT / "tools" / "docs"
sys.path.insert(0, str(TOOLS_DOCS))

from render_architecture_blueprint import load_manifest, output_path, render_blueprint  # noqa: E402


class RenderArchitectureBlueprintTest(unittest.TestCase):
    manifest_path = REPOSITORY_ROOT / "docs" / "architecture" / "blueprint" / "manifest.yaml"

    def test_render_is_deterministic_and_current(self) -> None:
        first = render_blueprint(self.manifest_path)
        second = render_blueprint(self.manifest_path)
        self.assertEqual(first, second)
        manifest = load_manifest(self.manifest_path)
        self.assertEqual(
            output_path(self.manifest_path, manifest).read_text(encoding="utf-8"), first
        )

    def test_render_has_canonical_document_control_and_identity(self) -> None:
        rendered = render_blueprint(self.manifest_path)
        self.assertIn("| Version | `3.4.2` |", rendered)
        self.assertIn("| Effective date | 2026-08-30 |", rendered)
        self.assertIn("github.com/mindclade/mindclade", rendered)
        self.assertNotIn("github.com/Mindclade/mindclade", rendered)
        self.assertIn("`us-central1`", rendered)
        self.assertIn("`us-east4`", rendered)
        self.assertIn("Google Identity Platform", rendered)
        self.assertIn("proprietary internal-use license", rendered)
        self.assertEqual(rendered.count("\n## Appendix A"), 40)

    def test_check_cli_accepts_current_render(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(TOOLS_DOCS / "render_architecture_blueprint.py"),
                "--manifest",
                str(self.manifest_path),
                "--check",
            ],
            cwd=REPOSITORY_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
