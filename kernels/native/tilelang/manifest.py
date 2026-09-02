"""Runtime-safe validation for the generated native-operator manifest.

The production loader depends only on the standard library.  It never imports
operation declarations, TileLang, discovery, or code-generation packages.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any

GENERATOR_ID = "kernels.native.codegen.generate"
GENERATOR_VERSION = 8
NAMESPACE = "mindclade"
REGISTRATION_MODE = "build_time_generated"

_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SYMBOL = _IDENTIFIER
_MAX_MANIFEST_BYTES = 16 * 1024 * 1024
_MAX_OPERATORS = 4096

_TOP_LEVEL_KEYS = {
    "schema_version", "generator", "source_inventory_sha256", "namespace",
    "registration_mode", "optimized_math_authority", "runtime_discovery",
    "request_time_compilation", "operators", "semantic_digest", "manifest_digest",
}
_OPERATOR_KEYS = {
    "name", "qualified_name", "namespace", "family", "source", "spec_sha256",
    "kernel_spec_digest", "implementation_digest", "implementation_candidates", "operator_schema", "facade_outputs", "fake", "forward",
    "backward", "autograd_policy", "composite", "effects", "launch", "backend",
    "runtime_workload", "version", "devices", "registrations", "launcher_plans",
}
_REGISTRATION_KEYS = {"qualified_name", "schema", "kind", "implementation_symbol"}
_FORWARD_KEYS = {"type", "schema", "builder", "symbol", "outputs", "program_group", "version"}
_BACKWARD_KEYS = {
    "type", "schema", "builder", "symbol", "argument_bindings", "gradients",
    "supports_double_backward", "program_group", "version",
}
_BACKWARD_ARGUMENT_BINDING_KEYS = {
    "type", "provider_argument", "source", "source_name", "missing", "version",
}
_OUTPUT_KEYS = {
    "type", "name", "shape", "dtype", "device", "semantic_axes",
    "visible_in_facade", "saved_for_backward", "initialization", "version",
}
_INITIALIZATION_KEYS = {"type", "mode", "value", "version"}
_GRADIENT_KEYS = {
    "type", "input_name", "output_name", "shape", "dtype", "device",
    "optional", "accumulation_dtype", "version",
}
_COMPOSITE_KEYS = {
    "type", "decomposition", "source_digest", "runtime_envelope", "gradients",
    "supports_double_backward", "setup_context", "backward", "version",
}
_EFFECT_KEYS = {
    "type", "mutates_inputs", "aliases_outputs", "uses_rng", "uses_atomics", "version",
}
_LAUNCH_KEYS = {
    "type", "current_stream_only", "global_synchronization", "hidden_device_allocation",
    "graph_capture_safe", "determinism", "version",
}
_PROGRAM_GROUP_KEYS = {
    "type", "nodes", "workspaces", "selector_bindings", "version",
}
_PROGRAM_NODE_KEYS = {
    "type", "name", "builder", "symbol", "entry_symbol", "entry_abi",
    "parameters", "bindings", "depends_on", "return_abi", "artifact_boundary",
    "version",
}
_PROGRAM_PARAMETER_KEYS = {
    "type", "position", "name", "kind", "access", "shape", "dtype", "device",
    "scalar_type", "optional", "version",
}
_PROGRAM_BINDING_KEYS = {"type", "parameter", "source", "source_name", "version"}
_PROGRAM_SELECTOR_BINDING_KEYS = {
    "type", "provider_argument", "selector_key", "scalar_type", "cases", "version",
}
_WORKSPACE_KEYS = {
    "type", "name", "shape", "dtype", "zero_initialize", "lifetime", "version",
}
_LAUNCHER_PLANS_KEYS = {"forward", "backward"}
_LAUNCHER_PLAN_KEYS = {
    "phase", "logical_symbol", "bridge_requirement", "execution_order",
    "adapter_symbol_prefixes", "nodes", "workspaces", "selector_bindings",
}
_IMPLEMENTATION_CANDIDATE_KEYS = {
    "name", "version", "tier", "priority", "requires", "envelope",
    "envelope_digest", "promoted", "selectable",
}
_CAPABILITY_KEYS = {
    "type", "architectures", "dtypes", "layouts", "modes", "constraints",
    "graph_capture_safe", "training_capable", "tensor_constraints", "version",
}
_DIMENSION_CONSTRAINT_KEYS = {"type", "predicate", "code", "message", "version"}
_TENSOR_CAPABILITY_KEYS = {
    "type", "argument", "dtypes", "layouts", "devices", "ranks", "version",
}
_RUNTIME_WORKLOAD_KEYS = {
    "type", "dimensions", "input_dtype", "layout", "mode_selector", "attributes",
    "canonicalization_version", "version",
}
_WORKLOAD_BINDING_KEYS = {"type", "name", "value", "version"}


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256(value: object) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _exact_mapping(value: object, keys: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError(f"native manifest {label} has missing or unsupported fields")
    return value


def _string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 4096:
        raise ValueError(f"native manifest {label} must be a bounded non-empty string")
    return value


def _identifier(value: object, label: str) -> str:
    result = _string(value, label)
    if _IDENTIFIER.fullmatch(result) is None:
        raise ValueError(f"native manifest {label} must be an identifier")
    return result


def _digest(value: object, label: str) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise ValueError(f"native manifest {label} must use sha256:<64 lowercase hex>")
    return value


def _version(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value != 1:
        raise ValueError(f"native manifest {label} must be exactly 1")
    return value


def _boolean(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"native manifest {label} must be a boolean")
    return value


def _string_list(value: object, label: str, *, nonempty: bool = False) -> list[str]:
    if not isinstance(value, list) or (nonempty and not value):
        raise ValueError(f"native manifest {label} must be a bounded array")
    result = [_string(item, f"{label} item") for item in value]
    if len(result) != len(set(result)):
        raise ValueError(f"native manifest {label} must contain unique values")
    return result


def _identity(value: object, label: str) -> str:
    result = _string(value, label)
    if result.count(":") != 1:
        raise ValueError(f"native manifest {label} must be a module:function identity")
    module, function = result.split(":", 1)
    if not function.isidentifier() or not module or not all(
        component.isidentifier() for component in module.split(".")
    ):
        raise ValueError(f"native manifest {label} must be a module:function identity")
    return result


def _expression(value: object, label: str) -> None:
    if not isinstance(value, dict) or not isinstance(value.get("node"), str):
        raise ValueError(f"native manifest {label} must be a declarative expression object")


def _validate_gradient(value: object, label: str) -> tuple[str, str]:
    item = _exact_mapping(value, _GRADIENT_KEYS, label)
    if item["type"] != "GradientSpec":
        raise ValueError(f"native manifest {label} has unsupported contract type")
    mapping = (
        _identifier(item["input_name"], f"{label} input_name"),
        _identifier(item["output_name"], f"{label} output_name"),
    )
    _boolean(item["optional"], f"{label} optional")
    _expression(item["shape"], f"{label} shape")
    _expression(item["dtype"], f"{label} dtype")
    _expression(item["device"], f"{label} device")
    if item["accumulation_dtype"] is not None:
        _string(item["accumulation_dtype"], f"{label} accumulation_dtype")
    _version(item["version"], f"{label} version")
    return mapping


def _validate_runtime_workload(value: object, label: str) -> None:
    workload = _exact_mapping(value, _RUNTIME_WORKLOAD_KEYS, label)
    if workload["type"] != "RuntimeWorkloadSpec":
        raise ValueError(f"native manifest {label} has unsupported contract type")
    dimensions = workload["dimensions"]
    if not isinstance(dimensions, list) or not dimensions:
        raise ValueError(f"native manifest {label} dimensions must be non-empty")
    dimension_names: list[str] = []
    for index, raw in enumerate(dimensions):
        binding = _exact_mapping(raw, _WORKLOAD_BINDING_KEYS, f"{label} dimension {index}")
        if binding["type"] != "WorkloadDimensionBinding":
            raise ValueError(f"native manifest {label} dimension has unsupported type")
        dimension_names.append(_identifier(binding["name"], f"{label} dimension name"))
        _expression(binding["value"], f"{label} dimension value")
        _version(binding["version"], f"{label} dimension version")
    if dimension_names != sorted(set(dimension_names)):
        raise ValueError(f"native manifest {label} dimensions must be sorted and unique")
    attributes = workload["attributes"]
    if not isinstance(attributes, list):
        raise ValueError(f"native manifest {label} attributes must be an array")
    attribute_names: list[str] = []
    for index, raw in enumerate(attributes):
        binding = _exact_mapping(raw, _WORKLOAD_BINDING_KEYS, f"{label} attribute {index}")
        if binding["type"] != "WorkloadAttributeBinding":
            raise ValueError(f"native manifest {label} attribute has unsupported type")
        attribute_names.append(_identifier(binding["name"], f"{label} attribute name"))
        _expression(binding["value"], f"{label} attribute value")
        _version(binding["version"], f"{label} attribute version")
    if attribute_names != sorted(set(attribute_names)):
        raise ValueError(f"native manifest {label} attributes must be sorted and unique")
    if set(dimension_names) & set(attribute_names):
        raise ValueError(f"native manifest {label} workload names must be disjoint")
    _expression(workload["input_dtype"], f"{label} input_dtype")
    _string(workload["layout"], f"{label} layout")
    if workload["mode_selector"] is not None:
        _identifier(workload["mode_selector"], f"{label} mode_selector")
    _version(workload["canonicalization_version"], f"{label} canonicalization_version")
    _version(workload["version"], f"{label} version")


def _validate_program_group(value: object, label: str) -> dict[str, Any] | None:
    if value is None:
        return None
    group = _exact_mapping(value, _PROGRAM_GROUP_KEYS, label)
    if group["type"] != "ProgramGroupSpec":
        raise ValueError(f"native manifest {label} has unsupported contract type")
    nodes = group["nodes"]
    if not isinstance(nodes, list) or not nodes:
        raise ValueError(f"native manifest {label} nodes must be a non-empty array")
    names: list[str] = []
    symbols: list[str] = []
    dependencies: dict[str, list[str]] = {}
    workspaces = group["workspaces"]
    if not isinstance(workspaces, list):
        raise ValueError(f"native manifest {label} workspaces must be an array")
    workspace_names: list[str] = []
    for workspace_index, raw_workspace in enumerate(workspaces):
        workspace_label = f"{label} workspace {workspace_index}"
        workspace = _exact_mapping(raw_workspace, _WORKSPACE_KEYS, workspace_label)
        if workspace["type"] != "WorkspaceSpec":
            raise ValueError(f"native manifest {workspace_label} has unsupported type")
        workspace_names.append(_identifier(workspace["name"], f"{workspace_label} name"))
        _expression(workspace["shape"], f"{workspace_label} shape")
        _expression(workspace["dtype"], f"{workspace_label} dtype")
        _boolean(workspace["zero_initialize"], f"{workspace_label} zero_initialize")
        if workspace["lifetime"] not in {"node", "program_group"}:
            raise ValueError(f"native manifest {workspace_label} has unsupported lifetime")
        _version(workspace["version"], f"{workspace_label} version")
    if len(workspace_names) != len(set(workspace_names)):
        raise ValueError(f"native manifest {label} workspace names must be unique")
    selectors = group["selector_bindings"]
    if not isinstance(selectors, list) or len(selectors) > 8:
        raise ValueError(f"native manifest {label} selector_bindings must be bounded")
    selector_arguments: list[str] = []
    selector_keys: list[str] = []
    for selector_index, raw_selector in enumerate(selectors):
        selector_label = f"{label} selector {selector_index}"
        selector = _exact_mapping(
            raw_selector, _PROGRAM_SELECTOR_BINDING_KEYS, selector_label
        )
        if selector["type"] != "ProgramSelectorBinding":
            raise ValueError(f"native manifest {selector_label} has unsupported type")
        selector_arguments.append(
            _identifier(selector["provider_argument"], f"{selector_label} provider_argument")
        )
        if selector["selector_key"] != "mode" or selector["scalar_type"] != "bool":
            raise ValueError(f"native manifest {selector_label} selector ABI is unsupported")
        if selector["cases"] != [[False, "incoming"], [True, "outgoing"]]:
            raise ValueError(f"native manifest {selector_label} cases are not canonical")
        selector_keys.append(selector["selector_key"])
        _version(selector["version"], f"{selector_label} version")
    if len(selector_arguments) != len(set(selector_arguments)) or len(selector_keys) != len(set(selector_keys)):
        raise ValueError(f"native manifest {label} selector identities must be unique")
    known_workspaces = set(workspace_names)
    for index, raw_node in enumerate(nodes):
        node_label = f"{label} node {index}"
        node = _exact_mapping(raw_node, _PROGRAM_NODE_KEYS, node_label)
        if node["type"] != "ProgramNodeSpec":
            raise ValueError(f"native manifest {node_label} has unsupported contract type")
        name = _identifier(node["name"], f"{node_label} name")
        _identity(node["builder"], f"{node_label} builder")
        symbol = _string(node["symbol"], f"{node_label} symbol")
        if _SYMBOL.fullmatch(symbol) is None:
            raise ValueError(f"native manifest {node_label} symbol must be a C identifier")
        entry_symbol = _string(node["entry_symbol"], f"{node_label} entry_symbol")
        if _SYMBOL.fullmatch(entry_symbol) is None or entry_symbol == symbol:
            raise ValueError(f"native manifest {node_label} entry_symbol is invalid")
        if node["entry_abi"] != "tilelang_0_1_13_host_call":
            raise ValueError(f"native manifest {node_label} entry_abi is unsupported")
        if node["return_abi"] != "status_i32_zero_success":
            raise ValueError(f"native manifest {node_label} return_abi is unsupported")
        if node["artifact_boundary"] != "node_content_addressed_dso":
            raise ValueError(f"native manifest {node_label} artifact boundary is unsupported")
        depends_on = _string_list(node["depends_on"], f"{node_label} depends_on")
        parameters = node["parameters"]
        bindings = node["bindings"]
        if not isinstance(parameters, list) or not parameters or len(parameters) > 256:
            raise ValueError(f"native manifest {node_label} parameters must be bounded")
        if not isinstance(bindings, list) or not bindings or len(bindings) > 256:
            raise ValueError(f"native manifest {node_label} bindings must be bounded")
        parameter_by_name: dict[str, dict[str, Any]] = {}
        positions: list[int] = []
        for parameter_index, raw_parameter in enumerate(parameters):
            parameter_label = f"{node_label} parameter {parameter_index}"
            parameter = _exact_mapping(
                raw_parameter, _PROGRAM_PARAMETER_KEYS, parameter_label
            )
            if parameter["type"] != "ProgramParameterSpec":
                raise ValueError(f"native manifest {parameter_label} has unsupported type")
            if type(parameter["position"]) is not int or not 0 <= parameter["position"] < 256:
                raise ValueError(f"native manifest {parameter_label} position is invalid")
            positions.append(parameter["position"])
            parameter_name = _identifier(parameter["name"], f"{parameter_label} name")
            if parameter_name in parameter_by_name:
                raise ValueError(f"native manifest {node_label} parameter names must be unique")
            parameter_by_name[parameter_name] = parameter
            if parameter["kind"] not in {"tensor", "scalar", "stream"}:
                raise ValueError(f"native manifest {parameter_label} kind is unsupported")
            if parameter["access"] not in {"read", "write", "read_write"}:
                raise ValueError(f"native manifest {parameter_label} access is unsupported")
            _boolean(parameter["optional"], f"{parameter_label} optional")
            if parameter["kind"] == "tensor":
                for field in ("shape", "dtype", "device"):
                    _expression(parameter[field], f"{parameter_label} {field}")
                if parameter["scalar_type"] is not None:
                    raise ValueError(f"native manifest {parameter_label} scalar_type is invalid")
            else:
                if any(parameter[field] is not None for field in ("shape", "dtype", "device")):
                    raise ValueError(f"native manifest {parameter_label} tensor metadata is invalid")
                if parameter["kind"] == "scalar" and parameter["scalar_type"] not in {
                    "bool", "int64", "float64"
                }:
                    raise ValueError(f"native manifest {parameter_label} scalar_type is invalid")
                if parameter["kind"] == "stream" and parameter["scalar_type"] is not None:
                    raise ValueError(f"native manifest {parameter_label} scalar_type is invalid")
            _version(parameter["version"], f"{parameter_label} version")
        if positions != list(range(len(parameters))):
            raise ValueError(f"native manifest {node_label} positions must be contiguous")

        bound_parameters: list[str] = []
        used_workspaces: list[str] = []
        current_streams = 0
        optional_provider_outputs: list[str] = []
        gradient_requests: list[str] = []
        for binding_index, raw_binding in enumerate(bindings):
            binding_label = f"{node_label} binding {binding_index}"
            binding = _exact_mapping(raw_binding, _PROGRAM_BINDING_KEYS, binding_label)
            if binding["type"] != "ProgramBindingSpec":
                raise ValueError(f"native manifest {binding_label} has unsupported type")
            parameter_name = _identifier(binding["parameter"], f"{binding_label} parameter")
            if parameter_name not in parameter_by_name:
                raise ValueError(f"native manifest {binding_label} parameter is unknown")
            bound_parameters.append(parameter_name)
            source = binding["source"]
            if source not in {
                "operator_argument", "output_gradient", "forward_output",
                "provider_output", "workspace", "gradient_request", "current_stream",
            }:
                raise ValueError(f"native manifest {binding_label} source is unsupported")
            source_name = binding["source_name"]
            if source == "current_stream":
                current_streams += 1
                if source_name is not None or parameter_by_name[parameter_name]["kind"] != "stream":
                    raise ValueError(f"native manifest {binding_label} stream binding is invalid")
            else:
                source_name = _identifier(source_name, f"{binding_label} source_name")
            if source == "workspace":
                used_workspaces.append(source_name)
            if source == "gradient_request":
                gradient_requests.append(source_name)
            if source == "provider_output" and parameter_by_name[parameter_name]["optional"]:
                optional_provider_outputs.append(source_name)
            _version(binding["version"], f"{binding_label} version")
        if len(bound_parameters) != len(set(bound_parameters)) or set(bound_parameters) != set(parameter_by_name):
            raise ValueError(f"native manifest {node_label} bindings must exactly cover parameters")
        if current_streams != 1:
            raise ValueError(f"native manifest {node_label} requires one current stream")
        if optional_provider_outputs and len(gradient_requests) != 1:
            raise ValueError(
                f"native manifest {node_label} optional outputs require one gradient request"
            )
        if len(used_workspaces) != len(set(used_workspaces)):
            raise ValueError(f"native manifest {node_label} workspace bindings must be unique")
        if set(used_workspaces) - known_workspaces:
            raise ValueError(f"native manifest {node_label} uses an unknown workspace")
        _version(node["version"], f"{node_label} version")
        names.append(name)
        symbols.append(symbol)
        dependencies[name] = depends_on
    if len(names) != len(set(names)) or len(symbols) != len(set(symbols)):
        raise ValueError(f"native manifest {label} node names and symbols must be unique")
    known = set(names)
    if any(set(items) - known for items in dependencies.values()):
        raise ValueError(f"native manifest {label} contains unknown node dependencies")
    pending = {name: set(items) for name, items in dependencies.items()}
    while pending:
        ready = sorted(name for name, items in pending.items() if not items)
        if not ready:
            raise ValueError(f"native manifest {label} contains a dependency cycle")
        for name in ready:
            del pending[name]
        for items in pending.values():
            items.difference_update(ready)
    _version(group["version"], f"{label} version")
    return group


def _expected_launcher_plan(
    phase: str,
    logical_symbol: str,
    group: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if group is None:
        return None
    return {
        "phase": phase,
        "logical_symbol": logical_symbol,
        "bridge_requirement": "mindclade_node_launch_v1",
        "execution_order": [node["name"] for node in group["nodes"]],
        "adapter_symbol_prefixes": [node["symbol"] for node in group["nodes"]],
        "selector_bindings": group["selector_bindings"],
        "nodes": [
            {
                "name": node["name"],
                "symbol": node["symbol"],
                "entry_symbol": node["entry_symbol"],
                "entry_abi": node["entry_abi"],
                "return_abi": node["return_abi"],
                "artifact_boundary": node["artifact_boundary"],
                "depends_on": node["depends_on"],
                "parameters": node["parameters"],
                "bindings": node["bindings"],
            }
            for node in group["nodes"]
        ],
        "workspaces": [
            {
                "name": workspace["name"],
                "shape": workspace["shape"],
                "dtype": workspace["dtype"],
                "zero_initialize": workspace["zero_initialize"],
                "lifetime": workspace["lifetime"],
            }
            for workspace in group["workspaces"]
        ],
    }


def _validate_launcher_plans(
    value: object,
    name: str,
    forward: dict[str, Any],
    backward: dict[str, Any] | None,
) -> None:
    plans = _exact_mapping(value, _LAUNCHER_PLANS_KEYS, f"{name} launcher_plans")
    expected = {
        "forward": _expected_launcher_plan(
            "forward", forward["symbol"], forward["program_group"]
        ),
        "backward": (
            _expected_launcher_plan(
                "backward", backward["symbol"], backward["program_group"]
            )
            if backward is not None
            else None
        ),
    }
    for phase, plan in plans.items():
        if plan is not None:
            _exact_mapping(plan, _LAUNCHER_PLAN_KEYS, f"{name} {phase} launcher plan")
    if plans != expected:
        raise ValueError(
            f"native manifest {name} launcher_plans do not match provider program groups"
        )


def _validate_output(value: object, label: str) -> tuple[str, bool]:
    item = _exact_mapping(value, _OUTPUT_KEYS, label)
    if item["type"] != "OutputSpec":
        raise ValueError(f"native manifest {label} has unsupported contract type")
    name = _identifier(item["name"], f"{label} name")
    for field in ("shape", "dtype", "device"):
        _expression(item[field], f"{label} {field}")
    _string_list(item["semantic_axes"], f"{label} semantic_axes", nonempty=True)
    visible = _boolean(item["visible_in_facade"], f"{label} visible_in_facade")
    _boolean(item["saved_for_backward"], f"{label} saved_for_backward")
    initialization = item["initialization"]
    if initialization is not None:
        initialization = _exact_mapping(initialization, _INITIALIZATION_KEYS, f"{label} initialization")
        if initialization["type"] != "InitializationSpec":
            raise ValueError(f"native manifest {label} initialization has unsupported type")
        if initialization["mode"] not in {
            "zero",
            "value",
            "negative_infinity",
            "uninitialized",
        }:
            raise ValueError(f"native manifest {label} initialization mode is unsupported")
        has_value = initialization["value"] is not None
        if (initialization["mode"] == "value") != has_value:
            raise ValueError(f"native manifest {label} initialization value is inconsistent")
        _version(initialization["version"], f"{label} initialization version")
    _version(item["version"], f"{label} version")
    return name, visible


def _validate_forward(value: object, name: str) -> dict[str, Any]:
    forward = _exact_mapping(value, _FORWARD_KEYS, f"{name} forward")
    if forward["type"] != "ForwardSpec":
        raise ValueError(f"native manifest {name} forward has unsupported type")
    schema = _string(forward["schema"], f"{name} forward schema")
    if not schema.lstrip().startswith(f"_{name}_fwd("):
        raise ValueError(f"native manifest {name} forward schema has wrong root")
    _identity(forward["builder"], f"{name} forward builder")
    symbol = _string(forward["symbol"], f"{name} forward symbol")
    if _SYMBOL.fullmatch(symbol) is None:
        raise ValueError(f"native manifest {name} forward symbol is invalid")
    outputs = forward["outputs"]
    if not isinstance(outputs, list) or not outputs:
        raise ValueError(f"native manifest {name} forward outputs must be non-empty")
    metadata = [_validate_output(item, f"{name} output {index}") for index, item in enumerate(outputs)]
    if len({item[0] for item in metadata}) != len(metadata):
        raise ValueError(f"native manifest {name} forward outputs must be unique")
    forward["program_group"] = _validate_program_group(
        forward["program_group"], f"{name} forward group"
    )
    _version(forward["version"], f"{name} forward version")
    return forward


def _validate_backward(value: object, name: str) -> dict[str, Any] | None:
    if value is None:
        return None
    backward = _exact_mapping(value, _BACKWARD_KEYS, f"{name} backward")
    if backward["type"] != "BackwardSpec":
        raise ValueError(f"native manifest {name} backward has unsupported type")
    schema = _string(backward["schema"], f"{name} backward schema")
    if not schema.lstrip().startswith(f"_{name}_bwd("):
        raise ValueError(f"native manifest {name} backward schema has wrong root")
    _identity(backward["builder"], f"{name} backward builder")
    symbol = _string(backward["symbol"], f"{name} backward symbol")
    if _SYMBOL.fullmatch(symbol) is None:
        raise ValueError(f"native manifest {name} backward symbol is invalid")
    bindings = backward["argument_bindings"]
    if not isinstance(bindings, list) or not bindings:
        raise ValueError(f"native manifest {name} backward argument_bindings must be non-empty")
    provider_arguments: list[str] = []
    for index, raw_binding in enumerate(bindings):
        label = f"{name} backward binding {index}"
        binding = _exact_mapping(raw_binding, _BACKWARD_ARGUMENT_BINDING_KEYS, label)
        if binding["type"] != "BackwardArgumentBinding":
            raise ValueError(f"native manifest {label} has unsupported type")
        provider_arguments.append(
            _identifier(binding["provider_argument"], f"{label} provider_argument")
        )
        if binding["source"] not in {
            "output_gradient", "operator_argument", "forward_output", "needs_input_grad",
        }:
            raise ValueError(f"native manifest {label} source is unsupported")
        _identifier(binding["source_name"], f"{label} source_name")
        if binding["missing"] not in {"error", "zero", "pass_none"}:
            raise ValueError(f"native manifest {label} missing policy is unsupported")
        _version(binding["version"], f"{label} version")
    if len(provider_arguments) != len(set(provider_arguments)):
        raise ValueError(f"native manifest {name} backward bindings must be unique")
    gradients = backward["gradients"]
    if not isinstance(gradients, list) or not gradients:
        raise ValueError(f"native manifest {name} backward gradients must be non-empty")
    mappings = [_validate_gradient(item, f"{name} backward gradient {index}") for index, item in enumerate(gradients)]
    if len({item[0] for item in mappings}) != len(mappings) or len({item[1] for item in mappings}) != len(mappings):
        raise ValueError(f"native manifest {name} backward gradients must be unique")
    _boolean(backward["supports_double_backward"], f"{name} supports_double_backward")
    backward["program_group"] = _validate_program_group(
        backward["program_group"], f"{name} backward group"
    )
    _version(backward["version"], f"{name} backward version")
    return backward


def _validate_composite(value: object, name: str) -> dict[str, Any] | None:
    if value is None:
        return None
    composite = _exact_mapping(value, _COMPOSITE_KEYS, f"{name} composite")
    if composite["type"] != "CompositeAutogradSpec":
        raise ValueError(f"native manifest {name} composite has unsupported type")
    for field in ("decomposition", "setup_context", "backward"):
        _identity(composite[field], f"{name} composite {field}")
    _digest(composite["source_digest"], f"{name} composite source_digest")
    _string(composite["runtime_envelope"], f"{name} composite runtime_envelope")
    gradients = composite["gradients"]
    if not isinstance(gradients, list) or not gradients:
        raise ValueError(f"native manifest {name} composite gradients must be non-empty")
    mappings = [_validate_gradient(item, f"{name} composite gradient {index}") for index, item in enumerate(gradients)]
    if len({item[0] for item in mappings}) != len(mappings) or len({item[1] for item in mappings}) != len(mappings):
        raise ValueError(f"native manifest {name} composite gradients must be unique")
    _boolean(composite["supports_double_backward"], f"{name} supports_double_backward")
    _version(composite["version"], f"{name} composite version")
    return composite


def _validate_effects(value: object, name: str) -> None:
    effects = _exact_mapping(value, _EFFECT_KEYS, f"{name} effects")
    if effects["type"] != "EffectSpec":
        raise ValueError(f"native manifest {name} effects has unsupported type")
    _string_list(effects["mutates_inputs"], f"{name} mutates_inputs")
    aliases = effects["aliases_outputs"]
    if not isinstance(aliases, list):
        raise ValueError(f"native manifest {name} aliases_outputs must be an array")
    outputs: list[str] = []
    for alias in aliases:
        if not isinstance(alias, list) or len(alias) != 2:
            raise ValueError(f"native manifest {name} aliases must be two-item arrays")
        outputs.append(_identifier(alias[0], f"{name} alias output"))
        _identifier(alias[1], f"{name} alias input")
    if len(outputs) != len(set(outputs)):
        raise ValueError(f"native manifest {name} alias outputs must be unique")
    _boolean(effects["uses_rng"], f"{name} uses_rng")
    _boolean(effects["uses_atomics"], f"{name} uses_atomics")
    _version(effects["version"], f"{name} effects version")


def _validate_launch_fields(value: dict[str, Any], label: str) -> None:
    current_stream = _boolean(value["current_stream_only"], f"{label} current_stream_only")
    global_sync = _boolean(value["global_synchronization"], f"{label} global_synchronization")
    hidden_allocation = _boolean(value["hidden_device_allocation"], f"{label} hidden_device_allocation")
    graph_safe = _boolean(value["graph_capture_safe"], f"{label} graph_capture_safe")
    if current_stream and global_sync:
        raise ValueError(f"native manifest {label} launch behavior is contradictory")
    if graph_safe and (global_sync or hidden_allocation):
        raise ValueError(f"native manifest {label} graph-capture claim is contradictory")


def _validate_launch(value: object, name: str) -> None:
    launch = _exact_mapping(value, _LAUNCH_KEYS, f"{name} launch")
    if launch["type"] != "LaunchContract":
        raise ValueError(f"native manifest {name} launch has unsupported type")
    _validate_launch_fields(launch, f"{name} launch")
    if launch["determinism"] not in {"deterministic", "conditionally_deterministic", "nondeterministic"}:
        raise ValueError(f"native manifest {name} determinism is unsupported")
    _version(launch["version"], f"{name} launch version")


def _validate_capability(value: object, label: str) -> None:
    envelope = _exact_mapping(value, _CAPABILITY_KEYS, label)
    if envelope["type"] != "CapabilityEnvelope":
        raise ValueError(f"native manifest {label} has unsupported type")
    for field in ("architectures", "dtypes", "layouts", "modes"):
        values = _string_list(envelope[field], f"{label} {field}", nonempty=True)
    constraints = envelope["constraints"]
    if not isinstance(constraints, list) or len(constraints) > 64:
        raise ValueError(f"native manifest {label} constraints must be bounded")
    codes: list[str] = []
    for index, raw in enumerate(constraints):
        item = _exact_mapping(raw, _DIMENSION_CONSTRAINT_KEYS, f"{label} constraint {index}")
        if item["type"] != "DimensionConstraint":
            raise ValueError(f"native manifest {label} constraint has unsupported type")
        _expression(item["predicate"], f"{label} constraint predicate")
        codes.append(_identifier(item["code"], f"{label} constraint code"))
        _string(item["message"], f"{label} constraint message")
        _version(item["version"], f"{label} constraint version")
    if len(codes) != len(set(codes)):
        raise ValueError(f"native manifest {label} constraint codes must be unique")
    tensor_constraints = envelope["tensor_constraints"]
    if not isinstance(tensor_constraints, list) or len(tensor_constraints) > 64:
        raise ValueError(f"native manifest {label} tensor constraints must be bounded")
    arguments: list[str] = []
    for index, raw in enumerate(tensor_constraints):
        item = _exact_mapping(raw, _TENSOR_CAPABILITY_KEYS, f"{label} tensor constraint {index}")
        if item["type"] != "TensorCapabilityConstraint":
            raise ValueError(f"native manifest {label} tensor constraint has unsupported type")
        arguments.append(_identifier(item["argument"], f"{label} tensor argument"))
        for field in ("dtypes", "layouts", "devices"):
            values = _string_list(item[field], f"{label} tensor {field}")
        ranks = item["ranks"]
        if not isinstance(ranks, list) or any(type(rank) is not int or rank < 0 for rank in ranks):
            raise ValueError(f"native manifest {label} tensor ranks are invalid")
        if ranks != sorted(set(ranks)):
            raise ValueError(f"native manifest {label} tensor ranks must be unique and sorted")
        _version(item["version"], f"{label} tensor constraint version")
    if len(arguments) != len(set(arguments)):
        raise ValueError(f"native manifest {label} tensor arguments must be unique")
    _boolean(envelope["graph_capture_safe"], f"{label} graph_capture_safe")
    _boolean(envelope["training_capable"], f"{label} training_capable")
    _version(envelope["version"], f"{label} version")


def _validate_implementation_candidates(value: object, name: str) -> None:
    if not isinstance(value, list) or len(value) > 64:
        raise ValueError(f"native manifest {name} implementation candidates must be bounded")
    identities: list[tuple[str, int]] = []
    for index, raw in enumerate(value):
        label = f"{name} implementation candidate {index}"
        item = _exact_mapping(raw, _IMPLEMENTATION_CANDIDATE_KEYS, label)
        identity = (
            _identifier(item["name"], f"{label} name"),
            item["version"],
        )
        if type(identity[1]) is not int or identity[1] < 1:
            raise ValueError(f"native manifest {label} version must be positive")
        if item["tier"] not in {"portable", "optimized", "specialized", "hand_specialized"}:
            raise ValueError(f"native manifest {label} tier is unsupported")
        if type(item["priority"]) is not int:
            raise ValueError(f"native manifest {label} priority must be an integer")
        requires = _string_list(item["requires"], f"{label} requires")
        _validate_capability(item["envelope"], f"{label} envelope")
        digest = _digest(item["envelope_digest"], f"{label} envelope_digest")
        if digest != _sha256(item["envelope"]):
            raise ValueError(f"native manifest {label} envelope digest mismatch")
        if item["promoted"] is not False or item["selectable"] is not False:
            raise ValueError(f"native manifest {label} cannot be promoted or selectable")
        identities.append(identity)
    if identities != sorted(identities) or len(identities) != len(set(identities)):
        raise ValueError(f"native manifest {name} implementation identities must be unique and sorted")


def _validate_operator(value: object, index: int) -> dict[str, Any]:
    operator = _exact_mapping(value, _OPERATOR_KEYS, f"operator {index}")
    name = _identifier(operator["name"], f"operator {index} name")
    if operator["namespace"] != NAMESPACE or operator["qualified_name"] != f"{NAMESPACE}::{name}":
        raise ValueError(f"native manifest {name} namespace identity is inconsistent")
    family = _identifier(operator["family"], f"{name} family")
    source = _string(operator["source"], f"{name} source")
    path = PurePosixPath(source)
    if path.is_absolute() or ".." in path.parts or path.parts[-3:] != (family, name, "spec.py"):
        raise ValueError(f"native manifest {name} source is not canonical")
    _digest(operator["spec_sha256"], f"{name} spec_sha256")
    _digest(operator["kernel_spec_digest"], f"{name} kernel_spec_digest")
    _digest(operator["implementation_digest"], f"{name} implementation_digest")
    _validate_implementation_candidates(operator["implementation_candidates"], name)
    schema = _string(operator["operator_schema"], f"{name} operator_schema")
    if not schema.lstrip().startswith(f"{name}("):
        raise ValueError(f"native manifest {name} operator_schema has wrong root")
    facade_outputs = _string_list(operator["facade_outputs"], f"{name} facade_outputs")
    if operator["fake"] is not None:
        _identity(operator["fake"], f"{name} fake")
    forward = _validate_forward(operator["forward"], name)
    backward = _validate_backward(operator["backward"], name)
    composite = _validate_composite(operator["composite"], name)
    policy = operator["autograd_policy"]
    if policy not in {"required", "none", "composite"}:
        raise ValueError(f"native manifest {name} autograd_policy is unsupported")
    if policy == "required" and (backward is None or composite is not None):
        raise ValueError(f"native manifest {name} REQUIRED autograd is incomplete")
    if policy == "none" and (backward is not None or composite is not None):
        raise ValueError(f"native manifest {name} NONE autograd is inconsistent")
    if policy == "composite" and (backward is not None or composite is None):
        raise ValueError(f"native manifest {name} COMPOSITE autograd is incomplete")
    _validate_launcher_plans(operator["launcher_plans"], name, forward, backward)
    _validate_effects(operator["effects"], name)
    _validate_launch(operator["launch"], name)
    _validate_runtime_workload(operator["runtime_workload"], f"{name} runtime_workload")
    if operator["backend"] != "tilelang" or operator["devices"] != ["cuda"]:
        raise ValueError(f"native manifest {name} backend/device contract is unsupported")
    _version(operator["version"], f"{name} version")
    expected_facade = [item["name"] for item in forward["outputs"] if item["visible_in_facade"]]
    if facade_outputs != expected_facade:
        raise ValueError(f"native manifest {name} facade_outputs do not match forward outputs")

    expected_registrations = [
        {"qualified_name": f"{NAMESPACE}::{name}", "schema": schema, "kind": "semantic", "implementation_symbol": forward["symbol"]},
        {"qualified_name": f"{NAMESPACE}::_{name}_fwd", "schema": forward["schema"], "kind": "forward", "implementation_symbol": forward["symbol"]},
    ]
    if backward is not None:
        expected_registrations.append(
            {"qualified_name": f"{NAMESPACE}::_{name}_bwd", "schema": backward["schema"], "kind": "backward", "implementation_symbol": backward["symbol"]}
        )
    registrations = operator["registrations"]
    if not isinstance(registrations, list):
        raise ValueError(f"native manifest {name} registrations must be an array")
    for registration_index, registration in enumerate(registrations):
        _exact_mapping(registration, _REGISTRATION_KEYS, f"{name} registration {registration_index}")
    if registrations != expected_registrations:
        raise ValueError(f"native manifest {name} registrations do not match its contracts")

    return operator


def validate_manifest(value: object) -> dict[str, Any]:
    """Validate and return an exact callable-node schema-v4 manifest."""

    manifest = _exact_mapping(value, _TOP_LEVEL_KEYS, "top level")
    if manifest["generator"] != {"id": GENERATOR_ID, "version": GENERATOR_VERSION}:
        raise ValueError("native manifest generator identity is unsupported")
    constants = {
        "schema_version": 4,
        "namespace": NAMESPACE,
        "registration_mode": REGISTRATION_MODE,
        "optimized_math_authority": "tilelang",
        "runtime_discovery": False,
        "request_time_compilation": False,
    }
    for field, expected in constants.items():
        if manifest[field] != expected:
            raise ValueError(f"native manifest {field} must be exactly {expected!r}")
    for field in ("source_inventory_sha256", "semantic_digest", "manifest_digest"):
        _digest(manifest[field], field)

    raw_operators = manifest["operators"]
    if not isinstance(raw_operators, list) or len(raw_operators) > _MAX_OPERATORS:
        raise ValueError("native manifest operators must be a bounded JSON array")
    operators = [_validate_operator(operator, index) for index, operator in enumerate(raw_operators)]
    qualified_names = [operator["qualified_name"] for operator in operators]
    if qualified_names != sorted(qualified_names) or len(set(qualified_names)) != len(qualified_names):
        raise ValueError("native manifest operators must be unique and sorted by qualified_name")
    for field in ("source", "spec_sha256", "kernel_spec_digest"):
        identities = [operator[field] for operator in operators]
        if len(identities) != len(set(identities)):
            raise ValueError(f"native manifest operator {field} identities must be unique")
    builders = [operator["forward"]["builder"] for operator in operators]
    builders += [operator["backward"]["builder"] for operator in operators if operator["backward"] is not None]
    symbols = [operator["forward"]["symbol"] for operator in operators]
    symbols += [operator["backward"]["symbol"] for operator in operators if operator["backward"] is not None]
    if len(builders) != len(set(builders)) or len(symbols) != len(set(symbols)):
        raise ValueError("native manifest provider builders and symbols must be unique")

    source_inventory = [
        {"source": operator["source"], "spec_sha256": operator["spec_sha256"], "kernel_spec_digest": operator["kernel_spec_digest"], "implementation_digest": operator["implementation_digest"]}
        for operator in sorted(operators, key=lambda item: item["source"])
    ]
    if manifest["source_inventory_sha256"] != _sha256(source_inventory):
        raise ValueError("native manifest source inventory digest does not match operators")
    semantic_inventory = [
        {"qualified_name": operator["qualified_name"], "kernel_spec_digest": operator["kernel_spec_digest"]}
        for operator in operators
    ]
    if manifest["semantic_digest"] != _sha256(semantic_inventory):
        raise ValueError("native manifest semantic digest does not match operators")
    manifest_body = {key: item for key, item in manifest.items() if key != "manifest_digest"}
    if manifest["manifest_digest"] != _sha256(manifest_body):
        raise ValueError("native manifest manifest_digest does not match canonical content")
    return manifest


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"native manifest contains duplicate JSON key {key!r}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"native manifest contains unsupported JSON constant {value!r}")


def load_manifest(native_root: Path | None = None) -> dict[str, Any]:
    """Load the committed manifest without discovery, generation, or compilation."""

    root = native_root or Path(__file__).resolve().parents[1]
    path = root / "generated" / "native_ops.json"
    try:
        if path.stat().st_size > _MAX_MANIFEST_BYTES:
            raise ValueError(f"native operator manifest {path} exceeds {_MAX_MANIFEST_BYTES} bytes")
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
    except FileNotFoundError:
        raise
    except ValueError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot load native operator manifest {path}: {exc}") from exc
    return validate_manifest(value)
