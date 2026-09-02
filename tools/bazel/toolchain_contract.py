#!/usr/bin/env python3.12
"""Validate configured Bazel toolchains against the pinned Nix manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
SYSTEMS = {"aarch64-darwin", "aarch64-linux", "x86_64-linux"}
MANIFEST_FIELDS = {
    "schema_version",
    "repository",
    "system",
    "policy",
    "nixpkgs",
    "locks",
    "executables",
    "toolchain_digest",
}
CANONICAL_NIXPKGS = {
    "revision": "83199d0d373dd3ac2b9a1996b1d0263f76ab7a4c",
    "nar_hash": "sha256-VYXO0XZlgj06dxJZRhrD3WoSsvq/c7+/Akyoa22pefw=",
}
REQUIRED_EXECUTABLES = {
    "bazel",
    "cargo",
    "cc",
    "cxx",
    "go",
    "java",
    "just",
    "nix",
    "node",
    "pnpm",
    "python",
    "rustc",
    "rustdoc",
}
CONFIGURED_EXECUTABLES = {
    "cargo",
    "cc",
    "cxx",
    "go",
    "java",
    "node",
    "python",
    "rustc",
    "rustdoc",
}
BOOTSTRAP_EXECUTABLES = REQUIRED_EXECUTABLES - CONFIGURED_EXECUTABLES
PROBE_EXECUTABLES = CONFIGURED_EXECUTABLES | {"node_runtime"}
RESOLUTION_EXECUTABLES = REQUIRED_EXECUTABLES | {"node_runtime"}
LABEL = re.compile(r"^(?:@{0,2}[A-Za-z0-9_.+~-]+)?//[^\s]*:[^\s]+$|^nix-bootstrap://[a-z0-9._/-]+$")
NIX_STORE_PATH = re.compile(r"^(/nix/store/[^/]+)(?:/|$)")
TOOLCHAIN_TYPE_SUFFIXES = {
    "@bazel_tools//tools/cpp:toolchain_type": "//tools/cpp:toolchain_type",
    "@rules_go//go:toolchain": "//go:toolchain",
    "@bazel_tools//tools/jdk:runtime_toolchain_type": "//tools/jdk:runtime_toolchain_type",
    "@rules_nodejs//nodejs:toolchain_type": "//nodejs:toolchain_type",
    "@rules_nodejs//nodejs:runtime_toolchain_type": "//nodejs:runtime_toolchain_type",
    "@bazel_tools//tools/python:toolchain_type": "//tools/python:toolchain_type",
    "@rules_rust//rust:toolchain_type": "//rust:toolchain_type",
}
ALLOWED_SELECTED_LABELS = {
    "@bazel_tools//tools/cpp:toolchain_type": "rules_cc++cc_configure_extension+local_config_cc//",
    "@rules_go//go:toolchain": "rules_go++go_sdk+go_sdk//",
    "@bazel_tools//tools/jdk:runtime_toolchain_type": "rules_java++toolchains+local_jdk//",
    "@rules_nodejs//nodejs:toolchain_type": "+nix_toolchains_repository+nix_toolchains//",
    "@rules_nodejs//nodejs:runtime_toolchain_type": "+nix_toolchains_repository+nix_toolchains//",
    "@bazel_tools//tools/python:toolchain_type": "+nix_toolchains_repository+nix_toolchains//",
    "@rules_rust//rust:toolchain_type": "+nix_toolchains_repository+nix_toolchains//",
}
BANNED_TOOLCHAIN_REPOSITORIES = ("rules_nodejs++node+", "rules_rust++rust+")
PROBE_TARGET = "//tools:configured_toolchain_probe"


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def digest_object(value: Mapping[str, Any], digest_field: str) -> str:
    unsigned = {key: item for key, item in value.items() if key != digest_field}
    return "sha256:" + hashlib.sha256(canonical_json(unsigned)).hexdigest()


def file_digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return "sha256:" + hasher.hexdigest()


def load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain one JSON object")
    return cast(dict[str, Any], value)


def validate_manifest(manifest: Mapping[str, Any], *, verify_files: bool) -> None:
    if set(manifest) != MANIFEST_FIELDS:
        raise ValueError("toolchain manifest contains missing or unknown fields")
    if manifest.get("schema_version") != "mindclade-toolchain.v2":
        raise ValueError("toolchain manifest must use mindclade-toolchain.v2")
    if manifest.get("repository") != "mindclade/mindclade":
        raise ValueError("toolchain manifest repository is not canonical")
    if manifest.get("system") not in SYSTEMS:
        raise ValueError("toolchain manifest system is unsupported")
    if manifest.get("nixpkgs") != CANONICAL_NIXPKGS:
        raise ValueError("toolchain manifest Nixpkgs identity is not canonical")
    locks_value = manifest.get("locks")
    if not isinstance(locks_value, Mapping):
        raise ValueError("toolchain manifest must bind flake, module, and policy locks")
    locks = cast(Mapping[str, object], locks_value)
    if set(locks) != {"flake", "module", "policy"}:
        raise ValueError("toolchain manifest must bind flake, module, and policy locks")
    if any(not isinstance(value, str) or not DIGEST.fullmatch(value) for value in locks.values()):
        raise ValueError("toolchain lock digests must be canonical SHA-256 values")
    policy = manifest.get("policy")
    if not isinstance(policy, Mapping) or policy != {
        "authority_repository": "mindclade/.github",
        "authority_revision": "49a015c2c0cdd6a75a5756eb8c1e95b49d117917",
        "policy_digest": "sha256:f2cac5e9ef4933544b042b04b6efeddc74a81e533019a6d42ec19d17c37ab34b",
    }:
        raise ValueError("toolchain manifest does not bind the canonical estate policy")
    executables_value = manifest.get("executables")
    if not isinstance(executables_value, Mapping):
        raise ValueError("toolchain manifest lacks executable identities")
    executables = cast(Mapping[str, object], executables_value)
    if set(executables) != REQUIRED_EXECUTABLES:
        missing = sorted(REQUIRED_EXECUTABLES - set(executables))
        extra = sorted(set(executables) - REQUIRED_EXECUTABLES)
        raise ValueError(f"toolchain executables differ; missing={missing}, extra={extra}")
    for name, raw_value in executables.items():
        if not isinstance(raw_value, Mapping):
            raise ValueError(f"executable {name} is not an object")
        raw = cast(Mapping[str, object], raw_value)
        if set(raw) != {"path", "sha256", "store_path", "version"}:
            raise ValueError(f"executable {name} has unexpected fields")
        path = raw.get("path")
        store_path = raw.get("store_path")
        version = raw.get("version")
        digest = raw.get("sha256")
        if not isinstance(path, str) or not path.startswith("/nix/store/"):
            raise ValueError(f"executable {name} is not Nix-store backed")
        if not isinstance(store_path, str) or not store_path.startswith("/nix/store/"):
            raise ValueError(f"executable {name} store path is invalid")
        if not path.startswith(store_path.rstrip("/") + "/"):
            raise ValueError(f"executable {name} escapes its declared store path")
        if not isinstance(version, str) or not version:
            raise ValueError(f"executable {name} has an empty version")
        if not isinstance(digest, str) or not DIGEST.fullmatch(digest):
            raise ValueError(f"executable {name} has a noncanonical digest")
        executable = Path(path)
        if verify_files:
            if not executable.is_file():
                raise ValueError(f"executable {name} is unavailable at {executable}")
            if file_digest(executable) != digest:
                raise ValueError(f"executable {name} digest does not match its file")
    if manifest.get("toolchain_digest") != digest_object(manifest, "toolchain_digest"):
        raise ValueError("toolchain manifest digest does not bind canonical content")


def _run(command: list[str], *, description: str) -> subprocess.CompletedProcess[str]:
    process = subprocess.run(command, check=False, capture_output=True, text=True)
    if process.returncode != 0:
        detail = (process.stderr or process.stdout).strip().splitlines()
        raise ValueError(f"{description} failed: {detail[-1] if detail else 'no diagnostic'}")
    return process


def _toolchain_type(debug_type: str) -> str | None:
    for canonical, suffix in TOOLCHAIN_TYPE_SUFFIXES.items():
        if debug_type.endswith(suffix):
            return canonical
    return None


def parse_selected_labels(trace: str) -> dict[str, str]:
    selected: dict[str, set[str]] = {name: set() for name in TOOLCHAIN_TYPE_SUFFIXES}
    pattern = re.compile(r"type\s+(?P<type>@{1,2}\S+)\s+->\s+toolchain\s+(?P<label>@{1,2}\S+)")
    for match in pattern.finditer(trace):
        canonical_type = _toolchain_type(match.group("type"))
        if canonical_type:
            selected[canonical_type].add(match.group("label").rstrip(","))
    labels: dict[str, str] = {}
    for toolchain_type, values in selected.items():
        if len(values) != 1:
            raise ValueError(
                f"configured resolution for {toolchain_type} is not singular: {sorted(values)}"
            )
        label = next(iter(values))
        if any(fragment in label for fragment in BANNED_TOOLCHAIN_REPOSITORIES):
            raise ValueError(f"configured toolchain uses a downloaded compiler repository: {label}")
        if ALLOWED_SELECTED_LABELS[toolchain_type] not in label:
            raise ValueError(
                f"configured toolchain label is outside the Nix-backed contract: {label}"
            )
        labels[toolchain_type] = label
    return labels


def _replace_first_symlink(path: Path) -> Path | None:
    parts = path.parts
    current = Path(parts[0])
    for index, part in enumerate(parts[1:], start=1):
        current /= part
        if current.is_symlink():
            target = current.readlink()
            if not target.is_absolute():
                target = current.parent / target
            return target.joinpath(*parts[index + 1 :])
    return None


def selected_identity_path(raw_path: str, execution_root: Path) -> tuple[Path, Path]:
    provider_path = Path(raw_path)
    if not provider_path.is_absolute():
        provider_path = execution_root / provider_path
    provider_path = Path(provider_path)
    if not provider_path.exists():
        raise ValueError(f"configured provider path is unavailable: {raw_path}")
    candidate = provider_path
    for _ in range(32):
        if str(candidate).startswith("/nix/store/"):
            return candidate, provider_path.resolve()
        replacement = _replace_first_symlink(candidate)
        if replacement is None:
            break
        candidate = Path(replacement)
    resolved = provider_path.resolve()
    if str(resolved).startswith("/nix/store/"):
        return resolved, resolved
    raise ValueError(f"configured provider path is not backed by the Nix store: {raw_path}")


def _compiler_driver(
    provider_path: str, execution_root: Path, expected_path: str
) -> tuple[Path, Path]:
    path = Path(provider_path)
    if not path.is_absolute():
        path = execution_root / path
    path = Path(path)
    if not path.is_file():
        raise ValueError(f"configured C/C++ compiler wrapper is unavailable: {provider_path}")
    wrapper = path.read_text(encoding="utf-8")
    invocation = re.compile(rf"(?m)^\s*(?:exec\s+)?{re.escape(expected_path)}(?:\s+|\s*\\$)")
    if not invocation.search(wrapper):
        raise ValueError("configured C/C++ wrapper does not invoke the manifest compiler driver")
    return Path(expected_path), path.resolve()


def bootstrap_identity_path(raw_path: str, expected_path: str) -> tuple[Path, Path]:
    provider_path = Path(raw_path)
    if not provider_path.is_absolute():
        provider_path = provider_path.absolute()
    candidate = provider_path
    for _ in range(32):
        if str(candidate) == expected_path:
            return candidate, provider_path.resolve()
        replacement = _replace_first_symlink(candidate)
        if replacement is None:
            break
        candidate = Path(replacement)
    raise ValueError(
        f"bootstrap provider path does not resolve through the Nix manifest: "
        f"{provider_path} != {expected_path}"
    )


def _store_path(path: Path) -> str:
    match = NIX_STORE_PATH.match(str(path))
    if not match:
        raise ValueError(f"selected executable lacks a Nix store identity: {path}")
    return match.group(1)


def _version_matches(name: str, provider_version: str, manifest_version: str) -> bool:
    if not provider_version or name in {"cc", "cxx"}:
        return True
    if name == "java":
        return manifest_version == provider_version or manifest_version.startswith(
            provider_version + "."
        )
    return provider_version.removeprefix("go") == manifest_version


def _observe_configured(
    probe: Mapping[str, Any],
    manifest: Mapping[str, Any],
    labels: Mapping[str, str],
    execution_root: Path,
) -> dict[str, dict[str, str]]:
    if probe.get("schema_version") != "bazel-configured-toolchain-probe.v1":
        raise ValueError("configured toolchain probe schema is unsupported")
    tools_value = probe.get("tools")
    if not isinstance(tools_value, Mapping):
        raise ValueError("configured toolchain probe is incomplete")
    tools = cast(Mapping[str, Mapping[str, str]], tools_value)
    if set(tools) != PROBE_EXECUTABLES:
        raise ValueError("configured toolchain probe is incomplete")
    expected = cast(Mapping[str, Mapping[str, str]], manifest["executables"])
    observed: dict[str, dict[str, str]] = {}
    for name in sorted(tools):
        item = tools[name]
        expected_name = "node" if name == "node_runtime" else name
        if set(item) != {"path", "provider_version", "toolchain_type"}:
            raise ValueError(f"configured probe record for {name} has unexpected fields")
        toolchain_type = item["toolchain_type"]
        if toolchain_type not in labels:
            raise ValueError(f"configured probe record for {name} has an unknown toolchain type")
        if name in {"cc", "cxx"}:
            identity, provider_realpath = _compiler_driver(
                item["path"], execution_root, expected[expected_name]["path"]
            )
        else:
            identity, provider_realpath = selected_identity_path(item["path"], execution_root)
        if str(identity) != expected[expected_name]["path"]:
            raise ValueError(
                f"configured {name} path differs from Nix: "
                f"{identity} != {expected[expected_name]['path']}"
            )
        if _store_path(identity) != expected[expected_name]["store_path"]:
            raise ValueError(f"configured {name} store path differs from Nix")
        digest = file_digest(identity)
        if digest != expected[expected_name]["sha256"]:
            raise ValueError(f"configured {name} digest differs from Nix")
        provider_version = item["provider_version"]
        if not _version_matches(name, provider_version, expected[expected_name]["version"]):
            raise ValueError(f"configured {name} version differs from Nix")
        observed[name] = {
            "label": labels[toolchain_type],
            "observation": "configured-bazel-provider",
            "observed_path": str(identity),
            "observed_provider_path": item["path"],
            "observed_provider_realpath": str(provider_realpath),
            "observed_sha256": digest,
            "observed_store_path": _store_path(identity),
            "provider_version": provider_version,
            "toolchain_type": toolchain_type,
        }
    return observed


def _observe_bootstrap(manifest: Mapping[str, Any], bazel: Path) -> dict[str, dict[str, str]]:
    expected = cast(Mapping[str, Mapping[str, str]], manifest["executables"])
    observed: dict[str, dict[str, str]] = {}
    for name in sorted(BOOTSTRAP_EXECUTABLES):
        selected = str(bazel) if name == "bazel" else shutil.which(name)
        if not selected:
            raise ValueError(f"bootstrap executable {name} is unavailable")
        try:
            identity, provider_realpath = bootstrap_identity_path(selected, expected[name]["path"])
        except ValueError as error:
            raise ValueError(f"bootstrap {name} path differs from Nix: {error}") from error
        provider_path = Path(selected)
        if not provider_path.is_absolute():
            provider_path = provider_path.absolute()
        if _store_path(identity) != expected[name]["store_path"]:
            raise ValueError(f"bootstrap {name} store path differs from Nix")
        digest = file_digest(identity)
        if digest != expected[name]["sha256"]:
            raise ValueError(f"bootstrap {name} digest differs from Nix")
        observed[name] = {
            "label": f"nix-bootstrap://{name}",
            "observation": "nix-bootstrap-process",
            "observed_path": str(identity),
            "observed_provider_path": str(provider_path),
            "observed_provider_realpath": str(provider_realpath),
            "observed_sha256": digest,
            "observed_store_path": _store_path(identity),
            "provider_version": expected[name]["version"],
            "toolchain_type": "nix-bootstrap",
        }
    return observed


def build_resolution(
    manifest: Mapping[str, Any], observations: Mapping[str, Mapping[str, str]]
) -> dict[str, Any]:
    validate_manifest(manifest, verify_files=False)
    if set(observations) != RESOLUTION_EXECUTABLES:
        missing = sorted(RESOLUTION_EXECUTABLES - set(observations))
        extra = sorted(set(observations) - RESOLUTION_EXECUTABLES)
        raise ValueError(f"resolution observations differ; missing={missing}, extra={extra}")
    toolchains: list[dict[str, str]] = []
    for name in sorted(observations):
        item = dict(observations[name])
        label = item.get("label", "")
        if not LABEL.fullmatch(label):
            raise ValueError(f"toolchain {name} label is not canonical: {label}")
        toolchains.append({"name": name, **item})
    report: dict[str, Any] = {
        "schema_version": "bazel-toolchain-resolution.v1",
        "repository": manifest["repository"],
        "system": manifest["system"],
        "nix_toolchain_digest": manifest["toolchain_digest"],
        "probe_target": PROBE_TARGET,
        "toolchains": toolchains,
    }
    report["resolution_digest"] = digest_object(report, "resolution_digest")
    return report


def resolve_with_bazel(
    manifest: Mapping[str, Any], *, bazel: Path, probe_target: str = PROBE_TARGET
) -> dict[str, Any]:
    build = _run(
        [
            str(bazel),
            "build",
            probe_target,
            "--color=no",
            "--curses=no",
            "--toolchain_resolution_debug=.*(rules_rust|rules_nodejs|rules_go|tools/python|tools/jdk|tools/cpp).*",
        ],
        description="configured toolchain probe build",
    )
    labels = parse_selected_labels(build.stdout + "\n" + build.stderr)
    query = _run(
        [str(bazel), "cquery", probe_target, "--output=files", "--color=no", "--curses=no"],
        description="configured toolchain probe output query",
    )
    outputs = [line.strip() for line in query.stdout.splitlines() if line.strip()]
    if len(outputs) != 1:
        raise ValueError(f"configured toolchain probe has {len(outputs)} outputs")
    probe_path = Path(outputs[0])
    if not probe_path.is_file():
        raise ValueError(f"configured toolchain probe output is unavailable: {probe_path}")
    execution_root_process = _run(
        [str(bazel), "info", "execution_root"], description="Bazel execution-root query"
    )
    execution_root = Path(execution_root_process.stdout.strip())
    observations = _observe_configured(load_object(probe_path), manifest, labels, execution_root)
    observations.update(_observe_bootstrap(manifest, bazel))
    return build_resolution(manifest, observations)


def validate_resolution(resolution: Mapping[str, Any]) -> None:
    if resolution.get("schema_version") != "bazel-toolchain-resolution.v1":
        raise ValueError("Bazel resolution schema is unsupported")
    if resolution.get("repository") != "mindclade/mindclade":
        raise ValueError("Bazel resolution repository is not canonical")
    if resolution.get("system") not in SYSTEMS:
        raise ValueError("Bazel resolution system is unsupported")
    if resolution.get("probe_target") != PROBE_TARGET:
        raise ValueError("Bazel resolution did not use the canonical configured probe")
    if resolution.get("resolution_digest") != digest_object(resolution, "resolution_digest"):
        raise ValueError("Bazel resolution digest does not bind canonical content")
    toolchains_value = resolution.get("toolchains")
    if not isinstance(toolchains_value, list):
        raise ValueError("Bazel resolution has no toolchains")
    names: list[str] = []
    required_fields = {
        "label",
        "name",
        "observation",
        "observed_path",
        "observed_provider_path",
        "observed_provider_realpath",
        "observed_sha256",
        "observed_store_path",
        "provider_version",
        "toolchain_type",
    }
    toolchains = cast(list[object], toolchains_value)
    for item_value in toolchains:
        if not isinstance(item_value, Mapping):
            raise ValueError("Bazel resolution toolchain record is malformed")
        item = cast(Mapping[str, object], item_value)
        if set(item) != required_fields:
            raise ValueError("Bazel resolution toolchain record is malformed")
        name = item.get("name")
        if not isinstance(name, str):
            raise ValueError("Bazel resolution toolchain name is invalid")
        digest = item.get("observed_sha256")
        if not isinstance(digest, str) or not DIGEST.fullmatch(digest):
            raise ValueError(f"Bazel resolution digest for {name} is invalid")
        names.append(name)
    if names != sorted(RESOLUTION_EXECUTABLES):
        raise ValueError("Bazel resolution toolchains are incomplete or unordered")


def build_agreement(
    manifest: Mapping[str, Any], resolution: Mapping[str, Any], *, verify_files: bool
) -> dict[str, Any]:
    validate_manifest(manifest, verify_files=verify_files)
    validate_resolution(resolution)
    if resolution["system"] != manifest["system"]:
        raise ValueError("Bazel and Nix systems differ")
    if resolution["nix_toolchain_digest"] != manifest["toolchain_digest"]:
        raise ValueError("Bazel resolution does not bind this Nix manifest")
    nix_tools = cast(Mapping[str, Mapping[str, str]], manifest["executables"])
    for resolved in cast(list[Mapping[str, str]], resolution["toolchains"]):
        name = resolved["name"]
        expected = nix_tools["node" if name == "node_runtime" else name]
        if resolved["observed_path"] != expected["path"]:
            raise ValueError(f"{name} selected path differs between Bazel and Nix")
        if resolved["observed_store_path"] != expected["store_path"]:
            raise ValueError(f"{name} store path differs between Bazel and Nix")
        if resolved["observed_sha256"] != expected["sha256"]:
            raise ValueError(f"{name} digest differs between Bazel and Nix")
        if not _version_matches(name, resolved["provider_version"], expected["version"]):
            raise ValueError(f"{name} version differs between Bazel and Nix")
    report: dict[str, Any] = {
        "schema_version": "bazel-native-agreement.v2",
        "conclusion": "PASS",
        "repository": manifest["repository"],
        "system": manifest["system"],
        "nix_toolchain_digest": manifest["toolchain_digest"],
        "bazel_resolution_digest": resolution["resolution_digest"],
        "toolchains": resolution["toolchains"],
    }
    report["agreement_digest"] = digest_object(report, "agreement_digest")
    return report


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate")
    validate.add_argument("--manifest", type=Path, required=True)
    validate.add_argument("--verify-files", action="store_true")
    resolve = commands.add_parser("resolve")
    resolve.add_argument("--manifest", type=Path, required=True)
    resolve.add_argument("--bazel", type=Path, required=True)
    resolve.add_argument("--output", type=Path, required=True)
    agreement = commands.add_parser("agreement")
    agreement.add_argument("--manifest", type=Path, required=True)
    agreement.add_argument("--resolution", type=Path, required=True)
    agreement.add_argument("--output", type=Path, required=True)
    agreement.add_argument("--verify-files", action="store_true")
    return root


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        manifest = load_object(args.manifest)
        if args.command == "validate":
            validate_manifest(manifest, verify_files=args.verify_files)
            print("mindclade-toolchain.v2: PASS")
            return 0
        if args.command == "resolve":
            report = resolve_with_bazel(manifest, bazel=args.bazel)
        else:
            report = build_agreement(
                manifest, load_object(args.resolution), verify_files=args.verify_files
            )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(canonical_json(report) + b"\n")
        return 0
    except (KeyError, OSError, ValueError, json.JSONDecodeError) as error:
        print(f"toolchain contract: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
