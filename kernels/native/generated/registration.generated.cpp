// GENERATED FILE - DO NOT EDIT. Generator: kernels.native.codegen.generate@2.
#include <torch/csrc/stable/library.h>

STABLE_TORCH_LIBRARY(mindclade, m) {
  m.def("outer_product_mean(Tensor left, Tensor right, Tensor mask, float epsilon) -> Tensor");
  m.def("pair_weighted_average(Tensor value, Tensor weights, Tensor mask, float epsilon) -> Tensor");
  m.def("transition(Tensor gate, Tensor value, Tensor output_weight, Tensor output_bias, Tensor mask) -> Tensor");
  m.def("triangle_attention(Tensor q, Tensor k, Tensor v, Tensor bias, Tensor mask, float scale) -> Tensor");
  m.def("triangle_multiplication(Tensor left, Tensor right, Tensor mask, bool outgoing) -> Tensor");
}
