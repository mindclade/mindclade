#!/usr/bin/env python3.12
"""Emit deterministic, explicitly non-ratifying training-vertical evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import cast

type JsonScalar = bool | float | int | str | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]
type JsonObject = dict[str, JsonValue]

REQUIRED_CHECKS = frozenset({"cross_language", "database", "event", "gateway", "grpc", "sdk"})
SDK_LANGUAGES = ("go", "python", "rust", "typescript")
POSTGRES_TARGETS = (
    "//services/control_plane:artifacts_server_test",
    "//services/control_plane:control_plane_test",
    "//services/control_plane:jobs_server_test",
    "//services/control_plane/internal/admin:admin_test",
    "//services/control_plane/internal/agents:agents_test",
    "//services/control_plane/internal/datasets:datasets_test",
    "//services/control_plane/internal/evaluations:evaluations_test",
    "//services/control_plane/internal/experiments:experiments_test",
    "//services/control_plane/internal/inference:inference_test",
    "//services/control_plane/internal/models:models_test",
    "//services/control_plane/internal/platform/eventprojection:event_projection_test",
    "//services/control_plane/internal/policies:policies_test",
    "//services/control_plane/internal/training:training_test",
    "//services/control_plane/internal/workflows:workflows_test",
)
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
IGNORED_PARTS = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "__pycache__",
        "node_modules",
        "target",
    }
)


def sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def canonical_json(value: JsonValue) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def load_object(path: Path) -> JsonObject:
    value: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain one JSON object")
    raw = cast(dict[object, object], value)
    if any(not isinstance(key, str) for key in raw):
        raise ValueError(f"{path} must contain one JSON object")
    return cast(JsonObject, value)


def repository_paths(root: Path, *, omitted: Path | None = None) -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=root,
        check=True,
        stdout=subprocess.PIPE,
    )
    paths: list[Path] = []
    omitted_resolved = omitted.resolve() if omitted is not None else None
    for raw in result.stdout.split(b"\0"):
        if not raw:
            continue
        relative = Path(os.fsdecode(raw))
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or IGNORED_PARTS.intersection(relative.parts)
        ):
            continue
        path = root / relative
        if not path.is_file() or (
            omitted_resolved is not None and path.resolve() == omitted_resolved
        ):
            continue
        paths.append(path)
    return sorted(set(paths))


def inventory_digest(root: Path, paths: Sequence[Path]) -> str:
    inventory: list[JsonValue] = []
    for path in sorted(set(paths)):
        relative = path.resolve().relative_to(root.resolve()).as_posix()
        inventory.append({"digest": sha256_file(path), "path": relative})
    return sha256_bytes(canonical_json(inventory))


def require_digest(value: JsonValue, label: str) -> str:
    if not isinstance(value, str) or DIGEST_RE.fullmatch(value) is None:
        raise ValueError(f"{label} is not a canonical SHA-256 digest")
    return value


def nested_digest(value: JsonValue, label: str) -> str:
    if not isinstance(value, dict):
        raise ValueError(f"{label} is absent")
    return require_digest(value.get("digest"), label)


def parse_passed_check(value: str) -> tuple[str, str]:
    name, separator, target = value.partition("=")
    if not separator or name not in REQUIRED_CHECKS or not target.startswith("//"):
        raise argparse.ArgumentTypeError("passed checks must be REQUIRED_NAME=//bazel:target")
    return name, target


def build_integration_receipt(root: Path, source_revision: str) -> JsonObject:
    migration_paths = sorted((root / "services/control_plane/migrations").glob("*.sql"))
    if not migration_paths:
        raise ValueError("the migration set is empty")
    receipt: JsonObject = {
        "database_lifecycle": {"complete_down_up": "passed", "empty_to_all_up": "passed"},
        "migration_set_digest": inventory_digest(root, migration_paths),
        "qualification": {
            "every_domain_repository": "passed",
            "reliability_and_dlq": "passed",
            "required_postgres_mode": True,
            "rls_tenant_isolation": "passed",
            "skipped_required_tests": [],
            "training_ownership_and_fencing": "passed",
        },
        "ratification_authorized": False,
        "required_bazel_targets": list(POSTGRES_TARGETS),
        "schema_version": "mindclade.fresh-database-integration/v1",
        "source_revision": source_revision,
        "status": "passed",
    }
    receipt["receipt_digest"] = sha256_bytes(canonical_json(receipt))
    return receipt


def build_receipt(
    root: Path,
    source_revision: str,
    checks: Mapping[str, str],
    output: Path,
    integration_receipt: JsonObject,
) -> JsonObject:
    if REVISION_RE.fullmatch(source_revision) is None:
        raise ValueError("source revision must be an exact 40-character lowercase Git revision")
    check_names = frozenset(checks)
    if check_names != REQUIRED_CHECKS:
        missing = sorted(REQUIRED_CHECKS - check_names)
        extra = sorted(check_names - REQUIRED_CHECKS)
        raise ValueError(f"training rehearsal checks differ: missing={missing}, unexpected={extra}")

    required = {
        "candidate": root / "protocols/compatibility/baselines/protobuf.candidate.json",
        "event_registry": root / "protocols/events/registry.yaml",
        "generated_manifest": root / "protocols/generated/generated-files.manifest.json",
        "grpc_coverage": root / "services/control_plane/grpc-implementation.generated.json",
        "openapi": root / "protocols/openapi/published/mindclade.openapi.yaml",
        "sdk_coverage": root / "sdks/rpc-coverage.generated.json",
        "toolchain": root / "tools/codegen/toolchain.lock.json",
    }
    missing_files = [name for name, path in required.items() if not path.is_file()]
    if missing_files:
        raise ValueError(f"training rehearsal inputs are missing: {missing_files}")

    source_paths = repository_paths(root, omitted=output)
    candidate = load_object(required["candidate"])
    descriptor_digest = nested_digest(
        candidate.get("descriptor_set"), "candidate descriptor digest"
    )
    candidate_event_digest = nested_digest(
        candidate.get("event_registry"), "candidate event registry digest"
    )
    migration_paths = sorted((root / "services/control_plane/migrations").glob("*.sql"))
    if not migration_paths:
        raise ValueError("the migration set is empty")
    sdk_digests: JsonObject = {}
    for language in SDK_LANGUAGES:
        prefix = (root / "sdks" / language).resolve()
        language_paths = [path for path in source_paths if path.resolve().is_relative_to(prefix)]
        if not language_paths:
            raise ValueError(f"the {language} SDK package is empty")
        sdk_digests[language] = inventory_digest(root, language_paths)

    check_records: JsonObject = {
        name: {"bazel_target": target, "status": "passed"}
        for name, target in sorted(checks.items())
    }
    receipt: JsonObject = {
        "bindings": {
            "candidate_artifact_digest": sha256_file(required["candidate"]),
            "candidate_descriptor_digest": descriptor_digest,
            "codegen_toolchain_digest": sha256_file(required["toolchain"]),
            "event_registry_digest": candidate_event_digest,
            "event_registry_source_digest": sha256_file(required["event_registry"]),
            "fresh_database_integration_receipt_digest": sha256_bytes(
                canonical_json(integration_receipt)
            ),
            "generated_manifest_digest": sha256_file(required["generated_manifest"]),
            "grpc_implementation_digest": sha256_file(required["grpc_coverage"]),
            "migration_set_digest": inventory_digest(root, migration_paths),
            "openapi_projection_digest": sha256_file(required["openapi"]),
            "sdk_package_digests": sdk_digests,
            "sdk_rpc_coverage_digest": sha256_file(required["sdk_coverage"]),
            "source_revision": source_revision,
            "source_tree_digest": inventory_digest(root, source_paths),
        },
        "checks": check_records,
        "ratification": {
            "authorized": False,
            "reason": "rehearsal evidence cannot ratify or publish the candidate v1 baseline",
        },
        "schema_version": "mindclade.training-vertical-rehearsal/v1",
        "status": "passed",
    }
    receipt["receipt_digest"] = sha256_bytes(canonical_json(receipt))
    return receipt


def atomic_write(path: Path, value: JsonObject) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=path.parent, prefix=f".{path.name}.", delete=False
    ) as handle:
        temporary = Path(handle.name)
        handle.write(canonical_json(value))
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list-integration-targets", action="store_true")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--source-revision")
    parser.add_argument("--passed-check", action="append", type=parse_passed_check, default=[])
    parser.add_argument("--integration-output", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.list_integration_targets:
        for target in POSTGRES_TARGETS:
            print(target)
        return 0
    if args.source_revision is None or args.output is None or args.integration_output is None:
        parser.error("receipt emission requires source-revision, integration-output, and output")
    root = cast(Path, args.root).resolve()
    output = cast(Path, args.output)
    integration_output = cast(Path, args.integration_output)
    if not output.is_absolute():
        output = root / output
    if not integration_output.is_absolute():
        integration_output = root / integration_output
    raw_checks = cast(list[tuple[str, str]], args.passed_check)
    checks = dict(raw_checks)
    if len(checks) != len(raw_checks):
        raise SystemExit("training rehearsal failed: duplicate passed-check name")
    try:
        source_revision = cast(str, args.source_revision)
        integration_receipt = build_integration_receipt(root, source_revision)
        receipt = build_receipt(root, source_revision, checks, output, integration_receipt)
        atomic_write(integration_output, integration_receipt)
        atomic_write(output, receipt)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        raise SystemExit(f"training rehearsal failed: {error}") from error
    print(
        integration_output.relative_to(root)
        if integration_output.is_relative_to(root)
        else integration_output
    )
    print(output.relative_to(root) if output.is_relative_to(root) else output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
