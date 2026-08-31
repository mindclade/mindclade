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
GENERATOR_VERSION = 5
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
    "kernel_spec_digest", "operator_schema", "facade_outputs", "fake", "forward",
    "backward", "autograd_policy", "composite", "effects", "launch", "backend",
    "version", "devices", "registrations", "launcher_plans",
}
_REGISTRATION_KEYS = {"qualified_name", "schema", "kind", "implementation_symbol"}
_FORWARD_KEYS = {"type", "schema", "builder", "symbol", "outputs", "program_group", "version"}
_BACKWARD_KEYS = {
    "type", "schema", "builder", "symbol", "gradients", "supports_double_backward",
    "program_group", "version",
}
_OUTPUT_KEYS = {
    "type", "name", "shape", "dtype", "device", "semantic_axes",
    "visible_in_facade", "saved_for_backward", "initialization", "version",
}
_INITIALIZATION_KEYS = {"type", "mode", "value", "version"}
_GRADIENT_KEYS = {
    "type", "input_name", "output_name", "optional", "accumulation_dtype", "version",
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
    "type", "nodes", "workspaces", "version",
}
_PROGRAM_NODE_KEYS = {
    "type", "name", "builder", "symbol", "depends_on", "workspace_uses", "version",
}
_WORKSPACE_USE_KEYS = {"type", "workspace", "access", "version"}
_WORKSPACE_KEYS = {
    "type", "name", "shape", "dtype", "zero_initialize", "lifetime", "version",
}
_LAUNCHER_PLANS_KEYS = {"forward", "backward"}
_LAUNCHER_PLAN_KEYS = {
    "phase", "logical_symbol", "bridge_requirement", "execution_order",
    "required_private_symbols", "nodes", "workspaces",
}


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
    if item["accumulation_dtype"] is not None:
        _string(item["accumulation_dtype"], f"{label} accumulation_dtype")
    _version(item["version"], f"{label} version")
    return mapping


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
        depends_on = _string_list(node["depends_on"], f"{node_label} depends_on")
        uses = node["workspace_uses"]
        if not isinstance(uses, list):
            raise ValueError(f"native manifest {node_label} workspace_uses must be an array")
        used_workspaces: list[str] = []
        for use_index, raw_use in enumerate(uses):
            use_label = f"{node_label} workspace use {use_index}"
            use = _exact_mapping(raw_use, _WORKSPACE_USE_KEYS, use_label)
            if use["type"] != "WorkspaceUseSpec":
                raise ValueError(f"native manifest {use_label} has unsupported type")
            used_workspaces.append(_identifier(use["workspace"], f"{use_label} workspace"))
            if use["access"] not in {"read", "write", "read_write"}:
                raise ValueError(f"native manifest {use_label} has unsupported access")
            _version(use["version"], f"{use_label} version")
        if len(used_workspaces) != len(set(used_workspaces)):
            raise ValueError(f"native manifest {node_label} workspace uses must be unique")
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
        "bridge_requirement": "mindclade_program_group_bridge_v1",
        "execution_order": [node["name"] for node in group["nodes"]],
        "required_private_symbols": [node["symbol"] for node in group["nodes"]],
        "nodes": [
            {
                "name": node["name"],
                "symbol": node["symbol"],
                "depends_on": node["depends_on"],
                "workspace_uses": [
                    {"workspace": use["workspace"], "access": use["access"]}
                    for use in node["workspace_uses"]
                ],
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
        if initialization["mode"] not in {"zero", "value", "uninitialized"}:
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
    """Validate and return an exact schema-v3 manifest."""

    manifest = _exact_mapping(value, _TOP_LEVEL_KEYS, "top level")
    if manifest["generator"] != {"id": GENERATOR_ID, "version": GENERATOR_VERSION}:
        raise ValueError("native manifest generator identity is unsupported")
    constants = {
        "schema_version": 3,
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
        {"source": operator["source"], "spec_sha256": operator["spec_sha256"], "kernel_spec_digest": operator["kernel_spec_digest"]}
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
