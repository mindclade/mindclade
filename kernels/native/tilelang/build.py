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
import tempfile
from types import MappingProxyType

from kernels.api import KernelSpec
from kernels.native.codegen.discover import DiscoveredKernelSpec, discover_specs
from kernels.native.tilelang.registry import registry

_PROFILE_NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_PARAMETER_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_TARGET = re.compile(r"^[a-z0-9][a-z0-9_.+-]{0,127}$")
_STRING_VALUE = re.compile(r"^[A-Za-z0-9_.+-]{1,128}$")
_MAX_PROFILES_PER_OPERATOR = 64
_MAX_PARAMETERS_PER_PROFILE = 32
_MAX_INTEGER = 2_147_483_647
_MAX_FLOAT_MAGNITUDE = 1.0e12

Scalar = bool | int | float | str


@dataclass(frozen=True, slots=True)
class SpecializationProfile:
    name: str
    arguments: Mapping[str, Scalar]

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or _PROFILE_NAME.fullmatch(self.name) is None:
            raise ValueError(f"invalid specialization profile name: {self.name!r}")
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
        if not isinstance(value, Mapping) or set(value) != {"name", "arguments"}:
            raise ValueError("profile must contain exactly name and arguments")
        return cls(name=value["name"], arguments=value["arguments"])  # type: ignore[arg-type]

    def to_manifest(self) -> dict[str, object]:
        return {"name": self.name, "arguments": dict(self.arguments)}


@dataclass(frozen=True, slots=True)
class BuildReceipt:
    qualified_name: str
    profile: str
    specialization: Mapping[str, Scalar]
    declaration_source: str
    spec_sha256: str
    kernel_spec_digest: str
    forward_symbol: str
    target: str
    output: str
    artifact_sha256: str
    compiler: str
    compiler_version: str

    def to_manifest(self) -> dict[str, object]:
        return {
            "artifact_sha256": self.artifact_sha256,
            "compiler": self.compiler,
            "compiler_version": self.compiler_version,
            "declaration_source": self.declaration_source,
            "forward_symbol": self.forward_symbol,
            "kernel_spec_digest": self.kernel_spec_digest,
            "output": self.output,
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
    if not all(isinstance(key, str) for key in profiles):
        raise ValueError("specialization profile keys must be qualified operator strings")
    expected = {spec.qualified_name for spec in specs}
    actual = set(profiles)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ValueError(
            f"specialization profile inventory mismatch; missing={missing}, extra={extra}"
        )
    normalized: dict[str, tuple[SpecializationProfile, ...]] = {}
    for qualified_name in sorted(expected):
        values = profiles[qualified_name]
        if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
            raise ValueError(f"{qualified_name}: profiles must be a bounded sequence")
        if not 1 <= len(values) <= _MAX_PROFILES_PER_OPERATOR:
            raise ValueError(
                f"{qualified_name}: requires 1-{_MAX_PROFILES_PER_OPERATOR} "
                "specialization profiles"
            )
        parsed = tuple(
            sorted(
                (SpecializationProfile.from_value(value) for value in values),
                key=lambda item: item.name,
            )
        )
        names = [profile.name for profile in parsed]
        if len(set(names)) != len(names):
            raise ValueError(f"{qualified_name}: duplicate specialization profile name")
        normalized[qualified_name] = parsed
    return normalized


def _require_supported_receipt_contract(specs: Sequence[KernelSpec]) -> None:
    """Reject contracts that the current forward-only receipt cannot represent."""

    for spec in specs:
        if spec.forward.program_group is not None:
            raise RuntimeError(
                f"{spec.qualified_name}: current receipt schema v2 cannot represent a "
                "forward ProgramGroupSpec; program-group compilation requires the newer "
                "program-group receipt/bridge implementation"
            )
        if spec.backward is not None and spec.backward.program_group is not None:
            raise RuntimeError(
                f"{spec.qualified_name}: current receipt schema v2 cannot represent a "
                "backward ProgramGroupSpec; program-group compilation requires the newer "
                "program-group receipt/bridge implementation"
            )
        if spec.backward is not None:
            raise RuntimeError(
                f"{spec.qualified_name}: current receipt schema v2 cannot represent a "
                "backward provider; compilation requires atomic forward/backward co-build "
                "receipts and the newer co-build receipt/bridge implementation"
            )


def _resolve_builder(spec: KernelSpec, kernels_root: Path):
    builder_identity = spec.forward.builder
    if builder_identity.count(":") != 1:
        raise RuntimeError(f"{spec.qualified_name}: forward builder is not module:function")
    module_name, function_name = builder_identity.split(":", 1)
    expected_module = f"kernels.{spec.family}.{spec.name}.tilelang"
    if module_name != expected_module:
        raise RuntimeError(
            f"{spec.qualified_name}: forward builder module must be {expected_module}"
        )

    declared_file = kernels_root / spec.family / spec.name / "tilelang.py"
    current = kernels_root
    for component in (spec.family, spec.name, "tilelang.py"):
        current = current / component
        if current.is_symlink():
            raise RuntimeError(
                f"{spec.qualified_name}: operation-local TileLang builder must not be a symlink"
            )
    try:
        declared_file = declared_file.resolve(strict=True)
    except (FileNotFoundError, RuntimeError) as exc:
        raise RuntimeError(
            f"{spec.qualified_name}: operation-local TileLang builder source does not exist"
        ) from exc
    if not declared_file.is_file():
        raise RuntimeError(
            f"{spec.qualified_name}: operation-local TileLang builder source is not a file"
        )

    module = importlib.import_module(module_name)
    module_file = getattr(module, "__file__", None)
    if module_file is None or Path(module_file).resolve(strict=True) != declared_file:
        raise RuntimeError(
            f"{spec.qualified_name}: imported builder does not match operation-local tilelang.py"
        )
    builder = getattr(module, function_name, None)
    if not callable(builder):
        raise RuntimeError(
            f"{spec.qualified_name}: declared forward builder {function_name!r} is not callable"
        )
    return builder


def _compiled_source(compiled: object, program: object, qualified_name: str) -> bytes:
    for candidate in (compiled, program):
        getter = getattr(candidate, "get_kernel_source", None)
        if callable(getter):
            value = getter()
            if isinstance(value, str) and value.strip():
                return value.encode("utf-8")
            if isinstance(value, bytes) and value.strip():
                return value
    if isinstance(compiled, str) and compiled.strip():
        return compiled.encode("utf-8")
    if isinstance(compiled, bytes) and compiled.strip():
        return compiled
    raise RuntimeError(
        f"{qualified_name}: TileLang compile completed without a nonempty generated source artifact"
    )


def _atomic_write(path: Path, content: bytes) -> None:
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
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
) -> list[BuildReceipt]:
    """Compile explicit, bounded specializations in a trusted offline build."""

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

    discovered = discover_specs(root.parent, source_files)
    specs = registry(discovered)
    _require_supported_receipt_contract(specs)
    declarations: dict[str, DiscoveredKernelSpec] = {
        entry.qualified_name: entry for entry in discovered
    }
    normalized_profiles = _normalize_profiles(specs, profiles)
    compiler_version = "not-invoked"
    compiled_outputs: list[tuple[str, bytes, BuildReceipt]] = []
    if specs:
        try:
            tilelang_module = importlib.import_module("tilelang")
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "TileLang is required for offline native kernel compilation; "
                "use the pinned build toolchain"
            ) from exc
        compiler_version_value = getattr(tilelang_module, "__version__", None)
        if not isinstance(compiler_version_value, str) or not compiler_version_value:
            raise RuntimeError("TileLang compiler must expose a nonempty version identity")
        compiler_version = compiler_version_value

    for spec in specs:
        builder = _resolve_builder(spec, root.parent)
        for profile in normalized_profiles[spec.qualified_name]:
            program = builder(target=target, **dict(profile.arguments))
            compile_method = getattr(program, "compile", None)
            if not callable(compile_method):
                raise RuntimeError(
                    f"{spec.qualified_name}/{profile.name}: builder did not return "
                    "a compilable TileLang object"
                )
            compiled = compile_method()
            artifact = _compiled_source(compiled, program, spec.qualified_name)
            artifact_name = f"{spec.name}.{profile.name}.{target}.tilelang-source"
            artifact_digest = "sha256:" + hashlib.sha256(artifact).hexdigest()
            receipt = BuildReceipt(
                qualified_name=spec.qualified_name,
                profile=profile.name,
                specialization=profile.arguments,
                declaration_source=spec.source,
                spec_sha256=declarations[spec.qualified_name].declaration_sha256,
                kernel_spec_digest=spec.digest,
                forward_symbol=spec.forward.symbol,
                target=target,
                output=artifact_name,
                artifact_sha256=artifact_digest,
                compiler="tilelang",
                compiler_version=compiler_version,
            )
            compiled_outputs.append((artifact_name, artifact, receipt))

    output.mkdir(parents=True, exist_ok=True)
    receipts = [receipt for _, _, receipt in compiled_outputs]
    for artifact_name, artifact, _ in compiled_outputs:
        _atomic_write(output / artifact_name, artifact)
    receipt_document = {
        "compiler": {"id": "tilelang", "version": compiler_version},
        "receipts": [receipt.to_manifest() for receipt in receipts],
        "schema_version": 2,
        "target": target,
    }
    _atomic_write(
        output / "build_receipts.json",
        (json.dumps(receipt_document, sort_keys=True, indent=2) + "\n").encode("utf-8"),
    )
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
