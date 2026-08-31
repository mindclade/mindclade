// GENERATED FILE - DO NOT EDIT. Generator: kernels.native.codegen.generate@2.
#include <cstdint>
#include <torch/csrc/stable/library.h>
#include <torch/csrc/stable/tensor.h>

extern "C" torch::stable::Tensor mindclade_tilelang_outer_product_mean_launch(const torch::stable::Tensor& left, const torch::stable::Tensor& right, const torch::stable::Tensor& mask, double epsilon);
extern "C" torch::stable::Tensor mindclade_tilelang_pair_weighted_average_launch(const torch::stable::Tensor& value, const torch::stable::Tensor& weights, const torch::stable::Tensor& mask, double epsilon);
extern "C" torch::stable::Tensor mindclade_tilelang_transition_launch(const torch::stable::Tensor& gate, const torch::stable::Tensor& value, const torch::stable::Tensor& output_weight, const torch::stable::Tensor& output_bias, const torch::stable::Tensor& mask);
extern "C" torch::stable::Tensor mindclade_tilelang_triangle_attention_launch(const torch::stable::Tensor& q, const torch::stable::Tensor& k, const torch::stable::Tensor& v, const torch::stable::Tensor& bias, const torch::stable::Tensor& mask, double scale);
extern "C" torch::stable::Tensor mindclade_tilelang_triangle_multiplication_launch(const torch::stable::Tensor& left, const torch::stable::Tensor& right, const torch::stable::Tensor& mask, bool outgoing);

namespace mindclade::native::tilelang {
torch::stable::Tensor outer_product_mean(const torch::stable::Tensor& left, const torch::stable::Tensor& right, const torch::stable::Tensor& mask, double epsilon) {
  return mindclade_tilelang_outer_product_mean_launch(left, right, mask, epsilon);
}
torch::stable::Tensor pair_weighted_average(const torch::stable::Tensor& value, const torch::stable::Tensor& weights, const torch::stable::Tensor& mask, double epsilon) {
  return mindclade_tilelang_pair_weighted_average_launch(value, weights, mask, epsilon);
}
torch::stable::Tensor transition(const torch::stable::Tensor& gate, const torch::stable::Tensor& value, const torch::stable::Tensor& output_weight, const torch::stable::Tensor& output_bias, const torch::stable::Tensor& mask) {
  return mindclade_tilelang_transition_launch(gate, value, output_weight, output_bias, mask);
}
torch::stable::Tensor triangle_attention(const torch::stable::Tensor& q, const torch::stable::Tensor& k, const torch::stable::Tensor& v, const torch::stable::Tensor& bias, const torch::stable::Tensor& mask, double scale) {
  return mindclade_tilelang_triangle_attention_launch(q, k, v, bias, mask, scale);
}
torch::stable::Tensor triangle_multiplication(const torch::stable::Tensor& left, const torch::stable::Tensor& right, const torch::stable::Tensor& mask, bool outgoing) {
  return mindclade_tilelang_triangle_multiplication_launch(left, right, mask, outgoing);
}
}  // namespace mindclade::native::tilelang

STABLE_TORCH_LIBRARY_IMPL(mindclade, CUDA, m) {
  m.impl("outer_product_mean", TORCH_BOX(&mindclade::native::tilelang::outer_product_mean));
  m.impl("pair_weighted_average", TORCH_BOX(&mindclade::native::tilelang::pair_weighted_average));
  m.impl("transition", TORCH_BOX(&mindclade::native::tilelang::transition));
  m.impl("triangle_attention", TORCH_BOX(&mindclade::native::tilelang::triangle_attention));
  m.impl("triangle_multiplication", TORCH_BOX(&mindclade::native::tilelang::triangle_multiplication));
}
