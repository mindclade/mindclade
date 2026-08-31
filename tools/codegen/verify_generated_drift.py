#!/usr/bin/env python3.12
"""Fail closed when committed Protobuf bindings differ from locked generation."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, cast

sys.path.insert(0, str(Path(__file__).resolve().parent))

from generate_protocols import generated_outputs, governed_generated_paths, sha256_file


def verify_manifest(root: Path) -> list[str]:
    manifest_path = root / "protocols/generated/generated-files.manifest.json"
    raw: Any = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return [str(manifest_path.relative_to(root))]
    manifest = cast(dict[str, object], raw)
    raw_files = manifest.get("files")
    if not isinstance(raw_files, dict):
        return [str(manifest_path.relative_to(root))]
    stale: list[str] = []
    files = cast(dict[str, object], raw_files)
    for relative, expected in files.items():
        path = root / relative
        if not path.is_file() or not isinstance(expected, str) or sha256_file(path) != expected:
            stale.append(relative)
    expected_paths = {root / relative for relative in files}
    expected_paths.add(manifest_path)
    for path in governed_generated_paths(root):
        if path.is_file() and path not in expected_paths:
            stale.append(str(path.relative_to(root)))
    return sorted(set(stale))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    root = args.root.resolve()
    if "TEST_SRCDIR" in os.environ:
        stale = verify_manifest(root)
    else:
        expected, _, _ = generated_outputs(root)
        stale = [
            str(path.relative_to(root))
            for path, content in expected.items()
            if not path.is_file() or path.read_bytes() != content
        ]
        stale.extend(verify_manifest(root))
    if stale:
        for path in sorted(set(stale)):
            print(path)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
