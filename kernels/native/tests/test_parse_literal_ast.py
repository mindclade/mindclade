from __future__ import annotations

from pathlib import Path

import pytest

from kernels.api import IntLiteral, KernelSpec, LaunchContract, ShapeTuple
from kernels.native.codegen.parse_literal_ast import (
    LiteralAstError,
    parse_kernel_spec_source,
    parse_literal_file,
    parse_literal_source,
)


def _minimal_kernel_source() -> str:
    return '''
"""A declarative test operation; this module is never imported by discovery."""
from __future__ import annotations
from kernels.api import (
    AutogradPolicy,
    EffectSpec,
    ForwardSpec,
    KernelSpec,
    OutputSpec,
    SameAsInputDType,
    SameAsInputDevice,
    DimRef,
    LaunchContract,
    ShapeTuple,
)

KERNEL_SPEC: KernelSpec = KernelSpec(
    name="noop",
    namespace="mindclade",
    family="testing",
    source="testing/noop/spec.py",
    operator_schema="noop(Tensor x) -> Tensor output",
    facade_outputs=("output",),
    fake=None,
    forward=ForwardSpec(
        schema="_noop_fwd(Tensor x) -> Tensor output",
        builder="kernels.testing.noop.tilelang:build_forward",
        symbol="mindclade_tilelang_noop_fwd_launch",
        outputs=(
            OutputSpec(
                name="output",
                shape=ShapeTuple(dimensions=(DimRef(argument="x", axis=0),)),
                dtype=SameAsInputDType(argument="x"),
                device=SameAsInputDevice(argument="x"),
                semantic_axes=("row",),
                visible_in_facade=True,
                saved_for_backward=False,
            ),
        ),
    ),
    backward=None,
    autograd_policy=AutogradPolicy.NONE,
    effects=EffectSpec(),
    launch=LaunchContract(),
)
'''


def test_parses_one_complete_kernel_spec_without_importing_operation() -> None:
    spec = parse_kernel_spec_source(_minimal_kernel_source(), filename="testing/noop/spec.py")
    assert isinstance(spec, KernelSpec)
    assert spec.qualified_name == "mindclade::noop"
    assert isinstance(spec.forward.outputs[0].shape, ShapeTuple)


def test_parses_approved_aliases_literals_containers_and_enum_members() -> None:
    source = '''
from kernels.api import DeterminismClass as D, LaunchContract as Contract
KERNEL_SPEC = Contract(
    determinism=D.CONDITIONALLY_DETERMINISTIC,
    current_stream_only=True,
    global_synchronization=False,
    hidden_device_allocation=False,
    graph_capture_safe=True,
    version=1,
)
'''
    value = parse_literal_source(source)
    assert isinstance(value, LaunchContract)
    assert value.determinism.value == "conditionally_deterministic"


def test_parses_shape_predicates_tensor_constraints_and_updated_composite_contract() -> None:
    shape_predicate = parse_literal_source(
        '''
from kernels.api import (
    And,
    Broadcastable,
    IntLiteral,
    IsFinite,
    ScalarRef,
    ScalarType,
    ShapeOf,
    ShapeTuple,
)
KERNEL_SPEC = And(
    operands=(
        Broadcastable(
            lhs=ShapeOf(argument="bias"),
            rhs=ShapeTuple(dimensions=(IntLiteral(value=1), IntLiteral(value=32))),
        ),
        IsFinite(value=ScalarRef(argument="scale", value_type=ScalarType.FLOAT)),
    ),
)
'''
    )
    assert shape_predicate.domain.value == "bool"

    tensor_constraint = parse_literal_source(
        '''
from kernels.api import TensorCapabilityConstraint
KERNEL_SPEC = TensorCapabilityConstraint(
    argument="q",
    dtypes=("bfloat16",),
    devices=("cuda",),
    ranks=(4,),
)
'''
    )
    assert tensor_constraint.argument == "q"

    composite = parse_literal_source(
        '''
from kernels.api import CompositeAutogradSpec, GradientSpec
KERNEL_SPEC = CompositeAutogradSpec(
    decomposition="kernels.testing.noop.reference:backward",
    source_digest="sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    runtime_envelope="pytorch-2.10",
    gradients=(GradientSpec(input_name="x", output_name="grad_x"),),
    supports_double_backward=False,
    setup_context="kernels.testing.noop.reference:setup_context",
    backward="kernels.testing.noop.reference:backward",
)
'''
    )
    assert composite.gradients[0].input_name == "x"


def test_literal_file_reads_spec_without_importing_its_package(tmp_path: Path) -> None:
    package = tmp_path / "operation"
    package.mkdir()
    sentinel = tmp_path / "imported"
    (package / "__init__.py").write_text(
        f"from pathlib import Path\nPath({str(sentinel)!r}).touch()\n",
        encoding="utf-8",
    )
    path = package / "spec.py"
    path.write_text(
        "from kernels.api import IntLiteral\n"
        "KERNEL_SPEC = IntLiteral(value=-7)\n",
        encoding="utf-8",
    )
    value = parse_literal_file(path)
    assert isinstance(value, IntLiteral)
    assert value.value == -7
    assert not sentinel.exists()


@pytest.mark.parametrize(
    ("source", "message"),
    (
        (
            "import os\nKERNEL_SPEC = os.environ\n",
            "arbitrary imports are forbidden",
        ),
        (
            "from pathlib import Path\nKERNEL_SPEC = Path(value='x')\n",
            "only explicit imports from kernels.api",
        ),
        (
            "from kernels.api import Missing\nKERNEL_SPEC = Missing()\n",
            "unsupported kernels.api import",
        ),
        (
            "from kernels.api import IntLiteral\nKERNEL_SPEC = danger()\n",
            "not an approved constructor",
        ),
        (
            "from kernels.api import IntLiteral\nKERNEL_SPEC = IntLiteral(1)\n",
            "keyword arguments only",
        ),
        (
            "from kernels.api import IntLiteral\nKERNEL_SPEC = IntLiteral(**{'value': 1})\n",
            "keyword unpacking is forbidden",
        ),
        (
            "from kernels.api import IntLiteral\nKERNEL_SPEC = [IntLiteral(value=x) for x in (1,)]\n",
            "unsupported expression node ListComp",
        ),
        (
            "from kernels.api import IntLiteral\nKERNEL_SPEC = IntLiteral.__class__\n",
            "attribute access is permitted only on an approved enum",
        ),
        (
            "from kernels.api import IntLiteral\nKERNEL_SPEC = IntLiteral(value=1 if flag else 2)\n",
            "unsupported expression node IfExp",
        ),
        (
            "from kernels.api import IntLiteral\nif True:\n    KERNEL_SPEC = IntLiteral(value=1)\n",
            "unsupported top-level statement If",
        ),
        (
            "from kernels.api import IntLiteral\nKERNEL_SPEC = IntLiteral(value=1 + 2)\n",
            "unsupported expression node BinOp",
        ),
    ),
)
def test_rejects_executable_or_dynamic_python(source: str, message: str) -> None:
    with pytest.raises(LiteralAstError, match=message):
        parse_literal_source(source)


def test_rejects_duplicate_imports_dictionary_keys_and_declarations() -> None:
    with pytest.raises(LiteralAstError, match="duplicate imported binding"):
        parse_literal_source(
            "from kernels.api import IntLiteral\n"
            "from kernels.api import IntLiteral\n"
            "KERNEL_SPEC = IntLiteral(value=1)\n"
        )


def test_annotated_declaration_requires_imported_kernel_spec_binding() -> None:
    aliased = _minimal_kernel_source().replace(
        "KernelSpec,\n",
        "KernelSpec as Contract,\n",
    ).replace("KERNEL_SPEC: KernelSpec = KernelSpec(", "KERNEL_SPEC: Contract = Contract(")
    assert parse_kernel_spec_source(aliased).name == "noop"

    with pytest.raises(LiteralAstError, match="must resolve to an explicitly imported"):
        parse_literal_source(
            "from kernels.api import IntLiteral\n"
            "KERNEL_SPEC: IntLiteral = IntLiteral(value=1)\n"
        )
    with pytest.raises(LiteralAstError, match="must resolve to an explicitly imported"):
        parse_literal_source(
            "from kernels.api import IntLiteral\n"
            "KERNEL_SPEC: Missing = IntLiteral(value=1)\n"
        )
    with pytest.raises(LiteralAstError, match="duplicate dictionary key"):
        parse_literal_source(
            "from kernels.api import InSet, ScalarRef, ScalarType\n"
            "KERNEL_SPEC = {'x': 1, 'x': 2}\n"
        )
    with pytest.raises(LiteralAstError, match="exactly one KERNEL_SPEC"):
        parse_literal_source(
            "from kernels.api import IntLiteral\n"
            "KERNEL_SPEC = IntLiteral(value=1)\n"
            "OTHER = IntLiteral(value=2)\n"
        )


def test_rejects_repeated_keyword_syntax_and_unsupported_schema_version() -> None:
    with pytest.raises(LiteralAstError, match="duplicate constructor field"):
        parse_literal_source(
            "from kernels.api import IntLiteral\n"
            "KERNEL_SPEC = IntLiteral(value=1, value=2)\n"
        )
    with pytest.raises(LiteralAstError, match="unsupported LaunchContract"):
        parse_literal_source(
            "from kernels.api import LaunchContract\n"
            "KERNEL_SPEC = LaunchContract(version=2)\n",
            supported_versions=frozenset({1}),
        )


def test_kernel_parser_rejects_a_non_kernel_contract() -> None:
    with pytest.raises(LiteralAstError, match="must construct kernels.api.KernelSpec"):
        parse_kernel_spec_source(
            "from kernels.api import IntLiteral\n"
            "KERNEL_SPEC = IntLiteral(value=1)\n"
        )


def test_canonical_file_policy_rejects_non_spec_filename_and_symlink(tmp_path: Path) -> None:
    source = tmp_path / "declaration.py"
    source.write_text(
        "from kernels.api import IntLiteral\nKERNEL_SPEC = IntLiteral(value=1)\n",
        encoding="utf-8",
    )
    with pytest.raises(LiteralAstError, match="filename must be spec.py"):
        parse_literal_file(source)

    target = tmp_path / "target.py"
    target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    link = tmp_path / "spec.py"
    link.symlink_to(target)
    with pytest.raises(LiteralAstError, match="must not be a symlink"):
        parse_literal_file(link)
