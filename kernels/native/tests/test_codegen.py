import json
from pathlib import Path

import pytest

from kernels.api import content_digest
from kernels.native.codegen.generate import GENERATED_FILENAMES, render_all, write_outputs
from kernels.native.tilelang.manifest import validate_manifest


def _fixture_native_root(tmp_path: Path, *, fake: bool = True) -> tuple[Path, str]:
    kernels_root = tmp_path / "kernels"
    native_root = kernels_root / "native"
    native_root.mkdir(parents=True)
    operation = kernels_root / "pairformer" / "fixture_op"
    operation.mkdir(parents=True)
    fake_value = '"kernels.pairformer.fixture_op.reference:fake"' if fake else "None"
    (operation / "spec.py").write_text(
        f'''from kernels.api import (
    AutogradPolicy, BoolLiteral, CapabilityEnvelope, ConstantDType,
    DimensionConstraint, EffectSpec, ForwardSpec, ImplementationSpec,
    ImplementationTier, KernelSpec, LaunchContract, OutputSpec, ShapeOf,
    SameAsInputDevice, TensorCapabilityConstraint,
)
KERNEL_SPEC: KernelSpec = KernelSpec(
    name="fixture_op", namespace="mindclade", family="pairformer",
    source="pairformer/fixture_op/spec.py",
    operator_schema="fixture_op(Tensor x, int width) -> Tensor output",
    facade_outputs=("output",), fake={fake_value},
    forward=ForwardSpec(
        schema="_fixture_op_fwd(Tensor x, int width) -> Tensor output",
        builder="kernels.pairformer.fixture_op.tilelang:build_tilelang_program",
        symbol="mindclade_tilelang_fixture_op_fwd_launch",
        outputs=(OutputSpec(
            name="output", shape=ShapeOf(argument="x"),
            dtype=ConstantDType(value="float32"),
            device=SameAsInputDevice(argument="x"), semantic_axes=("element",),
            visible_in_facade=True, saved_for_backward=False,
        ),),
    ), backward=None, autograd_policy=AutogradPolicy.NONE,
    effects=EffectSpec(), launch=LaunchContract(graph_capture_safe=False),
)
IMPLEMENTATION_SPECS = (
    ImplementationSpec(
        operation="fixture_op", name="portable", family="pairformer",
        backend="tilelang",
        builder="kernels.pairformer.fixture_op.tilelang:build_implementation",
        version=1, tier=ImplementationTier.PORTABLE, requires=("cuda",),
        envelope=CapabilityEnvelope(
            architectures=("sm90",), dtypes=("float32",),
            layouts=("contiguous",), modes=("default",),
            constraints=(DimensionConstraint(
                predicate=BoolLiteral(value=True), code="VALID",
                message="fixture capability",
            ),),
            graph_capture_safe=False, training_capable=False,
            tensor_constraints=(TensorCapabilityConstraint(
                argument="x", dtypes=("float32",), layouts=("contiguous",),
                devices=("cuda",), ranks=(1,),
            ),),
        ),
    ),
)
''',
        encoding="utf-8",
    )
    return native_root, "pairformer/fixture_op/spec.py"


def _required_fixture_native_root(tmp_path: Path) -> tuple[Path, str]:
    kernels_root = tmp_path / "kernels"
    native_root = kernels_root / "native"
    native_root.mkdir(parents=True)
    operation = kernels_root / "pairformer" / "required_fixture"
    operation.mkdir(parents=True)
    (operation / "spec.py").write_text(
        '''from kernels.api import (
    AutogradPolicy, BackwardArgumentBinding, BackwardArgumentSource,
    BackwardSpec, ConstantDType, EffectSpec, ForwardSpec, GradientSpec,
    KernelSpec, LaunchContract, MissingGradientPolicy, OutputSpec, ShapeOf,
    SameAsInputDevice,
)
KERNEL_SPEC: KernelSpec = KernelSpec(
    name="required_fixture", namespace="mindclade", family="pairformer",
    source="pairformer/required_fixture/spec.py",
    operator_schema="required_fixture(Tensor x, Tensor y, int width) -> Tensor output",
    facade_outputs=("output",), fake=None,
    forward=ForwardSpec(
        schema="_required_fixture_fwd(Tensor x, Tensor y, int width) -> Tensor output",
        builder="kernels.pairformer.required_fixture.tilelang:build_forward",
        symbol="mindclade_tilelang_required_fixture_fwd_launch",
        outputs=(OutputSpec(
            name="output", shape=ShapeOf(argument="x"),
            dtype=ConstantDType(value="float32"),
            device=SameAsInputDevice(argument="x"), semantic_axes=("element",),
            visible_in_facade=True, saved_for_backward=True,
        ),),
    ),
    backward=BackwardSpec(
        schema="_required_fixture_bwd(Tensor x, bool need_y_grad, Tensor grad_output, Tensor output, int width, Tensor y, bool need_x_grad) -> (Tensor grad_y, Tensor grad_x)",
        builder="kernels.pairformer.required_fixture.tilelang:build_backward",
        symbol="mindclade_tilelang_required_fixture_bwd_launch",
        argument_bindings=(
            BackwardArgumentBinding(
                provider_argument="width",
                source=BackwardArgumentSource.OPERATOR_ARGUMENT,
                source_name="width",
            ),
            BackwardArgumentBinding(
                provider_argument="y",
                source=BackwardArgumentSource.OPERATOR_ARGUMENT,
                source_name="y",
            ),
            BackwardArgumentBinding(
                provider_argument="need_y_grad",
                source=BackwardArgumentSource.NEEDS_INPUT_GRAD,
                source_name="y",
            ),
            BackwardArgumentBinding(
                provider_argument="output",
                source=BackwardArgumentSource.FORWARD_OUTPUT,
                source_name="output",
            ),
            BackwardArgumentBinding(
                provider_argument="grad_output",
                source=BackwardArgumentSource.OUTPUT_GRADIENT,
                source_name="output",
                missing=MissingGradientPolicy.ERROR,
            ),
            BackwardArgumentBinding(
                provider_argument="need_x_grad",
                source=BackwardArgumentSource.NEEDS_INPUT_GRAD,
                source_name="x",
            ),
            BackwardArgumentBinding(
                provider_argument="x",
                source=BackwardArgumentSource.OPERATOR_ARGUMENT,
                source_name="x",
            ),
        ),
        gradients=(
            GradientSpec(input_name="x", output_name="grad_x"),
            GradientSpec(input_name="y", output_name="grad_y"),
        ),
        supports_double_backward=False,
    ),
    autograd_policy=AutogradPolicy.REQUIRED,
    effects=EffectSpec(), launch=LaunchContract(graph_capture_safe=False),
)
IMPLEMENTATION_SPECS = ()
''',
        encoding="utf-8",
    )
    return native_root, "pairformer/required_fixture/spec.py"


def _program_group_fixture_native_root(tmp_path: Path) -> tuple[Path, str]:
    kernels_root = tmp_path / "kernels"
    native_root = kernels_root / "native"
    native_root.mkdir(parents=True)
    operation = kernels_root / "pairformer" / "group_fixture"
    operation.mkdir(parents=True)
    (operation / "spec.py").write_text(
        '''from kernels.api import (
    AutogradPolicy, ConstantDType, EffectSpec, ForwardSpec, KernelSpec,
    LaunchContract, OutputSpec, ProgramGroupSpec, ProgramNodeSpec, ShapeOf,
    SameAsInputDevice, WorkspaceAccess, WorkspaceLifetime, WorkspaceSpec,
    WorkspaceUseSpec,
)
KERNEL_SPEC: KernelSpec = KernelSpec(
    name="group_fixture", namespace="mindclade", family="pairformer",
    source="pairformer/group_fixture/spec.py",
    operator_schema="group_fixture(Tensor x) -> Tensor output",
    facade_outputs=("output",), fake=None,
    forward=ForwardSpec(
        schema="_group_fixture_fwd(Tensor x) -> Tensor output",
        builder="kernels.pairformer.group_fixture.tilelang:build_forward",
        symbol="mindclade_tilelang_group_fixture_fwd_launch",
        outputs=(OutputSpec(
            name="output", shape=ShapeOf(argument="x"),
            dtype=ConstantDType(value="float32"),
            device=SameAsInputDevice(argument="x"), semantic_axes=("element",),
            visible_in_facade=True, saved_for_backward=False,
        ),),
        program_group=ProgramGroupSpec(
            nodes=(
                ProgramNodeSpec(
                    name="reduce",
                    builder="kernels.pairformer.group_fixture.tilelang:build_reduce",
                    symbol="mindclade_tilelang_group_fixture_reduce_launch",
                    depends_on=("load",),
                    workspace_uses=(WorkspaceUseSpec(
                        workspace="scratch", access=WorkspaceAccess.READ,
                    ),),
                ),
                ProgramNodeSpec(
                    name="load",
                    builder="kernels.pairformer.group_fixture.tilelang:build_load",
                    symbol="mindclade_tilelang_group_fixture_load_launch",
                    workspace_uses=(WorkspaceUseSpec(
                        workspace="scratch", access=WorkspaceAccess.WRITE,
                    ),),
                ),
            ),
            workspaces=(WorkspaceSpec(
                name="scratch", shape=ShapeOf(argument="x"),
                dtype=ConstantDType(value="float32"), zero_initialize=False,
                lifetime=WorkspaceLifetime.PROGRAM_GROUP,
            ),),
        ),
    ), backward=None, autograd_policy=AutogradPolicy.NONE,
    effects=EffectSpec(),
    launch=LaunchContract(
        hidden_device_allocation=True, graph_capture_safe=False,
    ),
)
IMPLEMENTATION_SPECS = ()
''',
        encoding="utf-8",
    )
    return native_root, "pairformer/group_fixture/spec.py"


def test_render_is_deterministic_and_write_emits_exact_surfaces(tmp_path: Path):
    native_root, source = _fixture_native_root(tmp_path)
    first = render_all(native_root, source_files=[source])
    assert first == render_all(native_root, source_files=[source])
    output = tmp_path / "output"
    write_outputs(first, output)
    assert set(GENERATED_FILENAMES) == {path.name for path in output.iterdir()}
    assert all((output / name).read_text(encoding="utf-8") == first[name] for name in first)


def test_generated_schema_registry_and_build_inventories_are_v3(tmp_path: Path):
    native_root, source = _fixture_native_root(tmp_path)
    rendered = render_all(native_root, source_files=[source])
    definitions = rendered["registration.generated.cpp"]
    implementations = rendered["operation_registry.generated.cpp"]
    assert definitions.index('m.def("fixture_op(') < definitions.index('m.def("_fixture_op_fwd(')
    assert 'm.impl("fixture_op"' in implementations
    assert 'm.impl("_fixture_op_fwd"' in implementations
    assert "mindclade_tilelang_fixture_op_fwd_launch" in implementations
    assert "MINDCLADE_TILELANG_REQUIRED_LOGICAL_SYMBOLS" in rendered["native_ops.generated.bzl"]
    assert "mindclade_tilelang_fixture_op_fwd_launch" in rendered["native_ops.generated.cmake"]
    assert "MINDCLADE_KERNEL_SPEC_SOURCES" in rendered["native_ops.generated.bzl"]
    assert "//kernels/pairformer/fixture_op:spec.py" in rendered["native_ops.generated.bzl"]
    assert "MINDCLADE_TILELANG_KERNEL_SOURCES" in rendered["native_ops.generated.cmake"]


def test_manifest_has_exact_operator_keys_and_recomputable_digests(tmp_path: Path):
    native_root, source = _fixture_native_root(tmp_path)
    manifest = json.loads(render_all(native_root, source_files=[source])["native_ops.json"])
    assert manifest["schema_version"] == 3
    assert manifest["generator"] == {"id": "kernels.native.codegen.generate", "version": 7}
    operator = manifest["operators"][0]
    assert set(operator) == {
        "name", "qualified_name", "namespace", "family", "source", "spec_sha256",
        "kernel_spec_digest", "implementation_digest", "implementation_candidates",
        "operator_schema", "facade_outputs", "fake", "forward",
        "backward", "autograd_policy", "composite", "effects", "launch", "backend",
        "version", "devices", "registrations",
        "launcher_plans",
    }
    assert [entry["kind"] for entry in operator["registrations"]] == ["semantic", "forward"]
    candidate = operator["implementation_candidates"][0]
    assert candidate["name"] == "portable"
    assert candidate["promoted"] is False
    assert candidate["selectable"] is False
    assert candidate["envelope"]["constraints"][0]["predicate"] == {
        "node": "bool_literal", "value": True,
    }
    assert candidate["envelope_digest"] == content_digest(candidate["envelope"])
    without_digest = dict(manifest)
    assert without_digest.pop("manifest_digest") == content_digest(without_digest)
    assert operator["forward"]["outputs"][0]["shape"]["node"] == "shape_of"


def test_declarative_fake_and_explicit_non_differentiability_are_generated(tmp_path: Path):
    native_root, source = _fixture_native_root(tmp_path, fake=False)
    python = render_all(native_root, source_files=[source])["python_registration_generated.py"]
    assert "torch.empty(" in python
    assert "_mindclade_dtype(" in python
    assert "float32" in python
    assert "mindclade::fixture_op is non-differentiable" in python
    assert "importlib" not in python


def test_required_autograd_is_assembled_from_named_bindings(tmp_path: Path):
    native_root, source = _required_fixture_native_root(tmp_path)
    rendered = render_all(native_root, source_files=[source])
    python = rendered["python_registration_generated.py"]
    manifest = json.loads(rendered["native_ops.json"])
    compile(python, "python_registration_generated.py", "exec")

    assert "def _mindclade_required_setup_context_0(ctx, inputs, output):" in python
    assert "ctx.set_materialize_grads(False)" in python
    assert "ctx.save_for_backward(inputs[0], inputs[1], output_values[0])" in python
    assert "ctx._mindclade_saved_scalars_0 = (inputs[2],)" in python
    assert "if torch.is_grad_enabled():" in python
    assert "does not support double backward" in python
    assert "output_gradient_output = grad_outputs[0]" in python
    assert "ctx.needs_input_grad[0]" in python
    assert '''torch.ops.mindclade._required_fixture_bwd(
        saved_tensor_0,
        ctx.needs_input_grad[1],
        output_gradient_output,
        saved_tensor_2,
        saved_scalar_0,
        saved_tensor_1,
        ctx.needs_input_grad[0],
    )''' in python
    assert "raw_values[1] if ctx.needs_input_grad[0] else None" in python
    assert "raw_values[0] if ctx.needs_input_grad[1] else None" in python
    assert "return (torch.empty_like(y), torch.empty_like(x))" in python
    assert "torch.library.register_fake('mindclade::_required_fixture_bwd')" in python
    assert "torch.library.register_autograd('mindclade::required_fixture'" in python
    backward = manifest["operators"][0]["backward"]
    assert validate_manifest(manifest) is manifest
    assert [binding["provider_argument"] for binding in backward["argument_bindings"]] == [
        "grad_output", "need_x_grad", "need_y_grad", "output", "width", "x", "y",
    ]


def test_required_autograd_executes_named_provider_and_rejects_double_backward(
    tmp_path: Path,
):
    torch = pytest.importorskip("torch")
    native_root, source = _required_fixture_native_root(tmp_path)
    generated = render_all(native_root, source_files=[source])[
        "python_registration_generated.py"
    ]

    definitions = torch.library.Library("mindclade", "FRAGMENT")
    definitions.define("required_fixture(Tensor x, Tensor y, int width) -> Tensor output")
    definitions.define("_required_fixture_fwd(Tensor x, Tensor y, int width) -> Tensor output")
    definitions.define(
        "_required_fixture_bwd(Tensor x, bool need_y_grad, Tensor grad_output, "
        "Tensor output, int width, Tensor y, bool need_x_grad) -> "
        "(Tensor grad_y, Tensor grad_x)"
    )
    cpu = torch.library.Library("mindclade", "IMPL", "CPU")
    cpu.impl("required_fixture", lambda x, y, width: x * y * width)
    cpu.impl("_required_fixture_fwd", lambda x, y, width: x * y * width)
    cpu.impl(
        "_required_fixture_bwd",
        lambda x, need_y_grad, grad_output, output, width, y, need_x_grad: (
            grad_output * x * width if need_y_grad else torch.zeros_like(y),
            grad_output * y * width if need_x_grad else torch.zeros_like(x),
        ),
    )
    namespace: dict[str, object] = {}
    exec(compile(generated, "python_registration_generated.py", "exec"), namespace)
    namespace["register_python_kernels"]()

    x = torch.tensor(2.0, requires_grad=True)
    y = torch.tensor(5.0, requires_grad=True)
    result = torch.ops.mindclade.required_fixture(x, y, 3)
    result.backward()
    torch.testing.assert_close(x.grad, torch.tensor(15.0))
    torch.testing.assert_close(y.grad, torch.tensor(6.0))

    x = torch.tensor(2.0, requires_grad=True)
    y = torch.tensor(5.0, requires_grad=True)
    result = torch.ops.mindclade.required_fixture(x, y, 3)
    with pytest.raises(RuntimeError, match="does not support double backward"):
        torch.autograd.grad(result, x, create_graph=True)


def test_program_group_emits_canonical_launcher_plan_and_bridge_guard(tmp_path: Path):
    native_root, source = _program_group_fixture_native_root(tmp_path)
    rendered = render_all(native_root, source_files=[source])
    operator = json.loads(rendered["native_ops.json"])["operators"][0]
    plan = operator["launcher_plans"]["forward"]

    assert plan["execution_order"] == ["load", "reduce"]
    assert plan["required_private_symbols"] == [
        "mindclade_tilelang_group_fixture_load_launch",
        "mindclade_tilelang_group_fixture_reduce_launch",
    ]
    assert [node["name"] for node in plan["nodes"]] == ["load", "reduce"]
    assert "builder" not in json.dumps(plan, sort_keys=True)
    assert plan["bridge_requirement"] == "mindclade_program_group_bridge_v1"
    assert plan["workspaces"][0]["shape"]["node"] == "shape_of"
    registry = rendered["operation_registry.generated.cpp"]
    assert "#if !defined(MINDCLADE_PROGRAM_GROUP_BRIDGE_V1)" in registry
    assert "program-group CUDA registry requires qualified bridge v1" in registry
    assert "mindclade_tilelang_group_fixture_load_launch(" not in registry
    assert "mindclade_tilelang_group_fixture_reduce_launch(" not in registry
    for symbol in plan["required_private_symbols"]:
        assert symbol in rendered["native_ops.generated.bzl"]
        assert symbol in rendered["native_ops.generated.cmake"]
        assert f'extern "C" void {symbol}();' in rendered["launcher_plans.generated.cpp"]
        assert f"&{symbol}" in rendered["launcher_plans.generated.cpp"]
    static_plans = rendered["launcher_plans.generated.cpp"]
    assert '\"logical_symbol\":\"mindclade_tilelang_group_fixture_fwd_launch\"' in static_plans
    assert '\"execution_order\":[\"load\",\"reduce\"]' in static_plans
    assert "mindclade_native_required_private_launchers" in static_plans


def test_declarative_fake_rejects_optional_tensor_metadata_dependency(tmp_path: Path):
    native_root, source = _fixture_native_root(tmp_path, fake=False)
    spec_path = native_root.parent / source
    text = spec_path.read_text(encoding="utf-8")
    text = text.replace("int width", "Tensor? width").replace(
        'shape=ShapeOf(argument="x")', 'shape=ShapeOf(argument="width")'
    )
    spec_path.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError, match="optional Tensor.*custom fake"):
        render_all(native_root, source_files=[source])


def test_empty_inventory_emits_no_operation_labels_or_symbols(tmp_path: Path):
    native_root = tmp_path / "kernels" / "native"
    native_root.mkdir(parents=True)
    rendered = render_all(native_root, source_files=[])
    assert json.loads(rendered["native_ops.json"])["operators"] == []
    assert "//kernels/" not in rendered["native_ops.generated.bzl"]
    assert "/pairformer/" not in rendered["native_ops.generated.cmake"]
    assert "m.def(" not in rendered["registration.generated.cpp"]
    assert "m.impl(" not in rendered["operation_registry.generated.cpp"]
