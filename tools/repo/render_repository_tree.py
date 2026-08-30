#!/usr/bin/env python3.12
"""Render or verify Appendix A6 from the repository path manifest."""

from __future__ import annotations

import argparse
import sys
from collections import OrderedDict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from path_policy import PolicyError, load_manifest, validate_manifest

BEGIN_MARKER = "<!-- BEGIN GENERATED: repository-path-manifest -->"
END_MARKER = "<!-- END GENERATED: repository-path-manifest -->"


def _trie(paths: Sequence[str]) -> OrderedDict[str, Any]:
    root: OrderedDict[str, Any] = OrderedDict()
    for path in paths:
        node = root
        for part in path.split("/"):
            node = node.setdefault(part, OrderedDict())
    return root


def render_tree(paths: Sequence[str]) -> str:
    """Render a deterministic Unicode tree rooted at ``mindclade/``."""

    lines = ["mindclade/"]

    def visit(node: Mapping[str, Any], prefix: str) -> None:
        children = list(node.items())
        for index, (name, child) in enumerate(children):
            last = index == len(children) - 1
            connector = "└── " if last else "├── "
            directory = bool(child)
            lines.append(f"{prefix}{connector}{name}{'/' if directory else ''}")
            if directory:
                visit(child, prefix + ("    " if last else "│   "))

    visit(_trie(paths), "")
    return "\n".join(lines) + "\n"


def render_fenced(paths: Sequence[str]) -> str:
    return f"```text\n{render_tree(paths)}```\n"


def generated_region(paths: Sequence[str]) -> str:
    return f"{BEGIN_MARKER}\n{render_fenced(paths)}{END_MARKER}"


def replace_generated_region(document: str, paths: Sequence[str]) -> str:
    if document.count(BEGIN_MARKER) != 1 or document.count(END_MARKER) != 1:
        raise PolicyError("Appendix A6 must contain exactly one generated marker pair")
    before, remainder = document.split(BEGIN_MARKER, 1)
    _, after = remainder.split(END_MARKER, 1)
    return before + generated_region(paths) + after


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--appendix-a6", type=Path)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--tree-only", action="store_true")
    args = parser.parse_args(argv)
    if args.check and args.write:
        parser.error("--check and --write are mutually exclusive")
    if args.appendix_a6 and args.output:
        parser.error("--appendix-a6 and --output are mutually exclusive")

    manifest = load_manifest(args.manifest)
    errors = validate_manifest(manifest)
    if errors:
        raise PolicyError("invalid repository path manifest:\n" + "\n".join(errors))
    paths = [entry["path"] for entry in manifest["paths"]]

    if args.appendix_a6:
        current = args.appendix_a6.read_text(encoding="utf-8")
        expected = replace_generated_region(current, paths)
        if args.check:
            if current != expected:
                print(f"generated A6 region is stale: {args.appendix_a6}", file=sys.stderr)
                return 1
            print(f"repository tree render: PASS ({len(paths)} files)")
            return 0
        if args.write:
            args.appendix_a6.write_text(expected, encoding="utf-8")
            return 0
        sys.stdout.write(expected)
        return 0

    rendered = render_tree(paths) if args.tree_only else render_fenced(paths)
    if args.output:
        if args.check:
            if not args.output.exists() or args.output.read_text(encoding="utf-8") != rendered:
                print(f"repository tree render is stale: {args.output}", file=sys.stderr)
                return 1
            print(f"repository tree render: PASS ({len(paths)} files)")
            return 0
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
