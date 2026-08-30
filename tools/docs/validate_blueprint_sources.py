#!/usr/bin/env python3.12
"""Validate blueprint ordering, provenance, structure, and render drift."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol, cast

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError
from render_architecture_blueprint import (
    BlueprintError,
    gfm_anchor,
    load_manifest,
    output_path,
    render_blueprint,
    safe_path,
    source_entries,
    source_path,
)

BEGIN_TREE = "<!-- BEGIN GENERATED: repository-path-manifest -->"
END_TREE = "<!-- END GENERATED: repository-path-manifest -->"
FENCED_TREE = re.compile(r"^```text\nmindclade/\n.*?^```$", re.MULTILINE | re.DOTALL)
HEADING = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$")
MARKDOWN_LINK = re.compile(r"(?<!!)\[[^\]\n]+\]\(([^)\n]+)\)")
EXPLICIT_ANCHOR = re.compile(r"<a\s+[^>]*\b(?:id|name)=[\"']([^\"']+)[\"'][^>]*>", re.I)
PLACEHOLDER = re.compile(r"\b(?:TODO|TBD|FIXME|XXX)\b|\{\{[^{}\n]+\}\}")
SCHEMA_PATH = Path(__file__).with_name("blueprint_manifest.schema.json")


class _SchemaValidationError(Protocol):
    message: str
    absolute_path: Iterable[str | int]


class _SchemaValidator(Protocol):
    def iter_errors(self, instance: object) -> Iterable[_SchemaValidationError]: ...


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _expectations(manifest: Mapping[str, Any]) -> Mapping[str, Any]:
    value = manifest.get("heading_anchor_expectations")
    if not isinstance(value, dict):
        raise BlueprintError("manifest.heading_anchor_expectations must be a mapping")
    return cast(dict[str, Any], value)


def _expected_heading(manifest: Mapping[str, Any], kind: str, entry: Mapping[str, Any]) -> str:
    expectations = _expectations(manifest)
    template_key = "section_heading_template" if kind == "sections" else "appendix_heading_template"
    template = expectations.get(template_key)
    if not isinstance(template, str):
        raise BlueprintError(f"manifest.heading_anchor_expectations.{template_key} must be text")
    try:
        return template.format(number=entry.get("number"), title=entry.get("title"))
    except (KeyError, ValueError) as exc:
        raise BlueprintError(f"invalid heading template {template_key}: {exc}") from exc


def _outside_fences(text: str) -> list[str]:
    """Return Markdown lines outside fenced code blocks."""

    result: list[str] = []
    fence: str | None = None
    for line in text.splitlines():
        marker = re.match(r"^[ \t]*(`{3,}|~{3,})", line)
        if marker is not None:
            token = marker.group(1)
            if fence is None:
                fence = token[0]
            elif token[0] == fence:
                fence = None
            continue
        if fence is None:
            result.append(line)
    return result


def _heading_anchors(text: str) -> list[str]:
    anchors: list[str] = []
    for line in _outside_fences(text):
        match = HEADING.match(line)
        if match is not None:
            anchors.append(gfm_anchor(match.group(2)))
        anchors.extend(EXPLICIT_ANCHOR.findall(line))
    return anchors


def validate_manifest_schema(manifest: Mapping[str, Any]) -> list[str]:
    """Validate the source manifest against its committed JSON Schema."""

    try:
        schema_value = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return [f"cannot read blueprint manifest schema {SCHEMA_PATH}: {exc}"]
    if not isinstance(schema_value, dict):
        return [f"blueprint manifest schema must be a mapping: {SCHEMA_PATH}"]
    schema = cast(dict[str, Any], schema_value)
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        return [f"invalid blueprint manifest schema {SCHEMA_PATH}: {exc.message}"]
    validator = cast(
        _SchemaValidator,
        Draft202012Validator(schema, format_checker=FormatChecker()),
    )
    errors: list[str] = []
    for error in sorted(validator.iter_errors(manifest), key=lambda item: list(item.absolute_path)):
        location = ".".join(str(part) for part in error.absolute_path) or "<root>"
        errors.append(f"blueprint manifest schema violation at {location}: {error.message}")
    return errors


def validate_markdown_contract(text: str, label: str) -> list[str]:
    """Validate placeholders, unique anchors, and in-document link targets."""

    visible = "\n".join(_outside_fences(text))
    errors = [
        f"unresolved placeholder marker in {label}: {match.group(0)}"
        for match in PLACEHOLDER.finditer(visible)
    ]
    anchors = _heading_anchors(text)
    for anchor, count in sorted(Counter(anchors).items()):
        if count > 1:
            errors.append(f"duplicate Markdown anchor in {label}: #{anchor}")
    available = set(anchors)
    for match in MARKDOWN_LINK.finditer(visible):
        raw_target = match.group(1).strip().split(maxsplit=1)[0].strip("<>")
        if raw_target.startswith("#") and raw_target[1:] not in available:
            errors.append(f"broken Markdown anchor in {label}: {raw_target}")
    return errors


def validate_source_links(path: Path, text: str) -> list[str]:
    """Validate relative file links from one editable source."""

    errors: list[str] = []
    visible = "\n".join(_outside_fences(text))
    for match in MARKDOWN_LINK.finditer(visible):
        raw_target = match.group(1).strip().split(maxsplit=1)[0].strip("<>")
        if not raw_target or raw_target.startswith(("#", "/")):
            continue
        if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", raw_target):
            continue
        file_part, separator, fragment = raw_target.partition("#")
        candidate = (path.parent / file_part).resolve()
        if not candidate.is_file():
            errors.append(f"broken relative Markdown link in {path}: {raw_target}")
            continue
        if separator and fragment:
            try:
                target_anchors = set(_heading_anchors(candidate.read_text(encoding="utf-8")))
            except (OSError, UnicodeError) as exc:
                errors.append(f"cannot validate Markdown link target {candidate}: {exc}")
                continue
            if fragment not in target_anchors:
                errors.append(f"broken Markdown anchor in {path}: {raw_target}")
    return errors


def _render_repository_tree(paths: Iterable[str]) -> str:
    root: dict[str, Any] = {}
    for path in paths:
        node = root
        for part in path.split("/"):
            child = node.setdefault(part, {})
            if not isinstance(child, dict):
                raise BlueprintError(f"repository path is both file and directory: {path}")
            node = cast(dict[str, Any], child)

    lines = ["mindclade/"]

    def visit(node: Mapping[str, Any], prefix: str) -> None:
        children = list(node.items())
        for index, (name, child_value) in enumerate(children):
            last = index == len(children) - 1
            child = cast(dict[str, Any], child_value)
            directory = bool(child)
            lines.append(f"{prefix}{'└── ' if last else '├── '}{name}{'/' if directory else ''}")
            if directory:
                visit(child, prefix + ("    " if last else "│   "))

    visit(root, "")
    return "\n".join(lines) + "\n"


def validate_generated_tree(
    manifest_path: Path, manifest: Mapping[str, Any], a6_source: str
) -> list[str]:
    """Compare A6's generated region with the referenced path manifest."""

    relative = manifest.get("repository_path_manifest")
    if relative != "../repository-path-manifest.yaml":
        return ["manifest.repository_path_manifest must name ../repository-path-manifest.yaml"]
    repository_manifest = (manifest_path.parent / cast(str, relative)).resolve()
    expected_location = manifest_path.parent.parent / "repository-path-manifest.yaml"
    if repository_manifest != expected_location.resolve():
        return [f"repository-path manifest resolves outside its authority: {repository_manifest}"]
    try:
        value = json.loads(repository_manifest.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return [f"cannot read repository-path manifest {repository_manifest}: {exc}"]
    if not isinstance(value, dict):
        return [f"repository-path manifest has no paths list: {repository_manifest}"]
    repository_data = cast(dict[str, Any], value)
    path_entries = repository_data.get("paths")
    if not isinstance(path_entries, list):
        return [f"repository-path manifest has no paths list: {repository_manifest}"]
    paths: list[str] = []
    for index, entry_value in enumerate(cast(list[Any], path_entries)):
        if not isinstance(entry_value, dict):
            return [f"repository-path manifest paths[{index}] has no text path"]
        entry = cast(dict[str, Any], entry_value)
        path_value = entry.get("path")
        if not isinstance(path_value, str):
            return [f"repository-path manifest paths[{index}] has no text path"]
        paths.append(path_value)
    if len(paths) != len(set(paths)):
        return ["repository-path manifest contains duplicate paths"]
    bounded = a6_source.split(BEGIN_TREE, 1)[1].split(END_TREE, 1)[0]
    expected = f"\n```text\n{_render_repository_tree(paths)}```\n"
    if bounded != expected:
        return ["Appendix A6 generated tree is not synchronized with repository-path manifest"]
    return []


def _validate_a6_markers(source: str) -> list[str]:
    if source.count(BEGIN_TREE) != 1 or source.count(END_TREE) != 1:
        return ["Appendix A6 must contain one generated repository-path-manifest marker pair"]
    bounded = source.split(BEGIN_TREE, 1)[1].split(END_TREE, 1)[0]
    if len(list(FENCED_TREE.finditer(bounded))) != 1:
        return [
            "Appendix A6 generated region must contain exactly one explicit fenced mindclade/ tree"
        ]
    return []


def validate_blueprint(manifest_path: Path, require_generated: bool = True) -> list[str]:
    errors: list[str] = []
    try:
        manifest = load_manifest(manifest_path)
        errors.extend(validate_manifest_schema(manifest))
        entries = source_entries(manifest)
    except BlueprintError as exc:
        return [str(exc)]

    if manifest.get("schema") != "mindclade.dev/architecture-blueprint-manifest/v1":
        errors.append("manifest.schema must be mindclade.dev/architecture-blueprint-manifest/v1")
    document_value = manifest.get("document")
    if not isinstance(document_value, dict):
        errors.append("manifest.document must be a mapping")
    elif cast(dict[str, Any], document_value).get("version") != "3.4.2":
        errors.append("active blueprint version must be 3.4.2")

    sections = [(kind, entry) for kind, entry in entries if kind == "sections"]
    appendices = [(kind, entry) for kind, entry in entries if kind == "appendices"]
    if [entry.get("number") for _, entry in sections] != list(range(1, 19)):
        errors.append("manifest must order exactly sections 1 through 18")
    if [entry.get("number") for _, entry in appendices] != list(range(1, 41)):
        errors.append("manifest must order exactly appendices A1 through A40")

    listed_paths: list[Path] = []
    a6_source: str | None = None
    for kind, entry in entries:
        try:
            path = source_path(manifest_path, entry)
        except BlueprintError as exc:
            errors.append(str(exc))
            continue
        listed_paths.append(path)
        if not path.is_file():
            errors.append(f"missing blueprint source: {path}")
            continue
        raw = path.read_bytes()
        if b"\r" in raw:
            errors.append(f"source must use LF line endings: {path}")
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            errors.append(f"source is not UTF-8: {path}")
            continue
        if not text.endswith("\n"):
            errors.append(f"source must end with newline: {path}")
        first = text.splitlines()[0] if text else ""
        try:
            expected = _expected_heading(manifest, kind, entry)
        except BlueprintError as exc:
            errors.append(str(exc))
            continue
        if first != expected:
            errors.append(f"heading mismatch in {path}: expected {expected!r}, found {first!r}")
        if any(line.endswith((" ", "\t")) for line in text.splitlines()):
            errors.append(f"trailing whitespace in {path}")
        if sum(1 for line in text.splitlines() if line.startswith("```")) % 2:
            errors.append(f"unbalanced fenced blocks in {path}")
        errors.extend(validate_source_links(path, text))
        visible = "\n".join(_outside_fences(text))
        errors.extend(
            f"unresolved placeholder marker in {path}: {match.group(0)}"
            for match in PLACEHOLDER.finditer(visible)
        )
        if kind == "appendices" and entry.get("number") == 6:
            a6_source = text

    if len(set(listed_paths)) != len(listed_paths):
        errors.append("blueprint source paths must be unique")
    expected_set = {path.resolve() for path in listed_paths}
    for directory in (manifest_path.parent / "sections", manifest_path.parent / "appendices"):
        for path in sorted(directory.glob("*.md")):
            if path.resolve() not in expected_set:
                errors.append(f"unlisted blueprint source: {path}")

    provenance_value = manifest.get("provenance")
    if not isinstance(provenance_value, dict):
        errors.append("manifest.provenance must be a mapping")
    else:
        provenance = cast(dict[str, Any], provenance_value)
        for name in ("blueprint_v3_4_0", "repository_tree"):
            spec_value = provenance.get(name)
            if not isinstance(spec_value, dict):
                errors.append(f"missing provenance specification: {name}")
                continue
            spec = cast(dict[str, Any], spec_value)
            relative, expected_digest = spec.get("path"), spec.get("sha256")
            if not isinstance(relative, str) or not isinstance(expected_digest, str):
                errors.append(f"provenance {name} requires path and sha256")
                continue
            try:
                path = safe_path(manifest_path.parent, relative)
                actual_digest = sha256_file(path)
            except (BlueprintError, OSError) as exc:
                errors.append(f"cannot validate provenance {name}: {exc}")
                continue
            if actual_digest != expected_digest:
                errors.append(
                    f"provenance checksum mismatch for {path}: "
                    f"expected {expected_digest}, found {actual_digest}"
                )

    if a6_source is None:
        errors.append("Appendix A6 source is missing")
    else:
        errors.extend(_validate_a6_markers(a6_source))
        if not _validate_a6_markers(a6_source):
            errors.extend(validate_generated_tree(manifest_path, manifest, a6_source))

    try:
        rendered = render_blueprint(manifest_path)
        errors.extend(validate_markdown_contract(rendered, "generated architecture blueprint"))
        if "github.com/Mindclade/mindclade" in rendered:
            errors.append("generated blueprint retains non-canonical uppercase GitHub identity")
        for required_decision in (
            "`us-central1`",
            "`us-east4`",
            "Google Identity Platform",
            "proprietary internal-use license",
            "Per-wave cost approval",
        ):
            if required_decision not in rendered:
                errors.append(
                    f"generated blueprint omits owner-selected decision: {required_decision}"
                )
        for stale_decision in (
            "region decisions blocked",
            "MUST select primary/secondary GCP regions",
            "github.com/Mindclade/mindclade",
        ):
            if stale_decision in rendered:
                errors.append(
                    f"generated blueprint retains superseded decision text: {stale_decision}"
                )
        for old_name in (
            "docs/adr/0001-repository-identity.md",
            "docs/adr/0002-dependency-direction.md",
            "docs/adr/0003-artifact-identity.md",
            "docs/adr/0004-contract-authority.md",
            "docs/adr/0005-biological-identity.md",
            "docs/adr/0006-durable-work.md",
            "docs/adr/0007-training-state.md",
        ):
            if old_name in rendered:
                errors.append(f"generated blueprint retains superseded ADR path: {old_name}")
        if require_generated:
            generated_path = output_path(manifest_path, manifest)
            if not generated_path.is_file():
                errors.append(f"missing generated blueprint: {generated_path}")
            elif generated_path.read_text(encoding="utf-8") != rendered:
                errors.append(f"generated blueprint is stale: {generated_path}")
    except (BlueprintError, OSError, UnicodeError) as exc:
        errors.append(str(exc))
    return errors


def format_errors(errors: Sequence[str]) -> str:
    return "\n".join(f"- {error}" for error in errors)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("docs/architecture/blueprint/manifest.yaml"),
        help="ordered architecture source manifest",
    )
    parser.add_argument(
        "--allow-missing-render",
        action="store_true",
        help="validate editable inputs before the first generated render",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    errors = validate_blueprint(
        args.manifest.resolve(), require_generated=not args.allow_missing_render
    )
    if errors:
        print("blueprint validation failed:\n" + format_errors(errors), file=sys.stderr)
        return 1
    print("blueprint validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
