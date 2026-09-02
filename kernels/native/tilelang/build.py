from __future__ import annotations

import argparse
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import tempfile
from types import MappingProxyType
from typing import Any, Protocol

from kernels.api import ImplementationSpec, KernelSpec, content_digest
from kernels.native.codegen.discover import DiscoveredKernelSpec, discover_specs
from kernels.native.codegen.generate import GENERATOR_ID, GENERATOR_VERSION
from kernels.native.tilelang.registry import registry

_PROFILE_NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_PARAMETER_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_TARGET = re.compile(r"^[a-z0-9][a-z0-9_.+-]{0,127}$")
_STRING_VALUE = re.compile(r"^[A-Za-z0-9_.+-]{1,128}$")
_IMPLEMENTATION_ID = re.compile(r"^[a-z][a-z0-9_]{0,63}@[1-9][0-9]*$")
_SYMBOL = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,255}$")
_MAX_PROFILES_PER_OPERATOR = 64
_MAX_PARAMETERS_PER_PROFILE = 64
_MAX_INTEGER = 2_147_483_647
_MAX_FLOAT_MAGNITUDE = 1.0e12

Scalar = bool | int | float | str


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def _digest(value: object) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(value)).hexdigest()


@dataclass(frozen=True, slots=True)
class SpecializationProfile:
    name: str
    arguments: Mapping[str, Scalar]
    implementation: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or _PROFILE_NAME.fullmatch(self.name) is None:
            raise ValueError(f"invalid specialization profile name: {self.name!r}")
        if self.implementation is not None and (
            not isinstance(self.implementation, str)
            or _IMPLEMENTATION_ID.fullmatch(self.implementation) is None
        ):
            raise ValueError("profile implementation must be a canonical name@version identity")
        if not isinstance(self.arguments, Mapping):
            raise ValueError("specialization arguments must be a mapping")
        if not 1 <= len(self.arguments) <= _MAX_PARAMETERS_PER_PROFILE:
            raise ValueError(
                f"specialization profiles require 1-{_MAX_PARAMETERS_PER_PROFILE} bounded arguments"
            )
        normalized: dict[str, Scalar] = {}
        for key, value in sorted(self.arguments.items(), key=lambda item: str(item[0])):
            if not isinstance(key, str) or _PARAMETER_NAME.fullmatch(key) is None or key == "target":
                raise ValueError(f"invalid or reserved specialization argument: {key!r}")
            if isinstance(value, bool):
                pass
            elif isinstance(value, int):
                if not 1 <= value <= _MAX_INTEGER:
                    raise ValueError(f"specialization integer {key!r} is outside the bounded range")
            elif isinstance(value, float):
                if not math.isfinite(value) or abs(value) > _MAX_FLOAT_MAGNITUDE:
                    raise ValueError(f"specialization float {key!r} is not finite and bounded")
            elif isinstance(value, str):
                if _STRING_VALUE.fullmatch(value) is None:
                    raise ValueError(f"specialization string {key!r} is not a bounded token")
            else:
                raise ValueError(
                    f"unsupported specialization value for {key!r}: {type(value).__name__}"
                )
            normalized[key] = value
        object.__setattr__(self, "arguments", MappingProxyType(normalized))

    @classmethod
    def from_value(cls, value: object) -> SpecializationProfile:
        if isinstance(value, cls):
            return value
        if not isinstance(value, Mapping):
            raise ValueError("profile must be an object")
        if set(value) not in ({"name", "arguments"}, {"name", "arguments", "implementation"}):
            raise ValueError("profile must contain name, arguments, and optional implementation")
        return cls(
            name=value["name"],  # type: ignore[arg-type]
            arguments=value["arguments"],  # type: ignore[arg-type]
            implementation=value.get("implementation"),  # type: ignore[arg-type]
        )

    def to_manifest(self) -> dict[str, object]:
        return {
            "arguments": dict(self.arguments),
            "implementation": self.implementation,
            "name": self.name,
        }


@dataclass(frozen=True, slots=True)
class PicCompileAction:
    qualified_name: str
    phase: str
    node: str
    builder: str
    symbol: str
    target: str
    profile: str
    specialization: Mapping[str, Scalar]
    implementation: str | None

    def __post_init__(self) -> None:
        if self.phase not in {"forward", "backward"}:
            raise ValueError("PIC action phase must be forward or backward")
        if _SYMBOL.fullmatch(self.symbol) is None:
            raise ValueError("PIC action symbol is invalid")
        object.__setattr__(self, "specialization", MappingProxyType(dict(self.specialization)))

    def to_manifest(self) -> dict[str, object]:
        return {
            "builder": self.builder,
            "implementation": self.implementation,
            "node": self.node,
            "phase": self.phase,
            "profile": self.profile,
            "qualified_name": self.qualified_name,
            "specialization": dict(self.specialization),
            "symbol": self.symbol,
            "target": self.target,
        }

    @property
    def digest(self) -> str:
        return _digest(self.to_manifest())


@dataclass(frozen=True, slots=True)
class CompiledArtifact:
    pic_object: bytes
    exported_symbols: tuple[str, ...]
    source_sha256: str
    object_format: str = "pic_object"

    def __post_init__(self) -> None:
        if not isinstance(self.pic_object, bytes) or not self.pic_object:
            raise RuntimeError("compiler adapter returned an empty PIC object")
        if self.object_format != "pic_object":
            raise RuntimeError("compiler adapter must return object_format='pic_object'")
        if (
            not isinstance(self.exported_symbols, tuple)
            or not self.exported_symbols
            or any(_SYMBOL.fullmatch(value) is None for value in self.exported_symbols)
            or tuple(sorted(set(self.exported_symbols))) != self.exported_symbols
        ):
            raise RuntimeError("compiler adapter returned an invalid exported-symbol inventory")
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", self.source_sha256):
            raise RuntimeError("compiler adapter source digest is invalid")


class OfflineCompilerAdapter(Protocol):
    compiler_id: str
    compiler_version: str

    def compile(self, program: object, action: PicCompileAction) -> CompiledArtifact: ...


class TileLangCompatibilityAdapter:
    """Pinned adapter requiring TileLang to expose an actual PIC object.

    Source-only JIT adapters are intentionally rejected. A hermetic toolchain may
    implement ``get_pic_object`` and ``get_exported_symbols`` directly or replace
    this adapter with an equivalent Bazel action adapter.
    """

    compiler_id = "tilelang"

    def __init__(self, tilelang_module: object) -> None:
        version = getattr(tilelang_module, "__version__", None)
        if not isinstance(version, str) or not version:
            raise RuntimeError("TileLang compiler must expose a nonempty version identity")
        self.compiler_version = version

    def compile(self, program: object, action: PicCompileAction) -> CompiledArtifact:
        compile_method = getattr(program, "compile", None)
        if not callable(compile_method):
            raise RuntimeError(
                f"{action.qualified_name}/{action.profile}/{action.phase}/{action.node}: "
                "builder did not return a compilable TileLang object"
            )
        compiled = compile_method()
        source = _compiled_source(compiled, program, action.qualified_name)
        pic_object: bytes | None = None
        exported_symbols: tuple[str, ...] | None = None
        for candidate in (compiled, program):
            getter = getattr(candidate, "get_pic_object", None)
            if callable(getter):
                value = getter()
                if isinstance(value, bytes) and value:
                    pic_object = value
                    break
        for candidate in (compiled, program):
            getter = getattr(candidate, "get_exported_symbols", None)
            if callable(getter):
                value = getter()
                if isinstance(value, (tuple, list)) and all(
                    isinstance(symbol, str) for symbol in value
                ):
                    exported_symbols = tuple(sorted(set(value)))
                    break
        if pic_object is None or exported_symbols is None:
            raise RuntimeError(
                f"{action.qualified_name}/{action.profile}/{action.phase}/{action.node}: "
                "TileLang compatibility adapter produced source only; the pinned PIC "
                "compile action must provide get_pic_object() and get_exported_symbols()"
            )
        return CompiledArtifact(
            pic_object=pic_object,
            exported_symbols=exported_symbols,
            source_sha256="sha256:" + hashlib.sha256(source).hexdigest(),
        )


@dataclass(frozen=True, slots=True)
class CompiledUnitReceipt:
    phase: str
    node: str
    builder: str
    symbol: str
    action_digest: str
    artifact: str
    artifact_sha256: str
    source_sha256: str
    object_format: str

    def to_manifest(self) -> dict[str, object]:
        return {
            "action_digest": self.action_digest,
            "artifact": self.artifact,
            "artifact_sha256": self.artifact_sha256,
            "builder": self.builder,
            "node": self.node,
            "object_format": self.object_format,
            "phase": self.phase,
            "source_sha256": self.source_sha256,
            "symbol": self.symbol,
        }


@dataclass(frozen=True, slots=True)
class PhaseReceipt:
    phase: str
    logical_builder: str
    logical_symbol: str
    execution_order: tuple[str, ...]
    program_group: bool
    program_group_digest: str | None
    units: tuple[CompiledUnitReceipt, ...]

    def to_manifest(self) -> dict[str, object]:
        return {
            "execution_order": list(self.execution_order),
            "logical_builder": self.logical_builder,
            "logical_symbol": self.logical_symbol,
            "program_group": self.program_group,
            "program_group_digest": self.program_group_digest,
            "units": [unit.to_manifest() for unit in self.units],
        }


@dataclass(frozen=True, slots=True)
class BuildReceipt:
    qualified_name: str
    profile: str
    specialization: Mapping[str, Scalar]
    declaration_source: str
    spec_sha256: str
    kernel_spec_digest: str
    implementation: str | None
    implementation_digest: str
    capability_envelope_digest: str
    target: str
    compiler: str
    compiler_version: str
    forward: PhaseReceipt
    backward: PhaseReceipt | None
    capability_digest: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "specialization", MappingProxyType(dict(self.specialization)))
        if self.backward is None and self.forward.phase != "forward":
            raise ValueError("build receipt has an invalid forward phase")

    def to_manifest(self) -> dict[str, object]:
        return {
            "backward": self.backward.to_manifest() if self.backward is not None else None,
            "capability_digest": self.capability_digest,
            "capability_envelope_digest": self.capability_envelope_digest,
            "compiler": self.compiler,
            "compiler_version": self.compiler_version,
            "declaration_source": self.declaration_source,
            "forward": self.forward.to_manifest(),
            "implementation": self.implementation,
            "implementation_digest": self.implementation_digest,
            "kernel_spec_digest": self.kernel_spec_digest,
            "profile": self.profile,
            "qualified_name": self.qualified_name,
            "spec_sha256": self.spec_sha256,
            "specialization": dict(self.specialization),
            "target": self.target,
        }


def _normalize_profiles(
    specs: Sequence[KernelSpec],
    profiles: Mapping[str, Sequence[SpecializationProfile | Mapping[str, object]]],
) -> dict[str, tuple[SpecializationProfile, ...]]:
    if not isinstance(profiles, Mapping):
        raise ValueError("specialization profiles must be keyed by qualified operator name")
    expected = {spec.qualified_name for spec in specs}
    actual = set(profiles)
    if actual != expected:
        raise ValueError(
            "specialization profile inventory mismatch; "
            f"missing={sorted(expected - actual)}, extra={sorted(actual - expected)}"
        )
    normalized: dict[str, tuple[SpecializationProfile, ...]] = {}
    for qualified_name in sorted(expected):
        values = profiles[qualified_name]
        if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
            raise ValueError(f"{qualified_name}: profiles must be a bounded sequence")
        if not 1 <= len(values) <= _MAX_PROFILES_PER_OPERATOR:
            raise ValueError(
                f"{qualified_name}: requires 1-{_MAX_PROFILES_PER_OPERATOR} specialization profiles"
            )
        parsed = tuple(sorted((SpecializationProfile.from_value(value) for value in values), key=lambda item: item.name))
        if len({profile.name for profile in parsed}) != len(parsed):
            raise ValueError(f"{qualified_name}: duplicate specialization profile name")
        normalized[qualified_name] = parsed
    return normalized


def _implementation_identity(value: ImplementationSpec) -> str:
    return f"{value.name}@{value.version}"


def _select_implementation(
    entry: DiscoveredKernelSpec, profile: SpecializationProfile
) -> ImplementationSpec | None:
    implementations = entry.implementations
    if not implementations:
        if profile.implementation is not None:
            raise ValueError(
                f"{entry.qualified_name}/{profile.name}: profile selects an undeclared implementation"
            )
        return None
    by_identity = {_implementation_identity(value): value for value in implementations}
    if profile.implementation is not None:
        try:
            return by_identity[profile.implementation]
        except KeyError as exc:
            raise ValueError(
                f"{entry.qualified_name}/{profile.name}: unknown implementation "
                f"{profile.implementation!r}"
            ) from exc
    if len(implementations) != 1:
        raise ValueError(
            f"{entry.qualified_name}/{profile.name}: implementation must be explicit; "
            f"available={sorted(by_identity)}"
        )
    return implementations[0]


def _resolve_builder_identity(
    spec: KernelSpec, identity: str, kernels_root: Path
):
    if identity.count(":") != 1:
        raise RuntimeError(f"{spec.qualified_name}: builder is not module:function")
    module_name, function_name = identity.split(":", 1)
    expected_module = f"kernels.{spec.family}.{spec.name}.tilelang"
    if module_name != expected_module:
        raise RuntimeError(f"{spec.qualified_name}: builder module must be {expected_module}")
    declared_file = kernels_root / spec.family / spec.name / "tilelang.py"
    current = kernels_root
    for component in (spec.family, spec.name, "tilelang.py"):
        current = current / component
        if current.is_symlink():
            raise RuntimeError(f"{spec.qualified_name}: builder source must not be a symlink")
    try:
        declared_file = declared_file.resolve(strict=True)
    except (FileNotFoundError, RuntimeError) as exc:
        raise RuntimeError(f"{spec.qualified_name}: operation-local builder source does not exist") from exc
    module = importlib.import_module(module_name)
    module_file = getattr(module, "__file__", None)
    if module_file is None or Path(module_file).resolve(strict=True) != declared_file:
        raise RuntimeError(f"{spec.qualified_name}: imported builder does not match operation-local tilelang.py")
    builder = getattr(module, function_name, None)
    if not callable(builder):
        raise RuntimeError(f"{spec.qualified_name}: declared builder {function_name!r} is not callable")
    return builder


def _resolve_builder(spec: KernelSpec, kernels_root: Path):
    return _resolve_builder_identity(spec, spec.forward.builder, kernels_root)


def _compiled_source(compiled: object, program: object, qualified_name: str) -> bytes:
    for candidate in (compiled, program):
        getter = getattr(candidate, "get_kernel_source", None)
        if callable(getter):
            value = getter()
            if isinstance(value, str) and value.strip():
                return value.encode("utf-8")
            if isinstance(value, bytes) and value.strip():
                return value
    raise RuntimeError(f"{qualified_name}: TileLang compile returned no generated source")


def _validate_group_descriptor(
    value: object, *, phase: str, provider: Any
) -> None:
    group = provider.program_group
    assert group is not None
    expected = {
        "execution_order": tuple(node.name for node in group.nodes),
        "logical_symbol": provider.symbol,
        "phase": phase,
        "version": 1,
        "workspaces": tuple(workspace.name for workspace in group.workspaces),
    }
    if not isinstance(value, Mapping) or set(value) != set(expected):
        raise RuntimeError(
            f"{phase} program-group logical builder must return the exact descriptor keys "
            f"{sorted(expected)}"
        )
    normalized = dict(value)
    normalized["execution_order"] = tuple(normalized["execution_order"])
    normalized["workspaces"] = tuple(normalized["workspaces"])
    if normalized != expected:
        raise RuntimeError(f"{phase} program-group logical builder descriptor differs from KernelSpec")


def _artifact_name(
    spec: KernelSpec,
    profile: SpecializationProfile,
    phase: str,
    node: str,
    implementation: ImplementationSpec | None,
    target: str,
) -> str:
    identity = "provider" if implementation is None else _implementation_identity(implementation)
    safe_identity = identity.replace("@", "_v")
    return f"{spec.name}.{safe_identity}.{profile.name}.{phase}.{node}.{target}.pic.o"


def _compile_phase(
    *,
    spec: KernelSpec,
    provider: Any,
    phase: str,
    profile: SpecializationProfile,
    implementation: ImplementationSpec | None,
    target: str,
    kernels_root: Path,
    adapter: OfflineCompilerAdapter,
) -> tuple[PhaseReceipt, list[tuple[str, bytes]]]:
    arguments = dict(profile.arguments)
    group = provider.program_group
    units: list[CompiledUnitReceipt] = []
    outputs: list[tuple[str, bytes]] = []
    if group is None:
        work = (("logical", provider.builder, provider.symbol),)
        execution_order = ("logical",)
        group_digest = None
    else:
        logical_builder = _resolve_builder_identity(spec, provider.builder, kernels_root)
        descriptor = logical_builder(target=target, **arguments)
        _validate_group_descriptor(descriptor, phase=phase, provider=provider)
        work = tuple((node.name, node.builder, node.symbol) for node in group.nodes)
        execution_order = tuple(node.name for node in group.nodes)
        group_digest = group.digest
    for node, builder_identity, symbol in work:
        builder = _resolve_builder_identity(spec, builder_identity, kernels_root)
        program = builder(target=target, **arguments)
        action = PicCompileAction(
            qualified_name=spec.qualified_name,
            phase=phase,
            node=node,
            builder=builder_identity,
            symbol=symbol,
            target=target,
            profile=profile.name,
            specialization=profile.arguments,
            implementation=(
                _implementation_identity(implementation)
                if implementation is not None
                else None
            ),
        )
        artifact = adapter.compile(program, action)
        if artifact.exported_symbols != (symbol,):
            raise RuntimeError(
                f"{spec.qualified_name}/{profile.name}/{phase}/{node}: PIC object must "
                f"export exactly {symbol!r}, got {artifact.exported_symbols!r}"
            )
        name = _artifact_name(spec, profile, phase, node, implementation, target)
        digest = "sha256:" + hashlib.sha256(artifact.pic_object).hexdigest()
        outputs.append((name, artifact.pic_object))
        units.append(
            CompiledUnitReceipt(
                phase=phase,
                node=node,
                builder=builder_identity,
                symbol=symbol,
                action_digest=action.digest,
                artifact=name,
                artifact_sha256=digest,
                source_sha256=artifact.source_sha256,
                object_format=artifact.object_format,
            )
        )
    return (
        PhaseReceipt(
            phase=phase,
            logical_builder=provider.builder,
            logical_symbol=provider.symbol,
            execution_order=execution_order,
            program_group=group is not None,
            program_group_digest=group_digest,
            units=tuple(units),
        ),
        outputs,
    )


def _atomic_write(path: Path, content: bytes) -> None:
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=f".{path.name}.", suffix=".tmp", dir=path.parent, delete=False
        ) as temporary:
            temporary_name = temporary.name
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.chmod(temporary_name, 0o644)
        os.replace(temporary_name, path)
        temporary_name = None
    finally:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)


def compile_all(
    native_root: Path,
    output_dir: Path,
    *,
    source_files: Iterable[str | Path],
    profiles: Mapping[str, Sequence[SpecializationProfile | Mapping[str, object]]],
    target: str,
    compiler_adapter: OfflineCompilerAdapter | None = None,
) -> list[BuildReceipt]:
    """Compile bounded PIC specializations and atomically emit receipt schema v3."""

    if not isinstance(target, str) or _TARGET.fullmatch(target) is None:
        raise ValueError("target must be an explicit bounded toolchain target token")
    if native_root.is_symlink():
        raise ValueError(f"native root must not be a symlink: {native_root}")
    try:
        root = native_root.resolve(strict=True)
    except (FileNotFoundError, RuntimeError) as exc:
        raise ValueError(f"native root does not exist: {native_root}") from exc
    output = output_dir.resolve()
    try:
        output.relative_to(root)
    except ValueError:
        pass
    else:
        raise ValueError("compiled artifacts must be emitted outside the native source tree")
    if output.exists():
        raise ValueError("compiled output path must not already exist")

    discovered = discover_specs(root.parent, source_files)
    specs = registry(discovered)
    profiles_by_name = _normalize_profiles(specs, profiles)
    if compiler_adapter is None and specs:
        try:
            tilelang_module = importlib.import_module("tilelang")
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "TileLang is required for offline native kernel compilation; use the pinned build toolchain"
            ) from exc
        compiler_adapter = TileLangCompatibilityAdapter(tilelang_module)
    if compiler_adapter is None:
        compiler_id = "not-invoked"
        compiler_version = "not-invoked"
    else:
        compiler_id = compiler_adapter.compiler_id
        compiler_version = compiler_adapter.compiler_version
    if not isinstance(compiler_id, str) or not compiler_id:
        raise RuntimeError("compiler adapter id must be nonempty")
    if not isinstance(compiler_version, str) or not compiler_version:
        raise RuntimeError("compiler adapter version must be nonempty")

    declarations = {entry.qualified_name: entry for entry in discovered}
    staged: list[tuple[str, bytes]] = []
    receipts: list[BuildReceipt] = []
    for spec in specs:
        assert compiler_adapter is not None
        entry = declarations[spec.qualified_name]
        for profile in profiles_by_name[spec.qualified_name]:
            implementation = _select_implementation(entry, profile)
            if implementation is not None and implementation.builder != spec.forward.builder:
                raise RuntimeError(
                    f"{spec.qualified_name}/{profile.name}: receipt v3 requires the selected "
                    "implementation builder to match ForwardSpec.builder"
                )
            forward, forward_outputs = _compile_phase(
                spec=spec,
                provider=spec.forward,
                phase="forward",
                profile=profile,
                implementation=implementation,
                target=target,
                kernels_root=root.parent,
                adapter=compiler_adapter,
            )
            backward = None
            backward_outputs: list[tuple[str, bytes]] = []
            if spec.backward is not None:
                backward, backward_outputs = _compile_phase(
                    spec=spec,
                    provider=spec.backward,
                    phase="backward",
                    profile=profile,
                    implementation=implementation,
                    target=target,
                    kernels_root=root.parent,
                    adapter=compiler_adapter,
                )
            implementation_digest = (
                implementation.digest if implementation is not None else content_digest([])
            )
            envelope_digest = (
                implementation.envelope.digest
                if implementation is not None
                else content_digest({"unqualified_provider": True})
            )
            capability_input = {
                "backward": backward.to_manifest() if backward is not None else None,
                "capability_envelope_digest": envelope_digest,
                "forward": forward.to_manifest(),
                "implementation_digest": implementation_digest,
                "kernel_spec_digest": spec.digest,
                "profile": profile.to_manifest(),
                "target": target,
            }
            receipts.append(
                BuildReceipt(
                    qualified_name=spec.qualified_name,
                    profile=profile.name,
                    specialization=profile.arguments,
                    declaration_source=spec.source,
                    spec_sha256=entry.declaration_sha256,
                    kernel_spec_digest=spec.digest,
                    implementation=(
                        _implementation_identity(implementation)
                        if implementation is not None
                        else None
                    ),
                    implementation_digest=implementation_digest,
                    capability_envelope_digest=envelope_digest,
                    target=target,
                    compiler=compiler_id,
                    compiler_version=compiler_version,
                    forward=forward,
                    backward=backward,
                    capability_digest=_digest(capability_input),
                )
            )
            staged.extend(forward_outputs)
            staged.extend(backward_outputs)

    artifact_names = [name for name, _ in staged]
    if len(artifact_names) != len(set(artifact_names)):
        raise RuntimeError("compiled PIC artifact names collide")
    receipt_document: dict[str, object] = {
        "compiler": {
            "id": compiler_id,
            "version": compiler_version,
        },
        "receipts": [receipt.to_manifest() for receipt in receipts],
        "registry_generator": {"id": GENERATOR_ID, "version": GENERATOR_VERSION},
        "schema_version": 3,
        "target": target,
    }
    receipt_document["document_digest"] = _digest(receipt_document)
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=f".{output.name}.", suffix=".staging", dir=output.parent)
    )
    try:
        for artifact_name, artifact in staged:
            _atomic_write(staging / artifact_name, artifact)
        _atomic_write(
            staging / "build_receipts.json",
            (json.dumps(receipt_document, sort_keys=True, indent=2) + "\n").encode("utf-8"),
        )
        os.replace(staging, output)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return receipts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline Mindclade TileLang compiler")
    parser.add_argument("--native-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--profiles", type=Path, required=True)
    parser.add_argument("--source", action="append", type=Path, default=[])
    args = parser.parse_args(argv)
    raw_profiles = json.loads(args.profiles.read_text(encoding="utf-8"))
    if not isinstance(raw_profiles, dict):
        raise ValueError("profile document must be an object keyed by qualified operator name")
    compile_all(
        args.native_root,
        args.output,
        source_files=args.source,
        profiles=raw_profiles,
        target=args.target,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
