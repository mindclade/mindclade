"""Deterministic v3 native registration generation from canonical ``spec.py`` files."""

from __future__ import annotations

import argparse
from dataclasses import fields, is_dataclass
from enum import Enum
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from kernels.api import (
    AutogradPolicy,
    BackwardArgumentSource,
    Expr,
    MissingGradientPolicy,
    ProgramBindingSource,
)
from kernels.native.codegen.discover import DiscoveredKernelSpec, discover_specs
from kernels.native.codegen.schema import ParsedSchema, parse_schema

GENERATOR_ID = "kernels.native.codegen.generate"
GENERATOR_VERSION = 8
SCHEMA_VERSION = 4

GENERATED_FILENAMES = (
    "native_ops.json",
    "registration.generated.cpp",
    "operation_registry.generated.cpp",
    "launcher_plans.generated.cpp",
    "qualified_capabilities.generated.cpp",
    "qualified_capabilities.generated.json",
    "python_registration_generated.py",
    "native_ops.generated.cmake",
    "native_ops.generated.bzl",
)

_CAPABILITY_ROW_FIELDS = (
    "operation",
    "phase",
    "workload_digest",
    "specialization_digest",
    "capability_digest",
    "artifact_digest",
    "architecture",
    "dtype",
    "layout",
    "mode",
    "dimensions",
    "attributes",
    "specificity",
    "priority",
    "adapter_symbols",
)

_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_NAME = re.compile(r"[a-z][a-z0-9_]{0,63}")
_TOKEN = re.compile(r"[a-z][a-z0-9_]{0,63}")
_OPERATION = re.compile(r"mindclade::[a-z][a-z0-9_]{0,63}")
_ARCHITECTURE = re.compile(r"sm[0-9]{2,3}a?")
_C_SYMBOL = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_ROW_KEYS = frozenset(_CAPABILITY_ROW_FIELDS)
_DTYPE_CPP = {
    "float16": "MINDCLADE_NODE_DTYPE_FLOAT16_V1",
    "bfloat16": "MINDCLADE_NODE_DTYPE_BFLOAT16_V1",
    "float32": "MINDCLADE_NODE_DTYPE_FLOAT32_V1",
    "bool": "MINDCLADE_NODE_DTYPE_BOOL_V1",
    "int64": "MINDCLADE_NODE_DTYPE_INT64_V1",
}
_CAPABILITY_SORT_ORDER = (
    "operation",
    "phase",
    "-specificity",
    "-priority",
    "capability_digest",
)

DEFAULT_SPEC_SOURCES = (
    "pairformer/outer_product_mean/spec.py",
    "pairformer/pair_weighted_average/spec.py",
    "pairformer/transition/spec.py",
    "pairformer/triangle_attention/spec.py",
    "pairformer/triangle_multiplication/spec.py",
)


def _content_digest(value: object) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


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


def _launcher_plan(phase: str, provider: Any) -> dict[str, Any] | None:
    group = provider.program_group
    if group is None:
        return None
    return {
        "phase": phase,
        "logical_symbol": provider.symbol,
        "bridge_requirement": "mindclade_node_launch_v1",
        "execution_order": [node.name for node in group.nodes],
        "adapter_symbol_prefixes": [node.symbol for node in group.nodes],
        "selector_bindings": [_json_value(binding) for binding in group.selector_bindings],
        "nodes": [
            {
                "name": node.name,
                "symbol": node.symbol,
                "entry_symbol": node.entry_symbol,
                "entry_abi": node.entry_abi.value,
                "return_abi": node.return_abi.value,
                "artifact_boundary": node.artifact_boundary.value,
                "depends_on": list(node.depends_on),
                "parameters": [_json_value(parameter) for parameter in node.parameters],
                "bindings": [_json_value(binding) for binding in node.bindings],
            }
            for node in group.nodes
        ],
        "workspaces": [
            {
                "name": workspace.name,
                "shape": _json_value(workspace.shape),
                "dtype": _json_value(workspace.dtype),
                "zero_initialize": workspace.zero_initialize,
                "lifetime": workspace.lifetime.value,
            }
            for workspace in group.workspaces
        ],
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
    implementation_contracts = [_json_value(value) for value in item.implementations]
    implementation_candidates = []
    for implementation in item.implementations:
        envelope = _json_value(implementation.envelope)
        implementation_candidates.append(
            {
                "name": implementation.name,
                "version": implementation.version,
                "tier": implementation.tier.value,
                "priority": implementation.priority,
                "requires": list(implementation.requires),
                "envelope": envelope,
                "envelope_digest": _content_digest(envelope),
                "promoted": False,
                "selectable": False,
            }
        )
    return {
        "name": spec.name,
        "qualified_name": spec.qualified_name,
        "namespace": spec.namespace,
        "family": spec.family,
        "source": spec.source,
        "spec_sha256": item.declaration_sha256,
        "kernel_spec_digest": spec.digest,
        "implementation_digest": _content_digest(implementation_contracts),
        "implementation_candidates": implementation_candidates,
        "operator_schema": semantic.canonical,
        "facade_outputs": list(spec.facade_outputs),
        "fake": spec.fake,
        "forward": _json_value(spec.forward),
        "backward": _json_value(spec.backward),
        "autograd_policy": spec.autograd_policy.value,
        "composite": _json_value(spec.composite),
        "effects": _json_value(spec.effects),
        "launch": _json_value(spec.launch),
        "runtime_workload": _json_value(spec.runtime_workload),
        "backend": spec.backend,
        "version": spec.version,
        "devices": list(spec.devices),
        "registrations": registrations,
        "launcher_plans": {
            "forward": _launcher_plan("forward", spec.forward),
            "backward": (
                _launcher_plan("backward", spec.backward)
                if spec.backward is not None
                else None
            ),
        },
    }


def _manifest(discovered: list[DiscoveredKernelSpec]) -> dict[str, Any]:
    operators = [_operator_record(item) for item in discovered]
    source_inventory = [
        {
            "source": record["source"],
            "spec_sha256": record["spec_sha256"],
            "kernel_spec_digest": record["kernel_spec_digest"],
            "implementation_digest": record["implementation_digest"],
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
        "source_inventory_sha256": _content_digest(source_inventory),
        "namespace": "mindclade",
        "registration_mode": "build_time_generated",
        "optimized_math_authority": "tilelang",
        "runtime_discovery": False,
        "request_time_compilation": False,
        "operators": operators,
        "semantic_digest": _content_digest(semantic_inventory),
    }
    manifest["manifest_digest"] = _content_digest(manifest)
    return manifest


def _render_manifest(discovered: list[DiscoveredKernelSpec]) -> str:
    return json.dumps(_manifest(discovered), indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def _validated_capability_rows(
    rows: tuple[dict[str, Any], ...] | list[dict[str, Any]],
    *,
    required_operations: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    if not isinstance(rows, (tuple, list)):
        raise ValueError("qualified capability rows must be an explicit sequence")
    canonical: list[dict[str, Any]] = []
    for index, raw in enumerate(rows):
        if not isinstance(raw, dict) or set(raw) != _ROW_KEYS:
            raise ValueError(f"capability row {index} must contain exact v1 fields")
        row = dict(raw)
        if not isinstance(row["operation"], str) or _OPERATION.fullmatch(row["operation"]) is None:
            raise ValueError(f"capability row {index} has invalid operation")
        if row["phase"] not in {"forward", "backward"}:
            raise ValueError(f"capability row {index} has invalid phase")
        for key in ("workload_digest", "specialization_digest", "capability_digest", "artifact_digest"):
            if not isinstance(row[key], str) or _DIGEST.fullmatch(row[key]) is None:
                raise ValueError(f"capability row {index} has invalid {key}")
        if not isinstance(row["architecture"], str) or _ARCHITECTURE.fullmatch(row["architecture"]) is None:
            raise ValueError(f"capability row {index} has invalid architecture")
        if row["dtype"] not in _DTYPE_CPP:
            raise ValueError(f"capability row {index} has invalid dtype")
        for key in ("layout", "mode"):
            if not isinstance(row[key], str) or _TOKEN.fullmatch(row[key]) is None:
                raise ValueError(f"capability row {index} has invalid {key}")
        dimensions = row["dimensions"]
        if not isinstance(dimensions, list) or not dimensions:
            raise ValueError(f"capability row {index} dimensions must be nonempty")
        dimension_names: list[str] = []
        for dimension in dimensions:
            if not isinstance(dimension, dict) or set(dimension) != {"name", "value"}:
                raise ValueError(f"capability row {index} has invalid dimension entry")
            name, value = dimension["name"], dimension["value"]
            if not isinstance(name, str) or _NAME.fullmatch(name) is None:
                raise ValueError(f"capability row {index} has invalid dimension name")
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= (1 << 63) - 1:
                raise ValueError(f"capability row {index} has invalid dimension value")
            dimension_names.append(name)
        if dimension_names != sorted(set(dimension_names)):
            raise ValueError(f"capability row {index} dimensions must be sorted and unique")
        attributes = row["attributes"]
        if not isinstance(attributes, list):
            raise ValueError(f"capability row {index} attributes must be a list")
        attribute_names: list[str] = []
        for attribute in attributes:
            if not isinstance(attribute, dict) or set(attribute) != {"name", "type", "value"}:
                raise ValueError(f"capability row {index} has invalid attribute entry")
            name, kind, value = attribute["name"], attribute["type"], attribute["value"]
            if not isinstance(name, str) or _NAME.fullmatch(name) is None:
                raise ValueError(f"capability row {index} has invalid attribute name")
            valid = (
                (kind == "bool" and isinstance(value, bool))
                or (kind == "int64" and isinstance(value, int) and not isinstance(value, bool) and -(1 << 63) <= value <= (1 << 63) - 1)
                or (kind == "float64" and isinstance(value, float) and value == value and value not in {float("inf"), float("-inf")})
                or (kind == "string" and isinstance(value, str) and len(value.encode("utf-8")) <= 1024)
            )
            if not valid:
                raise ValueError(f"capability row {index} has invalid typed attribute")
            attribute_names.append(name)
        if attribute_names != sorted(set(attribute_names)):
            raise ValueError(f"capability row {index} attributes must be sorted and unique")
        overlap = sorted(set(dimension_names) & set(attribute_names))
        if overlap:
            raise ValueError(f"capability row {index} dimension/attribute names overlap: {overlap}")
        if isinstance(row["specificity"], bool) or row["specificity"] != len(dimensions) + len(attributes):
            raise ValueError(f"capability row {index} specificity must be derived from workload fields")
        if isinstance(row["priority"], bool) or not isinstance(row["priority"], int) or not -(1 << 31) <= row["priority"] <= (1 << 31) - 1:
            raise ValueError(f"capability row {index} priority is outside int32")
        symbols = row["adapter_symbols"]
        if not isinstance(symbols, list) or not symbols or any(
            not isinstance(symbol, str) or _C_SYMBOL.fullmatch(symbol) is None for symbol in symbols
        ) or len(symbols) != len(set(symbols)):
            raise ValueError(f"capability row {index} adapter_symbols must be unique C symbols")
        canonical.append(row)
    phase_rank = {"forward": 1, "backward": 2}
    canonical.sort(key=lambda row: (
        row["operation"], phase_rank[row["phase"]], -row["specificity"],
        -row["priority"], row["capability_digest"],
    ))
    identities: set[tuple[object, ...]] = set()
    for row in canonical:
        identity = (
            row["operation"], row["phase"], row["workload_digest"],
            row["architecture"], row["dtype"], row["layout"], row["mode"],
            row["specificity"], row["priority"], row["capability_digest"],
        )
        if identity in identities:
            raise ValueError("duplicate qualified capability selection identity")
        identities.add(identity)
    for operation in required_operations:
        operation_rows = [row for row in canonical if row["operation"] == operation]
        for row in operation_rows:
            peers = [
                peer for peer in operation_rows
                if peer["phase"] != row["phase"]
                and all(peer[key] == row[key] for key in (
                    "workload_digest", "specialization_digest", "capability_digest",
                    "architecture", "dtype", "layout", "mode", "dimensions",
                    "attributes", "specificity", "priority",
                ))
            ]
            if len(peers) != 1:
                raise ValueError(f"REQUIRED capability {operation} must contain one atomic FWD/BWD pair")
    return canonical


def _qualified_capability_manifest(
    rows: tuple[dict[str, Any], ...] | list[dict[str, Any]] = (),
    *,
    required_operations: tuple[str, ...] = (),
) -> dict[str, Any]:
    canonical_rows = _validated_capability_rows(rows, required_operations=required_operations)
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "generator": {"id": GENERATOR_ID, "version": GENERATOR_VERSION},
        "selection": "exact_qualified_only",
        "row_fields": list(_CAPABILITY_ROW_FIELDS),
        "sort_order": list(_CAPABILITY_SORT_ORDER),
        "rows": canonical_rows,
        "row_count": len(canonical_rows),
        "rows_digest": _content_digest(canonical_rows),
    }
    manifest["table_digest"] = _content_digest(manifest)
    return manifest


def _render_qualified_capabilities_json() -> str:
    return json.dumps(
        _qualified_capability_manifest(), indent=2, sort_keys=True, ensure_ascii=True
    ) + "\n"


def _render_qualified_capabilities_cpp(
    rows: tuple[dict[str, Any], ...] | list[dict[str, Any]] = (),
    *,
    required_operations: tuple[str, ...] = (),
) -> str:
    manifest = _qualified_capability_manifest(rows, required_operations=required_operations)
    canonical_rows = manifest["rows"]
    lines = [
            f"// GENERATED FILE - DO NOT EDIT. Generator: {GENERATOR_ID}@{GENERATOR_VERSION}.",
            "#include <array>",
            "#include <cstddef>",
            '#include "../stable_abi/qualified_capability_table.h"',
            "",
    ]
    symbols = sorted({symbol for row in canonical_rows for symbol in row["adapter_symbols"]})
    lines.extend(
        f'extern "C" int32_t {symbol}(const MindcladeNodeLaunchV1*);' for symbol in symbols
    )
    if symbols:
        lines.append("")
    lines.extend((
        "namespace {",
        "[[maybe_unused]] constexpr MindcladeCapabilityAttributeV1 capability_bool(const char* name, bool value) {",
        "  MindcladeCapabilityAttributeV1 result{}; result.name = name;",
        "  result.type = MINDCLADE_CAPABILITY_ATTRIBUTE_BOOL_V1; result.value.boolean_value = value ? 1u : 0u; return result;",
        "}",
        "[[maybe_unused]] constexpr MindcladeCapabilityAttributeV1 capability_int64(const char* name, int64_t value) {",
        "  MindcladeCapabilityAttributeV1 result{}; result.name = name;",
        "  result.type = MINDCLADE_CAPABILITY_ATTRIBUTE_INT64_V1; result.value.int64_value = value; return result;",
        "}",
        "[[maybe_unused]] constexpr MindcladeCapabilityAttributeV1 capability_float64(const char* name, double value) {",
        "  MindcladeCapabilityAttributeV1 result{}; result.name = name;",
        "  result.type = MINDCLADE_CAPABILITY_ATTRIBUTE_FLOAT64_V1; result.value.float64_value = value; return result;",
        "}",
        "[[maybe_unused]] constexpr MindcladeCapabilityAttributeV1 capability_string(const char* name, const char* value) {",
        "  MindcladeCapabilityAttributeV1 result{}; result.name = name;",
        "  result.type = MINDCLADE_CAPABILITY_ATTRIBUTE_STRING_V1; result.value.string_value = value; return result;",
        "}",
        "",
    ))
    for index, row in enumerate(canonical_rows):
        lines.append(
            f"constexpr std::array<MindcladeCapabilityDimensionV1, {len(row['dimensions'])}> kDimensions{index}{{{{"
        )
        lines.extend(
            f"    {{{json.dumps(value['name'])}, INT64_C({value['value']})}},"
            for value in row["dimensions"]
        )
        lines.append("}};")
        attributes = row["attributes"]
        if attributes:
            lines.append(
                f"constexpr std::array<MindcladeCapabilityAttributeV1, {len(attributes)}> kAttributes{index}{{{{"
            )
            for value in attributes:
                helper = {"bool": "capability_bool", "int64": "capability_int64", "float64": "capability_float64", "string": "capability_string"}[value["type"]]
                rendered_value = json.dumps(value["value"]) if value["type"] in {"string", "bool"} else repr(value["value"])
                lines.append(f"    {helper}({json.dumps(value['name'])}, {rendered_value}),")
            lines.append("}};")
        lines.append(
            f"constexpr std::array<MindcladeNodeAdapterV1, {len(row['adapter_symbols'])}> kAdapters{index}{{{{"
        )
        lines.extend(f"    &{symbol}," for symbol in row["adapter_symbols"])
        lines.append("}};")
        lines.append(
            f"constexpr std::array<const char*, {len(row['adapter_symbols'])}> kAdapterSymbols{index}{{{{"
        )
        lines.extend(f"    {json.dumps(symbol)}," for symbol in row["adapter_symbols"])
        lines.append("}};")
    if canonical_rows:
        lines.append(f"constexpr std::array<MindcladeQualifiedCapabilityRowV1, {len(canonical_rows)}> kRows{{{{")
        for index, row in enumerate(canonical_rows):
            digest = bytes.fromhex(row["specialization_digest"][7:])
            digest_values = ", ".join(f"0x{value:02x}" for value in digest)
            attrs_pointer = f"kAttributes{index}.data()" if row["attributes"] else "nullptr"
            phase = "MINDCLADE_CAPABILITY_PHASE_FORWARD_V1" if row["phase"] == "forward" else "MINDCLADE_CAPABILITY_PHASE_BACKWARD_V1"
            lines.extend((
                "    {",
                f"      {json.dumps(row['operation'])}, {phase}, {json.dumps(row['workload_digest'])},",
                f"      {{{digest_values}}}, {json.dumps(row['capability_digest'])}, {json.dumps(row['artifact_digest'])},",
                f"      {json.dumps(row['architecture'])}, {_DTYPE_CPP[row['dtype']]}, {json.dumps(row['layout'])}, {json.dumps(row['mode'])},",
                f"      kDimensions{index}.data(), {len(row['dimensions'])}u, {attrs_pointer}, {len(row['attributes'])}u,",
                f"      {row['specificity']}u, {row['priority']}, kAdapters{index}.data(), kAdapterSymbols{index}.data(), {len(row['adapter_symbols'])}u",
                "    },",
            ))
        lines.append("}};")
    lines.extend(("}  // namespace", ""))
    lines.extend((
            'extern "C" std::size_t mindclade_qualified_capability_row_count_v1() {',
            f"  return {len(canonical_rows)};",
            "}",
            "",
            'extern "C" const MindcladeQualifiedCapabilityRowV1*',
            "mindclade_qualified_capability_rows_v1() {",
            "  return " + ("kRows.data();" if canonical_rows else "nullptr;"),
            "}",
            "",
            'extern "C" const char* mindclade_qualified_capability_rows_digest_v1() {',
            f'  return "{manifest["rows_digest"]}";',
            "}",
            "",
            'extern "C" const char* mindclade_qualified_capability_table_digest_v1() {',
            f'  return "{manifest["table_digest"]}";',
            "}",
            "",
    ))
    return "\n".join(lines)


def render_qualified_capability_table(
    rows: tuple[dict[str, Any], ...] | list[dict[str, Any]],
    *,
    required_operations: tuple[str, ...] = (),
) -> dict[str, str]:
    """Render one immutable signed-index projection into exact JSON/C++ surfaces."""

    manifest = _qualified_capability_manifest(rows, required_operations=required_operations)
    return {
        "qualified_capabilities.generated.json": json.dumps(
            manifest, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False
        ) + "\n",
        "qualified_capabilities.generated.cpp": _render_qualified_capabilities_cpp(
            rows, required_operations=required_operations
        ),
    }


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
        "#include <optional>",
        "#include <tuple>",
        "#include <torch/csrc/stable/library.h>",
        "#include <torch/csrc/stable/tensor.h>",
        "",
        "#if defined(__clang__)",
        "#pragma clang diagnostic push",
        '#pragma clang diagnostic ignored "-Wreturn-type-c-linkage"',
        "#endif",
        "",
    ]
    if any(
        item.spec.forward.program_group is not None
        or (
            item.spec.backward is not None
            and item.spec.backward.program_group is not None
        )
        for item in discovered
    ):
        lines.extend(
            (
                "#if !defined(MINDCLADE_NODE_LAUNCH_ABI_V1)",
                '#error "program-group CUDA registry requires callable node ABI v1"',
                "#endif",
                "",
            )
        )
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
    lines.extend((
        "}",
        "",
        "#if defined(__clang__)",
        "#pragma clang diagnostic pop",
        "#endif",
        "",
    ))
    return "\n".join(lines)


def _split_identity(identity: str) -> tuple[str, str]:
    return tuple(identity.split(":", 1))  # type: ignore[return-value]


def _render_declarative_fake(item: DiscoveredKernelSpec, index: int) -> list[str]:
    spec = item.spec
    schema = parse_schema(spec.operator_schema)
    for argument in schema.args:
        if not argument.is_tensor or not argument.is_optional:
            continue
        if any(
            _contract_references_argument(expression, argument.name)
            for output in spec.forward.outputs
            for expression in (output.shape, output.dtype, output.device)
        ):
            raise ValueError(
                f"{spec.qualified_name} declarative fake depends on optional Tensor "
                f"argument {argument.name!r}; declare a custom fake"
            )
    tensor_arguments = [argument.name for argument in schema.args if argument.is_tensor]
    scalar_arguments = [argument.name for argument in schema.args if not argument.is_tensor]
    lines = [f"def _mindclade_fake_{index}({', '.join(schema.argument_names)}):"]
    lines.append(
        "    metadata = {" + ", ".join(f"{name!r}: {name}" for name in tensor_arguments) + "}"
    )
    lines.append(
        "    scalars = {" + ", ".join(f"{name!r}: {name}" for name in scalar_arguments) + "}"
    )
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


def _contract_references_argument(value: Any, argument: str) -> bool:
    data = _json_value(value)
    if isinstance(data, dict):
        if data.get("argument") == argument:
            return True
        return any(_contract_references_argument(item, argument) for item in data.values())
    if isinstance(data, list):
        return any(_contract_references_argument(item, argument) for item in data)
    return False


def _binding_map(item: DiscoveredKernelSpec):
    backward = item.spec.backward
    if backward is None:
        return {}
    return {binding.provider_argument: binding for binding in backward.argument_bindings}


def _required_saved_values(item: DiscoveredKernelSpec):
    """Return deterministic tensor/scalar context plans for REQUIRED autograd."""

    spec = item.spec
    assert spec.backward is not None
    semantic = parse_schema(spec.operator_schema)
    bindings = spec.backward.argument_bindings
    operator_sources = {
        binding.source_name
        for binding in bindings
        if binding.source is BackwardArgumentSource.OPERATOR_ARGUMENT
    }
    forward_sources = {
        binding.source_name
        for binding in bindings
        if binding.source is BackwardArgumentSource.FORWARD_OUTPUT
        or (
            binding.source is BackwardArgumentSource.OUTPUT_GRADIENT
            and binding.missing is MissingGradientPolicy.ZERO
        )
    }
    tensor_values: list[tuple[BackwardArgumentSource, str, str]] = []
    scalar_values: list[tuple[BackwardArgumentSource, str, str]] = []
    for position, argument in enumerate(semantic.args):
        if argument.name not in operator_sources:
            continue
        target = tensor_values if argument.is_tensor else scalar_values
        target.append(
            (
                BackwardArgumentSource.OPERATOR_ARGUMENT,
                argument.name,
                f"inputs[{position}]",
            )
        )
    outputs = {output.name: output for output in spec.forward.outputs}
    for position, output in enumerate(spec.forward.outputs):
        if output.name not in forward_sources:
            continue
        if not output.saved_for_backward:
            raise ValueError(
                f"{spec.qualified_name} forward output {output.name!r} must be "
                "saved_for_backward when used by native autograd"
            )
        tensor_values.append(
            (
                BackwardArgumentSource.FORWARD_OUTPUT,
                output.name,
                f"output_values[{position}]",
            )
        )
    if set(forward_sources) - set(outputs):
        raise ValueError(f"{spec.qualified_name} has an unknown saved forward source")
    return tensor_values, scalar_values


def _render_backward_fake(item: DiscoveredKernelSpec, index: int) -> list[str]:
    spec = item.spec
    assert spec.backward is not None
    backward = parse_schema(spec.backward.schema)
    bindings = _binding_map(item)
    gradient_by_output = {gradient.output_name: gradient for gradient in spec.backward.gradients}
    metadata_bindings = {
        binding.source_name: backward.argument_by_name(binding.provider_argument)
        for binding in spec.backward.argument_bindings
        if binding.source is BackwardArgumentSource.OPERATOR_ARGUMENT
    }
    request_bindings = {
        binding.source_name: binding.provider_argument
        for binding in spec.backward.argument_bindings
        if binding.source is BackwardArgumentSource.NEEDS_INPUT_GRAD
    }
    tensor_metadata = {
        source: argument.name
        for source, argument in metadata_bindings.items()
        if argument.is_tensor
    }
    scalar_metadata = {
        source: argument.name
        for source, argument in metadata_bindings.items()
        if argument.is_scalar
    }
    rendered: list[str] = []
    for returned in backward.returns:
        gradient = gradient_by_output[returned.name]
        value = (
            "torch.empty("
            f"{gradient.shape.to_python()}, "
            f"dtype=_mindclade_dtype({gradient.dtype.to_python()}), "
            f"device={gradient.device.to_python()})"
        )
        if gradient.optional:
            request = request_bindings[gradient.input_name]
            value = f"({value} if {request} else None)"
        rendered.append(value)
    lines = [f"def _mindclade_backward_fake_{index}({', '.join(backward.argument_names)}):"]
    lines.append(
        "    metadata = {"
        + ", ".join(f"{source!r}: {argument}" for source, argument in sorted(tensor_metadata.items()))
        + "}"
    )
    lines.append(
        "    scalars = {"
        + ", ".join(f"{source!r}: {argument}" for source, argument in sorted(scalar_metadata.items()))
        + "}"
    )
    if len(rendered) == 1:
        lines.append(f"    return {rendered[0]}")
    else:
        lines.append("    return (" + ", ".join(rendered) + ")")
    lines.extend(("", ""))
    return lines


def _render_required_autograd(item: DiscoveredKernelSpec, index: int) -> tuple[list[str], str, str]:
    spec = item.spec
    assert spec.backward is not None
    semantic = parse_schema(spec.operator_schema)
    backward = parse_schema(spec.backward.schema)
    bindings = _binding_map(item)
    tensor_values, scalar_values = _required_saved_values(item)
    setup_name = f"_mindclade_required_setup_context_{index}"
    backward_name = f"_mindclade_required_backward_{index}"
    lines = [
        f"def {setup_name}(ctx, inputs, output):",
        "    output_values = (output,)"
        if len(semantic.returns) == 1
        else "    output_values = output",
        "    ctx.set_materialize_grads(False)",
    ]
    tensor_expressions = ", ".join(value[2] for value in tensor_values)
    if tensor_expressions:
        lines.append(f"    ctx.save_for_backward({tensor_expressions})")
    else:
        lines.append("    ctx.save_for_backward()")
    scalar_expressions = ", ".join(value[2] for value in scalar_values)
    if len(scalar_values) == 1:
        scalar_expressions += ","
    lines.append(f"    ctx._mindclade_saved_scalars_{index} = ({scalar_expressions})")
    lines.extend(("", "", f"def {backward_name}(ctx, *grad_outputs):"))
    lines.extend(
        (
            "    if torch.is_grad_enabled():",
            f"        raise RuntimeError({(spec.qualified_name + ' does not support double backward')!r})",
        )
    )
    if tensor_values:
        names = ", ".join(f"saved_tensor_{position}" for position in range(len(tensor_values)))
        if len(tensor_values) == 1:
            names += ","
        lines.append(f"    {names} = ctx.saved_tensors")
    if scalar_values:
        names = ", ".join(f"saved_scalar_{position}" for position in range(len(scalar_values)))
        if len(scalar_values) == 1:
            names += ","
        lines.append(f"    {names} = ctx._mindclade_saved_scalars_{index}")

    saved: dict[tuple[BackwardArgumentSource, str], str] = {}
    for position, (source, source_name, _expression) in enumerate(tensor_values):
        saved[(source, source_name)] = f"saved_tensor_{position}"
    for position, (source, source_name, _expression) in enumerate(scalar_values):
        saved[(source, source_name)] = f"saved_scalar_{position}"

    output_positions = {
        returned.name: position for position, returned in enumerate(semantic.returns)
    }
    output_gradients: dict[str, str] = {}
    for binding in spec.backward.argument_bindings:
        if binding.source is not BackwardArgumentSource.OUTPUT_GRADIENT:
            continue
        variable = f"output_gradient_{binding.source_name}"
        if binding.source_name not in output_gradients:
            output_gradients[binding.source_name] = variable
            lines.append(f"    {variable} = grad_outputs[{output_positions[binding.source_name]}]")
        if binding.missing is MissingGradientPolicy.ERROR:
            lines.extend(
                (
                    f"    if {variable} is None:",
                    f"        raise RuntimeError({(spec.qualified_name + ' requires a gradient for output ' + binding.source_name)!r})",
                )
            )
        elif binding.missing is MissingGradientPolicy.ZERO:
            template = saved[(BackwardArgumentSource.FORWARD_OUTPUT, binding.source_name)]
            lines.append(f"    if {variable} is None: {variable} = torch.zeros_like({template})")

    semantic_positions = {
        argument.name: position for position, argument in enumerate(semantic.args)
    }
    provider_values: list[str] = []
    for provider_argument in backward.args:
        binding = bindings[provider_argument.name]
        if binding.source is BackwardArgumentSource.OUTPUT_GRADIENT:
            provider_values.append(output_gradients[binding.source_name])
        elif binding.source is BackwardArgumentSource.NEEDS_INPUT_GRAD:
            provider_values.append(
                f"ctx.needs_input_grad[{semantic_positions[binding.source_name]}]"
            )
        else:
            provider_values.append(saved[(binding.source, binding.source_name)])
    lines.append(f"    raw = torch.ops.{spec.namespace}.{backward.name}(")
    lines.extend(f"        {value}," for value in provider_values)
    lines.append("    )")
    lines.append(
        "    raw_values = (raw,)" if len(backward.returns) == 1 else "    raw_values = raw"
    )
    gradient_by_input = {gradient.input_name: gradient for gradient in spec.backward.gradients}
    return_values: list[str] = []
    for position, argument in enumerate(semantic.args):
        gradient = gradient_by_input.get(argument.name)
        if gradient is None:
            return_values.append("None")
            continue
        result_position = backward.return_names.index(gradient.output_name)
        return_values.append(
            f"raw_values[{result_position}] if ctx.needs_input_grad[{position}] else None"
        )
    lines.append("    return (")
    lines.extend(f"        {value}," for value in return_values)
    lines.extend(("    )", "", ""))
    return lines, setup_name, backward_name


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
        if spec.backward is not None:
            lines.extend(_render_backward_fake(item, index))
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
            required_lines, setup_name, backward_name = _render_required_autograd(item, index)
            lines.extend(required_lines)
            autograd.append((setup_name, backward_name))

    lines.extend(
        (
            "def register_python_kernels() -> None:",
            "    global _REGISTERED",
            "    if _REGISTERED:",
            "        return",
        )
    )
    for index, item in enumerate(discovered):
        spec = item.spec
        fake_name = fake_names[index]
        forward_name = parse_schema(spec.forward.schema).name
        lines.append(f"    torch.library.register_fake({spec.qualified_name!r})({fake_name})")
        lines.append(
            f"    torch.library.register_fake({(spec.namespace + '::' + forward_name)!r})({fake_name})"
        )
        if spec.backward is not None:
            backward_name = parse_schema(spec.backward.schema).name
            lines.append(
                f"    torch.library.register_fake({(spec.namespace + '::' + backward_name)!r})(_mindclade_backward_fake_{index})"
            )
        if spec.autograd_policy is AutogradPolicy.COMPOSITE:
            setup_alias, wrapper = autograd[index] or ("", "")
            lines.append(
                f"    torch.library.register_autograd({spec.qualified_name!r}, {wrapper}, setup_context={setup_alias})"
            )
        elif spec.autograd_policy is AutogradPolicy.REQUIRED:
            setup_name, backward_name = autograd[index] or ("", "")
            lines.append(
                f"    torch.library.register_autograd({spec.qualified_name!r}, {backward_name}, setup_context={setup_name})"
            )
        else:
            wrapper = next(
                value for qualified, value in none_wrappers if qualified == spec.qualified_name
            )
            lines.append(f"    torch.library.register_autograd({spec.qualified_name!r}, {wrapper})")
    lines.extend(("    _REGISTERED = True", ""))
    return "\n".join(lines)


def _source_rows(discovered: list[DiscoveredKernelSpec]) -> tuple[list[str], list[str]]:
    specs = [item.spec.source for item in discovered]
    builders = [source.replace("/spec.py", "/tilelang.py") for source in specs]
    return specs, builders


def _private_symbols(discovered: list[DiscoveredKernelSpec]) -> list[str]:
    del discovered
    # Resolved physical symbols come only from signed, promoted capability
    # receipts.  The checked-in capability table is deliberately empty.
    return []


def _adapter_symbol_prefixes(
    discovered: list[DiscoveredKernelSpec],
) -> list[str]:
    symbols: list[str] = []
    for item in discovered:
        providers = [item.spec.forward]
        if item.spec.backward is not None:
            providers.append(item.spec.backward)
        for provider in providers:
            if provider.program_group is not None:
                symbols.extend(node.symbol for node in provider.program_group.nodes)
    return sorted(symbols)


def _logical_symbols(discovered: list[DiscoveredKernelSpec]) -> list[str]:
    symbols: set[str] = set()
    for item in discovered:
        symbols.add(item.spec.forward.symbol)
        if item.spec.backward is not None:
            symbols.add(item.spec.backward.symbol)
    return sorted(symbols)


def _static_launcher_plans(discovered: list[DiscoveredKernelSpec]) -> list[dict[str, Any]]:
    plans: list[dict[str, Any]] = []
    for item in discovered:
        providers = [("forward", item.spec.forward)]
        if item.spec.backward is not None:
            providers.append(("backward", item.spec.backward))
        for phase, provider in providers:
            group = provider.program_group
            if group is None:
                continue
            outputs = []
            if phase == "forward":
                outputs = [
                    {
                        "initialization": _json_value(output.initialization),
                        "name": output.name,
                        "saved_for_backward": output.saved_for_backward,
                    }
                    for output in provider.outputs
                ]
            plans.append(
                {
                    "execution_order": [node.name for node in group.nodes],
                    "logical_symbol": provider.symbol,
                    "operation": item.spec.qualified_name,
                    "outputs": outputs,
                    "phase": phase,
                    "adapter_symbol_prefixes": [node.symbol for node in group.nodes],
                    "selector_bindings": [
                        _json_value(binding) for binding in group.selector_bindings
                    ],
                    "workspaces": [
                        {
                            "dtype": _json_value(workspace.dtype),
                            "lifetime": workspace.lifetime.value,
                            "name": workspace.name,
                            "shape": _json_value(workspace.shape),
                            "zero_initialize": workspace.zero_initialize,
                        }
                        for workspace in group.workspaces
                    ],
                }
            )
    return plans


def _cpp_tensor_dtype(expression: Expr, semantic_to_provider: dict[str, str]) -> str:
    data = expression.to_data()
    node = data["node"]
    if node in {"dtype_ref", "same_as_input_dtype"}:
        argument = semantic_to_provider.get(str(data["argument"]))
        if argument is None:
            raise ValueError(f"runtime dtype metadata is unavailable for {data['argument']!r}")
        return f"{argument}_view.dtype"
    if node == "constant_dtype":
        mapping = {
            "float16": "TensorDType::kFloat16",
            "bfloat16": "TensorDType::kBFloat16",
            "float32": "TensorDType::kFloat32",
            "bool": "TensorDType::kBool",
        }
        try:
            return mapping[str(data["value"])]
        except KeyError as exc:
            raise ValueError(f"unsupported native dtype expression {data!r}") from exc
    raise ValueError(f"unsupported native dtype expression {data!r}")


def _cpp_int_expression(data: dict[str, Any], semantic_to_provider: dict[str, str]) -> str:
    node = data["node"]
    if node == "int_literal":
        return f"INT64_C({data['value']})" if int(data["value"]) >= 0 else f"-INT64_C({-int(data['value'])})"
    if node == "dim_ref":
        argument = semantic_to_provider.get(str(data["argument"]))
        if argument is None:
            raise ValueError(f"runtime dimension metadata is unavailable for {data['argument']!r}")
        return f"tensor_dimension({argument}_view, {int(data['axis'])}, {json.dumps(argument)})"
    if node == "rank_ref":
        argument = semantic_to_provider.get(str(data["argument"]))
        if argument is None:
            raise ValueError(f"runtime rank metadata is unavailable for {data['argument']!r}")
        return f"static_cast<std::int64_t>({argument}_view.sizes.size())"
    if node == "scalar_ref":
        argument = semantic_to_provider.get(str(data["argument"]), str(data["argument"]))
        return f"static_cast<std::int64_t>({argument})"
    binary = {
        "add": "+", "sub": "-", "subtract": "-", "mul": "*", "multiply": "*",
        "floor_div": "/", "mod": "%", "modulo": "%",
    }
    if node in binary:
        return f"({_cpp_int_expression(data['lhs'], semantic_to_provider)} {binary[node]} {_cpp_int_expression(data['rhs'], semantic_to_provider)})"
    if node == "ceil_div":
        lhs = _cpp_int_expression(data["lhs"], semantic_to_provider)
        rhs = _cpp_int_expression(data["rhs"], semantic_to_provider)
        return f"(({lhs} + {rhs} - 1) / {rhs})"
    if node in {"min", "minimum", "max", "maximum"}:
        function = "std::min" if node in {"min", "minimum"} else "std::max"
        return f"{function}({_cpp_int_expression(data['lhs'], semantic_to_provider)}, {_cpp_int_expression(data['rhs'], semantic_to_provider)})"
    if node == "round_up":
        value = _cpp_int_expression(data["value"], semantic_to_provider)
        multiple = _cpp_int_expression(data["multiple"], semantic_to_provider)
        return f"((({value} + {multiple} - 1) / {multiple}) * {multiple})"
    raise ValueError(f"unsupported native integer expression {data!r}")


def _cpp_shape(expression: Expr, semantic_to_provider: dict[str, str]) -> str:
    data = expression.to_data()
    node = data["node"]
    if node == "shape_of":
        argument = semantic_to_provider.get(str(data["argument"]))
        if argument is None:
            raise ValueError(f"runtime shape metadata is unavailable for {data['argument']!r}")
        return f"{argument}_view.sizes"
    if node == "shape_tuple":
        values = ", ".join(_cpp_int_expression(value, semantic_to_provider) for value in data["dimensions"])
        return f"std::vector<std::int64_t>{{{values}}}"
    if node == "shape_prefix":
        argument = semantic_to_provider.get(str(data["argument"]))
        if argument is None:
            raise ValueError(f"runtime shape metadata is unavailable for {data['argument']!r}")
        trailing = int(data["trailing_rank"])
        return (
            f"std::vector<std::int64_t>({argument}_view.sizes.begin(), "
            f"{argument}_view.sizes.end() - {trailing})"
        )
    if node == "concat_shape":
        parts = [_cpp_shape_value(value, semantic_to_provider) for value in data["parts"]]
        statements = []
        for index, part in enumerate(parts):
            statements.append(f"auto part_{index} = {part};")
            statements.append(f"result.insert(result.end(), part_{index}.begin(), part_{index}.end());")
        return "([&]() { std::vector<std::int64_t> result; " + " ".join(statements) + " return result; }())"
    raise ValueError(f"unsupported native shape expression {data!r}")


def _cpp_shape_value(data: dict[str, Any], semantic_to_provider: dict[str, str]) -> str:
    class _DataExpression:
        def to_data(self):
            return data
    return _cpp_shape(_DataExpression(), semantic_to_provider)  # type: ignore[arg-type]


def _cpp_scalar_expression(expression: Expr, semantic_to_provider: dict[str, str]) -> tuple[str, str]:
    data = expression.to_data()
    node = data["node"]
    domain = expression.domain.value
    if node == "bool_literal":
        return "bool", "true" if data["value"] else "false"
    if node == "int_literal":
        return "int64", _cpp_int_expression(data, semantic_to_provider)
    if node == "float_literal":
        return "float64", repr(float(data["value"]))
    if node == "string_literal":
        return "string", json.dumps(data["value"])
    if node == "scalar_ref":
        argument = semantic_to_provider.get(str(data["argument"]), str(data["argument"]))
        return {"bool": "bool", "int": "int64", "float": "float64", "string": "string"}[domain], argument
    if domain == "int":
        return "int64", _cpp_int_expression(data, semantic_to_provider)
    raise ValueError(f"unsupported native scalar attribute expression {data!r}")


def _phase_source_arguments(spec, phase: str) -> dict[tuple[ProgramBindingSource, str], str]:
    provider = spec.forward if phase == "forward" else spec.backward
    assert provider is not None
    schema = parse_schema(provider.schema)
    if phase == "forward":
        return {
            (ProgramBindingSource.OPERATOR_ARGUMENT, argument.name): argument.name
            for argument in schema.args
        }
    result: dict[tuple[ProgramBindingSource, str], str] = {}
    source_map = {
        BackwardArgumentSource.OUTPUT_GRADIENT: ProgramBindingSource.OUTPUT_GRADIENT,
        BackwardArgumentSource.OPERATOR_ARGUMENT: ProgramBindingSource.OPERATOR_ARGUMENT,
        BackwardArgumentSource.FORWARD_OUTPUT: ProgramBindingSource.FORWARD_OUTPUT,
        BackwardArgumentSource.NEEDS_INPUT_GRAD: ProgramBindingSource.GRADIENT_REQUEST,
    }
    for binding in spec.backward.argument_bindings:
        result[(source_map[binding.source], binding.source_name)] = binding.provider_argument
    return result


def _semantic_to_provider(spec, phase: str) -> dict[str, str]:
    if phase == "forward":
        return {argument.name: argument.name for argument in parse_schema(spec.forward.schema).args}
    sources = _phase_source_arguments(spec, phase)
    return {
        source_name: provider_name
        for (source, source_name), provider_name in sources.items()
        if source is ProgramBindingSource.OPERATOR_ARGUMENT
    }


def _cpp_initialization(output) -> tuple[str, str]:
    if output.initialization is None:
        return "InitializationMode::kUninitialized", "0.0"
    mode = output.initialization.mode
    if mode == "value":
        return "InitializationMode::kValue", repr(float(output.initialization.value))
    return {
        "uninitialized": ("InitializationMode::kUninitialized", "0.0"),
        "zero": ("InitializationMode::kZero", "0.0"),
        "negative_infinity": ("InitializationMode::kNegativeInfinity", "0.0"),
    }[mode]


def _render_provider_launcher(item: DiscoveredKernelSpec, phase: str, provider) -> list[str]:
    spec = item.spec
    schema = parse_schema(provider.schema)
    group = provider.program_group
    assert group is not None
    semantic_to_provider = _semantic_to_provider(spec, phase)
    source_arguments = _phase_source_arguments(spec, phase)
    tensor_arguments = [argument for argument in schema.args if argument.is_tensor]
    if not tensor_arguments or any(argument.is_optional for argument in tensor_arguments):
        raise ValueError(f"{spec.qualified_name}/{phase}: v1 launch requires nonoptional tensor inputs")
    lines = [f'extern "C" {schema.cpp_return_type} {provider.symbol}({schema.cpp_parameters}) {{']
    for argument in tensor_arguments:
        lines.append(
            f"  const auto {argument.name}_view = require_cuda_contiguous_tensor({argument.name}, {json.dumps(argument.name)});"
        )
    template = tensor_arguments[0].name
    for argument in tensor_arguments[1:]:
        lines.append(f"  require_same_device({template}_view, {argument.name}_view, {json.dumps(argument.name)});")
    dimensions = spec.runtime_workload.dimensions
    lines.append(
        f"  const std::array<MindcladeCapabilityDimensionV1, {len(dimensions)}> workload_dimensions{{{{"
    )
    for binding in dimensions:
        lines.append(
            f"      {{{json.dumps(binding.name)}, {_cpp_int_expression(binding.value.to_data(), semantic_to_provider)}}},"
        )
    lines.append("  }};")
    attributes = spec.runtime_workload.attributes
    if attributes:
        lines.append(
            f"  std::array<MindcladeCapabilityAttributeV1, {len(attributes)}> workload_attributes{{}};"
        )
        for index, binding in enumerate(attributes):
            kind, value = _cpp_scalar_expression(binding.value, semantic_to_provider)
            field = {
                "bool": ("MINDCLADE_CAPABILITY_ATTRIBUTE_BOOL_V1", "boolean_value", f"({value}) ? 1u : 0u"),
                "int64": ("MINDCLADE_CAPABILITY_ATTRIBUTE_INT64_V1", "int64_value", value),
                "float64": ("MINDCLADE_CAPABILITY_ATTRIBUTE_FLOAT64_V1", "float64_value", value),
                "string": ("MINDCLADE_CAPABILITY_ATTRIBUTE_STRING_V1", "string_value", value),
            }[kind]
            lines.extend((
                f"  workload_attributes[{index}].name = {json.dumps(binding.name)};",
                f"  workload_attributes[{index}].type = {field[0]};",
                f"  workload_attributes[{index}].value.{field[1]} = {field[2]};",
            ))
    mode = '"default"'
    if spec.runtime_workload.mode_selector is not None:
        selectors = [
            selector for selector in group.selector_bindings
            if selector.selector_key == spec.runtime_workload.mode_selector
        ]
        if len(selectors) != 1:
            raise ValueError(f"{spec.qualified_name}/{phase}: runtime mode selector is ambiguous")
        selector = selectors[0]
        false_mode = next(value for case, value in selector.cases if not case)
        true_mode = next(value for case, value in selector.cases if case)
        mode = f"({selector.provider_argument} ? {json.dumps(true_mode)} : {json.dumps(false_mode)})"
    dtype = _cpp_tensor_dtype(spec.runtime_workload.input_dtype, semantic_to_provider)
    lines.extend((
        "  char workload_digest[72]{};",
        "  const auto digest_status = mindclade_canonical_workload_digest_v1(",
        f"      {json.dumps(spec.qualified_name)}, {spec.runtime_workload.canonicalization_version}u,",
        "      workload_dimensions.data(), workload_dimensions.size(),",
        f"      node_dtype({dtype}), {json.dumps(spec.runtime_workload.layout)}, {mode},",
        f"      {'workload_attributes.data()' if attributes else 'nullptr'}, {len(attributes)}u, workload_digest);",
        "  if (digest_status != MINDCLADE_CAPABILITY_STATUS_SUCCESS_V1) {",
        '    throw std::runtime_error("failed to canonicalize Mindclade native workload");',
        "  }",
        "  MindcladeCapabilityRequestV1 request{};",
        f"  request.operation = {json.dumps(spec.qualified_name)};",
        f"  request.phase = {'MINDCLADE_CAPABILITY_PHASE_FORWARD_V1' if phase == 'forward' else 'MINDCLADE_CAPABILITY_PHASE_BACKWARD_V1'};",
        "  request.workload_digest = workload_digest;",
        f"  request.device_index = {template}_view.device_index;",
        f"  request.dtype = node_dtype({dtype});",
        f"  request.layout = {json.dumps(spec.runtime_workload.layout)};",
        f"  request.mode = {mode};",
        "  request.dimensions = workload_dimensions.data();",
        "  request.dimension_count = static_cast<std::uint32_t>(workload_dimensions.size());",
        f"  request.attributes = {'workload_attributes.data()' if attributes else 'nullptr'}; request.attribute_count = {len(attributes)}u;",
        f"  request.require_atomic_backward = {1 if spec.autograd_policy is AutogradPolicy.REQUIRED else 0}u;",
        "  const MindcladeQualifiedCapabilityRowV1* capability = nullptr;",
        "  const auto selection_status = mindclade_select_qualified_capability_v1(",
        "      mindclade_qualified_capability_rows_v1(),",
        "      mindclade_qualified_capability_row_count_v1(), &request,",
        "      &mindclade_cuda_device_architecture_v1, &capability);",
        "  if (selection_status != MINDCLADE_CAPABILITY_STATUS_SUCCESS_V1 || capability == nullptr) {",
        f'    throw std::runtime_error("no exact qualified native capability for {spec.qualified_name}/{phase}");',
        "  }",
        f"  void* current_stream = current_cuda_stream({template}, {json.dumps(template)});",
    ))
    result_specs = provider.outputs if phase == "forward" else spec.backward.gradients
    output_by_name = {value.name if phase == "forward" else value.output_name: value for value in result_specs}
    request_by_input: dict[str, str] = {}
    if phase == "backward":
        request_by_input = {
            binding.source_name: binding.provider_argument
            for binding in spec.backward.argument_bindings
            if binding.source is BackwardArgumentSource.NEEDS_INPUT_GRAD
        }
    for returned in schema.returns:
        output = output_by_name[returned.name]
        shape = _cpp_shape(output.shape, semantic_to_provider)
        dtype_expr = _cpp_tensor_dtype(output.dtype, semantic_to_provider)
        initialization, initialization_value = (
            _cpp_initialization(output) if phase == "forward"
            else ("InitializationMode::kUninitialized", "0.0")
        )
        like = template
        if returned.is_optional:
            request_name = request_by_input[output.input_name]
            lines.extend((
                f"  std::optional<torch::stable::Tensor> {returned.name};",
                f"  if ({request_name}) {{",
                f"    {returned.name} = allocate_cuda_tensor({like}, {shape}, {dtype_expr}, {initialization}, {initialization_value});",
                "  }",
            ))
        else:
            lines.append(
                f"  auto {returned.name} = allocate_cuda_tensor({like}, {shape}, {dtype_expr}, {initialization}, {initialization_value});"
            )
    for workspace in group.workspaces:
        lines.append(
            f"  auto workspace_{workspace.name} = allocate_workspace({template}, {_cpp_shape(workspace.shape, semantic_to_provider)}, {_cpp_tensor_dtype(workspace.dtype, semantic_to_provider)}, {'true' if workspace.zero_initialize else 'false'});"
        )
    invocation_names: list[str] = []
    access = {
        "read": "MINDCLADE_NODE_ACCESS_READ_V1",
        "write": "MINDCLADE_NODE_ACCESS_WRITE_V1",
        "read_write": "MINDCLADE_NODE_ACCESS_READ_WRITE_V1",
    }
    for node_index, node in enumerate(group.nodes):
        bindings = {binding.parameter: binding for binding in node.bindings}
        storage_names: list[str] = []
        value_names: list[str] = []
        for parameter in node.parameters:
            binding = bindings[parameter.name]
            prefix = f"node_{node_index}_{parameter.name}"
            value_source: str
            if binding.source is ProgramBindingSource.CURRENT_STREAM:
                lines.append(f"  const auto {prefix}_value = make_node_stream_value(current_stream);")
                value_names.append(f"{prefix}_value")
                continue
            if binding.source is ProgramBindingSource.WORKSPACE:
                value_source = f"workspace_{binding.source_name}"
            elif binding.source is ProgramBindingSource.PROVIDER_OUTPUT:
                value_source = str(binding.source_name)
            elif phase == "forward" and binding.source is ProgramBindingSource.FORWARD_OUTPUT:
                value_source = str(binding.source_name)
            else:
                key = (binding.source, str(binding.source_name))
                try:
                    value_source = source_arguments[key]
                except KeyError as exc:
                    raise ValueError(
                        f"{spec.qualified_name}/{phase}/{node.name}: unresolved binding {key}"
                    ) from exc
            if parameter.kind.value == "tensor":
                optional = parameter.optional and binding.source is ProgramBindingSource.PROVIDER_OUTPUT
                if optional:
                    lines.append(
                        f"  auto {prefix}_storage = {value_source}.has_value() ? make_node_tensor_value(*{value_source}, {access[parameter.access.value]}, true, {json.dumps(parameter.name)}) : make_absent_node_tensor_value({access[parameter.access.value]});"
                    )
                else:
                    lines.append(
                        f"  auto {prefix}_storage = make_node_tensor_value({value_source}, {access[parameter.access.value]}, false, {json.dumps(parameter.name)});"
                    )
                storage_names.append(f"{prefix}_storage")
                value_names.append(f"{prefix}_storage.value")
            elif parameter.kind.value == "scalar":
                constructor = {
                    "bool": "make_node_bool_value",
                    "int64": "make_node_int64_value",
                    "float64": "make_node_float64_value",
                }[parameter.scalar_type.value]
                lines.append(
                    f"  const auto {prefix}_value = {constructor}({value_source}, {access[parameter.access.value]});"
                )
                value_names.append(f"{prefix}_value")
            else:
                raise ValueError(f"unsupported generated node parameter kind {parameter.kind}")
        lines.append(
            f"  const std::array<MindcladeNodeValueV1, {len(value_names)}> node_{node_index}_values{{{{{', '.join(value_names)}}}}};"
        )
        invocation_names.append(
            f"MindcladeNodeInvocationV1{{node_{node_index}_values.data(), static_cast<std::uint32_t>(node_{node_index}_values.size())}}"
        )
    lines.extend((
        f"  const std::array<MindcladeNodeInvocationV1, {len(invocation_names)}> invocations{{{{",
        *(f"      {value}," for value in invocation_names),
        "  }};",
        "  std::int32_t adapter_status = MINDCLADE_NODE_STATUS_SUCCESS_V1;",
        "  const auto execution_status = mindclade_execute_qualified_capability_v1(",
        "      capability, invocations.data(), invocations.size(), &adapter_status);",
        "  if (execution_status != MINDCLADE_CAPABILITY_STATUS_SUCCESS_V1) {",
        '    throw std::runtime_error("Mindclade native program group execution failed with status " +',
        "                             std::to_string(adapter_status));",
        "  }",
    ))
    if len(schema.returns) == 1:
        lines.append(f"  return {schema.returns[0].name};")
    else:
        lines.append("  return {" + ", ".join(value.name for value in schema.returns) + "};")
    lines.extend(("}", ""))
    return lines


def _render_static_launcher_plans(discovered: list[DiscoveredKernelSpec]) -> str:
    private_symbols = _private_symbols(discovered)
    plans = _static_launcher_plans(discovered)
    lines = [
        f"// GENERATED FILE - DO NOT EDIT. Generator: {GENERATOR_ID}@{GENERATOR_VERSION}.",
        "#include <algorithm>",
        "#include <array>",
        "#include <cstddef>",
        "#include <cstdint>",
        "#include <optional>",
        "#include <stdexcept>",
        "#include <string>",
        "#include <string_view>",
        "#include <tuple>",
        "#include <vector>",
        "#include <torch/csrc/stable/tensor.h>",
        '#include "../stable_abi/node_launch_bridge.h"',
        '#include "../stable_abi/qualified_capability_table.h"',
        '#include "../stable_abi/tensor_bridge.h"',
        "",
        'extern "C" std::int32_t mindclade_cuda_device_architecture_v1(',
        "    std::int32_t device_index, std::uint32_t* architecture);",
        "",
        "#if defined(__clang__)",
        "#pragma clang diagnostic push",
        '#pragma clang diagnostic ignored "-Wreturn-type-c-linkage"',
        "#endif",
        "",
    ]
    lines.extend(f'extern "C" void {symbol}();' for symbol in private_symbols)
    lines.extend(("", "namespace mindclade::native::generated {"))
    lines.append("using PrivateLauncher = void (*)();")
    lines.append(
        f"const std::array<PrivateLauncher, {len(private_symbols)}> kRequiredPrivateLaunchers{{{{"
    )
    lines.extend(f"    &{symbol}," for symbol in private_symbols)
    lines.extend(("}};", ""))

    declarations: dict[str, ParsedSchema] = {}
    for item in discovered:
        providers = [item.spec.forward]
        if item.spec.backward is not None:
            providers.append(item.spec.backward)
        for provider in providers:
            if provider.program_group is not None:
                declarations.setdefault(provider.symbol, parse_schema(provider.schema))
    lines.extend((
        "using mindclade::native::stable_abi::InitializationMode;",
        "using mindclade::native::stable_abi::TensorDType;",
        "using mindclade::native::stable_abi::allocate_cuda_tensor;",
        "using mindclade::native::stable_abi::allocate_workspace;",
        "using mindclade::native::stable_abi::current_cuda_stream;",
        "using mindclade::native::stable_abi::make_absent_node_tensor_value;",
        "using mindclade::native::stable_abi::make_node_bool_value;",
        "using mindclade::native::stable_abi::make_node_float64_value;",
        "using mindclade::native::stable_abi::make_node_int64_value;",
        "using mindclade::native::stable_abi::make_node_stream_value;",
        "using mindclade::native::stable_abi::make_node_tensor_value;",
        "using mindclade::native::stable_abi::node_dtype;",
        "using mindclade::native::stable_abi::require_cuda_contiguous_tensor;",
        "using mindclade::native::stable_abi::require_same_device;",
        "using mindclade::native::stable_abi::tensor_dimension;",
        "",
    ))
    for item in discovered:
        providers = [("forward", item.spec.forward)]
        if item.spec.backward is not None:
            providers.append(("backward", item.spec.backward))
        for phase, provider in providers:
            if provider.program_group is not None:
                lines.extend(_render_provider_launcher(item, phase, provider))
    lines.append(
        f"constexpr std::array<std::string_view, {len(plans)}> kStaticLauncherPlans{{{{"
    )
    for plan in plans:
        canonical = json.dumps(plan, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        lines.append(f"    R\"mindclade({canonical})mindclade\",")
    lines.extend(
        (
            "}};",
            "}  // namespace mindclade::native::generated",
            "",
            'extern "C" const mindclade::native::generated::PrivateLauncher*',
            "mindclade_native_required_private_launchers() noexcept {",
            "  return mindclade::native::generated::kRequiredPrivateLaunchers.data();",
            "}",
            "",
            'extern "C" std::size_t mindclade_native_static_launcher_plan_count() noexcept {',
            "  return mindclade::native::generated::kStaticLauncherPlans.size();",
            "}",
            "",
            "#if defined(__clang__)",
            "#pragma clang diagnostic pop",
            "#endif",
            "",
        )
    )
    return "\n".join(lines)


def _render_bzl(discovered: list[DiscoveredKernelSpec]) -> str:
    specs, builders = _source_rows(discovered)
    lines = [
        f"# GENERATED FILE - DO NOT EDIT. Generator: {GENERATOR_ID}@{GENERATOR_VERSION}.",
        '"""Generated Bazel source inventory for native TileLang kernels."""',
        "",
    ]
    for variable, sources in (
        ("MINDCLADE_KERNEL_SPEC_SOURCES", specs),
        ("MINDCLADE_TILELANG_KERNEL_SOURCES", builders),
    ):
        lines.append(f"{variable} = [")
        for source in sources:
            package, filename = source.rsplit("/", 1)
            lines.append(f'    "//kernels/{package}:{filename}",')
        lines.extend(("]", ""))
    lines.append("MINDCLADE_TILELANG_REQUIRED_PRIVATE_SYMBOLS = [")
    lines.extend(f'    "{symbol}",' for symbol in _private_symbols(discovered))
    lines.extend(("]", ""))
    lines.append("MINDCLADE_TILELANG_ADAPTER_SYMBOL_PREFIXES = [")
    lines.extend(f'    "{symbol}",' for symbol in _adapter_symbol_prefixes(discovered))
    lines.extend(("]", ""))
    lines.append("MINDCLADE_TILELANG_REQUIRED_LOGICAL_SYMBOLS = [")
    lines.extend(f'    "{symbol}",' for symbol in _logical_symbols(discovered))
    lines.extend(("]", ""))
    return "\n".join(lines)


def _render_cmake(discovered: list[DiscoveredKernelSpec]) -> str:
    specs, builders = _source_rows(discovered)
    lines = [f"# GENERATED FILE - DO NOT EDIT. Generator: {GENERATOR_ID}@{GENERATOR_VERSION}."]
    for variable, sources in (
        ("MINDCLADE_KERNEL_SPEC_SOURCES", specs),
        ("MINDCLADE_TILELANG_KERNEL_SOURCES", builders),
    ):
        lines.append(f"set({variable}")
        lines.extend(f'  "${{CMAKE_CURRENT_LIST_DIR}}/../../{source}"' for source in sources)
        lines.append(")")
    lines.append("set(MINDCLADE_TILELANG_REQUIRED_PRIVATE_SYMBOLS")
    lines.extend(f'  "{symbol}"' for symbol in _private_symbols(discovered))
    lines.append(")")
    lines.append("set(MINDCLADE_TILELANG_ADAPTER_SYMBOL_PREFIXES")
    lines.extend(f'  "{symbol}"' for symbol in _adapter_symbol_prefixes(discovered))
    lines.append(")")
    lines.append("set(MINDCLADE_TILELANG_REQUIRED_LOGICAL_SYMBOLS")
    lines.extend(f'  "{symbol}"' for symbol in _logical_symbols(discovered))
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
        "launcher_plans.generated.cpp": _render_static_launcher_plans(discovered),
        "qualified_capabilities.generated.cpp": _render_qualified_capabilities_cpp(),
        "qualified_capabilities.generated.json": _render_qualified_capabilities_json(),
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
