#!/usr/bin/env python3.12
"""Provider-neutral, fail-closed SDK generation boundary.

``plan`` and ``verify`` are deterministic and offline. ``generate`` is a guarded
subprocess boundary for a future pinned provider adapter; the checked-in
configuration intentionally leaves both providers unpinned, so connected
generation cannot currently execute.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn, cast

import yaml

PLAN_SCHEMA_VERSION = "mindclade.sdk-generation-plan/v1"
PROVENANCE_SCHEMA_VERSION = "mindclade.sdk-generation-provenance/v1"
DEFAULT_OPENAPI = Path("protocols/openapi/external-api.yaml")
DEFAULT_GENERATION = Path("protocols/openapi/generation.yaml")
DEFAULT_PLAN = Path("sdk-generation-plan.json")
HTTP_METHODS = frozenset({"delete", "get", "head", "options", "patch", "post", "put", "trace"})
LANGUAGES = ("go", "python", "typescript")
UNPINNED_VERSION = "unpinned"
EXIT_USAGE = 2
EXIT_CONNECTED_NOT_READY = 3
EXIT_VERIFY_MISMATCH = 4


class SdkGeneratorError(ValueError):
    """The local contract or requested operation is unsafe or inconsistent."""


class ConnectedGenerationError(RuntimeError):
    """Connected generation is not configured or explicitly authorized."""


@dataclass(frozen=True)
class ProviderAdapter:
    """Source-owned semantics for a provider implementation boundary."""

    provider_id: str
    role: str
    languages: tuple[str, ...]
    connected: bool


ADAPTERS: Mapping[str, ProviderAdapter] = {
    "stainless": ProviderAdapter(
        provider_id="stainless",
        role="primary",
        languages=LANGUAGES,
        connected=True,
    ),
    "oagen": ProviderAdapter(
        provider_id="oagen",
        role="shadow-promotable",
        languages=LANGUAGES,
        connected=True,
    ),
}


def sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def canonical_json(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def load_yaml_mapping(path: Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise SdkGeneratorError(f"cannot read {path}: {error}") from error
    if not isinstance(value, dict):
        raise SdkGeneratorError(f"{path} must contain a YAML mapping")
    return cast(dict[str, Any], value)


def require_mapping(value: Any, location: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SdkGeneratorError(f"{location} must be a mapping")
    return cast(Mapping[str, Any], value)


def require_sequence(value: Any, location: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise SdkGeneratorError(f"{location} must be an array")
    return cast(Sequence[Any], value)


def require_string(value: Any, location: str) -> str:
    if not isinstance(value, str) or not value or "\n" in value or "\r" in value:
        raise SdkGeneratorError(f"{location} must be a non-empty single-line string")
    return value


def repository_root(openapi_path: Path) -> Path | None:
    resolved = openapi_path.resolve()
    for candidate in resolved.parents:
        if (candidate / "protocols/openapi").is_dir() and (candidate / "tools/codegen").is_dir():
            return candidate
    return None


def validate_output_root(output_root: Path, openapi_path: Path) -> Path:
    resolved = output_root.resolve()
    if resolved == Path(resolved.anchor):
        raise SdkGeneratorError("output root cannot be the filesystem root")
    repository = repository_root(openapi_path)
    if repository is not None and resolved == repository:
        raise SdkGeneratorError("output root cannot be the repository root")
    return resolved


def confined_output(output_root: Path, relative: Path, label: str) -> Path:
    if relative.is_absolute() or relative == Path() or ".." in relative.parts:
        raise SdkGeneratorError(f"{label} must be a non-empty relative path beneath output root")
    candidate = (output_root / relative).resolve()
    if candidate == output_root or not candidate.is_relative_to(output_root):
        raise SdkGeneratorError(f"{label} escapes output root: {relative}")
    return candidate


def write_atomic(output_root: Path, relative: Path, content: bytes) -> Path:
    destination = confined_output(output_root, relative, "output")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp")
    if not temporary.is_relative_to(output_root):
        raise SdkGeneratorError("temporary output escapes output root")
    temporary.write_bytes(content)
    temporary.replace(destination)
    return destination


def operation_ids(openapi: Mapping[str, Any]) -> tuple[str, ...]:
    paths = require_mapping(openapi.get("paths"), "OpenAPI paths")
    found: list[str] = []
    for path_name, raw_path_item in paths.items():
        path_item = require_mapping(raw_path_item, f"OpenAPI path {path_name}")
        for method, raw_operation in path_item.items():
            if method not in HTTP_METHODS:
                continue
            operation = require_mapping(raw_operation, f"OpenAPI {method} {path_name}")
            found.append(
                require_string(
                    operation.get("operationId"),
                    f"OpenAPI {method} {path_name}.operationId",
                )
            )
    if len(found) != len(set(found)):
        raise SdkGeneratorError("OpenAPI operationId values must be unique")
    if not found:
        raise SdkGeneratorError("OpenAPI must declare at least one operation")
    return tuple(sorted(found))


def public_schemas(openapi: Mapping[str, Any]) -> tuple[str, ...]:
    components = require_mapping(openapi.get("components"), "OpenAPI components")
    schemas = require_mapping(components.get("schemas"), "OpenAPI components.schemas")
    names = tuple(sorted(require_string(name, "OpenAPI schema name") for name in schemas))
    if not names:
        raise SdkGeneratorError("OpenAPI must declare public schemas")
    return names


def iter_local_refs(value: object) -> Sequence[str]:
    """Return local references without resolving provider-specific extensions."""
    found: list[str] = []
    if isinstance(value, Mapping):
        for key, child in cast(Mapping[object, object], value).items():
            if key == "$ref":
                if not isinstance(child, str) or not child.startswith("#/"):
                    raise SdkGeneratorError(
                        f"OpenAPI references must be local JSON pointers: {child!r}"
                    )
                found.append(child)
            else:
                found.extend(iter_local_refs(child))
    elif isinstance(value, list):
        for child in cast(list[object], value):
            found.extend(iter_local_refs(child))
    return found


def resolve_local_ref(document: Mapping[str, Any], reference: str) -> Any:
    """Resolve a JSON-pointer reference in the bundled OpenAPI document."""
    value: object = document
    for component in reference[2:].split("/"):
        component = component.replace("~1", "/").replace("~0", "~")
        if not isinstance(value, Mapping):
            raise SdkGeneratorError(f"unresolved OpenAPI reference: {reference}")
        mapping = cast(Mapping[str, object], value)
        if component not in mapping:
            raise SdkGeneratorError(f"unresolved OpenAPI reference: {reference}")
        value = mapping[component]
    return value


def configured_providers(generation: Mapping[str, Any]) -> Mapping[str, Mapping[str, Any]]:
    spec = require_mapping(generation.get("spec"), "generation.spec")
    raw_providers = require_sequence(spec.get("providers"), "generation.spec.providers")
    providers: dict[str, Mapping[str, Any]] = {}
    for index, raw_provider in enumerate(raw_providers):
        provider = require_mapping(raw_provider, f"generation.spec.providers[{index}]")
        provider_id = require_string(provider.get("id"), f"providers[{index}].id")
        if provider_id in providers:
            raise SdkGeneratorError(f"duplicate SDK provider: {provider_id}")
        providers[provider_id] = provider
    return providers


def validate_contract(
    openapi: Mapping[str, Any],
    generation: Mapping[str, Any],
) -> Mapping[str, Mapping[str, Any]]:
    if openapi.get("openapi") != "3.1.0":
        raise SdkGeneratorError("SDK generation requires the OpenAPI 3.1.0 public contract")
    for reference in iter_local_refs(openapi):
        resolve_local_ref(openapi, reference)
    _ = operation_ids(openapi)
    _ = public_schemas(openapi)
    if generation.get("kind") != "SdkGeneration":
        raise SdkGeneratorError("generation kind must be SdkGeneration")
    spec = require_mapping(generation.get("spec"), "generation.spec")
    authority = require_mapping(spec.get("authority"), "generation.spec.authority")
    if authority.get("source") != DEFAULT_OPENAPI.as_posix():
        raise SdkGeneratorError("generation authority must remain the curated external OpenAPI")
    interface = require_mapping(spec.get("interface"), "generation.spec.interface")
    if interface.get("name") != "SdkGenerator" or interface.get("version") != "v1":
        raise SdkGeneratorError("generation interface must be SdkGenerator v1")
    local_adapter = require_mapping(
        spec.get("localContractAdapter"), "generation.spec.localContractAdapter"
    )
    if local_adapter.get("implementation") != "tools/codegen/sdk_generator.py":
        raise SdkGeneratorError("local contract adapter must be tools/codegen/sdk_generator.py")
    if (
        local_adapter.get("network") != "forbidden"
        or local_adapter.get("emitsSdkSource") is not False
    ):
        raise SdkGeneratorError("local plan/verify adapter must be offline and emit no SDK source")
    providers = configured_providers(generation)
    if set(providers) != set(ADAPTERS):
        raise SdkGeneratorError("configured providers must be exactly stainless and oagen")
    for provider_id, adapter in ADAPTERS.items():
        provider = providers[provider_id]
        if provider.get("role") != adapter.role:
            raise SdkGeneratorError(f"{provider_id} role must be {adapter.role}")
        languages = require_sequence(provider.get("languages"), f"{provider_id}.languages")
        if tuple(languages) != adapter.languages:
            raise SdkGeneratorError(
                f"{provider_id} languages must be {', '.join(adapter.languages)} in stable order"
            )
        if provider.get("source") != DEFAULT_OPENAPI.as_posix():
            raise SdkGeneratorError(f"{provider_id} must consume the curated OpenAPI source")
        release = require_mapping(provider.get("release"), f"{provider_id}.release")
        if release.get("publish") is not False:
            raise SdkGeneratorError(f"{provider_id} publication must remain disabled in source")
        adapter_config = require_mapping(provider.get("adapter"), f"{provider_id}.adapter")
        if adapter_config.get("contractVersion") != "v1":
            raise SdkGeneratorError(f"{provider_id} adapter contract must be v1")
        _ = require_string(adapter_config.get("providerVersion"), f"{provider_id}.providerVersion")
    parity = require_mapping(spec.get("parity"), "generation.spec.parity")
    if parity.get("primary") != "stainless" or parity.get("shadow") != "oagen":
        raise SdkGeneratorError("parity must compare Stainless primary with oagen shadow")
    qualification = require_mapping(spec.get("qualification"), "generation.spec.qualification")
    if qualification.get("publishAuthorized") is not False:
        raise SdkGeneratorError("source qualification cannot authorize SDK publication")
    return providers


def selected_values(selection: str, available: Sequence[str]) -> tuple[str, ...]:
    return tuple(available) if selection == "all" else (selection,)


def provider_version(provider: Mapping[str, Any], override: str | None) -> str:
    configured = require_mapping(provider.get("adapter"), "provider.adapter")
    value = require_string(configured.get("providerVersion"), "provider.adapter.providerVersion")
    if override is None:
        return value
    return require_string(override, "provider version override")


def require_digest(value: Any, location: str) -> str:
    digest = require_string(value, location)
    if len(digest) != 71 or not digest.startswith("sha256:"):
        raise SdkGeneratorError(f"{location} must be a sha256:<64 lowercase hex> digest")
    if any(character not in "0123456789abcdef" for character in digest[7:]):
        raise SdkGeneratorError(f"{location} must be a sha256:<64 lowercase hex> digest")
    return digest


def build_plan(
    *,
    openapi_path: Path,
    generation_path: Path,
    output_root: Path,
    source_revision: str,
    provider_selection: str,
    language_selection: str,
    provider_version_override: str | None = None,
) -> dict[str, Any]:
    openapi = load_yaml_mapping(openapi_path)
    generation = load_yaml_mapping(generation_path)
    providers = validate_contract(openapi, generation)
    safe_root = validate_output_root(output_root, openapi_path)
    source_revision = require_string(source_revision, "source revision")
    selected_providers = selected_values(provider_selection, tuple(sorted(ADAPTERS)))
    selected_languages = selected_values(language_selection, LANGUAGES)
    if provider_version_override is not None and len(selected_providers) != 1:
        raise SdkGeneratorError("--provider-version requires one explicit provider")

    provenance: list[dict[str, Any]] = []
    openapi_digest = sha256_file(openapi_path)
    generation_digest = sha256_file(generation_path)
    for provider_id in selected_providers:
        adapter = ADAPTERS[provider_id]
        provider = providers[provider_id]
        version = provider_version(provider, provider_version_override)
        adapter_config = require_mapping(provider.get("adapter"), f"{provider_id}.adapter")
        for language in selected_languages:
            if language not in adapter.languages:
                raise SdkGeneratorError(f"{provider_id} does not declare {language}")
            relative_output = Path(provider_id) / language
            _ = confined_output(safe_root, relative_output, "provider output directory")
            provenance.append(
                {
                    "adapterContractVersion": adapter_config["contractVersion"],
                    "connectedGeneration": "not-run",
                    "generationConfigSha256": generation_digest,
                    "language": language,
                    "openapiSha256": openapi_digest,
                    "outputDirectory": relative_output.as_posix(),
                    "provider": provider_id,
                    "providerRole": adapter.role,
                    "providerVersion": version,
                    "readiness": provider.get("readiness"),
                    "sourceRevision": source_revision,
                }
            )

    spec = require_mapping(generation["spec"], "generation.spec")
    parity = require_mapping(spec.get("parity"), "generation.spec.parity")
    return {
        "schemaVersion": PLAN_SCHEMA_VERSION,
        "kind": "SdkGenerationPlan",
        "authority": {
            "apiProfile": openapi.get("x-mindclade-api-profile"),
            "generationConfig": DEFAULT_GENERATION.as_posix(),
            "generationConfigSha256": generation_digest,
            "openapi": DEFAULT_OPENAPI.as_posix(),
            "openapiSha256": openapi_digest,
        },
        "inventory": {
            "operationIds": list(operation_ids(openapi)),
            "publicSchemas": list(public_schemas(openapi)),
        },
        "provenance": provenance,
        "parity": {
            "compare": sorted(
                require_string(value, "generation.spec.parity.compare item")
                for value in require_sequence(
                    parity.get("compare"), "generation.spec.parity.compare"
                )
            ),
            "failurePolicy": parity.get("failurePolicy"),
            "primary": "stainless",
            "shadow": "oagen",
        },
        "safety": {
            "emitsSdkSource": False,
            "network": "forbidden",
            "publishAuthorized": False,
        },
    }


def provider_configuration(generation: Mapping[str, Any], provider_id: str) -> Mapping[str, Any]:
    providers = configured_providers(generation)
    if provider_id not in providers:
        raise SdkGeneratorError(f"unknown SDK provider: {provider_id}")
    return providers[provider_id]


def executable_digest(path: Path) -> str:
    if not path.is_file():
        raise ConnectedGenerationError(f"provider executable does not exist: {path}")
    return sha256_file(path)


def generate_connected(args: argparse.Namespace) -> int:
    if not args.allow_connected:
        raise ConnectedGenerationError(
            "connected generation requires --allow-connected and protected qualification"
        )
    if args.provider == "all" or args.language == "all":
        raise ConnectedGenerationError(
            "connected generation requires one provider and one language"
        )
    if not 1 <= args.timeout_seconds <= 3600:
        raise ConnectedGenerationError("provider timeout must be between 1 and 3600 seconds")
    openapi_path = Path(args.openapi).resolve()
    generation_path = Path(args.generation).resolve()
    generation = load_yaml_mapping(generation_path)
    openapi = load_yaml_mapping(openapi_path)
    _ = validate_contract(openapi, generation)
    provider = provider_configuration(generation, args.provider)
    if provider.get("readiness") != "pinned-local-adapter":
        raise ConnectedGenerationError(
            f"{args.provider} is {provider.get('readiness')}; no pinned local adapter may execute"
        )
    adapter = require_mapping(provider.get("adapter"), f"{args.provider}.adapter")
    configured_executable = adapter.get("executable")
    configured_digest = adapter.get("executableSha256")
    if not isinstance(configured_executable, str) or not isinstance(configured_digest, str):
        raise ConnectedGenerationError("provider executable path and sha256 must be pinned")
    if not Path(configured_executable).is_absolute():
        raise ConnectedGenerationError("provider executable must be an absolute pinned path")
    try:
        configured_digest = require_digest(configured_digest, "provider.adapter.executableSha256")
    except SdkGeneratorError as error:
        raise ConnectedGenerationError(str(error)) from error
    if not args.provider_command:
        raise ConnectedGenerationError("a provider command is required after --provider-command")
    executable = Path(args.provider_command[0])
    if not executable.is_absolute():
        raise ConnectedGenerationError("provider executable must be an absolute pinned path")
    executable = executable.resolve()
    if executable.as_posix() != configured_executable:
        raise ConnectedGenerationError("provider executable differs from checked-in configuration")
    if executable_digest(executable) != configured_digest:
        raise ConnectedGenerationError(
            "provider executable digest differs from checked-in configuration"
        )
    configured_version = provider_version(provider, None)
    if configured_version == UNPINNED_VERSION:
        raise ConnectedGenerationError("provider version must be pinned before generation")
    if args.provider_version is not None and args.provider_version != configured_version:
        raise ConnectedGenerationError(
            "provider version override differs from checked-in configuration"
        )

    safe_root = validate_output_root(Path(args.output_root), openapi_path)
    relative_output = Path(args.provider) / args.language
    output_directory = confined_output(safe_root, relative_output, "provider output directory")
    output_directory.mkdir(parents=True, exist_ok=True)
    openapi_digest = sha256_file(openapi_path)
    generation_digest = sha256_file(generation_path)
    process_environment = {
        "LANG": "C",
        "LC_ALL": "C",
        "TZ": "UTC",
        "MINDCLADE_OPENAPI_PATH": openapi_path.as_posix(),
        "MINDCLADE_GENERATION_CONFIG_PATH": generation_path.as_posix(),
        "MINDCLADE_SDK_LANGUAGE": args.language,
        "MINDCLADE_SDK_OUTPUT_DIRECTORY": output_directory.as_posix(),
        "MINDCLADE_SDK_PROVIDER": args.provider,
    }
    try:
        result = subprocess.run(
            args.provider_command,
            check=False,
            cwd=output_directory,
            env=process_environment,
            timeout=args.timeout_seconds,
        )
    except subprocess.TimeoutExpired as error:
        raise ConnectedGenerationError(
            f"{args.provider} adapter exceeded {args.timeout_seconds}s timeout"
        ) from error
    if result.returncode != 0:
        raise ConnectedGenerationError(
            f"{args.provider} adapter exited with status {result.returncode}"
        )
    if (
        sha256_file(openapi_path) != openapi_digest
        or sha256_file(generation_path) != generation_digest
    ):
        raise ConnectedGenerationError("provider adapter mutated the OpenAPI or generation input")
    provenance = {
        "schemaVersion": PROVENANCE_SCHEMA_VERSION,
        "generationConfigSha256": generation_digest,
        "language": args.language,
        "openapiSha256": openapi_digest,
        "provider": args.provider,
        "providerExecutableSha256": configured_digest,
        "providerVersion": configured_version,
        "sourceRevision": require_string(args.source_revision, "source revision"),
    }
    _ = write_atomic(
        safe_root,
        relative_output / "mindclade-sdk-provenance.json",
        canonical_json(provenance),
    )
    return 0


def add_plan_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--openapi", type=Path, default=DEFAULT_OPENAPI)
    parser.add_argument("--generation", type=Path, default=DEFAULT_GENERATION)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--provider", choices=("all", *sorted(ADAPTERS)), default="all")
    parser.add_argument("--language", choices=("all", *LANGUAGES), default="all")
    parser.add_argument("--provider-version")


def parser() -> argparse.ArgumentParser:
    root_parser = argparse.ArgumentParser(description=__doc__)
    subparsers = root_parser.add_subparsers(dest="command", required=True)

    plan_parser = subparsers.add_parser("plan", help="emit an offline canonical SDK plan")
    add_plan_arguments(plan_parser)
    plan_parser.add_argument("--output", type=Path, default=DEFAULT_PLAN)

    verify_parser = subparsers.add_parser("verify", help="verify a canonical SDK plan offline")
    add_plan_arguments(verify_parser)
    verify_parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)

    generate_parser = subparsers.add_parser(
        "generate", help="guarded boundary for a future pinned provider executable"
    )
    add_plan_arguments(generate_parser)
    generate_parser.add_argument("--allow-connected", action="store_true")
    generate_parser.add_argument("--timeout-seconds", type=int, default=900)
    generate_parser.add_argument("--provider-command", nargs=argparse.REMAINDER)
    return root_parser


def plan_from_args(args: argparse.Namespace) -> dict[str, Any]:
    return build_plan(
        openapi_path=Path(args.openapi),
        generation_path=Path(args.generation),
        output_root=Path(args.output_root),
        source_revision=args.source_revision,
        provider_selection=args.provider,
        language_selection=args.language,
        provider_version_override=args.provider_version,
    )


def fail(message: str, exit_code: int) -> NoReturn:
    print(f"sdk-generator: {message}", file=sys.stderr)
    raise SystemExit(exit_code)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    try:
        if arguments.command == "plan":
            plan = plan_from_args(arguments)
            safe_root = validate_output_root(Path(arguments.output_root), Path(arguments.openapi))
            destination = write_atomic(safe_root, Path(arguments.output), canonical_json(plan))
            print(destination)
            return 0
        if arguments.command == "verify":
            expected = canonical_json(plan_from_args(arguments))
            safe_root = validate_output_root(Path(arguments.output_root), Path(arguments.openapi))
            plan_path = confined_output(safe_root, Path(arguments.plan), "plan")
            if not plan_path.is_file():
                fail(f"plan does not exist: {plan_path}", EXIT_VERIFY_MISMATCH)
            if plan_path.read_bytes() != expected:
                fail("plan differs from canonical OpenAPI/config projection", EXIT_VERIFY_MISMATCH)
            print(plan_path)
            return 0
        if arguments.command == "generate":
            return generate_connected(arguments)
        fail(f"unsupported command: {arguments.command}", EXIT_USAGE)
    except ConnectedGenerationError as error:
        fail(str(error), EXIT_CONNECTED_NOT_READY)
    except (OSError, SdkGeneratorError, subprocess.TimeoutExpired) as error:
        fail(str(error), EXIT_USAGE)


if __name__ == "__main__":
    raise SystemExit(main())
