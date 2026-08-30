#!/usr/bin/env python3.12
"""Render or drift-check the combined Mindclade architecture blueprint."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, cast


class BlueprintError(ValueError):
    """Raised when blueprint inputs violate the manifest contract."""


def load_manifest(path: Path) -> dict[str, Any]:
    """Load JSON-syntax YAML without adding a runtime package dependency."""

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BlueprintError(f"cannot read manifest {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise BlueprintError("blueprint manifest must be a mapping")
    return cast(dict[str, Any], data)


def safe_path(root: Path, relative: str) -> Path:
    candidate = (root / relative).resolve()
    resolved_root = root.resolve()
    if candidate != resolved_root and resolved_root not in candidate.parents:
        raise BlueprintError(f"path escapes blueprint root: {relative}")
    return candidate


def source_entries(manifest: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    sources_value = manifest.get("sources")
    if not isinstance(sources_value, dict):
        raise BlueprintError("manifest.sources must be a mapping")
    sources = cast(dict[str, Any], sources_value)
    result: list[tuple[str, dict[str, Any]]] = []
    for kind in ("sections", "appendices"):
        entries_value = sources.get(kind)
        if not isinstance(entries_value, list):
            raise BlueprintError(f"manifest.sources.{kind} must be a list")
        for entry_value in cast(list[Any], entries_value):
            if not isinstance(entry_value, dict):
                raise BlueprintError(f"manifest.sources.{kind} entries must be mappings")
            entry = cast(dict[str, Any], entry_value)
            result.append((kind, entry))
    return result


def source_path(manifest_path: Path, entry: dict[str, Any]) -> Path:
    relative = entry.get("path")
    if not isinstance(relative, str) or not relative:
        raise BlueprintError("every source entry requires a non-empty path")
    return safe_path(manifest_path.parent, relative)


def gfm_anchor(heading: str) -> str:
    """Return the repository's deterministic GFM-compatible heading anchor."""

    value = heading.strip().lower()
    value = re.sub(r"[^\w\- ]", "", value, flags=re.UNICODE)
    return value.replace(" ", "-")


def _document_value(document: dict[str, Any], key: str) -> str:
    value = document.get(key)
    if not isinstance(value, str) or not value:
        raise BlueprintError(f"manifest.document.{key} must be a non-empty string")
    return value


def render_preamble(manifest: dict[str, Any]) -> str:
    document_value = manifest.get("document")
    if not isinstance(document_value, dict):
        raise BlueprintError("manifest.document must be a mapping")
    document = cast(dict[str, Any], document_value)

    controls = (
        ("Document ID", "id"),
        ("Version", "version"),
        ("Status", "status"),
        ("Scope", "scope"),
        ("Audience", "audience"),
        ("Effective date", "effective_date"),
        ("Supersedes", "supersedes"),
        ("Review cadence", "review_cadence"),
        ("Repository evidence reviewed", "repository_evidence_reviewed"),
    )
    lines = [
        f"# {_document_value(document, 'title')}",
        "",
        "| Document control | Value |",
        "|---|---|",
    ]
    for label, key in controls:
        value = _document_value(document, key)
        if "\n" in value or "|" in value:
            raise BlueprintError(f"manifest.document.{key} is unsafe for a Markdown table")
        if key in {"id", "version"}:
            value = f"`{value}`"
        lines.append(f"| {label} | {value} |")

    lines.extend(
        (
            "",
            f"> **Authority note:** {_document_value(document, 'authority_note')}",
            "",
            "## Contents",
            "",
        )
    )
    entries = source_entries(manifest)
    sections = [entry for kind, entry in entries if kind == "sections"]
    appendices = [entry for kind, entry in entries if kind == "appendices"]
    for entry in sections:
        number, title = entry.get("number"), entry.get("title")
        heading = f"{number}. {title}"
        lines.append(f"{number}. [{title}](#{gfm_anchor(heading)})")
    if appendices:
        first = appendices[0]
        heading = f"Appendix A{first.get('number')} — {first.get('title')}"
        lines.append(f"{len(sections) + 1}. [Normative domain appendices](#{gfm_anchor(heading)})")
    return "\n".join(lines)


def render_blueprint(manifest_path: Path) -> str:
    manifest = load_manifest(manifest_path)
    chunks = [render_preamble(manifest)]
    for _, entry in source_entries(manifest):
        path = source_path(manifest_path, entry)
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise BlueprintError(f"cannot read blueprint source {path}: {exc}") from exc
        chunks.append(text.rstrip("\n"))
    return "\n\n---\n\n".join(chunks) + "\n"


def output_path(manifest_path: Path, manifest: dict[str, Any]) -> Path:
    relative = manifest.get("generated_output")
    if not isinstance(relative, str) or not relative:
        raise BlueprintError("manifest.generated_output must be a non-empty path")
    return safe_path(manifest_path.parent, relative)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("docs/architecture/blueprint/manifest.yaml"),
        help="ordered architecture source manifest",
    )
    parser.add_argument("--output", type=Path, help="override the manifest's generated output")
    parser.add_argument(
        "--check", action="store_true", help="fail instead of writing when output differs"
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest_path = args.manifest.resolve()
    try:
        manifest = load_manifest(manifest_path)
        rendered = render_blueprint(manifest_path)
        destination = args.output.resolve() if args.output else output_path(manifest_path, manifest)
    except BlueprintError as exc:
        print(f"blueprint render failed: {exc}", file=sys.stderr)
        return 2

    current = destination.read_text(encoding="utf-8") if destination.is_file() else None
    if args.check:
        if current != rendered:
            print(f"generated blueprint is stale: {destination}", file=sys.stderr)
            return 1
        print(f"blueprint render is current: {destination}")
        return 0

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(rendered, encoding="utf-8")
    print(f"rendered blueprint: {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
