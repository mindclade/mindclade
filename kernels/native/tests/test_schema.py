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


@pytest.mark.parametrize("schema", (
    "Example(Tensor x) -> Tensor output",
    "example(Tensor x) -> Tensor",
    "example(Tensor? x) -> Tensor output",
    "example(Tensor x, Tensor x) -> Tensor output",
    "example(Tensor x)-> Tensor output",
))
def test_schema_rejects_noncanonical_or_unsupported_syntax(schema: str):
    with pytest.raises(ValueError):
        parse_schema(schema)
