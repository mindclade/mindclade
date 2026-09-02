// GENERATED FILE - DO NOT EDIT. Generator: kernels.native.codegen.generate@7.
#include <array>
#include <cstddef>
#include <string_view>

extern "C" void mindclade_tilelang_outer_product_mean_dleft_launch();
extern "C" void mindclade_tilelang_outer_product_mean_dmask_launch();
extern "C" void mindclade_tilelang_outer_product_mean_dright_launch();
extern "C" void mindclade_tilelang_outer_product_mean_normalizer_launch();
extern "C" void mindclade_tilelang_outer_product_mean_numerator_launch();
extern "C" void mindclade_tilelang_pair_weighted_average_delta_launch();
extern "C" void mindclade_tilelang_pair_weighted_average_dvalue_launch();
extern "C" void mindclade_tilelang_pair_weighted_average_dweights_launch();
extern "C" void mindclade_tilelang_pair_weighted_average_online_forward_launch();
extern "C" void mindclade_tilelang_transition_forward_program_launch();
extern "C" void mindclade_tilelang_transition_grad_bias_launch();
extern "C" void mindclade_tilelang_transition_grad_gate_value_launch();
extern "C" void mindclade_tilelang_transition_grad_mask_launch();
extern "C" void mindclade_tilelang_transition_grad_weight_launch();
extern "C" void mindclade_tilelang_triangle_attention_dbias_raw();
extern "C" void mindclade_tilelang_triangle_attention_delta_raw();
extern "C" void mindclade_tilelang_triangle_attention_dkv_raw();
extern "C" void mindclade_tilelang_triangle_attention_dq_raw();
extern "C" void mindclade_tilelang_triangle_attention_forward_raw();
extern "C" void mindclade_tilelang_triangle_multiplication_dleft_raw();
extern "C" void mindclade_tilelang_triangle_multiplication_dright_raw();
extern "C" void mindclade_tilelang_triangle_multiplication_forward_raw();

namespace mindclade::native::generated {
using PrivateLauncher = void (*)();
const std::array<PrivateLauncher, 22> kRequiredPrivateLaunchers{{
    &mindclade_tilelang_outer_product_mean_dleft_launch,
    &mindclade_tilelang_outer_product_mean_dmask_launch,
    &mindclade_tilelang_outer_product_mean_dright_launch,
    &mindclade_tilelang_outer_product_mean_normalizer_launch,
    &mindclade_tilelang_outer_product_mean_numerator_launch,
    &mindclade_tilelang_pair_weighted_average_delta_launch,
    &mindclade_tilelang_pair_weighted_average_dvalue_launch,
    &mindclade_tilelang_pair_weighted_average_dweights_launch,
    &mindclade_tilelang_pair_weighted_average_online_forward_launch,
    &mindclade_tilelang_transition_forward_program_launch,
    &mindclade_tilelang_transition_grad_bias_launch,
    &mindclade_tilelang_transition_grad_gate_value_launch,
    &mindclade_tilelang_transition_grad_mask_launch,
    &mindclade_tilelang_transition_grad_weight_launch,
    &mindclade_tilelang_triangle_attention_dbias_raw,
    &mindclade_tilelang_triangle_attention_delta_raw,
    &mindclade_tilelang_triangle_attention_dkv_raw,
    &mindclade_tilelang_triangle_attention_dq_raw,
    &mindclade_tilelang_triangle_attention_forward_raw,
    &mindclade_tilelang_triangle_multiplication_dleft_raw,
    &mindclade_tilelang_triangle_multiplication_dright_raw,
    &mindclade_tilelang_triangle_multiplication_forward_raw,
}};

constexpr std::array<std::string_view, 10> kStaticLauncherPlans{{
    R"mindclade({"execution_order":["normalizer","numerator"],"logical_symbol":"mindclade_tilelang_outer_product_mean_fwd_launch","operation":"mindclade::outer_product_mean","outputs":[{"initialization":null,"name":"output","saved_for_backward":true},{"initialization":null,"name":"normalizer","saved_for_backward":true}],"phase":"forward","required_private_symbols":["mindclade_tilelang_outer_product_mean_normalizer_launch","mindclade_tilelang_outer_product_mean_numerator_launch"],"workspaces":[{"dtype":{"node":"constant_dtype","value":"float32"},"lifetime":"program_group","name":"normalizer","shape":{"node":"concat_shape","parts":[{"argument":"left","node":"shape_prefix","trailing_rank":3},{"dimensions":[{"argument":"left","axis":-2,"node":"dim_ref"},{"argument":"right","axis":-2,"node":"dim_ref"}],"node":"shape_tuple"}]},"zero_initialize":false}]})mindclade",
    R"mindclade({"execution_order":["dleft","dmask","dright"],"logical_symbol":"mindclade_tilelang_outer_product_mean_bwd_launch","operation":"mindclade::outer_product_mean","outputs":[],"phase":"backward","required_private_symbols":["mindclade_tilelang_outer_product_mean_dleft_launch","mindclade_tilelang_outer_product_mean_dmask_launch","mindclade_tilelang_outer_product_mean_dright_launch"],"workspaces":[]})mindclade",
    R"mindclade({"execution_order":["online_forward"],"logical_symbol":"mindclade_tilelang_pair_weighted_average_fwd_launch","operation":"mindclade::pair_weighted_average","outputs":[{"initialization":null,"name":"output","saved_for_backward":true},{"initialization":null,"name":"lse","saved_for_backward":true}],"phase":"forward","required_private_symbols":["mindclade_tilelang_pair_weighted_average_online_forward_launch"],"workspaces":[]})mindclade",
    R"mindclade({"execution_order":["delta","dvalue","dweights"],"logical_symbol":"mindclade_tilelang_pair_weighted_average_bwd_launch","operation":"mindclade::pair_weighted_average","outputs":[],"phase":"backward","required_private_symbols":["mindclade_tilelang_pair_weighted_average_delta_launch","mindclade_tilelang_pair_weighted_average_dvalue_launch","mindclade_tilelang_pair_weighted_average_dweights_launch"],"workspaces":[{"dtype":{"node":"constant_dtype","value":"float32"},"lifetime":"program_group","name":"delta","shape":{"node":"concat_shape","parts":[{"argument":"value","node":"shape_prefix","trailing_rank":2},{"dimensions":[{"argument":"value","axis":-2,"node":"dim_ref"},{"argument":"weights","axis":-1,"node":"dim_ref"}],"node":"shape_tuple"}]},"zero_initialize":false}]})mindclade",
    R"mindclade({"execution_order":["transition_forward"],"logical_symbol":"mindclade_tilelang_transition_fwd_launch","operation":"mindclade::transition","outputs":[{"initialization":null,"name":"output","saved_for_backward":false},{"initialization":null,"name":"pre_mask_output","saved_for_backward":true}],"phase":"forward","required_private_symbols":["mindclade_tilelang_transition_forward_program_launch"],"workspaces":[]})mindclade",
    R"mindclade({"execution_order":["grad_bias","grad_gate_value","grad_mask","grad_weight"],"logical_symbol":"mindclade_tilelang_transition_bwd_launch","operation":"mindclade::transition","outputs":[],"phase":"backward","required_private_symbols":["mindclade_tilelang_transition_grad_bias_launch","mindclade_tilelang_transition_grad_gate_value_launch","mindclade_tilelang_transition_grad_mask_launch","mindclade_tilelang_transition_grad_weight_launch"],"workspaces":[]})mindclade",
    R"mindclade({"execution_order":["forward"],"logical_symbol":"mindclade_tilelang_triangle_attention_fwd_launch","operation":"mindclade::triangle_attention","outputs":[{"initialization":null,"name":"output","saved_for_backward":true},{"initialization":{"mode":"negative_infinity","type":"InitializationSpec","value":null,"version":1},"name":"lse","saved_for_backward":true}],"phase":"forward","required_private_symbols":["mindclade_tilelang_triangle_attention_forward_raw"],"workspaces":[]})mindclade",
    R"mindclade({"execution_order":["delta","dbias","dkv","dq"],"logical_symbol":"mindclade_tilelang_triangle_attention_bwd_launch","operation":"mindclade::triangle_attention","outputs":[],"phase":"backward","required_private_symbols":["mindclade_tilelang_triangle_attention_delta_raw","mindclade_tilelang_triangle_attention_dbias_raw","mindclade_tilelang_triangle_attention_dkv_raw","mindclade_tilelang_triangle_attention_dq_raw"],"workspaces":[{"dtype":{"node":"constant_dtype","value":"float32"},"lifetime":"program_group","name":"delta","shape":{"dimensions":[{"argument":"q","axis":0,"node":"dim_ref"},{"argument":"q","axis":1,"node":"dim_ref"},{"argument":"q","axis":3,"node":"dim_ref"},{"multiple":{"node":"int_literal","value":32},"node":"round_up","value":{"argument":"q","axis":2,"node":"dim_ref"}}],"node":"shape_tuple"},"zero_initialize":false}]})mindclade",
    R"mindclade({"execution_order":["forward"],"logical_symbol":"mindclade_tilelang_triangle_multiplication_fwd_launch","operation":"mindclade::triangle_multiplication","outputs":[{"initialization":null,"name":"output","saved_for_backward":false}],"phase":"forward","required_private_symbols":["mindclade_tilelang_triangle_multiplication_forward_raw"],"workspaces":[]})mindclade",
    R"mindclade({"execution_order":["dleft","dright"],"logical_symbol":"mindclade_tilelang_triangle_multiplication_bwd_launch","operation":"mindclade::triangle_multiplication","outputs":[],"phase":"backward","required_private_symbols":["mindclade_tilelang_triangle_multiplication_dleft_raw","mindclade_tilelang_triangle_multiplication_dright_raw"],"workspaces":[]})mindclade",
}};
}  // namespace mindclade::native::generated

extern "C" const mindclade::native::generated::PrivateLauncher*
mindclade_native_required_private_launchers() noexcept {
  return mindclade::native::generated::kRequiredPrivateLaunchers.data();
}

extern "C" std::size_t mindclade_native_static_launcher_plan_count() noexcept {
  return mindclade::native::generated::kStaticLauncherPlans.size();
}
