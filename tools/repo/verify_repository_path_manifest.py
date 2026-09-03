#!/usr/bin/env python3.12
"""Run schema, path, owner, graph, generated-file, and target checks."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

from build_graph import target_sources as read_target_sources
from dependency_policy import validate_dependency_graph
from owner_policy import discover_components, validate_owners
from path_policy import (
    OPTIONAL_PENDING_RATIFICATION_ARTIFACT_PATHS,
    load_manifest,
    validate_manifest,
    validate_populated_paths,
)

GENERATED_MARKERS = ("generated", "do not edit", "begin generated: repository-path-manifest")

# Every generated family, and the gate that proves it matches its generator.
#
# This is an explicit map because `source_authority` cannot supply one: it is
# perfectly correlated with `status` and therefore carries no information, and
# validate_generated_files only checks that `reviewed-generated` entries HAVE a
# marker -- never that `hand-authored` entries lack one. A covered set derived from
# that field looks rigorous and misses the path manifest itself, NOTICE, and the
# cross-field constraint source, all of which are generator outputs labelled
# hand-authored.
#
# Longest prefix wins, so a more specific family may precede a broader one.
REGENERATION_GATES: tuple[tuple[str, str], ...] = (
    (
        "docs/architecture/repository-path-manifest.yaml",
        "tools/repo/tests: manifest reproducibility",
    ),
    ("docs/architecture/repository-drift-baseline.md", "just governance (--check)"),
    ("docs/architecture/blueprint/", "just docs: render_architecture_blueprint.py --check"),
    ("protocols/generated/", "just check-contract-drift"),
    ("protocols/openapi/", "just check-contract-drift"),
    ("protocols/compatibility/", "just check-contract-drift"),
    ("protocols/constraints/", "just check-cross-field-drift"),
    ("libs/go/pubsubx/", "just check-contract-drift"),
    ("sdks/rpc-coverage.generated.json", "just check-sdk-plan"),
    ("services/control_plane/grpc-implementation.generated.json", "just check-sdk-plan"),
    ("sdks/go/api.md", "just docs: render_sdk_api_reference.py --check"),
    ("sdks/python/api.md", "just docs: render_sdk_api_reference.py --check"),
    ("sdks/rust/api.md", "just docs: render_sdk_api_reference.py --check"),
    ("sdks/typescript/api.md", "just docs: render_sdk_api_reference.py --check"),
    ("sdks/go/mindclade/cross_field", "just check-cross-field-drift"),
    ("sdks/python/mindclade_internal_sdk/cross_field", "just check-cross-field-drift"),
    ("sdks/rust/src/cross_field", "just check-cross-field-drift"),
    ("sdks/typescript/src/crossField", "just check-cross-field-drift"),
    ("services/control_plane/internal/validation/cross_field", "just check-cross-field-drift"),
    ("third_party/notices/", "just security: generate_notices.py + cmp"),
    ("tools/repo/activation-bundles.generated.json", "tools/repo/tests: activation projection"),
)

# Generated families with no drift gate reachable from `just check`, each with the
# reason it cannot have one. An entry here records a known gap; it is not an
# approval, and nothing may be added without stating why the gate is impossible.
UNGATED_GENERATED_FAMILIES: dict[str, str] = {
    "kernels/native/generated/": (
        "kernels/native/tests/test_codegen_drift.py exists but imports torch, which the "
        "pinned source toolchain does not carry, and kernels/native/tests has no "
        "BUILD.bazel -- so no runner reaches it"
    ),
    "generated/": "vendored from mindclade/.github; no generator in this repository",
    "MODULE.bazel.lock": "produced by Bazel itself; no generator in this repository",
}


def _assert_generated_families_are_gated(manifest: Mapping[str, Any]) -> list[str]:
    """Every generated path belongs to a family whose drift gate is named.

    R11 asks that the covered set come from an explicit map. This is the assertion
    that makes the word "every" checkable: a new generated family that nobody wires
    a gate for fails here instead of being silently trusted.
    """
    generated = sorted(
        str(entry["path"])
        for entry in manifest["paths"]
        if entry.get("status") == "generated"
        or entry.get("source_authority") == "reviewed-generated"
    )
    if not generated:
        return ["no generated paths found; the regeneration-map check asserted nothing"]

    known = tuple(prefix for prefix, _ in REGENERATION_GATES) + tuple(UNGATED_GENERATED_FAMILIES)
    uncovered = sorted({path for path in generated if not path.startswith(known)})
    if uncovered:
        return [
            "generated path belongs to no family in REGENERATION_GATES and is not a "
            f"recorded gap, so nothing proves it current: {uncovered[:8]}"
        ]
    return []


def validate_generated_files(manifest: Mapping[str, Any], root: Path) -> list[str]:
    errors: list[str] = []
    for entry in manifest["paths"]:
        if entry.get("source_authority") != "reviewed-generated":
            continue
        path = root / entry["path"]
        if not path.is_file():
            continue
        if "/provenance/" in f"/{entry['path']}/":
            continue
        if entry["path"] == "MODULE.bazel.lock":
            try:
                value: object = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                errors.append("generated MODULE.bazel.lock is not valid JSON")
                continue
            if not isinstance(value, Mapping):
                errors.append("generated MODULE.bazel.lock root is not an object")
            continue
        if path.suffix == ".json":
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                value = None
            if isinstance(value, Mapping):
                value_object = cast(Mapping[str, object], value)
                structured_generator = isinstance(
                    value_object.get("generator"), Mapping
                ) or isinstance(value_object.get("x-mindclade-generator"), Mapping)
                candidate_descriptor = (
                    entry["path"] == "protocols/compatibility/baselines/protobuf.candidate.json"
                    and value_object.get("schema_version") == "mindclade.protobuf-candidate/v1"
                    and isinstance(value_object.get("lifecycle"), Mapping)
                )
                candidate_openapi = (
                    entry["path"] == "protocols/compatibility/baselines/openapi.lock.json"
                    and value_object.get("schema_version") == "mindclade.openapi-candidate/v1"
                    and isinstance(value_object.get("sources"), Mapping)
                )
                ratified_baseline = (
                    entry["path"]
                    in {
                        "protocols/compatibility/baselines/openapi.lock.json",
                        "protocols/compatibility/baselines/protobuf.lock.json",
                    }
                    and value_object.get("schema_version")
                    in {
                        "mindclade.openapi-baseline/v1",
                        "mindclade.protobuf-baseline/v3",
                    }
                    and isinstance(value_object.get("ratification"), Mapping)
                )
                if (
                    structured_generator
                    or candidate_descriptor
                    or candidate_openapi
                    or ratified_baseline
                ):
                    continue
        prefix = path.read_bytes()[:8192].decode("utf-8", errors="ignore").lower()
        if not any(marker in prefix for marker in GENERATED_MARKERS):
            errors.append(f"generated file lacks a generator marker: {entry['path']}")
    return errors


def validate_declared_targets(manifest: Mapping[str, Any], root: Path) -> list[str]:
    labels = {
        label
        for entry in manifest["paths"]
        if entry.get("status") in {"active", "generated"}
        for label in (*entry.get("build_targets", []), *entry.get("test_targets", []))
    }
    errors: list[str] = []
    target_sources: dict[str, set[str]] = {}
    for label in sorted(labels):
        match = re.fullmatch(r"//(?P<package>[^:]*):(?P<name>[A-Za-z0-9_.+-]+)", label)
        if match is None:
            errors.append(f"invalid Bazel label: {label}")
            continue
        package = match.group("package")
        build_file = root / package / "BUILD.bazel" if package else root / "BUILD.bazel"
        if not build_file.is_file():
            errors.append(f"target package has no BUILD.bazel: {label}")
            continue
        text = build_file.read_text(encoding="utf-8")
        name = re.escape(match.group("name"))
        if re.search(rf"\bname\s*=\s*[\"']{name}[\"']", text) is None:
            errors.append(f"declared target does not exist: {label}")
            continue
        sources, detail = read_target_sources(root, label)
        if detail is not None:
            errors.append(f"cannot resolve target source membership for {label}: {detail}")
            continue
        target_sources[label] = sources

    for entry in manifest["paths"]:
        if entry.get("status") not in {"active", "generated"}:
            continue
        if (
            entry["path"] in OPTIONAL_PENDING_RATIFICATION_ARTIFACT_PATHS
            and not (root / entry["path"]).is_file()
        ):
            continue
        for label in (*entry.get("build_targets", []), *entry.get("test_targets", [])):
            if label in target_sources and entry["path"] not in target_sources[label]:
                errors.append(f"{label} does not cover active path: {entry['path']}")
    return errors


def run_checks(
    root: Path,
    manifest_path: Path,
    component_schema: Path,
    *,
    allow_missing_active: bool = False,
    check_codeowners: bool = True,
    check_targets: bool = True,
) -> dict[str, Any]:
    manifest = load_manifest(manifest_path)
    errors = validate_manifest(manifest)
    drift = validate_populated_paths(manifest, root, allow_missing_active=allow_missing_active)
    for category, paths in drift.items():
        errors.extend(f"{category}: {path}" for path in paths)
    component_errors, components = discover_components(root, component_schema)
    errors.extend(component_errors)
    ownership_gaps = validate_owners(
        manifest, components, root / ".github/CODEOWNERS" if check_codeowners else None
    )
    errors.extend(f"ownership gap: {json.dumps(gap, sort_keys=True)}" for gap in ownership_gaps)
    graph_errors, edges = validate_dependency_graph(components)
    errors.extend(graph_errors)
    errors.extend(validate_generated_files(manifest, root))
    errors.extend(_assert_generated_families_are_gated(manifest))
    if check_targets:
        errors.extend(validate_declared_targets(manifest, root))
    return {
        "status": "PASS" if not errors else "FAIL",
        "errors": sorted(errors),
        "drift": drift,
        "components": components,
        "dependency_edges": edges,
        "ownership_gaps": ownership_gaps,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--component-schema", type=Path, required=True)
    parser.add_argument("--allow-missing-active", action="store_true")
    parser.add_argument("--skip-codeowners", action="store_true")
    parser.add_argument("--skip-targets", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = run_checks(
        args.root,
        args.manifest,
        args.component_schema,
        allow_missing_active=args.allow_missing_active,
        check_codeowners=not args.skip_codeowners,
        check_targets=not args.skip_targets,
    )
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    elif report["errors"]:
        print("\n".join(report["errors"]), file=sys.stderr)
    else:
        print(
            "repository governance: PASS "
            f"({len(report['components'])} components, {len(report['dependency_edges'])} edges)"
        )
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
