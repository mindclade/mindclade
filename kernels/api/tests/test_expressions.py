from __future__ import annotations

from dataclasses import FrozenInstanceError
import json

import pytest

from kernels.api.errors import (
    ExpressionDecodeError,
    ExpressionEvaluationError,
    ExpressionValidationError,
)
from kernels.api.expressions import (
    Add,
    And,
    BoolLiteral,
    Broadcastable,
    CeilDiv,
    ConcatShape,
    ConstantDType,
    ConstantDevice,
    DeviceRef,
    DimRef,
    DTypeRef,
    Eq,
    EvaluationContext,
    FloorDiv,
    GreaterEqual,
    InSet,
    IsFinite,
    IntLiteral,
    LessThan,
    Maximum,
    Minimum,
    Modulo,
    Multiply,
    Not,
    NotEqual,
    Or,
    RankRef,
    RoundUp,
    SameAsInputDType,
    SameAsInputDevice,
    ScalarRef,
    ScalarType,
    Select,
    ShapeOf,
    ShapePrefix,
    ShapeTuple,
    StringLiteral,
    Subtract,
    TensorMetadata,
    canonical_data,
    canonical_json,
    content_digest,
    evaluate,
    expression_from_data,
    expression_from_json,
    generate_native_host_validator,
    generate_python_validator,
    render,
)


@pytest.fixture
def context() -> EvaluationContext:
    return EvaluationContext(
        tensors={
            "q": TensorMetadata(shape=(2, 7, 65, 32), dtype="bfloat16", device="cuda:0"),
            "k": TensorMetadata(shape=(2, 7, 33, 32), dtype="bfloat16", device="cuda:0"),
        },
        scalars={"causal": True, "mode": "prefill", "tile": 32, "scale": 0.125},
    )


def test_arithmetic_and_metadata_references_evaluate_deterministically(
    context: EvaluationContext,
) -> None:
    length = DimRef("q", 2)
    expression = Add(
        RoundUp(length, IntLiteral(32)),
        Maximum(
            Minimum(Multiply(RankRef("q"), IntLiteral(4)), IntLiteral(20)),
            Subtract(CeilDiv(DimRef("k", 2), IntLiteral(16)), IntLiteral(1)),
        ),
    )
    assert evaluate(expression, context) == 112
    assert FloorDiv(IntLiteral(17), IntLiteral(4)).evaluate(context) == 4
    assert Modulo(IntLiteral(17), IntLiteral(4)).evaluate(context) == 1
    assert DimRef("q", -1).evaluate(context) == 32


def test_dtype_device_scalar_boolean_membership_and_select(context: EvaluationContext) -> None:
    supported = And(
        (
            Eq(DTypeRef("q"), ConstantDType("bfloat16")),
            Eq(DeviceRef("q"), ConstantDevice("cuda:0")),
            Eq(SameAsInputDType("q"), SameAsInputDType("k")),
            Eq(SameAsInputDevice("q"), SameAsInputDevice("k")),
            InSet(ScalarRef("mode", ScalarType.STRING), ("decode", "prefill")),
            ScalarRef("causal", ScalarType.BOOL),
            Not(LessThan(DimRef("q", 2), IntLiteral(32))),
        )
    )
    expression = Select(
        Or((supported, BoolLiteral(False))),
        DimRef("q", 2),
        IntLiteral(0),
    )
    assert expression.evaluate(context) == 65
    assert NotEqual(StringLiteral("prefill"), StringLiteral("decode")).evaluate(context)
    assert GreaterEqual(ScalarRef("scale", ScalarType.FLOAT), IntLiteral(0)).evaluate(context)


def test_canonical_serialization_round_trip_and_digest_are_stable() -> None:
    first = InSet(ScalarRef("mode", ScalarType.STRING), ("prefill", "decode"))
    second = InSet(ScalarRef("mode", ScalarType.STRING), ("decode", "prefill"))
    assert canonical_data(first) == canonical_data(second)
    assert canonical_json(first) == (
        '{"members":["decode","prefill"],"node":"in_set",'
        '"value":{"argument":"mode","node":"scalar_ref","value_type":"string"}}'
    )
    assert content_digest(first) == content_digest(second)
    assert content_digest(first).startswith("sha256:")
    decoded = expression_from_json(canonical_json(first))
    assert decoded == first
    assert decoded.digest() == first.digest()


def test_nested_decoder_reconstructs_every_expression_family(context: EvaluationContext) -> None:
    expression = Select(
        And(
            (
                Eq(SameAsInputDType("q"), ConstantDType("bfloat16")),
                Or(
                    (
                        InSet(ScalarRef("tile", ScalarType.INT), (16, 32, 64)),
                        BoolLiteral(False),
                    )
                ),
            )
        ),
        RoundUp(Add(DimRef("q", 2), IntLiteral(1)), IntLiteral(32)),
        FloorDiv(Multiply(RankRef("q"), IntLiteral(8)), IntLiteral(2)),
    )
    rebuilt = expression_from_data(json.loads(canonical_json(expression)))
    assert rebuilt == expression
    assert rebuilt.evaluate(context) == 96


def test_expression_nodes_and_context_snapshots_are_immutable() -> None:
    literal = IntLiteral(3)
    with pytest.raises(FrozenInstanceError):
        literal.value = 4  # type: ignore[misc]

    tensors = {"q": TensorMetadata((1,), "float16", "cuda:0")}
    context = EvaluationContext(tensors=tensors)
    tensors["q"] = TensorMetadata((99,), "float32", "cpu")
    assert DimRef("q", 0).evaluate(context) == 1
    with pytest.raises(TypeError):
        context.tensors["x"] = TensorMetadata((1,), "float16", "cuda:0")  # type: ignore[index]


def test_construction_rejects_cross_domain_and_unsafe_values() -> None:
    with pytest.raises(ExpressionValidationError, match="integer literal"):
        IntLiteral(True)  # type: ignore[arg-type]
    with pytest.raises(ExpressionValidationError, match="valid declarative"):
        DimRef("q.__class__", 0)
    with pytest.raises(ExpressionValidationError, match="int domain"):
        Add(BoolLiteral(True), IntLiteral(1))  # type: ignore[arg-type]
    with pytest.raises(ExpressionValidationError, match="matching domains"):
        Eq(DTypeRef("q"), ConstantDevice("cuda:0"))
    with pytest.raises(ExpressionValidationError, match="unique"):
        InSet(ScalarRef("tile", ScalarType.INT), (32, 32))
    with pytest.raises(ExpressionValidationError, match="matching domains"):
        Select(BoolLiteral(True), IntLiteral(1), StringLiteral("one"))


def test_decoder_fails_closed_on_unknown_fields_nodes_and_json_ambiguity() -> None:
    invalid = (
        ({"node": "call", "function": "os.system"}, "unsupported expression node"),
        ({"node": "int_literal", "value": 1, "extra": 2}, r"unknown=\['extra'\]"),
        ({"node": "dim_ref", "argument": "q", "axis": True}, "integer, not bool"),
        ({"node": "scalar_ref", "argument": "x", "value_type": "object"}, "unsupported"),
    )
    for value, message in invalid:
        with pytest.raises(ExpressionDecodeError, match=message):
            expression_from_data(value)

    with pytest.raises(ExpressionDecodeError, match="duplicate JSON object key"):
        expression_from_json('{"node":"int_literal","value":1,"value":2}')
    with pytest.raises(ExpressionDecodeError, match="non-finite JSON number"):
        expression_from_json('{"node":"float_literal","value":NaN}')


def test_decoder_enforces_depth_limit() -> None:
    value: object = {"node": "bool_literal", "value": True}
    for _ in range(66):
        value = {"node": "not", "operand": value}
    with pytest.raises(ExpressionDecodeError, match="maximum depth"):
        expression_from_data(value)


def test_evaluation_errors_are_precise(context: EvaluationContext) -> None:
    with pytest.raises(ExpressionEvaluationError, match="missing argument"):
        DimRef("missing", 0).evaluate(context)
    with pytest.raises(ExpressionEvaluationError, match="outside rank"):
        DimRef("q", 7).evaluate(context)
    with pytest.raises(ExpressionEvaluationError, match="divisor must be nonzero"):
        FloorDiv(IntLiteral(1), IntLiteral(0)).evaluate(context)
    with pytest.raises(ExpressionEvaluationError, match="must be positive"):
        CeilDiv(IntLiteral(1), IntLiteral(-1)).evaluate(context)
    with pytest.raises(ExpressionEvaluationError, match="must be int"):
        ScalarRef("scale", ScalarType.INT).evaluate(context)


def test_rendering_and_codegen_are_stable_and_inert() -> None:
    expression = And(
        (
            Eq(DTypeRef("q"), ConstantDType("bfloat16")),
            GreaterEqual(RoundUp(DimRef("q", 2), IntLiteral(32)), IntLiteral(64)),
        )
    )
    human = render(expression)
    python_source = generate_python_validator(expression)
    native_source = generate_native_host_validator(expression)

    assert "dtype(q)" in human
    assert "round_up(dim(q, 2), 32)" in human
    assert 'metadata["q"].dtype' in python_source
    assert "-(-(" in python_source
    assert 'metadata.dtype("q")' in native_source
    assert "mindclade_round_up" in native_source
    assert "eval(" not in python_source
    assert "exec(" not in python_source


def test_shape_nodes_support_arbitrary_prefixes_and_concatenation(
    context: EvaluationContext,
) -> None:
    prefix = ShapePrefix(argument="q", trailing_rank=2)
    expression = ConcatShape(
        parts=(
            prefix,
            ShapeTuple(dimensions=(DimRef("k", 2), IntLiteral(16))),
        )
    )
    assert ShapeOf("q").evaluate(context) == (2, 7, 65, 32)
    assert prefix.evaluate(context) == (2, 7)
    assert expression.evaluate(context) == (2, 7, 33, 16)
    assert ShapePrefix("q", trailing_rank=0).evaluate(context) == (2, 7, 65, 32)
    with pytest.raises(ExpressionEvaluationError, match="exceeds rank"):
        ShapePrefix("q", trailing_rank=5).evaluate(context)


def test_broadcastable_uses_pytorch_trailing_dimension_semantics(
    context: EvaluationContext,
) -> None:
    arbitrary_leading_prefix = ShapeTuple(
        dimensions=(
            IntLiteral(9),
            IntLiteral(1),
            IntLiteral(7),
            IntLiteral(1),
            IntLiteral(32),
        )
    )
    incompatible = ShapeTuple(
        dimensions=(IntLiteral(2), IntLiteral(8), IntLiteral(65), IntLiteral(32))
    )
    scalar = ShapeTuple(dimensions=())
    assert Broadcastable(ShapeOf("q"), arbitrary_leading_prefix).evaluate(context)
    assert Broadcastable(ShapeOf("q"), scalar).evaluate(context)
    assert not Broadcastable(ShapeOf("q"), incompatible).evaluate(context)


def test_is_finite_handles_integer_and_nonfinite_float_metadata() -> None:
    assert IsFinite(IntLiteral(4)).evaluate(EvaluationContext(tensors={}))
    assert IsFinite(ScalarRef("scale", ScalarType.FLOAT)).evaluate(
        EvaluationContext(tensors={}, scalars={"scale": 0.125})
    )
    assert not IsFinite(ScalarRef("scale", ScalarType.FLOAT)).evaluate(
        EvaluationContext(tensors={}, scalars={"scale": float("nan")})
    )
    assert not IsFinite(ScalarRef("scale", ScalarType.FLOAT)).evaluate(
        EvaluationContext(tensors={}, scalars={"scale": float("inf")})
    )


def test_shape_round_trip_render_and_codegen(context: EvaluationContext) -> None:
    expression = Broadcastable(
        lhs=ConcatShape(
            parts=(
                ShapePrefix("q", trailing_rank=2),
                ShapeTuple((IntLiteral(1), DimRef("q", -1))),
            )
        ),
        rhs=ShapeOf("q"),
    )
    rebuilt = expression_from_json(canonical_json(expression))
    assert rebuilt == expression
    assert rebuilt.evaluate(context)
    assert "shape_prefix(q, trailing_rank=2)" in render(expression)
    assert "mindclade_broadcastable" in generate_python_validator(expression)
    assert "mindclade_concat_shapes" in generate_native_host_validator(expression)


def test_shape_decoder_and_domain_validation_fail_closed() -> None:
    invalid = (
        (
            {"node": "shape_tuple", "dimensions": [{"node": "bool_literal", "value": True}]},
            "must have int domain",
        ),
        (
            {"node": "shape_prefix", "argument": "q", "trailing_rank": -1},
            "must be nonnegative",
        ),
        (
            {
                "node": "broadcastable",
                "lhs": {"node": "int_literal", "value": 1},
                "rhs": {"node": "shape_tuple", "dimensions": []},
            },
            "must have shape domain",
        ),
        (
            {"node": "is_finite", "value": {"node": "string_literal", "value": "nan"}},
            "must have int or float domain",
        ),
        (
            {"node": "shape_of", "argument": "q", "unknown": True},
            "unknown=\\['unknown'\\]",
        ),
    )
    for value, message in invalid:
        with pytest.raises(ExpressionDecodeError, match=message):
            expression_from_data(value)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
