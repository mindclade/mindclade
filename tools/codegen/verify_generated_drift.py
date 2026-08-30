#!/usr/bin/env python3.12
"""Fail closed when committed generated bindings differ from their sources."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from generate_protocols import rendered_files


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    root = args.root.resolve()
    expected = rendered_files(root)
    stale = [
        str(path.relative_to(root))
        for path, content in expected.items()
        if not path.is_file() or path.read_text(encoding="utf-8") != content
    ]
    actual = set((root / "protocols" / "generated").glob("**/*"))
    expected_generated = {path for path in expected if "protocols/generated" in str(path)}
    unexpected = sorted(
        str(path.relative_to(root))
        for path in actual
        if path.is_file()
        and path not in expected_generated
        and "__pycache__" not in path.parts
        and path.suffix not in {".pyc", ".pyo"}
    )
    if stale or unexpected:
        for path in [*stale, *unexpected]:
            print(path)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
