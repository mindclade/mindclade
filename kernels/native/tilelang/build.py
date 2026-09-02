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
import subprocess
import tempfile
from types import MappingProxyType
from typing import Any, Protocol

from kernels.api import (
    ImplementationSpec,
    KernelSpec,
    ProgramArtifactBoundary,
    ProgramBindingSource,
    ProgramEntryABI,
    ProgramNodeSpec,
    ProgramParameterKind,
    ScalarABIType,
    WorkspaceAccess,
    content_digest,
)
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
_PINNED_TILELANG_VERSION = "0.1.13"
_REQUIRED_REGISTRY_GENERATOR_VERSION = 8
_PINNED_CUDA_TARGETS = {
    "cuda-sm90a": "sm_90a",
    "cuda-sm100a": "sm_100a",
}
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_HOST_CALL = re.compile(
    r'extern\s+"C"\s+TL_EXPORT\s+int\s+call\s*\((?P<parameters>.*?)\)\s*\{',
    re.DOTALL,
)

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
    specialization_digest: str
    implementation: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or _PROFILE_NAME.fullmatch(self.name) is None:
            raise ValueError(f"invalid specialization profile name: {self.name!r}")
        if self.implementation is not None and (
            not isinstance(self.implementation, str)
            or _IMPLEMENTATION_ID.fullmatch(self.implementation) is None
        ):
            raise ValueError("profile implementation must be a canonical name@version identity")
        if (
            not isinstance(self.specialization_digest, str)
            or _DIGEST.fullmatch(self.specialization_digest) is None
        ):
            raise ValueError(
                "profile specialization_digest must be the canonical "
                "SpecializationSpec sha256 digest"
            )
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
        if set(value) not in (
            {"name", "arguments", "specialization_digest"},
            {"name", "arguments", "specialization_digest", "implementation"},
        ):
            raise ValueError(
                "profile must contain name, arguments, specialization_digest, "
                "and optional implementation"
            )
        return cls(
            name=value["name"],  # type: ignore[arg-type]
            arguments=value["arguments"],  # type: ignore[arg-type]
            specialization_digest=value["specialization_digest"],  # type: ignore[arg-type]
            implementation=value.get("implementation"),  # type: ignore[arg-type]
        )

    def to_manifest(self) -> dict[str, object]:
        return {
            "arguments": dict(self.arguments),
            "implementation": self.implementation,
            "name": self.name,
            "specialization_digest": self.specialization_digest,
        }


@dataclass(frozen=True, slots=True)
class DsoCompileAction:
    qualified_name: str
    phase: str
    node: str
    builder: str
    symbol: str
    target: str
    profile: str
    specialization: Mapping[str, Scalar]
    specialization_digest: str
    selectors: Mapping[str, str]
    implementation: str | None
    kernel_spec_digest: str
    implementation_digest: str
    capability_envelope_digest: str
    program_node: ProgramNodeSpec | None = None

    def __post_init__(self) -> None:
        if self.phase not in {"forward", "backward"}:
            raise ValueError("DSO action phase must be forward or backward")
        if _SYMBOL.fullmatch(self.symbol) is None:
            raise ValueError("DSO action symbol is invalid")
        for label, value in (
            ("kernel spec", self.kernel_spec_digest),
            ("implementation", self.implementation_digest),
            ("capability envelope", self.capability_envelope_digest),
            ("specialization", self.specialization_digest),
        ):
            if _DIGEST.fullmatch(value) is None:
                raise ValueError(f"DSO action {label} digest is invalid")
        object.__setattr__(self, "specialization", MappingProxyType(dict(self.specialization)))
        normalized_selectors: dict[str, str] = {}
        for key, value in sorted(self.selectors.items()):
            if _PARAMETER_NAME.fullmatch(key) is None or _STRING_VALUE.fullmatch(value) is None:
                raise ValueError("DSO action selector projection is invalid")
            normalized_selectors[key] = value
        object.__setattr__(self, "selectors", MappingProxyType(normalized_selectors))

    def to_manifest(self) -> dict[str, object]:
        value: dict[str, object] = {
            "builder": self.builder,
            "implementation": self.implementation,
            "implementation_digest": self.implementation_digest,
            "capability_envelope_digest": self.capability_envelope_digest,
            "kernel_spec_digest": self.kernel_spec_digest,
            "node": self.node,
            "phase": self.phase,
            "profile": self.profile,
            "qualified_name": self.qualified_name,
            "selectors": dict(self.selectors),
            "specialization": dict(self.specialization),
            "specialization_digest": self.specialization_digest,
            "symbol": self.symbol,
            "target": self.target,
        }
        if self.program_node is not None:
            value["callable_node"] = {
                "adapter_symbol": self.program_node.symbol,
                "artifact_boundary": self.program_node.artifact_boundary.value,
                "bindings": [
                    {
                        "parameter": binding.parameter,
                        "source": binding.source.value,
                        "source_name": binding.source_name,
                    }
                    for binding in self.program_node.bindings
                ],
                "entry_abi": self.program_node.entry_abi.value,
                "entry_symbol": self.program_node.entry_symbol,
                "parameters": [
                    {
                        "access": parameter.access.value,
                        "kind": parameter.kind.value,
                        "name": parameter.name,
                        "optional": parameter.optional,
                        "position": parameter.position,
                        "scalar_type": (
                            parameter.scalar_type.value
                            if parameter.scalar_type is not None
                            else None
                        ),
                    }
                    for parameter in self.program_node.parameters
                ],
                "return_abi": self.program_node.return_abi.value,
            }
        return value

    @property
    def digest(self) -> str:
        return _digest(self.to_manifest())


@dataclass(frozen=True, slots=True)
class CompiledArtifact:
    dso: bytes
    exported_symbols: tuple[str, ...]
    source_sha256: str
    adapter_source_sha256: str
    call_signature_sha256: str
    compile_command: tuple[str, ...]
    link_command: tuple[str, ...]
    toolchain_closure_digest: str
    adapter_symbol: str
    soname: str
    object_format: str = "elf_shared_object"

    def __post_init__(self) -> None:
        if not isinstance(self.dso, bytes) or not self.dso:
            raise RuntimeError("compiler adapter returned an empty node DSO")
        if self.object_format != "elf_shared_object":
            raise RuntimeError("compiler adapter must return an ELF shared object")
        if (
            not isinstance(self.exported_symbols, tuple)
            or not self.exported_symbols
            or any(_SYMBOL.fullmatch(value) is None for value in self.exported_symbols)
            or tuple(sorted(set(self.exported_symbols))) != self.exported_symbols
        ):
            raise RuntimeError("compiler adapter returned an invalid exported-symbol inventory")
        for label, value in (
            ("source", self.source_sha256),
            ("adapter source", self.adapter_source_sha256),
            ("call signature", self.call_signature_sha256),
            ("toolchain closure", self.toolchain_closure_digest),
        ):
            if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
                raise RuntimeError(f"compiler adapter {label} digest is invalid")
        if not self.compile_command or not self.link_command:
            raise RuntimeError("compiler adapter commands must be non-empty")
        if not re.fullmatch(r"libmindclade_node_[0-9a-f]{64}\.so", self.soname):
            raise RuntimeError("compiler adapter SONAME is invalid")
        if _SYMBOL.fullmatch(self.adapter_symbol) is None:
            raise RuntimeError("compiler adapter resolved symbol is invalid")


class OfflineCompilerAdapter(Protocol):
    compiler_id: str
    compiler_version: str

    def compile(self, program: object, action: DsoCompileAction) -> CompiledArtifact: ...


class TileLangCompatibilityAdapter:
    """Pinned TileLang 0.1.13 CUDA host-call to node-DSO compiler.

    Each node is isolated in one content-addressed DSO.  TileLang's fixed
    ``call``/``init``/``get_last_error`` symbols remain hidden inside that DSO;
    only the unique Mindclade callable-node adapter has default visibility.
    """

    compiler_id = "tilelang"

    def __init__(
        self,
        tilelang_module: object,
        *,
        nvcc: Path,
        nvcc_sha256: str,
        nvcc_version: str,
        toolchain_closure_digest: str,
        node_abi_header: Path,
        nm: Path,
        readelf: Path,
    ) -> None:
        version = getattr(tilelang_module, "__version__", None)
        if version != _PINNED_TILELANG_VERSION:
            raise RuntimeError(
                f"TileLang {_PINNED_TILELANG_VERSION} is required, found {version!r}"
            )
        self.compiler_version = version
        self._tilelang = tilelang_module
        self._nvcc = _validated_tool(nvcc, "nvcc")
        self._nm = _validated_tool(nm, "nm")
        self._readelf = _validated_tool(readelf, "readelf")
        self._header = _validated_file(node_abi_header, "node launch ABI header")
        if self._header.name != "node_launch_abi.h":
            raise RuntimeError("node launch ABI header must be node_launch_abi.h")
        if not isinstance(nvcc_sha256, str) or _DIGEST.fullmatch(nvcc_sha256) is None:
            raise RuntimeError("nvcc digest must be sha256:<64 lowercase hex>")
        actual_nvcc_digest = "sha256:" + hashlib.sha256(self._nvcc.read_bytes()).hexdigest()
        if actual_nvcc_digest != nvcc_sha256:
            raise RuntimeError("nvcc digest does not match the pinned toolchain")
        if not isinstance(nvcc_version, str) or not nvcc_version.strip():
            raise RuntimeError("pinned nvcc version must be non-empty")
        if (
            not isinstance(toolchain_closure_digest, str)
            or _DIGEST.fullmatch(toolchain_closure_digest) is None
        ):
            raise RuntimeError("toolchain closure digest must be sha256:<64 lowercase hex>")
        observed_version = _run_checked((str(self._nvcc), "--version"), "nvcc version").strip()
        if observed_version != nvcc_version.strip():
            raise RuntimeError("nvcc version output does not match the pinned toolchain")
        self._nvcc_sha256 = nvcc_sha256
        self._nvcc_version = observed_version
        self._declared_toolchain_closure_digest = toolchain_closure_digest

    def compile(self, program: object, action: DsoCompileAction) -> CompiledArtifact:
        node = action.program_node
        if node is None:
            raise RuntimeError("pinned node-DSO compilation requires ProgramNodeSpec metadata")
        if node.entry_abi is not ProgramEntryABI.TILELANG_0_1_13_HOST_CALL:
            raise RuntimeError("unsupported TileLang raw entry ABI")
        if node.artifact_boundary is not ProgramArtifactBoundary.NODE_CONTENT_ADDRESSED_DSO:
            raise RuntimeError("TileLang host call requires a node-content-addressed DSO")
        if action.target not in _PINNED_CUDA_TARGETS:
            raise RuntimeError(
                f"unsupported pinned CUDA target {action.target!r}; expected one of "
                f"{sorted(_PINNED_CUDA_TARGETS)}"
            )
        source = _compiled_host_source(program, action.qualified_name)
        call_signature, raw_parameters = _parse_host_call(source, node.entry_symbol)
        compile_command = _logical_compile_command(
            target=action.target,
            header_dir=self._header.parent,
        )
        toolchain_closure_digest = _digest(
            {
                "node_abi_header": "sha256:"
                + hashlib.sha256(self._header.read_bytes()).hexdigest(),
                "declared_toolchain_closure": self._declared_toolchain_closure_digest,
                "nvcc": self._nvcc_sha256,
                "nvcc_version": self._nvcc_version,
                "target": action.target,
                "tilelang": self.compiler_version,
            }
        )
        artifact_identity = _digest(
            {
                "action": action.to_manifest(),
                "adapter_template": 2,
                "call_signature_sha256": "sha256:"
                + hashlib.sha256(call_signature.encode("utf-8")).hexdigest(),
                "source_sha256": "sha256:"
                + hashlib.sha256(source.encode("utf-8")).hexdigest(),
                "toolchain_closure_digest": toolchain_closure_digest,
            }
        )
        identity_hex = artifact_identity.removeprefix("sha256:")
        adapter_symbol = f"{node.symbol}_{identity_hex}"
        if _SYMBOL.fullmatch(adapter_symbol) is None:
            raise RuntimeError("resolved node adapter symbol exceeds the C ABI bound")
        soname = f"libmindclade_node_{identity_hex}.so"
        link_command = _logical_link_command(soname)
        adapter_source = _render_node_adapter(
            node,
            raw_parameters,
            adapter_symbol,
            action.specialization_digest,
        )
        combined_source = source.rstrip() + "\n\n" + adapter_source
        with tempfile.TemporaryDirectory(prefix="mindclade-node-dso-") as directory:
            build_dir = Path(directory)
            source_path = build_dir / "node.cu"
            object_path = build_dir / "node.o"
            dso_path = build_dir / soname
            source_path.write_text(combined_source, encoding="utf-8", newline="\n")
            actual_compile = tuple(
                str(source_path) if value == "$SOURCE" else
                str(object_path) if value == "$OBJECT" else
                str(self._header.parent) if value == "$ABI_INCLUDE" else
                str(self._nvcc) if value == "$NVCC" else value
                for value in compile_command
            )
            actual_link = tuple(
                str(object_path) if value == "$OBJECT" else
                str(dso_path) if value == "$DSO" else
                str(self._nvcc) if value == "$NVCC" else value
                for value in link_command
            )
            _run_checked(actual_compile, "node CUDA compile")
            _run_checked(actual_link, "node DSO link")
            exported = _read_exported_symbols(self._nm, dso_path)
            if exported != (adapter_symbol,):
                raise RuntimeError(
                    f"node DSO must export exactly {adapter_symbol!r}, got {exported!r}"
                )
            observed_soname = _read_soname(self._readelf, dso_path)
            if observed_soname != soname:
                raise RuntimeError(
                    f"node DSO SONAME mismatch: expected {soname!r}, got {observed_soname!r}"
                )
            dso = dso_path.read_bytes()
        return CompiledArtifact(
            dso=dso,
            exported_symbols=exported,
            source_sha256="sha256:" + hashlib.sha256(source.encode("utf-8")).hexdigest(),
            adapter_source_sha256="sha256:"
            + hashlib.sha256(adapter_source.encode("utf-8")).hexdigest(),
            call_signature_sha256="sha256:"
            + hashlib.sha256(call_signature.encode("utf-8")).hexdigest(),
            compile_command=compile_command,
            link_command=link_command,
            toolchain_closure_digest=toolchain_closure_digest,
            adapter_symbol=adapter_symbol,
            soname=soname,
        )


@dataclass(frozen=True, slots=True)
class _RawCallParameter:
    name: str
    c_type: str


def _validated_file(path: Path, label: str) -> Path:
    if not isinstance(path, Path) or not path.is_absolute():
        raise RuntimeError(f"{label} path must be absolute")
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"{label} must be an existing non-symlink regular file")
    return path


def _validated_tool(path: Path, label: str) -> Path:
    value = _validated_file(path, label)
    if not os.access(value, os.X_OK):
        raise RuntimeError(f"{label} must be executable")
    return value


def _run_checked(command: Sequence[str], label: str) -> str:
    try:
        completed = subprocess.run(
            tuple(command),
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env={
                "HOME": "/homeless-shelter",
                "LANG": "C",
                "LC_ALL": "C",
                "PATH": os.environ.get("PATH", ""),
                "SOURCE_DATE_EPOCH": "0",
                "TZ": "UTC",
            },
        )
    except OSError as exc:
        raise RuntimeError(f"{label} could not execute: {exc}") from exc
    if completed.returncode != 0:
        raise RuntimeError(
            f"{label} failed with exit {completed.returncode}: {completed.stdout.strip()}"
        )
    return completed.stdout


def _compiled_host_source(program: object, qualified_name: str) -> str:
    candidates = (
        getattr(getattr(program, "adapter", None), "lib_code", None),
        getattr(program, "lib_code", None),
    )
    for value in candidates:
        if isinstance(value, str) and value.strip() and _HOST_CALL.search(value):
            return value.replace("\r\n", "\n")
    raise RuntimeError(
        f"{qualified_name}: operation builder must return a pinned TileLang 0.1.13 "
        "compiled CUDA object exposing adapter.lib_code with the observed host call; "
        "source-only PrimFunc and runtime compilation are prohibited"
    )


def _parse_host_call(
    source: str, expected_symbol: str
) -> tuple[str, tuple[_RawCallParameter, ...]]:
    if expected_symbol != "call":
        raise RuntimeError("TileLang 0.1.13 host-call entry symbol must be 'call'")
    matches = tuple(_HOST_CALL.finditer(source))
    if len(matches) != 1:
        raise RuntimeError("TileLang host source must define exactly one extern C call entry")
    body = matches[0].group("parameters")
    declarations = tuple(
        re.sub(r"\s+", " ", value.strip())
        for value in body.split(",")
        if value.strip()
    )
    parsed: list[_RawCallParameter] = []
    for declaration in declarations:
        without_default = declaration.split("=", 1)[0].strip()
        match = re.fullmatch(
            r"(?P<type>.+?)\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)",
            without_default,
        )
        if match is None:
            raise RuntimeError(
                f"unsupported TileLang host-call parameter declaration: {declaration!r}"
            )
        parsed.append(
            _RawCallParameter(
                name=match.group("name"),
                c_type=re.sub(r"\s+", " ", match.group("type").strip()),
            )
        )
    signature = "extern C int call(" + ",".join(
        f"{value.c_type} {value.name}" for value in parsed
    ) + ")"
    return signature, tuple(parsed)


def _render_node_adapter(
    node: ProgramNodeSpec,
    raw_parameters: tuple[_RawCallParameter, ...],
    adapter_symbol: str,
    specialization_digest: str,
) -> str:
    if _DIGEST.fullmatch(specialization_digest) is None:
        raise RuntimeError("node adapter requires a canonical SpecializationSpec digest")
    expected_digest = bytes.fromhex(specialization_digest.removeprefix("sha256:"))
    if len(expected_digest) != 32:
        raise RuntimeError("node adapter specialization digest must decode to 32 bytes")
    bindings = {binding.parameter: binding for binding in node.bindings}
    passed = tuple(
        parameter
        for parameter in node.parameters
        if bindings[parameter.name].source is not ProgramBindingSource.GRADIENT_REQUEST
    )
    raw_names = tuple(value.name for value in raw_parameters)
    passed_names = tuple(value.name for value in passed)
    if raw_names != passed_names:
        raise RuntimeError(
            "compiler-observed TileLang call parameters differ from ProgramNodeSpec: "
            f"observed={raw_names!r}, declared={passed_names!r}"
        )
    raw_by_name = {value.name: value for value in raw_parameters}
    request_parameters = tuple(
        parameter
        for parameter in node.parameters
        if bindings[parameter.name].source is ProgramBindingSource.GRADIENT_REQUEST
    )
    if len(request_parameters) > 1:
        raise RuntimeError(
            "one physical TileLang node may bind at most one independent gradient request"
        )

    access = {
        WorkspaceAccess.READ: "MINDCLADE_NODE_ACCESS_READ_V1",
        WorkspaceAccess.WRITE: "MINDCLADE_NODE_ACCESS_WRITE_V1",
        WorkspaceAccess.READ_WRITE: "MINDCLADE_NODE_ACCESS_READ_WRITE_V1",
    }
    kind = {
        ProgramParameterKind.TENSOR: "MINDCLADE_NODE_VALUE_TENSOR_V1",
        ProgramParameterKind.SCALAR: None,
        ProgramParameterKind.STREAM: "MINDCLADE_NODE_VALUE_STREAM_V1",
    }
    scalar_kind = {
        ScalarABIType.BOOL: "MINDCLADE_NODE_VALUE_BOOL_V1",
        ScalarABIType.INT64: "MINDCLADE_NODE_VALUE_INT64_V1",
        ScalarABIType.FLOAT64: "MINDCLADE_NODE_VALUE_FLOAT64_V1",
    }
    lines = [
        '#include "node_launch_abi.h"',
        "",
        '#if defined(__GNUC__) || defined(__clang__)',
        '#define MINDCLADE_NODE_EXPORT __attribute__((visibility("default")))',
        "#else",
        "#define MINDCLADE_NODE_EXPORT",
        "#endif",
        "",
        "namespace {",
        "constexpr uint8_t kExpectedSpecializationDigest[32] = {",
        "    " + ", ".join(f"UINT8_C(0x{value:02x})" for value in expected_digest),
        "};",
        "}  // namespace",
        "",
        f'extern "C" MINDCLADE_NODE_EXPORT int32_t {adapter_symbol}(',
        "    const MindcladeNodeLaunchV1* launch) noexcept {",
        "  if (launch == nullptr ||",
        "      launch->abi_version != MINDCLADE_NODE_LAUNCH_ABI_VERSION) {",
        "    return MINDCLADE_NODE_STATUS_INVALID_ABI_V1;",
        "  }",
        "  uint8_t specialization_mismatch = UINT8_C(0);",
        "  for (uint32_t index = UINT32_C(0); index < UINT32_C(32); ++index) {",
        "    specialization_mismatch |= static_cast<uint8_t>(",
        "        launch->specialization_digest[index] ^ kExpectedSpecializationDigest[index]);",
        "  }",
        "  if (specialization_mismatch != UINT8_C(0)) {",
        "    return MINDCLADE_NODE_STATUS_INVALID_PARAMETER_V1;",
        "  }",
        "  if (launch->parameters == nullptr) {",
        "    return MINDCLADE_NODE_STATUS_INVALID_ABI_V1;",
        "  }",
        f"  if (launch->parameter_count != UINT32_C({len(node.parameters)})) {{",
        "    return MINDCLADE_NODE_STATUS_INVALID_PARAMETER_COUNT_V1;",
        "  }",
    ]
    for parameter in node.parameters:
        expected_kind = (
            scalar_kind[parameter.scalar_type]
            if parameter.kind is ProgramParameterKind.SCALAR
            else kind[parameter.kind]
        )
        lines.extend(
            (
                f"  const MindcladeNodeValueV1& value_{parameter.position} = "
                f"launch->parameters[{parameter.position}];",
                f"  if (value_{parameter.position}.kind != {expected_kind} ||",
                f"      value_{parameter.position}.access != {access[parameter.access]}) {{",
                "    return MINDCLADE_NODE_STATUS_INVALID_PARAMETER_V1;",
                "  }",
            )
        )
    if request_parameters:
        request = request_parameters[0]
        lines.extend(
            (
                f"  if (value_{request.position}.payload.boolean_value == UINT64_C(0)) {{",
                "    return MINDCLADE_NODE_STATUS_SUCCESS_V1;",
                "  }",
            )
        )
    for parameter in passed:
        if parameter.kind is ProgramParameterKind.TENSOR:
            present = f"value_{parameter.position}.payload.tensor.flags & MINDCLADE_NODE_TENSOR_PRESENT_V1"
            lines.extend(
                (
                    f"  if (({present}) == 0 || value_{parameter.position}.payload.tensor.data == nullptr) {{",
                    "    return MINDCLADE_NODE_STATUS_INVALID_PARAMETER_V1;",
                    "  }",
                )
            )
    call_arguments: list[str] = []
    for parameter in passed:
        raw = raw_by_name[parameter.name]
        if parameter.kind is ProgramParameterKind.TENSOR:
            c_type = raw.c_type.replace("__restrict__", "").strip()
            call_arguments.append(
                f"reinterpret_cast<{c_type}>(value_{parameter.position}.payload.tensor.data)"
            )
        elif parameter.kind is ProgramParameterKind.STREAM:
            call_arguments.append(
                f"reinterpret_cast<cudaStream_t>(value_{parameter.position}.payload.stream)"
            )
        elif parameter.scalar_type is ScalarABIType.BOOL:
            call_arguments.append(
                f"static_cast<{raw.c_type}>(value_{parameter.position}.payload.boolean_value != 0)"
            )
        elif parameter.scalar_type is ScalarABIType.INT64:
            call_arguments.append(
                f"static_cast<{raw.c_type}>(value_{parameter.position}.payload.int64_value)"
            )
        else:
            call_arguments.append(
                f"static_cast<{raw.c_type}>(value_{parameter.position}.payload.float64_value)"
            )
    lines.extend(
        (
            "  const int entry_status = call(",
            "      " + ",\n      ".join(call_arguments) + ");",
            "  return entry_status == 0 ? MINDCLADE_NODE_STATUS_SUCCESS_V1",
            "                           : MINDCLADE_NODE_STATUS_ENTRY_FAILURE_V1;",
            "}",
            "",
        )
    )
    return "\n".join(lines)


def _logical_compile_command(*, target: str, header_dir: Path) -> tuple[str, ...]:
    del header_dir
    architecture = _PINNED_CUDA_TARGETS[target]
    return (
        "$NVCC",
        "-std=c++20",
        "-lineinfo",
        "-gencode",
        f"arch=compute_{architecture.removeprefix('sm_')},code={architecture}",
        "--compiler-options=-fPIC,-fvisibility=hidden",
        "-I",
        "$ABI_INCLUDE",
        "-c",
        "$SOURCE",
        "-o",
        "$OBJECT",
    )


def _logical_link_command(soname: str) -> tuple[str, ...]:
    return (
        "$NVCC",
        "-shared",
        "$OBJECT",
        "-lcuda",
        "-Xlinker",
        f"-soname={soname}",
        "-Xlinker",
        "--build-id=none",
        "-o",
        "$DSO",
    )


def _read_exported_symbols(nm: Path, dso: Path) -> tuple[str, ...]:
    output = _run_checked(
        (str(nm), "-D", "--defined-only", "--format=posix", str(dso)),
        "node DSO symbol inspection",
    )
    symbols = tuple(
        sorted(
            set(
                line.split()[0]
                for line in output.splitlines()
                if line.strip() and line.split()
            )
        )
    )
    if any(_SYMBOL.fullmatch(value) is None for value in symbols):
        raise RuntimeError("node DSO exposes a noncanonical symbol")
    return symbols


def _read_soname(readelf: Path, dso: Path) -> str:
    output = _run_checked((str(readelf), "-d", str(dso)), "node DSO SONAME inspection")
    values = re.findall(r"\(SONAME\).*?\[([^]]+)\]", output)
    if len(values) != 1:
        raise RuntimeError("node DSO must contain exactly one SONAME")
    return values[0]


def _required_environment(name: str) -> str:
    value = os.environ.get(name)
    if not isinstance(value, str) or not value:
        raise RuntimeError(
            f"offline TileLang compilation requires declared environment input {name}"
        )
    return value


def _required_environment_path(name: str) -> Path:
    value = Path(_required_environment(name))
    if not value.is_absolute():
        raise RuntimeError(f"{name} must be an absolute declared toolchain path")
    return value


@dataclass(frozen=True, slots=True)
class CompiledUnitReceipt:
    phase: str
    node: str
    builder: str
    adapter_symbol: str
    resolved_adapter_symbol: str
    entry_symbol: str
    entry_abi: str
    artifact_boundary: str
    action_digest: str
    specialization_digest: str
    artifact: str
    artifact_sha256: str
    source_sha256: str
    adapter_source_sha256: str
    call_signature_sha256: str
    compile_command: tuple[str, ...]
    link_command: tuple[str, ...]
    toolchain_closure_digest: str
    soname: str
    exported_symbols: tuple[str, ...]
    object_format: str

    def to_manifest(self) -> dict[str, object]:
        return {
            "action_digest": self.action_digest,
            "artifact": self.artifact,
            "artifact_sha256": self.artifact_sha256,
            "artifact_boundary": self.artifact_boundary,
            "adapter_source_sha256": self.adapter_source_sha256,
            "adapter_symbol": self.adapter_symbol,
            "builder": self.builder,
            "call_signature_sha256": self.call_signature_sha256,
            "compile_command": list(self.compile_command),
            "entry_abi": self.entry_abi,
            "entry_symbol": self.entry_symbol,
            "exported_symbols": list(self.exported_symbols),
            "link_command": list(self.link_command),
            "node": self.node,
            "object_format": self.object_format,
            "phase": self.phase,
            "resolved_adapter_symbol": self.resolved_adapter_symbol,
            "soname": self.soname,
            "source_sha256": self.source_sha256,
            "specialization_digest": self.specialization_digest,
            "toolchain_closure_digest": self.toolchain_closure_digest,
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
    specialization_digest: str
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
    status: str = "unqualified"

    def __post_init__(self) -> None:
        object.__setattr__(self, "specialization", MappingProxyType(dict(self.specialization)))
        if _DIGEST.fullmatch(self.specialization_digest) is None:
            raise ValueError("build receipt specialization digest is invalid")
        if self.backward is None and self.forward.phase != "forward":
            raise ValueError("build receipt has an invalid forward phase")
        if self.status != "unqualified":
            raise ValueError("offline compilation may emit only unqualified receipts")

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
            "specialization_digest": self.specialization_digest,
            "status": self.status,
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
    binary_digest: str,
) -> str:
    identity = "provider" if implementation is None else _implementation_identity(implementation)
    safe_identity = identity.replace("@", "_v")
    return (
        f"{spec.name}.{safe_identity}.{profile.name}.{phase}.{node}.{target}."
        f"{binary_digest.removeprefix('sha256:')}.so"
    )


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
    builder_target = "cuda" if target in _PINNED_CUDA_TARGETS else target
    if group is None:
        work = (("logical", provider.builder, provider.symbol, None),)
        execution_order = ("logical",)
        group_digest = None
        selector_values: dict[str, str] = {}
    else:
        logical_builder = _resolve_builder_identity(spec, provider.builder, kernels_root)
        descriptor = logical_builder(target=builder_target, **arguments)
        _validate_group_descriptor(descriptor, phase=phase, provider=provider)
        work = tuple(
            (node.name, node.builder, node.symbol, node) for node in group.nodes
        )
        execution_order = tuple(node.name for node in group.nodes)
        group_digest = group.digest
        selector_values = {}
        for selector in group.selector_bindings:
            raw_value = arguments.get(selector.provider_argument)
            if not isinstance(raw_value, bool):
                raise RuntimeError(
                    f"{spec.qualified_name}/{profile.name}/{phase}: selector argument "
                    f"{selector.provider_argument!r} must be an explicit bool profile value"
                )
            cases = dict(selector.cases)
            if raw_value not in cases:
                raise RuntimeError(
                    f"{spec.qualified_name}/{profile.name}/{phase}: selector argument "
                    f"{selector.provider_argument!r} has no declared case"
                )
            if selector.selector_key in selector_values:
                raise RuntimeError("program group selector keys must be unique")
            selector_values[selector.selector_key] = cases[raw_value]
    for node, builder_identity, symbol, program_node in work:
        builder = _resolve_builder_identity(spec, builder_identity, kernels_root)
        program = builder(target=builder_target, **arguments)
        action = DsoCompileAction(
            qualified_name=spec.qualified_name,
            phase=phase,
            node=node,
            builder=builder_identity,
            symbol=symbol,
            target=target,
            profile=profile.name,
            specialization=profile.arguments,
            specialization_digest=profile.specialization_digest,
            selectors=selector_values,
            implementation=(
                _implementation_identity(implementation)
                if implementation is not None
                else None
            ),
            kernel_spec_digest=spec.digest,
            implementation_digest=(
                implementation.digest
                if implementation is not None
                else content_digest([])
            ),
            capability_envelope_digest=(
                implementation.envelope.digest
                if implementation is not None
                else content_digest({"unqualified_provider": True})
            ),
            program_node=program_node,
        )
        artifact = adapter.compile(program, action)
        if artifact.exported_symbols != (artifact.adapter_symbol,):
            raise RuntimeError(
                f"{spec.qualified_name}/{profile.name}/{phase}/{node}: node DSO must "
                f"export exactly its resolved adapter symbol, got {artifact.exported_symbols!r}"
            )
        if program_node is not None and not artifact.adapter_symbol.startswith(symbol + "_"):
            raise RuntimeError("resolved node adapter symbol must extend the declared prefix")
        digest = "sha256:" + hashlib.sha256(artifact.dso).hexdigest()
        name = _artifact_name(
            spec, profile, phase, node, implementation, target, digest
        )
        outputs.append((name, artifact.dso))
        units.append(
            CompiledUnitReceipt(
                phase=phase,
                node=node,
                builder=builder_identity,
                adapter_symbol=symbol,
                resolved_adapter_symbol=artifact.adapter_symbol,
                entry_symbol=(program_node.entry_symbol if program_node is not None else ""),
                entry_abi=(
                    program_node.entry_abi.value if program_node is not None else "unmodeled"
                ),
                artifact_boundary=(
                    program_node.artifact_boundary.value
                    if program_node is not None
                    else "unmodeled"
                ),
                action_digest=action.digest,
                specialization_digest=action.specialization_digest,
                artifact=name,
                artifact_sha256=digest,
                source_sha256=artifact.source_sha256,
                adapter_source_sha256=artifact.adapter_source_sha256,
                call_signature_sha256=artifact.call_signature_sha256,
                compile_command=artifact.compile_command,
                link_command=artifact.link_command,
                toolchain_closure_digest=artifact.toolchain_closure_digest,
                soname=artifact.soname,
                exported_symbols=artifact.exported_symbols,
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
    """Compile bounded per-node DSOs and atomically emit receipt schema v4."""

    if GENERATOR_VERSION != _REQUIRED_REGISTRY_GENERATOR_VERSION:
        raise RuntimeError(
            "build receipt schema 4 requires native registry generator version 8"
        )

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
        compiler_adapter = TileLangCompatibilityAdapter(
            tilelang_module,
            nvcc=_required_environment_path("MINDCLADE_NVCC"),
            nvcc_sha256=_required_environment("MINDCLADE_NVCC_SHA256"),
            nvcc_version=_required_environment("MINDCLADE_NVCC_VERSION"),
            toolchain_closure_digest=_required_environment(
                "MINDCLADE_TOOLCHAIN_CLOSURE_DIGEST"
            ),
            node_abi_header=root / "stable_abi" / "node_launch_abi.h",
            nm=_required_environment_path("MINDCLADE_NM"),
            readelf=_required_environment_path("MINDCLADE_READELF"),
        )
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
                    specialization_digest=profile.specialization_digest,
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
        "qualification_status": "unqualified",
        "schema_version": 4,
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
