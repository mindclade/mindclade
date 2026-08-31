#!/usr/bin/env python3.12
"""Validate the governed JSON Schema catalog and guard baseline promotion."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any, Protocol, cast

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError, ValidationError

BASELINE_PATH = Path("protocols/compatibility/baselines/json-schema.lock.json")
MANIFEST_PATH = Path("docs/architecture/repository-path-manifest.yaml")
SCHEMA_ROOT = Path("protocols/schemas")
BASELINE_VERSION = "mindclade.json-schema-baseline/v2"


class CatalogError(ValueError):
    """Raised when a governed schema or fixture violates the catalog contract."""


class SchemaValidator(Protocol):
    def iter_errors(self, instance: object) -> Iterator[ValidationError]: ...


def sha256_bytes(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def load_object(path: Path) -> dict[str, object]:
    try:
        raw: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CatalogError(f"cannot load JSON object {path}: {error}") from error
    if not isinstance(raw, dict):
        raise CatalogError(f"expected a JSON object in {path}")
    return cast(dict[str, object], raw)


def governed_paths(root: Path, kind: str) -> set[Path]:
    manifest = load_object(root / MANIFEST_PATH)
    untyped_paths = manifest.get("paths")
    if not isinstance(untyped_paths, list):
        raise CatalogError(f"{MANIFEST_PATH} has no paths array")
    raw_paths = cast(list[object], untyped_paths)
    governed: set[Path] = set()
    for raw_entry in raw_paths:
        if not isinstance(raw_entry, Mapping):
            raise CatalogError(f"{MANIFEST_PATH} contains a non-object path entry")
        entry = cast(Mapping[str, object], raw_entry)
        path = entry.get("path")
        if (
            entry.get("kind") == kind
            and entry.get("status") == "active"
            and isinstance(path, str)
            and path.startswith(f"{SCHEMA_ROOT.as_posix()}/")
        ):
            governed.add(Path(path))
    return governed


def discovered_paths(root: Path, suffix: str) -> set[Path]:
    return {
        path.relative_to(root)
        for path in (root / SCHEMA_ROOT).glob("*/*.json")
        if (suffix == "schema") == path.name.endswith(".schema.json")
    }


def assert_governed_inventory(root: Path) -> tuple[list[Path], list[Path]]:
    declared_schemas = governed_paths(root, "schema")
    declared_fixtures = governed_paths(root, "fixture")
    actual_schemas = discovered_paths(root, "schema")
    actual_fixtures = discovered_paths(root, "fixture")
    errors: list[str] = []
    for label, declared, actual in (
        ("schemas", declared_schemas, actual_schemas),
        ("fixtures", declared_fixtures, actual_fixtures),
    ):
        missing = sorted(declared - actual)
        ungoverned = sorted(actual - declared)
        if missing:
            errors.append(f"missing governed {label}: {', '.join(map(str, missing))}")
        if ungoverned:
            errors.append(f"ungoverned {label}: {', '.join(map(str, ungoverned))}")
    if errors:
        raise CatalogError("; ".join(errors))
    return sorted(actual_schemas), sorted(actual_fixtures)


def validation_error_summary(errors: list[ValidationError]) -> str:
    first = errors[0]
    location = "/".join(str(part) for part in first.absolute_path) or "<root>"
    return f"{location}: {first.message}"


def validate_family(root: Path, schema_path: Path, fixture_paths: set[Path]) -> dict[str, object]:
    family = schema_path.parent.name
    family_fixtures = sorted(path for path in fixture_paths if path.parent.name == family)
    positives = [path for path in family_fixtures if path.name == "positive.json"]
    negatives = [path for path in family_fixtures if path.name.startswith("negative_")]
    if len(positives) != 1 or len(negatives) != 1 or len(family_fixtures) != 2:
        raise CatalogError(
            f"{family} requires exactly positive.json and one negative_<reason>.json"
        )

    schema = load_object(root / schema_path)
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as error:
        raise CatalogError(f"invalid Draft 2020-12 schema {schema_path}: {error}") from error
    if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
        raise CatalogError(f"{schema_path} must declare Draft 2020-12")

    validator = cast(
        SchemaValidator,
        Draft202012Validator(schema, format_checker=FormatChecker()),
    )
    positive = load_object(root / positives[0])
    positive_errors = sorted(validator.iter_errors(positive), key=lambda error: list(error.path))
    if positive_errors:
        raise CatalogError(
            f"positive fixture {positives[0]} failed: {validation_error_summary(positive_errors)}"
        )

    negative = load_object(root / negatives[0])
    negative_errors = sorted(validator.iter_errors(negative), key=lambda error: list(error.path))
    if not negative_errors:
        raise CatalogError(f"negative fixture {negatives[0]} unexpectedly validated")
    expected_failure = negatives[0].stem.removeprefix("negative_")
    if not expected_failure:
        raise CatalogError(f"negative fixture {negatives[0]} has no failure reason")

    return {
        "schema": {"path": str(schema_path), "sha256": sha256_file(root / schema_path)},
        "positive": {
            "path": str(positives[0]),
            "sha256": sha256_file(root / positives[0]),
            "expectation": "valid",
        },
        "negative": {
            "path": str(negatives[0]),
            "sha256": sha256_file(root / negatives[0]),
            "expectation": "invalid",
            "expected_failure": expected_failure,
        },
    }


def baseline_document(root: Path) -> dict[str, object]:
    schema_paths, fixture_paths = assert_governed_inventory(root)
    fixture_set = set(fixture_paths)
    catalog: dict[str, object] = {}
    for schema_path in schema_paths:
        family = schema_path.parent.name
        if family in catalog:
            raise CatalogError(f"duplicate schema family {family}")
        catalog[family] = validate_family(root, schema_path, fixture_set)
    return {"schema_version": BASELINE_VERSION, "catalog": catalog}


def baseline_bytes(root: Path) -> bytes:
    return (
        json.dumps(
            baseline_document(root),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        + "\n"
    ).encode("utf-8")


def check_baseline(root: Path, expected: bytes) -> bool:
    baseline_path = root / BASELINE_PATH
    return baseline_path.is_file() and baseline_path.read_bytes() == expected


def promote_baseline(root: Path, expected: bytes, predecessor_digest: str) -> None:
    baseline_path = root / BASELINE_PATH
    if not baseline_path.is_file():
        raise CatalogError(f"cannot promote without predecessor {BASELINE_PATH}")
    actual_digest = sha256_file(baseline_path)
    if predecessor_digest != actual_digest:
        raise CatalogError(
            "baseline promotion requires the exact reviewed predecessor digest: "
            f"expected {predecessor_digest!r}, actual {actual_digest!r}"
        )
    baseline_path.write_bytes(expected)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--check", action="store_true")
    action.add_argument("--promote-baseline", action="store_true")
    parser.add_argument(
        "--expected-baseline-digest",
        help="sha256:<hex> digest of the reviewed baseline being replaced",
    )
    args = parser.parse_args()
    if bool(args.promote_baseline) != bool(args.expected_baseline_digest):
        parser.error("--promote-baseline requires --expected-baseline-digest and vice versa")

    root = args.root.resolve()
    try:
        expected = baseline_bytes(root)
        if args.promote_baseline:
            promote_baseline(root, expected, args.expected_baseline_digest)
            catalog = cast(dict[str, object], baseline_document(root)["catalog"])
            print(f"promoted {BASELINE_PATH} ({len(catalog)} families)")
            return 0
        if not check_baseline(root, expected):
            print(f"stale {BASELINE_PATH}", file=sys.stderr)
            return 1
        catalog = cast(dict[str, object], baseline_document(root)["catalog"])
        print(f"validated {BASELINE_PATH} ({len(catalog)} families)")
        return 0
    except CatalogError as error:
        print(error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
