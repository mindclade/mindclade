#!/usr/bin/env python3.12
"""Validate component ownership and normalize component catalog facts."""

from __future__ import annotations

import argparse
import ast
import fnmatch
import json
import re
import sys
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol, cast

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError


class _Validator(Protocol):
    def iter_errors(self, instance: object) -> Iterable[ValidationError]: ...


def _yaml_scalar(value: str) -> Any:
    if value in {"null", "Null", "NULL", "~"}:
        return None
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    if value == "[]":
        return []
    if value == "{}":
        return {}
    if re.fullmatch(r"-?[0-9]+", value):
        return int(value)
    if value.startswith(("'", '"')):
        return ast.literal_eval(value)
    return value


def _parse_simple_yaml(text: str) -> Any:
    """Parse the strict mapping/list/scalar subset used by component metadata.

    Anchors, aliases, tags, block scalars, tabs, and implicit dates are intentionally unsupported.
    This keeps repository governance independent of ambient site packages.
    """

    tokens: list[tuple[int, str]] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        if "\t" in raw:
            raise ValueError(f"YAML line {number} contains a tab")
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        if indent % 2:
            raise ValueError(f"YAML line {number} has non-two-space indentation")
        content = raw[indent:]
        if " #" in content:
            content = content.split(" #", 1)[0].rstrip()
        tokens.append((indent, content))

    def mapping_item(content: str) -> tuple[str, str]:
        if ":" not in content:
            raise ValueError(f"YAML mapping entry lacks colon: {content!r}")
        key, value = content.split(":", 1)
        if not re.fullmatch(r"[A-Za-z0-9_.@/-]+", key):
            raise ValueError(f"unsupported YAML key: {key!r}")
        return key, value.strip()

    def parse_block(index: int, indent: int) -> tuple[Any, int]:
        if index >= len(tokens) or tokens[index][0] < indent:
            return {}, index
        is_list = tokens[index][1].startswith("- ") or tokens[index][1] == "-"
        result: Any = [] if is_list else {}
        while index < len(tokens):
            current_indent, content = tokens[index]
            if current_indent < indent:
                break
            if current_indent > indent:
                raise ValueError(f"unexpected YAML indentation before {content!r}")
            if is_list:
                if not content.startswith("-"):
                    break
                item = content[1:].strip()
                index += 1
                if not item:
                    value, index = parse_block(index, indent + 2)
                    result.append(value)
                elif ":" in item:
                    key, scalar = mapping_item(item)
                    value: dict[str, Any] = {key: _yaml_scalar(scalar)} if scalar else {}
                    if index < len(tokens) and tokens[index][0] > indent:
                        continuation, index = parse_block(index, indent + 2)
                        if not isinstance(continuation, dict):
                            raise ValueError("YAML list mapping continuation must be an object")
                        continuation = cast(dict[str, Any], continuation)
                        if not scalar and key in continuation:
                            value[key] = continuation.pop(key)
                        value.update(continuation)
                    result.append(value)
                else:
                    result.append(_yaml_scalar(item))
            else:
                if content.startswith("-"):
                    break
                key, scalar = mapping_item(content)
                index += 1
                if scalar:
                    result[key] = _yaml_scalar(scalar)
                else:
                    if index >= len(tokens) or tokens[index][0] <= indent:
                        result[key] = {}
                    else:
                        result[key], index = parse_block(index, indent + 2)
        return result, index

    if not tokens:
        return None
    value, consumed = parse_block(0, tokens[0][0])
    if consumed != len(tokens):
        raise ValueError(f"unparsed YAML content at {tokens[consumed][1]!r}")
    return value


def parse_yaml_or_json(text: str) -> Any:
    """Parse JSON or the repository's deliberately restricted YAML subset."""

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return _parse_simple_yaml(text)


def load_yaml_or_json(path: Path) -> Any:
    return parse_yaml_or_json(path.read_text(encoding="utf-8"))


def validate_component_document(value: Mapping[str, Any], schema: Mapping[str, Any]) -> list[str]:
    """Validate the full component schema plus repository-specific semantic checks."""

    errors: list[str] = []
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as error:
        return [f"invalid component schema: {error.message}"]
    validator = Draft202012Validator(schema)
    for error in cast(_Validator, validator).iter_errors(value):
        location = "/".join(str(part) for part in error.absolute_path) or "$"
        errors.append(f"schema {location}: {error.message}")
    if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
        errors.append("component schema does not declare JSON Schema 2020-12")
    return sorted(set(errors))


def discover_components(root: Path, schema_path: Path) -> tuple[list[str], list[dict[str, Any]]]:
    errors: list[str] = []
    schema_value = json.loads(schema_path.read_text(encoding="utf-8"))
    if not isinstance(schema_value, Mapping):
        return ["component schema root must be an object"], []
    schema = cast(Mapping[str, Any], schema_value)
    components: list[dict[str, Any]] = []
    for path in sorted(root.rglob("component.yaml")):
        if ".git" in path.parts or any(part.startswith("bazel-") for part in path.parts):
            continue
        try:
            value = load_yaml_or_json(path)
        except (OSError, ValueError) as error:
            errors.append(str(error))
            continue
        if not isinstance(value, Mapping):
            errors.append(f"{path}: component root must be an object")
            continue
        value = cast(Mapping[str, Any], value)
        errors.extend(f"{path}: {issue}" for issue in validate_component_document(value, schema))
        metadata = value.get("metadata", {})
        spec = value.get("spec", {})
        if not isinstance(metadata, Mapping) or not isinstance(spec, Mapping):
            continue
        metadata = cast(Mapping[str, Any], metadata)
        spec = cast(Mapping[str, Any], spec)
        status = value.get("status", {})
        if not isinstance(status, Mapping):
            status = {}
        status = cast(Mapping[str, Any], status)
        dependencies = spec.get("dependencies", [])
        provides = spec.get("provides", [])
        if not isinstance(dependencies, list) or not isinstance(provides, list):
            continue
        relative = str(path.parent.relative_to(root)) or "."
        components.append(
            {
                "name": str(metadata.get("name", "")),
                "path": relative,
                "metadata_path": str(path.relative_to(root)),
                "owner": str(spec.get("owner", "")),
                "maturity": str(spec.get("maturity", "")),
                "readiness": str(status.get("readiness", "")),
                "dependencies": list(cast(list[Any], dependencies)),
                "provides": list(cast(list[Any], provides)),
            }
        )
    names = [component["name"] for component in components]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    errors.extend(f"duplicate component identity: {name}" for name in duplicates)
    return errors, components


def _codeowners_rules(text: str) -> list[tuple[str, set[str]]]:
    rules: list[tuple[str, set[str]]] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split()
        if len(fields) < 2 or not all(owner.startswith("@") for owner in fields[1:]):
            raise ValueError(f"invalid CODEOWNERS rule at line {number}: {raw!r}")
        pattern = fields[0]
        if pattern.startswith("!") or "[" in pattern or "]" in pattern:
            raise ValueError(f"unsupported CODEOWNERS pattern at line {number}: {pattern!r}")
        rules.append((pattern, set(fields[1:])))
    return rules


def _codeowners_matches(pattern: str, path: str) -> bool:
    anchored = pattern.startswith("/")
    normalized = pattern.removeprefix("/")
    if normalized.endswith("/"):
        directory = normalized.rstrip("/")
        if anchored or "/" in directory:
            return path == directory or path.startswith(directory + "/")
        return directory in Path(path).parts[:-1]
    if "/" not in normalized and not anchored:
        return normalized == "*" or any(
            fnmatch.fnmatchcase(part, normalized) for part in Path(path).parts
        )
    return fnmatch.fnmatchcase(path, normalized)


def _effective_codeowners(rules: Sequence[tuple[str, set[str]]], path: str) -> set[str] | None:
    owners: set[str] | None = None
    for pattern, candidate_owners in rules:
        if _codeowners_matches(pattern, path):
            owners = candidate_owners
    return owners


def validate_owners(
    manifest: Mapping[str, Any],
    components: Sequence[Mapping[str, Any]],
    codeowners_path: Path | None,
) -> list[dict[str, str]]:
    known = set(manifest["metadata"]["owners"])
    entries = {str(entry["path"]): entry for entry in manifest["paths"]}
    gaps: list[dict[str, str]] = []
    for component in components:
        owner = str(component.get("owner", ""))
        if owner not in known:
            gaps.append(
                {
                    "type": "unknown_component_owner",
                    "path": str(component.get("path", "")),
                    "component": str(component.get("name", "")),
                    "owner": owner,
                }
            )
        metadata_path = str(component.get("metadata_path", ""))
        entry = entries.get(metadata_path)
        if entry is None:
            gaps.append(
                {
                    "type": "component_metadata_path_absent_from_manifest",
                    "path": metadata_path,
                    "component": str(component.get("name", "")),
                    "owner": owner,
                }
            )
        elif entry.get("component") != component.get("name") or entry.get("owner") != owner:
            gaps.append(
                {
                    "type": "component_manifest_metadata_mismatch",
                    "path": metadata_path,
                    "component": str(component.get("name", "")),
                    "owner": owner,
                }
            )
    if codeowners_path is not None and not codeowners_path.exists():
        gaps.append(
            {
                "type": "codeowners_missing",
                "path": str(codeowners_path),
                "component": "",
                "owner": "developer-platform",
            }
        )
    elif codeowners_path is not None:
        try:
            rules = _codeowners_rules(codeowners_path.read_text(encoding="utf-8"))
        except ValueError as error:
            gaps.append(
                {
                    "type": "codeowners_invalid",
                    "path": ".github/CODEOWNERS",
                    "component": "",
                    "owner": str(error),
                }
            )
            return gaps
        owner_metadata = manifest["metadata"]["owners"]
        for path, entry in entries.items():
            if entry.get("status") not in {"active", "generated"}:
                continue
            semantic_owner = str(entry.get("owner", ""))
            if semantic_owner not in owner_metadata:
                continue
            required_team = str(owner_metadata[semantic_owner]["team"])
            effective = _effective_codeowners(rules, path)
            if effective is None or required_team not in effective:
                gaps.append(
                    {
                        "type": "codeowners_path_owner_mismatch",
                        "path": path,
                        "component": str(entry.get("component", "")),
                        "owner": required_team,
                    }
                )
    return gaps


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--schema", type=Path, required=True)
    args = parser.parse_args(argv)
    from path_policy import load_manifest

    manifest = load_manifest(args.manifest)
    errors, components = discover_components(args.root, args.schema)
    gaps = validate_owners(manifest, components, args.root / ".github/CODEOWNERS")
    if errors or gaps:
        for error in errors:
            print(error, file=sys.stderr)
        for gap in gaps:
            print(json.dumps(gap, sort_keys=True), file=sys.stderr)
        return 1
    print(f"owner policy: PASS ({len(components)} components)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
