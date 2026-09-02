// GENERATED FILE - DO NOT EDIT. Generator: kernels.native.codegen.generate@8.
#include <torch/csrc/stable/library.h>

STABLE_TORCH_LIBRARY(mindclade, m) {
  m.def("outer_product_mean(Tensor left, Tensor right, Tensor mask, float epsilon) -> (Tensor output, Tensor normalizer)");
  m.def("_outer_product_mean_fwd(Tensor left, Tensor right, Tensor mask, float epsilon) -> (Tensor output, Tensor normalizer)");
  m.def("_outer_product_mean_bwd(Tensor grad_output, Tensor left, Tensor right, Tensor mask, float epsilon, Tensor output, Tensor normalizer, bool need_left_grad, bool need_right_grad, bool need_mask_grad) -> (Tensor? grad_left, Tensor? grad_right, Tensor? grad_mask)");
  m.def("pair_weighted_average(Tensor value, Tensor weights, Tensor mask, float epsilon) -> (Tensor output, Tensor lse)");
  m.def("_pair_weighted_average_fwd(Tensor value, Tensor weights, Tensor mask, float epsilon) -> (Tensor output, Tensor lse)");
  m.def("_pair_weighted_average_bwd(Tensor grad_output, Tensor value, Tensor weights, Tensor mask, Tensor output, Tensor lse, bool need_value_grad, bool need_weights_grad) -> (Tensor? grad_value, Tensor? grad_weights)");
  m.def("transition(Tensor gate, Tensor value, Tensor output_weight, Tensor output_bias, Tensor mask) -> (Tensor output, Tensor pre_mask_output)");
  m.def("_transition_fwd(Tensor gate, Tensor value, Tensor output_weight, Tensor output_bias, Tensor mask) -> (Tensor output, Tensor pre_mask_output)");
  m.def("_transition_bwd(Tensor grad_output, Tensor gate, Tensor value, Tensor output_weight, Tensor mask, Tensor pre_mask_output, bool need_gate_grad, bool need_value_grad, bool need_weight_grad, bool need_bias_grad, bool need_mask_grad) -> (Tensor? grad_gate, Tensor? grad_value, Tensor? grad_weight, Tensor? grad_bias, Tensor? grad_mask)");
  m.def("triangle_attention(Tensor q, Tensor k, Tensor v, Tensor bias, Tensor mask, float scale) -> (Tensor output, Tensor lse)");
  m.def("_triangle_attention_fwd(Tensor q, Tensor k, Tensor v, Tensor bias, Tensor mask, float scale) -> (Tensor output, Tensor lse)");
  m.def("_triangle_attention_bwd(Tensor grad_output, Tensor q, Tensor k, Tensor v, Tensor bias, Tensor mask, float scale, Tensor output, Tensor lse, bool need_q_grad, bool need_k_grad, bool need_v_grad, bool need_bias_grad) -> (Tensor? grad_q, Tensor? grad_k, Tensor? grad_v, Tensor? grad_bias)");
  m.def("triangle_multiplication(Tensor left, Tensor right, Tensor mask, bool outgoing) -> Tensor output");
  m.def("_triangle_multiplication_fwd(Tensor left, Tensor right, Tensor mask, bool outgoing) -> Tensor output");
  m.def("_triangle_multiplication_bwd(Tensor grad_output, Tensor left, Tensor right, Tensor mask, bool outgoing, bool need_left_grad, bool need_right_grad) -> (Tensor? grad_left, Tensor? grad_right)");
}
