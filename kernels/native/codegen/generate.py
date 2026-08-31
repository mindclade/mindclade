"""Deterministic v3 native registration generation from canonical ``spec.py`` files."""

from __future__ import annotations

import argparse
from dataclasses import fields, is_dataclass
from enum import Enum
import json
from pathlib import Path
from typing import Any

from kernels.api import AutogradPolicy, Expr, content_digest
from kernels.native.codegen.discover import DiscoveredKernelSpec, discover_specs
from kernels.native.codegen.schema import ParsedSchema, parse_schema

GENERATOR_ID = "kernels.native.codegen.generate"
GENERATOR_VERSION = 3
SCHEMA_VERSION = 3

GENERATED_FILENAMES = (
    "native_ops.json",
    "registration.generated.cpp",
    "operation_registry.generated.cpp",
    "python_registration_generated.py",
    "native_ops.generated.cmake",
    "native_ops.generated.bzl",
)

DEFAULT_SPEC_SOURCES = (
    "pairformer/outer_product_mean/spec.py",
    "pairformer/pair_weighted_average/spec.py",
    "pairformer/transition/spec.py",
    "pairformer/triangle_attention/spec.py",
    "pairformer/triangle_multiplication/spec.py",
)


def _json_value(value: Any) -> Any:
    """Serialize contracts without losing expression node discriminators."""

    if isinstance(value, Expr):
        return value.to_data()
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {
            "type": type(value).__name__,
            **{field.name: _json_value(getattr(value, field.name)) for field in fields(value)},
        }
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_value(value[key]) for key in sorted(value, key=str)}
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"unsupported manifest value: {type(value).__name__}")


def _registration(
    namespace: str,
    schema: ParsedSchema,
    kind: str,
    implementation_symbol: str,
) -> dict[str, str]:
    return {
        "qualified_name": f"{namespace}::{schema.name}",
        "schema": schema.canonical,
        "kind": kind,
        "implementation_symbol": implementation_symbol,
    }


def _operator_record(item: DiscoveredKernelSpec) -> dict[str, Any]:
    spec = item.spec
    semantic = parse_schema(spec.operator_schema)
    forward = parse_schema(spec.forward.schema)
    registrations = [
        _registration(spec.namespace, semantic, "semantic", spec.forward.symbol),
        _registration(spec.namespace, forward, "forward", spec.forward.symbol),
    ]
    if spec.backward is not None:
        registrations.append(
            _registration(
                spec.namespace,
                parse_schema(spec.backward.schema),
                "backward",
                spec.backward.symbol,
            )
        )
    return {
        "name": spec.name,
        "qualified_name": spec.qualified_name,
        "namespace": spec.namespace,
        "family": spec.family,
        "source": spec.source,
        "spec_sha256": item.declaration_sha256,
        "kernel_spec_digest": spec.digest,
        "operator_schema": semantic.canonical,
        "facade_outputs": list(spec.facade_outputs),
        "fake": spec.fake,
        "forward": _json_value(spec.forward),
        "backward": _json_value(spec.backward),
        "autograd_policy": spec.autograd_policy.value,
        "composite": _json_value(spec.composite),
        "effects": _json_value(spec.effects),
        "launch": _json_value(spec.launch),
        "backend": spec.backend,
        "version": spec.version,
        "devices": list(spec.devices),
        "registrations": registrations,
    }


def _manifest(discovered: list[DiscoveredKernelSpec]) -> dict[str, Any]:
    operators = [_operator_record(item) for item in discovered]
    source_inventory = [
        {
            "source": record["source"],
            "spec_sha256": record["spec_sha256"],
            "kernel_spec_digest": record["kernel_spec_digest"],
        }
        for record in operators
    ]
    semantic_inventory = [
        {
            "qualified_name": record["qualified_name"],
            "kernel_spec_digest": record["kernel_spec_digest"],
        }
        for record in operators
    ]
    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generator": {"id": GENERATOR_ID, "version": GENERATOR_VERSION},
        "source_inventory_sha256": content_digest(source_inventory),
        "namespace": "mindclade",
        "registration_mode": "build_time_generated",
        "optimized_math_authority": "tilelang",
        "runtime_discovery": False,
        "request_time_compilation": False,
        "operators": operators,
        "semantic_digest": content_digest(semantic_inventory),
    }
    manifest["manifest_digest"] = content_digest(manifest)
    return manifest


def _render_manifest(discovered: list[DiscoveredKernelSpec]) -> str:
    return json.dumps(_manifest(discovered), indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def _render_schema_registration(discovered: list[DiscoveredKernelSpec]) -> str:
    schemas: list[str] = []
    for item in discovered:
        spec = item.spec
        schemas.extend((spec.operator_schema, spec.forward.schema))
        if spec.backward is not None:
            schemas.append(spec.backward.schema)
    lines = [
        f"// GENERATED FILE - DO NOT EDIT. Generator: {GENERATOR_ID}@{GENERATOR_VERSION}.",
        "#include <torch/csrc/stable/library.h>",
        "",
        "STABLE_TORCH_LIBRARY(mindclade, m) {",
    ]
    lines.extend(f"  m.def({json.dumps(parse_schema(schema).canonical)});" for schema in schemas)
    lines.extend(("}", ""))
    return "\n".join(lines)


def _cpp_invocation(schema: ParsedSchema, symbol: str) -> str:
    return f"{symbol}({', '.join(schema.argument_names)})"


def _cpp_wrapper(name: str, schema: ParsedSchema, symbol: str) -> list[str]:
    return [
        f"{schema.cpp_return_type} {name}({schema.cpp_parameters}) {{",
        f"  return {_cpp_invocation(schema, symbol)};",
        "}",
    ]


def _render_operation_registry(discovered: list[DiscoveredKernelSpec]) -> str:
    lines = [
        f"// GENERATED FILE - DO NOT EDIT. Generator: {GENERATOR_ID}@{GENERATOR_VERSION}.",
        "#include <cstdint>",
        "#include <torch/csrc/stable/library.h>",
        "#include <torch/csrc/stable/tensor.h>",
        "",
    ]
    declarations: dict[str, ParsedSchema] = {}
    for item in discovered:
        spec = item.spec
        declarations.setdefault(spec.forward.symbol, parse_schema(spec.forward.schema))
        if spec.backward is not None:
            declarations.setdefault(spec.backward.symbol, parse_schema(spec.backward.schema))
    for symbol, schema in declarations.items():
        lines.append(f'extern "C" {schema.cpp_return_type} {symbol}({schema.cpp_parameters});')

    lines.extend(("", "namespace mindclade::native::tilelang {"))
    implementations: list[tuple[str, str]] = []
    for item in discovered:
        spec = item.spec
        semantic = parse_schema(spec.operator_schema)
        forward = parse_schema(spec.forward.schema)
        semantic_wrapper = f"{spec.name}_semantic"
        forward_wrapper = f"{spec.name}_forward"
        lines.extend(_cpp_wrapper(semantic_wrapper, semantic, spec.forward.symbol))
        lines.extend(_cpp_wrapper(forward_wrapper, forward, spec.forward.symbol))
        implementations.extend(((semantic.name, semantic_wrapper), (forward.name, forward_wrapper)))
        if spec.backward is not None:
            backward = parse_schema(spec.backward.schema)
            backward_wrapper = f"{spec.name}_backward"
            lines.extend(_cpp_wrapper(backward_wrapper, backward, spec.backward.symbol))
            implementations.append((backward.name, backward_wrapper))
    lines.extend(("}  // namespace mindclade::native::tilelang", ""))
    lines.append("STABLE_TORCH_LIBRARY_IMPL(mindclade, CUDA, m) {")
    lines.extend(
        f'  m.impl("{operator}", TORCH_BOX(&mindclade::native::tilelang::{wrapper}));'
        for operator, wrapper in implementations
    )
    lines.extend(("}", ""))
    return "\n".join(lines)


def _split_identity(identity: str) -> tuple[str, str]:
    return tuple(identity.split(":", 1))  # type: ignore[return-value]


def _render_declarative_fake(item: DiscoveredKernelSpec, index: int) -> list[str]:
    spec = item.spec
    schema = parse_schema(spec.operator_schema)
    tensor_arguments = [argument.name for argument in schema.args if argument.kind == "Tensor"]
    scalar_arguments = [argument.name for argument in schema.args if argument.kind != "Tensor"]
    lines = [f"def _mindclade_fake_{index}({', '.join(schema.argument_names)}):"]
    lines.append("    metadata = {" + ", ".join(f"{name!r}: {name}" for name in tensor_arguments) + "}")
    lines.append("    scalars = {" + ", ".join(f"{name!r}: {name}" for name in scalar_arguments) + "}")
    rendered_outputs = []
    for output in spec.forward.outputs:
        rendered_outputs.append(
            "torch.empty("
            f"{output.shape.to_python()}, dtype=_mindclade_dtype({output.dtype.to_python()}), "
            f"device={output.device.to_python()})"
        )
    if len(rendered_outputs) == 1:
        lines.append(f"    return {rendered_outputs[0]}")
    else:
        lines.append("    return (" + ", ".join(rendered_outputs) + ")")
    lines.extend(("", ""))
    return lines


def _render_python_registration(discovered: list[DiscoveredKernelSpec]) -> str:
    lines = [
        f"# GENERATED FILE - DO NOT EDIT. Generator: {GENERATOR_ID}@{GENERATOR_VERSION}.",
        "from __future__ import annotations",
        "",
        "import torch",
        "",
        "_REGISTERED = False",
        "",
        "",
        "def _mindclade_dtype(value):",
        "    return getattr(torch, value) if isinstance(value, str) else value",
        "",
        "",
    ]
    fake_names: list[str] = []
    autograd: list[tuple[str, str] | None] = []
    none_wrappers: list[tuple[str, str]] = []
    for index, item in enumerate(discovered):
        spec = item.spec
        if spec.fake is None:
            lines.extend(_render_declarative_fake(item, index))
        else:
            module, symbol = _split_identity(spec.fake)
            lines.append(f"from {module} import {symbol} as _mindclade_fake_{index}")
        fake_names.append(f"_mindclade_fake_{index}")
        if spec.autograd_policy is AutogradPolicy.COMPOSITE:
            assert spec.composite is not None
            setup_module, setup_symbol = _split_identity(spec.composite.setup_context or "")
            backward_module, backward_symbol = _split_identity(spec.composite.backward or "")
            setup_alias = f"_mindclade_setup_context_{index}"
            raw_backward = f"_mindclade_raw_backward_{index}"
            wrapper = f"_mindclade_backward_{index}"
            lines.append(f"from {setup_module} import {setup_symbol} as {setup_alias}")
            lines.append(f"from {backward_module} import {backward_symbol} as {raw_backward}")
            lines.extend(
                (
                    "",
                    f"def {wrapper}(ctx, *grad_outputs):",
                    "    if torch.is_grad_enabled() and any(",
                    "        gradient is not None and gradient.requires_grad",
                    "        for gradient in grad_outputs",
                    "    ):",
                    f"        raise RuntimeError({('mindclade::' + spec.name + ' does not support double backward')!r})",
                    f"    return {raw_backward}(ctx, *grad_outputs)",
                    "",
                    "",
                )
            )
            autograd.append((setup_alias, wrapper))
        elif spec.autograd_policy is AutogradPolicy.NONE:
            wrapper = f"_mindclade_no_autograd_{index}"
            lines.extend(
                (
                    "",
                    f"def {wrapper}(ctx, *grad_outputs):",
                    "    del ctx, grad_outputs",
                    f"    raise RuntimeError({(spec.qualified_name + ' is non-differentiable')!r})",
                    "",
                    "",
                )
            )
            none_wrappers.append((spec.qualified_name, wrapper))
            autograd.append(None)
        else:
            autograd.append(None)

    lines.extend(("def register_python_kernels() -> None:", "    global _REGISTERED", "    if _REGISTERED:", "        return"))
    for index, item in enumerate(discovered):
        spec = item.spec
        fake_name = fake_names[index]
        forward_name = parse_schema(spec.forward.schema).name
        lines.append(f"    torch.library.register_fake({spec.qualified_name!r})({fake_name})")
        lines.append(f"    torch.library.register_fake({(spec.namespace + '::' + forward_name)!r})({fake_name})")
        if spec.autograd_policy is AutogradPolicy.COMPOSITE:
            setup_alias, wrapper = autograd[index] or ("", "")
            lines.append(
                f"    torch.library.register_autograd({spec.qualified_name!r}, {wrapper}, setup_context={setup_alias})"
            )
        elif spec.autograd_policy is AutogradPolicy.REQUIRED:
            message = (
                f"{spec.qualified_name} requires generated named provider-argument roles "
                "before native autograd registration"
            )
            lines.append(f"    raise RuntimeError({message!r})")
        else:
            wrapper = next(value for qualified, value in none_wrappers if qualified == spec.qualified_name)
            lines.append(f"    torch.library.register_autograd({spec.qualified_name!r}, {wrapper})")
    lines.extend(("    _REGISTERED = True", ""))
    return "\n".join(lines)


def _source_rows(discovered: list[DiscoveredKernelSpec]) -> tuple[list[str], list[str]]:
    specs = [item.spec.source for item in discovered]
    builders = [source.replace("/spec.py", "/tilelang.py") for source in specs]
    return specs, builders


def _render_bzl(discovered: list[DiscoveredKernelSpec]) -> str:
    specs, builders = _source_rows(discovered)
    lines = [f"# GENERATED FILE - DO NOT EDIT. Generator: {GENERATOR_ID}@{GENERATOR_VERSION}."]
    for variable, sources in (("MINDCLADE_KERNEL_SPEC_SOURCES", specs), ("MINDCLADE_TILELANG_KERNEL_SOURCES", builders)):
        lines.append(f"{variable} = [")
        for source in sources:
            package, filename = source.rsplit("/", 1)
            lines.append(f'    "//kernels/{package}:{filename}",')
        lines.extend(("]", ""))
    return "\n".join(lines)


def _render_cmake(discovered: list[DiscoveredKernelSpec]) -> str:
    specs, builders = _source_rows(discovered)
    lines = [f"# GENERATED FILE - DO NOT EDIT. Generator: {GENERATOR_ID}@{GENERATOR_VERSION}."]
    for variable, sources in (("MINDCLADE_KERNEL_SPEC_SOURCES", specs), ("MINDCLADE_TILELANG_KERNEL_SOURCES", builders)):
        lines.append(f"set({variable}")
        lines.extend(f'  "${{CMAKE_CURRENT_LIST_DIR}}/../../{source}"' for source in sources)
        lines.append(")")
    lines.append("")
    return "\n".join(lines)


def render_all(
    native_root: Path,
    *,
    source_files: tuple[str | Path, ...] | list[str | Path],
) -> dict[str, str]:
    """Render every owned v3 surface from an explicit relative inventory."""

    native_root = Path(native_root)
    discovered = discover_specs(native_root.parent, source_files)
    return {
        "native_ops.json": _render_manifest(discovered),
        "registration.generated.cpp": _render_schema_registration(discovered),
        "operation_registry.generated.cpp": _render_operation_registry(discovered),
        "python_registration_generated.py": _render_python_registration(discovered),
        "native_ops.generated.cmake": _render_cmake(discovered),
        "native_ops.generated.bzl": _render_bzl(discovered),
    }


def write_outputs(rendered: dict[str, str], output_dir: Path) -> None:
    """Atomically replace each generated text surface."""

    output_dir.mkdir(parents=True, exist_ok=True)
    for name in GENERATED_FILENAMES:
        destination = output_dir / name
        temporary = output_dir / f".{name}.tmp"
        temporary.write_text(rendered[name], encoding="utf-8", newline="\n")
        temporary.replace(destination)


def check_outputs(rendered: dict[str, str], output_dir: Path) -> tuple[str, ...]:
    """Return deterministic drift diagnostics without mutating the tree."""

    errors: list[str] = []
    for name in GENERATED_FILENAMES:
        path = output_dir / name
        if not path.is_file():
            errors.append(f"missing generated output: {name}")
        elif path.read_text(encoding="utf-8") != rendered[name]:
            errors.append(f"generated output drift: {name}")
    legacy = output_dir / "python_registration.generated.py"
    if legacy.exists():
        errors.append(f"legacy generated output must be removed: {legacy.name}")
    return tuple(errors)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args(argv)
    native_root = Path(__file__).resolve().parents[1]
    rendered = render_all(native_root, source_files=DEFAULT_SPEC_SOURCES)
    output = native_root / "generated"
    if arguments.check:
        errors = check_outputs(rendered, output)
        if errors:
            parser.error("; ".join(errors))
        return 0
    write_outputs(rendered, output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
