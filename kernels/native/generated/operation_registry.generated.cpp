// GENERATED FILE - DO NOT EDIT. Generator: kernels.native.codegen.generate@8.
#include <cstdint>
#include <optional>
#include <tuple>
#include <torch/csrc/stable/library.h>
#include <torch/csrc/stable/tensor.h>

#if defined(__clang__)
#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wreturn-type-c-linkage"
#endif

#if !defined(MINDCLADE_NODE_LAUNCH_ABI_V1)
#error "program-group CUDA registry requires callable node ABI v1"
#endif

extern "C" std::tuple<torch::stable::Tensor, torch::stable::Tensor> mindclade_tilelang_outer_product_mean_fwd_launch(const torch::stable::Tensor& left, const torch::stable::Tensor& right, const torch::stable::Tensor& mask, double epsilon);
extern "C" std::tuple<std::optional<torch::stable::Tensor>, std::optional<torch::stable::Tensor>, std::optional<torch::stable::Tensor>> mindclade_tilelang_outer_product_mean_bwd_launch(const torch::stable::Tensor& grad_output, const torch::stable::Tensor& left, const torch::stable::Tensor& right, const torch::stable::Tensor& mask, double epsilon, const torch::stable::Tensor& output, const torch::stable::Tensor& normalizer, bool need_left_grad, bool need_right_grad, bool need_mask_grad);
extern "C" std::tuple<torch::stable::Tensor, torch::stable::Tensor> mindclade_tilelang_pair_weighted_average_fwd_launch(const torch::stable::Tensor& value, const torch::stable::Tensor& weights, const torch::stable::Tensor& mask, double epsilon);
extern "C" std::tuple<std::optional<torch::stable::Tensor>, std::optional<torch::stable::Tensor>> mindclade_tilelang_pair_weighted_average_bwd_launch(const torch::stable::Tensor& grad_output, const torch::stable::Tensor& value, const torch::stable::Tensor& weights, const torch::stable::Tensor& mask, const torch::stable::Tensor& output, const torch::stable::Tensor& lse, bool need_value_grad, bool need_weights_grad);
extern "C" std::tuple<torch::stable::Tensor, torch::stable::Tensor> mindclade_tilelang_transition_fwd_launch(const torch::stable::Tensor& gate, const torch::stable::Tensor& value, const torch::stable::Tensor& output_weight, const torch::stable::Tensor& output_bias, const torch::stable::Tensor& mask);
extern "C" std::tuple<std::optional<torch::stable::Tensor>, std::optional<torch::stable::Tensor>, std::optional<torch::stable::Tensor>, std::optional<torch::stable::Tensor>, std::optional<torch::stable::Tensor>> mindclade_tilelang_transition_bwd_launch(const torch::stable::Tensor& grad_output, const torch::stable::Tensor& gate, const torch::stable::Tensor& value, const torch::stable::Tensor& output_weight, const torch::stable::Tensor& mask, const torch::stable::Tensor& pre_mask_output, bool need_gate_grad, bool need_value_grad, bool need_weight_grad, bool need_bias_grad, bool need_mask_grad);
extern "C" std::tuple<torch::stable::Tensor, torch::stable::Tensor> mindclade_tilelang_triangle_attention_fwd_launch(const torch::stable::Tensor& q, const torch::stable::Tensor& k, const torch::stable::Tensor& v, const torch::stable::Tensor& bias, const torch::stable::Tensor& mask, double scale);
extern "C" std::tuple<std::optional<torch::stable::Tensor>, std::optional<torch::stable::Tensor>, std::optional<torch::stable::Tensor>, std::optional<torch::stable::Tensor>> mindclade_tilelang_triangle_attention_bwd_launch(const torch::stable::Tensor& grad_output, const torch::stable::Tensor& q, const torch::stable::Tensor& k, const torch::stable::Tensor& v, const torch::stable::Tensor& bias, const torch::stable::Tensor& mask, double scale, const torch::stable::Tensor& output, const torch::stable::Tensor& lse, bool need_q_grad, bool need_k_grad, bool need_v_grad, bool need_bias_grad);
extern "C" torch::stable::Tensor mindclade_tilelang_triangle_multiplication_fwd_launch(const torch::stable::Tensor& left, const torch::stable::Tensor& right, const torch::stable::Tensor& mask, bool outgoing);
extern "C" std::tuple<std::optional<torch::stable::Tensor>, std::optional<torch::stable::Tensor>> mindclade_tilelang_triangle_multiplication_bwd_launch(const torch::stable::Tensor& grad_output, const torch::stable::Tensor& left, const torch::stable::Tensor& right, const torch::stable::Tensor& mask, bool outgoing, bool need_left_grad, bool need_right_grad);

namespace mindclade::native::tilelang {
std::tuple<torch::stable::Tensor, torch::stable::Tensor> outer_product_mean_semantic(const torch::stable::Tensor& left, const torch::stable::Tensor& right, const torch::stable::Tensor& mask, double epsilon) {
  return mindclade_tilelang_outer_product_mean_fwd_launch(left, right, mask, epsilon);
}
std::tuple<torch::stable::Tensor, torch::stable::Tensor> outer_product_mean_forward(const torch::stable::Tensor& left, const torch::stable::Tensor& right, const torch::stable::Tensor& mask, double epsilon) {
  return mindclade_tilelang_outer_product_mean_fwd_launch(left, right, mask, epsilon);
}
std::tuple<std::optional<torch::stable::Tensor>, std::optional<torch::stable::Tensor>, std::optional<torch::stable::Tensor>> outer_product_mean_backward(const torch::stable::Tensor& grad_output, const torch::stable::Tensor& left, const torch::stable::Tensor& right, const torch::stable::Tensor& mask, double epsilon, const torch::stable::Tensor& output, const torch::stable::Tensor& normalizer, bool need_left_grad, bool need_right_grad, bool need_mask_grad) {
  return mindclade_tilelang_outer_product_mean_bwd_launch(grad_output, left, right, mask, epsilon, output, normalizer, need_left_grad, need_right_grad, need_mask_grad);
}
std::tuple<torch::stable::Tensor, torch::stable::Tensor> pair_weighted_average_semantic(const torch::stable::Tensor& value, const torch::stable::Tensor& weights, const torch::stable::Tensor& mask, double epsilon) {
  return mindclade_tilelang_pair_weighted_average_fwd_launch(value, weights, mask, epsilon);
}
std::tuple<torch::stable::Tensor, torch::stable::Tensor> pair_weighted_average_forward(const torch::stable::Tensor& value, const torch::stable::Tensor& weights, const torch::stable::Tensor& mask, double epsilon) {
  return mindclade_tilelang_pair_weighted_average_fwd_launch(value, weights, mask, epsilon);
}
std::tuple<std::optional<torch::stable::Tensor>, std::optional<torch::stable::Tensor>> pair_weighted_average_backward(const torch::stable::Tensor& grad_output, const torch::stable::Tensor& value, const torch::stable::Tensor& weights, const torch::stable::Tensor& mask, const torch::stable::Tensor& output, const torch::stable::Tensor& lse, bool need_value_grad, bool need_weights_grad) {
  return mindclade_tilelang_pair_weighted_average_bwd_launch(grad_output, value, weights, mask, output, lse, need_value_grad, need_weights_grad);
}
std::tuple<torch::stable::Tensor, torch::stable::Tensor> transition_semantic(const torch::stable::Tensor& gate, const torch::stable::Tensor& value, const torch::stable::Tensor& output_weight, const torch::stable::Tensor& output_bias, const torch::stable::Tensor& mask) {
  return mindclade_tilelang_transition_fwd_launch(gate, value, output_weight, output_bias, mask);
}
std::tuple<torch::stable::Tensor, torch::stable::Tensor> transition_forward(const torch::stable::Tensor& gate, const torch::stable::Tensor& value, const torch::stable::Tensor& output_weight, const torch::stable::Tensor& output_bias, const torch::stable::Tensor& mask) {
  return mindclade_tilelang_transition_fwd_launch(gate, value, output_weight, output_bias, mask);
}
std::tuple<std::optional<torch::stable::Tensor>, std::optional<torch::stable::Tensor>, std::optional<torch::stable::Tensor>, std::optional<torch::stable::Tensor>, std::optional<torch::stable::Tensor>> transition_backward(const torch::stable::Tensor& grad_output, const torch::stable::Tensor& gate, const torch::stable::Tensor& value, const torch::stable::Tensor& output_weight, const torch::stable::Tensor& mask, const torch::stable::Tensor& pre_mask_output, bool need_gate_grad, bool need_value_grad, bool need_weight_grad, bool need_bias_grad, bool need_mask_grad) {
  return mindclade_tilelang_transition_bwd_launch(grad_output, gate, value, output_weight, mask, pre_mask_output, need_gate_grad, need_value_grad, need_weight_grad, need_bias_grad, need_mask_grad);
}
std::tuple<torch::stable::Tensor, torch::stable::Tensor> triangle_attention_semantic(const torch::stable::Tensor& q, const torch::stable::Tensor& k, const torch::stable::Tensor& v, const torch::stable::Tensor& bias, const torch::stable::Tensor& mask, double scale) {
  return mindclade_tilelang_triangle_attention_fwd_launch(q, k, v, bias, mask, scale);
}
std::tuple<torch::stable::Tensor, torch::stable::Tensor> triangle_attention_forward(const torch::stable::Tensor& q, const torch::stable::Tensor& k, const torch::stable::Tensor& v, const torch::stable::Tensor& bias, const torch::stable::Tensor& mask, double scale) {
  return mindclade_tilelang_triangle_attention_fwd_launch(q, k, v, bias, mask, scale);
}
std::tuple<std::optional<torch::stable::Tensor>, std::optional<torch::stable::Tensor>, std::optional<torch::stable::Tensor>, std::optional<torch::stable::Tensor>> triangle_attention_backward(const torch::stable::Tensor& grad_output, const torch::stable::Tensor& q, const torch::stable::Tensor& k, const torch::stable::Tensor& v, const torch::stable::Tensor& bias, const torch::stable::Tensor& mask, double scale, const torch::stable::Tensor& output, const torch::stable::Tensor& lse, bool need_q_grad, bool need_k_grad, bool need_v_grad, bool need_bias_grad) {
  return mindclade_tilelang_triangle_attention_bwd_launch(grad_output, q, k, v, bias, mask, scale, output, lse, need_q_grad, need_k_grad, need_v_grad, need_bias_grad);
}
torch::stable::Tensor triangle_multiplication_semantic(const torch::stable::Tensor& left, const torch::stable::Tensor& right, const torch::stable::Tensor& mask, bool outgoing) {
  return mindclade_tilelang_triangle_multiplication_fwd_launch(left, right, mask, outgoing);
}
torch::stable::Tensor triangle_multiplication_forward(const torch::stable::Tensor& left, const torch::stable::Tensor& right, const torch::stable::Tensor& mask, bool outgoing) {
  return mindclade_tilelang_triangle_multiplication_fwd_launch(left, right, mask, outgoing);
}
std::tuple<std::optional<torch::stable::Tensor>, std::optional<torch::stable::Tensor>> triangle_multiplication_backward(const torch::stable::Tensor& grad_output, const torch::stable::Tensor& left, const torch::stable::Tensor& right, const torch::stable::Tensor& mask, bool outgoing, bool need_left_grad, bool need_right_grad) {
  return mindclade_tilelang_triangle_multiplication_bwd_launch(grad_output, left, right, mask, outgoing, need_left_grad, need_right_grad);
}
}  // namespace mindclade::native::tilelang

STABLE_TORCH_LIBRARY_IMPL(mindclade, CUDA, m) {
  m.impl("outer_product_mean", TORCH_BOX(&mindclade::native::tilelang::outer_product_mean_semantic));
  m.impl("_outer_product_mean_fwd", TORCH_BOX(&mindclade::native::tilelang::outer_product_mean_forward));
  m.impl("_outer_product_mean_bwd", TORCH_BOX(&mindclade::native::tilelang::outer_product_mean_backward));
  m.impl("pair_weighted_average", TORCH_BOX(&mindclade::native::tilelang::pair_weighted_average_semantic));
  m.impl("_pair_weighted_average_fwd", TORCH_BOX(&mindclade::native::tilelang::pair_weighted_average_forward));
  m.impl("_pair_weighted_average_bwd", TORCH_BOX(&mindclade::native::tilelang::pair_weighted_average_backward));
  m.impl("transition", TORCH_BOX(&mindclade::native::tilelang::transition_semantic));
  m.impl("_transition_fwd", TORCH_BOX(&mindclade::native::tilelang::transition_forward));
  m.impl("_transition_bwd", TORCH_BOX(&mindclade::native::tilelang::transition_backward));
  m.impl("triangle_attention", TORCH_BOX(&mindclade::native::tilelang::triangle_attention_semantic));
  m.impl("_triangle_attention_fwd", TORCH_BOX(&mindclade::native::tilelang::triangle_attention_forward));
  m.impl("_triangle_attention_bwd", TORCH_BOX(&mindclade::native::tilelang::triangle_attention_backward));
  m.impl("triangle_multiplication", TORCH_BOX(&mindclade::native::tilelang::triangle_multiplication_semantic));
  m.impl("_triangle_multiplication_fwd", TORCH_BOX(&mindclade::native::tilelang::triangle_multiplication_forward));
  m.impl("_triangle_multiplication_bwd", TORCH_BOX(&mindclade::native::tilelang::triangle_multiplication_backward));
}

#if defined(__clang__)
#pragma clang diagnostic pop
#endif
