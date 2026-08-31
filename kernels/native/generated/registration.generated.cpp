// GENERATED FILE - DO NOT EDIT. Generator: kernels.native.codegen.generate@5.
#include <torch/csrc/stable/library.h>

STABLE_TORCH_LIBRARY(mindclade, m) {
  m.def("outer_product_mean(Tensor left, Tensor right, Tensor mask, float epsilon) -> Tensor output");
  m.def("_outer_product_mean_fwd(Tensor left, Tensor right, Tensor mask, float epsilon) -> Tensor output");
  m.def("pair_weighted_average(Tensor value, Tensor weights, Tensor mask, float epsilon) -> Tensor output");
  m.def("_pair_weighted_average_fwd(Tensor value, Tensor weights, Tensor mask, float epsilon) -> Tensor output");
  m.def("transition(Tensor gate, Tensor value, Tensor output_weight, Tensor output_bias, Tensor mask) -> Tensor output");
  m.def("_transition_fwd(Tensor gate, Tensor value, Tensor output_weight, Tensor output_bias, Tensor mask) -> Tensor output");
  m.def("triangle_attention(Tensor q, Tensor k, Tensor v, Tensor bias, Tensor mask, float scale) -> Tensor output");
  m.def("_triangle_attention_fwd(Tensor q, Tensor k, Tensor v, Tensor bias, Tensor mask, float scale) -> Tensor output");
  m.def("triangle_multiplication(Tensor left, Tensor right, Tensor mask, bool outgoing) -> Tensor output");
  m.def("_triangle_multiplication_fwd(Tensor left, Tensor right, Tensor mask, bool outgoing) -> Tensor output");
}
