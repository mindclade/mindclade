import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from kernels.native.codegen.discover import discover_specs
import kernels.native.tilelang.build as build
from kernels.native.tilelang.build import compile_all
from kernels.native.tilelang.decorator import mindclade_kernel


def _fixture_source(tmp_path: Path) -> tuple[Path, str, Path]:
    kernels_root = tmp_path / "kernels"
    native_root = kernels_root / "native"
    native_root.mkdir(parents=True)
    operation = kernels_root / "family_a" / "fixture_op"
    operation.mkdir(parents=True)
    spec_source = operation / "spec.py"
    spec_source.write_text(
        '''from kernels.api import (
    AutogradPolicy, CompositeAutogradSpec, DeviceRef, DTypeRef, EffectSpec,
    ForwardSpec, GradientSpec, KernelSpec, LaunchContract, OutputSpec, ShapeOf,
)

KERNEL_SPEC = KernelSpec(
    name="fixture_op",
    namespace="mindclade",
    family="family_a",
    source="family_a/fixture_op/spec.py",
    operator_schema="fixture_op(Tensor x) -> Tensor output",
    facade_outputs=("output",),
    fake=None,
    forward=ForwardSpec(
        schema="_fixture_op_fwd(Tensor x) -> Tensor output",
        builder="kernels.family_a.fixture_op.tilelang:build_tilelang_program",
        symbol="mindclade_tilelang_fixture_op_fwd_launch",
        outputs=(OutputSpec(
            name="output",
            shape=ShapeOf(argument="x"),
            dtype=DTypeRef(argument="x"),
            device=DeviceRef(argument="x"),
            semantic_axes=("elements",),
            visible_in_facade=True,
            saved_for_backward=False,
        ),),
    ),
    backward=None,
    autograd_policy=AutogradPolicy.COMPOSITE,
    composite=CompositeAutogradSpec(
        decomposition="kernels.family_a.fixture_op.reference:reference",
        source_digest="sha256:0000000000000000000000000000000000000000000000000000000000000000",
        runtime_envelope="pytorch>=2.10,<2.11",
        gradients=(GradientSpec(
            input_name="x",
            output_name="grad_x",
            shape=ShapeOf(argument="x"),
            dtype=DTypeRef(argument="x"),
            device=DeviceRef(argument="x"),
        ),),
        supports_double_backward=False,
        setup_context="kernels.family_a.fixture_op.reference:setup_context",
        backward="kernels.family_a.fixture_op.reference:backward",
    ),
    effects=EffectSpec(),
    launch=LaunchContract(graph_capture_safe=False),
)

IMPLEMENTATION_SPECS = ()
''',
        encoding="utf-8",
    )
    builder_source = operation / "tilelang.py"
    builder_source.write_text(
        '''def build_tilelang_program(*, target, m):
    raise NotImplementedError
''',
        encoding="utf-8",
    )
    return native_root, "family_a/fixture_op/spec.py", builder_source


def _profiles():
    return {
        "mindclade::fixture_op": [
            {
                "name": "m16",
                "arguments": {"m": 16},
                "specialization_digest": "sha256:" + "5" * 64,
            },
        ]
    }


def _implementation_source(tmp_path: Path) -> tuple[Path, str]:
    native_root, source, _builder_source = _fixture_source(tmp_path)
    spec_file = native_root.parent / source
    contents = spec_file.read_text(encoding="utf-8")
    contents = contents.replace(
        "AutogradPolicy, CompositeAutogradSpec, DeviceRef, DTypeRef, EffectSpec,",
        "AutogradPolicy, BoolLiteral, CapabilityEnvelope, CompositeAutogradSpec, "
        "DeviceRef, DimensionConstraint, DTypeRef, EffectSpec,",
    ).replace(
        "ForwardSpec, GradientSpec, KernelSpec, LaunchContract, OutputSpec, ShapeOf,",
        "ForwardSpec, GradientSpec, ImplementationSpec, ImplementationTier, KernelSpec, "
        "LaunchContract, OutputSpec, ShapeOf,",
    ).replace(
        "IMPLEMENTATION_SPECS = ()",
        '''IMPLEMENTATION_SPECS = (
    ImplementationSpec(
        operation="fixture_op",
        name="portable",
        family="family_a",
        backend="tilelang",
        builder="kernels.family_a.fixture_op.tilelang:build_implementation",
        version=1,
        tier=ImplementationTier.PORTABLE,
        requires=("cuda",),
        envelope=CapabilityEnvelope(
            architectures=("sm90",),
            dtypes=("float32",),
            layouts=("contiguous",),
            modes=("default",),
            constraints=(DimensionConstraint(
                predicate=BoolLiteral(value=True),
                code="VALID",
                message="fixture implementation is supported",
            ),),
            graph_capture_safe=False,
            training_capable=False,
        ),
    ),
)''',
    )
    spec_file.write_text(contents, encoding="utf-8")
    return native_root, source


def _unsupported_source(
    tmp_path: Path,
    *,
    phase: str,
) -> tuple[Path, str]:
    native_root, source, _builder_source = _fixture_source(tmp_path)
    if phase not in {"backward", "forward_group", "backward_group"}:
        raise AssertionError(f"unsupported test phase: {phase}")

    forward_group = ""
    if phase == "forward_group":
        forward_group = '''
        program_group=ProgramGroupSpec(
            nodes=(ProgramNodeSpec(
                name="forward_stage",
                builder="kernels.family_a.fixture_op.tilelang:build_forward_stage",
                symbol="mindclade_tilelang_fixture_op_forward_stage_launch",
                entry_symbol="call",
                entry_abi=ProgramEntryABI.TILELANG_0_1_13_HOST_CALL,
                parameters=(
                    ProgramParameterSpec(position=0, name="x", kind=ProgramParameterKind.TENSOR, access=WorkspaceAccess.READ, shape=ShapeOf(argument="x"), dtype=DTypeRef(argument="x"), device=DeviceRef(argument="x")),
                    ProgramParameterSpec(position=1, name="output", kind=ProgramParameterKind.TENSOR, access=WorkspaceAccess.WRITE, shape=ShapeOf(argument="x"), dtype=DTypeRef(argument="x"), device=DeviceRef(argument="x")),
                    ProgramParameterSpec(position=2, name="stream", kind=ProgramParameterKind.STREAM, access=WorkspaceAccess.READ),
                ),
                bindings=(
                    ProgramBindingSpec(parameter="x", source=ProgramBindingSource.OPERATOR_ARGUMENT, source_name="x"),
                    ProgramBindingSpec(parameter="output", source=ProgramBindingSource.PROVIDER_OUTPUT, source_name="output"),
                    ProgramBindingSpec(parameter="stream", source=ProgramBindingSource.CURRENT_STREAM),
                ),
            ),),
        ),'''

    backward = "None"
    autograd_policy = "AutogradPolicy.COMPOSITE"
    composite = '''CompositeAutogradSpec(
        decomposition="kernels.family_a.fixture_op.reference:reference",
        source_digest="sha256:0000000000000000000000000000000000000000000000000000000000000000",
        runtime_envelope="pytorch>=2.10,<2.11",
        gradients=(GradientSpec(
            input_name="x",
            output_name="grad_x",
            shape=ShapeOf(argument="x"),
            dtype=DTypeRef(argument="x"),
            device=DeviceRef(argument="x"),
        ),),
        supports_double_backward=False,
        setup_context="kernels.family_a.fixture_op.reference:setup_context",
        backward="kernels.family_a.fixture_op.reference:backward",
    )'''
    if phase in {"backward", "backward_group"}:
        backward_group = ""
        if phase == "backward_group":
            backward_group = '''
        program_group=ProgramGroupSpec(
            nodes=(ProgramNodeSpec(
                name="backward_stage",
                builder="kernels.family_a.fixture_op.tilelang:build_backward_stage",
                symbol="mindclade_tilelang_fixture_op_backward_stage_launch",
                entry_symbol="call",
                entry_abi=ProgramEntryABI.TILELANG_0_1_13_HOST_CALL,
                parameters=(
                    ProgramParameterSpec(position=0, name="grad_output", kind=ProgramParameterKind.TENSOR, access=WorkspaceAccess.READ, shape=ShapeOf(argument="x"), dtype=DTypeRef(argument="x"), device=DeviceRef(argument="x")),
                    ProgramParameterSpec(position=1, name="x", kind=ProgramParameterKind.TENSOR, access=WorkspaceAccess.READ, shape=ShapeOf(argument="x"), dtype=DTypeRef(argument="x"), device=DeviceRef(argument="x")),
                    ProgramParameterSpec(position=2, name="grad_x", kind=ProgramParameterKind.TENSOR, access=WorkspaceAccess.WRITE, shape=ShapeOf(argument="x"), dtype=DTypeRef(argument="x"), device=DeviceRef(argument="x")),
                    ProgramParameterSpec(position=3, name="stream", kind=ProgramParameterKind.STREAM, access=WorkspaceAccess.READ),
                ),
                bindings=(
                    ProgramBindingSpec(parameter="grad_output", source=ProgramBindingSource.OUTPUT_GRADIENT, source_name="output"),
                    ProgramBindingSpec(parameter="x", source=ProgramBindingSource.OPERATOR_ARGUMENT, source_name="x"),
                    ProgramBindingSpec(parameter="grad_x", source=ProgramBindingSource.PROVIDER_OUTPUT, source_name="grad_x"),
                    ProgramBindingSpec(parameter="stream", source=ProgramBindingSource.CURRENT_STREAM),
                ),
            ),),
        ),'''
        backward = f'''BackwardSpec(
        schema="_fixture_op_bwd(Tensor grad_output, Tensor x) -> Tensor grad_x",
        builder="kernels.family_a.fixture_op.tilelang:build_backward",
        symbol="mindclade_tilelang_fixture_op_bwd_launch",
        argument_bindings=(
            BackwardArgumentBinding(
                provider_argument="grad_output",
                source=BackwardArgumentSource.OUTPUT_GRADIENT,
                source_name="output",
            ),
            BackwardArgumentBinding(
                provider_argument="x",
                source=BackwardArgumentSource.OPERATOR_ARGUMENT,
                source_name="x",
            ),
        ),
        gradients=(GradientSpec(
            input_name="x",
            output_name="grad_x",
            shape=ShapeOf(argument="x"),
            dtype=DTypeRef(argument="x"),
            device=DeviceRef(argument="x"),
        ),),
        supports_double_backward=False,{backward_group}
    )'''
        autograd_policy = "AutogradPolicy.REQUIRED"
        composite = "None"

    spec_file = native_root.parent / source
    spec_file.write_text(
        f'''from kernels.api import (
    AutogradPolicy, BackwardArgumentBinding, BackwardArgumentSource,
    BackwardSpec, CompositeAutogradSpec, DeviceRef, DTypeRef, EffectSpec,
    ForwardSpec, GradientSpec, KernelSpec, LaunchContract, OutputSpec,
    ProgramBindingSource, ProgramBindingSpec, ProgramEntryABI, ProgramGroupSpec,
    ProgramNodeSpec, ProgramParameterKind, ProgramParameterSpec, ShapeOf,
    WorkspaceAccess,
)

KERNEL_SPEC = KernelSpec(
    name="fixture_op",
    namespace="mindclade",
    family="family_a",
    source="family_a/fixture_op/spec.py",
    operator_schema="fixture_op(Tensor x) -> Tensor output",
    facade_outputs=("output",),
    fake=None,
    forward=ForwardSpec(
        schema="_fixture_op_fwd(Tensor x) -> Tensor output",
        builder="kernels.family_a.fixture_op.tilelang:build_tilelang_program",
        symbol="mindclade_tilelang_fixture_op_fwd_launch",
        outputs=(OutputSpec(
            name="output",
            shape=ShapeOf(argument="x"),
            dtype=DTypeRef(argument="x"),
            device=DeviceRef(argument="x"),
            semantic_axes=("elements",),
            visible_in_facade=True,
            saved_for_backward=False,
        ),),{forward_group}
    ),
    backward={backward},
    autograd_policy={autograd_policy},
    composite={composite},
    effects=EffectSpec(),
    launch=LaunchContract(graph_capture_safe=False),
)

IMPLEMENTATION_SPECS = ()
''',
        encoding="utf-8",
    )
    return native_root, source


def _assert_rejected_before_tilelang_or_builder(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    phase: str,
    message: str,
) -> None:
    native_root, source = _unsupported_source(tmp_path, phase=phase)
    monkeypatch.setattr(
        build.importlib,
        "import_module",
        lambda name: (_ for _ in ()).throw(AssertionError(f"unexpected import: {name}")),
    )
    monkeypatch.setattr(
        build,
        "_resolve_builder",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("unexpected builder resolution")
        ),
    )
    with pytest.raises(RuntimeError, match=message):
        compile_all(
            native_root,
            tmp_path / "compiled",
            source_files=[source],
            profiles=_profiles(),
            target="cuda-sm90a",
        )


def test_retired_decorator_fails_with_canonical_migration_path():
    with pytest.raises(RuntimeError, match=r"KERNEL_SPEC.*spec\.py"):
        mindclade_kernel(name="fixture_op")


def test_builder_resolution_uses_forward_identity_and_operation_local_tilelang(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    native_root, source, builder_source = _fixture_source(tmp_path)
    spec = discover_specs(native_root.parent, [source])[0].spec

    def declared_builder(*, target: str, m: int):
        return target, m

    imported: list[str] = []

    def import_module(name: str):
        imported.append(name)
        return SimpleNamespace(
            __file__=str(builder_source),
            build_tilelang_program=declared_builder,
        )

    monkeypatch.setattr(build.importlib, "import_module", import_module)
    assert build._resolve_builder(spec, native_root.parent) is declared_builder
    assert imported == ["kernels.family_a.fixture_op.tilelang"]


def test_builder_resolution_rejects_imported_module_from_spec_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    native_root, source, _builder_source = _fixture_source(tmp_path)
    spec = discover_specs(native_root.parent, [source])[0].spec
    spec_file = native_root.parent / source
    monkeypatch.setattr(
        build.importlib,
        "import_module",
        lambda _name: SimpleNamespace(
            __file__=str(spec_file),
            build_tilelang_program=lambda **_kwargs: None,
        ),
    )
    with pytest.raises(RuntimeError, match="operation-local tilelang.py"):
        build._resolve_builder(spec, native_root.parent)


class _MockPicAdapter:
    compiler_id = "mock-node-dso"
    compiler_version = "1"

    def __init__(self, *, fail_phase: str | None = None):
        self.fail_phase = fail_phase
        self.actions = []

    def compile(self, _program, action):
        self.actions.append(action)
        if action.phase == self.fail_phase:
            raise RuntimeError(f"injected {action.phase} compile failure")
        suffix = "a" * 64
        adapter_symbol = (
            f"{action.symbol}_{suffix}" if action.program_node is not None else action.symbol
        )
        return build.CompiledArtifact(
            dso=("mock-dso:" + action.digest).encode("ascii"),
            exported_symbols=(adapter_symbol,),
            source_sha256="sha256:" + "0" * 64,
            adapter_source_sha256="sha256:" + "1" * 64,
            call_signature_sha256="sha256:" + "2" * 64,
            compile_command=("$NVCC", "-c", "$SOURCE"),
            link_command=("$NVCC", "-shared", "$OBJECT"),
            toolchain_closure_digest="sha256:" + "3" * 64,
            adapter_symbol=adapter_symbol,
            soname="libmindclade_node_" + suffix + ".so",
        )


def _mock_builder_resolution(monkeypatch: pytest.MonkeyPatch, spec):
    def resolve(_spec, identity, _kernels_root):
        provider = None
        phase = None
        for candidate_phase, candidate in (
            ("forward", spec.forward),
            ("backward", spec.backward),
        ):
            if candidate is not None and candidate.builder == identity:
                provider = candidate
                phase = candidate_phase
                break
        if provider is not None and provider.program_group is not None:
            group = provider.program_group
            descriptor = {
                "execution_order": tuple(node.name for node in group.nodes),
                "logical_symbol": provider.symbol,
                "phase": phase,
                "version": 1,
                "workspaces": tuple(workspace.name for workspace in group.workspaces),
            }
            return lambda **_kwargs: descriptor
        return lambda **_kwargs: object()

    monkeypatch.setattr(build, "_resolve_builder_identity", resolve)


def test_offline_builder_emits_receipt_v4_and_node_dso_action(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    native_root, source, _builder_source = _fixture_source(tmp_path)
    spec = discover_specs(native_root.parent, [source])[0].spec
    _mock_builder_resolution(monkeypatch, spec)
    adapter = _MockPicAdapter()
    output = tmp_path / "compiled"
    receipts = compile_all(
        native_root,
        output,
        source_files=[source],
        profiles=_profiles(),
        target="cuda-sm90",
        compiler_adapter=adapter,
    )

    assert len(receipts) == 1
    receipt = receipts[0]
    assert receipt.qualified_name == "mindclade::fixture_op"
    assert receipt.forward.logical_symbol == "mindclade_tilelang_fixture_op_fwd_launch"
    assert receipt.forward.execution_order == ("logical",)
    assert receipt.backward is None
    assert len(adapter.actions) == 1
    artifact = output / receipt.forward.units[0].artifact
    assert artifact.read_bytes().startswith(b"mock-dso:sha256:")
    document = json.loads((output / "build_receipts.json").read_text(encoding="utf-8"))
    assert document["schema_version"] == 4
    assert document["qualification_status"] == "unqualified"
    assert document["compiler"] == {"id": "mock-node-dso", "version": "1"}
    assert document["registry_generator"] == {
        "id": "kernels.native.codegen.generate",
        "version": 8,
    }
    assert document["document_digest"].startswith("sha256:")
    unit = document["receipts"][0]["forward"]["units"][0]
    assert unit["object_format"] == "elf_shared_object"
    assert unit["soname"].startswith("libmindclade_node_")
    assert unit["specialization_digest"] == "sha256:" + "5" * 64
    assert document["receipts"][0]["specialization_digest"] == "sha256:" + "5" * 64
    assert document["receipts"][0]["status"] == "unqualified"


def test_offline_builder_requires_exact_bounded_profile_inventory(tmp_path: Path):
    native_root, source, _builder_source = _fixture_source(tmp_path)
    with pytest.raises(ValueError, match="inventory mismatch"):
        compile_all(
            native_root,
            tmp_path / "compiled",
            source_files=[source],
            profiles={},
            target="cuda-sm90",
            compiler_adapter=_MockPicAdapter(),
        )


def test_offline_builder_rejects_reused_output_before_compilation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    native_root, source, _builder_source = _fixture_source(tmp_path)
    spec = discover_specs(native_root.parent, [source])[0].spec
    _mock_builder_resolution(monkeypatch, spec)
    output = tmp_path / "compiled"
    output.mkdir()
    adapter = _MockPicAdapter()
    with pytest.raises(ValueError, match="must not already exist"):
        compile_all(
            native_root,
            output,
            source_files=[source],
            profiles=_profiles(),
            target="cuda-sm90",
            compiler_adapter=adapter,
        )
    assert adapter.actions == []


def test_required_forward_backward_are_built_and_published_atomically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    native_root, source = _unsupported_source(tmp_path, phase="backward")
    spec = discover_specs(native_root.parent, [source])[0].spec
    _mock_builder_resolution(monkeypatch, spec)
    adapter = _MockPicAdapter()
    output = tmp_path / "compiled"
    receipt = compile_all(
        native_root,
        output,
        source_files=[source],
        profiles=_profiles(),
        target="cuda-sm90",
        compiler_adapter=adapter,
    )[0]
    assert [action.phase for action in adapter.actions] == ["forward", "backward"]
    assert receipt.backward is not None
    assert receipt.backward.logical_symbol == "mindclade_tilelang_fixture_op_bwd_launch"
    assert all((output / unit.artifact).is_file() for phase in (receipt.forward, receipt.backward) for unit in phase.units)


def test_backward_failure_publishes_no_partial_artifacts_or_receipts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    native_root, source = _unsupported_source(tmp_path, phase="backward")
    spec = discover_specs(native_root.parent, [source])[0].spec
    _mock_builder_resolution(monkeypatch, spec)
    output = tmp_path / "compiled"
    with pytest.raises(RuntimeError, match="injected backward compile failure"):
        compile_all(
            native_root,
            output,
            source_files=[source],
            profiles=_profiles(),
            target="cuda-sm90",
            compiler_adapter=_MockPicAdapter(fail_phase="backward"),
        )
    assert not output.exists()


def test_program_group_compiles_node_builders_in_canonical_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    native_root, source = _unsupported_source(tmp_path, phase="forward_group")
    spec = discover_specs(native_root.parent, [source])[0].spec
    _mock_builder_resolution(monkeypatch, spec)
    adapter = _MockPicAdapter()
    receipt = compile_all(
        native_root,
        tmp_path / "compiled",
        source_files=[source],
        profiles=_profiles(),
        target="cuda-sm90",
        compiler_adapter=adapter,
    )[0]
    group = spec.forward.program_group
    assert group is not None
    assert receipt.forward.program_group is True
    assert receipt.forward.execution_order == tuple(node.name for node in group.nodes)
    assert [action.node for action in adapter.actions[: len(group.nodes)]] == [
        node.name for node in group.nodes
    ]
    assert [action.symbol for action in adapter.actions[: len(group.nodes)]] == [
        node.symbol for node in group.nodes
    ]


def test_program_group_rejects_incompatible_logical_descriptor_before_nodes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    native_root, source = _unsupported_source(tmp_path, phase="forward_group")
    spec = discover_specs(native_root.parent, [source])[0].spec
    monkeypatch.setattr(
        build,
        "_resolve_builder_identity",
        lambda *_args: (lambda **_kwargs: {"version": 1}),
    )
    adapter = _MockPicAdapter()
    with pytest.raises(RuntimeError, match="exact descriptor keys"):
        compile_all(
            native_root,
            tmp_path / "compiled",
            source_files=[source],
            profiles=_profiles(),
            target="cuda-sm90",
            compiler_adapter=adapter,
        )
    assert adapter.actions == []


def test_compatibility_adapter_rejects_source_only_tilelang_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    native_root, source = _unsupported_source(tmp_path, phase="forward_group")
    spec = discover_specs(native_root.parent, [source])[0].spec

    class SourceOnlyProgram:
        def compile(self):
            return self

        def get_kernel_source(self):
            return 'extern "C" __global__ void fixture() {}\n'

    group = spec.forward.program_group
    assert group is not None

    def resolve(_spec, identity, _kernels_root):
        if identity == spec.forward.builder:
            return lambda **_kwargs: {
                "execution_order": tuple(node.name for node in group.nodes),
                "logical_symbol": spec.forward.symbol,
                "phase": "forward",
                "version": 1,
                "workspaces": tuple(workspace.name for workspace in group.workspaces),
            }
        return lambda **_kwargs: SourceOnlyProgram()

    monkeypatch.setattr(build, "_resolve_builder_identity", resolve)
    tool = tmp_path / "tool"
    tool.write_bytes(b"tool")
    tool.chmod(0o755)
    header = tmp_path / "node_launch_abi.h"
    header.write_text("#pragma once\n", encoding="utf-8")
    monkeypatch.setattr(build, "_run_checked", lambda *_args: "pinned nvcc 1\n")
    adapter = build.TileLangCompatibilityAdapter(
        SimpleNamespace(__version__="0.1.13"),
        nvcc=tool,
        nvcc_sha256="sha256:" + hashlib.sha256(tool.read_bytes()).hexdigest(),
        nvcc_version="pinned nvcc 1",
        toolchain_closure_digest="sha256:" + "4" * 64,
        node_abi_header=header,
        nm=tool,
        readelf=tool,
    )
    output = tmp_path / "compiled"
    with pytest.raises(RuntimeError, match="compiled CUDA object"):
        compile_all(
            native_root,
            output,
            source_files=[source],
            profiles=_profiles(),
            target="cuda-sm90a",
            compiler_adapter=adapter,
        )
    assert not output.exists()


def test_compatibility_adapter_requires_exact_tilelang_version_before_tools():
    missing = Path("/definitely/not/a/tool")
    with pytest.raises(RuntimeError, match=r"TileLang 0\.1\.13 is required"):
        build.TileLangCompatibilityAdapter(
            SimpleNamespace(__version__="0.1.14"),
            nvcc=missing,
            nvcc_sha256="sha256:" + "0" * 64,
            nvcc_version="unused",
            toolchain_closure_digest="sha256:" + "0" * 64,
            node_abi_header=missing,
            nm=missing,
            readelf=missing,
        )


def test_generated_node_adapter_guards_optional_gradient_before_raw_call():
    from kernels.pairformer.outer_product_mean.spec import KERNEL_SPEC as spec

    assert spec.backward is not None
    group = spec.backward.program_group
    assert group is not None
    node = next(value for value in group.nodes if value.name == "dleft")
    raw = (
        build._RawCallParameter("grad_output", "float* __restrict__"),
        build._RawCallParameter("right", "float* __restrict__"),
        build._RawCallParameter("mask", "float* __restrict__"),
        build._RawCallParameter("epsilon", "float"),
        build._RawCallParameter("normalizer", "float* __restrict__"),
        build._RawCallParameter("grad_left", "float* __restrict__"),
        build._RawCallParameter("stream", "cudaStream_t"),
    )
    symbol = node.symbol + "_" + "a" * 64
    specialization_digest = "sha256:" + "5" * 64
    first = build._render_node_adapter(node, raw, symbol, specialization_digest)
    second = build._render_node_adapter(node, raw, symbol, specialization_digest)
    assert first == second
    assert f'int32_t {symbol}(' in first
    assert "MINDCLADE_NODE_LAUNCH_ABI_VERSION" in first
    digest_guard = first.index("specialization_mismatch")
    parameter_pointer_guard = first.index("launch->parameters == nullptr")
    assert digest_guard < parameter_pointer_guard
    assert first.count("UINT8_C(0x55)") == 32
    request_guard = first.index("payload.boolean_value == UINT64_C(0)")
    raw_call = first.index("const int entry_status = call(")
    assert request_guard < raw_call
    assert "call(" in first


def test_specialization_profile_requires_canonical_specialization_spec_digest():
    with pytest.raises(ValueError, match="specialization_digest"):
        build.SpecializationProfile.from_value(
            {"name": "m16", "arguments": {"m": 16}}
        )


def test_host_call_signature_is_canonical_and_exact():
    source = '''
extern "C" TL_EXPORT int call(
    half_t* __restrict__ x, float scale, cudaStream_t stream=cudaStreamDefault) {
  return 0;
}
'''
    signature, parameters = build._parse_host_call(source, "call")
    assert signature == (
        "extern C int call(half_t* __restrict__ x,float scale,cudaStream_t stream)"
    )
    assert tuple(parameter.name for parameter in parameters) == ("x", "scale", "stream")


def test_compiler_rejects_wrong_exported_symbol_inventory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    native_root, source, _builder_source = _fixture_source(tmp_path)
    spec = discover_specs(native_root.parent, [source])[0].spec
    _mock_builder_resolution(monkeypatch, spec)

    class WrongSymbolAdapter(_MockPicAdapter):
        def compile(self, program, action):
            artifact = super().compile(program, action)
            return build.CompiledArtifact(
                dso=artifact.dso,
                exported_symbols=("wrong_symbol",),
                source_sha256=artifact.source_sha256,
                adapter_source_sha256=artifact.adapter_source_sha256,
                call_signature_sha256=artifact.call_signature_sha256,
                compile_command=artifact.compile_command,
                link_command=artifact.link_command,
                toolchain_closure_digest=artifact.toolchain_closure_digest,
                adapter_symbol=artifact.adapter_symbol,
                soname=artifact.soname,
            )

    with pytest.raises(RuntimeError, match="must export exactly"):
        compile_all(
            native_root,
            tmp_path / "compiled",
            source_files=[source],
            profiles=_profiles(),
            target="cuda-sm90",
            compiler_adapter=WrongSymbolAdapter(),
        )


def test_offline_builder_fails_closed_when_tilelang_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    native_root, source, _builder_source = _fixture_source(tmp_path)

    def missing(name: str):
        if name == "tilelang":
            raise ModuleNotFoundError(name)
        raise AssertionError(name)

    monkeypatch.setattr(build.importlib, "import_module", missing)
    with pytest.raises(RuntimeError, match="TileLang is required"):
        compile_all(
            native_root,
            tmp_path / "compiled",
            source_files=[source],
            profiles=_profiles(),
            target="cuda-sm90",
        )


@pytest.mark.parametrize(
    ("filename", "architecture"),
    (("tilelang_profiles.sm90.json", "sm90a"), ("tilelang_profiles.sm100.json", "sm100a")),
)
def test_pairformer_profiles_bind_architecture_and_cover_fp16_bf16(
    filename: str, architecture: str
):
    manifest = (
        Path(build.__file__).resolve().parents[1] / "manifests" / filename
    )
    profiles = json.loads(manifest.read_text(encoding="utf-8"))
    for operation in (
        "mindclade::outer_product_mean",
        "mindclade::pair_weighted_average",
        "mindclade::transition",
        "mindclade::triangle_attention",
        "mindclade::triangle_multiplication",
    ):
        entries = profiles[operation]
        assert entries
        assert {entry["arguments"]["architecture"] for entry in entries} == {
            architecture
        }
        identities = {}
        for entry in entries:
            arguments = entry["arguments"]
            assert arguments["dtype"] in {"float16", "bfloat16"}
            shape = tuple(
                (key, value)
                for key, value in sorted(arguments.items())
                if key not in {"architecture", "dtype"}
            )
            identities.setdefault(shape, set()).add(arguments["dtype"])
        assert all(values == {"float16", "bfloat16"} for values in identities.values())
