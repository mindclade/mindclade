from pathlib import Path
import json

import jsonschema
import pytest

from kernels.native.codegen.generate import render_all

ROOT = Path(__file__).resolve().parents[1]


def _fixture_manifest(tmp_path: Path) -> dict:
    kernels_root = tmp_path / "kernels"
    native_root = kernels_root / "native"
    native_root.mkdir(parents=True)
    operation = kernels_root / "family_a" / "fixture_op"
    operation.mkdir(parents=True)
    (operation / "spec.py").write_text(
        '''from kernels.api import (
    AutogradPolicy, EffectSpec, ForwardSpec, KernelSpec, LaunchContract,
    OutputSpec, SameAsInputDType, SameAsInputDevice, ShapeOf,
)
KERNEL_SPEC: KernelSpec = KernelSpec(
    name="fixture_op", namespace="mindclade", family="family_a",
    source="family_a/fixture_op/spec.py",
    operator_schema="fixture_op(Tensor x) -> Tensor output",
    facade_outputs=("output",), fake="kernels.family_a.fixture_op.reference:fake",
    forward=ForwardSpec(
        schema="_fixture_op_fwd(Tensor x) -> Tensor output",
        builder="kernels.family_a.fixture_op.tilelang:build_tilelang_program",
        symbol="mindclade_tilelang_fixture_op_fwd_launch",
        outputs=(OutputSpec(
            name="output", shape=ShapeOf(argument="x"),
            dtype=SameAsInputDType(argument="x"), device=SameAsInputDevice(argument="x"),
            semantic_axes=("element",), visible_in_facade=True, saved_for_backward=False,
        ),),
    ), backward=None, autograd_policy=AutogradPolicy.NONE,
    effects=EffectSpec(), launch=LaunchContract(graph_capture_safe=False),
)
''', encoding="utf-8")
    return json.loads(render_all(native_root, source_files=["family_a/fixture_op/spec.py"])["native_ops.json"])


def _validator() -> jsonschema.Draft202012Validator:
    schema = json.loads((ROOT / "manifests" / "native_ops.schema.json").read_text())
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(schema)


def _with_backward_bindings(manifest: dict) -> dict:
    manifest["operators"][0]["backward"] = {
        "type": "BackwardSpec",
        "schema": (
            "_fixture_op_bwd(Tensor grad_output, Tensor? grad_aux, Tensor x, "
            "Tensor output, bool need_x_grad) -> Tensor grad_x"
        ),
        "builder": "kernels.family_a.fixture_op.tilelang:build_backward",
        "symbol": "mindclade_tilelang_fixture_op_bwd_launch",
        "argument_bindings": [
            {
                "type": "BackwardArgumentBinding",
                "provider_argument": "grad_output",
                "source": "output_gradient",
                "source_name": "output",
                "missing": "zero",
                "version": 1,
            },
            {
                "type": "BackwardArgumentBinding",
                "provider_argument": "grad_aux",
                "source": "output_gradient",
                "source_name": "auxiliary",
                "missing": "pass_none",
                "version": 1,
            },
            {
                "type": "BackwardArgumentBinding",
                "provider_argument": "need_x_grad",
                "source": "needs_input_grad",
                "source_name": "x",
                "missing": "error",
                "version": 1,
            },
            {
                "type": "BackwardArgumentBinding",
                "provider_argument": "output",
                "source": "forward_output",
                "source_name": "output",
                "missing": "error",
                "version": 1,
            },
            {
                "type": "BackwardArgumentBinding",
                "provider_argument": "x",
                "source": "operator_argument",
                "source_name": "x",
                "missing": "error",
                "version": 1,
            },
        ],
        "gradients": [
            {
                "type": "GradientSpec",
                "input_name": "x",
                "output_name": "grad_x",
                "optional": False,
                "accumulation_dtype": None,
                "version": 1,
            }
        ],
        "supports_double_backward": False,
        "program_group": None,
        "version": 1,
    }
    return manifest


def _program_group() -> dict:
    return {
        "type": "ProgramGroupSpec",
        "nodes": [
            {
                "type": "ProgramNodeSpec",
                "name": "produce",
                "builder": "kernels.family_a.fixture_op.tilelang:build_produce",
                "symbol": "mindclade_tilelang_fixture_op_produce_launch",
                "depends_on": [],
                "workspace_uses": [
                    {
                        "type": "WorkspaceUseSpec",
                        "workspace": "scratch",
                        "access": "write",
                        "version": 1,
                    }
                ],
                "version": 1,
            },
            {
                "type": "ProgramNodeSpec",
                "name": "consume",
                "builder": "kernels.family_a.fixture_op.tilelang:build_consume",
                "symbol": "mindclade_tilelang_fixture_op_consume_launch",
                "depends_on": ["produce"],
                "workspace_uses": [
                    {
                        "type": "WorkspaceUseSpec",
                        "workspace": "scratch",
                        "access": "read_write",
                        "version": 1,
                    }
                ],
                "version": 1,
            },
        ],
        "workspaces": [
            {
                "type": "WorkspaceSpec",
                "name": "scratch",
                "shape": {
                    "node": "shape_tuple",
                    "dimensions": [
                        {"node": "dim_ref", "argument": "x", "axis": 0}
                    ],
                },
                "dtype": {"node": "constant_dtype", "value": "float32"},
                "zero_initialize": True,
                "lifetime": "program_group",
                "version": 1,
            }
        ],
        "version": 1,
    }


def _launcher_plan(phase: str) -> dict:
    group = _program_group()
    logical_symbol = f"mindclade_tilelang_fixture_op_{phase}_launch"
    return {
        "phase": phase,
        "logical_symbol": logical_symbol,
        "bridge_requirement": "mindclade_program_group_bridge_v1",
        "execution_order": ["produce", "consume"],
        "required_private_symbols": [
            node["symbol"] for node in group["nodes"]
        ],
        "nodes": [
            {
                "name": node["name"],
                "symbol": node["symbol"],
                "depends_on": node["depends_on"],
                "workspace_uses": [
                    {
                        "workspace": use["workspace"],
                        "access": use["access"],
                    }
                    for use in node["workspace_uses"]
                ],
            }
            for node in group["nodes"]
        ],
        "workspaces": [
            {
                key: workspace[key]
                for key in (
                    "name",
                    "shape",
                    "dtype",
                    "zero_initialize",
                    "lifetime",
                )
            }
            for workspace in group["workspaces"]
        ],
    }


def test_generated_manifest_validates_against_strict_v3_schema():
    manifest = json.loads((ROOT / "generated" / "native_ops.json").read_text())
    _validator().validate(manifest)


def test_schema_rejects_additional_properties_recursively(tmp_path: Path):
    validator = _validator()
    manifest = _fixture_manifest(tmp_path)
    manifest["unexpected"] = True
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(manifest)
    manifest = _fixture_manifest(tmp_path / "contract")
    manifest["operators"][0]["forward"]["outputs"][0]["shape"]["unexpected"] = True
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(manifest)


def test_schema_rejects_non_mindclade_identity_and_registration_order(tmp_path: Path):
    validator = _validator()
    manifest = _fixture_manifest(tmp_path)
    manifest["operators"][0]["namespace"] = "other"
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(manifest)
    manifest = _fixture_manifest(tmp_path / "order")
    manifest["operators"][0]["registrations"].reverse()
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(manifest)


def test_schema_accepts_exact_named_backward_argument_bindings(tmp_path: Path):
    manifest = _with_backward_bindings(_fixture_manifest(tmp_path))
    _validator().validate(manifest)


@pytest.mark.parametrize(
    ("field", "invalid"),
    (
        ("source", "runtime_lookup"),
        ("missing", "materialize_implicitly"),
        ("type", "PositionalBackwardBinding"),
        ("version", 2),
    ),
)
def test_schema_rejects_invalid_named_backward_binding_values(
    tmp_path: Path, field: str, invalid: object
):
    manifest = _with_backward_bindings(_fixture_manifest(tmp_path))
    manifest["operators"][0]["backward"]["argument_bindings"][0][field] = invalid
    with pytest.raises(jsonschema.ValidationError):
        _validator().validate(manifest)


def test_schema_rejects_unknown_named_backward_binding_fields(tmp_path: Path):
    manifest = _with_backward_bindings(_fixture_manifest(tmp_path))
    binding = manifest["operators"][0]["backward"]["argument_bindings"][0]
    binding["runtime_expression"] = "ctx.saved_tensors[0]"
    with pytest.raises(jsonschema.ValidationError):
        _validator().validate(manifest)


def test_schema_rejects_missing_named_backward_binding_fields(tmp_path: Path):
    manifest = _with_backward_bindings(_fixture_manifest(tmp_path))
    binding = manifest["operators"][0]["backward"]["argument_bindings"][0]
    del binding["source_name"]
    with pytest.raises(jsonschema.ValidationError):
        _validator().validate(manifest)


def test_schema_accepts_forward_and_backward_program_groups(tmp_path: Path):
    manifest = _with_backward_bindings(_fixture_manifest(tmp_path))
    manifest["operators"][0]["forward"]["program_group"] = _program_group()
    manifest["operators"][0]["backward"]["program_group"] = _program_group()
    manifest["operators"][0]["launcher_plans"] = {
        "forward": _launcher_plan("forward"),
        "backward": _launcher_plan("backward"),
    }
    _validator().validate(manifest)


@pytest.mark.parametrize(
    ("contract", "field"),
    (
        ("group", "workspaces"),
        ("node", "workspace_uses"),
        ("workspace", "shape"),
        ("use", "access"),
    ),
)
def test_schema_rejects_missing_program_group_fields(
    tmp_path: Path, contract: str, field: str
):
    manifest = _fixture_manifest(tmp_path)
    group = _program_group()
    target = {
        "group": group,
        "node": group["nodes"][0],
        "workspace": group["workspaces"][0],
        "use": group["nodes"][0]["workspace_uses"][0],
    }[contract]
    del target[field]
    manifest["operators"][0]["forward"]["program_group"] = group
    with pytest.raises(jsonschema.ValidationError):
        _validator().validate(manifest)


@pytest.mark.parametrize("contract", ("group", "node", "workspace", "use"))
def test_schema_rejects_extra_program_group_fields(
    tmp_path: Path, contract: str
):
    manifest = _fixture_manifest(tmp_path)
    group = _program_group()
    target = {
        "group": group,
        "node": group["nodes"][0],
        "workspace": group["workspaces"][0],
        "use": group["nodes"][0]["workspace_uses"][0],
    }[contract]
    target["runtime_expression"] = "prohibited"
    manifest["operators"][0]["forward"]["program_group"] = group
    with pytest.raises(jsonschema.ValidationError):
        _validator().validate(manifest)


@pytest.mark.parametrize(
    ("contract", "field", "invalid"),
    (
        ("group", "type", "RuntimeProgramGroup"),
        ("group", "version", 2),
        ("node", "type", "RuntimeProgramNode"),
        ("node", "version", 2),
        ("workspace", "type", "RuntimeWorkspace"),
        ("workspace", "version", 2),
        ("workspace", "lifetime", "process"),
        ("use", "type", "RuntimeWorkspaceUse"),
        ("use", "version", 2),
        ("use", "access", "execute"),
    ),
)
def test_schema_rejects_invalid_program_group_contract_values(
    tmp_path: Path, contract: str, field: str, invalid: object
):
    manifest = _fixture_manifest(tmp_path)
    group = _program_group()
    target = {
        "group": group,
        "node": group["nodes"][0],
        "workspace": group["workspaces"][0],
        "use": group["nodes"][0]["workspace_uses"][0],
    }[contract]
    target[field] = invalid
    manifest["operators"][0]["forward"]["program_group"] = group
    with pytest.raises(jsonschema.ValidationError):
        _validator().validate(manifest)


def test_schema_rejects_empty_or_oversized_program_group_arrays(tmp_path: Path):
    validator = _validator()
    for field in ("nodes",):
        manifest = _fixture_manifest(tmp_path / f"empty-{field}")
        group = _program_group()
        group[field] = []
        manifest["operators"][0]["forward"]["program_group"] = group
        with pytest.raises(jsonschema.ValidationError):
            validator.validate(manifest)
    for field, item in (
        ("nodes", _program_group()["nodes"][0]),
        ("workspaces", _program_group()["workspaces"][0]),
    ):
        manifest = _fixture_manifest(tmp_path / f"oversized-{field}")
        group = _program_group()
        group[field] = [dict(item, name=f"item_{index}") for index in range(65)]
        manifest["operators"][0]["forward"]["program_group"] = group
        with pytest.raises(jsonschema.ValidationError):
            validator.validate(manifest)


@pytest.mark.parametrize(
    ("field", "invalid"),
    (
        ("shape", []),
        ("dtype", []),
        ("shape", {"node": "constant_dtype", "value": "float32"}),
        ("dtype", {"node": "shape_of", "argument": "x"}),
    ),
)
def test_schema_rejects_invalid_workspace_expression_domains(
    tmp_path: Path, field: str, invalid: object
):
    manifest = _fixture_manifest(tmp_path)
    group = _program_group()
    group["workspaces"][0][field] = invalid
    manifest["operators"][0]["forward"]["program_group"] = group
    with pytest.raises(jsonschema.ValidationError):
        _validator().validate(manifest)


@pytest.mark.parametrize(
    ("location", "field"),
    (
        ("plans", "backward"),
        ("plan", "execution_order"),
        ("node", "workspace_uses"),
        ("workspace", "shape"),
        ("use", "access"),
    ),
)
def test_schema_rejects_missing_launcher_plan_fields(
    tmp_path: Path, location: str, field: str
):
    manifest = _fixture_manifest(tmp_path)
    manifest["operators"][0]["launcher_plans"] = {
        "forward": _launcher_plan("forward"),
        "backward": None,
    }
    plan = manifest["operators"][0]["launcher_plans"]["forward"]
    target = {
        "plans": manifest["operators"][0]["launcher_plans"],
        "plan": plan,
        "node": plan["nodes"][0],
        "workspace": plan["workspaces"][0],
        "use": plan["nodes"][0]["workspace_uses"][0],
    }[location]
    del target[field]
    with pytest.raises(jsonschema.ValidationError):
        _validator().validate(manifest)


@pytest.mark.parametrize("location", ("plans", "plan", "node", "workspace", "use"))
def test_schema_rejects_extra_launcher_plan_fields(
    tmp_path: Path, location: str
):
    manifest = _fixture_manifest(tmp_path)
    manifest["operators"][0]["launcher_plans"] = {
        "forward": _launcher_plan("forward"),
        "backward": None,
    }
    plan = manifest["operators"][0]["launcher_plans"]["forward"]
    target = {
        "plans": manifest["operators"][0]["launcher_plans"],
        "plan": plan,
        "node": plan["nodes"][0],
        "workspace": plan["workspaces"][0],
        "use": plan["nodes"][0]["workspace_uses"][0],
    }[location]
    target["builder"] = "prohibited"
    with pytest.raises(jsonschema.ValidationError):
        _validator().validate(manifest)


@pytest.mark.parametrize(
    ("field", "invalid"),
    (
        ("phase", "training"),
        ("logical_symbol", "not a symbol"),
        ("bridge_requirement", "unreviewed_bridge_v2"),
    ),
)
def test_schema_rejects_invalid_launcher_plan_contract_values(
    tmp_path: Path, field: str, invalid: object
):
    manifest = _fixture_manifest(tmp_path)
    plan = _launcher_plan("forward")
    plan[field] = invalid
    manifest["operators"][0]["launcher_plans"] = {
        "forward": plan,
        "backward": None,
    }
    with pytest.raises(jsonschema.ValidationError):
        _validator().validate(manifest)


@pytest.mark.parametrize(
    "field", ("execution_order", "required_private_symbols", "nodes")
)
def test_schema_rejects_empty_launcher_plan_execution_arrays(
    tmp_path: Path, field: str
):
    manifest = _fixture_manifest(tmp_path)
    plan = _launcher_plan("forward")
    plan[field] = []
    manifest["operators"][0]["launcher_plans"] = {
        "forward": plan,
        "backward": None,
    }
    with pytest.raises(jsonschema.ValidationError):
        _validator().validate(manifest)
