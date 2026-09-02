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
        gradients=(GradientSpec(input_name="x", output_name="grad_x"),),
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
            {"name": "m16", "arguments": {"m": 16}},
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
            ),),
        ),'''

    backward = "None"
    autograd_policy = "AutogradPolicy.COMPOSITE"
    composite = '''CompositeAutogradSpec(
        decomposition="kernels.family_a.fixture_op.reference:reference",
        source_digest="sha256:0000000000000000000000000000000000000000000000000000000000000000",
        runtime_envelope="pytorch>=2.10,<2.11",
        gradients=(GradientSpec(input_name="x", output_name="grad_x"),),
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
        gradients=(GradientSpec(input_name="x", output_name="grad_x"),),
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
    ProgramGroupSpec, ProgramNodeSpec, ShapeOf,
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
            target="cuda-sm90",
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
    compiler_id = "mock-pic"
    compiler_version = "1"

    def __init__(self, *, fail_phase: str | None = None):
        self.fail_phase = fail_phase
        self.actions = []

    def compile(self, _program, action):
        self.actions.append(action)
        if action.phase == self.fail_phase:
            raise RuntimeError(f"injected {action.phase} compile failure")
        return build.CompiledArtifact(
            pic_object=("mock-pic:" + action.digest).encode("ascii"),
            exported_symbols=(action.symbol,),
            source_sha256="sha256:" + "0" * 64,
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


def test_offline_builder_emits_receipt_v3_and_pic_action(
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
    assert artifact.read_bytes().startswith(b"mock-pic:sha256:")
    document = json.loads((output / "build_receipts.json").read_text(encoding="utf-8"))
    assert document["schema_version"] == 3
    assert document["compiler"] == {"id": "mock-pic", "version": "1"}
    assert document["registry_generator"] == {
        "id": "kernels.native.codegen.generate",
        "version": 7,
    }
    assert document["document_digest"].startswith("sha256:")
    assert document["receipts"][0]["forward"]["units"][0]["object_format"] == "pic_object"


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
    native_root, source, _builder_source = _fixture_source(tmp_path)
    spec = discover_specs(native_root.parent, [source])[0].spec

    class SourceOnlyProgram:
        def compile(self):
            return self

        def get_kernel_source(self):
            return 'extern "C" __global__ void fixture() {}\n'

    monkeypatch.setattr(
        build,
        "_resolve_builder_identity",
        lambda *_args: (lambda **_kwargs: SourceOnlyProgram()),
    )
    adapter = build.TileLangCompatibilityAdapter(SimpleNamespace(__version__="0.1.13"))
    output = tmp_path / "compiled"
    with pytest.raises(RuntimeError, match="produced source only"):
        compile_all(
            native_root,
            output,
            source_files=[source],
            profiles=_profiles(),
            target="cuda-sm90",
            compiler_adapter=adapter,
        )
    assert not output.exists()


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
                pic_object=artifact.pic_object,
                exported_symbols=("wrong_symbol",),
                source_sha256=artifact.source_sha256,
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
