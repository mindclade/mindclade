#!/usr/bin/env python3.12
"""Descriptor-bound proof of internal SDK RPC implementation coverage.

The Protobuf descriptor owns RPC identity and streaming shape. The reviewed
policy owns classification only. An ergonomic classification is accepted only
when every private SDK language contains both a non-generated facade transport
reference and a compiled behavioral-test reference. Evidence paths, build
targets, proof kind, and content digests are projected deterministically.
"""

from __future__ import annotations

import argparse
import ast
import base64
import hashlib
import json
import re
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import yaml
from google.protobuf import descriptor_pb2

SCHEMA_VERSION = "mindclade.internal-sdk-rpc-coverage/v2"
GENERATED_SCHEMA_VERSION = "mindclade.internal-sdk-rpc-coverage-projection/v2"
LANGUAGES = ("go", "python", "rust", "typescript")
CLASSIFICATIONS = frozenset({"ergonomic", "raw-only", "unsupported"})
POLICY_PATH = Path("sdks/rpc-coverage.yaml")
OUTPUT_PATH = Path("sdks/rpc-coverage.generated.json")
CANDIDATE_PATH = Path("protocols/compatibility/baselines/protobuf.candidate.json")
ROUTE_PATTERN = re.compile(r"/mindclade\.internal\.[A-Za-z0-9_.]+/[A-Za-z0-9_]+")


@dataclass(frozen=True)
class LanguageLayout:
    source_root: Path
    generated_root: Path
    build_file: Path
    library_target: str
    test_target: str
    source_files: Callable[[Path], list[Path]]
    test_files: Callable[[Path], list[Path]]


@dataclass(frozen=True)
class EvidenceIndex:
    sources: dict[Path, str]
    tests: dict[Path, str]
    generated: dict[Path, str]
    generated_digests: dict[Path, str]
    symbols: dict[str, set[str]]
    symbols_by_path: dict[Path, dict[str, set[str]]]


def _files(root: Path, pattern: str) -> list[Path]:
    return sorted(path for path in root.glob(pattern) if path.is_file())


def _go_sources(root: Path) -> list[Path]:
    return [path for path in _files(root, "*.go") if not path.name.endswith("_test.go")]


def _go_tests(root: Path) -> list[Path]:
    return _files(root, "*_test.go")


def _python_sources(root: Path) -> list[Path]:
    return _files(root / "mindclade_internal_sdk", "*.py")


def _python_tests(root: Path) -> list[Path]:
    return _files(root / "tests", "test_*.py")


def _rust_sources(root: Path) -> list[Path]:
    return [
        path
        for path in _files(root / "src", "*.rs")
        if not path.name.endswith("_tests.rs") and path.name != "tests.rs"
    ]


def _rust_tests(root: Path) -> list[Path]:
    return [
        path
        for path in _files(root / "src", "*.rs")
        if path.name.endswith("_tests.rs") or path.name == "tests.rs"
    ]


def _typescript_sources(root: Path) -> list[Path]:
    return _files(root / "src", "*.ts")


def _typescript_tests(root: Path) -> list[Path]:
    return _files(root / "tests", "*.test.ts")


LAYOUTS = {
    "go": LanguageLayout(
        source_root=Path("sdks/go/mindclade"),
        generated_root=Path("protocols/generated/go"),
        build_file=Path("sdks/go/mindclade/BUILD.bazel"),
        library_target="//sdks/go/mindclade:mindclade",
        test_target="//sdks/go/mindclade:mindclade_test",
        source_files=_go_sources,
        test_files=_go_tests,
    ),
    "python": LanguageLayout(
        source_root=Path("sdks/python"),
        generated_root=Path("protocols/generated/python"),
        build_file=Path("sdks/python/BUILD.bazel"),
        library_target="//sdks/python:mindclade_internal_sdk",
        test_target="//sdks/python:tests",
        source_files=_python_sources,
        test_files=_python_tests,
    ),
    "rust": LanguageLayout(
        source_root=Path("sdks/rust"),
        generated_root=Path("protocols/generated/rust"),
        build_file=Path("sdks/rust/BUILD.bazel"),
        library_target="//sdks/rust:mindclade_internal_sdk",
        test_target="//sdks/rust:mindclade_internal_sdk_test",
        source_files=_rust_sources,
        test_files=_rust_tests,
    ),
    "typescript": LanguageLayout(
        source_root=Path("sdks/typescript"),
        generated_root=Path("protocols/generated/typescript"),
        build_file=Path("sdks/typescript/BUILD.bazel"),
        library_target="//sdks/typescript:mindclade_internal_sdk",
        test_target="//sdks/typescript:tests",
        source_files=_typescript_sources,
        test_files=_typescript_tests,
    ),
}

FACADE_SOURCE_EXCLUSIONS = {
    "go": frozenset(
        {
            "auth.go",
            "client.go",
            "config.go",
            "error.go",
            "interceptors.go",
            "method_policy.go",
            "request.go",
            "transport.go",
        }
    ),
    "python": frozenset(
        {
            "__init__.py",
            "_invocation.py",
            "_validation.py",
            "auth.py",
            "calls.py",
            "client.py",
            "config.py",
            "errors.py",
            "generated.py",
            "method_policy.py",
            "testing.py",
            "transport.py",
        }
    ),
    "rust": frozenset(
        {"auth.rs", "config.rs", "error.rs", "lib.rs", "request.rs", "retry.rs", "transport.rs"}
    ),
    "typescript": frozenset(
        {
            "auth.ts",
            "client.ts",
            "config.ts",
            "core.ts",
            "error.ts",
            "gcp_auth.ts",
            "index.ts",
            "raw.ts",
            "request.ts",
            "retry.ts",
            "runtime.ts",
            "safety.ts",
            "testing.ts",
            "transport.ts",
        }
    ),
}


def sha256(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


def load_object(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected an object: {path}")
    return cast(dict[str, Any], value)


def load_descriptor(root: Path) -> tuple[descriptor_pb2.FileDescriptorSet, str]:
    candidate = load_object(root / CANDIDATE_PATH)
    raw_descriptor = candidate.get("descriptor_set")
    if not isinstance(raw_descriptor, dict):
        raise ValueError("candidate baseline has no descriptor_set.base64")
    descriptor = cast(dict[str, object], raw_descriptor)
    encoded = descriptor.get("base64")
    if not isinstance(encoded, str):
        raise ValueError("candidate baseline has no descriptor_set.base64")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except ValueError as error:
        raise ValueError("candidate descriptor is not canonical base64") from error
    descriptor_set = descriptor_pb2.FileDescriptorSet()
    descriptor_set.ParseFromString(raw)
    if not descriptor_set.file:
        raise ValueError("candidate descriptor set is empty")
    return descriptor_set, sha256(raw)


def descriptor_services(
    descriptor_set: descriptor_pb2.FileDescriptorSet,
) -> dict[str, dict[str, dict[str, Any]]]:
    services: dict[str, dict[str, dict[str, Any]]] = {}
    for source in descriptor_set.file:
        if not source.package.startswith("mindclade.internal."):
            continue
        for service in source.service:
            full_service = f"{source.package}.{service.name}"
            methods: dict[str, dict[str, Any]] = {}
            for method in service.method:
                methods[method.name] = {
                    "client_streaming": method.client_streaming,
                    "input_type": method.input_type.removeprefix("."),
                    "output_type": method.output_type.removeprefix("."),
                    "route": f"/{full_service}/{method.name}",
                    "server_streaming": method.server_streaming,
                    "source": source.name,
                }
            if full_service in services:
                raise ValueError(f"duplicate descriptor service: {full_service}")
            services[full_service] = methods
    if not services:
        raise ValueError("candidate descriptor has no mindclade.internal services")
    return services


def require_exact_keys(value: Mapping[str, object], expected: set[str], context: str) -> None:
    actual = set(value)
    if actual != expected:
        raise ValueError(
            f"{context} keys differ: missing={sorted(expected - actual)}, "
            f"unexpected={sorted(actual - expected)}"
        )


def _camel_lower(value: str) -> str:
    return value[:1].lower() + value[1:]


def _snake(value: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", value).lower()


def _route_symbols(path: Path) -> dict[str, set[str]]:
    """Return exact route -> local constant names, including multiline Python."""
    result: dict[str, set[str]] = {}
    if path.suffix == ".py":
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as error:
            raise ValueError(f"cannot parse SDK evidence source {path}: {error}") from error
        for node in tree.body:
            target: ast.expr | None = None
            value: ast.expr | None = None
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                target, value = node.targets[0], node.value
            elif isinstance(node, ast.AnnAssign):
                target, value = node.target, node.value
            if (
                isinstance(target, ast.Name)
                and isinstance(value, ast.Constant)
                and isinstance(value.value, str)
                and ROUTE_PATTERN.fullmatch(value.value)
            ):
                result.setdefault(value.value, set()).add(target.id)
        return result

    content = path.read_text(encoding="utf-8")
    for match in re.finditer(
        r"(?m)^\s*(?:const\s+)?([A-Z][A-Z0-9_]*)[^\n=]*=\s*[\"']"
        r"(/mindclade\.internal\.[A-Za-z0-9_.]+/[A-Za-z0-9_]+)[\"']",
        content,
    ):
        result.setdefault(match.group(2), set()).add(match.group(1))
    return result


def source_evidence_proof(
    language: str,
    content: str,
    method: str,
    route: str,
    symbols: set[str],
) -> str | None:
    for symbol in sorted(symbols):
        if len(re.findall(rf"\b{re.escape(symbol)}\b", content)) >= 2:
            return f"route-constant:{symbol}"
    if language == "go" and re.search(rf"\.{re.escape(method)}\s*\(", content):
        return f"typed-generated-call:{method}"
    if language == "typescript" and re.search(
        rf"\.{re.escape(_camel_lower(method))}\s*\(", content
    ):
        return f"typed-generated-call:{_camel_lower(method)}"
    return None


def behavioral_test_proof(
    language: str,
    content: str,
    method: str,
    route: str,
    symbols: set[str],
) -> str | None:
    test_marker = {
        "go": r"(?m)^func Test",
        "python": r"(?m)^\s*(?:async\s+)?def test_|unittest\.TestCase",
        "rust": r"#\[(?:tokio::)?test\]",
        "typescript": r"\b(?:test|it)\s*\(",
    }[language]
    if re.search(test_marker, content) is None:
        return None
    if route in content:
        return "exact-route-capture"
    for symbol in sorted(symbols):
        if re.search(rf"\b{re.escape(symbol)}\b", content):
            return f"route-symbol-capture:{symbol}"
    typed = (
        method
        if language == "go"
        else _snake(method)
        if language == "rust"
        else _camel_lower(method)
    )
    if re.search(rf"\b{re.escape(typed)}\b", content):
        return f"generated-rpc-capture:{typed}"
    return None


def _relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _evidence_record(
    root: Path,
    path: Path,
    proof: str,
    *,
    content_digest: str | None = None,
) -> dict[str, str]:
    return {
        "digest": content_digest or sha256(path.read_bytes()),
        "path": _relative(root, path),
        "proof": proof,
    }


def _evidence_index(
    root: Path,
    language: str,
    generated_outputs: Mapping[Path, bytes] | None = None,
) -> EvidenceIndex:
    layout = LAYOUTS[language]
    language_root = root / layout.source_root
    source_paths = [
        path
        for path in layout.source_files(language_root)
        if path.name not in FACADE_SOURCE_EXCLUSIONS[language]
    ]
    test_paths = layout.test_files(language_root)
    all_language_sources = layout.source_files(language_root)
    sources = {path: path.read_text(encoding="utf-8") for path in source_paths}
    tests = {path: path.read_text(encoding="utf-8") for path in test_paths}
    symbols: dict[str, set[str]] = {}
    symbols_by_path: dict[Path, dict[str, set[str]]] = {}
    for path in [*all_language_sources, *test_paths]:
        route_symbols = _route_symbols(path)
        symbols_by_path[path] = route_symbols
        for route, names in route_symbols.items():
            symbols.setdefault(route, set()).update(names)
    generated: dict[Path, str] = {}
    generated_digests: dict[Path, str] = {}
    generated_root = root / layout.generated_root
    if generated_outputs is None:
        for path in sorted(generated_root.rglob("*")):
            if path.is_file() and path.suffix in {".go", ".py", ".pyi", ".rs", ".ts"}:
                content = path.read_bytes()
                generated[path] = content.decode("utf-8", errors="replace")
                generated_digests[path] = sha256(content)
    else:
        for path, content in sorted(generated_outputs.items()):
            try:
                path.relative_to(generated_root)
            except ValueError:
                continue
            if path.suffix in {".go", ".py", ".pyi", ".rs", ".ts"}:
                generated[path] = content.decode("utf-8", errors="replace")
                generated_digests[path] = sha256(content)
    return EvidenceIndex(
        sources=sources,
        tests=tests,
        generated=generated,
        generated_digests=generated_digests,
        symbols=symbols,
        symbols_by_path=symbols_by_path,
    )


def _assert_build_ownership(
    root: Path,
    language: str,
    implementation: list[Path],
    tests: list[Path],
) -> None:
    layout = LAYOUTS[language]
    build = (root / layout.build_file).read_text(encoding="utf-8")
    if f'name = "{layout.library_target.rsplit(":", 1)[1]}"' not in build:
        raise ValueError(f"missing SDK library target {layout.library_target}")
    if f'name = "{layout.test_target.rsplit(":", 1)[1]}"' not in build:
        raise ValueError(f"missing SDK test target {layout.test_target}")
    for path in implementation:
        relative = path.relative_to(root / layout.source_root).as_posix()
        if language == "go" and f'"{relative}"' not in build:
            raise ValueError(
                f"Go facade evidence is not compiled by {layout.library_target}: {path}"
            )
        if language == "python" and "mindclade_internal_sdk/*.py" not in build:
            raise ValueError(f"Python facade source glob is absent from {layout.library_target}")
        if language == "rust" and 'glob(["src/**/*.rs"])' not in build:
            raise ValueError(f"Rust facade source glob is absent from {layout.library_target}")
        if language == "typescript" and 'glob(["src/*.ts"])' not in build:
            raise ValueError(
                f"TypeScript facade source glob is absent from {layout.library_target}"
            )
    for path in tests:
        relative = path.relative_to(root / layout.source_root).as_posix()
        if language == "go" and f'"{relative}"' not in build:
            raise ValueError(f"Go SDK test evidence is not compiled: {path}")
        if language == "python" and f'"{relative}"' not in build:
            raise ValueError(f"Python SDK test evidence has no py_test: {path}")
        if language == "rust" and 'glob(["src/**/*.rs"])' not in build:
            raise ValueError(f"Rust SDK test source glob is absent: {path}")
        if language == "typescript" and f'"{relative}"' not in build:
            raise ValueError(f"TypeScript SDK test evidence has no js_test: {path}")


def _generated_transport_evidence(
    root: Path,
    language: str,
    service: str,
    method: str,
    route: str,
    index: EvidenceIndex,
) -> list[dict[str, str]]:
    spellings = {method, _camel_lower(method), _snake(method), route}
    candidates: list[tuple[Path, str]] = []
    for path, content in index.generated.items():
        if not _is_generated_transport(language, path):
            continue
        if service not in content:
            continue
        proof = next((token for token in sorted(spellings) if token in content), None)
        if proof is not None:
            candidates.append((path, f"generated-transport:{proof}"))
    if not candidates:
        raise ValueError(f"{language} raw generated transport omits {service}.{method}")
    path, proof = candidates[0]
    return [
        _evidence_record(
            root,
            path,
            proof,
            content_digest=index.generated_digests[path],
        )
    ]


def _is_generated_transport(language: str, path: Path) -> bool:
    if language == "go":
        return path.name.endswith("_grpc.pb.go")
    if language == "python":
        return path.name.endswith("_pb2_grpc.py")
    if language == "rust":
        return path.name.endswith("_grpc.rs")
    if language == "typescript":
        return path.name.endswith("_pb.ts")
    raise ValueError(f"unsupported SDK evidence language: {language}")


def _language_evidence(
    root: Path,
    language: str,
    service: str,
    method: str,
    route: str,
    classification: str,
    index: EvidenceIndex,
) -> dict[str, object]:
    layout = LAYOUTS[language]
    symbol_routes: dict[str, set[str]] = {}
    for candidate_route, names in index.symbols.items():
        for name in names:
            symbol_routes.setdefault(name, set()).add(candidate_route)
    unique_symbols = {
        name for name in index.symbols.get(route, set()) if symbol_routes.get(name) == {route}
    }

    implementation = [
        (path, proof)
        for path, content in index.sources.items()
        if (
            proof := source_evidence_proof(
                language,
                content,
                method,
                route,
                index.symbols_by_path.get(path, {}).get(route, set()) | unique_symbols,
            )
        )
        is not None
    ]
    behavioral = [
        (path, proof)
        for path, content in index.tests.items()
        if (proof := behavioral_test_proof(language, content, method, route, unique_symbols))
        is not None
    ]

    if classification == "ergonomic":
        if not implementation:
            raise ValueError(
                f"{language} ergonomic facade has no transport proof for {service}.{method}"
            )
        if not behavioral:
            raise ValueError(
                f"{language} ergonomic facade has no behavioral test proof for {service}.{method}"
            )
        _assert_build_ownership(
            root, language, [path for path, _ in implementation], [path for path, _ in behavioral]
        )
    elif implementation:
        paths = [_relative(root, path) for path, _ in implementation]
        raise ValueError(
            f"{language} {classification} RPC leaks into ergonomic facade: "
            f"{service}.{method}: {paths}"
        )
    else:
        behavioral = []

    return {
        "behavioral_tests": [_evidence_record(root, path, proof) for path, proof in behavioral],
        "implementation": [_evidence_record(root, path, proof) for path, proof in implementation],
        "library_target": layout.library_target,
        "raw_transport": _generated_transport_evidence(
            root, language, service, method, route, index
        ),
        "test_target": layout.test_target,
    }


def render(
    root: Path,
    *,
    descriptor_bytes: bytes | None = None,
    generated_outputs: Mapping[Path, bytes] | None = None,
) -> bytes:
    if descriptor_bytes is None:
        descriptor_set, descriptor_digest = load_descriptor(root)
    else:
        descriptor_set = descriptor_pb2.FileDescriptorSet()
        descriptor_set.ParseFromString(descriptor_bytes)
        if not descriptor_set.file:
            raise ValueError("staged descriptor set is empty")
        descriptor_digest = sha256(descriptor_bytes)
    declared_services = descriptor_services(descriptor_set)
    policy_path = root / POLICY_PATH
    policy_bytes = policy_path.read_bytes()
    policy = load_object(policy_path)
    require_exact_keys(
        policy,
        {"default_classification", "languages", "schema_version", "scope", "services"},
        "SDK coverage policy",
    )
    if policy["schema_version"] != SCHEMA_VERSION:
        raise ValueError("unsupported SDK coverage policy schema_version")
    if policy["scope"] != "mindclade.internal":
        raise ValueError("SDK coverage policy must be confined to mindclade.internal")
    if tuple(policy["languages"]) != LANGUAGES:
        raise ValueError(f"SDK coverage languages must be {LANGUAGES}")
    if policy["default_classification"] != "ergonomic":
        raise ValueError("the internal SDK default classification must be ergonomic")
    raw_services = policy["services"]
    if not isinstance(raw_services, dict):
        raise ValueError("SDK coverage services must be an object")
    services = cast(dict[str, object], raw_services)
    if set(services) != set(declared_services):
        raise ValueError(
            "SDK coverage service closure differs from the descriptor: "
            f"missing={sorted(set(declared_services) - set(services))}, "
            f"orphaned={sorted(set(services) - set(declared_services))}"
        )

    evidence_indexes = {
        language: _evidence_index(root, language, generated_outputs) for language in LANGUAGES
    }
    declared_routes = {
        cast(str, descriptor["route"])
        for methods in declared_services.values()
        for descriptor in methods.values()
    }
    for language, index in evidence_indexes.items():
        orphan_routes = {
            route
            for content in index.sources.values()
            for route in ROUTE_PATTERN.findall(content)
            if route not in declared_routes
        }
        if orphan_routes:
            raise ValueError(
                f"{language} ergonomic facade references descriptor-orphan routes: "
                f"{sorted(orphan_routes)}"
            )

    entries: list[dict[str, Any]] = []
    for service_name in sorted(declared_services):
        raw_service = services[service_name]
        if not isinstance(raw_service, dict):
            raise ValueError(f"SDK coverage service is not an object: {service_name}")
        service_policy = cast(dict[str, object], raw_service)
        require_exact_keys(service_policy, {"facade", "owner", "overrides"}, service_name)
        owner, facade, overrides = (
            service_policy["owner"],
            service_policy["facade"],
            service_policy["overrides"],
        )
        if not isinstance(owner, str) or not owner:
            raise ValueError(f"SDK coverage service has no owner: {service_name}")
        if not isinstance(facade, str) or not facade:
            raise ValueError(f"SDK coverage service has no facade: {service_name}")
        if not isinstance(overrides, dict):
            raise ValueError(f"SDK coverage overrides are not an object: {service_name}")
        method_overrides = cast(dict[str, object], overrides)
        unknown_methods = set(method_overrides) - set(declared_services[service_name])
        if unknown_methods:
            raise ValueError(
                f"SDK coverage overrides unknown methods for {service_name}: "
                f"{sorted(unknown_methods)}"
            )

        for method_name, descriptor in sorted(declared_services[service_name].items()):
            classification = cast(str, policy["default_classification"])
            reason = ""
            temporary = False
            raw_override = method_overrides.get(method_name)
            if raw_override is not None:
                if not isinstance(raw_override, dict):
                    raise ValueError(
                        f"SDK coverage override is not an object: {service_name}.{method_name}"
                    )
                override = cast(dict[str, object], raw_override)
                require_exact_keys(
                    override,
                    {"classification", "reason", "temporary"},
                    f"{service_name}.{method_name}",
                )
                classification_value = override["classification"]
                reason_value = override["reason"]
                temporary_value = override["temporary"]
                if classification_value not in CLASSIFICATIONS:
                    raise ValueError(
                        f"invalid SDK classification for {service_name}.{method_name}: "
                        f"{classification_value!r}"
                    )
                if not isinstance(reason_value, str) or not reason_value.strip():
                    raise ValueError(
                        f"non-ergonomic RPC needs a reviewed reason: {service_name}.{method_name}"
                    )
                if not isinstance(temporary_value, bool):
                    raise ValueError(
                        f"SDK temporary flag must be boolean: {service_name}.{method_name}"
                    )
                classification = cast(str, classification_value)
                reason = reason_value
                temporary = temporary_value
            if classification == "ergonomic" and (reason or temporary):
                raise ValueError(
                    f"ergonomic RPC cannot carry a gap reason: {service_name}.{method_name}"
                )
            route = cast(str, descriptor["route"])
            evidence = {
                language: _language_evidence(
                    root,
                    language,
                    service_name,
                    method_name,
                    route,
                    classification,
                    evidence_indexes[language],
                )
                for language in LANGUAGES
            }
            entries.append(
                {
                    **descriptor,
                    "classification": classification,
                    "evidence": evidence,
                    "facade": facade,
                    "full_name": f"{service_name}.{method_name}",
                    "method": method_name,
                    "owner": owner,
                    "reason": reason,
                    "service": service_name,
                    "temporary": temporary,
                }
            )

    counts = Counter(cast(str, entry["classification"]) for entry in entries)
    temporary_gaps = [cast(str, entry["full_name"]) for entry in entries if entry["temporary"]]
    evidence_files = {
        record["path"]: record["digest"]
        for entry in entries
        for language in LANGUAGES
        for category in ("implementation", "behavioral_tests", "raw_transport")
        for record in cast(dict[str, list[dict[str, str]]], entry["evidence"][language])[category]
    }
    projection = {
        "descriptor_digest": descriptor_digest,
        "evidence_files": [
            {"digest": digest, "path": path} for path, digest in sorted(evidence_files.items())
        ],
        "generator": {
            "name": "tools/codegen/generate_sdk_coverage.py",
            "version": GENERATED_SCHEMA_VERSION,
        },
        "languages": list(LANGUAGES),
        "policy_digest": sha256(policy_bytes),
        "ratification_ready": not temporary_gaps,
        "rpcs": entries,
        "schema_version": GENERATED_SCHEMA_VERSION,
        "summary": {
            "classifications": {
                classification: counts.get(classification, 0)
                for classification in sorted(CLASSIFICATIONS)
            },
            "evidence_file_count": len(evidence_files),
            "rpc_count": len(entries),
            "service_count": len(declared_services),
            "temporary_gap_count": len(temporary_gaps),
            "temporary_gaps": temporary_gaps,
        },
    }
    return (json.dumps(projection, sort_keys=True, separators=(",", ":")) + "\n").encode()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    output = root / OUTPUT_PATH
    expected = render(root)
    if args.check:
        if not output.is_file() or output.read_bytes() != expected:
            print(OUTPUT_PATH.as_posix())
            return 1
        return 0
    parser.error(
        "SDK coverage writes are owned by generate_protocols.py's atomic transaction; "
        "use --check here or run `just generate-contracts`"
    )


if __name__ == "__main__":
    raise SystemExit(main())
