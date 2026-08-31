#!/usr/bin/env python3.12
"""Generate committed Protobuf bindings with the locked native toolchain."""

from __future__ import annotations

import argparse
import base64
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
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

import yaml

GENERATOR = "mindclade-contract-codegen 3.1.0"
LANGUAGES = ("go", "python", "rust", "typescript")
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
    binary_root = target / "release"
    for name in ("protoc-gen-prost", "protoc-gen-tonic"):
        binary = binary_root / name
        if not binary.is_file():
            raise RuntimeError(f"cargo did not build the locked {name} binary")
        actual = command_version([str(binary), "--version"], root)
        if actual != tools[name]["version_output"]:
            raise RuntimeError(
                f"{name} version mismatch: expected {tools[name]['version_output']!r}, "
                f"got {actual!r}"
            )
    return binary_root


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


def projection_path(package: str) -> Path:
    return Path(*projection_parts(package))


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
    for value in cast(dict[str, object], raw_files):
        relative = Path(value)
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or relative.parts[:2] != ("protocols", "generated")
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
    package_path = projection_path(cast(str, descriptor["package"]))
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
            *projection_parts(cast(str, descriptor["package"])),
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
            f"from {'.'.join(projection_parts(cast(str, item['package'])))} "
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
            outputs[generated / "python" / package_path / "__init__.py"] = (
                f"# Code generated by {GENERATOR}; DO NOT EDIT.\n"
            ).encode()

        go_descriptors = [
            item
            for item in by_projection[projection]
            if "go" in declared_languages(lock, cast(str, item["package"]))
        ]
        if go_descriptors:
            go_sources = sorted(
                path.name
                for path in outputs
                if path.parent == generated / "go" / package_path and path.name.endswith(".go")
            )
            dependency_projections = sorted(
                {
                    projection_parts(cast(str, by_name[dependency]["package"]))
                    for item in go_descriptors
                    for dependency in cast(list[str], item.get("dependency", []))
                    if dependency in by_name
                    and projection_parts(cast(str, by_name[dependency]["package"])) != projection
                }
            )
            deps = [
                '"@org_golang_google_protobuf//reflect/protoreflect"',
                '"@org_golang_google_protobuf//runtime/protoimpl"',
            ]
            well_known_deps = {
                "google/protobuf/duration.proto": (
                    "@org_golang_google_protobuf//types/known/durationpb"
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
                f"github.com/mindclade/mindclade/protocols/generated/go/{package_path.as_posix()}"
            )
            outputs[generated / "go" / package_path / "BUILD.bazel"] = (
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
        ["BUILD.bazel", "README.generated.md"]
        + [
            f"//protocols/generated/go/{Path(*projection).as_posix()}:generated_sources"
            for projection in projections
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
        b'    deps = ["@mindclade_pypi//grpcio", "@mindclade_pypi//protobuf"],\n'
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
    rust_modules = rust_module_declarations(projections)
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
        b'        "@crate_index//:prost",\n'
        b'        "@crate_index//:prost-types",\n'
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
        b'load("@aspect_rules_ts//ts:defs.bzl", "ts_project")\n'
        b'load("@npm//:defs.bzl", "npm_link_all_packages")\n\n'
        b'npm_link_all_packages(name = "node_modules")\n\n'
        b"ts_project(\n"
        b'    name = "bindings",\n'
        b'    srcs = glob(["**/*.ts"], exclude = ["node_modules/**"]),\n'
        b"    declaration = True,\n"
        b'    tsconfig = "tsconfig.json",\n'
        b'    transpiler = "tsc",\n'
        b"    deps = [\n"
        b'        ":node_modules/@bufbuild/protobuf",\n'
        b'        ":node_modules/@connectrpc/connect",\n'
        b"    ],\n"
        b'    visibility = ["//visibility:public"],\n'
        b")\n\n"
        b"filegroup(\n"
        b'    name = "generated_sources",\n'
        b'    srcs = glob(["**/*"]),\n'
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


def protobuf_baseline(
    root: Path,
    descriptors: Sequence[Mapping[str, Any]],
    descriptor_set: bytes,
    *,
    predecessor_digest: str | None = None,
    reset_authority: str | None = None,
) -> bytes:
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
        "schema_version": "mindclade.protobuf-baseline/v2",
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
    if predecessor_digest is not None:
        if reset_authority is None:
            value["promotion"] = {
                "compatibility_check": "buf-breaking-file",
                "mode": "compatible",
                "predecessor_digest": predecessor_digest,
            }
        else:
            value["promotion"] = {
                "authority": reset_authority,
                "compatibility_check": "intentional-clean-v1-reset",
                "mode": "baseline-reset",
                "predecessor_digest": predecessor_digest,
            }
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def generated_outputs(root: Path) -> tuple[dict[Path, bytes], bytes, list[dict[str, Any]]]:
    lock = toolchain(root)
    with tempfile.TemporaryDirectory(prefix="mindclade-codegen-") as temporary:
        staging = Path(temporary)
        rust_plugin_path = ensure_toolchain(root, staging, lock)
        descriptor_set, descriptors = build_descriptors(root, staging)
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
        language_metadata(root, descriptors, lock, outputs)
        format_generated_build_files(root, staging, outputs)
        generated = root / "protocols/generated"
        manifest_files = {
            path.relative_to(root).as_posix(): sha256_bytes(content)
            for path, content in sorted(outputs.items())
        }
        outputs[generated / "generated-files.manifest.json"] = (
            json.dumps(
                {
                    "descriptor_digest": sha256_bytes(descriptor_set),
                    "files": manifest_files,
                    "generator": GENERATOR,
                    "input_digests": {
                        relative: sha256_file(root / relative)
                        for relative in (
                            "Cargo.lock",
                            "Cargo.toml",
                            "buf.gen.yaml",
                            "buf.yaml",
                            "flake.lock",
                            "go.mod",
                            "go.sum",
                            "package.json",
                            "pnpm-lock.yaml",
                            "pnpm-workspace.yaml",
                            "pyproject.toml",
                            "protocols/generated/python/pyproject.toml",
                            "protocols/generated/rust/Cargo.toml",
                            "protocols/generated/typescript/package.json",
                            "protocols/generated/typescript/tsconfig.json",
                            "tools/codegen/generate_protocols.py",
                            "tools/codegen/rust_plugins/Cargo.toml",
                            "tools/codegen/rust_plugins/src/bin/protoc-gen-prost.rs",
                            "tools/codegen/rust_plugins/src/bin/protoc-gen-tonic.rs",
                            "tools/codegen/toolchain.lock.json",
                            "uv.lock",
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
        validate_manifest(root, descriptors, outputs)
        return outputs, descriptor_set, descriptors


def write_generated(
    root: Path,
    *,
    promote_baseline: bool,
    reset_baseline: bool,
    expected_baseline_digest: str | None,
) -> None:
    outputs, descriptor_set, descriptors = generated_outputs(root)
    promoted_baseline: bytes | None = None
    baseline = root / "protocols/compatibility/baselines/protobuf.lock.json"
    if promote_baseline or reset_baseline:
        actual_digest = sha256_file(baseline)
        if expected_baseline_digest != actual_digest:
            raise RuntimeError(
                "baseline promotion requires the exact reviewed predecessor digest: "
                f"expected {expected_baseline_digest!r}, actual {actual_digest!r}"
            )
        recorded_predecessor_digest = actual_digest
        if promote_baseline:
            previous = load_json(baseline)
            raw_descriptor = previous.get("descriptor_set")
            if not isinstance(raw_descriptor, dict):
                raise ValueError("existing Protobuf baseline has no descriptor set")
            descriptor = cast(dict[str, Any], raw_descriptor)
            encoded_descriptor = descriptor.get("base64")
            if not isinstance(encoded_descriptor, str):
                raise ValueError("existing Protobuf baseline has no descriptor set")
            with tempfile.NamedTemporaryFile(suffix=".binpb") as previous_file:
                previous_file.write(base64.b64decode(encoded_descriptor, validate=True))
                previous_file.flush()
                run(["buf", "breaking", "--against", previous_file.name], cwd=root)
        reset_authority = None
        if reset_baseline:
            reset_authority = "docs/adr/0015-all-contracts-clean-v1-baseline.md"
            if not (root / reset_authority).is_file():
                raise RuntimeError(f"baseline reset authority is missing: {reset_authority}")
            previous = load_json(baseline)
            raw_promotion = previous.get("promotion")
            if isinstance(raw_promotion, dict):
                promotion = cast(dict[str, object], raw_promotion)
                original_predecessor = promotion.get("predecessor_digest")
                if (
                    promotion.get("mode") == "baseline-reset"
                    and promotion.get("authority") == reset_authority
                    and isinstance(original_predecessor, str)
                ):
                    recorded_predecessor_digest = original_predecessor
        promoted_baseline = protobuf_baseline(
            root,
            descriptors,
            descriptor_set,
            predecessor_digest=recorded_predecessor_digest,
            reset_authority=reset_authority,
        )
    stale_candidates = (
        governed_generated_paths(root)
        | previous_generated_paths(root)
        | discovered_generated_paths(root)
    )
    for path in sorted(stale_candidates, reverse=True):
        if path.is_file() and path not in outputs:
            path.unlink()
    for path, content in sorted(outputs.items()):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    if promoted_baseline is not None:
        baseline.write_bytes(promoted_baseline)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--promote-baseline",
        action="store_true",
        help="promote a compatible descriptor set from an exact reviewed predecessor",
    )
    parser.add_argument(
        "--reset-baseline",
        action="store_true",
        help="reset the clean-v1 descriptor baseline under ADR-0015 authority",
    )
    parser.add_argument(
        "--expected-baseline-digest",
        help="sha256 digest of the reviewed baseline being promoted",
    )
    args = parser.parse_args()
    if args.promote_baseline and args.reset_baseline:
        parser.error("choose either --promote-baseline or --reset-baseline")
    if bool(args.promote_baseline or args.reset_baseline) != bool(args.expected_baseline_digest):
        parser.error(
            "baseline changes require a promotion/reset mode and --expected-baseline-digest"
        )
    write_generated(
        args.root.resolve(),
        promote_baseline=args.promote_baseline,
        reset_baseline=args.reset_baseline,
        expected_baseline_digest=args.expected_baseline_digest,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
