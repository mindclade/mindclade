#!/usr/bin/env python3.12
"""Build and verify deterministic DeepEP wheel and evidence artifacts."""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any, cast

DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
STORE_PATH_PATTERN = re.compile(r"^/nix/store/[a-z0-9]{32}-.+$")
ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


class ArtifactError(ValueError):
    """Raised when an artifact violates the DeepEP package contract."""


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def load_object(path: Path, description: str) -> dict[str, Any]:
    try:
        value: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ArtifactError(f"cannot read {description}: {error}") from error
    if not isinstance(value, dict):
        raise ArtifactError(f"{description} must be an object")
    return cast(dict[str, Any], value)


def validate_runtime_manifest(manifest: Mapping[str, Any]) -> str:
    if manifest.get("schema_version") != "mindclade.deepep-runtime-manifest/v2":
        raise ArtifactError("runtime manifest schema version is not v2")
    if manifest.get("production_authority") is not False:
        raise ArtifactError("source-built runtime manifest cannot claim production authority")
    fingerprint = manifest.get("fingerprint")
    inputs = manifest.get("fingerprint_inputs")
    if not isinstance(fingerprint, Mapping) or not isinstance(inputs, Mapping):
        raise ArtifactError("runtime manifest fingerprint is malformed")
    declared = fingerprint.get("value")
    calculated = sha256_bytes(canonical_json(inputs).rstrip(b"\n"))
    if declared != calculated or not isinstance(declared, str):
        raise ArtifactError("runtime manifest fingerprint does not match canonical inputs")
    toolchain = manifest.get("toolchain")
    if not isinstance(toolchain, Mapping):
        raise ArtifactError("runtime manifest toolchain is malformed")
    for name in ("cuda_home", "nccl_root", "nvcc", "nvshmem_root"):
        value = toolchain.get(name)
        if not isinstance(value, str) or STORE_PATH_PATTERN.fullmatch(value) is None:
            raise ArtifactError(f"runtime manifest {name} is not an immutable Nix store path")
    distribution = manifest.get("distribution")
    allowed_distributions = (
        {"mode": "hermetic-nix", "requirements": []},
        {"mode": "nix-closure", "requirements": []},
    )
    if distribution not in allowed_distributions:
        raise ArtifactError("runtime manifest must describe the locked Nix closure")
    return declared


def _safe_members(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    members = archive.infolist()
    for member in members:
        path = PurePosixPath(member.filename)
        if path.is_absolute() or ".." in path.parts or "\\" in member.filename:
            raise ArtifactError(f"wheel contains an unsafe member: {member.filename}")
    return members


def _run(tool: str, *arguments: str) -> str:
    result = subprocess.run(
        [tool, *arguments],
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "no diagnostic output"
        raise ArtifactError(f"{Path(tool).name} failed: {detail}")
    return result.stdout.strip()


def _rewrite_metadata(path: Path, requirements: Sequence[str]) -> None:
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line]
    if not any(line == "Name: deep_ep" for line in lines):
        raise ArtifactError("wheel metadata does not identify deep_ep")
    if not any(line.startswith("Version: 2.1.0+") for line in lines):
        raise ArtifactError("wheel metadata does not identify DeepEP 2.1.0 plus its commit")
    retained = [line for line in lines if not line.startswith("Requires-Dist:")]
    retained.extend(f"Requires-Dist: {requirement}" for requirement in sorted(requirements))
    path.write_text("\n".join(retained) + "\n", encoding="utf-8")


def _record_hash(path: Path) -> str:
    value = hashlib.sha256(path.read_bytes()).digest()
    return "sha256=" + base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _rewrite_record(root: Path, record: Path) -> None:
    rows: list[tuple[str, str, str]] = []
    for path in sorted(candidate for candidate in root.rglob("*") if candidate.is_file()):
        relative = path.relative_to(root).as_posix()
        if path == record:
            rows.append((relative, "", ""))
        else:
            rows.append((relative, _record_hash(path), str(path.stat().st_size)))
    with record.open("w", encoding="utf-8", newline="") as handle:
        csv.writer(handle, lineterminator="\n").writerows(rows)


def _write_wheel(root: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(candidate for candidate in root.rglob("*") if candidate.is_file()):
            info = zipfile.ZipInfo(path.relative_to(root).as_posix(), ZIP_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            mode = 0o755 if os.access(path, os.X_OK) else 0o644
            info.external_attr = (mode & 0xFFFF) << 16
            info.create_system = 3
            archive.writestr(info, path.read_bytes(), compresslevel=9)


def normalize_wheel(
    input_path: Path,
    output_path: Path,
    runtime_manifest_path: Path,
    requirements_path: Path,
    patchelf: str,
    strip: str,
    elf_manifest_path: Path,
) -> None:
    runtime_manifest = load_object(runtime_manifest_path, "runtime manifest")
    validate_runtime_manifest(runtime_manifest)
    requirements_value = load_object(requirements_path, "wheel requirement lock")
    requirements = requirements_value.get("requirements")
    if not isinstance(requirements, list) or not all(
        isinstance(item, str) and "==" in item for item in requirements
    ):
        raise ArtifactError("wheel requirement lock must contain only exact requirements")
    with tempfile.TemporaryDirectory(prefix="mindclade-deepep-wheel-") as directory:
        root = Path(directory)
        with zipfile.ZipFile(input_path) as archive:
            _safe_members(archive)
            archive.extractall(root)
        dist_infos = list(root.glob("deep_ep-*.dist-info"))
        extensions = list(root.glob("deep_ep/_C*.so"))
        if len(dist_infos) != 1 or len(extensions) != 1:
            raise ArtifactError("wheel must contain one dist-info directory and one DeepEP extension")
        extension = extensions[0]
        needed = sorted(filter(None, _run(patchelf, "--print-needed", str(extension)).splitlines()))
        if not any(name.startswith("libnccl.so") for name in needed):
            raise ArtifactError("DeepEP extension does not declare NCCL")
        if not any(name.startswith("libnvshmem_host.so") for name in needed):
            raise ArtifactError("DeepEP extension does not declare NVSHMEM host runtime")
        rpath = _run(patchelf, "--print-rpath", str(extension))
        rpath_entries = [entry for entry in rpath.split(":") if entry]
        if not rpath_entries or any(
            not entry.startswith("/nix/store/") for entry in rpath_entries
        ):
            raise ArtifactError("closure-bound wheel has an undeclared ELF runtime path")
        _run(strip, "--strip-debug", str(extension))
        _rewrite_metadata(dist_infos[0] / "METADATA", cast(list[str], requirements))
        (root / "deep_ep" / "mindclade-runtime.json").write_bytes(
            canonical_json(runtime_manifest)
        )
        elf_manifest = {
            "extension": extension.relative_to(root).as_posix(),
            "needed": needed,
            "distribution": "nix-closure-bound",
            "rpath": rpath,
            "schema_version": "mindclade.deepep-elf-manifest/v1",
        }
        (root / "deep_ep" / "mindclade-elf.json").write_bytes(canonical_json(elf_manifest))
        record = dist_infos[0] / "RECORD"
        _rewrite_record(root, record)
        _write_wheel(root, output_path)
    elf_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    elf_manifest_path.write_bytes(canonical_json(elf_manifest))


def build_bundle(
    wheel: Path,
    runtime_manifest_path: Path,
    elf_manifest_path: Path,
    package_path: Path,
    package_drv: str,
    closure_paths: Path,
    output: Path,
) -> None:
    runtime = load_object(runtime_manifest_path, "runtime manifest")
    fingerprint = validate_runtime_manifest(runtime)
    elf = load_object(elf_manifest_path, "ELF manifest")
    output.mkdir(parents=True, exist_ok=False)
    wheel_dir = output / "wheel"
    wheel_dir.mkdir()
    installed_wheel = wheel_dir / wheel.name
    shutil.copyfile(wheel, installed_wheel)
    os.symlink(package_path, output / "package")
    (output / "package-path").write_text(f"{package_path}\n", encoding="utf-8")
    (output / "package-drv-path").write_text(f"{package_drv}\n", encoding="utf-8")
    shutil.copyfile(runtime_manifest_path, output / "runtime-manifest.json")
    shutil.copyfile(elf_manifest_path, output / "elf-dependencies.json")
    shutil.copyfile(closure_paths, output / "nix-closure-paths")
    wheel_digest = sha256_file(installed_wheel)
    artifact_manifest = {
        "artifacts": {
            "nix_package": {"derivation": package_drv, "output": str(package_path)},
            "wheel": {
                "digest": wheel_digest,
                "filename": wheel.name,
                "size": installed_wheel.stat().st_size,
            },
        },
        "production_authority": False,
        "runtime_fingerprint": fingerprint,
        "schema_version": "mindclade.deepep-artifact-bundle/v1",
    }
    (output / "artifact-manifest.json").write_bytes(canonical_json(artifact_manifest))
    artifact = cast(Mapping[str, str], runtime["artifact"])
    profile = cast(Mapping[str, str], runtime["runtime_profile"])
    packages = [
        ("SPDXRef-DeepEP", "deep-ep", artifact["version"], "MIT"),
        ("SPDXRef-Torch", "torch", profile["torch"], "BSD-3-Clause"),
        ("SPDXRef-NCCL", "nccl", profile["nccl"], "LicenseRef-NVIDIA-NCCL"),
        ("SPDXRef-NVSHMEM", "nvshmem", profile["nvshmem"], "LicenseRef-NVIDIA-NVSHMEM"),
    ]
    sbom = {
        "SPDXID": "SPDXRef-DOCUMENT",
        "creationInfo": {"creators": ["Tool: mindclade-deepep-artifact-contract"]},
        "dataLicense": "CC0-1.0",
        "documentNamespace": f"https://artifacts.mindclade.dev/deepep/{fingerprint}",
        "name": f"deep-ep-{artifact['version']}",
        "packages": [
            {
                "SPDXID": identifier,
                "downloadLocation": "NOASSERTION",
                "filesAnalyzed": False,
                "licenseConcluded": license_id,
                "licenseDeclared": license_id,
                "name": name,
                "versionInfo": version,
            }
            for identifier, name, version, license_id in packages
        ],
        "relationships": [
            {
                "relatedSpdxElement": "SPDXRef-DeepEP",
                "relationshipType": "DESCRIBES",
                "spdxElementId": "SPDXRef-DOCUMENT",
            },
            *[
                {
                    "relatedSpdxElement": identifier,
                    "relationshipType": "DEPENDS_ON",
                    "spdxElementId": "SPDXRef-DeepEP",
                }
                for identifier, _name, _version, _license in packages[1:]
            ],
        ],
        "spdxVersion": "SPDX-2.3",
    }
    (output / "sbom.spdx.json").write_bytes(canonical_json(sbom))
    provenance = {
        "_type": "https://in-toto.io/Statement/v1",
        "predicate": {
            "buildDefinition": {
                "buildType": "https://nixos.org/nix/derivation",
                "externalParameters": {
                    "runtime_fingerprint": fingerprint,
                    "upstream_commit": artifact["upstream_commit"],
                },
                "resolvedDependencies": [
                    {
                        "digest": {"sha256": artifact["archive_sha256"].removeprefix("sha256:")},
                        "uri": "pkg:github/deepseek-ai/DeepEP",
                    }
                ],
            },
            "runDetails": {
                "builder": {"id": "https://github.com/mindclade/mindclade/nix-deepep"},
                "metadata": {"invocationId": fingerprint},
            },
        },
        "predicateType": "https://slsa.dev/provenance/v1",
        "subject": [{"digest": {"sha256": wheel_digest.removeprefix("sha256:")}, "name": wheel.name}],
    }
    (output / "provenance.intoto.jsonl").write_bytes(canonical_json(provenance))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    verify = subparsers.add_parser("verify-runtime")
    verify.add_argument("--manifest", type=Path, required=True)
    normalize = subparsers.add_parser("normalize-wheel")
    normalize.add_argument("--input", type=Path, required=True)
    normalize.add_argument("--output", type=Path, required=True)
    normalize.add_argument("--runtime-manifest", type=Path, required=True)
    normalize.add_argument("--requirements", type=Path, required=True)
    normalize.add_argument("--patchelf", required=True)
    normalize.add_argument("--strip", required=True)
    normalize.add_argument("--elf-manifest", type=Path, required=True)
    bundle = subparsers.add_parser("bundle")
    bundle.add_argument("--wheel", type=Path, required=True)
    bundle.add_argument("--runtime-manifest", type=Path, required=True)
    bundle.add_argument("--elf-manifest", type=Path, required=True)
    bundle.add_argument("--package", type=Path, required=True)
    bundle.add_argument("--package-drv", required=True)
    bundle.add_argument("--closure-paths", type=Path, required=True)
    bundle.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "verify-runtime":
            validate_runtime_manifest(load_object(args.manifest, "runtime manifest"))
        elif args.command == "normalize-wheel":
            normalize_wheel(
                args.input,
                args.output,
                args.runtime_manifest,
                args.requirements,
                args.patchelf,
                args.strip,
                args.elf_manifest,
            )
        elif args.command == "bundle":
            build_bundle(
                args.wheel,
                args.runtime_manifest,
                args.elf_manifest,
                args.package,
                args.package_drv,
                args.closure_paths,
                args.output,
            )
        else:
            raise ArtifactError(f"unsupported command: {args.command}")
    except (ArtifactError, OSError, subprocess.SubprocessError, zipfile.BadZipFile) as error:
        print(f"DeepEP artifact contract failed: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
