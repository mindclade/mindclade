#!/usr/bin/env python3.12
"""Validate the governed JSON Schema catalog and guard baseline promotion."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, TypeGuard, cast

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError, ValidationError

BASELINE_PATH = Path("protocols/compatibility/baselines/json-schema.lock.json")
MANIFEST_PATH = Path("docs/architecture/repository-path-manifest.yaml")
SCHEMA_ROOT = Path("protocols/schemas")
BASELINE_VERSION = "mindclade.json-schema-baseline/v2"
GENERATOR = "mindclade-schema-codegen"
GENERATED_ROOT = Path("protocols/generated")
TOOLCHAIN_LOCK = Path("tools/codegen/toolchain.lock.json")

GO_BINDING = GENERATED_ROOT / "go/schema/v1/bindings.generated.go"
GO_BINDING_TEST = GENERATED_ROOT / "go/schema/v1/bindings_generated_test.go"
GO_BUILD = GENERATED_ROOT / "go/schema/v1/BUILD.bazel"
PYTHON_BINDING = GENERATED_ROOT / "python/mindclade/schema/v1/bindings.py"
PYTHON_INIT = GENERATED_ROOT / "python/mindclade/schema/v1/__init__.py"
RUST_BINDING = GENERATED_ROOT / "rust/schema/v1.rs"
TYPESCRIPT_BINDING = GENERATED_ROOT / "typescript/schema/v1/bindings.ts"


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


@dataclass(frozen=True)
class ObjectBinding:
    """A named object discovered in one governed schema."""

    name: str
    pointer: str
    value: Mapping[str, object]


@dataclass(frozen=True)
class SchemaBinding:
    """Language-neutral binding model for one schema family."""

    family: str
    title: str
    schema: Mapping[str, object]
    names: Mapping[str, str]
    objects: tuple[ObjectBinding, ...]


def pascal_case(value: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", value)
    result = "".join(word[:1].upper() + word[1:] for word in words)
    if not result:
        return "Value"
    if result[0].isdigit():
        return "Value" + result
    return result


def pointer_escape(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def is_object_mapping(value: object) -> TypeGuard[Mapping[str, object]]:
    """Narrow JSON objects to the string-keyed mapping used by schema traversal."""
    return isinstance(value, Mapping)


def pointer_value(schema: Mapping[str, object], pointer: str) -> Mapping[str, object]:
    if pointer == "#":
        return schema
    if not pointer.startswith("#/"):
        raise CatalogError(f"only local JSON Schema references are supported: {pointer}")
    value: object = schema
    for encoded in pointer[2:].split("/"):
        part = encoded.replace("~1", "/").replace("~0", "~")
        if not is_object_mapping(value):
            raise CatalogError(f"unresolved local JSON Schema reference: {pointer}")
        if part not in value:
            raise CatalogError(f"unresolved local JSON Schema reference: {pointer}")
        value = value[part]
    if not is_object_mapping(value):
        raise CatalogError(f"JSON Schema reference is not an object: {pointer}")
    return value


def is_object_schema(value: Mapping[str, object]) -> bool:
    return value.get("type") == "object" or isinstance(value.get("properties"), Mapping)


def build_binding(family: str, raw_schema: Mapping[str, object]) -> SchemaBinding:
    raw_title = raw_schema.get("title")
    if not isinstance(raw_title, str) or not raw_title:
        raise CatalogError(f"{family} has no binding title")
    title = pascal_case(raw_title)
    names: dict[str, str] = {}
    objects: list[ObjectBinding] = []
    used_names: set[str] = set()

    def unique_name(candidate: str) -> str:
        value = candidate
        index = 2
        while value in used_names:
            value = f"{candidate}{index}"
            index += 1
        used_names.add(value)
        return value

    def walk(value: Mapping[str, object], pointer: str, hint: str) -> None:
        reference = value.get("$ref")
        if isinstance(reference, str):
            pointer_value(raw_schema, reference)
            return
        if is_object_schema(value):
            properties = value.get("properties")
            closed_empty = value.get("additionalProperties") is False
            if isinstance(properties, Mapping) or closed_empty:
                name = unique_name(title if pointer == "#" else title + pascal_case(hint))
                names[pointer] = name
                objects.append(ObjectBinding(name, pointer, value))
            if isinstance(properties, Mapping):
                for property_name, child in cast(Mapping[str, object], properties).items():
                    if isinstance(child, Mapping):
                        walk(
                            cast(Mapping[str, object], child),
                            f"{pointer}/properties/{pointer_escape(property_name)}",
                            hint + pascal_case(property_name),
                        )
            additional = value.get("additionalProperties")
            if isinstance(additional, Mapping):
                walk(
                    cast(Mapping[str, object], additional),
                    f"{pointer}/additionalProperties",
                    hint + "Value",
                )
        items = value.get("items")
        if isinstance(items, Mapping):
            walk(cast(Mapping[str, object], items), f"{pointer}/items", hint + "Item")
        alternatives = value.get("oneOf")
        if isinstance(alternatives, list):
            for index, child in enumerate(cast(list[object], alternatives)):
                if isinstance(child, Mapping):
                    walk(
                        cast(Mapping[str, object], child),
                        f"{pointer}/oneOf/{index}",
                        f"{hint}Option{index + 1}",
                    )

    walk(raw_schema, "#", "")
    definitions = raw_schema.get("$defs")
    if isinstance(definitions, Mapping):
        for definition_name, definition in cast(Mapping[str, object], definitions).items():
            if not isinstance(definition, Mapping):
                continue
            pointer = f"#/$defs/{pointer_escape(definition_name)}"
            if pointer not in names and is_object_schema(cast(Mapping[str, object], definition)):
                walk(
                    cast(Mapping[str, object], definition),
                    pointer,
                    pascal_case(definition_name),
                )
    return SchemaBinding(family, title, raw_schema, names, tuple(objects))


def schema_bindings(root: Path) -> tuple[SchemaBinding, ...]:
    schema_paths, _ = assert_governed_inventory(root)
    return tuple(build_binding(path.parent.name, load_object(root / path)) for path in schema_paths)


def dereference(
    binding: SchemaBinding, value: Mapping[str, object]
) -> tuple[str | None, Mapping[str, object]]:
    reference = value.get("$ref")
    if not isinstance(reference, str):
        return None, value
    return reference, pointer_value(binding.schema, reference)


def mapping_entries(value: object) -> list[tuple[str, Mapping[str, object]]]:
    if not isinstance(value, Mapping):
        return []
    entries: list[tuple[str, Mapping[str, object]]] = []
    for name, child in cast(Mapping[str, object], value).items():
        if isinstance(child, Mapping):
            entries.append((name, cast(Mapping[str, object], child)))
    return entries


def required_names(value: Mapping[str, object]) -> frozenset[str]:
    raw = value.get("required")
    if not isinstance(raw, list):
        return frozenset()
    raw_items = cast(list[object], raw)
    if not all(isinstance(item, str) for item in raw_items):
        return frozenset()
    return frozenset(cast(list[str], raw_items))


def schema_source_map(bindings: Sequence[SchemaBinding]) -> dict[str, str]:
    return {
        binding.family: json.dumps(
            binding.schema,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        for binding in bindings
    }


def fixture_source_map(root: Path, bindings: Sequence[SchemaBinding]) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for binding in bindings:
        directory = root / SCHEMA_ROOT / binding.family
        positive = directory / "positive.json"
        negatives = sorted(directory.glob("negative_*.json"))
        if len(negatives) != 1:
            raise CatalogError(f"{binding.family} requires one negative fixture")
        result[binding.family] = {
            "positive": positive.read_text(encoding="utf-8").strip(),
            "negative": negatives[0].read_text(encoding="utf-8").strip(),
        }
    return result


def python_type(binding: SchemaBinding, value: Mapping[str, object], pointer: str) -> str:
    reference, resolved = dereference(binding, value)
    if reference is not None and reference in binding.names:
        return json.dumps(binding.names[reference])
    if reference is not None:
        return python_type(binding, resolved, reference)
    alternatives = resolved.get("oneOf")
    if isinstance(alternatives, list):
        members = [
            python_type(binding, cast(Mapping[str, object], item), f"{pointer}/oneOf/{index}")
            for index, item in enumerate(cast(list[object], alternatives))
            if isinstance(item, Mapping)
        ]
        return f"Union[{', '.join(members)}]" if members else "Any"
    if "const" in resolved:
        return f"Literal[{resolved['const']!r}]"
    enum = resolved.get("enum")
    if isinstance(enum, list) and enum:
        values = ", ".join(repr(item) for item in cast(list[object], enum))
        return f"Literal[{values}]"
    value_type = resolved.get("type")
    if isinstance(value_type, list):
        members = [
            python_type(binding, {"type": item}, pointer)
            for item in cast(list[object], value_type)
            if isinstance(item, str)
        ]
        return f"Union[{', '.join(members)}]" if members else "Any"
    if value_type == "string":
        return "str"
    if value_type == "integer":
        return "int"
    if value_type == "number":
        return "float"
    if value_type == "boolean":
        return "bool"
    if value_type == "array":
        items = resolved.get("items")
        item_type = (
            python_type(binding, cast(Mapping[str, object], items), f"{pointer}/items")
            if isinstance(items, Mapping)
            else "Any"
        )
        return f"list[{item_type}]"
    if is_object_schema(resolved):
        if pointer in binding.names:
            return json.dumps(binding.names[pointer])
        additional = resolved.get("additionalProperties")
        value_binding = (
            python_type(
                binding,
                cast(Mapping[str, object], additional),
                f"{pointer}/additionalProperties",
            )
            if isinstance(additional, Mapping)
            else "Any"
        )
        return f"dict[str, {value_binding}]"
    return "Any"


def render_python(
    bindings: Sequence[SchemaBinding], fixtures: Mapping[str, Mapping[str, str]]
) -> bytes:
    sources = schema_source_map(bindings)
    serialized_sources = json.dumps(sources, sort_keys=True, indent=4)
    serialized_fixtures = json.dumps(fixtures, sort_keys=True, indent=4)
    lines = [
        f"# Code generated by {GENERATOR}. DO NOT EDIT.",
        "from __future__ import annotations",
        "",
        "import json",
        "from functools import lru_cache",
        "from typing import Any, Final, Literal, NotRequired, TypedDict, Union, cast",
        "",
        "from jsonschema import Draft202012Validator, FormatChecker",
        "from jsonschema.exceptions import ValidationError",
        "",
    ]
    for binding in bindings:
        for obj in binding.objects:
            fields: list[str] = []
            required = required_names(obj.value)
            for property_name, child in mapping_entries(obj.value.get("properties")):
                pointer = f"{obj.pointer}/properties/{pointer_escape(property_name)}"
                type_name = python_type(binding, child, pointer)
                if property_name not in required:
                    type_name = f"NotRequired[{type_name}]"
                fields.append(f"    {json.dumps(property_name)}: {type_name},")
            lines.extend(
                [
                    f"{obj.name} = TypedDict(",
                    f"    {json.dumps(obj.name)},",
                    "    {",
                    *fields,
                    "    },",
                    ")",
                    "",
                ]
            )
    lines.extend(
        [
            f"_SCHEMA_TEXT: Final[dict[str, str]] = {serialized_sources}",
            f"_FIXTURES: Final[dict[str, dict[str, str]]] = {serialized_fixtures}",
            "",
            "",
            "@lru_cache(maxsize=None)",
            "def _validator(family: str) -> Draft202012Validator:",
            "    try:",
            "        schema = json.loads(_SCHEMA_TEXT[family])",
            "    except KeyError as error:",
            '        raise ValueError(f"unknown schema family: {family}") from error',
            "    Draft202012Validator.check_schema(schema)",
            "    return Draft202012Validator(schema, format_checker=FormatChecker())",
            "",
            "",
            "def validate_document(family: str, document: object) -> None:",
            '    """Validate a document against the authoritative Draft 2020-12 schema."""',
            "    _validator(family).validate(document)",
            "",
            "",
            "def assert_fixture_conformance() -> None:",
            '    """Execute every positive and negative governed fixture."""',
            "    for family, fixture in _FIXTURES.items():",
            '        validate_document(family, json.loads(fixture["positive"]))',
            "        try:",
            '            validate_document(family, json.loads(fixture["negative"]))',
            "        except ValidationError:",
            "            continue",
            '        raise AssertionError(f"negative fixture validated: {family}")',
            "",
        ]
    )
    for binding in bindings:
        function_name = f"decode_{binding.family}"
        lines.extend(
            [
                "",
                f"def {function_name}(document: object) -> {binding.title}:",
                f'    """Validate and narrow a {binding.title} document."""',
                f'    validate_document("{binding.family}", document)',
                f"    return cast({binding.title}, document)",
            ]
        )
    lines.extend(["", "", "__all__ = ["])
    exports = [
        "assert_fixture_conformance",
        *[f"decode_{binding.family}" for binding in bindings],
        *sorted({obj.name for binding in bindings for obj in binding.objects}),
        "validate_document",
    ]
    lines.extend(f"    {json.dumps(name)}," for name in exports)
    lines.extend(["]", ""])
    return "\n".join(lines).encode("utf-8")


def go_type(binding: SchemaBinding, value: Mapping[str, object], pointer: str) -> str:
    reference, resolved = dereference(binding, value)
    if reference is not None and reference in binding.names:
        return binding.names[reference]
    if reference is not None:
        return go_type(binding, resolved, reference)
    alternatives = resolved.get("oneOf")
    if isinstance(alternatives, list):
        return "any"
    constant = resolved.get("const")
    if isinstance(constant, bool):
        return "bool"
    if isinstance(constant, int):
        return "int64"
    if isinstance(constant, float):
        return "float64"
    if isinstance(constant, str) or isinstance(resolved.get("enum"), list):
        return "string"
    value_type = resolved.get("type")
    if isinstance(value_type, list):
        return "any"
    if value_type == "string":
        return "string"
    if value_type == "integer":
        return "int64"
    if value_type == "number":
        return "float64"
    if value_type == "boolean":
        return "bool"
    if value_type == "array":
        items = resolved.get("items")
        item_type = (
            go_type(binding, cast(Mapping[str, object], items), f"{pointer}/items")
            if isinstance(items, Mapping)
            else "any"
        )
        return f"[]{item_type}"
    if is_object_schema(resolved):
        if pointer in binding.names:
            return binding.names[pointer]
        additional = resolved.get("additionalProperties")
        value_binding = (
            go_type(
                binding,
                cast(Mapping[str, object], additional),
                f"{pointer}/additionalProperties",
            )
            if isinstance(additional, Mapping)
            else "any"
        )
        return f"map[string]{value_binding}"
    return "any"


def go_optional(type_name: str) -> str:
    if type_name.startswith(("[]", "map[")) or type_name == "any":
        return type_name
    return "*" + type_name


def render_go(
    bindings: Sequence[SchemaBinding], fixtures: Mapping[str, Mapping[str, str]]
) -> bytes:
    sources = schema_source_map(bindings)
    lines = [
        f"// Code generated by {GENERATOR}. DO NOT EDIT.",
        "",
        "// Package schemav1 contains typed bindings and Draft 2020-12 validators.",
        "package schemav1",
        "",
        "import (",
        '    "encoding/json"',
        '    "fmt"',
        '    "sync"',
        '    "time"',
        "",
        '    "github.com/dlclark/regexp2"',
        '    jsonschema "github.com/santhosh-tekuri/jsonschema/v6"',
        ")",
        "",
    ]
    for binding in bindings:
        for obj in binding.objects:
            lines.append(f"// {obj.name} is generated from {binding.family}{obj.pointer[1:]}.")
            lines.append(f"type {obj.name} struct {{")
            required = required_names(obj.value)
            for property_name, child in mapping_entries(obj.value.get("properties")):
                pointer = f"{obj.pointer}/properties/{pointer_escape(property_name)}"
                type_name = go_type(binding, child, pointer)
                tag = property_name
                if property_name not in required:
                    type_name = go_optional(type_name)
                    tag += ",omitempty"
                lines.append(
                    f"    {pascal_case(property_name)} {type_name} `json:{json.dumps(tag)}`"
                )
            lines.extend(["}", ""])
    lines.extend(
        [
            "var schemaSources = map[string]string{",
            *[f"    {json.dumps(family)}: `{source}`," for family, source in sources.items()],
            "}",
            "",
            "var schemaCache = struct {",
            "    sync.Mutex",
            "    values map[string]*jsonschema.Schema",
            "}{values: make(map[string]*jsonschema.Schema)}",
            "",
            "type ecmaRegexp regexp2.Regexp",
            "",
            "func (expression *ecmaRegexp) MatchString(value string) bool {",
            "    matched, err := (*regexp2.Regexp)(expression).MatchString(value)",
            "    return err == nil && matched",
            "}",
            "",
            "func (expression *ecmaRegexp) String() string {",
            "    return (*regexp2.Regexp)(expression).String()",
            "}",
            "",
            "func compileECMARegexp(pattern string) (jsonschema.Regexp, error) {",
            "    expression, err := regexp2.Compile(pattern, regexp2.ECMAScript)",
            "    if err != nil {",
            "        return nil, err",
            "    }",
            "    expression.MatchTimeout = 250 * time.Millisecond",
            "    return (*ecmaRegexp)(expression), nil",
            "}",
            "",
            "func compiledSchema(family string) (*jsonschema.Schema, error) {",
            "    source, ok := schemaSources[family]",
            "    if !ok {",
            '        return nil, fmt.Errorf("unknown schema family %q", family)',
            "    }",
            "    schemaCache.Lock()",
            "    defer schemaCache.Unlock()",
            "    if cached := schemaCache.values[family]; cached != nil {",
            "        return cached, nil",
            "    }",
            "    var document any",
            "    if err := json.Unmarshal([]byte(source), &document); err != nil {",
            '        return nil, fmt.Errorf("decode schema %q: %w", family, err)',
            "    }",
            '    identifier := fmt.Sprintf("https://mindclade.dev/generated-schemas/%s", family)',
            "    compiler := jsonschema.NewCompiler()",
            "    compiler.DefaultDraft(jsonschema.Draft2020)",
            "    compiler.AssertFormat()",
            "    compiler.UseRegexpEngine(compileECMARegexp)",
            "    if err := compiler.AddResource(identifier, document); err != nil {",
            '        return nil, fmt.Errorf("register schema %q: %w", family, err)',
            "    }",
            "    compiled, err := compiler.Compile(identifier)",
            "    if err != nil {",
            '        return nil, fmt.Errorf("compile schema %q: %w", family, err)',
            "    }",
            "    schemaCache.values[family] = compiled",
            "    return compiled, nil",
            "}",
            "",
            "// ValidateDocument validates canonical JSON against a governed schema family.",
            "func ValidateDocument(family string, content []byte) error {",
            "    compiled, err := compiledSchema(family)",
            "    if err != nil {",
            "        return err",
            "    }",
            "    var document any",
            "    if err := json.Unmarshal(content, &document); err != nil {",
            '        return fmt.Errorf("decode %q document: %w", family, err)',
            "    }",
            "    if err := compiled.Validate(document); err != nil {",
            '        return fmt.Errorf("validate %q document: %w", family, err)',
            "    }",
            "    return nil",
            "}",
            "",
            "func decodeDocument(family string, content []byte, destination any) error {",
            "    if err := ValidateDocument(family, content); err != nil {",
            "        return err",
            "    }",
            "    if err := json.Unmarshal(content, destination); err != nil {",
            '        return fmt.Errorf("decode typed %q document: %w", family, err)',
            "    }",
            "    return nil",
            "}",
            "",
        ]
    )
    for binding in bindings:
        lines.extend(
            [
                f"// Decode{binding.title} validates and decodes a {binding.title}.",
                f"func Decode{binding.title}(content []byte) ({binding.title}, error) {{",
                f"    var result {binding.title}",
                f'    err := decodeDocument("{binding.family}", content, &result)',
                "    return result, err",
                "}",
                "",
            ]
        )
    lines.extend(
        [
            "var fixtureSources = map[string][2]string{",
            *[
                f"    {json.dumps(family)}: {{`{value['positive']}`, `{value['negative']}`}},"
                for family, value in fixtures.items()
            ],
            "}",
            "",
            "// AssertFixtureConformance executes every governed positive and negative fixture.",
            "func AssertFixtureConformance() error {",
            "    for family, fixture := range fixtureSources {",
            "        if err := ValidateDocument(family, []byte(fixture[0])); err != nil {",
            '            return fmt.Errorf("positive fixture %q: %w", family, err)',
            "        }",
            "        if err := ValidateDocument(family, []byte(fixture[1])); err == nil {",
            '            return fmt.Errorf("negative fixture unexpectedly validated: %s", family)',
            "        }",
            "        var err error",
            "        switch family {",
        ]
    )
    for binding in bindings:
        lines.extend(
            [
                f'        case "{binding.family}":',
                f"            _, err = Decode{binding.title}([]byte(fixture[0]))",
            ]
        )
    lines.extend(
        [
            "        default:",
            '            return fmt.Errorf("fixture has no generated binding: %s", family)',
            "        }",
            "        if err != nil {",
            '            return fmt.Errorf("typed fixture %q: %w", family, err)',
            "        }",
            "    }",
            "    return nil",
            "}",
            "",
        ]
    )
    return "\n".join(lines).encode("utf-8")


def render_go_test() -> bytes:
    return (
        f"// Code generated by {GENERATOR}. DO NOT EDIT.\n\n"
        "package schemav1\n\n"
        'import "testing"\n\n'
        "func TestAllGovernedFixturesConform(t *testing.T) {\n"
        "\tt.Helper()\n"
        "\tif err := AssertFixtureConformance(); err != nil {\n"
        "\t\tt.Fatal(err)\n"
        "\t}\n"
        "}\n"
    ).encode()


def render_go_build() -> bytes:
    return (
        b"# Code generated by mindclade-schema-codegen. DO NOT EDIT.\n\n"
        b'load("@rules_go//go:def.bzl", "go_library", "go_test")\n\n'
        b"go_library(\n"
        b'    name = "bindings",\n'
        b'    srcs = ["bindings.generated.go"],\n'
        b'    importpath = "github.com/mindclade/mindclade/protocols/generated/go/schema/v1",\n'
        b'    visibility = ["//visibility:public"],\n'
        b"    deps = [\n"
        b'        "@com_github_dlclark_regexp2//:regexp2",\n'
        b'        "@com_github_santhosh_tekuri_jsonschema_v6//:jsonschema",\n'
        b"    ],\n"
        b")\n\n"
        b"go_test(\n"
        b'    name = "bindings_test",\n'
        b'    srcs = ["bindings_generated_test.go"],\n'
        b'    embed = [":bindings"],\n'
        b")\n\n"
        b"filegroup(\n"
        b'    name = "generated_sources",\n'
        b"    srcs = [\n"
        b'        "BUILD.bazel",\n'
        b'        "bindings.generated.go",\n'
        b'        "bindings_generated_test.go",\n'
        b"    ],\n"
        b'    visibility = ["//visibility:public"],\n'
        b")\n"
    )


RUST_KEYWORDS = frozenset(
    {
        "as",
        "break",
        "const",
        "continue",
        "crate",
        "else",
        "enum",
        "extern",
        "false",
        "fn",
        "for",
        "if",
        "impl",
        "in",
        "let",
        "loop",
        "match",
        "mod",
        "move",
        "mut",
        "pub",
        "ref",
        "return",
        "self",
        "Self",
        "static",
        "struct",
        "super",
        "trait",
        "true",
        "type",
        "unsafe",
        "use",
        "where",
        "while",
        "async",
        "await",
        "dyn",
    }
)


def rust_identifier(value: str) -> str:
    identifier = re.sub(r"[^a-zA-Z0-9_]", "_", value)
    if not identifier or identifier[0].isdigit():
        identifier = "value_" + identifier
    if identifier in RUST_KEYWORDS:
        identifier += "_"
    return identifier


def rust_type(binding: SchemaBinding, value: Mapping[str, object], pointer: str) -> str:
    reference, resolved = dereference(binding, value)
    if reference is not None and reference in binding.names:
        return binding.names[reference]
    if reference is not None:
        return rust_type(binding, resolved, reference)
    alternatives = resolved.get("oneOf")
    if isinstance(alternatives, list):
        return "serde_json::Value"
    constant = resolved.get("const")
    if isinstance(constant, bool):
        return "bool"
    if isinstance(constant, int):
        return "i64"
    if isinstance(constant, float):
        return "f64"
    if isinstance(constant, str) or isinstance(resolved.get("enum"), list):
        return "String"
    value_type = resolved.get("type")
    if isinstance(value_type, list):
        return "serde_json::Value"
    if value_type == "string":
        return "String"
    if value_type == "integer":
        return "i64"
    if value_type == "number":
        return "f64"
    if value_type == "boolean":
        return "bool"
    if value_type == "array":
        items = resolved.get("items")
        item_type = (
            rust_type(binding, cast(Mapping[str, object], items), f"{pointer}/items")
            if isinstance(items, Mapping)
            else "serde_json::Value"
        )
        return f"Vec<{item_type}>"
    if is_object_schema(resolved):
        if pointer in binding.names:
            return binding.names[pointer]
        additional = resolved.get("additionalProperties")
        value_binding = (
            rust_type(
                binding,
                cast(Mapping[str, object], additional),
                f"{pointer}/additionalProperties",
            )
            if isinstance(additional, Mapping)
            else "serde_json::Value"
        )
        return f"BTreeMap<String, {value_binding}>"
    return "serde_json::Value"


def render_rust(
    bindings: Sequence[SchemaBinding], fixtures: Mapping[str, Mapping[str, str]]
) -> bytes:
    sources = schema_source_map(bindings)
    lines = [
        f"// Code generated by {GENERATOR}. DO NOT EDIT.",
        "",
        "use std::collections::BTreeMap;",
        "use std::error::Error;",
        "use std::fmt::{Display, Formatter};",
        "",
        "use serde::{Deserialize, Serialize};",
        "",
    ]
    for binding in bindings:
        for obj in binding.objects:
            lines.extend(
                [
                    f"/// Generated from `{binding.family}{obj.pointer[1:]}`.",
                    "#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]",
                ]
            )
            if obj.value.get("additionalProperties") is False:
                lines.append("#[serde(deny_unknown_fields)]")
            lines.append(f"pub struct {obj.name} {{")
            required = required_names(obj.value)
            for property_name, child in mapping_entries(obj.value.get("properties")):
                pointer = f"{obj.pointer}/properties/{pointer_escape(property_name)}"
                type_name = rust_type(binding, child, pointer)
                field_name = rust_identifier(property_name)
                lines.append(f"    #[serde(rename = {json.dumps(property_name)})]")
                if property_name not in required:
                    lines.append('    #[serde(default, skip_serializing_if = "Option::is_none")]')
                    type_name = f"Option<{type_name}>"
                lines.append(f"    pub {field_name}: {type_name},")
            lines.extend(["}", ""])
    lines.extend(
        [
            "/// Errors returned by generated schema validation and decoding.",
            "#[derive(Clone, Debug, Eq, PartialEq)]",
            "pub enum SchemaError {",
            "    UnknownFamily(String),",
            "    InvalidSchema(String),",
            "    InvalidDocument(String),",
            "    Decode(String),",
            "}",
            "",
            "impl Display for SchemaError {",
            "    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {",
            "        match self {",
            (
                "            Self::UnknownFamily(value) => write!(formatter, "
                '"unknown schema family: {value}"),'
            ),
            (
                "            Self::InvalidSchema(value) => write!(formatter, "
                '"invalid schema: {value}"),'
            ),
            (
                "            Self::InvalidDocument(value) => write!(formatter, "
                '"invalid document: {value}"),'
            ),
            (
                "            Self::Decode(value) => write!(formatter, "
                '"document decode failed: {value}"),'
            ),
            "        }",
            "    }",
            "}",
            "",
            "impl Error for SchemaError {}",
            "",
            "fn schema_source(family: &str) -> Option<&'static str> {",
            "    match family {",
            *[
                f'        "{family}" => Some(r###"{source}"###),'
                for family, source in sources.items()
            ],
            "        _ => None,",
            "    }",
            "}",
            "",
            "/// Validates a document against an authoritative Draft 2020-12 schema.",
            "pub fn validate_document(",
            "    family: &str,",
            "    document: &serde_json::Value,",
            ") -> Result<(), SchemaError> {",
            "    let source = schema_source(family)",
            "        .ok_or_else(|| SchemaError::UnknownFamily(family.to_owned()))?;",
            "    let schema: serde_json::Value = serde_json::from_str(source)",
            "        .map_err(|error| SchemaError::InvalidSchema(error.to_string()))?;",
            "    let validator = jsonschema::draft202012::options()",
            "        .should_validate_formats(true)",
            "        .build(&schema)",
            "        .map_err(|error| SchemaError::InvalidSchema(error.to_string()))?;",
            "    validator",
            "        .validate(document)",
            "        .map_err(|error| SchemaError::InvalidDocument(error.to_string()))",
            "}",
            "",
            "fn decode_document<T>(family: &str, content: &[u8]) -> Result<T, SchemaError>",
            "where",
            "    T: serde::de::DeserializeOwned,",
            "{",
            "    let document: serde_json::Value = serde_json::from_slice(content)",
            "        .map_err(|error| SchemaError::Decode(error.to_string()))?;",
            "    validate_document(family, &document)?;",
            (
                "    serde_json::from_value(document)"
                ".map_err(|error| SchemaError::Decode(error.to_string()))"
            ),
            "}",
            "",
        ]
    )
    for binding in bindings:
        lines.extend(
            [
                f"/// Validates and decodes a [`{binding.title}`].",
                (
                    f"pub fn decode_{binding.family}(content: &[u8]) "
                    f"-> Result<{binding.title}, SchemaError> {{"
                ),
                f'    decode_document("{binding.family}", content)',
                "}",
                "",
            ]
        )
    lines.extend(
        [
            "fn fixture_source(family: &str) -> Option<(&'static str, &'static str)> {",
            "    match family {",
            *[
                (
                    f'        "{family}" => Some((r###"{value["positive"]}"###, '
                    f'r###"{value["negative"]}"###)),'
                )
                for family, value in fixtures.items()
            ],
            "        _ => None,",
            "    }",
            "}",
            "",
            "/// Executes every governed positive and negative fixture.",
            "pub fn assert_fixture_conformance() -> Result<(), SchemaError> {",
            "    for family in [",
            *[f'        "{binding.family}",' for binding in bindings],
            "    ] {",
            "        let (positive, negative) = fixture_source(family)",
            "            .ok_or_else(|| SchemaError::UnknownFamily(family.to_owned()))?;",
            "        let positive_value: serde_json::Value = serde_json::from_str(positive)",
            "            .map_err(|error| SchemaError::Decode(error.to_string()))?;",
            "        validate_document(family, &positive_value)?;",
            "        let negative_value: serde_json::Value = serde_json::from_str(negative)",
            "            .map_err(|error| SchemaError::Decode(error.to_string()))?;",
            "        if validate_document(family, &negative_value).is_ok() {",
            "            return Err(SchemaError::InvalidDocument(format!(",
            '                "negative fixture unexpectedly validated: {family}"',
            "            )));",
            "        }",
            "        match family {",
        ]
    )
    for binding in bindings:
        lines.extend(
            [
                f'            "{binding.family}" => {{',
                f"                decode_{binding.family}(positive.as_bytes()).map(|_| ())?;",
                "            }",
            ]
        )
    lines.extend(
        [
            "            _ => return Err(SchemaError::UnknownFamily(family.to_owned())),",
            "        }",
            "    }",
            "    Ok(())",
            "}",
            "",
            "#[cfg(test)]",
            "mod tests {",
            "    #[test]",
            "    fn all_governed_fixtures_conform() {",
            '        super::assert_fixture_conformance().expect("schema fixtures must conform");',
            "    }",
            "}",
            "",
        ]
    )
    return "\n".join(lines).encode("utf-8")


def typescript_type(binding: SchemaBinding, value: Mapping[str, object], pointer: str) -> str:
    reference, resolved = dereference(binding, value)
    if reference is not None and reference in binding.names:
        return binding.names[reference]
    if reference is not None:
        return typescript_type(binding, resolved, reference)
    alternatives = resolved.get("oneOf")
    if isinstance(alternatives, list):
        members = [
            typescript_type(
                binding,
                cast(Mapping[str, object], item),
                f"{pointer}/oneOf/{index}",
            )
            for index, item in enumerate(cast(list[object], alternatives))
            if isinstance(item, Mapping)
        ]
        return " | ".join(members) if members else "unknown"
    if "const" in resolved:
        return json.dumps(resolved["const"], ensure_ascii=True)
    enum = resolved.get("enum")
    if isinstance(enum, list) and enum:
        return " | ".join(json.dumps(item, ensure_ascii=True) for item in cast(list[object], enum))
    value_type = resolved.get("type")
    if isinstance(value_type, list):
        members = [
            typescript_type(binding, {"type": item}, pointer)
            for item in cast(list[object], value_type)
            if isinstance(item, str)
        ]
        return " | ".join(members) if members else "unknown"
    if value_type == "string":
        return "string"
    if value_type in {"integer", "number"}:
        return "number"
    if value_type == "boolean":
        return "boolean"
    if value_type == "array":
        items = resolved.get("items")
        item_type = (
            typescript_type(binding, cast(Mapping[str, object], items), f"{pointer}/items")
            if isinstance(items, Mapping)
            else "unknown"
        )
        return f"Array<{item_type}>"
    if is_object_schema(resolved):
        if pointer in binding.names:
            return binding.names[pointer]
        additional = resolved.get("additionalProperties")
        value_binding = (
            typescript_type(
                binding,
                cast(Mapping[str, object], additional),
                f"{pointer}/additionalProperties",
            )
            if isinstance(additional, Mapping)
            else "unknown"
        )
        return f"Record<string, {value_binding}>"
    return "unknown"


def render_typescript(
    bindings: Sequence[SchemaBinding], fixtures: Mapping[str, Mapping[str, str]]
) -> bytes:
    sources = schema_source_map(bindings)
    serialized_sources = json.dumps(sources, sort_keys=True, indent=2)
    serialized_fixtures = json.dumps(fixtures, sort_keys=True, indent=2)
    lines = [
        f"// Code generated by {GENERATOR}. DO NOT EDIT.",
        "",
        'import { Ajv2020, type ValidateFunction } from "ajv/dist/2020.js";',
        'import * as formatsModule from "ajv-formats";',
        "",
    ]
    for binding in bindings:
        for obj in binding.objects:
            lines.append(f"/** Generated from {binding.family}{obj.pointer[1:]}. */")
            lines.append(f"export interface {obj.name} {{")
            required = required_names(obj.value)
            for property_name, child in mapping_entries(obj.value.get("properties")):
                pointer = f"{obj.pointer}/properties/{pointer_escape(property_name)}"
                type_name = typescript_type(binding, child, pointer)
                optional = "" if property_name in required else "?"
                lines.append(f"  {json.dumps(property_name)}{optional}: {type_name};")
            lines.extend(["}", ""])
    families = " | ".join(json.dumps(binding.family) for binding in bindings)
    lines.extend(
        [
            f"export type SchemaFamily = {families};",
            "",
            "export interface SchemaDocuments {",
            *[f"  {json.dumps(binding.family)}: {binding.title};" for binding in bindings],
            "}",
            "",
            f"const schemaText: Readonly<Record<SchemaFamily, string>> = {serialized_sources};",
            (
                "const fixtures: Readonly<Record<SchemaFamily, "
                "Readonly<{ positive: string; negative: string }>>> = "
                f"{serialized_fixtures};"
            ),
            "",
            "const ajv = new Ajv2020({ allErrors: true, allowUnionTypes: true, strict: true });",
            (
                "const installFormats = formatsModule.default as unknown as "
                "(instance: Ajv2020) => Ajv2020;"
            ),
            "installFormats(ajv);",
            "const validators = new Map<SchemaFamily, ValidateFunction>();",
            "",
            "const validatorFor = (family: SchemaFamily): ValidateFunction => {",
            "  const cached = validators.get(family);",
            "  if (cached !== undefined) return cached;",
            "  const validator = ajv.compile(JSON.parse(schemaText[family]));",
            "  validators.set(family, validator);",
            "  return validator;",
            "};",
            "",
            "/** Validate a document against an authoritative Draft 2020-12 schema. */",
            "export const validateDocument = (family: SchemaFamily, document: unknown): void => {",
            "  const validator = validatorFor(family);",
            "  if (!validator(document)) {",
            '    throw new Error(ajv.errorsText(validator.errors, { separator: "; " }));',
            "  }",
            "};",
            "",
            "/** Validate and narrow a document to its generated schema binding. */",
            "export const decodeDocument = <Family extends SchemaFamily>(",
            "  family: Family,",
            "  document: unknown,",
            "): SchemaDocuments[Family] => {",
            "  validateDocument(family, document);",
            "  return document as SchemaDocuments[Family];",
            "};",
            "",
            "/** Execute every governed positive and negative fixture. */",
            "export const assertFixtureConformance = (): void => {",
            "  for (const family of Object.keys(fixtures) as SchemaFamily[]) {",
            "    decodeDocument(family, JSON.parse(fixtures[family].positive));",
            "    let rejected = false;",
            "    try {",
            "      validateDocument(family, JSON.parse(fixtures[family].negative));",
            "    } catch {",
            "      rejected = true;",
            "    }",
            (
                "    if (!rejected) throw new Error("
                "`negative fixture unexpectedly validated: ${family}`);"
            ),
            "  }",
            "};",
            "",
        ]
    )
    return "\n".join(lines).encode("utf-8")


def generated_binding_outputs(root: Path) -> dict[Path, bytes]:
    """Return deterministic generated schema bindings for all four languages."""

    toolchain = load_object(root / TOOLCHAIN_LOCK)
    tools = toolchain.get("tools")
    if not isinstance(tools, Mapping):
        raise CatalogError(f"{TOOLCHAIN_LOCK} has no tools object")
    rustfmt = cast(Mapping[str, object], tools).get("rustfmt")
    if not isinstance(rustfmt, Mapping):
        raise CatalogError(f"{TOOLCHAIN_LOCK} has no pinned rustfmt")
    rustfmt_version_output = cast(Mapping[str, object], rustfmt).get("version_output")
    if not isinstance(rustfmt_version_output, str):
        raise CatalogError(f"{TOOLCHAIN_LOCK} has no pinned rustfmt")
    rustfmt_version = subprocess.run(
        ["rustfmt", "--version"],
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    ).stdout.strip()
    if rustfmt_version != rustfmt_version_output:
        raise CatalogError(
            "rustfmt version mismatch: "
            f"expected {rustfmt_version_output!r}, got {rustfmt_version!r}"
        )

    bindings = schema_bindings(root)
    fixtures = fixture_source_map(root, bindings)
    go_source = render_go(bindings, fixtures)
    formatted_go = subprocess.run(
        ["gofmt"],
        check=True,
        input=go_source,
        stdout=subprocess.PIPE,
    ).stdout
    go_test = subprocess.run(
        ["gofmt"],
        check=True,
        input=render_go_test(),
        stdout=subprocess.PIPE,
    ).stdout
    rust_source = subprocess.run(
        ["rustfmt", "--emit", "stdout", "--edition", "2024"],
        check=True,
        input=render_rust(bindings, fixtures),
        stdout=subprocess.PIPE,
    ).stdout
    return {
        root / GO_BINDING: formatted_go,
        root / GO_BINDING_TEST: go_test,
        root / GO_BUILD: render_go_build(),
        root / PYTHON_BINDING: render_python(bindings, fixtures),
        root / PYTHON_INIT: (
            f"# Code generated by {GENERATOR}. DO NOT EDIT.\n"
            "from .bindings import *  # noqa: F403\n"
        ).encode(),
        root / RUST_BINDING: rust_source,
        root / TYPESCRIPT_BINDING: render_typescript(bindings, fixtures),
    }


def write_binding_outputs(root: Path, outputs: Mapping[Path, bytes]) -> None:
    for path, content in sorted(outputs.items()):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)


def check_binding_outputs(outputs: Mapping[Path, bytes]) -> list[Path]:
    return [
        path
        for path, expected in sorted(outputs.items())
        if not path.is_file() or path.read_bytes() != expected
    ]


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
    action.add_argument("--generate", action="store_true")
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
        outputs = generated_binding_outputs(root)
        if args.promote_baseline:
            promote_baseline(root, expected, args.expected_baseline_digest)
            catalog = cast(dict[str, object], baseline_document(root)["catalog"])
            print(f"promoted {BASELINE_PATH} ({len(catalog)} families)")
            return 0
        if not check_baseline(root, expected):
            print(f"stale {BASELINE_PATH}", file=sys.stderr)
            return 1
        if args.generate:
            write_binding_outputs(root, outputs)
        else:
            stale_bindings = check_binding_outputs(outputs)
            if stale_bindings:
                paths = ", ".join(str(path.relative_to(root)) for path in stale_bindings)
                print(f"stale generated schema bindings: {paths}", file=sys.stderr)
                return 1
        catalog = cast(dict[str, object], baseline_document(root)["catalog"])
        action_name = "generated" if args.generate else "validated"
        print(
            f"{action_name} {BASELINE_PATH} and schema bindings "
            f"({len(catalog)} families, {len(outputs)} files)"
        )
        return 0
    except CatalogError as error:
        print(error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
