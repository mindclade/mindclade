import pytest

from kernels.native.codegen.schema import parse_schema


def test_schema_parses_named_single_and_tuple_returns_for_stable_abi():
    single = parse_schema("example(Tensor x, float scale, int width, bool mode) -> Tensor output")
    assert single.argument_names == ("x", "scale", "width", "mode")
    assert single.return_names == ("output",)
    assert single.cpp_return_type == "torch::stable::Tensor"
    multiple = parse_schema("_example_bwd(Tensor grad) -> (Tensor grad_x, Tensor grad_y)")
    assert multiple.return_names == ("grad_x", "grad_y")
    assert multiple.cpp_return_type.startswith("torch::stable::std::tuple<")


def test_exact_name_lookup_preserves_declared_abi_order_and_optional_types():
    schema = parse_schema(
        "example(Tensor x, Tensor? bias, bool need_bias, float scale, int axis) "
        "-> (Tensor output, Tensor? auxiliary)"
    )
    assert schema.argument_names == ("x", "bias", "need_bias", "scale", "axis")
    assert schema.return_names == ("output", "auxiliary")
    assert schema.argument_by_name("bias") is schema.args[1]
    assert schema.return_by_name("auxiliary") is schema.returns[1]
    with pytest.raises(KeyError, match="no argument named 'missing'"):
        schema.argument_by_name("missing")
    with pytest.raises(KeyError, match="no return named 'missing'"):
        schema.return_by_name("missing")

    tensor = schema.argument_by_name("x")
    optional_tensor = schema.argument_by_name("bias")
    request = schema.argument_by_name("need_bias")
    scalar = schema.argument_by_name("scale")
    assert tensor.is_tensor and not tensor.is_optional and not tensor.is_scalar
    assert optional_tensor.is_tensor and optional_tensor.is_optional
    assert optional_tensor.normalized_kind == "Tensor"
    assert optional_tensor.type_identity == ("Tensor", True)
    assert request.is_bool and request.is_scalar
    assert scalar.is_scalar and not scalar.is_bool
    assert "optional" in optional_tensor.cpp_type
    assert "optional" in schema.return_by_name("auxiliary").cpp_type


def test_exact_signature_comparison_uses_names_types_optionality_and_order():
    semantic = parse_schema("example(Tensor x, Tensor? bias) -> Tensor output")
    forward = parse_schema("_example_fwd(Tensor x, Tensor? bias) -> Tensor output")
    assert semantic.has_exact_signature(forward)
    assert not semantic.has_exact_signature(
        parse_schema("_example_fwd(Tensor? x, Tensor? bias) -> Tensor output")
    )
    assert not semantic.has_exact_signature(
        parse_schema("_example_fwd(Tensor? bias, Tensor x) -> Tensor output")
    )
    assert not semantic.has_exact_signature(
        parse_schema("_example_fwd(Tensor x, Tensor? bias) -> Tensor result")
    )


def test_duplicate_names_fail_with_argument_or_return_identity():
    with pytest.raises(ValueError, match="duplicate argument name 'x'"):
        parse_schema("example(Tensor x, Tensor? x) -> Tensor output")
    with pytest.raises(ValueError, match="duplicate return name 'output'"):
        parse_schema("example(Tensor x) -> (Tensor output, Tensor? output)")


@pytest.mark.parametrize(
    ("schema", "identity"),
    (
        ("class(Tensor x) -> Tensor output", "operator name 'class'"),
        ("example(Tensor from) -> Tensor output", "argument name 'from'"),
        ("example(Tensor x) -> Tensor template", "return name 'template'"),
        ("example(Tensor operator) -> Tensor output", "argument name 'operator'"),
    ),
)
def test_language_reserved_names_are_rejected_before_codegen(
    schema: str, identity: str
):
    with pytest.raises(ValueError, match=identity):
        parse_schema(schema)


@pytest.mark.parametrize("schema", (
    "Example(Tensor x) -> Tensor output",
    "example(Tensor x) -> Tensor",
    "example(Tensor ? x) -> Tensor output",
    "example(Tensor x, Tensor x) -> Tensor output",
    "example(Tensor x)-> Tensor output",
))
def test_schema_rejects_noncanonical_or_unsupported_syntax(schema: str):
    with pytest.raises(ValueError):
        parse_schema(schema)
