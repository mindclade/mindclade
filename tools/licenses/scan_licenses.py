#!/usr/bin/env python3.12
"""Inventory every resolved Wave 0 build dependency and enforce license policy."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
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


def _policy_set(spec: Mapping[str, object], field: str) -> set[str]:
    raw_values = _array(spec, field)
    if not all(isinstance(value, str) and value and value.strip() == value for value in raw_values):
        raise ValueError(f"license policy {field} must contain non-empty trimmed strings")
    values = cast(list[str], raw_values)
    if len(values) != len(set(values)):
        raise ValueError(f"license policy {field} contains duplicate values")
    return set(values)


def load_policy(
    path: Path,
) -> tuple[
    set[str],
    set[str],
    set[str],
    dict[tuple[str, str, str], str],
    set[tuple[str, str, str]],
]:
    value: object = json.loads(path.read_text(encoding="utf-8"))
    root = _object(value, "license policy")
    spec = _object(root.get("spec"), "license policy spec")
    allowed = _policy_set(spec, "licenses")
    review = _policy_set(spec, "reviewRequired")
    prohibited = _policy_set(spec, "prohibited")
    if allowed & review or allowed & prohibited or review & prohibited:
        raise ValueError("license policy classifications must not overlap")
    classified = allowed | review | prohibited
    packages: dict[tuple[str, str, str], str] = {}
    for raw_entry in _array(spec, "packages"):
        entry = _object(raw_entry, "package policy entry")
        key = (_string(entry, "ecosystem"), _string(entry, "name"), _string(entry, "version"))
        if key in packages:
            raise ValueError(f"duplicate package policy entry: {key}")
        license_id = _string(entry, "license")
        if license_id not in classified:
            raise ValueError(f"package policy entry uses an unclassified license: {key}")
        packages[key] = license_id
    build_only: set[tuple[str, str, str]] = set()
    for raw_entry in _array(spec, "buildOnlyExceptions"):
        entry = _object(raw_entry, "build-only exception")
        key = (_string(entry, "ecosystem"), _string(entry, "name"), _string(entry, "version"))
        if key in build_only:
            raise ValueError(f"duplicate build-only exception: {key}")
        if packages.get(key) not in review:
            raise ValueError(f"build-only exception must refer to a review-required package: {key}")
        if entry.get("distribution") != "prohibited":
            raise ValueError(f"build-only exception must prohibit distribution: {key}")
        build_only.add(key)
    return allowed, review, prohibited, packages, build_only


def _policy_license(
    policy: Mapping[tuple[str, str, str], str],
    ecosystem: str,
    name: str,
    version: str,
    authority: str,
) -> str:
    license_id = policy.get((ecosystem, name, version))
    if license_id is None:
        raise ValueError(
            f"resolved {authority} dependency lacks policy-recorded license metadata: "
            f"{name}@{version}"
        )
    return license_id


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
        license_id = _policy_license(policy, "python", name, version, "uv")
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


def _cargo_dependency(value: object) -> tuple[str, str | None]:
    if not isinstance(value, str) or not value:
        raise ValueError("Cargo.lock dependency entries must be non-empty strings")
    identity = value.partition(" (")[0]
    parts = identity.split()
    if len(parts) not in {1, 2}:
        raise ValueError(f"Cargo.lock dependency identity is ambiguous: {value}")
    version = parts[1] if len(parts) == 2 else None
    return parts[0], version


def _cargo_packages(
    root: Path,
    policy: Mapping[tuple[str, str, str], str],
) -> list[Dependency]:
    lock_value: object = tomllib.loads((root / "Cargo.lock").read_text(encoding="utf-8"))
    lock = _object(lock_value, "Cargo.lock")
    if lock.get("version") != 4:
        raise ValueError("Cargo.lock must use the pinned version 4 contract")
    raw_packages = _array(lock, "package")
    direct: set[tuple[str, str | None]] = set()
    for raw_package in raw_packages:
        package = _object(raw_package, "Cargo.lock package")
        if package.get("source") is not None:
            continue
        raw_dependencies = package.get("dependencies", [])
        if not isinstance(raw_dependencies, list):
            raise ValueError("Cargo.lock local package dependencies must be an array")
        direct.update(_cargo_dependency(value) for value in cast(list[object], raw_dependencies))

    records: list[Dependency] = []
    identities: set[tuple[str, str]] = set()
    for raw_package in raw_packages:
        package = _object(raw_package, "Cargo.lock package")
        source = package.get("source")
        if source is None:
            continue
        if not isinstance(source, str) or not source:
            raise ValueError("Cargo.lock package source must be a non-empty string")
        name = _string(package, "name")
        version = _string(package, "version")
        identity = (name, version)
        if identity in identities:
            raise ValueError(f"Cargo.lock repeats a resolved package identity: {name}@{version}")
        identities.add(identity)
        if source.startswith("registry+"):
            checksum = package.get("checksum")
            if not isinstance(checksum, str) or not re.fullmatch(r"[0-9a-f]{64}", checksum):
                raise ValueError(f"Cargo.lock registry package lacks a checksum: {name}@{version}")
        license_id = _policy_license(policy, "cargo", name, version, "Cargo.lock")
        is_direct = (name, version) in direct or (name, None) in direct
        records.append(
            Dependency(
                ecosystem="cargo",
                name=name,
                version=version,
                license=license_id,
                source="Cargo.lock",
                scope="repository-build-runtime",
                direct=is_direct,
            )
        )
    if not records:
        raise ValueError("Cargo.lock resolved registry closure is empty")
    return sorted(records, key=lambda item: (item.name, item.version))


def _go_requirements(path: Path) -> dict[tuple[str, str], bool]:
    requirements: dict[tuple[str, str], bool] = {}
    in_block = False
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("//"):
            continue
        if line.startswith(("replace ", "exclude ")):
            raise ValueError("go.mod replace/exclude directives require explicit license handling")
        if line == "require (":
            if in_block:
                raise ValueError("go.mod contains nested require blocks")
            in_block = True
            continue
        if in_block and line == ")":
            in_block = False
            continue
        if line.startswith("require "):
            dependency = line.removeprefix("require ")
        elif in_block:
            dependency = line
        else:
            continue
        content = dependency.partition("//")[0].strip()
        parts = content.split()
        if len(parts) != 2 or not parts[1].startswith("v"):
            raise ValueError(f"go.mod requirement is ambiguous: {raw_line.strip()}")
        key = (parts[0], parts[1])
        if key in requirements:
            raise ValueError(f"go.mod repeats requirement: {parts[0]}@{parts[1]}")
        requirements[key] = "// indirect" not in dependency
    if in_block:
        raise ValueError("go.mod require block is unterminated")
    if not requirements:
        raise ValueError("go.mod resolved requirement set is empty")
    return requirements


def _go_packages(
    root: Path,
    policy: Mapping[tuple[str, str, str], str],
    resolved_modules: Sequence[Mapping[str, object]] | None = None,
) -> list[Dependency]:
    requirements = _go_requirements(root / "go.mod")
    checksums: dict[tuple[str, str], str] = {}
    for raw_line in (root / "go.sum").read_text(encoding="utf-8").splitlines():
        parts = raw_line.split()
        if len(parts) != 3 or not re.fullmatch(r"h1:[A-Za-z0-9+/=]+", parts[2]):
            raise ValueError(f"go.sum entry is malformed: {raw_line}")
        version = parts[1]
        if not version.startswith("v"):
            raise ValueError(f"go.sum version is not canonical: {parts[1]}")
        checksums[(parts[0], version)] = parts[2]
    if not checksums:
        raise ValueError("go.sum resolved checksum closure is empty")
    if resolved_modules is None:
        go = shutil.which("go")
        if go is None:
            raise ValueError("the pinned Go executable is required to resolve the module closure")
        completed = subprocess.run(
            [go, "list", "-mod=readonly", "-m", "-json", "all"],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
            env={**dict(os.environ), "GOTOOLCHAIN": "local"},
            timeout=120,
        )
        if completed.returncode != 0:
            raise ValueError(f"readonly Go module graph failed: {completed.stderr.strip()}")
        decoder = json.JSONDecoder()
        position = 0
        parsed_by_identity: dict[tuple[str, str], Mapping[str, object]] = {}
        while position < len(completed.stdout):
            while position < len(completed.stdout) and completed.stdout[position].isspace():
                position += 1
            if position == len(completed.stdout):
                break
            value, position = decoder.raw_decode(completed.stdout, position)
            package = _object(value, "go list package")
            module_value = package.get("Module")
            if isinstance(module_value, dict):
                module = cast(dict[str, object], module_value)
                if module.get("Main") is not True:
                    identity = (_string(module, "Path"), _string(module, "Version"))
                    parsed_by_identity[identity] = module
        resolved_modules = [parsed_by_identity[key] for key in sorted(parsed_by_identity)]
    records: list[Dependency] = []
    for module in resolved_modules:
        if module.get("Main") is True:
            continue
        if module.get("Replace") is not None:
            raise ValueError("resolved Go replacements require explicit license handling")
        name = _string(module, "Path")
        version = _string(module, "Version")
        content_sum = _string(module, "Sum")
        go_mod_sum = _string(module, "GoModSum")
        if checksums.get((name, version)) != content_sum:
            raise ValueError(f"go.sum content checksum mismatch: {name}@{version}")
        if checksums.get((name, f"{version}/go.mod")) != go_mod_sum:
            raise ValueError(f"go.sum module checksum mismatch: {name}@{version}")
        records.append(
            Dependency(
                ecosystem="go",
                name=name,
                version=version,
                license=_policy_license(policy, "go", name, version, "go.sum"),
                source="go.mod+go.sum",
                scope="repository-build-and-test-checksum-closure",
                direct=requirements.get((name, version), False),
            )
        )
    return records


def _workspace_npm_direct_names(root: Path) -> set[str]:
    direct: set[str] = set()
    ignored = {".git", ".venv", "build", "node_modules"}
    for path in sorted(root.rglob("package.json")):
        if any(part in ignored or part.startswith("bazel-") for part in path.parts):
            continue
        value: object = json.loads(path.read_text(encoding="utf-8"))
        package = _object(value, str(path.relative_to(root)))
        for field in (
            "dependencies",
            "devDependencies",
            "optionalDependencies",
            "peerDependencies",
        ):
            raw_dependencies = package.get(field, {})
            dependencies = _object(raw_dependencies, f"{path} {field}")
            for name, constraint in dependencies.items():
                if not isinstance(constraint, str) or not constraint:
                    raise ValueError(f"{path} {field} constraint for {name} is invalid")
                if not constraint.startswith("workspace:"):
                    direct.add(name)
    return direct


def _pnpm_packages(
    root: Path,
    policy: Mapping[tuple[str, str, str], str],
) -> list[Dependency]:
    content = (root / "pnpm-lock.yaml").read_text(encoding="utf-8")
    if not re.search(r"^lockfileVersion:\s*['\"]?9\.0['\"]?\s*$", content, re.MULTILINE):
        raise ValueError("pnpm-lock.yaml must use the pinned version 9.0 contract")
    section = re.search(
        r"^packages:\s*$\n(?P<body>.*?)^snapshots:\s*$", content, re.MULTILINE | re.DOTALL
    )
    if section is None:
        raise ValueError("pnpm-lock.yaml lacks bounded packages/snapshots sections")
    raw_entries = list(
        re.finditer(
            r"^  (?P<key>[^\n]+):\s*$\n(?P<body>(?:(?: {4,}[^\n]*|\s*)\n)*)",
            section.group("body"),
            re.MULTILINE,
        )
    )
    if not raw_entries:
        raise ValueError("pnpm-lock.yaml resolved package closure is empty")
    direct_names = _workspace_npm_direct_names(root)
    records: list[Dependency] = []
    identities: set[tuple[str, str]] = set()
    for match in raw_entries:
        raw_key = match.group("key").strip()
        if raw_key[:1] in {"'", '"'}:
            if len(raw_key) < 2 or raw_key[-1] != raw_key[0]:
                raise ValueError(f"pnpm package identity has mismatched quoting: {raw_key}")
            raw_key = raw_key[1:-1]
        name, separator, version = raw_key.rpartition("@")
        if (
            not separator
            or not re.fullmatch(r"(?:@[a-z0-9._-]+/)?[a-z0-9._-]+", name)
            or not re.fullmatch(r"[0-9][A-Za-z0-9.+_-]*", version)
        ):
            raise ValueError(f"pnpm package identity is unsupported or ambiguous: {raw_key}")
        identity = (name, version)
        if identity in identities:
            raise ValueError(f"pnpm-lock.yaml repeats package identity: {raw_key}")
        identities.add(identity)
        if not re.search(r"integrity:\s*sha512-[A-Za-z0-9+/=]+", match.group("body")):
            raise ValueError(f"pnpm registry package lacks sha512 integrity: {raw_key}")
        records.append(
            Dependency(
                ecosystem="npm",
                name=name,
                version=version,
                license=_policy_license(policy, "npm", name, version, "pnpm-lock.yaml"),
                source="pnpm-lock.yaml",
                scope="repository-build-runtime",
                direct=name in direct_names,
            )
        )
    missing_direct = sorted(direct_names - {record.name for record in records})
    if missing_direct:
        raise ValueError(
            "pnpm-lock.yaml omits external workspace declarations: " + ", ".join(missing_direct)
        )
    return sorted(records, key=lambda item: (item.name, item.version))


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
        license_id = _policy_license(policy, "bazel", name, version, "Bazel")
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
    license_id = _policy_license(policy, "nix", "nixpkgs", revision, "nixpkgs")
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
        *_cargo_packages(root, package_policy),
        *_go_packages(root, package_policy),
        *_pnpm_packages(root, package_policy),
        *_bazel_packages(root, package_policy),
        _nix_source(root, package_policy),
    ]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path)
    parser.add_argument("--self-test", action="store_true")
    return parser


def self_test() -> None:
    policy = {
        ("cargo", "serde", "1.0.0"): "MIT OR Apache-2.0",
        ("go", "example.com/direct", "v1.2.3"): "MIT",
        ("go", "example.com/history", "v0.9.0"): "BSD-3-Clause",
        ("npm", "typescript", "5.9.3"): "Apache-2.0",
        ("npm", "undici-types", "7.16.0"): "MIT",
    }
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "Cargo.lock").write_text(
            """version = 4

[[package]]
name = "local"
version = "0.1.0"
dependencies = ["serde 1.0.0"]

[[package]]
name = "serde"
version = "1.0.0"
source = "registry+https://example.invalid/index"
checksum = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
""",
            encoding="utf-8",
        )
        (root / "go.mod").write_text(
            """module example.com/local

go 1.26.0

require example.com/direct v1.2.3
""",
            encoding="utf-8",
        )
        (root / "go.sum").write_text(
            """example.com/direct v1.2.3 h1:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=
example.com/direct v1.2.3/go.mod h1:BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB=
example.com/history v0.9.0/go.mod h1:CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC=
""",
            encoding="utf-8",
        )
        (root / "package.json").write_text(
            json.dumps(
                {
                    "dependencies": {"local": "workspace:*"},
                    "devDependencies": {"typescript": "5.9.3"},
                }
            ),
            encoding="utf-8",
        )
        (root / "pnpm-lock.yaml").write_text(
            """lockfileVersion: '9.0'
packages:
  typescript@5.9.3:
    resolution: {integrity: sha512-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=}
  undici-types@7.16.0:
    resolution: {integrity: sha512-BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB=}
snapshots:
""",
            encoding="utf-8",
        )
        cargo = _cargo_packages(root, policy)
        resolved_go_modules: list[Mapping[str, object]] = [
            {
                "GoModSum": "h1:BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB=",
                "Path": "example.com/direct",
                "Sum": "h1:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
                "Version": "v1.2.3",
            }
        ]
        go = _go_packages(root, policy, resolved_modules=resolved_go_modules)
        npm = _pnpm_packages(root, policy)
        if len(cargo) != 1 or not cargo[0].direct:
            raise AssertionError("Cargo.lock direct closure classification failed")
        if len(go) != 1 or not go[0].direct:
            raise AssertionError("go.sum/go.mod direct closure classification failed")
        if len(npm) != 2 or not next(item for item in npm if item.name == "typescript").direct:
            raise AssertionError("pnpm direct closure classification failed")
        if [asdict(item) for item in _pnpm_packages(root, policy)] != [
            asdict(item) for item in npm
        ]:
            raise AssertionError("pnpm inventory is not deterministic")
        for description, operation in (
            ("missing Cargo policy", lambda: _cargo_packages(root, {})),
            (
                "missing Go policy",
                lambda: _go_packages(root, {}, resolved_modules=resolved_go_modules),
            ),
            ("missing pnpm policy", lambda: _pnpm_packages(root, {})),
        ):
            try:
                operation()
            except ValueError:
                continue
            raise AssertionError(f"scanner accepted {description}")


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.self_test:
        self_test()
        print("native lock license closure self-test passed")
        return 0
    root = args.root.resolve()
    try:
        allowed, review, prohibited, package_policy, build_only = load_policy(
            root / "tools/licenses/allowlist.yaml"
        )
        records = declared_dependencies(root, package_policy)
    except (OSError, ValueError, json.JSONDecodeError, tomllib.TOMLDecodeError) as error:
        print(f"license inventory failed: {error}", file=sys.stderr)
        return 2
    sorted_records = sorted(records, key=lambda item: (item.ecosystem, item.name, item.version))
    violations: list[dict[str, object]] = []
    for record in sorted_records:
        reason = ""
        if record.license in prohibited:
            reason = "prohibited"
        elif (
            record.license in review
            and (
                record.ecosystem,
                record.name,
                record.version,
            )
            not in build_only
        ):
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
            {
                "authority": "Cargo.lock",
                "status": "complete-resolved-closure",
                "record_count": sum(record.ecosystem == "cargo" for record in sorted_records),
            },
            {
                "authority": "go.sum",
                "status": "complete-resolved-checksum-closure",
                "go_mod_validated": True,
                "record_count": sum(record.ecosystem == "go" for record in sorted_records),
            },
            {
                "authority": "pnpm-lock.yaml",
                "status": "complete-resolved-closure",
                "record_count": sum(
                    record.ecosystem == "npm" and record.source == "pnpm-lock.yaml"
                    for record in sorted_records
                ),
            },
            {"authority": "MODULE.bazel.lock", "status": "complete-declared-module-closure"},
            {
                "authority": "flake.lock",
                "status": "development-package-set-source-pinned",
                "distribution": "excluded-from-product-artifacts",
            },
        ],
        "records": [asdict(record) for record in sorted_records],
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
