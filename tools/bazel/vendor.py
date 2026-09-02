#!/usr/bin/env python3.12
"""Refresh, verify, or physically isolate the Wave 1 Bazel vendor snapshot."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
from collections.abc import Generator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any, cast

import toolchain_contract

SCHEMA = "bazel-vendor-manifest.v1"
TARGET = "//:wave1_tests"
IGNORED_SYMLINK = "bazel-external"
BAZEL_VERSION = "9.1.1"
MANIFEST_FIELDS = {
    "bazel_version",
    "module_lock_digest",
    "schema_version",
    "snapshot_digest",
    "system",
    "target",
    "toolchain_digest",
    "trees",
}
HOST_SYSTEMS = {
    ("Darwin", "arm64"): "aarch64-darwin",
    ("Linux", "aarch64"): "aarch64-linux",
    ("Linux", "x86_64"): "x86_64-linux",
}
LOCAL_REPOSITORIES = frozenset(
    {
        "go_sdk",
        "mindclade_deepep_nix",
        "nix_python_3_12",
        "nix_python_toolchains",
        "nix_toolchains",
    }
)


def digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def digest_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def host_system() -> str:
    observed = (platform.system(), platform.machine())
    try:
        return HOST_SYSTEMS[observed]
    except KeyError as error:
        raise ValueError(f"unsupported host system: {observed[0]} {observed[1]}") from error


def toolchain_context(
    repository: Path, toolchain_manifest: Mapping[str, Any]
) -> tuple[str, str, str]:
    toolchain_contract.validate_manifest(toolchain_manifest, verify_files=False)
    module_lock_digest = digest(repository / "MODULE.bazel.lock")
    locks = cast(Mapping[str, str], toolchain_manifest["locks"])
    if locks["module"] != module_lock_digest:
        raise ValueError("toolchain manifest does not bind the current MODULE.bazel.lock")
    return (
        cast(str, toolchain_manifest["system"]),
        cast(str, toolchain_manifest["toolchain_digest"]),
        module_lock_digest,
    )


def require_host_system(expected: str, *, linux_only: bool) -> None:
    observed = host_system()
    if observed != expected:
        raise ValueError(f"toolchain system {expected} does not match host system {observed}")
    if linux_only and not observed.endswith("-linux"):
        raise ValueError("authoritative physical offline verification requires Linux")


def normalize_modes(root: Path) -> None:
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            continue
        if path.is_dir():
            path.chmod(0o755)
        elif path.is_file():
            mode = stat.S_IMODE(path.stat().st_mode)
            path.chmod(0o755 if mode & 0o111 else 0o644)
        else:
            relative = path.relative_to(root)
            raise ValueError(f"vendor tree contains unsupported file type: {relative}")


def _symlink_record(root: Path, path: Path, relative: str) -> dict[str, Any] | None:
    if path == root / IGNORED_SYMLINK:
        return None
    target_path = path.readlink()
    target = target_path.as_posix()
    if target_path.is_absolute():
        raise ValueError(f"vendor tree contains absolute symlink: {relative}")
    try:
        resolved = (path.parent / target_path).resolve(strict=False)
    except (OSError, RuntimeError) as error:
        raise ValueError(f"vendor tree contains invalid symlink: {relative}") from error
    if root not in resolved.parents:
        raise ValueError(f"vendor tree symlink escapes its root: {relative} -> {target}")
    target_bytes = target.encode()
    return {
        "kind": "symlink",
        "path": relative,
        "sha256": digest_bytes(target_bytes),
        "size": len(target_bytes),
        "symlink_target": target,
    }


def inventory(
    root: Path, repository: Path, toolchain_manifest: Mapping[str, Any]
) -> dict[str, Any]:
    root = root.resolve()
    system, toolchain_digest, module_lock_digest = toolchain_context(repository, toolchain_manifest)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            record = _symlink_record(root, path, relative)
            if record is None:
                continue
            grouped.setdefault(relative.split("/", 1)[0], []).append(record)
            continue
        if path.is_dir() or relative == "vendor-manifest.v1.json":
            continue
        if not path.is_file():
            raise ValueError(f"vendor tree contains unsupported file type: {relative}")
        record = {
            "kind": "file",
            "mode": f"{stat.S_IMODE(path.stat().st_mode):04o}",
            "path": relative,
            "sha256": digest(path),
            "size": path.stat().st_size,
        }
        grouped.setdefault(relative.split("/", 1)[0], []).append(record)
    trees: list[dict[str, Any]] = []
    for name, records in sorted(grouped.items()):
        trees.append(
            {
                "entry_count": len(records),
                "path": name,
                "size": sum(int(record["size"]) for record in records),
                "tree_sha256": digest_bytes(
                    b"\n".join(
                        json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
                        for record in records
                    )
                ),
            }
        )
    unsigned: dict[str, Any] = {
        "schema_version": SCHEMA,
        "target": TARGET,
        "bazel_version": BAZEL_VERSION,
        "system": system,
        "toolchain_digest": toolchain_digest,
        "module_lock_digest": module_lock_digest,
        "trees": trees,
    }
    unsigned["snapshot_digest"] = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )
    return unsigned


def write_manifest(root: Path, repository: Path, toolchain_manifest: Mapping[str, Any]) -> None:
    normalize_modes(root)
    value = inventory(root, repository, toolchain_manifest)
    (root / "vendor-manifest.v1.json").write_text(
        json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8"
    )


def verify(root: Path, repository: Path, toolchain_manifest: Mapping[str, Any]) -> None:
    expected_value: Any = json.loads((root / "vendor-manifest.v1.json").read_text(encoding="utf-8"))
    if not isinstance(expected_value, dict):
        raise ValueError("vendor manifest must contain one JSON object")
    expected = cast(dict[str, Any], expected_value)
    if set(expected) != MANIFEST_FIELDS:
        raise ValueError("vendor manifest contains missing or unknown fields")
    system, toolchain_digest, module_lock_digest = toolchain_context(repository, toolchain_manifest)
    if expected["system"] != system:
        raise ValueError(
            f"vendor manifest system {expected['system']} does not match toolchain system {system}"
        )
    if expected["toolchain_digest"] != toolchain_digest:
        raise ValueError("vendor manifest does not bind the current toolchain digest")
    if expected["module_lock_digest"] != module_lock_digest:
        raise ValueError("vendor manifest does not bind the current MODULE.bazel.lock")
    actual = inventory(root, repository, toolchain_manifest)
    if expected != actual:
        raise ValueError("vendor tree differs from vendor-manifest.v1.json")


def bazel_command(bazel: str, output_user_root: Path | None, *arguments: str) -> list[str]:
    command = [bazel]
    if output_user_root is not None:
        command.append(f"--output_user_root={output_user_root}")
    command.extend(arguments)
    return command


def require_bazel_version(bazel: str) -> None:
    version = subprocess.run(
        [bazel, "--version"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if version != f"bazel {BAZEL_VERSION}":
        raise ValueError(f"Bazel {BAZEL_VERSION} is required; observed {version!r}")


def validated_bazel(toolchain_manifest: Mapping[str, Any], requested: str | None) -> str:
    executables = cast(Mapping[str, Mapping[str, str]], toolchain_manifest["executables"])
    expected = Path(executables["bazel"]["path"])
    if requested is None:
        selected = expected
    else:
        discovered = shutil.which(requested) if "/" not in requested else requested
        if discovered is None:
            raise ValueError(f"requested Bazel executable is unavailable: {requested}")
        selected = Path(discovered)
    try:
        selected = selected.resolve(strict=True)
        expected = expected.resolve(strict=True)
    except OSError as error:
        raise ValueError("manifest Bazel executable is unavailable") from error
    if selected != expected:
        raise ValueError(
            f"Bazel executable differs from toolchain manifest: {selected} != {expected}"
        )
    if toolchain_contract.file_digest(selected) != executables["bazel"]["sha256"]:
        raise ValueError("Bazel executable digest differs from toolchain manifest")
    require_bazel_version(str(selected))
    return str(selected)


def nix_backed_unshare() -> str:
    selected = shutil.which("unshare")
    if selected is None:
        raise ValueError("unshare is required for OS-level network denial")
    try:
        resolved = Path(selected).resolve(strict=True)
    except OSError as error:
        raise ValueError("unshare is unavailable") from error
    if resolved.parts[:3] != ("/", "nix", "store"):
        raise ValueError(f"unshare is not Nix-store backed: {resolved}")
    if not resolved.is_file() or not os.access(resolved, os.X_OK):
        raise ValueError(f"unshare is not executable: {resolved}")
    return str(resolved)


def target_repositories(repository: Path, bazel: str, output_user_root: Path) -> list[str]:
    require_bazel_version(bazel)
    query = subprocess.run(
        bazel_command(
            bazel,
            output_user_root,
            "cquery",
            "--color=no",
            "--curses=no",
            "--output=label",
            f"deps({TARGET})",
        ),
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )
    mapping_process = subprocess.run(
        bazel_command(
            bazel,
            output_user_root,
            "mod",
            "dump_repo_mapping",
            "",
            "--color=no",
            "--curses=no",
        ),
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )
    mapping_value: Any = json.loads(mapping_process.stdout)
    if not isinstance(mapping_value, dict):
        raise ValueError("Bazel repository mapping is not an object")
    mapping: dict[str, str] = {}
    for apparent, canonical in cast(dict[object, object], mapping_value).items():
        if not isinstance(apparent, str) or not isinstance(canonical, str):
            raise ValueError("Bazel repository mapping entries must be strings")
        mapping[apparent] = canonical
    canonical_to_apparent = {
        canonical: apparent for apparent, canonical in mapping.items() if apparent
    }
    local_canonical = {mapping[name] for name in LOCAL_REPOSITORIES if name in mapping}
    repository_names: set[str] = set()
    for label in query.stdout.splitlines():
        if not label.startswith("@") or "//" not in label:
            continue
        name = label.lstrip("@").split("//", 1)[0]
        if not name or name == "bazel_tools":
            continue
        if name in mapping:
            apparent = name
        elif name in canonical_to_apparent:
            apparent = canonical_to_apparent[name]
        else:
            repository_names.add(f"@@{name}")
            continue
        if apparent not in LOCAL_REPOSITORIES:
            repository_names.add(f"@{apparent}")

    output_base_process = subprocess.run(
        bazel_command(
            bazel,
            output_user_root,
            "info",
            "output_base",
            "--color=no",
            "--curses=no",
        ),
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )
    external = Path(output_base_process.stdout.strip()) / "external"
    if not external.is_dir():
        raise ValueError("Bazel output base has no external repository directory")
    for path in sorted(external.iterdir(), key=lambda item: item.name):
        name = path.name
        if (
            name in {"_main", "bazel_tools"}
            or name in local_canonical
            or name.startswith("@")
            or name.endswith(".marker")
        ):
            continue
        repository_names.add(f"@@{name}")
    return sorted(repository_names)


@contextmanager
def blocked_replacement_signals() -> Generator[None, None, None]:
    blocked = {signal.SIGINT, signal.SIGTERM, signal.SIGHUP}
    previous = signal.pthread_sigmask(signal.SIG_BLOCK, blocked)
    try:
        yield
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, previous)


def refresh(
    root: Path,
    repository: Path,
    toolchain_manifest: Mapping[str, Any],
    requested_bazel: str | None = None,
) -> None:
    toolchain_contract.validate_manifest(toolchain_manifest, verify_files=True)
    system, _, _ = toolchain_context(repository, toolchain_manifest)
    require_host_system(system, linux_only=False)
    bazel = validated_bazel(toolchain_manifest, requested_bazel)
    resolved = root.resolve(strict=False)
    if resolved == repository or repository not in resolved.parents:
        raise ValueError("vendor directory must be below, but not equal to, the checkout")
    root = resolved
    root.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="mindclade-vendor-bazel-") as output_directory:
        output_user_root = Path(output_directory) / "output-user-root"
        repositories = target_repositories(repository, bazel, output_user_root)
        with tempfile.TemporaryDirectory(
            prefix=f".{root.name}-refresh-", dir=root.parent
        ) as directory:
            transaction = Path(directory)
            staged = transaction / "snapshot"
            staged.mkdir()
            subprocess.run(
                bazel_command(
                    bazel,
                    output_user_root,
                    "vendor",
                    f"--vendor_dir={staged}",
                    "--lockfile_mode=error",
                    "--remote_cache=",
                    "--remote_executor=",
                    *[f"--repo={name}" for name in repositories],
                ),
                cwd=repository,
                check=True,
            )
            write_manifest(staged, repository, toolchain_manifest)

            previous = transaction / "previous"
            had_previous = root.exists()
            with blocked_replacement_signals():
                try:
                    if had_previous:
                        root.replace(previous)
                    staged.replace(root)
                except BaseException:
                    if root.exists() and not staged.exists():
                        root.replace(staged)
                    if had_previous and previous.exists():
                        previous.replace(root)
                    raise


def offline(
    root: Path,
    repository: Path,
    toolchain_manifest: Mapping[str, Any],
    requested_bazel: str | None = None,
) -> None:
    toolchain_contract.validate_manifest(toolchain_manifest, verify_files=True)
    system, _, _ = toolchain_context(repository, toolchain_manifest)
    require_host_system(system, linux_only=True)
    verify(root, repository, toolchain_manifest)
    bazel = validated_bazel(toolchain_manifest, requested_bazel)
    unshare = nix_backed_unshare()
    with tempfile.TemporaryDirectory(prefix="mindclade-offline-") as directory:
        scratch = Path(directory)
        home = scratch / "home"
        home.mkdir()
        command = [
            unshare,
            "--user",
            "--map-root-user",
            "--net",
            bazel,
            "--nosystem_rc",
            "--nohome_rc",
            f"--output_user_root={scratch / 'output'}",
            "test",
            "--config=ci",
            "--config=offline",
            f"--vendor_dir={root}",
            f"--repository_cache={scratch / 'repository-cache'}",
            f"--repo_contents_cache={scratch / 'repo-contents-cache'}",
            "--repository_disable_download",
            "--lockfile_mode=error",
            "--remote_cache=",
            "--remote_executor=",
            "--disk_cache=",
            "--noremote_accept_cached",
            "--noremote_upload_local_results",
            TARGET,
        ]
        environment = {
            key: value
            for key, value in os.environ.items()
            if key.lower() not in {"http_proxy", "https_proxy", "all_proxy"}
        }
        environment.update(
            {
                "HOME": str(home),
                "XDG_CACHE_HOME": str(scratch / "xdg-cache"),
                "XDG_CONFIG_HOME": str(scratch / "xdg-config"),
            }
        )
        subprocess.run(command, cwd=repository, env=environment, check=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("refresh", "verify", "offline"))
    parser.add_argument("--root", type=Path, default=Path("third_party/bazel_vendor"))
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--bazel", default=os.environ.get("BAZEL"))
    parser.add_argument(
        "--manifest",
        type=Path,
        default=(
            Path(os.environ["MINDCLADE_TOOLCHAIN_MANIFEST"])
            if "MINDCLADE_TOOLCHAIN_MANIFEST" in os.environ
            else None
        ),
        help="mindclade-toolchain.v2 manifest (defaults to MINDCLADE_TOOLCHAIN_MANIFEST)",
    )
    args = parser.parse_args(argv)
    repository = args.repository.resolve()
    root = (
        (repository / args.root).resolve() if not args.root.is_absolute() else args.root.resolve()
    )
    try:
        if args.manifest is None:
            raise ValueError("--manifest or MINDCLADE_TOOLCHAIN_MANIFEST is required")
        toolchain_manifest = toolchain_contract.load_object(args.manifest.resolve())
        toolchain_contract.validate_manifest(toolchain_manifest, verify_files=True)
        if args.command == "refresh":
            refresh(root, repository, toolchain_manifest, args.bazel)
        elif args.command == "verify":
            verify(root, repository, toolchain_manifest)
        else:
            offline(root, repository, toolchain_manifest, args.bazel)
        print(f"Wave 1 vendor {args.command}: PASS")
        return 0
    except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
        print(f"Wave 1 vendor {args.command}: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
