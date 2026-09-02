#!/usr/bin/env python3.12
"""Atomically generate every descriptor-bound contract projection and manifest."""

from __future__ import annotations

import argparse
import base64
import fcntl
import hashlib
import importlib.metadata
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from collections import defaultdict
from collections.abc import Generator, Mapping, Sequence
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, cast

import yaml
from google.protobuf import descriptor as protobuf_descriptor
from google.protobuf import descriptor_pb2, descriptor_pool, message_factory
from google.protobuf import message as protobuf_message

GENERATOR = "mindclade-contract-codegen 3.1.0"
LANGUAGES = ("go", "python", "rust", "typescript")
PROTOBUF_CANDIDATE = Path("protocols/compatibility/baselines/protobuf.candidate.json")
PROTOBUF_PREDECESSOR = Path("protocols/compatibility/baselines/protobuf.predecessor.lock.json")
PROTOBUF_RATIFIED_BASELINE = Path("protocols/compatibility/baselines/protobuf.lock.json")
OPENAPI_CANDIDATE = Path("protocols/compatibility/baselines/openapi.lock.json")
PUBLISHED_OPENAPI = Path("protocols/openapi/published/mindclade.openapi.yaml")
EVENT_REGISTRY = Path("protocols/events/registry.yaml")
TOOLCHAIN_LOCK = Path("tools/codegen/toolchain.lock.json")
GENERATED_MANIFEST = Path("protocols/generated/generated-files.manifest.json")
SDK_RPC_COVERAGE = Path("internal/sdk/rpc-coverage.generated.json")
GRPC_IMPLEMENTATION_COVERAGE = Path("services/control_plane/grpc-implementation.generated.json")
PREDECESSOR_ARTIFACT_DIGEST = (
    "sha256:07d7ee37e68211870861b7fc1ec5118c423447319603523bd9589c1c5dea6aaf"
)
PREDECESSOR_DESCRIPTOR_DIGEST = (
    "sha256:c817a8313d6378738386f6733337fd54fbeb37c38ddf86ac79859f10afb471d9"
)
PREDECESSOR_REVISION = "9b5fbea8a44b15c291c6fd6247a57ad350487544"
TRAINING_VERTICAL_EVIDENCE_CHECKS = frozenset(
    {"cross_language", "database", "event", "gateway", "grpc", "sdk"}
)
RATIFICATION_BINDING_FIELDS = frozenset(
    {
        "candidate_descriptor_digest",
        "codegen_toolchain_digest",
        "event_registry_digest",
        "generated_manifest_digest",
        "grpc_implementation_digest",
        "migration_set_digest",
        "openapi_projection_digest",
        "sdk_package_digests",
        "sdk_rpc_coverage_digest",
        "source_revision",
    }
)
EVENT_CONTENT_TYPE = "application/x-protobuf; deterministic=true"
EVENT_LIFECYCLE_STATES = frozenset({"active", "candidate", "deprecated", "retired"})
EVENT_COMPATIBILITY_POLICIES = frozenset({"exact-version"})
EVENT_ACTIVATION_GAPS = frozenset({"fixture", "producer", "semantic-consumer"})
EVENT_PRODUCER_MODES = frozenset({"durable-audit", "transactional-outbox"})
EVENT_CONSUMER_MODES = frozenset({"semantic-inbox"})
EVENT_FIXTURE_MODES = frozenset({"populated-protobuf-roundtrip", "transactional-outbox-roundtrip"})
EVENT_OWNER = re.compile(r"^[a-z0-9](?:[a-z0-9._/-]*[a-z0-9])?$")
EVENT_ENDPOINT_ID = re.compile(r"^[a-z0-9](?:[a-z0-9._/-]*[a-z0-9])?$")
BAZEL_TARGET = re.compile(r"^//(?P<package>[A-Za-z0-9_./-]+):(?P<name>[A-Za-z0-9_.+-]+)$")
PROTO_SUFFIX = {"go": ".pb.go", "python": "_pb2.py", "rust": ".rs", "typescript": "_pb.ts"}
GENERATED_SUFFIXES = {
    "go": (".pb.go", "_grpc.pb.go"),
    "python": ("_pb2.py", "_pb2.pyi", "_pb2_grpc.py", "_pb2_grpc.pyi"),
    "typescript": ("_pb.ts",),
}
TS_IMPORT = re.compile(r'from "(?P<path>[^"]+_pb)\.js"')
RUST_TONIC_INCLUDE = re.compile(r'^include!\("[^"]+\.tonic\.rs"\);\n?', re.MULTILINE)
HAND_AUTHORED_GENERATED_PATHS = frozenset(
    {
        Path("protocols/generated/python/pyproject.toml"),
        Path("protocols/generated/rust/Cargo.toml"),
        Path("protocols/generated/typescript/package.json"),
        Path("protocols/generated/typescript/tsconfig.json"),
    }
)
GENERATED_METADATA_NAMES = frozenset(
    {
        "BUILD.bazel",
        "README.generated.md",
        "README.md",
        "generated-files.manifest.json",
        "__init__.py",
        "index.ts",
        "lib.rs",
        "mod.rs",
    }
)


@dataclass(frozen=True, slots=True)
class EventEvidenceEndpoint:
    endpoint_id: str
    source: str
    target: str
    mode: str


@dataclass(frozen=True, slots=True)
class EventFixtureEvidence:
    status: str
    source: str = ""
    target: str = ""
    mode: str = ""
    reason: str = ""


@dataclass(frozen=True, slots=True)
class EventRegistryEntry:
    full_name: str
    version: int
    content_type: str
    source: str
    owner: str
    lifecycle_state: str
    compatibility_policy: str
    fixture: EventFixtureEvidence
    producers: tuple[EventEvidenceEndpoint, ...]
    consumers: tuple[EventEvidenceEndpoint, ...]
    activation_gaps: tuple[str, ...]


class _PublicStringEnumContract(Protocol):
    field: str
    values: Sequence[str]


class _PublicMessageContract(Protocol):
    required_fields: Sequence[str]
    string_enums: Sequence[_PublicStringEnumContract]


class _GoogleHTTPRule(Protocol):
    body: str


class _PublicHTTPContract(Protocol):
    bearer_auth: bool
    non_success_status: Sequence[int]
    request_body_required: bool
    request_headers: Sequence[str]
    required_request_headers: Sequence[str]
    response_headers: Sequence[str]
    stream: int
    success_status: Sequence[int]


def sha256_bytes(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def run(
    command: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str] | None = None,
    input_bytes: bytes | None = None,
) -> subprocess.CompletedProcess[bytes]:
    merged_env = dict(os.environ)
    merged_env.update(
        {
            "BUF_CACHE_DIR": str(cwd / "build" / "buf-cache"),
            "CARGO_HOME": str(cwd / "build" / "cargo-home"),
            "GOCACHE": str(cwd / "build" / "go-cache"),
            "GOTOOLCHAIN": "local",
            "LANG": "C",
            "LC_ALL": "C",
            "SOURCE_DATE_EPOCH": "0",
            "TZ": "UTC",
        }
    )
    if env is not None:
        merged_env.update(env)
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=merged_env,
        input=input_bytes,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(
            f"command failed ({completed.returncode}): {' '.join(command)}\n{detail}"
        )
    return completed


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return cast(dict[str, Any], value)


def toolchain(root: Path) -> dict[str, Any]:
    lock = load_json(root / "tools/codegen/toolchain.lock.json")
    if lock.get("schema_version") != "mindclade.codegen-toolchain/v3":
        raise ValueError("unsupported code-generation toolchain lock")
    return lock


def command_version(command: Sequence[str], root: Path) -> str:
    completed = run(command, cwd=root)
    return (completed.stdout + completed.stderr).decode("utf-8").strip().splitlines()[-1]


def rust_plugin_cache_digest(
    root: Path, lock: Mapping[str, Any], rust_toolchain: Mapping[str, str]
) -> str:
    inputs = (
        Path("Cargo.toml"),
        Path("Cargo.lock"),
        Path("tools/codegen/rust_plugins/Cargo.toml"),
        Path("tools/codegen/rust_plugins/src/bin/protoc-gen-prost.rs"),
        Path("tools/codegen/rust_plugins/src/bin/protoc-gen-tonic.rs"),
    )
    material = {
        "schema_version": "mindclade.rust-protobuf-plugin-cache/v1",
        "platform": {"system": sys.platform, "machine": os.uname().machine},
        "rust_toolchain": dict(sorted(rust_toolchain.items())),
        "locked_plugins": {
            name: cast(Mapping[str, Any], lock["tools"])[name]
            for name in ("protoc-gen-prost", "protoc-gen-tonic")
        },
        "inputs": {path.as_posix(): sha256_file(root / path) for path in inputs},
    }
    return sha256_bytes(json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def validate_rust_plugin_cache(
    root: Path,
    cache_root: Path,
    cache_digest: str,
    tools: Mapping[str, Mapping[str, str]],
) -> Path:
    marker_path = cache_root / "receipt.json"
    if not marker_path.is_file():
        raise RuntimeError(f"Rust protobuf plugin cache is incomplete: {cache_root}")
    marker = load_json(marker_path)
    if (
        marker.get("schema_version") != "mindclade.rust-protobuf-plugin-cache/v1"
        or marker.get("cache_digest") != cache_digest
    ):
        raise RuntimeError(f"Rust protobuf plugin cache receipt is invalid: {cache_root}")
    raw_binaries = marker.get("binaries")
    if not isinstance(raw_binaries, dict):
        raise RuntimeError(f"Rust protobuf plugin cache has no binary inventory: {cache_root}")
    binaries = cast(dict[str, object], raw_binaries)
    binary_root = cache_root / "bin"
    for name in ("protoc-gen-prost", "protoc-gen-tonic"):
        binary = binary_root / name
        raw_evidence = binaries.get(name)
        evidence = cast(dict[str, object], raw_evidence) if isinstance(raw_evidence, dict) else None
        if (
            not binary.is_file()
            or evidence is None
            or evidence.get("digest") != sha256_file(binary)
            or evidence.get("version") != tools[name]["version_output"]
        ):
            raise RuntimeError(f"Rust protobuf plugin cache binary is invalid: {binary}")
        actual = command_version([str(binary), "--version"], root)
        if actual != tools[name]["version_output"]:
            raise RuntimeError(
                f"{name} cached version mismatch: expected {tools[name]['version_output']!r}, "
                f"got {actual!r}"
            )
    return binary_root


def install_rust_plugin_cache(
    root: Path,
    built_binary_root: Path,
    cache_root: Path,
    cache_digest: str,
    tools: Mapping[str, Mapping[str, str]],
) -> Path:
    cache_parent = cache_root.parent
    cache_parent.mkdir(parents=True, exist_ok=True)
    if cache_root.exists():
        return validate_rust_plugin_cache(root, cache_root, cache_digest, tools)
    with tempfile.TemporaryDirectory(prefix=".rust-plugin-install-", dir=cache_parent) as temporary:
        payload = Path(temporary) / "payload"
        binary_root = payload / "bin"
        binary_root.mkdir(parents=True)
        binary_evidence: dict[str, dict[str, str]] = {}
        for name in ("protoc-gen-prost", "protoc-gen-tonic"):
            source = built_binary_root / name
            target = binary_root / name
            shutil.copy2(source, target)
            binary_evidence[name] = {
                "digest": sha256_file(target),
                "version": tools[name]["version_output"],
            }
        receipt = {
            "schema_version": "mindclade.rust-protobuf-plugin-cache/v1",
            "cache_digest": cache_digest,
            "binaries": binary_evidence,
        }
        (payload / "receipt.json").write_text(
            json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        with suppress(FileExistsError):
            payload.rename(cache_root)
    return validate_rust_plugin_cache(root, cache_root, cache_digest, tools)


def ensure_toolchain(root: Path, staging: Path, lock: Mapping[str, Any]) -> Path:
    tools = cast(dict[str, dict[str, str]], lock["tools"])
    actual_versions = {
        "buildifier": command_version(["buildifier", "--version"], root),
        "buf": command_version(["buf", "--version"], root),
        "protoc": command_version(["protoc", "--version"], root),
        "protoc-gen-go": command_version(["go", "tool", "protoc-gen-go", "--version"], root),
        "protoc-gen-go-grpc": command_version(
            ["go", "tool", "protoc-gen-go-grpc", "--version"], root
        ),
        "protoc-gen-es": command_version(["node_modules/.bin/protoc-gen-es", "--version"], root),
        "rustfmt": command_version(["rustfmt", "--version"], root),
    }
    for name, actual in actual_versions.items():
        wanted = tools[name]["version_output"]
        if actual != wanted:
            raise RuntimeError(f"{name} version mismatch: expected {wanted!r}, got {actual!r}")

    cargo_lock = tomllib.loads((root / "Cargo.lock").read_text(encoding="utf-8"))
    raw_packages = cargo_lock.get("package")
    if not isinstance(raw_packages, list):
        raise ValueError("Cargo.lock does not contain a package closure")
    packages = [
        cast(dict[str, Any], value)
        for value in cast(list[object], raw_packages)
        if isinstance(value, dict)
    ]
    for tool_name in ("protoc-gen-prost", "protoc-gen-tonic"):
        rust = tools[tool_name]
        matches = [
            package
            for package in packages
            if package.get("name") == rust["package"] and package.get("version") == rust["version"]
        ]
        if len(matches) != 1 or matches[0].get("checksum") != rust["checksum"]:
            raise RuntimeError(f"{tool_name} is not bound to the recorded Cargo.lock checksum")

    python_versions = {
        "grpcio-tools": importlib.metadata.version("grpcio-tools"),
        "mypy-protobuf": importlib.metadata.version("mypy-protobuf"),
    }
    for name, actual in python_versions.items():
        if actual != tools[name]["version"]:
            raise RuntimeError(
                f"{name} version mismatch: expected {tools[name]['version']!r}, got {actual!r}"
            )

    rust_toolchain = {
        "cargo": (run(["cargo", "--version"], cwd=root).stdout).decode("utf-8").strip(),
        "rustc": (run(["rustc", "--version", "--verbose"], cwd=root).stdout)
        .decode("utf-8")
        .strip(),
    }
    cache_digest = rust_plugin_cache_digest(root, lock, rust_toolchain)
    cache_root = root / "build/codegen/rust-protobuf-plugins" / cache_digest.removeprefix("sha256:")
    if cache_root.exists():
        return validate_rust_plugin_cache(root, cache_root, cache_digest, tools)

    target = staging / "toolchain" / "rust-target"
    run(
        [
            "cargo",
            "build",
            "--locked",
            "--release",
            "--package",
            "mindclade-protoc-plugins",
            "--bins",
        ],
        cwd=root,
        env={"CARGO_TARGET_DIR": str(target)},
    )
    built_binary_root = target / "release"
    for name in ("protoc-gen-prost", "protoc-gen-tonic"):
        binary = built_binary_root / name
        if not binary.is_file():
            raise RuntimeError(f"cargo did not build the locked {name} binary")
        actual = command_version([str(binary), "--version"], root)
        if actual != tools[name]["version_output"]:
            raise RuntimeError(
                f"{name} version mismatch: expected {tools[name]['version_output']!r}, "
                f"got {actual!r}"
            )
    return install_rust_plugin_cache(root, built_binary_root, cache_root, cache_digest, tools)


def build_descriptors(root: Path, staging: Path) -> tuple[bytes, list[dict[str, Any]]]:
    binary_path = staging / "descriptor-set.binpb"
    json_path = staging / "descriptor-set.json"
    common = ["buf", "build", "--exclude-source-info", "--as-file-descriptor-set"]
    run([*common, "-o", str(json_path)], cwd=root)
    run(
        ["buf", "build", str(json_path), "--as-file-descriptor-set", "-o", str(binary_path)],
        cwd=root,
    )
    descriptor = load_json(json_path)
    files = descriptor.get("file")
    if not isinstance(files, list):
        raise ValueError("Buf descriptor set does not contain a file list")
    raw_files = cast(list[object], files)
    all_files = [cast(dict[str, Any], item) for item in raw_files if isinstance(item, dict)]
    if len(all_files) != len(raw_files):
        raise ValueError("Buf descriptor set contains a non-object file descriptor")
    managed = [
        descriptor
        for descriptor in all_files
        if isinstance(descriptor.get("name"), str)
        and cast(str, descriptor["name"]).startswith(("proto/mindclade/", "events/mindclade/"))
    ]
    return binary_path.read_bytes(), managed


def projection_parts(package: str) -> tuple[str, ...]:
    """Return the committed binding namespace for one Protobuf package."""
    parts = package.split(".")
    if len(parts) < 3 or parts[0] != "mindclade" or parts[-1] != "v1":
        raise ValueError(f"unsupported Protobuf package: {package}")
    if parts[1] == "internal":
        if len(parts) != 4:
            raise ValueError(f"unsupported internal Protobuf package: {package}")
        return ("internal", parts[2], "v1")
    if parts[1] == "events":
        if len(parts) != 4:
            raise ValueError(f"unsupported event Protobuf package: {package}")
        return (parts[2], "v1")
    if len(parts) != 3:
        raise ValueError(f"unsupported Protobuf package: {package}")
    return (parts[1], "v1")


def go_projection_parts(package: str) -> tuple[str, ...]:
    """Return a Go-importable projection path for one Protobuf package.

    Go reserves a path segment named ``internal`` for compiler-enforced import
    visibility. The protobuf namespace remains ``mindclade.internal.*`` while
    its Go projection uses ``internalrpc`` so control-plane and worker packages
    can consume the generated interfaces.
    """
    parts = projection_parts(package)
    if parts[0] == "internal":
        return ("internalrpc", *parts[1:])
    return parts


def projection_path(package: str) -> Path:
    return Path(*projection_parts(package))


def python_projection_parts(package: str) -> tuple[str, ...]:
    """Keep the canonical Protobuf root in Python import and filesystem paths."""
    return ("mindclade", *projection_parts(package))


def source_path(root: Path, descriptor: Mapping[str, Any]) -> Path:
    name = descriptor.get("name")
    if not isinstance(name, str):
        raise ValueError("file descriptor is missing its name")
    return root / "protocols" / name


def declared_languages(lock: Mapping[str, Any], package: str) -> frozenset[str]:
    matrix = cast(dict[str, list[str]], lock["domain_language_matrix"])
    raw_default = lock.get("default_languages")
    if not isinstance(raw_default, list):
        raise ValueError("toolchain lock has no default language policy")
    default_languages = cast(list[object], raw_default)
    if not all(isinstance(value, str) for value in default_languages):
        raise ValueError("toolchain lock has no default language policy")
    values = matrix.get(package, cast(list[str], default_languages))
    unknown = set(values).difference(LANGUAGES)
    if unknown:
        raise ValueError(f"unsupported languages for {package}: {sorted(unknown)}")
    return frozenset(values)


def validate_manifest(
    root: Path,
    descriptors: Sequence[Mapping[str, Any]],
    outputs: Mapping[Path, bytes] | None = None,
) -> None:
    raw = yaml.safe_load(
        (root / "docs/architecture/repository-path-manifest.yaml").read_text(encoding="utf-8")
    )
    if not isinstance(raw, dict):
        raise ValueError("repository path manifest has an invalid shape")
    manifest = cast(dict[str, object], raw)
    raw_paths = manifest.get("paths")
    if not isinstance(raw_paths, list):
        raise ValueError("repository path manifest has an invalid shape")
    entries: dict[str, dict[str, Any]] = {}
    for value in cast(list[object], raw_paths):
        if not isinstance(value, dict):
            continue
        entry = cast(dict[str, object], value)
        path = entry.get("path")
        if isinstance(path, str):
            entries[path] = cast(dict[str, Any], value)
    for descriptor in descriptors:
        relative = source_path(root, descriptor).relative_to(root).as_posix()
        entry = entries.get(relative)
        if entry is None or entry.get("status") != "active":
            raise ValueError(f"Protobuf source is not active in the path manifest: {relative}")
    if outputs is None:
        return
    for path in outputs:
        relative = path.relative_to(root).as_posix()
        entry = entries.get(relative)
        if entry is None or entry.get("status") != "generated":
            raise ValueError(f"generated output is not governed as generated: {relative}")


def governed_generated_paths(root: Path) -> set[Path]:
    raw = yaml.safe_load(
        (root / "docs/architecture/repository-path-manifest.yaml").read_text(encoding="utf-8")
    )
    if not isinstance(raw, dict):
        raise ValueError("repository path manifest has an invalid shape")
    manifest = cast(dict[str, object], raw)
    raw_paths = manifest.get("paths")
    if not isinstance(raw_paths, list):
        raise ValueError("repository path manifest has an invalid shape")
    paths: set[Path] = set()
    for value in cast(list[object], raw_paths):
        if not isinstance(value, dict):
            continue
        entry = cast(dict[str, object], value)
        path = entry.get("path")
        if (
            entry.get("status") == "generated"
            and isinstance(path, str)
            and path.startswith("protocols/generated/")
        ):
            paths.add(root / path)
    return paths


def previous_generated_paths(root: Path) -> set[Path]:
    manifest_path = root / "protocols/generated/generated-files.manifest.json"
    if not manifest_path.is_file():
        return set()
    manifest = load_json(manifest_path)
    raw_files = manifest.get("files")
    if not isinstance(raw_files, dict):
        raise ValueError("generated file manifest has no files object")
    paths: set[Path] = set()
    external_allowlist = {
        GRPC_IMPLEMENTATION_COVERAGE,
        OPENAPI_CANDIDATE,
        PROTOBUF_CANDIDATE,
        SDK_RPC_COVERAGE,
        Path("protocols/openapi/curated/mindclade.openapi.yaml"),
        Path("protocols/openapi/published/mindclade.openapi.yaml"),
        Path("protocols/openapi/raw/mindclade.openapi.yaml"),
        Path("services/control_plane/internal/platform/queue/event_registry_generated.go"),
    }
    for value in cast(dict[str, object], raw_files):
        relative = Path(value)
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or (
                relative.parts[:2] != ("protocols", "generated")
                and relative not in external_allowlist
            )
        ):
            raise ValueError(f"unsafe prior generated path: {value}")
        paths.add(root / relative)
    return paths


def discovered_generated_paths(root: Path) -> set[Path]:
    """Find generator-owned files even when an older manifest no longer lists them."""
    generated_root = root / "protocols/generated"
    paths: set[Path] = set()
    for path in generated_root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if relative in HAND_AUTHORED_GENERATED_PATHS:
            continue
        if path.name in GENERATED_METADATA_NAMES or path.name.endswith(
            (".pb.go", ".py", ".pyi", ".rs", ".ts")
        ):
            paths.add(path)
    return paths


def plugin_config(root: Path, language: str, output: Path) -> dict[str, Any]:
    config = load_json(root / "buf.gen.yaml")
    plugins = config.get("plugins")
    if not isinstance(plugins, list):
        raise ValueError("buf.gen.yaml must declare plugins")
    selected_plugins: list[dict[str, Any]] = []
    for raw_plugin in cast(list[object], plugins):
        if not isinstance(raw_plugin, dict):
            continue
        plugin = cast(dict[str, object], raw_plugin)
        out = plugin.get("out")
        if isinstance(out, str) and Path(out).name == language:
            selected = cast(dict[str, Any], dict(plugin))
            selected["out"] = str(output)
            selected_plugins.append(selected)
    if not selected_plugins:
        raise ValueError(f"buf.gen.yaml has no {language} plugin")
    return {"version": "v2", "clean": True, "plugins": selected_plugins}


def generate_language(
    root: Path,
    staging: Path,
    language: str,
    descriptors: Sequence[Mapping[str, Any]],
    lock: Mapping[str, Any],
    rust_plugin_path: Path,
) -> Path:
    raw_root = staging / "raw" / language
    selected = [
        descriptor
        for descriptor in descriptors
        if language in declared_languages(lock, cast(str, descriptor["package"]))
    ]
    path_env = os.pathsep.join([str(rust_plugin_path), os.environ.get("PATH", "")])

    groups: dict[str, list[Mapping[str, Any]]]
    if language == "rust":
        groups = {}
        for descriptor in selected:
            package_path = projection_path(cast(str, descriptor["package"]))
            stem = Path(cast(str, descriptor["name"])).stem
            groups[f"{'-'.join(package_path.parts)}-{stem}"] = [descriptor]
    else:
        groups = {language: selected}

    for group, group_descriptors in sorted(groups.items()):
        if language == "rust":
            descriptor = group_descriptors[0]
            output = (
                raw_root
                / projection_path(cast(str, descriptor["package"]))
                / Path(cast(str, descriptor["name"])).stem
            )
        else:
            output = raw_root
        template = staging / f"buf.{language}.{group}.json"
        template.write_text(
            json.dumps(plugin_config(root, language, output), sort_keys=True), encoding="utf-8"
        )
        command = ["buf", "generate", "protocols", "--template", str(template)]
        if language == "typescript":
            command.append("--include-imports")
        for descriptor in group_descriptors:
            command.extend(["--path", f"protocols/{cast(str, descriptor['name'])}"])
        run(command, cwd=root, env={"PATH": path_env})

    if language == "python":
        grpc_sources = [
            f"protocols/{cast(str, descriptor['name'])}"
            for descriptor in selected
            if descriptor.get("service")
        ]
        if grpc_sources:
            raw_buf_lock: object = yaml.safe_load((root / "buf.lock").read_text(encoding="utf-8"))
            if not isinstance(raw_buf_lock, dict):
                raise ValueError("buf.lock has no dependency closure")
            buf_lock = cast(dict[str, object], raw_buf_lock)
            dependencies = buf_lock.get("deps")
            if not isinstance(dependencies, list):
                raise ValueError("buf.lock has no dependency closure")
            googleapis = next(
                dependency
                for dependency in cast(list[dict[str, str]], dependencies)
                if dependency.get("name") == "buf.build/googleapis/googleapis"
            )
            googleapis_root = staging / "external" / "googleapis"
            run(
                [
                    "buf",
                    "export",
                    f"{googleapis['name']}:{googleapis['commit']}",
                    "--path",
                    "google/api/annotations.proto",
                    "--path",
                    "google/api/http.proto",
                    "--output",
                    str(googleapis_root),
                ],
                cwd=root,
            )
            python_bin = Path(sys.executable).parent
            mypy_grpc = shutil.which("protoc-gen-mypy_grpc", path=str(python_bin))
            if mypy_grpc is None:
                raise RuntimeError("locked protoc-gen-mypy_grpc is not available")
            run(
                [
                    sys.executable,
                    "-m",
                    "grpc_tools.protoc",
                    "-Iprotocols",
                    f"-I{googleapis_root}",
                    f"--grpc_python_out={raw_root}",
                    f"--mypy_grpc_out={raw_root}",
                    f"--plugin=protoc-gen-mypy_grpc={mypy_grpc}",
                    *grpc_sources,
                ],
                cwd=root,
            )
    return raw_root


def target_path(
    root: Path,
    language: str,
    descriptor: Mapping[str, Any],
    suffix: str | None = None,
) -> Path:
    package = cast(str, descriptor["package"])
    if language == "python":
        parts = python_projection_parts(package)
    elif language == "go":
        parts = go_projection_parts(package)
    else:
        parts = projection_parts(package)
    package_path = Path(*parts)
    stem = Path(cast(str, descriptor["name"])).stem
    resolved_suffix = PROTO_SUFFIX[language] if suffix is None else suffix
    return root / "protocols/generated" / language / package_path / f"{stem}{resolved_suffix}"


def raw_path(raw_root: Path, language: str, descriptor: Mapping[str, Any]) -> Path:
    source = Path(cast(str, descriptor["name"]))
    if language == "rust":
        generated_root = raw_root / projection_path(cast(str, descriptor["package"])) / source.stem
        candidates = sorted(
            path for path in generated_root.rglob("*.rs") if not path.name.endswith(".tonic.rs")
        )
        if len(candidates) != 1:
            raise ValueError(
                f"expected one Prost output for {descriptor['name']}, found {len(candidates)}"
            )
        return candidates[0]
    return raw_root / source.parent / f"{source.stem}{PROTO_SUFFIX[language]}"


def raw_variant_path(
    raw_root: Path,
    language: str,
    descriptor: Mapping[str, Any],
    suffix: str,
) -> Path:
    source = Path(cast(str, descriptor["name"]))
    if language == "rust":
        generated_root = raw_root / projection_path(cast(str, descriptor["package"])) / source.stem
        candidates = sorted(generated_root.rglob("*.tonic.rs"))
        if len(candidates) != 1:
            return generated_root / "missing.tonic.rs"
        return candidates[0]
    return raw_root / source.parent / f"{source.stem}{suffix}"


def python_module(source: str) -> str:
    path = Path(source)
    return ".".join((*path.parent.parts, f"{path.stem}_pb2"))


def target_python_module(descriptor: Mapping[str, Any]) -> str:
    return ".".join(
        (
            *python_projection_parts(cast(str, descriptor["package"])),
            f"{Path(cast(str, descriptor['name'])).stem}_pb2",
        )
    )


def normalize_python(content: str, descriptors: Sequence[Mapping[str, Any]]) -> str:
    replacements: list[tuple[str, str]] = []
    for item in descriptors:
        source = Path(cast(str, item["name"]))
        old_module = python_module(cast(str, item["name"]))
        new_module = target_python_module(item)
        replacements.append((old_module, new_module))
        old_package = ".".join(source.parent.parts)
        generated_name = f"{source.stem}_pb2"
        content = content.replace(
            f"from {old_package} import {generated_name}",
            f"from {'.'.join(python_projection_parts(cast(str, item['package'])))} "
            f"import {generated_name}",
        )
    for old, new in sorted(replacements, key=lambda pair: len(pair[0]), reverse=True):
        content = content.replace(old, new)
    prefix = content[:8192].lower()
    if not any(marker in prefix for marker in ("generated", "do not edit")):
        content = f"# Code generated by {GENERATOR}; DO NOT EDIT.\n{content}"
    return content


def isolate_rust_source(
    content: str,
    descriptor: Mapping[str, Any],
    by_name: Mapping[str, Mapping[str, Any]],
) -> str:
    """Keep only the Prost declarations owned by one source descriptor.

    protoc-gen-prost emits one Rust file per Protobuf package. A Buf request for a
    single source still contains its imports, so same-package imports are prepended
    to that file. The committed projection intentionally remains source-relative;
    strip the prepended declarations while retaining references to the authoritative
    definitions included by the package module.
    """
    package = descriptor.get("package")
    dependencies = descriptor.get("dependency", [])
    if not isinstance(package, str) or not isinstance(dependencies, list):
        raise ValueError("descriptor package or dependency list is invalid")
    has_same_package_dependency = any(
        isinstance(dependency, str)
        and dependency in by_name
        and by_name[dependency].get("package") == package
        for dependency in cast(list[object], dependencies)
    )
    if not has_same_package_dependency:
        return content

    declarations = descriptor.get("messageType") or descriptor.get("enumType")
    if not isinstance(declarations, list) or not declarations:
        return content
    first_declaration = cast(list[object], declarations)[0]
    if not isinstance(first_declaration, dict):
        raise ValueError(f"descriptor has an invalid Rust declaration: {descriptor.get('name')}")
    declaration = cast(dict[str, object], first_declaration)
    name = declaration.get("name")
    if not isinstance(name, str):
        raise ValueError(f"descriptor has an invalid Rust declaration: {descriptor.get('name')}")
    declaration = re.search(
        rf"^pub (?:struct|enum) {re.escape(name)} \{{",
        content,
        flags=re.MULTILINE,
    )
    if declaration is None:
        raise ValueError(
            f"generated Rust output has no declaration for {name}: {descriptor.get('name')}"
        )

    lines = content.splitlines(keepends=True)
    declaration_line = content.count("\n", 0, declaration.start())
    start_line = declaration_line
    while start_line > 0:
        previous = lines[start_line - 1].lstrip()
        if previous.startswith(("///", "#[")):
            start_line -= 1
            continue
        break

    footer = "// @@protoc_insertion_point(module)\n"
    footer_position = content.rfind(footer)
    if footer_position == -1:
        raise ValueError(f"generated Rust output has no insertion point: {descriptor.get('name')}")
    header = "// @generated\n// This file is @generated by prost-build.\n"
    body_start = sum(len(line) for line in lines[:start_line])
    return header + content[body_start:footer_position] + footer


def normalize_rust(
    content: str,
    descriptor: Mapping[str, Any],
    by_name: Mapping[str, Mapping[str, Any]],
    *,
    is_prost: bool,
) -> str:
    content = RUST_TONIC_INCLUDE.sub("", content)
    if is_prost:
        content = isolate_rust_source(content, descriptor, by_name)
    current_package = cast(str, descriptor["package"]).split(".")
    dependencies = descriptor.get("dependency", [])
    if not isinstance(dependencies, list):
        raise ValueError("descriptor dependency list is invalid")
    for dependency in cast(list[object], dependencies):
        if not isinstance(dependency, str) or dependency not in by_name:
            continue
        dependency_package_name = cast(str, by_name[dependency]["package"])
        dependency_package = dependency_package_name.split(".")
        if dependency_package == current_package:
            continue
        common = 0
        for current_part, dependency_part in zip(current_package, dependency_package, strict=False):
            if current_part != dependency_part:
                break
            common += 1
        relative = "super::" * (len(current_package) - common)
        relative += "::".join(dependency_package[common:]) + "::"
        dependency_projection = "::".join(projection_parts(dependency_package_name))
        content = re.sub(
            rf"(?:super::)*{re.escape(relative)}",
            f"crate::{dependency_projection}::",
            content,
        )
    content = re.sub(r"(?m)^[ \t]*///[ \t]*\n", "", content)
    return content.rstrip() + "\n"


def normalize_typescript(
    content: str,
    raw_file: Path,
    target_file: Path,
    raw_to_target: Mapping[Path, Path],
) -> str:
    def replace(match: re.Match[str]) -> str:
        raw_import = (raw_file.parent / f"{match.group('path')}.ts").resolve()
        imported_target = raw_to_target.get(raw_import)
        if imported_target is None:
            raise ValueError(f"unmapped generated TypeScript import: {raw_import}")
        relative = os.path.relpath(imported_target.with_suffix(".js"), target_file.parent)
        if not relative.startswith("."):
            relative = "./" + relative
        return f'from "{relative}"'

    return TS_IMPORT.sub(replace, content).rstrip() + "\n"


def generated_build(srcs: Sequence[str]) -> bytes:
    entries = "\n".join(f'        "{source}",' for source in srcs)
    return (
        "# Code generated by mindclade-contract-codegen. DO NOT EDIT.\n\n"
        "filegroup(\n"
        '    name = "generated_sources",\n'
        f"    srcs = [\n{entries}\n    ],\n"
        '    visibility = ["//visibility:public"],\n'
        ")\n"
    ).encode()


def format_generated_build_files(
    root: Path,
    staging: Path,
    outputs: dict[Path, bytes],
) -> None:
    formatting_root = staging / "buildifier"
    build_files = sorted(path for path in outputs if path.name == "BUILD.bazel")
    for index, path in enumerate(build_files):
        candidate = formatting_root / str(index) / "BUILD.bazel"
        candidate.parent.mkdir(parents=True, exist_ok=True)
        candidate.write_bytes(outputs[path])
        run(["buildifier", "-mode=fix", str(candidate)], cwd=root)
        outputs[path] = candidate.read_bytes()


def format_generated_rust_metadata(
    root: Path,
    staging: Path,
    content: bytes,
) -> bytes:
    """Format the synthesized crate root without following included modules."""
    candidate = staging / "rustfmt" / "lib.rs"
    candidate.parent.mkdir(parents=True, exist_ok=True)
    candidate.write_bytes(content)
    run(
        [
            "rustfmt",
            "--edition",
            "2024",
            "--config",
            "skip_children=true",
            str(candidate),
        ],
        cwd=root,
    )
    return candidate.read_bytes()


def rust_module_declarations(projections: Sequence[tuple[str, ...]]) -> str:
    tree: dict[str, dict[str, Any]] = {}
    for projection in projections:
        branch = tree
        for part in projection:
            branch = branch.setdefault(part, {})

    def render(branch: Mapping[str, dict[str, Any]], indent: str = "") -> list[str]:
        lines: list[str] = []
        for name, children in sorted(branch.items()):
            if children:
                lines.append(f"{indent}pub mod {name} {{")
                lines.extend(render(children, indent + "    "))
                lines.append(f"{indent}}}")
            else:
                lines.append(f"{indent}pub mod {name};")
        return lines

    return "\n".join(render(tree))


def language_metadata(
    root: Path,
    descriptors: Sequence[Mapping[str, Any]],
    lock: Mapping[str, Any],
    outputs: dict[Path, bytes],
) -> None:
    generated = root / "protocols/generated"
    projections = sorted({projection_parts(cast(str, item["package"])) for item in descriptors})
    by_projection: dict[tuple[str, ...], list[Mapping[str, Any]]] = defaultdict(list)
    by_name = {cast(str, item["name"]): item for item in descriptors}
    for descriptor in descriptors:
        by_projection[projection_parts(cast(str, descriptor["package"]))].append(descriptor)

    for projection in projections:
        package_path = Path(*projection)
        rust_sources = sorted(
            path.name
            for path in outputs
            if path.parent == generated / "rust" / package_path
            and path.suffix == ".rs"
            and path.name != "mod.rs"
        )
        if rust_sources:
            modules = "\n".join(f'include!("{source}");' for source in rust_sources)
            outputs[generated / "rust" / package_path / "mod.rs"] = (
                f"// Code generated by {GENERATOR}; DO NOT EDIT.\n\n{modules}\n"
            ).encode()
        ts_sources = sorted(
            path.name
            for path in outputs
            if path.parent == generated / "typescript" / package_path
            and path.name.endswith("_pb.ts")
        )
        if ts_sources:
            exports = "\n".join(
                f"export * from './{Path(source).stem}.js';" for source in ts_sources
            )
            outputs[generated / "typescript" / package_path / "index.ts"] = (
                f"// Code generated by {GENERATOR}; DO NOT EDIT.\n\n{exports}\n"
            ).encode()
        if any(
            "python" in declared_languages(lock, cast(str, item["package"]))
            for item in by_projection[projection]
        ):
            python_package_path = Path(
                *python_projection_parts(cast(str, by_projection[projection][0]["package"]))
            )
            outputs[generated / "python" / python_package_path / "__init__.py"] = (
                f"# Code generated by {GENERATOR}; DO NOT EDIT.\n"
            ).encode()

        go_descriptors = [
            item
            for item in by_projection[projection]
            if "go" in declared_languages(lock, cast(str, item["package"]))
        ]
        if go_descriptors:
            go_package_path = Path(*go_projection_parts(cast(str, go_descriptors[0]["package"])))
            go_sources = sorted(
                path.name
                for path in outputs
                if path.parent == generated / "go" / go_package_path and path.name.endswith(".go")
            )
            dependency_projections = sorted(
                {
                    go_projection_parts(cast(str, by_name[dependency]["package"]))
                    for item in go_descriptors
                    for dependency in cast(list[str], item.get("dependency", []))
                    if dependency in by_name
                    and go_projection_parts(cast(str, by_name[dependency]["package"]))
                    != go_projection_parts(cast(str, item["package"]))
                }
            )
            deps = [
                '"@org_golang_google_protobuf//reflect/protoreflect"',
                '"@org_golang_google_protobuf//runtime/protoimpl"',
            ]
            well_known_deps = {
                "google/api/annotations.proto": (
                    "@org_golang_google_genproto_googleapis_api//annotations"
                ),
                "google/protobuf/duration.proto": (
                    "@org_golang_google_protobuf//types/known/durationpb"
                ),
                "google/protobuf/descriptor.proto": (
                    "@org_golang_google_protobuf//types/descriptorpb"
                ),
                "google/protobuf/empty.proto": "@org_golang_google_protobuf//types/known/emptypb",
                "google/protobuf/field_mask.proto": (
                    "@org_golang_google_protobuf//types/known/fieldmaskpb"
                ),
                "google/protobuf/timestamp.proto": (
                    "@org_golang_google_protobuf//types/known/timestamppb"
                ),
            }
            direct_well_known_deps = {
                label
                for item in go_descriptors
                for dependency in cast(list[str], item.get("dependency", []))
                for label in [well_known_deps.get(dependency)]
                if label is not None
            }
            deps.extend(f'"{label}"' for label in sorted(direct_well_known_deps))
            if any(source.endswith("_grpc.pb.go") for source in go_sources):
                deps.extend(
                    [
                        '"@org_golang_google_grpc//:grpc"',
                        '"@org_golang_google_grpc//codes"',
                        '"@org_golang_google_grpc//status"',
                    ]
                )
            deps.extend(
                f'"//protocols/generated/go/{Path(*value).as_posix()}:bindings"'
                for value in dependency_projections
            )
            import_path = (
                "github.com/mindclade/mindclade/protocols/generated/go/"
                f"{go_package_path.as_posix()}"
            )
            outputs[generated / "go" / go_package_path / "BUILD.bazel"] = (
                'load("@rules_go//go:def.bzl", "go_library")\n\n'
                "go_library(\n"
                '    name = "bindings",\n'
                f"    srcs = {json.dumps(go_sources)},\n"
                f'    importpath = "{import_path}",\n'
                f"    deps = [{', '.join(deps)}],\n"
                '    visibility = ["//visibility:public"],\n'
                ")\n\n"
                "filegroup(\n"
                '    name = "generated_sources",\n'
                f"    srcs = {json.dumps(['BUILD.bazel', *go_sources])},\n"
                '    visibility = ["//visibility:public"],\n'
                ")\n"
            ).encode()

    outputs[generated / "go" / "README.generated.md"] = (
        b"# Generated Go bindings\n\nGenerated by the locked Protobuf and gRPC-Go toolchain.\n"
    )
    outputs[generated / "go" / "BUILD.bazel"] = generated_build(
        [
            "BUILD.bazel",
            "README.generated.md",
            *sorted(
                {
                    "//protocols/generated/go/"
                    f"{Path(*go_projection_parts(cast(str, descriptor['package']))).as_posix()}"
                    ":generated_sources"
                    for descriptor in descriptors
                    if "go" in declared_languages(lock, cast(str, descriptor["package"]))
                }
            ),
            "//protocols/generated/go/schema/v1:generated_sources",
        ]
    )
    outputs[generated / "python" / "README.generated.md"] = (
        b"# Generated Python bindings\n\n"
        b"Generated by the locked Protobuf, gRPC, and mypy-protobuf toolchain.\n"
    )
    outputs[generated / "python" / "BUILD.bazel"] = (
        b'load("@rules_python//python:defs.bzl", "py_library")\n\n'
        b"py_library(\n"
        b'    name = "bindings",\n'
        b'    srcs = glob(["**/*.py"]),\n'
        b'    imports = ["."],\n'
        b'    deps = ["@mindclade_pypi//googleapis_common_protos", '
        b'"@mindclade_pypi//grpcio", "@mindclade_pypi//jsonschema", '
        b'"@mindclade_pypi//protobuf"],\n'
        b'    visibility = ["//visibility:public"],\n'
        b")\n\n"
        b"filegroup(\n"
        b'    name = "generated_sources",\n'
        b'    srcs = glob(["**/*"]),\n'
        b'    visibility = ["//visibility:public"],\n'
        b")\n"
    )
    outputs[generated / "rust" / "README.generated.md"] = (
        b"# Generated Rust bindings\n\nGenerated by the locked Prost and Tonic toolchain.\n"
    )
    rust_modules = rust_module_declarations([*projections, ("schema", "v1")])
    outputs[generated / "rust" / "lib.rs"] = (
        f"// Code generated by {GENERATOR}; DO NOT EDIT.\n"
        "#![allow(clippy::large_enum_variant)]\n\n"
        f"{rust_modules}\n"
    ).encode()
    outputs[generated / "rust" / "BUILD.bazel"] = (
        b'load("@rules_rust//rust:defs.bzl", "rust_library")\n\n'
        b"rust_library(\n"
        b'    name = "bindings",\n'
        b'    crate_name = "mindclade_protocols",\n'
        b'    edition = "2024",\n'
        b'    srcs = glob(["**/*.rs"]),\n'
        b"    deps = [\n"
        b'        "@crate_index//:jsonschema",\n'
        b'        "@crate_index//:prost",\n'
        b'        "@crate_index//:prost-types",\n'
        b'        "@crate_index//:serde",\n'
        b'        "@crate_index//:serde_json",\n'
        b'        "@crate_index//:tonic",\n'
        b'        "@crate_index//:tonic-prost",\n'
        b"    ],\n"
        b'    visibility = ["//visibility:public"],\n'
        b")\n\n"
        b"filegroup(\n"
        b'    name = "generated_sources",\n'
        b'    srcs = glob(["**/*"]),\n'
        b'    visibility = ["//visibility:public"],\n'
        b")\n"
    )
    outputs[generated / "typescript" / "README.generated.md"] = (
        b"# Generated TypeScript bindings\n\n"
        b"Generated by the locked Protobuf-ES and Connect toolchain.\n"
    )
    outputs[generated / "typescript" / "BUILD.bazel"] = (
        b'load("@aspect_rules_ts//ts:defs.bzl", "ts_config", "ts_project")\n'
        b'load("@npm//:defs.bzl", "npm_link_all_packages")\n\n'
        b'npm_link_all_packages(name = "node_modules")\n\n'
        b"# NodeNext classifies generated modules using this package boundary.\n"
        b"# Keep package.json explicit so sandboxed builds emit the same ESM as pnpm.\n"
        b"ts_config(\n"
        b'    name = "generated_tsconfig",\n'
        b'    src = "tsconfig.json",\n'
        b'    deps = ["package.json"],\n'
        b")\n\n"
        b"ts_project(\n"
        b'    name = "bindings",\n'
        b'    srcs = glob(["**/*.ts"], exclude = ["node_modules/**"]),\n'
        b'    assets = ["package.json"],\n'
        b"    declaration = True,\n"
        b'    tsconfig = ":generated_tsconfig",\n'
        b'    transpiler = "tsc",\n'
        b"    deps = [\n"
        b'        ":node_modules/@bufbuild/protobuf",\n'
        b'        ":node_modules/@connectrpc/connect",\n'
        b'        ":node_modules/ajv",\n'
        b'        ":node_modules/ajv-formats",\n'
        b"    ],\n"
        b'    visibility = ["//visibility:public"],\n'
        b")\n\n"
        b"filegroup(\n"
        b'    name = "generated_sources",\n'
        b'    srcs = glob(["**/*"], exclude = ["node_modules/**"]),\n'
        b'    visibility = ["//visibility:public"],\n'
        b")\n"
    )
    outputs[generated / "README.md"] = (
        b"# Generated protocol bindings\n\nGenerated by the locked Buf plugin closure.\n"
    )
    outputs[generated / "BUILD.bazel"] = generated_build(
        [
            "BUILD.bazel",
            "README.md",
            "generated-files.manifest.json",
            "//protocols/generated/go:generated_sources",
            "//protocols/generated/python:generated_sources",
            "//protocols/generated/rust:generated_sources",
            "//protocols/generated/typescript:generated_sources",
        ]
    )


def event_registry_entries(
    root: Path,
    descriptors: Sequence[Mapping[str, Any]],
) -> tuple[list[EventRegistryEntry], str]:
    """Validate and return the complete governed event registry."""
    registry_path = root / "protocols/events/registry.yaml"
    raw_value: object = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    if not isinstance(raw_value, dict):
        raise ValueError("protocols/events/registry.yaml has an unsupported schema version")
    raw = cast(dict[str, object], raw_value)
    if raw.get("schema_version") != "mindclade.event-registry/v2":
        raise ValueError("protocols/events/registry.yaml has an unsupported schema version")
    if set(raw) != {"schema_version", "events"}:
        raise ValueError("protocols/events/registry.yaml has unknown top-level fields")
    raw_events = raw.get("events")
    if not isinstance(raw_events, list):
        raise ValueError("protocols/events/registry.yaml must contain an events list")

    descriptor_events: dict[str, str] = {}
    for descriptor in descriptors:
        package = descriptor.get("package")
        source = descriptor.get("name")
        messages = descriptor.get("messageType", [])
        if not isinstance(package, str) or not package.startswith("mindclade.events."):
            continue
        if not isinstance(source, str) or not isinstance(messages, list):
            raise ValueError("event descriptor has an invalid source or message list")
        for raw_message in cast(list[object], messages):
            if not isinstance(raw_message, dict):
                raise ValueError(f"event descriptor has an invalid message: {source}")
            message = cast(dict[str, object], raw_message)
            name = message.get("name")
            if not isinstance(name, str):
                raise ValueError(f"event descriptor has an unnamed message: {source}")
            full_name = f"{package}.{name}"
            if full_name in descriptor_events:
                raise ValueError(f"duplicate event descriptor message: {full_name}")
            descriptor_events[full_name] = source

    entries: list[EventRegistryEntry] = []
    seen: set[tuple[str, int]] = set()
    for index, raw_event in enumerate(cast(list[object], raw_events)):
        if not isinstance(raw_event, dict):
            raise ValueError(f"event registry entry {index} is not an object")
        event = cast(dict[str, object], raw_event)
        expected_fields = {
            "activation_gaps",
            "compatibility_policy",
            "consumers",
            "content_type",
            "fixture",
            "full_name",
            "lifecycle_state",
            "owner",
            "producers",
            "source",
            "version",
        }
        if set(event) != expected_fields:
            missing_fields = sorted(expected_fields.difference(event))
            unknown_fields = sorted(set(event).difference(expected_fields))
            raise ValueError(
                f"event registry entry {index} fields are invalid: "
                f"missing={missing_fields}, unknown={unknown_fields}"
            )
        full_name = event.get("full_name")
        version = event.get("version")
        content_type = event.get("content_type")
        source = event.get("source")
        owner = event.get("owner")
        lifecycle_state = event.get("lifecycle_state")
        compatibility_policy = event.get("compatibility_policy")
        if (
            not isinstance(full_name, str)
            or not isinstance(version, int)
            or isinstance(version, bool)
            or version < 1
            or version > 0xFFFFFFFF
            or not isinstance(content_type, str)
            or not isinstance(source, str)
            or not isinstance(owner, str)
            or not EVENT_OWNER.fullmatch(owner)
            or not isinstance(lifecycle_state, str)
            or lifecycle_state not in EVENT_LIFECYCLE_STATES
            or not isinstance(compatibility_policy, str)
            or compatibility_policy not in EVENT_COMPATIBILITY_POLICIES
        ):
            raise ValueError(f"event registry entry {index} is incomplete")
        if content_type != EVENT_CONTENT_TYPE:
            raise ValueError(f"event registry content type is not canonical: {full_name}")
        if descriptor_events.get(full_name) != source:
            raise ValueError(
                f"event registry source mismatch for {full_name}: "
                f"expected {descriptor_events.get(full_name)!r}, got {source!r}"
            )
        identity = (full_name, version)
        if identity in seen:
            raise ValueError(f"duplicate event registry identity: {full_name}@{version}")
        seen.add(identity)
        short_name = full_name.rsplit(".", 1)[-1]
        fixture = _event_fixture(root, full_name, event.get("fixture"))
        producers = _event_endpoints(
            root,
            full_name,
            short_name,
            "producer",
            event.get("producers"),
        )
        consumers = _event_endpoints(
            root,
            full_name,
            short_name,
            "consumer",
            event.get("consumers"),
        )
        raw_gaps = event.get("activation_gaps")
        if not isinstance(raw_gaps, list):
            raise ValueError(f"event registry activation gaps are invalid: {full_name}")
        gap_values = cast(list[object], raw_gaps)
        if not all(isinstance(value, str) for value in gap_values):
            raise ValueError(f"event registry activation gaps are invalid: {full_name}")
        activation_gaps = tuple(cast(list[str], gap_values))
        if list(activation_gaps) != sorted(set(activation_gaps)) or not set(
            activation_gaps
        ).issubset(EVENT_ACTIVATION_GAPS):
            raise ValueError(f"event registry activation gaps are invalid: {full_name}")
        expected_gaps: set[str] = set()
        if not producers:
            expected_gaps.add("producer")
        if not consumers:
            expected_gaps.add("semantic-consumer")
        if fixture.status != "verified":
            expected_gaps.add("fixture")
        if set(activation_gaps) != expected_gaps:
            raise ValueError(
                f"event registry activation gaps do not match evidence for {full_name}: "
                f"expected={sorted(expected_gaps)}, got={list(activation_gaps)}"
            )
        if lifecycle_state == "active" and activation_gaps:
            raise ValueError(f"active event registry entry has evidence gaps: {full_name}")
        if lifecycle_state == "candidate" and not activation_gaps:
            raise ValueError(
                f"candidate event registry entry has no activation gap; activate it: {full_name}"
            )
        entries.append(
            EventRegistryEntry(
                full_name=full_name,
                version=version,
                content_type=content_type,
                source=source,
                owner=owner,
                lifecycle_state=lifecycle_state,
                compatibility_policy=compatibility_policy,
                fixture=fixture,
                producers=producers,
                consumers=consumers,
                activation_gaps=activation_gaps,
            )
        )

    registered_names = {entry.full_name for entry in entries}
    if registered_names != set(descriptor_events):
        missing = sorted(set(descriptor_events).difference(registered_names))
        orphaned = sorted(registered_names.difference(descriptor_events))
        raise ValueError(f"event registry descriptor drift: missing={missing}, orphaned={orphaned}")
    if [entry.full_name for entry in entries] != sorted(registered_names):
        raise ValueError("event registry entries must be sorted by full_name")

    return entries, sha256_file(registry_path)


def _repository_evidence_path(root: Path, value: object, *, context: str) -> tuple[str, Path]:
    if not isinstance(value, str):
        raise ValueError(f"{context} source must be a repository-relative path")
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts or relative.as_posix() != value:
        raise ValueError(f"{context} source is not canonical: {value!r}")
    resolved = root / relative
    if not resolved.is_file():
        raise ValueError(f"{context} source does not exist: {value}")
    return value, resolved


def _validated_bazel_target(root: Path, value: object, *, context: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{context} target must be an explicit Bazel label")
    match = BAZEL_TARGET.fullmatch(value)
    if match is None:
        raise ValueError(f"{context} target must be an explicit Bazel label: {value!r}")
    build_file = root / match.group("package") / "BUILD.bazel"
    if not build_file.is_file():
        raise ValueError(f"{context} target package has no BUILD.bazel: {value}")
    declaration = re.compile(rf'(?m)^\s*name\s*=\s*"{re.escape(match.group("name"))}",\s*$')
    if declaration.search(build_file.read_text(encoding="utf-8")) is None:
        raise ValueError(f"{context} target is not declared: {value}")
    return value


def _event_fixture(root: Path, full_name: str, value: object) -> EventFixtureEvidence:
    if not isinstance(value, dict):
        raise ValueError(f"event registry fixture is not an object: {full_name}")
    fixture = cast(dict[str, object], value)
    status = fixture.get("status")
    if status == "missing":
        if set(fixture) != {"reason", "status"}:
            raise ValueError(f"missing event fixture has invalid fields: {full_name}")
        reason = fixture.get("reason")
        if not isinstance(reason, str) or len(reason.strip()) < 12:
            raise ValueError(f"missing event fixture needs a specific reason: {full_name}")
        return EventFixtureEvidence(status="missing", reason=reason)
    if status != "verified" or set(fixture) != {"mode", "source", "status", "target"}:
        raise ValueError(f"verified event fixture has invalid fields: {full_name}")
    source, _ = _repository_evidence_path(
        root, fixture.get("source"), context=f"event fixture {full_name}"
    )
    target = _validated_bazel_target(
        root, fixture.get("target"), context=f"event fixture {full_name}"
    )
    mode = fixture.get("mode")
    if not isinstance(mode, str) or mode not in EVENT_FIXTURE_MODES:
        raise ValueError(f"event fixture mode is invalid: {full_name}")
    return EventFixtureEvidence(status="verified", source=source, target=target, mode=mode)


def _event_endpoints(
    root: Path,
    full_name: str,
    short_name: str,
    role: str,
    value: object,
) -> tuple[EventEvidenceEndpoint, ...]:
    if not isinstance(value, list):
        raise ValueError(f"event registry {role}s must be a list: {full_name}")
    allowed_modes = EVENT_PRODUCER_MODES if role == "producer" else EVENT_CONSUMER_MODES
    endpoints: list[EventEvidenceEndpoint] = []
    for index, raw_endpoint in enumerate(cast(list[object], value)):
        if not isinstance(raw_endpoint, dict):
            raise ValueError(f"event registry {role} {index} is not an object: {full_name}")
        endpoint = cast(dict[str, object], raw_endpoint)
        if set(endpoint) != {"id", "mode", "source", "target"}:
            raise ValueError(f"event registry {role} fields are invalid: {full_name}")
        endpoint_id = endpoint.get("id")
        mode = endpoint.get("mode")
        if (
            not isinstance(endpoint_id, str)
            or not EVENT_ENDPOINT_ID.fullmatch(endpoint_id)
            or not isinstance(mode, str)
            or mode not in allowed_modes
        ):
            raise ValueError(f"event registry {role} is invalid: {full_name}")
        source, source_path = _repository_evidence_path(
            root, endpoint.get("source"), context=f"event {role} {full_name}"
        )
        if short_name not in source_path.read_text(encoding="utf-8"):
            raise ValueError(f"event {role} evidence does not reference {short_name}: {source}")
        target = _validated_bazel_target(
            root, endpoint.get("target"), context=f"event {role} {full_name}"
        )
        endpoints.append(
            EventEvidenceEndpoint(
                endpoint_id=endpoint_id,
                source=source,
                target=target,
                mode=mode,
            )
        )
    if [endpoint.endpoint_id for endpoint in endpoints] != sorted(
        {endpoint.endpoint_id for endpoint in endpoints}
    ):
        raise ValueError(f"event registry {role}s must have unique sorted ids: {full_name}")
    return tuple(endpoints)


def event_registry_ratification_blockers(
    entries: Sequence[EventRegistryEntry],
) -> tuple[str, ...]:
    """Return descriptor-visible events that are not production-active."""
    return tuple(entry.full_name for entry in entries if entry.lifecycle_state != "active")


def event_registry_go(
    root: Path,
    descriptors: Sequence[Mapping[str, Any]],
    descriptor_digest: str,
) -> bytes:
    """Render the validated event registry as a Go lookup table."""
    entries, digest = event_registry_entries(root, descriptors)
    rows = "\n".join(_event_registry_go_row(entry) for entry in entries)
    return (
        f"// Code generated by {GENERATOR}; DO NOT EDIT.\n"
        f"// Source: protocols/events/registry.yaml ({digest})\n\n"
        "package queue\n\n"
        f"const authoritativeEventDescriptorDigest = {json.dumps(descriptor_digest)}\n\n"
        "var authoritativeEventRegistrations = []EventRegistration{\n"
        f"{rows}\n"
        "}\n"
    ).encode()


def _event_registry_go_row(entry: EventRegistryEntry) -> str:
    def endpoints(values: Sequence[EventEvidenceEndpoint]) -> str:
        if not values:
            return "nil"
        rendered = ", ".join(
            "{ID: "
            + json.dumps(value.endpoint_id)
            + ", Source: "
            + json.dumps(value.source)
            + ", Target: "
            + json.dumps(value.target)
            + ", Mode: "
            + json.dumps(value.mode)
            + "}"
            for value in values
        )
        return "[]EventEvidenceEndpoint{" + rendered + "}"

    fixture = entry.fixture
    gaps = (
        "nil"
        if not entry.activation_gaps
        else "[]string{" + ", ".join(json.dumps(value) for value in entry.activation_gaps) + "}"
    )
    return (
        "\t{FullName: "
        + json.dumps(entry.full_name)
        + ", Version: "
        + str(entry.version)
        + ", ContentType: "
        + json.dumps(entry.content_type)
        + ", Source: "
        + json.dumps(entry.source)
        + ", Owner: "
        + json.dumps(entry.owner)
        + ", LifecycleState: "
        + json.dumps(entry.lifecycle_state)
        + ", CompatibilityPolicy: "
        + json.dumps(entry.compatibility_policy)
        + ", Fixture: EventFixtureEvidence{Status: "
        + json.dumps(fixture.status)
        + ", Source: "
        + json.dumps(fixture.source)
        + ", Target: "
        + json.dumps(fixture.target)
        + ", Mode: "
        + json.dumps(fixture.mode)
        + ", Reason: "
        + json.dumps(fixture.reason)
        + "}, Producers: "
        + endpoints(entry.producers)
        + ", Consumers: "
        + endpoints(entry.consumers)
        + ", ActivationGaps: "
        + gaps
        + "},"
    )


def event_registry_python(
    root: Path,
    descriptors: Sequence[Mapping[str, Any]],
    descriptor_digest: str,
) -> bytes:
    """Render the validated event registry for Python publishers and consumers."""
    entries, digest = event_registry_entries(root, descriptors)
    registrations = "\n".join(_event_registry_python_row(entry) for entry in entries)
    ratifiable = not event_registry_ratification_blockers(entries)
    return (
        f"# Code generated by {GENERATOR}; DO NOT EDIT.\n"
        "# Source: protocols/events/registry.yaml\n"
        f"# Source digest: {digest}\n\n"
        "from __future__ import annotations\n\n"
        "from dataclasses import dataclass\n"
        "from typing import Final\n\n"
        f"EVENT_DESCRIPTOR_DIGEST: Final = {json.dumps(descriptor_digest)}\n"
        "DETERMINISTIC_PROTOBUF_CONTENT_TYPE: Final = "
        '"application/x-protobuf; deterministic=true"\n\n\n'
        "@dataclass(frozen=True, slots=True)\n"
        "class EventEvidenceEndpoint:\n"
        "    endpoint_id: str\n"
        "    source: str\n"
        "    target: str\n"
        "    mode: str\n\n\n"
        "@dataclass(frozen=True, slots=True)\n"
        "class EventFixtureEvidence:\n"
        "    status: str\n"
        "    source: str\n"
        "    target: str\n"
        "    mode: str\n"
        "    reason: str\n\n\n"
        "@dataclass(frozen=True, slots=True)\n"
        "class EventRegistration:\n"
        "    full_name: str\n"
        "    version: int\n"
        "    content_type: str\n"
        "    source: str\n"
        "    owner: str\n"
        "    lifecycle_state: str\n"
        "    compatibility_policy: str\n"
        "    fixture: EventFixtureEvidence\n"
        "    producers: tuple[EventEvidenceEndpoint, ...]\n"
        "    consumers: tuple[EventEvidenceEndpoint, ...]\n"
        "    activation_gaps: tuple[str, ...]\n\n\n"
        "EVENT_REGISTRATIONS: Final[tuple[EventRegistration, ...]] = (\n"
        f"{registrations}\n"
        ")\n\n"
        f"EVENT_REGISTRY_RATIFIABLE: Final = {ratifiable!r}\n\n"
        "_REGISTRATIONS_BY_IDENTITY: Final = {\n"
        "    (registration.full_name, registration.version): registration\n"
        "    for registration in EVENT_REGISTRATIONS\n"
        "}\n\n\n"
        "def require_event_registration(\n"
        "    full_name: str, version: int, content_type: str\n"
        ") -> EventRegistration:\n"
        '    """Return the exact registration or reject an unsupported envelope."""\n'
        "    registration = _REGISTRATIONS_BY_IDENTITY.get((full_name, version))\n"
        "    if registration is None:\n"
        '        raise ValueError(f"unregistered event type/version: {full_name}@{version}")\n'
        "    if registration.content_type != content_type:\n"
        "        raise ValueError(\n"
        '            f"event content type mismatch: expected '
        '{registration.content_type}, got {content_type}"\n'
        "        )\n"
        "    return registration\n"
    ).encode()


def _event_registry_python_row(entry: EventRegistryEntry) -> str:
    def endpoint(value: EventEvidenceEndpoint) -> str:
        return (
            "EventEvidenceEndpoint(endpoint_id="
            + json.dumps(value.endpoint_id)
            + ", source="
            + json.dumps(value.source)
            + ", target="
            + json.dumps(value.target)
            + ", mode="
            + json.dumps(value.mode)
            + ")"
        )

    producers = ", ".join(endpoint(value) for value in entry.producers)
    consumers = ", ".join(endpoint(value) for value in entry.consumers)
    if len(entry.producers) == 1:
        producers += ","
    if len(entry.consumers) == 1:
        consumers += ","
    fixture = entry.fixture
    return (
        "    EventRegistration(\n"
        f"        full_name={json.dumps(entry.full_name)},\n"
        f"        version={entry.version},\n"
        f"        content_type={json.dumps(entry.content_type)},\n"
        f"        source={json.dumps(entry.source)},\n"
        f"        owner={json.dumps(entry.owner)},\n"
        f"        lifecycle_state={json.dumps(entry.lifecycle_state)},\n"
        f"        compatibility_policy={json.dumps(entry.compatibility_policy)},\n"
        "        fixture=EventFixtureEvidence("
        f"status={json.dumps(fixture.status)}, source={json.dumps(fixture.source)}, "
        f"target={json.dumps(fixture.target)}, mode={json.dumps(fixture.mode)}, "
        f"reason={json.dumps(fixture.reason)}),\n"
        f"        producers=({producers}),\n"
        f"        consumers=({consumers}),\n"
        f"        activation_gaps={entry.activation_gaps!r},\n"
        "    ),"
    )


def event_registry_rust(
    root: Path,
    descriptors: Sequence[Mapping[str, Any]],
    descriptor_digest: str,
) -> bytes:
    """Render an immutable Rust registry inside the generated transport crate."""
    entries, digest = event_registry_entries(root, descriptors)
    rows = "\n".join(_event_registry_rust_row(entry) for entry in entries)
    ratifiable = str(not event_registry_ratification_blockers(entries)).lower()
    return (
        f"// Source: protocols/events/registry.yaml ({digest})\n"
        f"pub const EVENT_DESCRIPTOR_DIGEST: &str = {json.dumps(descriptor_digest)};\n\n"
        "#[derive(Clone, Copy, Debug, Eq, PartialEq)]\n"
        "pub struct EventEvidenceEndpoint {\n"
        "    pub id: &'static str,\n"
        "    pub source: &'static str,\n"
        "    pub target: &'static str,\n"
        "    pub mode: &'static str,\n"
        "}\n\n"
        "#[derive(Clone, Copy, Debug, Eq, PartialEq)]\n"
        "pub struct EventFixtureEvidence {\n"
        "    pub status: &'static str,\n"
        "    pub source: &'static str,\n"
        "    pub target: &'static str,\n"
        "    pub mode: &'static str,\n"
        "    pub reason: &'static str,\n"
        "}\n\n"
        "#[derive(Clone, Copy, Debug, Eq, PartialEq)]\n"
        "pub struct EventRegistration {\n"
        "    pub full_name: &'static str,\n"
        "    pub version: u32,\n"
        "    pub content_type: &'static str,\n"
        "    pub source: &'static str,\n"
        "    pub owner: &'static str,\n"
        "    pub lifecycle_state: &'static str,\n"
        "    pub compatibility_policy: &'static str,\n"
        "    pub fixture: EventFixtureEvidence,\n"
        "    pub producers: &'static [EventEvidenceEndpoint],\n"
        "    pub consumers: &'static [EventEvidenceEndpoint],\n"
        "    pub activation_gaps: &'static [&'static str],\n"
        "}\n\n"
        "pub static EVENT_REGISTRATIONS: &[EventRegistration] = &[\n"
        f"{rows}\n"
        "];\n\n"
        f"pub const EVENT_REGISTRY_RATIFIABLE: bool = {ratifiable};\n\n"
        "pub fn require_event_registration(\n"
        "    full_name: &str,\n"
        "    version: u32,\n"
        "    content_type: &str,\n"
        ") -> Result<&'static EventRegistration, String> {\n"
        "    let registration = EVENT_REGISTRATIONS\n"
        "        .iter()\n"
        "        .find(|entry| entry.full_name == full_name && entry.version == version)\n"
        '        .ok_or_else(|| format!("unregistered event type/version: '
        '{full_name}@{version}"))?;\n'
        "    if registration.content_type != content_type {\n"
        "        return Err(format!(\n"
        '            "event content type mismatch: expected {}, got {content_type}",\n'
        "            registration.content_type\n"
        "        ));\n"
        "    }\n"
        "    Ok(registration)\n"
        "}\n"
    ).encode()


def _event_registry_rust_row(entry: EventRegistryEntry) -> str:
    def endpoint(value: EventEvidenceEndpoint) -> str:
        return (
            "EventEvidenceEndpoint { id: "
            + json.dumps(value.endpoint_id)
            + ", source: "
            + json.dumps(value.source)
            + ", target: "
            + json.dumps(value.target)
            + ", mode: "
            + json.dumps(value.mode)
            + " }"
        )

    fixture = entry.fixture
    producers = ", ".join(endpoint(value) for value in entry.producers)
    consumers = ", ".join(endpoint(value) for value in entry.consumers)
    gaps = ", ".join(json.dumps(value) for value in entry.activation_gaps)
    return (
        "    EventRegistration { full_name: "
        + json.dumps(entry.full_name)
        + ", version: "
        + str(entry.version)
        + ", content_type: "
        + json.dumps(entry.content_type)
        + ", source: "
        + json.dumps(entry.source)
        + ", owner: "
        + json.dumps(entry.owner)
        + ", lifecycle_state: "
        + json.dumps(entry.lifecycle_state)
        + ", compatibility_policy: "
        + json.dumps(entry.compatibility_policy)
        + ", fixture: EventFixtureEvidence { status: "
        + json.dumps(fixture.status)
        + ", source: "
        + json.dumps(fixture.source)
        + ", target: "
        + json.dumps(fixture.target)
        + ", mode: "
        + json.dumps(fixture.mode)
        + ", reason: "
        + json.dumps(fixture.reason)
        + " }, producers: &["
        + producers
        + "], consumers: &["
        + consumers
        + "], activation_gaps: &["
        + gaps
        + "] },"
    )


def event_registry_typescript(
    root: Path,
    descriptors: Sequence[Mapping[str, Any]],
    descriptor_digest: str,
) -> bytes:
    """Render the exact registry for TypeScript Connect consumers."""
    entries, digest = event_registry_entries(root, descriptors)
    rows = ",\n".join(_event_registry_typescript_row(entry) for entry in entries)
    ratifiable = str(not event_registry_ratification_blockers(entries)).lower()
    return (
        f"// Source: protocols/events/registry.yaml ({digest})\n"
        f"export const EVENT_DESCRIPTOR_DIGEST = {json.dumps(descriptor_digest)} as const;\n\n"
        "export interface EventEvidenceEndpoint {\n"
        "  readonly id: string;\n"
        "  readonly source: string;\n"
        "  readonly target: string;\n"
        "  readonly mode: string;\n"
        "}\n\n"
        "export interface EventFixtureEvidence {\n"
        "  readonly status: string;\n"
        "  readonly source: string;\n"
        "  readonly target: string;\n"
        "  readonly mode: string;\n"
        "  readonly reason: string;\n"
        "}\n\n"
        "export interface EventRegistration {\n"
        "  readonly fullName: string;\n"
        "  readonly version: number;\n"
        "  readonly contentType: string;\n"
        "  readonly source: string;\n"
        "  readonly owner: string;\n"
        "  readonly lifecycleState: string;\n"
        "  readonly compatibilityPolicy: string;\n"
        "  readonly fixture: EventFixtureEvidence;\n"
        "  readonly producers: readonly EventEvidenceEndpoint[];\n"
        "  readonly consumers: readonly EventEvidenceEndpoint[];\n"
        "  readonly activationGaps: readonly string[];\n"
        "}\n\n"
        "export const EVENT_REGISTRATIONS = [\n"
        f"{rows}\n"
        "] as const satisfies readonly EventRegistration[];\n\n"
        f"export const EVENT_REGISTRY_RATIFIABLE = {ratifiable} as const;\n\n"
        "const registrationsByIdentity = new Map(\n"
        "  EVENT_REGISTRATIONS.map((entry) => ["
        "`${entry.fullName}\\u0000${entry.version}`, entry]),\n"
        ");\n\n"
        "export function requireEventRegistration(\n"
        "  fullName: string,\n"
        "  version: number,\n"
        "  contentType: string,\n"
        "): EventRegistration {\n"
        "  const registration = registrationsByIdentity.get(`${fullName}\\u0000${version}`);\n"
        "  if (registration === undefined) {\n"
        "    throw new Error(`unregistered event type/version: ${fullName}@${version}`);\n"
        "  }\n"
        "  if (registration.contentType !== contentType) {\n"
        "    throw new Error(\n"
        "      `event content type mismatch: expected ${registration.contentType}, "
        "got ${contentType}`,\n"
        "    );\n"
        "  }\n"
        "  return registration;\n"
        "}\n"
    ).encode()


def _event_registry_typescript_row(entry: EventRegistryEntry) -> str:
    def endpoint(value: EventEvidenceEndpoint) -> dict[str, str]:
        return {
            "id": value.endpoint_id,
            "mode": value.mode,
            "source": value.source,
            "target": value.target,
        }

    fixture = entry.fixture
    value = {
        "activationGaps": list(entry.activation_gaps),
        "compatibilityPolicy": entry.compatibility_policy,
        "consumers": [endpoint(endpoint_value) for endpoint_value in entry.consumers],
        "contentType": entry.content_type,
        "fixture": {
            "mode": fixture.mode,
            "reason": fixture.reason,
            "source": fixture.source,
            "status": fixture.status,
            "target": fixture.target,
        },
        "fullName": entry.full_name,
        "lifecycleState": entry.lifecycle_state,
        "owner": entry.owner,
        "producers": [endpoint(endpoint_value) for endpoint_value in entry.producers],
        "source": entry.source,
        "version": entry.version,
    }
    return "  " + json.dumps(value, sort_keys=True, separators=(",", ":"))


def protobuf_candidate(
    root: Path,
    descriptors: Sequence[Mapping[str, Any]],
    descriptor_set: bytes,
) -> bytes:
    event_entries, event_registry_digest = event_registry_entries(root, descriptors)
    event_blockers = event_registry_ratification_blockers(event_entries)
    sources = {
        path.relative_to(root).as_posix(): sha256_file(path)
        for path in sorted(source_path(root, descriptor) for descriptor in descriptors)
    }
    fixture_text = (
        b'tenant_id: "tenant-01"\nproject_id: "project-01"\nprincipal_id: "principal-01"\n'
        b'request_id: "request-01"\ntrace_id: "trace-01"\n'
    )
    fixture = run(
        [
            "protoc",
            "-I",
            "protocols",
            "--encode=mindclade.common.v1.Identifiers",
            "protocols/proto/mindclade/common/v1/identifiers.proto",
        ],
        cwd=root,
        input_bytes=fixture_text,
    ).stdout
    value = {
        "descriptor_set": {
            "base64": base64.b64encode(descriptor_set).decode("ascii"),
            "digest": sha256_bytes(descriptor_set),
        },
        "event_registry": {
            "active_event_count": sum(entry.lifecycle_state == "active" for entry in event_entries),
            "blockers": list(event_blockers),
            "digest": event_registry_digest,
            "event_count": len(event_entries),
            "path": "protocols/events/registry.yaml",
            "ratifiable": not event_blockers,
            "schema_version": "mindclade.event-registry/v2",
        },
        "lifecycle": {
            "authority": "docs/adr/0015-all-contracts-clean-v1-baseline.md",
            "breaking_enforcement": "not-started",
            "predecessor": {
                "artifact_digest": PREDECESSOR_ARTIFACT_DIGEST,
                "descriptor_digest": PREDECESSOR_DESCRIPTOR_DIGEST,
                "path": PROTOBUF_PREDECESSOR.as_posix(),
                "revision": PREDECESSOR_REVISION,
                "source_count": 22,
            },
            "ratification": {
                "action": "generate_protocols.py --ratify-v1-baseline",
                "required_bindings": sorted(RATIFICATION_BINDING_FIELDS),
                "required_evidence": sorted(TRAINING_VERTICAL_EVIDENCE_CHECKS),
            },
            "state": "unratified-candidate",
        },
        "schema_version": "mindclade.protobuf-candidate/v1",
        "sources": sources,
        "wire_fixture": {
            "base64": base64.b64encode(fixture).decode("ascii"),
            "message": "mindclade.common.v1.Identifiers",
            "values": {
                "principal_id": "principal-01",
                "project_id": "project-01",
                "request_id": "request-01",
                "tenant_id": "tenant-01",
                "trace_id": "trace-01",
            },
        },
    }
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _tracked_paths(root: Path, prefix: str) -> list[Path]:
    result = run(["git", "ls-files", "-z", "--", prefix], cwd=root).stdout
    paths = [Path(value.decode("utf-8")) for value in result.split(b"\x00") if value]
    if not paths:
        raise RuntimeError(f"ratification input has no tracked files: {prefix}")
    for path in paths:
        if path.is_absolute() or ".." in path.parts or not (root / path).is_file():
            raise RuntimeError(f"ratification input is not a regular tracked file: {path}")
    return sorted(paths)


def _inventory_digest(root: Path, paths: Sequence[Path]) -> str:
    inventory = {path.as_posix(): sha256_file(root / path) for path in sorted(paths)}
    return sha256_bytes(
        json.dumps(inventory, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )


def ratification_bindings(
    root: Path,
    *,
    candidate_descriptor_digest: str,
    event_registry_digest: str,
) -> dict[str, Any]:
    """Resolve every immutable input the eventual v1 receipt must bind."""

    status = run(["git", "status", "--porcelain=v1", "--untracked-files=all"], cwd=root).stdout
    if status:
        raise RuntimeError("ratification requires a clean Git worktree")
    source_revision = run(["git", "rev-parse", "HEAD"], cwd=root).stdout.decode().strip()
    if re.fullmatch(r"[0-9a-f]{40}", source_revision) is None:
        raise RuntimeError("ratification requires an exact 40-character Git revision")

    required_files = (
        PUBLISHED_OPENAPI,
        TOOLCHAIN_LOCK,
        GENERATED_MANIFEST,
        SDK_RPC_COVERAGE,
        GRPC_IMPLEMENTATION_COVERAGE,
    )
    missing = [path.as_posix() for path in required_files if not (root / path).is_file()]
    if missing:
        raise RuntimeError(f"ratification inputs are missing: {missing}")
    migration_paths = _tracked_paths(root, "services/control_plane/migrations")
    if any(path.suffix != ".sql" for path in migration_paths):
        raise RuntimeError("the tracked migration set contains a non-SQL file")
    sdk_package_digests = {
        language: _inventory_digest(root, _tracked_paths(root, f"internal/sdk/{language}"))
        for language in LANGUAGES
    }
    return {
        "candidate_descriptor_digest": candidate_descriptor_digest,
        "codegen_toolchain_digest": sha256_file(root / TOOLCHAIN_LOCK),
        "event_registry_digest": event_registry_digest,
        "generated_manifest_digest": sha256_file(root / GENERATED_MANIFEST),
        "grpc_implementation_digest": sha256_file(root / GRPC_IMPLEMENTATION_COVERAGE),
        "migration_set_digest": _inventory_digest(root, migration_paths),
        "openapi_projection_digest": sha256_file(root / PUBLISHED_OPENAPI),
        "sdk_package_digests": sdk_package_digests,
        "sdk_rpc_coverage_digest": sha256_file(root / SDK_RPC_COVERAGE),
        "source_revision": source_revision,
    }


def validate_training_vertical_evidence(
    root: Path,
    evidence_path: Path,
    *,
    bindings: Mapping[str, Any],
) -> tuple[dict[str, Any], str]:
    """Validate the closed evidence gate for the one-time v1 ratification."""

    evidence = load_json(evidence_path)
    if evidence.get("schema_version") != "mindclade.training-vertical-evidence/v2":
        raise ValueError("training vertical evidence has an unsupported schema_version")
    expected_fields = {"checks", "schema_version", "status", *RATIFICATION_BINDING_FIELDS}
    if set(evidence) != expected_fields:
        raise ValueError(
            "training vertical evidence fields differ: "
            f"missing={sorted(expected_fields - set(evidence))}, "
            f"unexpected={sorted(set(evidence) - expected_fields)}"
        )
    if evidence.get("status") != "passed":
        raise ValueError("training vertical evidence is not passed")
    if set(bindings) != set(RATIFICATION_BINDING_FIELDS):
        raise ValueError("internal ratification binding set is incomplete")
    for name, expected in sorted(bindings.items()):
        if evidence.get(name) != expected:
            raise ValueError(f"training vertical evidence is bound to a different {name}")
    raw_checks = evidence.get("checks")
    if not isinstance(raw_checks, dict):
        raise ValueError(
            "training vertical evidence must contain exactly these checks: "
            + ", ".join(sorted(TRAINING_VERTICAL_EVIDENCE_CHECKS))
        )
    checks = cast(dict[str, object], raw_checks)
    if set(checks) != set(TRAINING_VERTICAL_EVIDENCE_CHECKS):
        raise ValueError(
            "training vertical evidence must contain exactly these checks: "
            + ", ".join(sorted(TRAINING_VERTICAL_EVIDENCE_CHECKS))
        )
    for name, raw_check in sorted(checks.items()):
        if not isinstance(raw_check, dict):
            raise ValueError(f"training vertical evidence check {name!r} is not an object")
        check = cast(dict[str, object], raw_check)
        receipt_digest = check.get("receipt_digest")
        if check.get("status") != "passed" or not isinstance(receipt_digest, str):
            raise ValueError(f"training vertical evidence check {name!r} is not passed")
        if re.fullmatch(r"sha256:[0-9a-f]{64}", receipt_digest) is None:
            raise ValueError(
                f"training vertical evidence check {name!r} has an invalid receipt digest"
            )
    if evidence_path.resolve().is_relative_to(root.resolve()) is False:
        raise ValueError("training vertical evidence must be a repository-owned receipt")
    return evidence, sha256_file(evidence_path)


def ratified_protobuf_baseline(
    candidate: Mapping[str, Any],
    *,
    bindings: Mapping[str, Any],
    evidence: Mapping[str, Any],
    evidence_digest: str,
) -> bytes:
    """Construct the first enforceable v1 baseline after the evidence gate passes."""

    value = {
        "descriptor_set": candidate["descriptor_set"],
        "event_registry": candidate["event_registry"],
        "ratification": {
            "authority": "docs/adr/0015-all-contracts-clean-v1-baseline.md",
            "candidate_artifact_digest": sha256_bytes(
                (json.dumps(candidate, sort_keys=True, separators=(",", ":")) + "\n").encode()
            ),
            "evidence_digest": evidence_digest,
            "evidence_schema_version": evidence["schema_version"],
            "bindings": dict(bindings),
            "qualification_results": {
                name: cast(Mapping[str, str], check)["receipt_digest"]
                for name, check in sorted(cast(Mapping[str, object], evidence["checks"]).items())
            },
            "source_revision": bindings["source_revision"],
            "predecessor_artifact_digest": PREDECESSOR_ARTIFACT_DIGEST,
        },
        "schema_version": "mindclade.protobuf-baseline/v3",
        "sources": candidate["sources"],
        "wire_fixture": candidate["wire_fixture"],
    }
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def protojson_field_schema(field: protobuf_descriptor.FieldDescriptor) -> dict[str, Any]:
    """Return the descriptor-derived JSON shape of one Protobuf field."""
    field_type = descriptor_pb2.FieldDescriptorProto
    message_type = field.message_type
    if (
        field.type == field_type.TYPE_MESSAGE
        and message_type is not None
        and message_type.GetOptions().map_entry
    ):
        value = message_type.fields_by_name["value"]
        return {
            "additionalProperties": protojson_field_schema(value),
            "type": "object",
        }

    if field.type == field_type.TYPE_MESSAGE:
        if message_type is None:
            raise ValueError(f"message field has no descriptor: {field.full_name}")
        well_known = {
            "google.protobuf.Duration": {"format": "duration", "type": "string"},
            "google.protobuf.Timestamp": {"format": "date-time", "type": "string"},
        }
        value = well_known.get(message_type.full_name)
        schema = (
            dict(value)
            if value is not None
            else {
                "$ref": "#/components/schemas/" + message_type.full_name,
            }
        )
    elif field.type == field_type.TYPE_ENUM:
        enum_type = field.enum_type
        if enum_type is None:
            raise ValueError(f"enum field has no descriptor: {field.full_name}")
        schema = {
            "enum": [value.name for value in enum_type.values],
            "type": "string",
        }
    elif field.type == field_type.TYPE_BOOL:
        schema = {"type": "boolean"}
    elif field.type == field_type.TYPE_STRING:
        schema = {"type": "string"}
    elif field.type == field_type.TYPE_BYTES:
        schema = {"format": "byte", "type": "string"}
    elif field.type in {
        field_type.TYPE_INT64,
        field_type.TYPE_SFIXED64,
        field_type.TYPE_SINT64,
    }:
        schema = {"pattern": "^-?(0|[1-9][0-9]*)$", "type": "string"}
    elif field.type in {field_type.TYPE_FIXED64, field_type.TYPE_UINT64}:
        schema = {"pattern": "^(0|[1-9][0-9]*)$", "type": "string"}
    elif field.type in {
        field_type.TYPE_INT32,
        field_type.TYPE_SFIXED32,
        field_type.TYPE_SINT32,
    }:
        schema = {"format": "int32", "type": "integer"}
    elif field.type in {field_type.TYPE_FIXED32, field_type.TYPE_UINT32}:
        schema = {"format": "uint32", "type": "integer"}
    elif field.type == field_type.TYPE_FLOAT:
        schema = {"format": "float", "type": "number"}
    elif field.type == field_type.TYPE_DOUBLE:
        schema = {"format": "double", "type": "number"}
    else:
        raise ValueError(f"unsupported public ProtoJSON field type: {field.full_name}")

    if field.is_repeated:
        return {"items": schema, "type": "array"}
    return schema


def public_protojson_components(
    pool: descriptor_pool.DescriptorPool,
) -> dict[str, dict[str, Any]]:
    """Build complete public ProtoJSON component shapes from descriptors."""
    options_class = message_factory.GetMessageClass(
        pool.FindMessageTypeByName("google.protobuf.MessageOptions")
    )
    contract_extension = pool.FindExtensionByName("mindclade.api.v1.public_message")
    public_file = pool.FindFileByName("proto/mindclade/api/v1/mindclade_service.proto")
    pending = list(public_file.message_types_by_name.values())
    messages: list[protobuf_descriptor.Descriptor] = []
    while pending:
        message = pending.pop()
        pending.extend(message.nested_types)
        if not message.GetOptions().map_entry:
            messages.append(message)

    result: dict[str, dict[str, Any]] = {}
    for message in sorted(messages, key=lambda value: value.full_name):
        options = options_class.FromString(message.GetOptions().SerializeToString())
        extension_values = cast(Any, options.Extensions)
        contract = cast(_PublicMessageContract, extension_values[contract_extension])
        required: list[str] = []
        for field_name in contract.required_fields:
            field = message.fields_by_name.get(field_name)
            if field is None:
                raise ValueError(
                    f"public required field does not exist: {message.full_name}.{field_name}"
                )
            required.append(field.json_name)
        properties = {field.json_name: protojson_field_schema(field) for field in message.fields}
        for string_enum in contract.string_enums:
            field = message.fields_by_name.get(string_enum.field)
            if field is None or field.type != descriptor_pb2.FieldDescriptorProto.TYPE_STRING:
                raise ValueError(
                    "public string-enum field is not a string: "
                    f"{message.full_name}.{string_enum.field}"
                )
            values = list(string_enum.values)
            if not values or len(values) != len(set(values)):
                raise ValueError(f"public string enum is empty or duplicated: {field.full_name}")
            properties[field.json_name]["enum"] = values
        result[message.full_name] = {
            "x-mindclade-oneofs": {
                oneof.name: sorted(field.json_name for field in oneof.fields)
                for oneof in message.oneofs
                if len(oneof.fields) > 1
            },
            "properties": properties,
            "required": sorted(required),
            "type": "object",
        }
    return result


PUBLIC_PROTO_DEPENDENCY_ALLOWLIST = frozenset(
    {
        "google/api/annotations.proto",
        "google/protobuf/descriptor.proto",
        "google/protobuf/timestamp.proto",
    }
)
PUBLIC_FORBIDDEN_FIELD_NAMES = frozenset(
    {
        "active_fence",
        "command_context",
        "delivery_envelope",
        "executable_plan",
        "fence",
        "lease_token",
        "lease_token_digest",
        "principal_id",
        "secret",
        "storage_locator",
        "tenant_id",
        "uri",
        "worker_id",
    }
)

# A caller-selected ``project_id`` is an ordinary public resource identifier,
# not trusted authorization context.  Authorization and tenant binding are
# resolved from transport credentials; those security-sensitive fields remain
# forbidden above.  Keeping this distinction explicit prevents the boundary
# check from rejecting safe ProjectCreate/ProjectView messages while still
# failing closed on client-supplied principal or tenant identity.


def validate_public_descriptor_boundary(pool: descriptor_pool.DescriptorPool) -> None:
    """Enforce the public-safe Protobuf module as a fail-closed boundary."""
    public_file = pool.FindFileByName("proto/mindclade/api/v1/mindclade_service.proto")
    dependencies = {dependency.name for dependency in public_file.dependencies}
    unexpected_dependencies = dependencies - PUBLIC_PROTO_DEPENDENCY_ALLOWLIST
    if unexpected_dependencies:
        raise ValueError(
            "public API descriptor imports a non-allowlisted dependency: "
            + ", ".join(sorted(unexpected_dependencies))
        )

    pending = list(public_file.message_types_by_name.values())
    while pending:
        message = pending.pop()
        pending.extend(message.nested_types)
        for field in message.fields:
            if field.name in PUBLIC_FORBIDDEN_FIELD_NAMES or field.name.endswith(
                ("_lease_token", "_storage_uri", "_secret")
            ):
                raise ValueError(f"public API exposes forbidden field {field.full_name}")
            if (
                field.message_type is not None
                and field.message_type.full_name == "google.protobuf.Any"
            ):
                raise ValueError(f"public API exposes unrestricted Any at {field.full_name}")
            if field.message_type is not None and not (
                field.message_type.full_name.startswith("mindclade.api.v1.")
                or field.message_type.full_name
                in {"google.protobuf.Timestamp", "google.protobuf.Duration"}
                or field.message_type.GetOptions().map_entry
            ):
                raise ValueError(
                    "public API message closure escapes its hard module boundary at "
                    f"{field.full_name}: {field.message_type.full_name}"
                )

    service = pool.FindServiceByName("mindclade.api.v1.MindcladeService")
    for method in service.methods:
        if not method.input_type.full_name.startswith(
            "mindclade.api.v1."
        ) or not method.output_type.full_name.startswith("mindclade.api.v1."):
            raise ValueError(f"public RPC {method.full_name} escapes the public message boundary")
        if method.client_streaming:
            raise ValueError(f"public RPC {method.full_name} uses unapproved client streaming")


def expand_google_http_path(path_template: str) -> tuple[str, list[str]]:
    """Expand a Google resource-pattern binding into a concrete OpenAPI path."""
    parameter_names: list[str] = []

    def singular(resource: str) -> str:
        if resource.endswith("ies"):
            return resource[:-3] + "y"
        if resource.endswith("s"):
            return resource[:-1]
        return resource

    def replace(match: re.Match[str]) -> str:
        pattern = match.group(2).split("/")
        result: list[str] = []
        index = 0
        while index < len(pattern):
            part = pattern[index]
            if index + 1 < len(pattern) and pattern[index + 1] in {"*", "**"}:
                name = singular(part)
                if name in parameter_names:
                    raise ValueError(f"duplicate expanded path parameter: {name}")
                parameter_names.append(name)
                result.extend([part, "{" + name + "}"])
                index += 2
                continue
            if part in {"*", "**"}:
                raise ValueError(f"unbound wildcard in public HTTP path: {path_template}")
            result.append(part)
            index += 1
        return "/".join(result)

    expanded = re.sub(r"\{([^={}]+)=([^{}]+)\}", replace, path_template)
    if "*" in expanded or re.search(r"\{[^{}=]+=", expanded):
        raise ValueError(f"unsupported public HTTP path template: {path_template}")
    return expanded, parameter_names


def raw_openapi_document(
    operations: Sequence[Mapping[str, Any]],
    components: Mapping[str, Mapping[str, Any]],
    descriptor_digest: str,
) -> dict[str, Any]:
    """Render a valid descriptor-derived OpenAPI 3.1 document."""
    paths: dict[str, dict[str, Any]] = {}
    for contract in operations:
        path, path_parameters = expand_google_http_path(cast(str, contract["pathTemplate"]))
        parameters: list[dict[str, Any]] = [
            {
                "in": "path",
                "name": name,
                "required": True,
                "schema": {"type": "string"},
            }
            for name in path_parameters
        ]
        required_headers = set(cast(list[str], contract["requiredRequestHeaders"]))
        parameters.extend(
            {
                "in": "header",
                "name": name,
                "required": name in required_headers,
                "schema": {"type": "string"},
            }
            for name in cast(list[str], contract["requestHeaders"])
        )
        parameters.extend(
            {
                "in": "query",
                "name": name,
                "required": False,
                "schema": schema,
            }
            for name, schema in cast(dict[str, dict[str, Any]], contract["queryFields"]).items()
        )
        responses: dict[str, Any] = {}
        success_status = set(cast(list[int], contract["successStatus"]))
        for status_code in cast(list[int], contract["responseStatus"]):
            response: dict[str, Any] = {"description": "Descriptor-derived response contract."}
            if status_code in success_status:
                response["headers"] = {
                    header: {"schema": {"type": "string"}}
                    for header in cast(list[str], contract["responseHeaders"])
                }
                media_type = (
                    "text/event-stream"
                    if contract["stream"] == "STREAM_PROJECTION_SSE"
                    else "application/json"
                )
                response["content"] = {
                    media_type: {
                        "schema": {
                            "$ref": "#/components/schemas/" + cast(str, contract["responseMessage"])
                        }
                    }
                }
            elif status_code != 304:
                response["content"] = {
                    "application/problem+json": {
                        "schema": {"$ref": "#/components/schemas/mindclade.api.v1.PublicError"}
                    }
                }
            responses[str(status_code)] = response
        operation: dict[str, Any] = {
            "operationId": contract["operationId"],
            "parameters": parameters,
            "responses": responses,
            "security": [{"bearerAuth": []}] if contract["auth"] == "bearer" else [],
        }
        body_message = contract.get("bodyMessage")
        if isinstance(body_message, str):
            operation["requestBody"] = {
                "content": {
                    "application/json": {"schema": {"$ref": "#/components/schemas/" + body_message}}
                },
                "required": contract["requestBodyRequired"],
            }
        paths.setdefault(path, {})[cast(str, contract["method"]).lower()] = operation
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "Mindclade descriptor-derived public API projection",
            "version": "v1-candidate",
        },
        "paths": paths,
        "components": {
            "schemas": dict(components),
            "securitySchemes": {
                "bearerAuth": {"scheme": "bearer", "type": "http"},
            },
        },
        "x-mindclade-binding-contracts": list(operations),
        "x-mindclade-descriptor-digest": descriptor_digest,
        "x-mindclade-schema-version": "mindclade.raw-openapi-projection/v3",
        "x-mindclade-generator": {
            "name": GENERATOR,
            "source": "tools/codegen/generate_protocols.py",
        },
    }


def public_openapi_projection(descriptor_set: bytes) -> dict[str, Any]:
    """Extract raw HTTP bindings and ProtoJSON components from descriptors."""
    files = descriptor_pb2.FileDescriptorSet.FromString(descriptor_set)
    pool = descriptor_pool.DescriptorPool()
    pending = list(files.file)
    while pending:
        progress = False
        for file_descriptor in pending[:]:
            try:
                pool.Add(file_descriptor)
            except Exception:  # Dependencies may not have been installed yet.
                continue
            pending.remove(file_descriptor)
            progress = True
        if not progress:
            missing = ", ".join(sorted(item.name for item in pending))
            raise ValueError(f"cannot resolve public descriptor closure: {missing}")

    validate_public_descriptor_boundary(pool)

    options_class = message_factory.GetMessageClass(
        pool.FindMessageTypeByName("google.protobuf.MethodOptions")
    )
    http_extension = pool.FindExtensionByName("google.api.http")
    contract_extension = pool.FindExtensionByName("mindclade.api.v1.public_http")
    service = pool.FindServiceByName("mindclade.api.v1.MindcladeService")
    operations: list[dict[str, Any]] = []
    for method in service.methods:
        options = options_class.FromString(method.GetOptions().SerializeToString())
        extension_values = cast(Any, options.Extensions)
        rule = cast(_GoogleHTTPRule, extension_values[http_extension])
        contract = cast(_PublicHTTPContract, extension_values[contract_extension])
        verb = cast(protobuf_message.Message, rule).WhichOneof("pattern")
        if verb is None:
            raise ValueError(f"public RPC has no google.api.http binding: {method.full_name}")
        contract_message = contract_extension.message_type
        if contract_message is None:
            raise ValueError("public HTTP extension has no message descriptor")
        stream_field = contract_message.fields_by_name.get("stream")
        if stream_field is None or stream_field.enum_type is None:
            raise ValueError("public HTTP stream contract has no enum descriptor")
        stream_value = stream_field.enum_type.values_by_number.get(contract.stream)
        if stream_value is None:
            raise ValueError(f"public RPC has an unknown stream projection: {method.full_name}")
        raw_path_template: object = getattr(rule, verb)
        if not isinstance(raw_path_template, str):
            raise ValueError(f"public RPC has an invalid HTTP path: {method.full_name}")
        path_template = raw_path_template
        path_fields = sorted(
            {value.split(".", 1)[0] for value in re.findall(r"\{([^={}]+)=", path_template)}
        )
        body = rule.body
        body_field = method.input_type.fields_by_name.get(body) if body else None
        query_fields = {
            field.json_name: protojson_field_schema(field)
            for field in method.input_type.fields
            if field.name not in path_fields and field.name != body
        }
        operations.append(
            {
                "auth": "bearer" if contract.bearer_auth else "none",
                "body": body or None,
                "bodyMessage": (
                    body_field.message_type.full_name
                    if body_field is not None and body_field.message_type is not None
                    else None
                ),
                "method": verb.upper(),
                "operationId": method.name[0].lower() + method.name[1:],
                "pathFields": path_fields,
                "pathTemplate": path_template,
                "queryFields": query_fields,
                "requestHeaders": sorted(contract.request_headers),
                "requiredRequestHeaders": sorted(contract.required_request_headers),
                "requestBodyRequired": contract.request_body_required,
                "requestMessage": method.input_type.full_name,
                "responseHeaders": sorted(contract.response_headers),
                "responseMessage": method.output_type.full_name,
                "responseStatus": sorted([*contract.success_status, *contract.non_success_status]),
                "serverStreaming": method.server_streaming,
                "stream": stream_value.name,
                "successStatus": sorted(contract.success_status),
            }
        )
    return raw_openapi_document(
        sorted(operations, key=lambda item: cast(str, item["operationId"])),
        public_protojson_components(pool),
        sha256_bytes(descriptor_set),
    )


def resolve_openapi_ref(document: Mapping[str, Any], value: Mapping[str, Any]) -> object:
    """Resolve one bundled OpenAPI reference without permitting external input."""
    ref = value.get("$ref")
    if not isinstance(ref, str):
        return value
    if not ref.startswith("#/"):
        raise ValueError(f"external OpenAPI reference is forbidden: {ref}")
    resolved: object = document
    for component in ref[2:].split("/"):
        key = component.replace("~1", "/").replace("~0", "~")
        if not isinstance(resolved, dict) or key not in resolved:
            raise ValueError(f"unresolved OpenAPI reference: {ref}")
        resolved = cast(dict[str, object], resolved)[key]
    return resolved


def schema_authority_names(value: object) -> set[str]:
    """Collect descriptor message identities declared inside one schema."""
    if isinstance(value, dict):
        mapping = cast(dict[str, object], value)
        result = {
            name
            for name in [mapping.get("x-mindclade-authoritative-message")]
            if isinstance(name, str)
        }
        for child in mapping.values():
            result.update(schema_authority_names(child))
        return result
    if isinstance(value, list):
        result: set[str] = set()
        for child in cast(list[object], value):
            result.update(schema_authority_names(child))
        return result
    return set()


def merged_openapi_object(
    document: Mapping[str, Any],
    schema: Mapping[str, Any],
) -> tuple[dict[str, Any], set[str]]:
    """Resolve object composition into its effective properties and required set."""
    resolved = resolve_openapi_ref(document, schema)
    if not isinstance(resolved, dict):
        raise ValueError("OpenAPI schema reference did not resolve to an object")
    resolved_mapping = cast(dict[str, object], resolved)
    properties = dict(cast(dict[str, Any], resolved_mapping.get("properties", {})))
    required = set(cast(list[str], resolved_mapping.get("required", [])))
    for part in cast(list[object], resolved_mapping.get("allOf", [])):
        if not isinstance(part, dict):
            raise ValueError("OpenAPI allOf member is not an object")
        child_properties, child_required = merged_openapi_object(
            document, cast(dict[str, Any], part)
        )
        overlap = set(properties).intersection(child_properties)
        if overlap:
            raise ValueError(f"OpenAPI allOf duplicates properties: {sorted(overlap)}")
        properties.update(child_properties)
        required.update(child_required)
    return properties, required


def validate_curated_protojson(
    raw: Mapping[str, Any],
    curated: Mapping[str, Any],
) -> None:
    """Reject curated component shapes that differ from descriptor ProtoJSON."""
    raw_components = cast(
        dict[str, dict[str, Any]], cast(dict[str, Any], raw["components"])["schemas"]
    )
    curated_components = cast(dict[str, dict[str, Any]], curated["components"]["schemas"])
    component_messages: dict[str, str] = {}
    for component_name, schema in curated_components.items():
        authorities = schema_authority_names(schema)
        if len(authorities) > 1:
            raise ValueError(
                f"OpenAPI component has multiple message authorities: {component_name}"
            )
        if authorities:
            component_messages[component_name] = next(iter(authorities))
            continue
        inferred = f"mindclade.api.v1.{component_name}"
        if inferred in raw_components:
            component_messages[component_name] = inferred

    validated_messages: set[str] = set()

    def validate_schema(
        curated_schema: Mapping[str, Any],
        raw_schema: Mapping[str, Any],
        context: str,
    ) -> None:
        expected_ref = raw_schema.get("$ref")
        if isinstance(expected_ref, str):
            expected_message = expected_ref.removeprefix("#/components/schemas/")
            curated_ref = curated_schema.get("$ref")
            if not isinstance(curated_ref, str) or not curated_ref.startswith(
                "#/components/schemas/"
            ):
                raise ValueError(f"{context}: expected a message schema reference")
            component_name = curated_ref.rsplit("/", 1)[1]
            actual_ref = component_messages.get(component_name)
            if actual_ref != expected_message:
                raise ValueError(
                    f"{context}: expected {expected_message}, got {actual_ref or component_name}"
                )
            validate_message(component_name, expected_message, context)
            return

        resolved = resolve_openapi_ref(curated, curated_schema)
        if not isinstance(resolved, dict):
            raise ValueError(f"{context}: schema did not resolve to an object")
        resolved_mapping = cast(dict[str, object], resolved)
        expected_type = raw_schema.get("type")
        actual_type = resolved_mapping.get("type")
        if expected_type != actual_type:
            raise ValueError(
                f"{context}: ProtoJSON type mismatch: expected {expected_type}, got {actual_type}"
            )
        if expected_type == "array":
            raw_items = raw_schema.get("items")
            actual_items = resolved_mapping.get("items")
            if not isinstance(raw_items, dict) or not isinstance(actual_items, dict):
                raise ValueError(f"{context}: array item schema is missing")
            validate_schema(
                cast(dict[str, Any], actual_items),
                cast(dict[str, Any], raw_items),
                f"{context}[]",
            )
        elif expected_type == "object" and "additionalProperties" in raw_schema:
            raw_values = raw_schema["additionalProperties"]
            actual_values = resolved_mapping.get("additionalProperties")
            if not isinstance(raw_values, dict) or not isinstance(actual_values, dict):
                raise ValueError(f"{context}: map value schema is missing")
            validate_schema(
                cast(dict[str, Any], actual_values),
                cast(dict[str, Any], raw_values),
                f"{context}{{}}",
            )
        expected_enum = raw_schema.get("enum")
        if expected_enum is not None and resolved_mapping.get("enum") != expected_enum:
            raise ValueError(f"{context}: ProtoJSON enum mismatch")
        expected_format = raw_schema.get("format")
        if expected_format is not None and resolved_mapping.get("format") != expected_format:
            actual_format = resolved_mapping.get("format")
            raise ValueError(f"{context}: expected format {expected_format}, got {actual_format}")

    def validate_message(component_name: str, message_name: str, context: str) -> None:
        if message_name in validated_messages:
            return
        validated_messages.add(message_name)
        raw_message = raw_components.get(message_name)
        if raw_message is None:
            raise ValueError(f"{context}: unknown descriptor message {message_name}")
        properties, required = merged_openapi_object(curated, curated_components[component_name])
        raw_properties = cast(dict[str, dict[str, Any]], raw_message["properties"])
        if set(properties) != set(raw_properties):
            raise ValueError(
                f"{context}: ProtoJSON property drift for {message_name}: "
                f"curated-only={sorted(set(properties) - set(raw_properties))}, "
                f"descriptor-only={sorted(set(raw_properties) - set(properties))}"
            )
        expected_required = set(cast(list[str], raw_message["required"]))
        if required != expected_required:
            raise ValueError(
                f"{context}: requiredness drift for {message_name}: "
                f"curated={sorted(required)}, descriptor={sorted(expected_required)}"
            )
        for field_name, raw_field in raw_properties.items():
            validate_schema(
                cast(dict[str, Any], properties[field_name]),
                raw_field,
                f"{context}.{field_name}",
            )

    def operation_schema(operation: Mapping[str, Any], success_status: int) -> dict[str, Any]:
        response = cast(dict[str, Any], operation["responses"][str(success_status)])
        response = cast(dict[str, Any], resolve_openapi_ref(curated, response))
        content = cast(dict[str, dict[str, Any]], response.get("content", {}))
        for media_type in ("application/json", "text/event-stream"):
            if media_type in content:
                return cast(dict[str, Any], content[media_type]["schema"])
        raise ValueError(f"operation response has no ProtoJSON schema: {operation['operationId']}")

    operation_by_id = {
        operation["operationId"]: operation
        for path_item in cast(dict[str, dict[str, Any]], curated["paths"]).values()
        for method, operation in path_item.items()
        if method in {"delete", "get", "patch", "post", "put"}
    }
    for raw_operation in cast(list[dict[str, Any]], raw["x-mindclade-binding-contracts"]):
        operation_id = cast(str, raw_operation["operationId"])
        operation = operation_by_id[operation_id]
        body_message = raw_operation.get("bodyMessage")
        if isinstance(body_message, str):
            body = cast(dict[str, Any], operation["requestBody"])
            content = cast(dict[str, dict[str, Any]], body["content"])
            validate_schema(
                cast(dict[str, Any], content["application/json"]["schema"]),
                {"$ref": "#/components/schemas/" + body_message},
                f"{operation_id}.request",
            )
        validate_schema(
            operation_schema(operation, cast(list[int], raw_operation["successStatus"])[0]),
            {"$ref": "#/components/schemas/" + raw_operation["responseMessage"]},
            f"{operation_id}.response",
        )
        for status_code in cast(list[int], raw_operation["responseStatus"]):
            if status_code in raw_operation["successStatus"] or status_code == 304:
                continue
            error_response = cast(
                dict[str, Any],
                resolve_openapi_ref(
                    curated,
                    cast(dict[str, Any], operation["responses"][str(status_code)]),
                ),
            )
            error_content = cast(dict[str, dict[str, Any]], error_response["content"])
            validate_schema(
                cast(dict[str, Any], error_content["application/problem+json"]["schema"]),
                {"$ref": "#/components/schemas/mindclade.api.v1.PublicError"},
                f"{operation_id}.error.{status_code}",
            )
    for component_name, message_name in sorted(component_messages.items()):
        validate_message(component_name, message_name, f"component.{component_name}")


def validate_curated_bindings(
    raw: Mapping[str, Any],
    curated: Mapping[str, Any],
) -> None:
    """Prove method, path, query, body, auth, status, header, and stream parity."""
    methods = {"delete", "get", "patch", "post", "put"}
    operations: dict[str, tuple[str, str, dict[str, Any]]] = {}
    for path, path_item in cast(dict[str, dict[str, Any]], curated["paths"]).items():
        for method, operation in path_item.items():
            if method in methods:
                operations[operation["operationId"]] = (method.upper(), path, operation)
    raw_operations = {
        cast(str, operation["operationId"]): operation
        for operation in cast(list[dict[str, Any]], raw["x-mindclade-binding-contracts"])
    }
    if set(operations) != set(raw_operations):
        raise ValueError(
            "raw/curated public operation mismatch: "
            f"raw-only={sorted(set(raw_operations) - set(operations))}, "
            f"curated-only={sorted(set(operations) - set(raw_operations))}"
        )

    def parameters(operation: Mapping[str, Any]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for raw_parameter in cast(list[object], operation.get("parameters", [])):
            if not isinstance(raw_parameter, dict):
                raise ValueError("OpenAPI operation parameter is not an object")
            parameter = resolve_openapi_ref(curated, cast(dict[str, Any], raw_parameter))
            if not isinstance(parameter, dict):
                raise ValueError("OpenAPI parameter did not resolve to an object")
            result.append(cast(dict[str, Any], parameter))
        return result

    def skeleton(path: str, *, descriptor: bool) -> str:
        if descriptor:
            path = re.sub(r"\{[^={}]+=([^{}]+)\}", r"\1", path)
            return path.replace("*", "{}")
        return re.sub(r"\{[^{}]+\}", "{}", path)

    global_security = curated.get("security")
    for operation_id, raw_operation in raw_operations.items():
        method, path, operation = operations[operation_id]
        if method != raw_operation["method"]:
            raise ValueError(f"{operation_id}: HTTP method drift")
        if skeleton(path, descriptor=False) != skeleton(
            cast(str, raw_operation["pathTemplate"]), descriptor=True
        ):
            raise ValueError(f"{operation_id}: HTTP path binding drift")
        effective_security = operation.get("security", global_security)
        if raw_operation["auth"] == "bearer" and effective_security != [{"bearerAuth": []}]:
            raise ValueError(f"{operation_id}: bearer authentication drift")
        operation_parameters = parameters(operation)
        request_headers = sorted(
            parameter["name"] for parameter in operation_parameters if parameter["in"] == "header"
        )
        if request_headers != raw_operation["requestHeaders"]:
            raise ValueError(f"{operation_id}: request-header binding drift")
        required_request_headers = sorted(
            parameter["name"]
            for parameter in operation_parameters
            if parameter["in"] == "header" and parameter.get("required") is True
        )
        if required_request_headers != raw_operation["requiredRequestHeaders"]:
            raise ValueError(f"{operation_id}: request-header requiredness drift")
        query = {
            parameter["name"]: parameter
            for parameter in operation_parameters
            if parameter["in"] == "query"
        }
        raw_query = cast(dict[str, dict[str, Any]], raw_operation["queryFields"])
        if set(query) != set(raw_query):
            raise ValueError(f"{operation_id}: query binding drift")
        for name, raw_schema in raw_query.items():
            parameter_schema = query[name].get("schema")
            if not isinstance(parameter_schema, dict):
                raise ValueError(f"{operation_id}.{name}: query schema is missing")
            resolved = resolve_openapi_ref(curated, cast(dict[str, object], parameter_schema))
            if not isinstance(resolved, dict):
                raise ValueError(f"{operation_id}.{name}: query schema is not an object")
            resolved_mapping = cast(dict[str, object], resolved)
            if resolved_mapping.get("type") != raw_schema.get("type"):
                raise ValueError(f"{operation_id}.{name}: query ProtoJSON type drift")
            if raw_schema.get("format") is not None and resolved_mapping.get(
                "format"
            ) != raw_schema.get("format"):
                raise ValueError(f"{operation_id}.{name}: query ProtoJSON format drift")
        has_body = "requestBody" in operation
        if has_body != bool(raw_operation["body"]):
            raise ValueError(f"{operation_id}: request-body binding drift")
        if has_body and bool(operation["requestBody"].get("required")) != bool(
            raw_operation["requestBodyRequired"]
        ):
            raise ValueError(f"{operation_id}: request-body requiredness drift")
        path_parameters = [
            parameter for parameter in operation_parameters if parameter["in"] == "path"
        ]
        if any(parameter.get("required") is not True for parameter in path_parameters):
            raise ValueError(f"{operation_id}: path parameters must be required")
        expected_path_parameter_count = cast(str, raw_operation["pathTemplate"]).count("*")
        if len(path_parameters) != expected_path_parameter_count:
            raise ValueError(f"{operation_id}: path parameter expansion drift")
        if any(parameter.get("required") is True for parameter in query.values()):
            raise ValueError(f"{operation_id}: optional query-field requiredness drift")
        response_status = sorted(int(code) for code in operation["responses"])
        if response_status != raw_operation["responseStatus"]:
            raise ValueError(f"{operation_id}: documented response-status drift")
        success_status = sorted(
            int(code) for code in operation["responses"] if str(code).startswith("2")
        )
        if success_status != raw_operation["successStatus"]:
            raise ValueError(f"{operation_id}: success-status drift")
        response = cast(
            dict[str, Any],
            resolve_openapi_ref(
                curated, cast(dict[str, Any], operation["responses"][str(success_status[0])])
            ),
        )
        response_headers = sorted(cast(dict[str, Any], response.get("headers", {})))
        if response_headers != raw_operation["responseHeaders"]:
            raise ValueError(f"{operation_id}: response-header binding drift")
        content_types = set(cast(dict[str, Any], response.get("content", {})))
        expected_content = (
            {"text/event-stream"}
            if raw_operation["stream"] == "STREAM_PROJECTION_SSE"
            else {"application/octet-stream"}
            if raw_operation["stream"] == "STREAM_PROJECTION_BINARY"
            else {"application/json"}
        )
        if content_types != expected_content:
            raise ValueError(f"{operation_id}: response media-type/stream drift")
        for status_code in raw_operation["responseStatus"]:
            if status_code in raw_operation["successStatus"]:
                continue
            error_response = cast(
                dict[str, Any],
                resolve_openapi_ref(
                    curated,
                    cast(dict[str, Any], operation["responses"][str(status_code)]),
                ),
            )
            if error_response.get("headers"):
                raise ValueError(f"{operation_id}.{status_code}: response-header drift")
            error_content = set(cast(dict[str, Any], error_response.get("content", {})))
            expected_error_content: set[str] = (
                set() if status_code == 304 else {"application/problem+json"}
            )
            if error_content != expected_error_content:
                raise ValueError(f"{operation_id}.{status_code}: error media-type/body drift")


def curate_openapi_overlay(overlay: Mapping[str, Any]) -> dict[str, Any]:
    """Apply deterministic, semantics-preserving curation to the public overlay."""
    curated = cast(dict[str, Any], json.loads(json.dumps(overlay)))
    components = cast(dict[str, dict[str, Any]], curated.get("components", {}))
    reachable: dict[str, set[str]] = defaultdict(set)
    pending: list[str] = []

    def collect_references(value: object) -> None:
        if isinstance(value, dict):
            for key, child in cast(dict[str, object], value).items():
                if key == "$ref" and isinstance(child, str):
                    pending.append(child)
                else:
                    collect_references(child)
        elif isinstance(value, list):
            for child in cast(list[object], value):
                collect_references(child)

    collect_references(curated.get("paths", {}))
    while pending:
        reference = pending.pop()
        match = re.fullmatch(r"#/components/([^/]+)/([^/]+)", reference)
        if match is None:
            raise ValueError(f"curation encountered an unsupported reference: {reference}")
        section, name = match.groups()
        if name in reachable[section]:
            continue
        values = components.get(section)
        if values is None or name not in values:
            raise ValueError(f"curation encountered an unresolved reference: {reference}")
        reachable[section].add(name)
        collect_references(values[name])

    security_names: set[str] = set()
    for security in cast(list[object], curated.get("security", [])):
        if isinstance(security, dict):
            security_names.update(cast(dict[str, Any], security))
    for path_item in cast(dict[str, dict[str, Any]], curated.get("paths", {})).values():
        for operation in path_item.values():
            if not isinstance(operation, dict):
                continue
            operation_mapping = cast(dict[str, object], operation)
            for security in cast(list[object], operation_mapping.get("security", [])):
                if isinstance(security, dict):
                    security_names.update(cast(dict[str, Any], security))
    reachable["securitySchemes"].update(security_names)

    curated_components: dict[str, Any] = {}
    for section, values in components.items():
        selected = reachable.get(section, set())
        if selected:
            curated_components[section] = {
                name: values[name] for name in values if name in selected
            }
    curated["components"] = curated_components
    return curated


def openapi_pipeline_outputs(root: Path, descriptor_set: bytes) -> dict[Path, bytes]:
    """Return checked raw, curated, and published OpenAPI candidate stages."""
    raw = public_openapi_projection(descriptor_set)
    curated_source = root / "protocols/openapi/external-api.yaml"
    raw_overlay: object = yaml.safe_load(curated_source.read_text(encoding="utf-8"))
    if not isinstance(raw_overlay, dict):
        raise ValueError("curated OpenAPI document is not an object")
    overlay = cast(dict[str, object], raw_overlay)
    if not isinstance(overlay.get("paths"), dict):
        raise ValueError("curated OpenAPI document has no paths object")
    curated = curate_openapi_overlay(overlay)
    descriptor_digest = raw.get("x-mindclade-descriptor-digest")
    if not isinstance(descriptor_digest, str):
        raise ValueError("raw OpenAPI projection has no descriptor digest")
    curated["x-mindclade-descriptor-digest"] = descriptor_digest
    validate_curated_bindings(raw, curated)
    validate_curated_protojson(raw, curated)
    curated_bytes = (
        "# Code generated by mindclade-contract-codegen. DO NOT EDIT.\n"
        + yaml.safe_dump(curated, sort_keys=False, allow_unicode=True)
    ).encode()
    raw_bytes = (
        "# Code generated by mindclade-contract-codegen. DO NOT EDIT.\n"
        + yaml.safe_dump(raw, sort_keys=False, allow_unicode=True)
    ).encode()
    return {
        root / "protocols/openapi/raw/mindclade.openapi.yaml": raw_bytes,
        root / "protocols/openapi/curated/mindclade.openapi.yaml": curated_bytes,
        root / "protocols/openapi/published/mindclade.openapi.yaml": curated_bytes,
    }


def openapi_candidate_lock(root: Path, generated: Mapping[Path, bytes]) -> bytes:
    """Bind every editable and generated OpenAPI candidate source by digest."""
    openapi_root = root / "protocols/openapi"
    sources = {
        path
        for path in openapi_root.rglob("*")
        if path.is_file() and path.suffix in {".json", ".yaml"}
    }
    sources.update(generated)
    digests: dict[str, str] = {}
    for path in sorted(sources):
        content = generated[path] if path in generated else path.read_bytes()
        digests[path.relative_to(root).as_posix()] = sha256_bytes(content)
    return (
        json.dumps(
            {
                "schema_version": "mindclade.openapi-candidate/v1",
                "sources": digests,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode()


def validate_staged_descriptor_joins(
    root: Path,
    outputs: Mapping[Path, bytes],
    descriptor_digest: str,
) -> None:
    """Prove every staged projection is joined to the same descriptor image."""

    json_fields = {
        PROTOBUF_CANDIDATE: ("descriptor_set", "digest"),
        SDK_RPC_COVERAGE: ("descriptor_digest",),
        GRPC_IMPLEMENTATION_COVERAGE: ("descriptor_digest",),
        GENERATED_MANIFEST: ("descriptor_digest",),
    }
    for relative, field_path in json_fields.items():
        content = outputs.get(root / relative)
        if content is None:
            if relative == GENERATED_MANIFEST:
                continue
            raise ValueError(f"staged descriptor projection is absent: {relative}")
        value: object = json.loads(content)
        for field in field_path:
            if not isinstance(value, dict):
                raise ValueError(f"staged descriptor projection is malformed: {relative}")
            value = cast(dict[str, object], value).get(field)
        if value != descriptor_digest:
            raise ValueError(
                f"staged descriptor digest mismatch in {relative}: "
                f"expected {descriptor_digest}, got {value!r}"
            )

    for relative in (
        Path("protocols/openapi/raw/mindclade.openapi.yaml"),
        Path("protocols/openapi/curated/mindclade.openapi.yaml"),
        Path("protocols/openapi/published/mindclade.openapi.yaml"),
    ):
        content = outputs.get(root / relative)
        if content is None:
            raise ValueError(f"staged OpenAPI projection is absent: {relative}")
        value: object = yaml.safe_load(content)
        if (
            not isinstance(value, dict)
            or cast(dict[str, object], value).get("x-mindclade-descriptor-digest")
            != descriptor_digest
        ):
            raise ValueError(f"staged OpenAPI descriptor digest mismatch: {relative}")

    # Formatters may adjust type spelling or whitespace around these declarations.
    # Require both the language-specific authority symbol and the exact shared
    # descriptor digest instead of coupling the join check to formatter output.
    registry_markers = {
        Path("protocols/generated/python/mindclade/events/registry.py"): b"EVENT_DESCRIPTOR_DIGEST",
        Path("protocols/generated/rust/lib.rs"): b"EVENT_DESCRIPTOR_DIGEST",
        Path("protocols/generated/typescript/common/v1/index.ts"): b"EVENT_DESCRIPTOR_DIGEST",
        Path("services/control_plane/internal/platform/queue/event_registry_generated.go"): (
            b"authoritativeEventDescriptorDigest"
        ),
    }
    descriptor_marker = descriptor_digest.encode()
    for relative, symbol in registry_markers.items():
        content = outputs.get(root / relative)
        if content is None or symbol not in content or descriptor_marker not in content:
            raise ValueError(f"staged event registry descriptor digest mismatch: {relative}")


def generated_outputs(root: Path) -> tuple[dict[Path, bytes], bytes, list[dict[str, Any]]]:
    if __package__:
        from tools.codegen.generate_grpc_implementation_coverage import (
            render as render_grpc_implementation_coverage,
        )
        from tools.codegen.generate_schemas import generated_binding_outputs
        from tools.codegen.generate_sdk_coverage import render as render_sdk_coverage
    else:
        from generate_grpc_implementation_coverage import (
            render as render_grpc_implementation_coverage,
        )
        from generate_schemas import generated_binding_outputs
        from generate_sdk_coverage import render as render_sdk_coverage

    lock = toolchain(root)
    with tempfile.TemporaryDirectory(prefix="mindclade-codegen-") as temporary:
        staging = Path(temporary)
        rust_plugin_path = ensure_toolchain(root, staging, lock)
        descriptor_set, descriptors = build_descriptors(root, staging)
        descriptor_digest = sha256_bytes(descriptor_set)
        validate_manifest(root, descriptors)
        outputs: dict[Path, bytes] = {}
        raw_roots = {
            language: generate_language(
                root, staging, language, descriptors, lock, rust_plugin_path
            )
            for language in LANGUAGES
        }
        by_name = {cast(str, item["name"]): item for item in descriptors}
        ts_raw_to_target = {
            raw_path(raw_roots["typescript"], "typescript", item).resolve(): target_path(
                root, "typescript", item
            )
            for item in descriptors
            if "typescript" in declared_languages(lock, cast(str, item["package"]))
        }
        external_typescript = {
            (raw_roots["typescript"] / "google/api/annotations_pb.ts").resolve(): (
                root / "protocols/generated/typescript/google/api/annotations_pb.ts"
            ),
            (raw_roots["typescript"] / "google/api/http_pb.ts").resolve(): (
                root / "protocols/generated/typescript/google/api/http_pb.ts"
            ),
        }
        ts_raw_to_target.update(external_typescript)
        for descriptor in descriptors:
            package = cast(str, descriptor["package"])
            for language in declared_languages(lock, package):
                if language == "rust":
                    variants = [(raw_path(raw_roots[language], language, descriptor), ".rs")]
                    if descriptor.get("service"):
                        variants.append(
                            (
                                raw_variant_path(
                                    raw_roots[language], language, descriptor, "_grpc.rs"
                                ),
                                "_grpc.rs",
                            )
                        )
                else:
                    variants = [
                        (
                            raw_variant_path(raw_roots[language], language, descriptor, suffix),
                            suffix,
                        )
                        for suffix in GENERATED_SUFFIXES[language]
                    ]
                for source, suffix in variants:
                    if not source.is_file():
                        continue
                    target = target_path(root, language, descriptor, suffix)
                    content = source.read_text(encoding="utf-8")
                    if language == "python":
                        content = normalize_python(content, descriptors)
                    elif language == "rust":
                        content = normalize_rust(
                            content,
                            descriptor,
                            by_name,
                            is_prost=suffix == ".rs",
                        )
                    elif language == "typescript":
                        content = normalize_typescript(
                            content, source.resolve(), target, ts_raw_to_target
                        )
                    outputs[target] = content.encode()
        schema_outputs = generated_binding_outputs(root)
        overlap = set(outputs).intersection(schema_outputs)
        if overlap:
            raise ValueError(f"schema binding output collision: {sorted(map(str, overlap))}")
        outputs.update(schema_outputs)
        for source, target in external_typescript.items():
            if not source.is_file():
                raise ValueError(f"missing generated Google API TypeScript dependency: {source}")
            outputs[target] = normalize_typescript(
                source.read_text(encoding="utf-8"), source, target, ts_raw_to_target
            ).encode()
        language_metadata(root, descriptors, lock, outputs)
        openapi_outputs = openapi_pipeline_outputs(root, descriptor_set)
        overlap = set(outputs).intersection(openapi_outputs)
        if overlap:
            raise ValueError(f"OpenAPI output collision: {sorted(map(str, overlap))}")
        outputs.update(openapi_outputs)
        outputs[root / OPENAPI_CANDIDATE] = openapi_candidate_lock(root, openapi_outputs)

        outputs[root / "protocols/generated/python/mindclade/events/registry.py"] = (
            event_registry_python(root, descriptors, descriptor_digest)
        )
        rust_registry = event_registry_rust(root, descriptors, descriptor_digest).decode("utf-8")
        rust_lib = root / "protocols/generated/rust/lib.rs"
        outputs[rust_lib] += (
            "\npub mod event_registry {\n"
            + "\n".join(
                "    " + line if line else "" for line in rust_registry.rstrip().splitlines()
            )
            + "\n}\n"
        ).encode()
        outputs[rust_lib] = format_generated_rust_metadata(root, staging, outputs[rust_lib])
        typescript_index = root / "protocols/generated/typescript/common/v1/index.ts"
        outputs[typescript_index] += b"\n" + event_registry_typescript(
            root, descriptors, descriptor_digest
        )
        outputs[
            root / "services/control_plane/internal/platform/queue/event_registry_generated.go"
        ] = event_registry_go(root, descriptors, descriptor_digest)

        outputs[root / PROTOBUF_CANDIDATE] = protobuf_candidate(root, descriptors, descriptor_set)
        format_generated_build_files(root, staging, outputs)
        outputs[root / SDK_RPC_COVERAGE] = render_sdk_coverage(
            root,
            descriptor_bytes=descriptor_set,
            generated_outputs=outputs,
        )
        outputs[root / GRPC_IMPLEMENTATION_COVERAGE] = render_grpc_implementation_coverage(
            root,
            descriptor_bytes=descriptor_set,
        )
        validate_staged_descriptor_joins(root, outputs, descriptor_digest)
        generated = root / "protocols/generated"
        manifest_files = {
            path.relative_to(root).as_posix(): sha256_bytes(content)
            for path, content in sorted(outputs.items())
        }
        outputs[generated / "generated-files.manifest.json"] = (
            json.dumps(
                {
                    "descriptor_digest": descriptor_digest,
                    "files": manifest_files,
                    "generator": GENERATOR,
                    "input_digests": {
                        relative: sha256_file(root / relative)
                        for relative in (
                            "Cargo.lock",
                            "Cargo.toml",
                            "buf.gen.yaml",
                            "buf.lock",
                            "buf.yaml",
                            "flake.lock",
                            "go.mod",
                            "go.sum",
                            "package.json",
                            "pnpm-lock.yaml",
                            "pnpm-workspace.yaml",
                            "pyproject.toml",
                            "protocols/events/registry.yaml",
                            "protocols/openapi/compatibility-policy.yaml",
                            "protocols/openapi/external-api.yaml",
                            "protocols/openapi/generation.yaml",
                            "internal/sdk/rpc-coverage.yaml",
                            "services/control_plane/grpc-implementation.yaml",
                            "protocols/generated/python/pyproject.toml",
                            "protocols/generated/rust/Cargo.toml",
                            "protocols/generated/typescript/package.json",
                            "protocols/generated/typescript/tsconfig.json",
                            "tools/codegen/generate_protocols.py",
                            "tools/codegen/generate_sdk_coverage.py",
                            "tools/codegen/generate_grpc_implementation_coverage.py",
                            "tools/codegen/generate_schemas.py",
                            "tools/codegen/rust_plugins/Cargo.toml",
                            "tools/codegen/rust_plugins/src/bin/protoc-gen-prost.rs",
                            "tools/codegen/rust_plugins/src/bin/protoc-gen-tonic.rs",
                            "tools/codegen/toolchain.lock.json",
                            "uv.lock",
                            "docs/architecture/repository-path-manifest.yaml",
                            *sorted(
                                path.relative_to(root).as_posix()
                                for path in (root / "protocols/schemas").glob("*/*.json")
                            ),
                        )
                    },
                    "schema_version": "mindclade.generated-files/v2",
                    "toolchain_digest": sha256_file(root / "tools/codegen/toolchain.lock.json"),
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode()
        validate_staged_descriptor_joins(root, outputs, descriptor_digest)
        validate_manifest(root, descriptors, outputs)
        return outputs, descriptor_set, descriptors


def generation_authority_digest(root: Path) -> str:
    """Snapshot every tracked or review-visible source before a staged build."""

    raw_paths = run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=root,
    ).stdout
    material = bytearray()
    for raw_relative in sorted(value for value in raw_paths.split(b"\x00") if value):
        relative = Path(os.fsdecode(raw_relative))
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"unsafe repository source path: {relative}")
        path = root / relative
        material.extend(raw_relative)
        material.extend(b"\x00")
        if path.is_symlink():
            material.extend(b"symlink:\x00")
            material.extend(os.fsencode(path.readlink()))
        elif path.is_file():
            material.extend(b"file:\x00")
            material.extend(hashlib.sha256(path.read_bytes()).digest())
        else:
            material.extend(b"missing:\x00")
        material.extend(b"\x00")
    return sha256_bytes(bytes(material))


@contextmanager
def exclusive_generation_lock(root: Path) -> Generator[None, None, None]:
    """Serialize complete contract transactions without mutating authority files."""

    lock_root = root / "build/codegen"
    lock_root.mkdir(parents=True, exist_ok=True)
    lock_path = lock_root / "generation.lock"
    with lock_path.open("a+b") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def atomic_replace_generated_file(path: Path, content: bytes, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        prefix=f".{path.name}.",
        dir=path.parent,
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        temporary.chmod(mode)
        temporary.replace(path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


def commit_generation_transaction(
    root: Path,
    outputs: Mapping[Path, bytes],
    stale_paths: Sequence[Path],
) -> None:
    """Commit a validated generation set and roll it back on any write error."""

    normalized_outputs: dict[Path, bytes] = {}
    for path, content in outputs.items():
        try:
            path.relative_to(root)
        except ValueError as error:
            raise ValueError(f"generated output escapes repository root: {path}") from error
        normalized_outputs[path] = content
    normalized_stale: set[Path] = set()
    for path in stale_paths:
        try:
            path.relative_to(root)
        except ValueError as error:
            raise ValueError(f"stale generated path escapes repository root: {path}") from error
        if path.is_symlink():
            raise ValueError(f"stale generated path must not be a symlink: {path}")
        if path not in normalized_outputs and path.is_file():
            normalized_stale.add(path)

    targets = set(normalized_outputs) | normalized_stale
    originals: dict[Path, tuple[bytes, int] | None] = {}
    for path in targets:
        if path.is_symlink():
            raise ValueError(f"generated output target must not be a symlink: {path}")
        if path.exists() and not path.is_file():
            raise ValueError(f"generated output target is not a regular file: {path}")
        originals[path] = (
            (path.read_bytes(), path.stat().st_mode & 0o777) if path.is_file() else None
        )

    stage_parent = root / "build/codegen"
    stage_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".contract-transaction-",
        dir=stage_parent,
    ) as temporary:
        stage = Path(temporary) / "payload"
        for path, content in sorted(normalized_outputs.items()):
            staged = stage / path.relative_to(root)
            staged.parent.mkdir(parents=True, exist_ok=True)
            staged.write_bytes(content)
            if staged.read_bytes() != content:
                raise RuntimeError(f"staged generation verification failed: {path}")

        committed: list[Path] = []
        try:
            for path in sorted(normalized_stale, reverse=True):
                path.unlink()
                committed.append(path)
            manifest_path = root / GENERATED_MANIFEST
            write_order = sorted(path for path in normalized_outputs if path != manifest_path)
            if manifest_path in normalized_outputs:
                write_order.append(manifest_path)
            for path in write_order:
                content = (stage / path.relative_to(root)).read_bytes()
                atomic_replace_generated_file(path, content)
                committed.append(path)
        except BaseException as error:
            rollback_errors: list[str] = []
            for path in reversed(committed):
                original = originals[path]
                try:
                    if original is None:
                        path.unlink(missing_ok=True)
                    else:
                        atomic_replace_generated_file(path, original[0], original[1])
                except OSError as rollback_error:
                    rollback_errors.append(f"{path}: {rollback_error}")
            if rollback_errors:
                raise RuntimeError(
                    "generation commit failed and rollback was incomplete: "
                    + "; ".join(rollback_errors)
                ) from error
            raise


def generation_drift(
    root: Path,
    outputs: Mapping[Path, bytes],
    stale_paths: Sequence[Path],
) -> list[Path]:
    """Return deterministic drift without modifying any repository output."""

    drift = [
        path
        for path, content in outputs.items()
        if not path.is_file() or path.read_bytes() != content
    ]
    drift.extend(path for path in stale_paths if path not in outputs and path.is_file())
    return sorted(set(drift))


def write_generated(
    root: Path,
    *,
    ratify_v1_baseline: bool,
    expected_candidate_digest: str | None,
    training_vertical_evidence: Path | None,
    check: bool = False,
) -> bool:
    source_digest_before = generation_authority_digest(root)
    outputs, descriptor_set, descriptors = generated_outputs(root)
    source_digest_after = generation_authority_digest(root)
    if source_digest_after != source_digest_before:
        raise RuntimeError(
            "contract generation inputs changed during the staged transaction; "
            "no authoritative output was updated"
        )
    predecessor = root / PROTOBUF_PREDECESSOR
    if not predecessor.is_file() or sha256_file(predecessor) != PREDECESSOR_ARTIFACT_DIGEST:
        raise RuntimeError("the archived 22-source Protobuf predecessor is missing or has changed")
    candidate_content = outputs[root / PROTOBUF_CANDIDATE]
    candidate_path = root / PROTOBUF_CANDIDATE
    baseline_path = root / PROTOBUF_RATIFIED_BASELINE
    ratified_baseline: bytes | None = None
    if baseline_path.is_file() and not ratify_v1_baseline:
        baseline = load_json(baseline_path)
        if baseline.get("schema_version") != "mindclade.protobuf-baseline/v3":
            raise RuntimeError("the ratified Protobuf baseline has an unsupported format")
        raw_descriptor = baseline.get("descriptor_set")
        if not isinstance(raw_descriptor, dict):
            raise ValueError("the ratified Protobuf baseline has no descriptor set")
        encoded_descriptor = cast(dict[str, object], raw_descriptor).get("base64")
        if not isinstance(encoded_descriptor, str):
            raise ValueError("the ratified Protobuf baseline has no descriptor bytes")
        with tempfile.NamedTemporaryFile(suffix=".binpb") as previous_file:
            previous_file.write(base64.b64decode(encoded_descriptor, validate=True))
            previous_file.flush()
            run(["buf", "breaking", "--against", previous_file.name], cwd=root)
    if ratify_v1_baseline:
        if baseline_path.exists():
            raise RuntimeError("v1 is already ratified; baseline replacement is prohibited")
        if not candidate_path.is_file() or candidate_path.read_bytes() != candidate_content:
            raise RuntimeError(
                "ratification requires an up-to-date committed candidate; run ordinary "
                "generation and review it first"
            )
        actual_candidate_digest = sha256_bytes(candidate_content)
        if expected_candidate_digest != actual_candidate_digest:
            raise RuntimeError(
                "ratification requires the exact reviewed candidate artifact digest: "
                f"expected {expected_candidate_digest!r}, actual {actual_candidate_digest!r}"
            )
        if training_vertical_evidence is None:
            raise RuntimeError("ratification requires training vertical evidence")
        event_entries, _ = event_registry_entries(root, descriptors)
        event_blockers = event_registry_ratification_blockers(event_entries)
        if event_blockers:
            preview = ", ".join(event_blockers[:8])
            suffix = "" if len(event_blockers) <= 8 else f" (+{len(event_blockers) - 8} more)"
            raise RuntimeError(
                "ratification requires every descriptor-visible event to be active with "
                f"producer, semantic consumer, and fixture evidence; blockers: {preview}{suffix}"
            )
        candidate = cast(dict[str, Any], json.loads(candidate_content))
        descriptor_digest = cast(dict[str, str], candidate["descriptor_set"])["digest"]
        event_registry_digest = cast(dict[str, str], candidate["event_registry"])["digest"]
        bindings = ratification_bindings(
            root,
            candidate_descriptor_digest=descriptor_digest,
            event_registry_digest=event_registry_digest,
        )
        evidence, evidence_digest = validate_training_vertical_evidence(
            root,
            training_vertical_evidence,
            bindings=bindings,
        )
        ratified_baseline = ratified_protobuf_baseline(
            candidate,
            bindings=bindings,
            evidence=evidence,
            evidence_digest=evidence_digest,
        )
    stale_candidates = sorted(
        governed_generated_paths(root)
        | previous_generated_paths(root)
        | discovered_generated_paths(root)
    )
    if generation_authority_digest(root) != source_digest_before:
        raise RuntimeError(
            "contract generation inputs changed before commit; no authoritative output was updated"
        )
    if check:
        drift = generation_drift(root, outputs, stale_candidates)
        for path in drift:
            print(path.relative_to(root).as_posix())
        return not drift

    materialized_outputs = dict(outputs)
    if ratified_baseline is not None:
        materialized_outputs[baseline_path] = ratified_baseline
    openapi_outputs = openapi_pipeline_outputs(root, descriptor_set)
    materialized_outputs.update(
        {
            root / "build/openapi/raw/descriptor-projection.yaml": openapi_outputs[
                root / "protocols/openapi/raw/mindclade.openapi.yaml"
            ],
            root / "build/openapi/curated/external-api.yaml": openapi_outputs[
                root / "protocols/openapi/curated/mindclade.openapi.yaml"
            ],
            root / "build/openapi/published/external-api.yaml": openapi_outputs[
                root / "protocols/openapi/published/mindclade.openapi.yaml"
            ],
        }
    )
    commit_generation_transaction(root, materialized_outputs, stale_candidates)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--ratify-v1-baseline",
        action="store_true",
        help="ratify the reviewed candidate after the training vertical evidence gate",
    )
    parser.add_argument(
        "--expected-candidate-digest",
        help="sha256 digest of the exact reviewed candidate artifact",
    )
    parser.add_argument(
        "--training-vertical-evidence",
        type=Path,
        help="passed evidence receipt covering every required training vertical boundary",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="validate the complete atomic generation plan without updating files",
    )
    args = parser.parse_args()
    if args.check and args.ratify_v1_baseline:
        parser.error("--check cannot be combined with --ratify-v1-baseline")
    ratification_arguments = bool(args.expected_candidate_digest or args.training_vertical_evidence)
    if args.ratify_v1_baseline != ratification_arguments:
        parser.error(
            "--ratify-v1-baseline requires --expected-candidate-digest and "
            "--training-vertical-evidence; those arguments are invalid during ordinary generation"
        )
    if args.ratify_v1_baseline and (
        not args.expected_candidate_digest or args.training_vertical_evidence is None
    ):
        parser.error(
            "--ratify-v1-baseline requires both --expected-candidate-digest and "
            "--training-vertical-evidence"
        )
    root = args.root.resolve()
    with exclusive_generation_lock(root):
        current = write_generated(
            root,
            ratify_v1_baseline=args.ratify_v1_baseline,
            expected_candidate_digest=args.expected_candidate_digest,
            training_vertical_evidence=(
                args.training_vertical_evidence.resolve()
                if args.training_vertical_evidence is not None
                else None
            ),
            check=args.check,
        )
    return 0 if current else 1


if __name__ == "__main__":
    raise SystemExit(main())
