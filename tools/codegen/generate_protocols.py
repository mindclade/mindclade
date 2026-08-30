#!/usr/bin/env python3.12
"""Generate committed Protobuf bindings with the locked native toolchain."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import subprocess
import tempfile
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

import yaml

GENERATOR = "mindclade-contract-codegen 2.0.0"
LANGUAGES = ("go", "python", "rust", "typescript")
PROTO_SUFFIX = {"go": ".pb.go", "python": "_pb2.py", "rust": ".rs", "typescript": "_pb.ts"}
TS_IMPORT = re.compile(r'from "(?P<path>[^"]+_pb)\.js"')


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
    merged_env.update({"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "TZ": "UTC"})
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
    if lock.get("schema_version") != "mindclade.codegen-toolchain/v2":
        raise ValueError("unsupported code-generation toolchain lock")
    return lock


def command_version(command: Sequence[str], root: Path) -> str:
    completed = run(command, cwd=root)
    return (completed.stdout + completed.stderr).decode("utf-8").strip().splitlines()[-1]


def ensure_toolchain(root: Path, lock: Mapping[str, Any]) -> Path:
    tools = cast(dict[str, dict[str, str]], lock["tools"])
    actual_versions = {
        "buf": command_version(["buf", "--version"], root),
        "protoc": command_version(["protoc", "--version"], root),
        "protoc-gen-go": command_version(["go", "tool", "protoc-gen-go", "--version"], root),
        "protoc-gen-es": command_version(["pnpm", "exec", "protoc-gen-es", "--version"], root),
    }
    for name, actual in actual_versions.items():
        wanted = tools[name]["version_output"]
        if actual != wanted:
            raise RuntimeError(f"{name} version mismatch: expected {wanted!r}, got {actual!r}")

    rust = tools["protoc-gen-rs"]
    cache_home = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    install_root = cache_home / "mindclade" / "codegen" / f"protobuf-codegen-{rust['version']}"
    binary = install_root / "bin" / "protoc-gen-rs"
    installed = b""
    if binary.is_file():
        installed = run(
            ["cargo", "install", "--list", "--root", str(install_root)], cwd=root
        ).stdout
    if f"protobuf-codegen v{rust['version']}:".encode() not in installed:
        run(
            [
                "cargo",
                "install",
                "--locked",
                "--root",
                str(install_root),
                "--version",
                rust["version"],
                "protobuf-codegen",
            ],
            cwd=root,
        )
    if not binary.is_file():
        raise RuntimeError("cargo did not install the locked protoc-gen-rs binary")
    return binary.parent


def build_descriptors(root: Path, staging: Path) -> tuple[bytes, list[dict[str, Any]]]:
    binary_path = staging / "descriptor-set.binpb"
    json_path = staging / "descriptor-set.json"
    common = ["buf", "build", "--exclude-source-info", "--as-file-descriptor-set"]
    run([*common, "-o", str(binary_path)], cwd=root)
    run([*common, "-o", str(json_path)], cwd=root)
    descriptor = load_json(json_path)
    files = descriptor.get("file")
    if not isinstance(files, list):
        raise ValueError("Buf descriptor set does not contain a file list")
    raw_files = cast(list[object], files)
    typed_files = [cast(dict[str, Any], item) for item in raw_files if isinstance(item, dict)]
    if len(typed_files) != len(raw_files):
        raise ValueError("Buf descriptor set contains a non-object file descriptor")
    return binary_path.read_bytes(), typed_files


def domain_for(package: str) -> str:
    parts = package.split(".")
    if len(parts) < 3 or parts[0] != "mindclade" or parts[-1] != "v1":
        raise ValueError(f"unsupported Protobuf package: {package}")
    return parts[-2]


def source_path(root: Path, descriptor: Mapping[str, Any]) -> Path:
    name = descriptor.get("name")
    if not isinstance(name, str):
        raise ValueError("file descriptor is missing its name")
    return root / "protocols" / name


def declared_languages(lock: Mapping[str, Any], package: str) -> frozenset[str]:
    matrix = cast(dict[str, list[str]], lock["domain_language_matrix"])
    values = matrix.get(package)
    if values is None:
        raise ValueError(f"Protobuf package is absent from the domain/language matrix: {package}")
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


def plugin_config(root: Path, language: str, output: Path) -> dict[str, Any]:
    config = load_json(root / "buf.gen.yaml")
    plugins = config.get("plugins")
    if not isinstance(plugins, list):
        raise ValueError("buf.gen.yaml must declare plugins")
    for raw_plugin in cast(list[object], plugins):
        if not isinstance(raw_plugin, dict):
            continue
        plugin = cast(dict[str, object], raw_plugin)
        out = plugin.get("out")
        if isinstance(out, str) and Path(out).name == language:
            selected = cast(dict[str, Any], dict(plugin))
            selected["out"] = str(output)
            return {"version": "v2", "clean": True, "plugins": [selected]}
    raise ValueError(f"buf.gen.yaml has no {language} plugin")


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
        groups = defaultdict(list)
        for descriptor in selected:
            groups[domain_for(cast(str, descriptor["package"]))].append(descriptor)
    else:
        groups = {language: selected}

    for group, group_descriptors in sorted(groups.items()):
        output = raw_root / group if language == "rust" else raw_root
        template = staging / f"buf.{language}.{group}.json"
        template.write_text(
            json.dumps(plugin_config(root, language, output), sort_keys=True), encoding="utf-8"
        )
        command = ["buf", "generate", "protocols", "--template", str(template)]
        for descriptor in group_descriptors:
            command.extend(["--path", f"protocols/{cast(str, descriptor['name'])}"])
        run(command, cwd=root, env={"PATH": path_env})
    return raw_root


def target_path(root: Path, language: str, descriptor: Mapping[str, Any]) -> Path:
    domain = domain_for(cast(str, descriptor["package"]))
    stem = Path(cast(str, descriptor["name"])).stem
    return (
        root / "protocols/generated" / language / domain / "v1" / f"{stem}{PROTO_SUFFIX[language]}"
    )


def raw_path(raw_root: Path, language: str, descriptor: Mapping[str, Any]) -> Path:
    source = Path(cast(str, descriptor["name"]))
    if language == "rust":
        return raw_root / domain_for(cast(str, descriptor["package"])) / f"{source.stem}.rs"
    return raw_root / source.parent / f"{source.stem}{PROTO_SUFFIX[language]}"


def python_module(source: str) -> str:
    path = Path(source)
    return ".".join((*path.parent.parts, f"{path.stem}_pb2"))


def target_python_module(descriptor: Mapping[str, Any]) -> str:
    return ".".join(
        (
            domain_for(cast(str, descriptor["package"])),
            "v1",
            f"{Path(cast(str, descriptor['name'])).stem}_pb2",
        )
    )


def normalize_python(content: str, descriptors: Sequence[Mapping[str, Any]]) -> str:
    replacements = sorted(
        (
            (python_module(cast(str, item["name"])), target_python_module(item))
            for item in descriptors
        ),
        key=lambda pair: len(pair[0]),
        reverse=True,
    )
    for old, new in replacements:
        content = content.replace(old, new)
    return content


def normalize_rust(
    content: str, descriptor: Mapping[str, Any], by_name: Mapping[str, Mapping[str, Any]]
) -> str:
    current_domain = domain_for(cast(str, descriptor["package"]))
    dependencies = descriptor.get("dependency", [])
    if not isinstance(dependencies, list):
        raise ValueError("descriptor dependency list is invalid")
    for dependency in cast(list[object], dependencies):
        if not isinstance(dependency, str) or dependency not in by_name:
            continue
        dependency_domain = domain_for(cast(str, by_name[dependency]["package"]))
        if dependency_domain != current_domain:
            stem = Path(dependency).stem
            content = content.replace(f"super::{stem}", f"crate::{dependency_domain}::v1::{stem}")
    return content


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


def language_metadata(
    root: Path,
    descriptors: Sequence[Mapping[str, Any]],
    lock: Mapping[str, Any],
    outputs: dict[Path, bytes],
) -> None:
    generated = root / "protocols/generated"
    domains = sorted({domain_for(cast(str, item["package"])) for item in descriptors})
    by_domain: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    by_name = {cast(str, item["name"]): item for item in descriptors}
    for descriptor in descriptors:
        by_domain[domain_for(cast(str, descriptor["package"]))].append(descriptor)

    for domain in domains:
        rust_stems = sorted(
            Path(cast(str, item["name"])).stem
            for item in by_domain[domain]
            if "rust" in declared_languages(lock, cast(str, item["package"]))
        )
        if rust_stems:
            modules = "\n".join(f"pub mod {stem};" for stem in rust_stems)
            outputs[generated / "rust" / domain / "v1" / "mod.rs"] = (
                f"// Code generated by {GENERATOR}; DO NOT EDIT.\n\n{modules}\n"
            ).encode()
        ts_stems = sorted(
            Path(cast(str, item["name"])).stem
            for item in by_domain[domain]
            if "typescript" in declared_languages(lock, cast(str, item["package"]))
        )
        if ts_stems:
            exports = "\n".join(f"export * from './{stem}_pb.js';" for stem in ts_stems)
            outputs[generated / "typescript" / domain / "v1" / "index.ts"] = (
                f"// Code generated by {GENERATOR}; DO NOT EDIT.\n\n{exports}\n"
            ).encode()
        if any(
            "python" in declared_languages(lock, cast(str, item["package"]))
            for item in by_domain[domain]
        ):
            outputs[generated / "python" / domain / "v1" / "__init__.py"] = (
                f"# Code generated by {GENERATOR}; DO NOT EDIT.\n"
            ).encode()

        go_descriptors = [
            item
            for item in by_domain[domain]
            if "go" in declared_languages(lock, cast(str, item["package"]))
        ]
        if go_descriptors:
            go_sources = sorted(
                f"{Path(cast(str, item['name'])).stem}.pb.go" for item in go_descriptors
            )
            dependency_domains = sorted(
                {
                    domain_for(cast(str, by_name[dependency]["package"]))
                    for item in go_descriptors
                    for dependency in cast(list[str], item.get("dependency", []))
                    if dependency in by_name
                    and domain_for(cast(str, by_name[dependency]["package"])) != domain
                }
            )
            deps = [
                '"@org_golang_google_protobuf//reflect/protoreflect"',
                '"@org_golang_google_protobuf//runtime/protoimpl"',
            ]
            deps.extend(
                f'"//protocols/generated/go/{value}/v1:bindings"' for value in dependency_domains
            )
            import_path = f"github.com/mindclade/mindclade/protocols/generated/go/{domain}/v1"
            outputs[generated / "go" / domain / "v1" / "BUILD.bazel"] = (
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
        b"# Generated Go bindings\n\nGenerated by the locked Buf/protoc-gen-go toolchain.\n"
    )
    outputs[generated / "go" / "BUILD.bazel"] = generated_build(
        ["BUILD.bazel", "README.generated.md"]
        + [f"//protocols/generated/go/{domain}/v1:generated_sources" for domain in domains]
    )
    outputs[generated / "python" / "README.generated.md"] = (
        b"# Generated Python bindings\n\nGenerated by the locked Buf/protoc toolchain.\n"
    )
    outputs[generated / "python" / "BUILD.bazel"] = (
        b'load("@rules_python//python:defs.bzl", "py_library")\n\n'
        b"py_library(\n"
        b'    name = "bindings",\n'
        b'    srcs = glob(["**/*.py"]),\n'
        b'    imports = ["."],\n'
        b'    deps = ["@mindclade_pypi//protobuf"],\n'
        b'    visibility = ["//visibility:public"],\n'
        b")\n\n"
        b"filegroup(\n"
        b'    name = "generated_sources",\n'
        b'    srcs = glob(["**/*"]),\n'
        b'    visibility = ["//visibility:public"],\n'
        b")\n"
    )
    outputs[generated / "rust" / "README.generated.md"] = (
        b"# Generated Rust bindings\n\nGenerated by the locked Buf/protoc-gen-rs toolchain.\n"
    )
    rust_modules = "\n".join(f"pub mod {domain} {{ pub mod v1; }}" for domain in domains)
    outputs[generated / "rust" / "lib.rs"] = (
        f"// Code generated by {GENERATOR}; DO NOT EDIT.\n\n{rust_modules}\n"
    ).encode()
    outputs[generated / "rust" / "BUILD.bazel"] = (
        b'load("@rules_rust//rust:defs.bzl", "rust_library")\n\n'
        b"rust_library(\n"
        b'    name = "bindings",\n'
        b'    crate_name = "mindclade_protocols",\n'
        b'    edition = "2024",\n'
        b'    srcs = glob(["**/*.rs"]),\n'
        b'    deps = ["@crate_index//:protobuf"],\n'
        b'    visibility = ["//visibility:public"],\n'
        b")\n\n"
        b"filegroup(\n"
        b'    name = "generated_sources",\n'
        b'    srcs = glob(["**/*"]),\n'
        b'    visibility = ["//visibility:public"],\n'
        b")\n"
    )
    outputs[generated / "typescript" / "README.generated.md"] = (
        b"# Generated TypeScript bindings\n\nGenerated by the locked Buf/protoc-gen-es toolchain.\n"
    )
    outputs[generated / "typescript" / "BUILD.bazel"] = (
        b'load("@aspect_rules_ts//ts:defs.bzl", "ts_project")\n\n'
        b"ts_project(\n"
        b'    name = "bindings",\n'
        b'    srcs = glob(["**/*.ts"]),\n'
        b"    declaration = True,\n"
        b'    tsconfig = "tsconfig.json",\n'
        b'    deps = ["@npm//:node_modules/@bufbuild/protobuf"],\n'
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
    root: Path, descriptors: Sequence[Mapping[str, Any]], descriptor_set: bytes
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
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def generated_outputs(root: Path) -> tuple[dict[Path, bytes], bytes, list[dict[str, Any]]]:
    lock = toolchain(root)
    rust_plugin_path = ensure_toolchain(root, lock)
    with tempfile.TemporaryDirectory(prefix="mindclade-codegen-") as temporary:
        staging = Path(temporary)
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
                source = raw_path(raw_roots[language], language, descriptor)
                target = target_path(root, language, descriptor)
                content = source.read_text(encoding="utf-8")
                if language == "python":
                    content = normalize_python(content, descriptors)
                elif language == "rust":
                    content = normalize_rust(content, descriptor, by_name)
                elif language == "typescript":
                    content = normalize_typescript(
                        content, source.resolve(), target, ts_raw_to_target
                    )
                outputs[target] = content.encode()
        language_metadata(root, descriptors, lock, outputs)
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
                    "toolchain_digest": sha256_file(root / "tools/codegen/toolchain.lock.json"),
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode()
        validate_manifest(root, descriptors, outputs)
        return outputs, descriptor_set, descriptors


def write_generated(root: Path, *, update_baseline: bool) -> None:
    outputs, descriptor_set, descriptors = generated_outputs(root)
    for path in sorted(governed_generated_paths(root), reverse=True):
        if path.is_file() and path not in outputs:
            path.unlink()
    for path, content in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    if update_baseline:
        baseline = root / "protocols/compatibility/baselines/protobuf.lock.json"
        baseline.write_bytes(protobuf_baseline(root, descriptors, descriptor_set))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="accept the current descriptor set as the compatibility baseline",
    )
    args = parser.parse_args()
    write_generated(args.root.resolve(), update_baseline=args.update_baseline)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
