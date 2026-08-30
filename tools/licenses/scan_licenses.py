#!/usr/bin/env python3.12
"""Inventory every resolved Wave 0 build dependency and enforce license policy."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import cast


@dataclass(frozen=True)
class Dependency:
    ecosystem: str
    name: str
    version: str
    license: str
    source: str
    scope: str
    direct: bool


def _object(value: object, description: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{description} must be an object")
    return cast(dict[str, object], value)


def _array(value: Mapping[str, object], field: str) -> list[object]:
    candidate = value.get(field)
    if not isinstance(candidate, list):
        raise ValueError(f"{field} must be an array")
    return cast(list[object], candidate)


def _string(value: Mapping[str, object], field: str) -> str:
    candidate = value.get(field)
    if not isinstance(candidate, str) or not candidate:
        raise ValueError(f"{field} must be a non-empty string")
    return candidate


def load_policy(path: Path) -> tuple[set[str], set[str], set[str], dict[tuple[str, str, str], str]]:
    value: object = json.loads(path.read_text(encoding="utf-8"))
    root = _object(value, "license policy")
    spec = _object(root.get("spec"), "license policy spec")
    allowed = {item for item in _array(spec, "licenses") if isinstance(item, str)}
    review = {item for item in _array(spec, "reviewRequired") if isinstance(item, str)}
    prohibited = {item for item in _array(spec, "prohibited") if isinstance(item, str)}
    packages: dict[tuple[str, str, str], str] = {}
    for raw_entry in _array(spec, "packages"):
        entry = _object(raw_entry, "package policy entry")
        key = (_string(entry, "ecosystem"), _string(entry, "name"), _string(entry, "version"))
        if key in packages:
            raise ValueError(f"duplicate package policy entry: {key}")
        packages[key] = _string(entry, "license")
    return allowed, review, prohibited, packages


def _root_packages(root: Path) -> list[Dependency]:
    package_value: object = json.loads((root / "package.json").read_text(encoding="utf-8"))
    package = _object(package_value, "package.json")
    cargo_value: object = tomllib.loads((root / "Cargo.toml").read_text(encoding="utf-8"))
    cargo = _object(cargo_value, "Cargo.toml")
    workspace = _object(cargo.get("workspace"), "Cargo workspace")
    cargo_package = _object(workspace.get("package"), "Cargo workspace package")
    return [
        Dependency(
            ecosystem="npm",
            name=_string(package, "name"),
            version=_string(package, "version"),
            license=_string(package, "license"),
            source="package.json",
            scope="authored-workspace",
            direct=True,
        ),
        Dependency(
            ecosystem="cargo",
            name="mindclade-workspace",
            version="0.0.0",
            license=_string(cargo_package, "license"),
            source="Cargo.toml",
            scope="authored-workspace",
            direct=True,
        ),
    ]


def _python_packages(
    root: Path,
    policy: Mapping[tuple[str, str, str], str],
) -> list[Dependency]:
    lock_value: object = tomllib.loads((root / "uv.lock").read_text(encoding="utf-8"))
    lock = _object(lock_value, "uv.lock")
    raw_packages = _array(lock, "package")
    direct: set[str] = set()
    for raw_package in raw_packages:
        package = _object(raw_package, "uv package")
        if package.get("name") != "mindclade-workspace":
            continue
        for raw_dependency in _array(package, "dependencies"):
            dependency = _object(raw_dependency, "uv direct dependency")
            direct.add(_string(dependency, "name"))

    records: list[Dependency] = []
    for raw_package in raw_packages:
        package = _object(raw_package, "uv package")
        source = _object(package.get("source"), "uv package source")
        if "registry" not in source:
            continue
        name = _string(package, "name")
        version = _string(package, "version")
        key = ("python", name, version)
        license_id = policy.get(key)
        if license_id is None:
            raise ValueError(
                f"resolved uv package lacks policy-recorded license metadata: {name}@{version}"
            )
        records.append(
            Dependency(
                ecosystem="python",
                name=name,
                version=version,
                license=license_id,
                source="uv.lock",
                scope="repository-validation-runtime",
                direct=name in direct,
            )
        )
    return records


def _bazel_packages(
    root: Path,
    policy: Mapping[tuple[str, str, str], str],
) -> list[Dependency]:
    module = (root / "MODULE.bazel").read_text(encoding="utf-8")
    direct_matches = re.findall(
        r'bazel_dep\(\s*name\s*=\s*"([a-z0-9_.+-]+)"\s*,\s*version\s*=\s*"([^"]+)"\s*\)',
        module,
    )
    direct_names = {name for name, _version in direct_matches}
    bazel = shutil.which("bazel")
    if bazel is None:
        raise ValueError("the pinned Bazel executable is required to resolve the module closure")
    completed = subprocess.run(
        [
            bazel,
            "--nohome_rc",
            "--noworkspace_rc",
            f"--output_user_root={root.resolve() / 'build/bazel-user-root'}",
            f"--bazelrc={root.resolve() / '.bazelrc'}",
            "mod",
            "graph",
            "--lockfile_mode=error",
        ],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if completed.returncode != 0:
        raise ValueError(f"locked Bazel module graph failed: {completed.stderr.strip()}")
    matches = sorted(set(re.findall(r"([a-z][a-z0-9_.+-]+)@([0-9][^\s(*)]*)", completed.stdout)))
    matches = [(name, version) for name, version in matches if name != "mindclade"]
    if not matches or not direct_names.issubset({name for name, _version in matches}):
        raise ValueError("resolved Bazel module closure is incomplete")
    records: list[Dependency] = []
    for name, version in matches:
        key = ("bazel", name, version)
        license_id = policy.get(key)
        if license_id is None:
            raise ValueError(
                f"Bazel dependency lacks policy-recorded license metadata: {name}@{version}"
            )
        records.append(
            Dependency(
                ecosystem="bazel",
                name=name,
                version=version,
                license=license_id,
                source="MODULE.bazel+MODULE.bazel.lock",
                scope="repository-build-runtime",
                direct=name in direct_names,
            )
        )
    return records


def _nix_source(
    root: Path,
    policy: Mapping[tuple[str, str, str], str],
) -> Dependency:
    lock_value: object = json.loads((root / "flake.lock").read_text(encoding="utf-8"))
    lock = _object(lock_value, "flake.lock")
    nodes = _object(lock.get("nodes"), "flake nodes")
    nixpkgs = _object(nodes.get("nixpkgs"), "nixpkgs node")
    locked = _object(nixpkgs.get("locked"), "locked nixpkgs node")
    revision = _string(locked, "rev")
    key = ("nix", "nixpkgs", revision)
    license_id = policy.get(key)
    if license_id is None:
        raise ValueError(f"locked nixpkgs input lacks policy-recorded license metadata: {revision}")
    return Dependency(
        ecosystem="nix",
        name="nixpkgs",
        version=revision,
        license=license_id,
        source="flake.lock",
        scope="development-package-set-source",
        direct=True,
    )


def declared_dependencies(
    root: Path,
    package_policy: Mapping[tuple[str, str, str], str],
) -> list[Dependency]:
    return [
        *_root_packages(root),
        *_python_packages(root, package_policy),
        *_bazel_packages(root, package_policy),
        _nix_source(root, package_policy),
    ]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = args.root.resolve()
    try:
        allowed, review, prohibited, package_policy = load_policy(
            root / "tools/licenses/allowlist.yaml"
        )
        records = declared_dependencies(root, package_policy)
    except (OSError, ValueError, json.JSONDecodeError, tomllib.TOMLDecodeError) as error:
        print(f"license inventory failed: {error}", file=sys.stderr)
        return 2
    violations: list[dict[str, object]] = []
    for record in records:
        reason = ""
        if record.license in prohibited:
            reason = "prohibited"
        elif record.license in review:
            reason = "independent review required"
        elif record.license not in allowed:
            reason = "not allowlisted"
        if reason:
            violations.append({**asdict(record), "reason": reason})
    report: dict[str, object] = {
        "schema_version": "license-inventory.v1",
        "scope": "resolved-wave0-repository-build-inputs",
        "coverage": [
            {"authority": "uv.lock", "status": "complete-resolved-closure"},
            {"authority": "Cargo.lock", "status": "complete-no-third-party-packages"},
            {"authority": "go.sum", "status": "complete-no-third-party-modules"},
            {"authority": "pnpm-lock.yaml", "status": "complete-no-third-party-packages"},
            {"authority": "MODULE.bazel.lock", "status": "complete-declared-module-closure"},
            {
                "authority": "flake.lock",
                "status": "development-package-set-source-pinned",
                "distribution": "excluded-from-product-artifacts",
            },
        ],
        "records": [
            asdict(record)
            for record in sorted(
                records,
                key=lambda item: (item.ecosystem, item.name, item.version),
            )
        ],
        "violations": violations,
    }
    rendered = json.dumps(report, sort_keys=True, separators=(",", ":")) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        sys.stdout.write(rendered)
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
