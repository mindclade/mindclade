#!/usr/bin/env python3.12
"""Prove every descriptor-declared gRPC RPC has an explicit Go implementation.

Generated `Unimplemented*Server` embeddings are forward-compatibility guards, not
implementations. This projection fails unless each RPC is declared directly on
the reviewed application receiver named by the control-plane policy.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import cast

import yaml
from google.protobuf import descriptor_pb2

POLICY_PATH = Path("services/control_plane/grpc-implementation.yaml")
OUTPUT_PATH = Path("services/control_plane/grpc-implementation.generated.json")
CANDIDATE_PATH = Path("protocols/compatibility/baselines/protobuf.candidate.json")
POLICY_SCHEMA = "mindclade.grpc-implementation-policy/v1"
OUTPUT_SCHEMA = "mindclade.grpc-implementation-coverage/v1"
IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
OWNER = re.compile(r"^[a-z0-9](?:[a-z0-9._/-]*[a-z0-9])?$")

RUNTIME_SOURCE_SUFFIXES = frozenset({".go", ".py", ".rs", ".ts", ".tsx"})
IGNORED_SOURCE_PARTS = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "build",
        "node_modules",
        "target",
        "third_party",
        "venv",
    }
)
IGNORED_SOURCE_PREFIXES = (
    ("protocols", "generated"),
    ("docs", "architecture", "blueprint", "provenance"),
)

# Generated registration helpers are allowed below; these expressions only
# reject transport *contract construction*. Application adapters and service
# implementations must consume the generated descriptors/interfaces instead.
FORBIDDEN_TRANSPORT_CONTRACTS: dict[str, tuple[tuple[str, re.Pattern[str]], ...]] = {
    ".go": (
        (
            "raw grpc service descriptor",
            re.compile(
                r"(?:&\s*)?\b[A-Za-z_][A-Za-z0-9_]*\.(?:ServiceDesc|MethodDesc|StreamDesc)\s*\{"
            ),
        ),
        ("raw grpc service registration", re.compile(r"\.RegisterService\s*\(")),
        (
            "handwritten generated-style grpc registrar",
            re.compile(r"(?m)^\s*func\s+Register[A-Za-z0-9_]+ServiceServer\s*\("),
        ),
        (
            "handwritten grpc registration adapter",
            re.compile(r"(?m)^\s*func\s+RegisterService\s*\("),
        ),
    ),
    ".py": (
        (
            "generic grpc handler construction",
            re.compile(
                r"\b(?:method_handlers_generic_handler|(?:unary_unary|unary_stream|stream_unary|stream_stream)_rpc_method_handler)\s*\("
            ),
        ),
        ("generic grpc handler registration", re.compile(r"\.add_generic_rpc_handlers\s*\(")),
        (
            "handwritten generated-style grpc registrar",
            re.compile(r"(?m)^\s*def\s+add_[A-Za-z0-9_]+Servicer_to_server\s*\("),
        ),
    ),
    ".rs": (
        (
            "raw tonic named-service contract",
            re.compile(
                r"\btonic(?:::codegen)?::server::NamedService\b|\btonic::server::NamedService\b"
            ),
        ),
        ("raw tonic grpc method descriptor", re.compile(r"\bGrpcMethod::new\s*\(")),
        (
            "handwritten tonic service trait",
            re.compile(r"(?s)#\s*\[\s*tonic::async_trait\s*\]\s*(?:pub\s+)?trait\s+"),
        ),
    ),
    ".ts": (
        ("handwritten Connect method kind", re.compile(r"\bMethodKind\b")),
        ("handwritten Connect service type", re.compile(r"\bServiceType\b")),
        (
            "handwritten Connect service descriptor",
            re.compile(
                r"(?s)\b(?:const|let|var)\s+[A-Za-z0-9_]+Service\s*(?::[^=]{0,300})?=\s*\{.{0,1200}?\b(?:methods|typeName)\s*:"
            ),
        ),
    ),
    ".tsx": (
        ("handwritten Connect method kind", re.compile(r"\bMethodKind\b")),
        ("handwritten Connect service type", re.compile(r"\bServiceType\b")),
        (
            "handwritten Connect service descriptor",
            re.compile(
                r"(?s)\b(?:const|let|var)\s+[A-Za-z0-9_]+Service\s*(?::[^=]{0,300})?=\s*\{.{0,1200}?\b(?:methods|typeName)\s*:"
            ),
        ),
    ),
}

GO_GENERATED_IMPORT = re.compile(
    r"(?m)^[ \t]*(?:import[ \t]+)?(?P<alias>[A-Za-z_][A-Za-z0-9_]*)[ \t]+"
    r'"github\.com/mindclade/mindclade/protocols/generated/go/[^"]+"'
)
GO_GENERATED_REGISTRATION = re.compile(
    r"\b(?P<alias>[A-Za-z_][A-Za-z0-9_]*)\.Register[A-Za-z0-9_]+ServiceServer\s*\("
)
PYTHON_GENERATED_GRPC_IMPORT = re.compile(
    r"(?m)^\s*from\s+mindclade(?:\.[A-Za-z0-9_]+)+\s+import\s+"
    r"[A-Za-z0-9_]+_pb2_grpc\s+as\s+(?P<alias>[A-Za-z_][A-Za-z0-9_]*)\s*$"
)
PYTHON_GENERATED_GRPC_DYNAMIC_IMPORT = re.compile(
    r"(?m)^\s*(?P<alias>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*importlib\.import_module\("
    r'["\']mindclade(?:\.[A-Za-z0-9_]+)+_pb2_grpc["\']\)\s*$'
)
PYTHON_GENERATED_REGISTRATION = re.compile(
    r"\b(?P<alias>[A-Za-z_][A-Za-z0-9_]*)\.add_[A-Za-z0-9_]+Servicer_to_server\s*\("
)
GO_GENERIC_INVOKE = re.compile(r"\.[ \t]*Invoke\s*\(")
GENERIC_DESCRIPTOR_ADAPTERS: dict[Path, tuple[str, ...]] = {
    Path("services/control_plane/cmd/control-plane/wire.go"): (
        "apiv1.File_proto_mindclade_api_v1_mindclade_service_proto",
        'Services().ByName("MindcladeService")',
        "dynamicpb.NewMessage(selected.method.Input())",
        "dynamicpb.NewMessage(selected.method.Output())",
        "selected.method.Parent().FullName()",
        "selected.method.Name()",
    ),
}
GO_INTERFACE = re.compile(
    r"(?ms)^\s*type\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s+interface\s*\{(?P<body>.*?)^\s*\}"
)
GO_INTERFACE_METHOD = re.compile(r"(?m)^\s*(?P<name>[A-Z][A-Za-z0-9_]*)\s*(?:\[[^\n]*\]\s*)?\(")


def digest(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


def runtime_source_paths(root: Path) -> list[Path]:
    """Return owned runtime sources that could define a parallel RPC contract."""
    result: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix not in RUNTIME_SOURCE_SUFFIXES:
            continue
        relative = path.relative_to(root)
        if any(
            part in IGNORED_SOURCE_PARTS or part.startswith("bazel-") for part in relative.parts
        ):
            continue
        if any(relative.parts[: len(prefix)] == prefix for prefix in IGNORED_SOURCE_PREFIXES):
            continue
        # This checker necessarily contains the expressions it enforces.
        if relative == Path("tools/codegen/generate_grpc_implementation_coverage.py"):
            continue
        result.append(path)
    return sorted(result)


def handwritten_contract_findings(
    root: Path,
    descriptor_methods: Mapping[str, Mapping[str, Mapping[str, object]]] | None = None,
) -> list[str]:
    """Reject handwritten gRPC/Connect descriptors and non-generated registrars."""
    findings: list[str] = []
    for path in runtime_source_paths(root):
        relative = path.relative_to(root).as_posix()
        source = path.read_text(encoding="utf-8")
        for label, pattern in FORBIDDEN_TRANSPORT_CONTRACTS.get(path.suffix, ()):
            match = pattern.search(source)
            if match is not None:
                line = source.count("\n", 0, match.start()) + 1
                findings.append(f"{relative}:{line}: {label}")

        # Go implementations and tests may register a generated server, but a
        # same-looking helper from an application package is not authority.
        if path.suffix == ".go":
            generated_aliases = {
                match.group("alias") for match in GO_GENERATED_IMPORT.finditer(source)
            }
            for match in GO_GENERATED_REGISTRATION.finditer(source):
                if match.group("alias") not in generated_aliases:
                    line = source.count("\n", 0, match.start()) + 1
                    findings.append(
                        f"{relative}:{line}: grpc registration does not resolve "
                        "to a generated Go package"
                    )
            invokes = list(GO_GENERIC_INVOKE.finditer(source))
            if invokes:
                required_markers = GENERIC_DESCRIPTOR_ADAPTERS.get(Path(relative))
                if required_markers is None or len(invokes) != 1:
                    for invoke in invokes:
                        line = source.count("\n", 0, invoke.start()) + 1
                        findings.append(
                            f"{relative}:{line}: generic grpc invocation is outside "
                            "the sole descriptor-backed HTTP adapter"
                        )
                else:
                    missing_markers = [
                        marker for marker in required_markers if marker not in source
                    ]
                    if missing_markers:
                        line = source.count("\n", 0, invokes[0].start()) + 1
                        findings.append(
                            f"{relative}:{line}: generic grpc adapter is not derived "
                            "entirely from the generated public descriptor; "
                            f"missing={missing_markers}"
                        )
            for interface in GO_INTERFACE.finditer(source):
                body = interface.group("body")
                declarations = list(GO_INTERFACE_METHOD.finditer(body))
                signatures = {
                    method.group("name"): body[
                        method.start() : (
                            declarations[index + 1].start()
                            if index + 1 < len(declarations)
                            else len(body)
                        )
                    ]
                    for index, method in enumerate(declarations)
                }
                for service_name, service_methods in (descriptor_methods or {}).items():
                    # One-method behavioral seams are common and are not a useful
                    # signal. Multi-RPC interfaces that reproduce every method in
                    # a descriptor service are parallel transport contracts and
                    # must be replaced by the generated server/client interface.
                    matches = len(service_methods) >= 2
                    for method_name, method in service_methods.items():
                        signature = signatures.get(method_name, "")
                        input_name = str(method["input_type"]).rsplit(".", 1)[-1]
                        output_name = str(method["output_type"]).rsplit(".", 1)[-1]
                        if not signature or not all(
                            re.search(rf"\b{re.escape(message)}\b", signature)
                            for message in (input_name, output_name)
                        ):
                            matches = False
                            break
                    if matches:
                        line = source.count("\n", 0, interface.start()) + 1
                        findings.append(
                            f"{relative}:{line}: handwritten interface "
                            f"{interface.group('name')} reproduces generated service {service_name}"
                        )

        # The native Python package is namespaced as mindclade.*_pb2_grpc;
        # generic handlers or locally defined lookalike modules are forbidden.
        if path.suffix == ".py":
            generated_aliases = {
                match.group("alias") for match in PYTHON_GENERATED_GRPC_IMPORT.finditer(source)
            }
            generated_aliases.update(
                match.group("alias")
                for match in PYTHON_GENERATED_GRPC_DYNAMIC_IMPORT.finditer(source)
            )
            for match in PYTHON_GENERATED_REGISTRATION.finditer(source):
                if match.group("alias") not in generated_aliases:
                    line = source.count("\n", 0, match.start()) + 1
                    findings.append(
                        f"{relative}:{line}: grpc registration does not resolve "
                        "to a generated Python package"
                    )
    return sorted(set(findings))


def load_object(path: Path) -> dict[str, object]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected an object: {path}")
    return cast(dict[str, object], value)


def exact_keys(value: Mapping[str, object], expected: set[str], context: str) -> None:
    actual = set(value)
    if actual != expected:
        raise ValueError(
            f"{context} keys differ: missing={sorted(expected - actual)}, "
            f"unexpected={sorted(actual - expected)}"
        )


def descriptor_services(
    root: Path,
    *,
    descriptor_bytes: bytes | None = None,
) -> tuple[dict[str, dict[str, object]], str]:
    if descriptor_bytes is None:
        candidate = load_object(root / CANDIDATE_PATH)
        descriptor = candidate.get("descriptor_set")
        if not isinstance(descriptor, Mapping):
            raise ValueError("candidate baseline has no descriptor_set object")
        descriptor = cast(Mapping[str, object], descriptor)
        if not isinstance(descriptor.get("base64"), str):
            raise ValueError("candidate baseline has no descriptor_set.base64")
        encoded = cast(str, descriptor["base64"])
        raw = base64.b64decode(encoded, validate=True)
    else:
        raw = descriptor_bytes
    descriptor_set = descriptor_pb2.FileDescriptorSet()
    descriptor_set.ParseFromString(raw)
    services: dict[str, dict[str, object]] = {}
    for source in descriptor_set.file:
        if not source.package.startswith("mindclade."):
            continue
        for service in source.service:
            full_name = f"{source.package}.{service.name}"
            if full_name in services:
                raise ValueError(f"duplicate descriptor service: {full_name}")
            descriptor_source = Path("protocols") / source.name
            if (
                descriptor_source.is_absolute()
                or ".." in descriptor_source.parts
                or descriptor_source.suffix != ".proto"
                or descriptor_source.parts[:3] != ("protocols", "proto", "mindclade")
            ):
                raise ValueError(
                    f"gRPC service {full_name} is not declared in a versioned "
                    f"Mindclade proto source: {source.name}"
                )
            descriptor_path = root / descriptor_source
            if not descriptor_path.is_file():
                raise ValueError(
                    f"gRPC descriptor source is absent from the repository: "
                    f"{descriptor_source.as_posix()}"
                )
            services[full_name] = {
                "methods": {
                    method.name: {
                        "client_streaming": method.client_streaming,
                        "input_type": method.input_type.removeprefix("."),
                        "output_type": method.output_type.removeprefix("."),
                        "server_streaming": method.server_streaming,
                    }
                    for method in service.method
                },
                "source": descriptor_source.as_posix(),
                "source_digest": digest(descriptor_path.read_bytes()),
            }
    if not services:
        raise ValueError("candidate descriptor contains no Mindclade gRPC services")
    return services, digest(raw)


def explicit_receiver_methods(source: str, receiver: str) -> set[str]:
    pattern = re.compile(
        rf"^func\s+\(\s*[A-Za-z_][A-Za-z0-9_]*\s+\*?{re.escape(receiver)}\s*\)\s+"
        r"([A-Za-z_][A-Za-z0-9_]*)\s*\(",
        re.MULTILINE,
    )
    return set(pattern.findall(source))


def render(root: Path, *, descriptor_bytes: bytes | None = None) -> bytes:
    declared, descriptor_digest = descriptor_services(root, descriptor_bytes=descriptor_bytes)
    handwritten = handwritten_contract_findings(
        root,
        {
            service_name: cast(dict[str, dict[str, object]], service["methods"])
            for service_name, service in declared.items()
        },
    )
    if handwritten:
        raise ValueError(
            "handwritten gRPC/Connect transport contracts are forbidden; "
            "implement and register generated interfaces only:\n" + "\n".join(handwritten)
        )
    policy_path = root / POLICY_PATH
    policy_bytes = policy_path.read_bytes()
    policy = load_object(policy_path)
    exact_keys(policy, {"schema_version", "scope", "services"}, "gRPC policy")
    if policy["schema_version"] != POLICY_SCHEMA or policy["scope"] != "mindclade":
        raise ValueError("unsupported or incorrectly scoped gRPC implementation policy")
    raw_services = policy["services"]
    if not isinstance(raw_services, dict):
        raise ValueError("gRPC policy services must be an object")
    services = cast(dict[str, object], raw_services)
    if set(services) != set(declared):
        raise ValueError(
            "gRPC implementation policy differs from descriptor closure: "
            f"missing={sorted(set(declared) - set(services))}, "
            f"orphaned={sorted(set(services) - set(declared))}"
        )

    projection: list[dict[str, object]] = []
    all_sources: dict[str, str] = {}
    rpc_count = 0
    for service_name in sorted(declared):
        raw_entry = services[service_name]
        if not isinstance(raw_entry, dict):
            raise ValueError(f"gRPC service policy is not an object: {service_name}")
        entry = cast(dict[str, object], raw_entry)
        exact_keys(entry, {"owner", "receiver", "sources"}, service_name)
        owner, receiver, raw_sources = entry["owner"], entry["receiver"], entry["sources"]
        if not isinstance(owner, str) or OWNER.fullmatch(owner) is None:
            raise ValueError(f"invalid gRPC service owner: {service_name}")
        if not isinstance(receiver, str) or IDENTIFIER.fullmatch(receiver) is None:
            raise ValueError(f"invalid gRPC receiver: {service_name}")
        if not isinstance(raw_sources, list) or not raw_sources:
            raise ValueError(f"gRPC service has no implementation sources: {service_name}")
        sources: list[str] = []
        explicit: set[str] = set()
        for raw_source in cast(list[object], raw_sources):
            if not isinstance(raw_source, str):
                raise ValueError(f"gRPC source path is not a string: {service_name}")
            relative = Path(raw_source)
            if (
                relative.is_absolute()
                or ".." in relative.parts
                or relative.suffix != ".go"
                or relative.parts[:2] != ("services", "control_plane")
            ):
                raise ValueError(f"gRPC source path escapes the control plane: {raw_source}")
            path = root / relative
            if not path.is_file():
                raise ValueError(f"gRPC implementation source does not exist: {raw_source}")
            content = path.read_bytes()
            text = content.decode("utf-8")
            sources.append(relative.as_posix())
            explicit.update(explicit_receiver_methods(text, receiver))
            all_sources[relative.as_posix()] = digest(content)
        methods = cast(dict[str, dict[str, object]], declared[service_name]["methods"])
        missing = sorted(set(methods) - explicit)
        if missing:
            raise ValueError(
                f"{service_name} inherits generated Unimplemented fallbacks for: {missing}"
            )
        rpc_count += len(methods)
        projection.append(
            {
                "descriptor_source": declared[service_name]["source"],
                "descriptor_source_digest": declared[service_name]["source_digest"],
                "methods": [
                    {"name": method_name, **methods[method_name]} for method_name in sorted(methods)
                ],
                "owner": owner,
                "receiver": receiver,
                "service": service_name,
                "sources": sources,
            }
        )

    result = {
        "descriptor_digest": descriptor_digest,
        "explicit_rpc_count": rpc_count,
        "generator": {
            "name": "tools/codegen/generate_grpc_implementation_coverage.py",
            "version": OUTPUT_SCHEMA,
        },
        "policy_digest": digest(policy_bytes),
        "schema_version": OUTPUT_SCHEMA,
        "service_count": len(projection),
        "services": projection,
        "source_digests": dict(sorted(all_sources.items())),
    }
    return (json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n").encode()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    expected = render(root)
    output = root / OUTPUT_PATH
    if args.check:
        if not output.is_file() or output.read_bytes() != expected:
            print(OUTPUT_PATH.as_posix())
            return 1
        return 0
    parser.error(
        "gRPC coverage writes are owned by generate_protocols.py's atomic transaction; "
        "use --check here or run `just generate-contracts`"
    )


if __name__ == "__main__":
    raise SystemExit(main())
