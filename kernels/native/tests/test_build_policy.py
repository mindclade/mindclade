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


def test_offline_builder_invokes_compile_and_captures_nonempty_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    native_root, source, _builder_source = _fixture_source(tmp_path)
    calls: list[tuple[str, int]] = []

    class Program:
        def compile(self):
            calls.append(("compile", 16))
            return self

        def get_kernel_source(self):
            return 'extern "C" __global__ void fixture_op() {}\n'

    def builder(*, target: str, m: int):
        assert target == "cuda-sm90"
        assert m == 16
        return Program()

    original_import = build.importlib.import_module
    monkeypatch.setattr(
        build.importlib,
        "import_module",
        lambda name: SimpleNamespace(__version__="test-pinned")
        if name == "tilelang"
        else original_import(name),
    )
    monkeypatch.setattr(build, "_resolve_builder", lambda spec, kernels_root: builder)
    output = tmp_path / "compiled"
    receipts = compile_all(
        native_root,
        output,
        source_files=[source],
        profiles=_profiles(),
        target="cuda-sm90",
    )
    assert calls == [("compile", 16)]
    assert len(receipts) == 1
    artifact = output / receipts[0].output
    assert artifact.read_bytes()
    assert receipts[0].artifact_sha256 == (
        "sha256:" + hashlib.sha256(artifact.read_bytes()).hexdigest()
    )
    spec_bytes = (native_root.parent / source).read_bytes()
    assert receipts[0].declaration_source == source
    assert receipts[0].spec_sha256 == "sha256:" + hashlib.sha256(spec_bytes).hexdigest()
    assert receipts[0].kernel_spec_digest.startswith("sha256:")
    assert receipts[0].forward_symbol == "mindclade_tilelang_fixture_op_fwd_launch"
    document = json.loads((output / "build_receipts.json").read_text(encoding="utf-8"))
    assert document["schema_version"] == 2
    assert document["receipts"][0]["qualified_name"] == "mindclade::fixture_op"
    assert document["receipts"][0]["kernel_spec_digest"] == receipts[0].kernel_spec_digest


def test_offline_builder_requires_exact_bounded_profile_inventory(tmp_path: Path):
    native_root, source, _builder_source = _fixture_source(tmp_path)
    with pytest.raises(ValueError, match="inventory mismatch"):
        compile_all(
            native_root,
            tmp_path / "compiled",
            source_files=[source],
            profiles={},
            target="cuda-sm90",
        )


def test_offline_builder_rejects_backward_provider_before_tilelang_import(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _assert_rejected_before_tilelang_or_builder(
        tmp_path,
        monkeypatch,
        phase="backward",
        message=r"receipt schema v2.*atomic forward/backward co-build.*receipt/bridge implementation",
    )


def test_offline_builder_rejects_forward_program_group_before_tilelang_import(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _assert_rejected_before_tilelang_or_builder(
        tmp_path,
        monkeypatch,
        phase="forward_group",
        message=r"receipt schema v2.*forward ProgramGroupSpec.*program-group receipt/bridge implementation",
    )


def test_offline_builder_rejects_backward_program_group_before_tilelang_import(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _assert_rejected_before_tilelang_or_builder(
        tmp_path,
        monkeypatch,
        phase="backward_group",
        message=r"receipt schema v2.*backward ProgramGroupSpec.*program-group receipt/bridge implementation",
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
