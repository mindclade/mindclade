// GENERATED FILE - DO NOT EDIT. Generator: kernels.native.codegen.generate@8.
#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>
#include <optional>
#include <stdexcept>
#include <string>
#include <string_view>
#include <tuple>
#include <vector>
#include <torch/csrc/stable/tensor.h>
#include "../stable_abi/node_launch_bridge.h"
#include "../stable_abi/qualified_capability_table.h"
#include "../stable_abi/tensor_bridge.h"

extern "C" std::int32_t mindclade_cuda_device_architecture_v1(
    std::int32_t device_index, std::uint32_t* architecture);

#if defined(__clang__)
#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wreturn-type-c-linkage"
#endif


namespace mindclade::native::generated {
using PrivateLauncher = void (*)();
const std::array<PrivateLauncher, 0> kRequiredPrivateLaunchers{{
}};

using mindclade::native::stable_abi::InitializationMode;
using mindclade::native::stable_abi::TensorDType;
using mindclade::native::stable_abi::allocate_cuda_tensor;
using mindclade::native::stable_abi::allocate_workspace;
using mindclade::native::stable_abi::current_cuda_stream;
using mindclade::native::stable_abi::make_absent_node_tensor_value;
using mindclade::native::stable_abi::make_node_bool_value;
using mindclade::native::stable_abi::make_node_float64_value;
using mindclade::native::stable_abi::make_node_int64_value;
using mindclade::native::stable_abi::make_node_stream_value;
using mindclade::native::stable_abi::make_node_tensor_value;
using mindclade::native::stable_abi::node_dtype;
using mindclade::native::stable_abi::require_cuda_contiguous_tensor;
using mindclade::native::stable_abi::require_same_device;
using mindclade::native::stable_abi::tensor_dimension;

extern "C" std::tuple<torch::stable::Tensor, torch::stable::Tensor> mindclade_tilelang_outer_product_mean_fwd_launch(const torch::stable::Tensor& left, const torch::stable::Tensor& right, const torch::stable::Tensor& mask, double epsilon) {
  const auto left_view = require_cuda_contiguous_tensor(left, "left");
  const auto right_view = require_cuda_contiguous_tensor(right, "right");
  const auto mask_view = require_cuda_contiguous_tensor(mask, "mask");
  require_same_device(left_view, right_view, "right");
  require_same_device(left_view, mask_view, "mask");
  const std::array<MindcladeCapabilityDimensionV1, 5> workload_dimensions{{
      {"batch_size", tensor_dimension(left_view, 0, "left")},
      {"left_channels", tensor_dimension(left_view, 3, "left")},
      {"node_count", tensor_dimension(left_view, 2, "left")},
      {"right_channels", tensor_dimension(right_view, 3, "right")},
      {"source_count", tensor_dimension(left_view, 1, "left")},
  }};
  char workload_digest[72]{};
  const auto digest_status = mindclade_canonical_workload_digest_v1(
      "mindclade::outer_product_mean", 1u,
      workload_dimensions.data(), workload_dimensions.size(),
      node_dtype(left_view.dtype), "contiguous", "default",
      nullptr, 0u, workload_digest);
  if (digest_status != MINDCLADE_CAPABILITY_STATUS_SUCCESS_V1) {
    throw std::runtime_error("failed to canonicalize Mindclade native workload");
  }
  MindcladeCapabilityRequestV1 request{};
  request.operation = "mindclade::outer_product_mean";
  request.phase = MINDCLADE_CAPABILITY_PHASE_FORWARD_V1;
  request.workload_digest = workload_digest;
  request.device_index = left_view.device_index;
  request.dtype = node_dtype(left_view.dtype);
  request.layout = "contiguous";
  request.mode = "default";
  request.dimensions = workload_dimensions.data();
  request.dimension_count = static_cast<std::uint32_t>(workload_dimensions.size());
  request.attributes = nullptr; request.attribute_count = 0u;
  request.require_atomic_backward = 1u;
  const MindcladeQualifiedCapabilityRowV1* capability = nullptr;
  const auto selection_status = mindclade_select_qualified_capability_v1(
      mindclade_qualified_capability_rows_v1(),
      mindclade_qualified_capability_row_count_v1(), &request,
      &mindclade_cuda_device_architecture_v1, &capability);
  if (selection_status != MINDCLADE_CAPABILITY_STATUS_SUCCESS_V1 || capability == nullptr) {
    throw std::runtime_error("no exact qualified native capability for mindclade::outer_product_mean/forward");
  }
  void* current_stream = current_cuda_stream(left, "left");
  auto output = allocate_cuda_tensor(left, ([&]() { std::vector<std::int64_t> result; auto part_0 = std::vector<std::int64_t>(left_view.sizes.begin(), left_view.sizes.end() - 3); result.insert(result.end(), part_0.begin(), part_0.end()); auto part_1 = std::vector<std::int64_t>{tensor_dimension(left_view, -2, "left"), tensor_dimension(right_view, -2, "right"), tensor_dimension(left_view, -1, "left"), tensor_dimension(right_view, -1, "right")}; result.insert(result.end(), part_1.begin(), part_1.end()); return result; }()), left_view.dtype, InitializationMode::kUninitialized, 0.0);
  auto normalizer = allocate_cuda_tensor(left, ([&]() { std::vector<std::int64_t> result; auto part_0 = std::vector<std::int64_t>(left_view.sizes.begin(), left_view.sizes.end() - 3); result.insert(result.end(), part_0.begin(), part_0.end()); auto part_1 = std::vector<std::int64_t>{tensor_dimension(left_view, -2, "left"), tensor_dimension(right_view, -2, "right")}; result.insert(result.end(), part_1.begin(), part_1.end()); return result; }()), TensorDType::kFloat32, InitializationMode::kUninitialized, 0.0);
  auto node_0_mask_storage = make_node_tensor_value(mask, MINDCLADE_NODE_ACCESS_READ_V1, false, "mask");
  auto node_0_normalizer_storage = make_node_tensor_value(normalizer, MINDCLADE_NODE_ACCESS_WRITE_V1, false, "normalizer");
  const auto node_0_stream_value = make_node_stream_value(current_stream);
  const std::array<MindcladeNodeValueV1, 3> node_0_values{{node_0_mask_storage.value, node_0_normalizer_storage.value, node_0_stream_value}};
  auto node_1_left_storage = make_node_tensor_value(left, MINDCLADE_NODE_ACCESS_READ_V1, false, "left");
  auto node_1_right_storage = make_node_tensor_value(right, MINDCLADE_NODE_ACCESS_READ_V1, false, "right");
  auto node_1_mask_storage = make_node_tensor_value(mask, MINDCLADE_NODE_ACCESS_READ_V1, false, "mask");
  const auto node_1_epsilon_value = make_node_float64_value(epsilon, MINDCLADE_NODE_ACCESS_READ_V1);
  auto node_1_normalizer_storage = make_node_tensor_value(normalizer, MINDCLADE_NODE_ACCESS_READ_V1, false, "normalizer");
  auto node_1_output_storage = make_node_tensor_value(output, MINDCLADE_NODE_ACCESS_WRITE_V1, false, "output");
  const auto node_1_stream_value = make_node_stream_value(current_stream);
  const std::array<MindcladeNodeValueV1, 7> node_1_values{{node_1_left_storage.value, node_1_right_storage.value, node_1_mask_storage.value, node_1_epsilon_value, node_1_normalizer_storage.value, node_1_output_storage.value, node_1_stream_value}};
  const std::array<MindcladeNodeInvocationV1, 2> invocations{{
      MindcladeNodeInvocationV1{node_0_values.data(), static_cast<std::uint32_t>(node_0_values.size())},
      MindcladeNodeInvocationV1{node_1_values.data(), static_cast<std::uint32_t>(node_1_values.size())},
  }};
  std::int32_t adapter_status = MINDCLADE_NODE_STATUS_SUCCESS_V1;
  const auto execution_status = mindclade_execute_qualified_capability_v1(
      capability, invocations.data(), invocations.size(), &adapter_status);
  if (execution_status != MINDCLADE_CAPABILITY_STATUS_SUCCESS_V1) {
    throw std::runtime_error("Mindclade native program group execution failed with status " +
                             std::to_string(adapter_status));
  }
  return {output, normalizer};
}

extern "C" std::tuple<std::optional<torch::stable::Tensor>, std::optional<torch::stable::Tensor>, std::optional<torch::stable::Tensor>> mindclade_tilelang_outer_product_mean_bwd_launch(const torch::stable::Tensor& grad_output, const torch::stable::Tensor& left, const torch::stable::Tensor& right, const torch::stable::Tensor& mask, double epsilon, const torch::stable::Tensor& output, const torch::stable::Tensor& normalizer, bool need_left_grad, bool need_right_grad, bool need_mask_grad) {
  const auto grad_output_view = require_cuda_contiguous_tensor(grad_output, "grad_output");
  const auto left_view = require_cuda_contiguous_tensor(left, "left");
  const auto right_view = require_cuda_contiguous_tensor(right, "right");
  const auto mask_view = require_cuda_contiguous_tensor(mask, "mask");
  const auto output_view = require_cuda_contiguous_tensor(output, "output");
  const auto normalizer_view = require_cuda_contiguous_tensor(normalizer, "normalizer");
  require_same_device(grad_output_view, left_view, "left");
  require_same_device(grad_output_view, right_view, "right");
  require_same_device(grad_output_view, mask_view, "mask");
  require_same_device(grad_output_view, output_view, "output");
  require_same_device(grad_output_view, normalizer_view, "normalizer");
  const std::array<MindcladeCapabilityDimensionV1, 5> workload_dimensions{{
      {"batch_size", tensor_dimension(left_view, 0, "left")},
      {"left_channels", tensor_dimension(left_view, 3, "left")},
      {"node_count", tensor_dimension(left_view, 2, "left")},
      {"right_channels", tensor_dimension(right_view, 3, "right")},
      {"source_count", tensor_dimension(left_view, 1, "left")},
  }};
  char workload_digest[72]{};
  const auto digest_status = mindclade_canonical_workload_digest_v1(
      "mindclade::outer_product_mean", 1u,
      workload_dimensions.data(), workload_dimensions.size(),
      node_dtype(left_view.dtype), "contiguous", "default",
      nullptr, 0u, workload_digest);
  if (digest_status != MINDCLADE_CAPABILITY_STATUS_SUCCESS_V1) {
    throw std::runtime_error("failed to canonicalize Mindclade native workload");
  }
  MindcladeCapabilityRequestV1 request{};
  request.operation = "mindclade::outer_product_mean";
  request.phase = MINDCLADE_CAPABILITY_PHASE_BACKWARD_V1;
  request.workload_digest = workload_digest;
  request.device_index = grad_output_view.device_index;
  request.dtype = node_dtype(left_view.dtype);
  request.layout = "contiguous";
  request.mode = "default";
  request.dimensions = workload_dimensions.data();
  request.dimension_count = static_cast<std::uint32_t>(workload_dimensions.size());
  request.attributes = nullptr; request.attribute_count = 0u;
  request.require_atomic_backward = 1u;
  const MindcladeQualifiedCapabilityRowV1* capability = nullptr;
  const auto selection_status = mindclade_select_qualified_capability_v1(
      mindclade_qualified_capability_rows_v1(),
      mindclade_qualified_capability_row_count_v1(), &request,
      &mindclade_cuda_device_architecture_v1, &capability);
  if (selection_status != MINDCLADE_CAPABILITY_STATUS_SUCCESS_V1 || capability == nullptr) {
    throw std::runtime_error("no exact qualified native capability for mindclade::outer_product_mean/backward");
  }
  void* current_stream = current_cuda_stream(grad_output, "grad_output");
  std::optional<torch::stable::Tensor> grad_left;
  if (need_left_grad) {
    grad_left = allocate_cuda_tensor(grad_output, left_view.sizes, left_view.dtype, InitializationMode::kUninitialized, 0.0);
  }
  std::optional<torch::stable::Tensor> grad_right;
  if (need_right_grad) {
    grad_right = allocate_cuda_tensor(grad_output, right_view.sizes, right_view.dtype, InitializationMode::kUninitialized, 0.0);
  }
  std::optional<torch::stable::Tensor> grad_mask;
  if (need_mask_grad) {
    grad_mask = allocate_cuda_tensor(grad_output, mask_view.sizes, mask_view.dtype, InitializationMode::kUninitialized, 0.0);
  }
  auto node_0_grad_output_storage = make_node_tensor_value(grad_output, MINDCLADE_NODE_ACCESS_READ_V1, false, "grad_output");
  auto node_0_right_storage = make_node_tensor_value(right, MINDCLADE_NODE_ACCESS_READ_V1, false, "right");
  auto node_0_mask_storage = make_node_tensor_value(mask, MINDCLADE_NODE_ACCESS_READ_V1, false, "mask");
  const auto node_0_epsilon_value = make_node_float64_value(epsilon, MINDCLADE_NODE_ACCESS_READ_V1);
  auto node_0_normalizer_storage = make_node_tensor_value(normalizer, MINDCLADE_NODE_ACCESS_READ_V1, false, "normalizer");
  auto node_0_grad_left_storage = grad_left.has_value() ? make_node_tensor_value(*grad_left, MINDCLADE_NODE_ACCESS_WRITE_V1, true, "grad_left") : make_absent_node_tensor_value(MINDCLADE_NODE_ACCESS_WRITE_V1);
  const auto node_0_need_left_grad_value = make_node_bool_value(need_left_grad, MINDCLADE_NODE_ACCESS_READ_V1);
  const auto node_0_stream_value = make_node_stream_value(current_stream);
  const std::array<MindcladeNodeValueV1, 8> node_0_values{{node_0_grad_output_storage.value, node_0_right_storage.value, node_0_mask_storage.value, node_0_epsilon_value, node_0_normalizer_storage.value, node_0_grad_left_storage.value, node_0_need_left_grad_value, node_0_stream_value}};
  auto node_1_grad_output_storage = make_node_tensor_value(grad_output, MINDCLADE_NODE_ACCESS_READ_V1, false, "grad_output");
  auto node_1_left_storage = make_node_tensor_value(left, MINDCLADE_NODE_ACCESS_READ_V1, false, "left");
  auto node_1_right_storage = make_node_tensor_value(right, MINDCLADE_NODE_ACCESS_READ_V1, false, "right");
  auto node_1_mask_storage = make_node_tensor_value(mask, MINDCLADE_NODE_ACCESS_READ_V1, false, "mask");
  const auto node_1_epsilon_value = make_node_float64_value(epsilon, MINDCLADE_NODE_ACCESS_READ_V1);
  auto node_1_output_storage = make_node_tensor_value(output, MINDCLADE_NODE_ACCESS_READ_V1, false, "output");
  auto node_1_normalizer_storage = make_node_tensor_value(normalizer, MINDCLADE_NODE_ACCESS_READ_V1, false, "normalizer");
  auto node_1_grad_mask_storage = grad_mask.has_value() ? make_node_tensor_value(*grad_mask, MINDCLADE_NODE_ACCESS_WRITE_V1, true, "grad_mask") : make_absent_node_tensor_value(MINDCLADE_NODE_ACCESS_WRITE_V1);
  const auto node_1_need_mask_grad_value = make_node_bool_value(need_mask_grad, MINDCLADE_NODE_ACCESS_READ_V1);
  const auto node_1_stream_value = make_node_stream_value(current_stream);
  const std::array<MindcladeNodeValueV1, 10> node_1_values{{node_1_grad_output_storage.value, node_1_left_storage.value, node_1_right_storage.value, node_1_mask_storage.value, node_1_epsilon_value, node_1_output_storage.value, node_1_normalizer_storage.value, node_1_grad_mask_storage.value, node_1_need_mask_grad_value, node_1_stream_value}};
  auto node_2_grad_output_storage = make_node_tensor_value(grad_output, MINDCLADE_NODE_ACCESS_READ_V1, false, "grad_output");
  auto node_2_left_storage = make_node_tensor_value(left, MINDCLADE_NODE_ACCESS_READ_V1, false, "left");
  auto node_2_mask_storage = make_node_tensor_value(mask, MINDCLADE_NODE_ACCESS_READ_V1, false, "mask");
  const auto node_2_epsilon_value = make_node_float64_value(epsilon, MINDCLADE_NODE_ACCESS_READ_V1);
  auto node_2_normalizer_storage = make_node_tensor_value(normalizer, MINDCLADE_NODE_ACCESS_READ_V1, false, "normalizer");
  auto node_2_grad_right_storage = grad_right.has_value() ? make_node_tensor_value(*grad_right, MINDCLADE_NODE_ACCESS_WRITE_V1, true, "grad_right") : make_absent_node_tensor_value(MINDCLADE_NODE_ACCESS_WRITE_V1);
  const auto node_2_need_right_grad_value = make_node_bool_value(need_right_grad, MINDCLADE_NODE_ACCESS_READ_V1);
  const auto node_2_stream_value = make_node_stream_value(current_stream);
  const std::array<MindcladeNodeValueV1, 8> node_2_values{{node_2_grad_output_storage.value, node_2_left_storage.value, node_2_mask_storage.value, node_2_epsilon_value, node_2_normalizer_storage.value, node_2_grad_right_storage.value, node_2_need_right_grad_value, node_2_stream_value}};
  const std::array<MindcladeNodeInvocationV1, 3> invocations{{
      MindcladeNodeInvocationV1{node_0_values.data(), static_cast<std::uint32_t>(node_0_values.size())},
      MindcladeNodeInvocationV1{node_1_values.data(), static_cast<std::uint32_t>(node_1_values.size())},
      MindcladeNodeInvocationV1{node_2_values.data(), static_cast<std::uint32_t>(node_2_values.size())},
  }};
  std::int32_t adapter_status = MINDCLADE_NODE_STATUS_SUCCESS_V1;
  const auto execution_status = mindclade_execute_qualified_capability_v1(
      capability, invocations.data(), invocations.size(), &adapter_status);
  if (execution_status != MINDCLADE_CAPABILITY_STATUS_SUCCESS_V1) {
    throw std::runtime_error("Mindclade native program group execution failed with status " +
                             std::to_string(adapter_status));
  }
  return {grad_left, grad_right, grad_mask};
}

extern "C" std::tuple<torch::stable::Tensor, torch::stable::Tensor> mindclade_tilelang_pair_weighted_average_fwd_launch(const torch::stable::Tensor& value, const torch::stable::Tensor& weights, const torch::stable::Tensor& mask, double epsilon) {
  const auto value_view = require_cuda_contiguous_tensor(value, "value");
  const auto weights_view = require_cuda_contiguous_tensor(weights, "weights");
  const auto mask_view = require_cuda_contiguous_tensor(mask, "mask");
  require_same_device(value_view, weights_view, "weights");
  require_same_device(value_view, mask_view, "mask");
  const std::array<MindcladeCapabilityDimensionV1, 4> workload_dimensions{{
      {"batch_size", tensor_dimension(value_view, 0, "value")},
      {"channels", tensor_dimension(value_view, 3, "value")},
      {"heads", tensor_dimension(weights_view, 3, "weights")},
      {"node_count", tensor_dimension(value_view, 1, "value")},
  }};
  char workload_digest[72]{};
  const auto digest_status = mindclade_canonical_workload_digest_v1(
      "mindclade::pair_weighted_average", 1u,
      workload_dimensions.data(), workload_dimensions.size(),
      node_dtype(value_view.dtype), "contiguous", "default",
      nullptr, 0u, workload_digest);
  if (digest_status != MINDCLADE_CAPABILITY_STATUS_SUCCESS_V1) {
    throw std::runtime_error("failed to canonicalize Mindclade native workload");
  }
  MindcladeCapabilityRequestV1 request{};
  request.operation = "mindclade::pair_weighted_average";
  request.phase = MINDCLADE_CAPABILITY_PHASE_FORWARD_V1;
  request.workload_digest = workload_digest;
  request.device_index = value_view.device_index;
  request.dtype = node_dtype(value_view.dtype);
  request.layout = "contiguous";
  request.mode = "default";
  request.dimensions = workload_dimensions.data();
  request.dimension_count = static_cast<std::uint32_t>(workload_dimensions.size());
  request.attributes = nullptr; request.attribute_count = 0u;
  request.require_atomic_backward = 1u;
  const MindcladeQualifiedCapabilityRowV1* capability = nullptr;
  const auto selection_status = mindclade_select_qualified_capability_v1(
      mindclade_qualified_capability_rows_v1(),
      mindclade_qualified_capability_row_count_v1(), &request,
      &mindclade_cuda_device_architecture_v1, &capability);
  if (selection_status != MINDCLADE_CAPABILITY_STATUS_SUCCESS_V1 || capability == nullptr) {
    throw std::runtime_error("no exact qualified native capability for mindclade::pair_weighted_average/forward");
  }
  void* current_stream = current_cuda_stream(value, "value");
  auto output = allocate_cuda_tensor(value, ([&]() { std::vector<std::int64_t> result; auto part_0 = std::vector<std::int64_t>(value_view.sizes.begin(), value_view.sizes.end() - 2); result.insert(result.end(), part_0.begin(), part_0.end()); auto part_1 = std::vector<std::int64_t>{tensor_dimension(value_view, -2, "value"), tensor_dimension(weights_view, -1, "weights"), tensor_dimension(value_view, -1, "value")}; result.insert(result.end(), part_1.begin(), part_1.end()); return result; }()), value_view.dtype, InitializationMode::kUninitialized, 0.0);
  auto lse = allocate_cuda_tensor(value, ([&]() { std::vector<std::int64_t> result; auto part_0 = std::vector<std::int64_t>(value_view.sizes.begin(), value_view.sizes.end() - 2); result.insert(result.end(), part_0.begin(), part_0.end()); auto part_1 = std::vector<std::int64_t>{tensor_dimension(value_view, -2, "value"), tensor_dimension(weights_view, -1, "weights")}; result.insert(result.end(), part_1.begin(), part_1.end()); return result; }()), TensorDType::kFloat32, InitializationMode::kUninitialized, 0.0);
  auto node_0_value_storage = make_node_tensor_value(value, MINDCLADE_NODE_ACCESS_READ_V1, false, "value");
  auto node_0_weights_storage = make_node_tensor_value(weights, MINDCLADE_NODE_ACCESS_READ_V1, false, "weights");
  auto node_0_mask_storage = make_node_tensor_value(mask, MINDCLADE_NODE_ACCESS_READ_V1, false, "mask");
  const auto node_0_epsilon_value = make_node_float64_value(epsilon, MINDCLADE_NODE_ACCESS_READ_V1);
  auto node_0_output_storage = make_node_tensor_value(output, MINDCLADE_NODE_ACCESS_WRITE_V1, false, "output");
  auto node_0_lse_storage = make_node_tensor_value(lse, MINDCLADE_NODE_ACCESS_WRITE_V1, false, "lse");
  const auto node_0_stream_value = make_node_stream_value(current_stream);
  const std::array<MindcladeNodeValueV1, 7> node_0_values{{node_0_value_storage.value, node_0_weights_storage.value, node_0_mask_storage.value, node_0_epsilon_value, node_0_output_storage.value, node_0_lse_storage.value, node_0_stream_value}};
  const std::array<MindcladeNodeInvocationV1, 1> invocations{{
      MindcladeNodeInvocationV1{node_0_values.data(), static_cast<std::uint32_t>(node_0_values.size())},
  }};
  std::int32_t adapter_status = MINDCLADE_NODE_STATUS_SUCCESS_V1;
  const auto execution_status = mindclade_execute_qualified_capability_v1(
      capability, invocations.data(), invocations.size(), &adapter_status);
  if (execution_status != MINDCLADE_CAPABILITY_STATUS_SUCCESS_V1) {
    throw std::runtime_error("Mindclade native program group execution failed with status " +
                             std::to_string(adapter_status));
  }
  return {output, lse};
}

extern "C" std::tuple<std::optional<torch::stable::Tensor>, std::optional<torch::stable::Tensor>> mindclade_tilelang_pair_weighted_average_bwd_launch(const torch::stable::Tensor& grad_output, const torch::stable::Tensor& value, const torch::stable::Tensor& weights, const torch::stable::Tensor& mask, const torch::stable::Tensor& output, const torch::stable::Tensor& lse, bool need_value_grad, bool need_weights_grad) {
  const auto grad_output_view = require_cuda_contiguous_tensor(grad_output, "grad_output");
  const auto value_view = require_cuda_contiguous_tensor(value, "value");
  const auto weights_view = require_cuda_contiguous_tensor(weights, "weights");
  const auto mask_view = require_cuda_contiguous_tensor(mask, "mask");
  const auto output_view = require_cuda_contiguous_tensor(output, "output");
  const auto lse_view = require_cuda_contiguous_tensor(lse, "lse");
  require_same_device(grad_output_view, value_view, "value");
  require_same_device(grad_output_view, weights_view, "weights");
  require_same_device(grad_output_view, mask_view, "mask");
  require_same_device(grad_output_view, output_view, "output");
  require_same_device(grad_output_view, lse_view, "lse");
  const std::array<MindcladeCapabilityDimensionV1, 4> workload_dimensions{{
      {"batch_size", tensor_dimension(value_view, 0, "value")},
      {"channels", tensor_dimension(value_view, 3, "value")},
      {"heads", tensor_dimension(weights_view, 3, "weights")},
      {"node_count", tensor_dimension(value_view, 1, "value")},
  }};
  char workload_digest[72]{};
  const auto digest_status = mindclade_canonical_workload_digest_v1(
      "mindclade::pair_weighted_average", 1u,
      workload_dimensions.data(), workload_dimensions.size(),
      node_dtype(value_view.dtype), "contiguous", "default",
      nullptr, 0u, workload_digest);
  if (digest_status != MINDCLADE_CAPABILITY_STATUS_SUCCESS_V1) {
    throw std::runtime_error("failed to canonicalize Mindclade native workload");
  }
  MindcladeCapabilityRequestV1 request{};
  request.operation = "mindclade::pair_weighted_average";
  request.phase = MINDCLADE_CAPABILITY_PHASE_BACKWARD_V1;
  request.workload_digest = workload_digest;
  request.device_index = grad_output_view.device_index;
  request.dtype = node_dtype(value_view.dtype);
  request.layout = "contiguous";
  request.mode = "default";
  request.dimensions = workload_dimensions.data();
  request.dimension_count = static_cast<std::uint32_t>(workload_dimensions.size());
  request.attributes = nullptr; request.attribute_count = 0u;
  request.require_atomic_backward = 1u;
  const MindcladeQualifiedCapabilityRowV1* capability = nullptr;
  const auto selection_status = mindclade_select_qualified_capability_v1(
      mindclade_qualified_capability_rows_v1(),
      mindclade_qualified_capability_row_count_v1(), &request,
      &mindclade_cuda_device_architecture_v1, &capability);
  if (selection_status != MINDCLADE_CAPABILITY_STATUS_SUCCESS_V1 || capability == nullptr) {
    throw std::runtime_error("no exact qualified native capability for mindclade::pair_weighted_average/backward");
  }
  void* current_stream = current_cuda_stream(grad_output, "grad_output");
  std::optional<torch::stable::Tensor> grad_value;
  if (need_value_grad) {
    grad_value = allocate_cuda_tensor(grad_output, value_view.sizes, value_view.dtype, InitializationMode::kUninitialized, 0.0);
  }
  std::optional<torch::stable::Tensor> grad_weights;
  if (need_weights_grad) {
    grad_weights = allocate_cuda_tensor(grad_output, weights_view.sizes, weights_view.dtype, InitializationMode::kUninitialized, 0.0);
  }
  auto workspace_delta = allocate_workspace(grad_output, std::vector<std::int64_t>{tensor_dimension(value_view, 0, "value"), tensor_dimension(weights_view, 1, "weights"), tensor_dimension(weights_view, 3, "weights")}, TensorDType::kFloat32, false);
  auto node_0_grad_output_storage = make_node_tensor_value(grad_output, MINDCLADE_NODE_ACCESS_READ_V1, false, "grad_output");
  auto node_0_output_storage = make_node_tensor_value(output, MINDCLADE_NODE_ACCESS_READ_V1, false, "output");
  auto node_0_delta_storage = make_node_tensor_value(workspace_delta, MINDCLADE_NODE_ACCESS_WRITE_V1, false, "delta");
  const auto node_0_stream_value = make_node_stream_value(current_stream);
  const std::array<MindcladeNodeValueV1, 4> node_0_values{{node_0_grad_output_storage.value, node_0_output_storage.value, node_0_delta_storage.value, node_0_stream_value}};
  auto node_1_grad_output_storage = make_node_tensor_value(grad_output, MINDCLADE_NODE_ACCESS_READ_V1, false, "grad_output");
  auto node_1_weights_storage = make_node_tensor_value(weights, MINDCLADE_NODE_ACCESS_READ_V1, false, "weights");
  auto node_1_mask_storage = make_node_tensor_value(mask, MINDCLADE_NODE_ACCESS_READ_V1, false, "mask");
  auto node_1_lse_storage = make_node_tensor_value(lse, MINDCLADE_NODE_ACCESS_READ_V1, false, "lse");
  auto node_1_grad_value_storage = grad_value.has_value() ? make_node_tensor_value(*grad_value, MINDCLADE_NODE_ACCESS_WRITE_V1, true, "grad_value") : make_absent_node_tensor_value(MINDCLADE_NODE_ACCESS_WRITE_V1);
  const auto node_1_need_value_grad_value = make_node_bool_value(need_value_grad, MINDCLADE_NODE_ACCESS_READ_V1);
  const auto node_1_stream_value = make_node_stream_value(current_stream);
  const std::array<MindcladeNodeValueV1, 7> node_1_values{{node_1_grad_output_storage.value, node_1_weights_storage.value, node_1_mask_storage.value, node_1_lse_storage.value, node_1_grad_value_storage.value, node_1_need_value_grad_value, node_1_stream_value}};
  auto node_2_grad_output_storage = make_node_tensor_value(grad_output, MINDCLADE_NODE_ACCESS_READ_V1, false, "grad_output");
  auto node_2_value_storage = make_node_tensor_value(value, MINDCLADE_NODE_ACCESS_READ_V1, false, "value");
  auto node_2_weights_storage = make_node_tensor_value(weights, MINDCLADE_NODE_ACCESS_READ_V1, false, "weights");
  auto node_2_mask_storage = make_node_tensor_value(mask, MINDCLADE_NODE_ACCESS_READ_V1, false, "mask");
  auto node_2_lse_storage = make_node_tensor_value(lse, MINDCLADE_NODE_ACCESS_READ_V1, false, "lse");
  auto node_2_delta_storage = make_node_tensor_value(workspace_delta, MINDCLADE_NODE_ACCESS_READ_V1, false, "delta");
  auto node_2_grad_weights_storage = grad_weights.has_value() ? make_node_tensor_value(*grad_weights, MINDCLADE_NODE_ACCESS_WRITE_V1, true, "grad_weights") : make_absent_node_tensor_value(MINDCLADE_NODE_ACCESS_WRITE_V1);
  const auto node_2_need_weights_grad_value = make_node_bool_value(need_weights_grad, MINDCLADE_NODE_ACCESS_READ_V1);
  const auto node_2_stream_value = make_node_stream_value(current_stream);
  const std::array<MindcladeNodeValueV1, 9> node_2_values{{node_2_grad_output_storage.value, node_2_value_storage.value, node_2_weights_storage.value, node_2_mask_storage.value, node_2_lse_storage.value, node_2_delta_storage.value, node_2_grad_weights_storage.value, node_2_need_weights_grad_value, node_2_stream_value}};
  const std::array<MindcladeNodeInvocationV1, 3> invocations{{
      MindcladeNodeInvocationV1{node_0_values.data(), static_cast<std::uint32_t>(node_0_values.size())},
      MindcladeNodeInvocationV1{node_1_values.data(), static_cast<std::uint32_t>(node_1_values.size())},
      MindcladeNodeInvocationV1{node_2_values.data(), static_cast<std::uint32_t>(node_2_values.size())},
  }};
  std::int32_t adapter_status = MINDCLADE_NODE_STATUS_SUCCESS_V1;
  const auto execution_status = mindclade_execute_qualified_capability_v1(
      capability, invocations.data(), invocations.size(), &adapter_status);
  if (execution_status != MINDCLADE_CAPABILITY_STATUS_SUCCESS_V1) {
    throw std::runtime_error("Mindclade native program group execution failed with status " +
                             std::to_string(adapter_status));
  }
  return {grad_value, grad_weights};
}

extern "C" std::tuple<torch::stable::Tensor, torch::stable::Tensor> mindclade_tilelang_transition_fwd_launch(const torch::stable::Tensor& gate, const torch::stable::Tensor& value, const torch::stable::Tensor& output_weight, const torch::stable::Tensor& output_bias, const torch::stable::Tensor& mask) {
  const auto gate_view = require_cuda_contiguous_tensor(gate, "gate");
  const auto value_view = require_cuda_contiguous_tensor(value, "value");
  const auto output_weight_view = require_cuda_contiguous_tensor(output_weight, "output_weight");
  const auto output_bias_view = require_cuda_contiguous_tensor(output_bias, "output_bias");
  const auto mask_view = require_cuda_contiguous_tensor(mask, "mask");
  require_same_device(gate_view, value_view, "value");
  require_same_device(gate_view, output_weight_view, "output_weight");
  require_same_device(gate_view, output_bias_view, "output_bias");
  require_same_device(gate_view, mask_view, "mask");
  const std::array<MindcladeCapabilityDimensionV1, 4> workload_dimensions{{
      {"batch_size", tensor_dimension(gate_view, 0, "gate")},
      {"hidden_channels", tensor_dimension(gate_view, 2, "gate")},
      {"output_channels", tensor_dimension(output_weight_view, 1, "output_weight")},
      {"rows", tensor_dimension(gate_view, 1, "gate")},
  }};
  char workload_digest[72]{};
  const auto digest_status = mindclade_canonical_workload_digest_v1(
      "mindclade::transition", 1u,
      workload_dimensions.data(), workload_dimensions.size(),
      node_dtype(gate_view.dtype), "contiguous", "default",
      nullptr, 0u, workload_digest);
  if (digest_status != MINDCLADE_CAPABILITY_STATUS_SUCCESS_V1) {
    throw std::runtime_error("failed to canonicalize Mindclade native workload");
  }
  MindcladeCapabilityRequestV1 request{};
  request.operation = "mindclade::transition";
  request.phase = MINDCLADE_CAPABILITY_PHASE_FORWARD_V1;
  request.workload_digest = workload_digest;
  request.device_index = gate_view.device_index;
  request.dtype = node_dtype(gate_view.dtype);
  request.layout = "contiguous";
  request.mode = "default";
  request.dimensions = workload_dimensions.data();
  request.dimension_count = static_cast<std::uint32_t>(workload_dimensions.size());
  request.attributes = nullptr; request.attribute_count = 0u;
  request.require_atomic_backward = 1u;
  const MindcladeQualifiedCapabilityRowV1* capability = nullptr;
  const auto selection_status = mindclade_select_qualified_capability_v1(
      mindclade_qualified_capability_rows_v1(),
      mindclade_qualified_capability_row_count_v1(), &request,
      &mindclade_cuda_device_architecture_v1, &capability);
  if (selection_status != MINDCLADE_CAPABILITY_STATUS_SUCCESS_V1 || capability == nullptr) {
    throw std::runtime_error("no exact qualified native capability for mindclade::transition/forward");
  }
  void* current_stream = current_cuda_stream(gate, "gate");
  auto output = allocate_cuda_tensor(gate, ([&]() { std::vector<std::int64_t> result; auto part_0 = std::vector<std::int64_t>(gate_view.sizes.begin(), gate_view.sizes.end() - 1); result.insert(result.end(), part_0.begin(), part_0.end()); auto part_1 = std::vector<std::int64_t>{tensor_dimension(output_weight_view, 1, "output_weight")}; result.insert(result.end(), part_1.begin(), part_1.end()); return result; }()), gate_view.dtype, InitializationMode::kUninitialized, 0.0);
  auto pre_mask_output = allocate_cuda_tensor(gate, ([&]() { std::vector<std::int64_t> result; auto part_0 = std::vector<std::int64_t>(gate_view.sizes.begin(), gate_view.sizes.end() - 1); result.insert(result.end(), part_0.begin(), part_0.end()); auto part_1 = std::vector<std::int64_t>{tensor_dimension(output_weight_view, 1, "output_weight")}; result.insert(result.end(), part_1.begin(), part_1.end()); return result; }()), gate_view.dtype, InitializationMode::kUninitialized, 0.0);
  auto node_0_gate_storage = make_node_tensor_value(gate, MINDCLADE_NODE_ACCESS_READ_V1, false, "gate");
  auto node_0_value_storage = make_node_tensor_value(value, MINDCLADE_NODE_ACCESS_READ_V1, false, "value");
  auto node_0_output_weight_storage = make_node_tensor_value(output_weight, MINDCLADE_NODE_ACCESS_READ_V1, false, "output_weight");
  auto node_0_output_bias_storage = make_node_tensor_value(output_bias, MINDCLADE_NODE_ACCESS_READ_V1, false, "output_bias");
  auto node_0_mask_storage = make_node_tensor_value(mask, MINDCLADE_NODE_ACCESS_READ_V1, false, "mask");
  auto node_0_output_storage = make_node_tensor_value(output, MINDCLADE_NODE_ACCESS_WRITE_V1, false, "output");
  auto node_0_pre_mask_output_storage = make_node_tensor_value(pre_mask_output, MINDCLADE_NODE_ACCESS_WRITE_V1, false, "pre_mask_output");
  const auto node_0_stream_value = make_node_stream_value(current_stream);
  const std::array<MindcladeNodeValueV1, 8> node_0_values{{node_0_gate_storage.value, node_0_value_storage.value, node_0_output_weight_storage.value, node_0_output_bias_storage.value, node_0_mask_storage.value, node_0_output_storage.value, node_0_pre_mask_output_storage.value, node_0_stream_value}};
  const std::array<MindcladeNodeInvocationV1, 1> invocations{{
      MindcladeNodeInvocationV1{node_0_values.data(), static_cast<std::uint32_t>(node_0_values.size())},
  }};
  std::int32_t adapter_status = MINDCLADE_NODE_STATUS_SUCCESS_V1;
  const auto execution_status = mindclade_execute_qualified_capability_v1(
      capability, invocations.data(), invocations.size(), &adapter_status);
  if (execution_status != MINDCLADE_CAPABILITY_STATUS_SUCCESS_V1) {
    throw std::runtime_error("Mindclade native program group execution failed with status " +
                             std::to_string(adapter_status));
  }
  return {output, pre_mask_output};
}

extern "C" std::tuple<std::optional<torch::stable::Tensor>, std::optional<torch::stable::Tensor>, std::optional<torch::stable::Tensor>, std::optional<torch::stable::Tensor>, std::optional<torch::stable::Tensor>> mindclade_tilelang_transition_bwd_launch(const torch::stable::Tensor& grad_output, const torch::stable::Tensor& gate, const torch::stable::Tensor& value, const torch::stable::Tensor& output_weight, const torch::stable::Tensor& mask, const torch::stable::Tensor& pre_mask_output, bool need_gate_grad, bool need_value_grad, bool need_weight_grad, bool need_bias_grad, bool need_mask_grad) {
  const auto grad_output_view = require_cuda_contiguous_tensor(grad_output, "grad_output");
  const auto gate_view = require_cuda_contiguous_tensor(gate, "gate");
  const auto value_view = require_cuda_contiguous_tensor(value, "value");
  const auto output_weight_view = require_cuda_contiguous_tensor(output_weight, "output_weight");
  const auto mask_view = require_cuda_contiguous_tensor(mask, "mask");
  const auto pre_mask_output_view = require_cuda_contiguous_tensor(pre_mask_output, "pre_mask_output");
  require_same_device(grad_output_view, gate_view, "gate");
  require_same_device(grad_output_view, value_view, "value");
  require_same_device(grad_output_view, output_weight_view, "output_weight");
  require_same_device(grad_output_view, mask_view, "mask");
  require_same_device(grad_output_view, pre_mask_output_view, "pre_mask_output");
  const std::array<MindcladeCapabilityDimensionV1, 4> workload_dimensions{{
      {"batch_size", tensor_dimension(gate_view, 0, "gate")},
      {"hidden_channels", tensor_dimension(gate_view, 2, "gate")},
      {"output_channels", tensor_dimension(output_weight_view, 1, "output_weight")},
      {"rows", tensor_dimension(gate_view, 1, "gate")},
  }};
  char workload_digest[72]{};
  const auto digest_status = mindclade_canonical_workload_digest_v1(
      "mindclade::transition", 1u,
      workload_dimensions.data(), workload_dimensions.size(),
      node_dtype(gate_view.dtype), "contiguous", "default",
      nullptr, 0u, workload_digest);
  if (digest_status != MINDCLADE_CAPABILITY_STATUS_SUCCESS_V1) {
    throw std::runtime_error("failed to canonicalize Mindclade native workload");
  }
  MindcladeCapabilityRequestV1 request{};
  request.operation = "mindclade::transition";
  request.phase = MINDCLADE_CAPABILITY_PHASE_BACKWARD_V1;
  request.workload_digest = workload_digest;
  request.device_index = grad_output_view.device_index;
  request.dtype = node_dtype(gate_view.dtype);
  request.layout = "contiguous";
  request.mode = "default";
  request.dimensions = workload_dimensions.data();
  request.dimension_count = static_cast<std::uint32_t>(workload_dimensions.size());
  request.attributes = nullptr; request.attribute_count = 0u;
  request.require_atomic_backward = 1u;
  const MindcladeQualifiedCapabilityRowV1* capability = nullptr;
  const auto selection_status = mindclade_select_qualified_capability_v1(
      mindclade_qualified_capability_rows_v1(),
      mindclade_qualified_capability_row_count_v1(), &request,
      &mindclade_cuda_device_architecture_v1, &capability);
  if (selection_status != MINDCLADE_CAPABILITY_STATUS_SUCCESS_V1 || capability == nullptr) {
    throw std::runtime_error("no exact qualified native capability for mindclade::transition/backward");
  }
  void* current_stream = current_cuda_stream(grad_output, "grad_output");
  std::optional<torch::stable::Tensor> grad_gate;
  if (need_gate_grad) {
    grad_gate = allocate_cuda_tensor(grad_output, gate_view.sizes, gate_view.dtype, InitializationMode::kUninitialized, 0.0);
  }
  std::optional<torch::stable::Tensor> grad_value;
  if (need_value_grad) {
    grad_value = allocate_cuda_tensor(grad_output, value_view.sizes, value_view.dtype, InitializationMode::kUninitialized, 0.0);
  }
  std::optional<torch::stable::Tensor> grad_weight;
  if (need_weight_grad) {
    grad_weight = allocate_cuda_tensor(grad_output, output_weight_view.sizes, output_weight_view.dtype, InitializationMode::kUninitialized, 0.0);
  }
  std::optional<torch::stable::Tensor> grad_bias;
  if (need_bias_grad) {
    grad_bias = allocate_cuda_tensor(grad_output, std::vector<std::int64_t>{tensor_dimension(output_weight_view, 1, "output_weight")}, output_weight_view.dtype, InitializationMode::kUninitialized, 0.0);
  }
  std::optional<torch::stable::Tensor> grad_mask;
  if (need_mask_grad) {
    grad_mask = allocate_cuda_tensor(grad_output, mask_view.sizes, mask_view.dtype, InitializationMode::kUninitialized, 0.0);
  }
  auto node_0_grad_output_storage = make_node_tensor_value(grad_output, MINDCLADE_NODE_ACCESS_READ_V1, false, "grad_output");
  auto node_0_mask_storage = make_node_tensor_value(mask, MINDCLADE_NODE_ACCESS_READ_V1, false, "mask");
  auto node_0_grad_bias_storage = grad_bias.has_value() ? make_node_tensor_value(*grad_bias, MINDCLADE_NODE_ACCESS_WRITE_V1, true, "grad_bias") : make_absent_node_tensor_value(MINDCLADE_NODE_ACCESS_WRITE_V1);
  const auto node_0_need_output_bias_grad_value = make_node_bool_value(need_bias_grad, MINDCLADE_NODE_ACCESS_READ_V1);
  const auto node_0_stream_value = make_node_stream_value(current_stream);
  const std::array<MindcladeNodeValueV1, 5> node_0_values{{node_0_grad_output_storage.value, node_0_mask_storage.value, node_0_grad_bias_storage.value, node_0_need_output_bias_grad_value, node_0_stream_value}};
  auto node_1_grad_output_storage = make_node_tensor_value(grad_output, MINDCLADE_NODE_ACCESS_READ_V1, false, "grad_output");
  auto node_1_gate_storage = make_node_tensor_value(gate, MINDCLADE_NODE_ACCESS_READ_V1, false, "gate");
  auto node_1_value_storage = make_node_tensor_value(value, MINDCLADE_NODE_ACCESS_READ_V1, false, "value");
  auto node_1_output_weight_storage = make_node_tensor_value(output_weight, MINDCLADE_NODE_ACCESS_READ_V1, false, "output_weight");
  auto node_1_mask_storage = make_node_tensor_value(mask, MINDCLADE_NODE_ACCESS_READ_V1, false, "mask");
  auto node_1_grad_gate_storage = grad_gate.has_value() ? make_node_tensor_value(*grad_gate, MINDCLADE_NODE_ACCESS_WRITE_V1, true, "grad_gate") : make_absent_node_tensor_value(MINDCLADE_NODE_ACCESS_WRITE_V1);
  const auto node_1_need_gate_grad_value = make_node_bool_value(need_gate_grad, MINDCLADE_NODE_ACCESS_READ_V1);
  const auto node_1_stream_value = make_node_stream_value(current_stream);
  const std::array<MindcladeNodeValueV1, 8> node_1_values{{node_1_grad_output_storage.value, node_1_gate_storage.value, node_1_value_storage.value, node_1_output_weight_storage.value, node_1_mask_storage.value, node_1_grad_gate_storage.value, node_1_need_gate_grad_value, node_1_stream_value}};
  auto node_2_grad_output_storage = make_node_tensor_value(grad_output, MINDCLADE_NODE_ACCESS_READ_V1, false, "grad_output");
  auto node_2_pre_mask_output_storage = make_node_tensor_value(pre_mask_output, MINDCLADE_NODE_ACCESS_READ_V1, false, "pre_mask_output");
  auto node_2_grad_mask_storage = grad_mask.has_value() ? make_node_tensor_value(*grad_mask, MINDCLADE_NODE_ACCESS_WRITE_V1, true, "grad_mask") : make_absent_node_tensor_value(MINDCLADE_NODE_ACCESS_WRITE_V1);
  const auto node_2_need_mask_grad_value = make_node_bool_value(need_mask_grad, MINDCLADE_NODE_ACCESS_READ_V1);
  const auto node_2_stream_value = make_node_stream_value(current_stream);
  const std::array<MindcladeNodeValueV1, 5> node_2_values{{node_2_grad_output_storage.value, node_2_pre_mask_output_storage.value, node_2_grad_mask_storage.value, node_2_need_mask_grad_value, node_2_stream_value}};
  auto node_3_grad_output_storage = make_node_tensor_value(grad_output, MINDCLADE_NODE_ACCESS_READ_V1, false, "grad_output");
  auto node_3_gate_storage = make_node_tensor_value(gate, MINDCLADE_NODE_ACCESS_READ_V1, false, "gate");
  auto node_3_output_weight_storage = make_node_tensor_value(output_weight, MINDCLADE_NODE_ACCESS_READ_V1, false, "output_weight");
  auto node_3_mask_storage = make_node_tensor_value(mask, MINDCLADE_NODE_ACCESS_READ_V1, false, "mask");
  auto node_3_grad_value_storage = grad_value.has_value() ? make_node_tensor_value(*grad_value, MINDCLADE_NODE_ACCESS_WRITE_V1, true, "grad_value") : make_absent_node_tensor_value(MINDCLADE_NODE_ACCESS_WRITE_V1);
  const auto node_3_need_value_grad_value = make_node_bool_value(need_value_grad, MINDCLADE_NODE_ACCESS_READ_V1);
  const auto node_3_stream_value = make_node_stream_value(current_stream);
  const std::array<MindcladeNodeValueV1, 7> node_3_values{{node_3_grad_output_storage.value, node_3_gate_storage.value, node_3_output_weight_storage.value, node_3_mask_storage.value, node_3_grad_value_storage.value, node_3_need_value_grad_value, node_3_stream_value}};
  auto node_4_grad_output_storage = make_node_tensor_value(grad_output, MINDCLADE_NODE_ACCESS_READ_V1, false, "grad_output");
  auto node_4_gate_storage = make_node_tensor_value(gate, MINDCLADE_NODE_ACCESS_READ_V1, false, "gate");
  auto node_4_value_storage = make_node_tensor_value(value, MINDCLADE_NODE_ACCESS_READ_V1, false, "value");
  auto node_4_mask_storage = make_node_tensor_value(mask, MINDCLADE_NODE_ACCESS_READ_V1, false, "mask");
  auto node_4_grad_weight_storage = grad_weight.has_value() ? make_node_tensor_value(*grad_weight, MINDCLADE_NODE_ACCESS_WRITE_V1, true, "grad_weight") : make_absent_node_tensor_value(MINDCLADE_NODE_ACCESS_WRITE_V1);
  const auto node_4_need_output_weight_grad_value = make_node_bool_value(need_weight_grad, MINDCLADE_NODE_ACCESS_READ_V1);
  const auto node_4_stream_value = make_node_stream_value(current_stream);
  const std::array<MindcladeNodeValueV1, 7> node_4_values{{node_4_grad_output_storage.value, node_4_gate_storage.value, node_4_value_storage.value, node_4_mask_storage.value, node_4_grad_weight_storage.value, node_4_need_output_weight_grad_value, node_4_stream_value}};
  const std::array<MindcladeNodeInvocationV1, 5> invocations{{
      MindcladeNodeInvocationV1{node_0_values.data(), static_cast<std::uint32_t>(node_0_values.size())},
      MindcladeNodeInvocationV1{node_1_values.data(), static_cast<std::uint32_t>(node_1_values.size())},
      MindcladeNodeInvocationV1{node_2_values.data(), static_cast<std::uint32_t>(node_2_values.size())},
      MindcladeNodeInvocationV1{node_3_values.data(), static_cast<std::uint32_t>(node_3_values.size())},
      MindcladeNodeInvocationV1{node_4_values.data(), static_cast<std::uint32_t>(node_4_values.size())},
  }};
  std::int32_t adapter_status = MINDCLADE_NODE_STATUS_SUCCESS_V1;
  const auto execution_status = mindclade_execute_qualified_capability_v1(
      capability, invocations.data(), invocations.size(), &adapter_status);
  if (execution_status != MINDCLADE_CAPABILITY_STATUS_SUCCESS_V1) {
    throw std::runtime_error("Mindclade native program group execution failed with status " +
                             std::to_string(adapter_status));
  }
  return {grad_gate, grad_value, grad_weight, grad_bias, grad_mask};
}

extern "C" std::tuple<torch::stable::Tensor, torch::stable::Tensor> mindclade_tilelang_triangle_attention_fwd_launch(const torch::stable::Tensor& q, const torch::stable::Tensor& k, const torch::stable::Tensor& v, const torch::stable::Tensor& bias, const torch::stable::Tensor& mask, double scale) {
  const auto q_view = require_cuda_contiguous_tensor(q, "q");
  const auto k_view = require_cuda_contiguous_tensor(k, "k");
  const auto v_view = require_cuda_contiguous_tensor(v, "v");
  const auto bias_view = require_cuda_contiguous_tensor(bias, "bias");
  const auto mask_view = require_cuda_contiguous_tensor(mask, "mask");
  require_same_device(q_view, k_view, "k");
  require_same_device(q_view, v_view, "v");
  require_same_device(q_view, bias_view, "bias");
  require_same_device(q_view, mask_view, "mask");
  const std::array<MindcladeCapabilityDimensionV1, 4> workload_dimensions{{
      {"batch", tensor_dimension(q_view, 0, "q")},
      {"head_dim", tensor_dimension(q_view, 3, "q")},
      {"heads", tensor_dimension(q_view, 2, "q")},
      {"n", tensor_dimension(q_view, 1, "q")},
  }};
  char workload_digest[72]{};
  const auto digest_status = mindclade_canonical_workload_digest_v1(
      "mindclade::triangle_attention", 1u,
      workload_dimensions.data(), workload_dimensions.size(),
      node_dtype(q_view.dtype), "contiguous", "default",
      nullptr, 0u, workload_digest);
  if (digest_status != MINDCLADE_CAPABILITY_STATUS_SUCCESS_V1) {
    throw std::runtime_error("failed to canonicalize Mindclade native workload");
  }
  MindcladeCapabilityRequestV1 request{};
  request.operation = "mindclade::triangle_attention";
  request.phase = MINDCLADE_CAPABILITY_PHASE_FORWARD_V1;
  request.workload_digest = workload_digest;
  request.device_index = q_view.device_index;
  request.dtype = node_dtype(q_view.dtype);
  request.layout = "contiguous";
  request.mode = "default";
  request.dimensions = workload_dimensions.data();
  request.dimension_count = static_cast<std::uint32_t>(workload_dimensions.size());
  request.attributes = nullptr; request.attribute_count = 0u;
  request.require_atomic_backward = 1u;
  const MindcladeQualifiedCapabilityRowV1* capability = nullptr;
  const auto selection_status = mindclade_select_qualified_capability_v1(
      mindclade_qualified_capability_rows_v1(),
      mindclade_qualified_capability_row_count_v1(), &request,
      &mindclade_cuda_device_architecture_v1, &capability);
  if (selection_status != MINDCLADE_CAPABILITY_STATUS_SUCCESS_V1 || capability == nullptr) {
    throw std::runtime_error("no exact qualified native capability for mindclade::triangle_attention/forward");
  }
  void* current_stream = current_cuda_stream(q, "q");
  auto output = allocate_cuda_tensor(q, q_view.sizes, q_view.dtype, InitializationMode::kUninitialized, 0.0);
  auto lse = allocate_cuda_tensor(q, std::vector<std::int64_t>{tensor_dimension(q_view, 0, "q"), tensor_dimension(q_view, 1, "q"), tensor_dimension(q_view, 3, "q"), (((tensor_dimension(q_view, 2, "q") + INT64_C(32) - 1) / INT64_C(32)) * INT64_C(32))}, TensorDType::kFloat32, InitializationMode::kNegativeInfinity, 0.0);
  auto node_0_q_storage = make_node_tensor_value(q, MINDCLADE_NODE_ACCESS_READ_V1, false, "q");
  auto node_0_k_storage = make_node_tensor_value(k, MINDCLADE_NODE_ACCESS_READ_V1, false, "k");
  auto node_0_v_storage = make_node_tensor_value(v, MINDCLADE_NODE_ACCESS_READ_V1, false, "v");
  auto node_0_bias_storage = make_node_tensor_value(bias, MINDCLADE_NODE_ACCESS_READ_V1, false, "bias");
  auto node_0_mask_storage = make_node_tensor_value(mask, MINDCLADE_NODE_ACCESS_READ_V1, false, "mask");
  const auto node_0_scale_value = make_node_float64_value(scale, MINDCLADE_NODE_ACCESS_READ_V1);
  auto node_0_output_storage = make_node_tensor_value(output, MINDCLADE_NODE_ACCESS_WRITE_V1, false, "output");
  auto node_0_lse_storage = make_node_tensor_value(lse, MINDCLADE_NODE_ACCESS_WRITE_V1, false, "lse");
  const auto node_0_stream_value = make_node_stream_value(current_stream);
  const std::array<MindcladeNodeValueV1, 9> node_0_values{{node_0_q_storage.value, node_0_k_storage.value, node_0_v_storage.value, node_0_bias_storage.value, node_0_mask_storage.value, node_0_scale_value, node_0_output_storage.value, node_0_lse_storage.value, node_0_stream_value}};
  const std::array<MindcladeNodeInvocationV1, 1> invocations{{
      MindcladeNodeInvocationV1{node_0_values.data(), static_cast<std::uint32_t>(node_0_values.size())},
  }};
  std::int32_t adapter_status = MINDCLADE_NODE_STATUS_SUCCESS_V1;
  const auto execution_status = mindclade_execute_qualified_capability_v1(
      capability, invocations.data(), invocations.size(), &adapter_status);
  if (execution_status != MINDCLADE_CAPABILITY_STATUS_SUCCESS_V1) {
    throw std::runtime_error("Mindclade native program group execution failed with status " +
                             std::to_string(adapter_status));
  }
  return {output, lse};
}

extern "C" std::tuple<std::optional<torch::stable::Tensor>, std::optional<torch::stable::Tensor>, std::optional<torch::stable::Tensor>, std::optional<torch::stable::Tensor>> mindclade_tilelang_triangle_attention_bwd_launch(const torch::stable::Tensor& grad_output, const torch::stable::Tensor& q, const torch::stable::Tensor& k, const torch::stable::Tensor& v, const torch::stable::Tensor& bias, const torch::stable::Tensor& mask, double scale, const torch::stable::Tensor& output, const torch::stable::Tensor& lse, bool need_q_grad, bool need_k_grad, bool need_v_grad, bool need_bias_grad) {
  const auto grad_output_view = require_cuda_contiguous_tensor(grad_output, "grad_output");
  const auto q_view = require_cuda_contiguous_tensor(q, "q");
  const auto k_view = require_cuda_contiguous_tensor(k, "k");
  const auto v_view = require_cuda_contiguous_tensor(v, "v");
  const auto bias_view = require_cuda_contiguous_tensor(bias, "bias");
  const auto mask_view = require_cuda_contiguous_tensor(mask, "mask");
  const auto output_view = require_cuda_contiguous_tensor(output, "output");
  const auto lse_view = require_cuda_contiguous_tensor(lse, "lse");
  require_same_device(grad_output_view, q_view, "q");
  require_same_device(grad_output_view, k_view, "k");
  require_same_device(grad_output_view, v_view, "v");
  require_same_device(grad_output_view, bias_view, "bias");
  require_same_device(grad_output_view, mask_view, "mask");
  require_same_device(grad_output_view, output_view, "output");
  require_same_device(grad_output_view, lse_view, "lse");
  const std::array<MindcladeCapabilityDimensionV1, 4> workload_dimensions{{
      {"batch", tensor_dimension(q_view, 0, "q")},
      {"head_dim", tensor_dimension(q_view, 3, "q")},
      {"heads", tensor_dimension(q_view, 2, "q")},
      {"n", tensor_dimension(q_view, 1, "q")},
  }};
  char workload_digest[72]{};
  const auto digest_status = mindclade_canonical_workload_digest_v1(
      "mindclade::triangle_attention", 1u,
      workload_dimensions.data(), workload_dimensions.size(),
      node_dtype(q_view.dtype), "contiguous", "default",
      nullptr, 0u, workload_digest);
  if (digest_status != MINDCLADE_CAPABILITY_STATUS_SUCCESS_V1) {
    throw std::runtime_error("failed to canonicalize Mindclade native workload");
  }
  MindcladeCapabilityRequestV1 request{};
  request.operation = "mindclade::triangle_attention";
  request.phase = MINDCLADE_CAPABILITY_PHASE_BACKWARD_V1;
  request.workload_digest = workload_digest;
  request.device_index = grad_output_view.device_index;
  request.dtype = node_dtype(q_view.dtype);
  request.layout = "contiguous";
  request.mode = "default";
  request.dimensions = workload_dimensions.data();
  request.dimension_count = static_cast<std::uint32_t>(workload_dimensions.size());
  request.attributes = nullptr; request.attribute_count = 0u;
  request.require_atomic_backward = 1u;
  const MindcladeQualifiedCapabilityRowV1* capability = nullptr;
  const auto selection_status = mindclade_select_qualified_capability_v1(
      mindclade_qualified_capability_rows_v1(),
      mindclade_qualified_capability_row_count_v1(), &request,
      &mindclade_cuda_device_architecture_v1, &capability);
  if (selection_status != MINDCLADE_CAPABILITY_STATUS_SUCCESS_V1 || capability == nullptr) {
    throw std::runtime_error("no exact qualified native capability for mindclade::triangle_attention/backward");
  }
  void* current_stream = current_cuda_stream(grad_output, "grad_output");
  std::optional<torch::stable::Tensor> grad_q;
  if (need_q_grad) {
    grad_q = allocate_cuda_tensor(grad_output, q_view.sizes, q_view.dtype, InitializationMode::kUninitialized, 0.0);
  }
  std::optional<torch::stable::Tensor> grad_k;
  if (need_k_grad) {
    grad_k = allocate_cuda_tensor(grad_output, k_view.sizes, k_view.dtype, InitializationMode::kUninitialized, 0.0);
  }
  std::optional<torch::stable::Tensor> grad_v;
  if (need_v_grad) {
    grad_v = allocate_cuda_tensor(grad_output, v_view.sizes, v_view.dtype, InitializationMode::kUninitialized, 0.0);
  }
  std::optional<torch::stable::Tensor> grad_bias;
  if (need_bias_grad) {
    grad_bias = allocate_cuda_tensor(grad_output, bias_view.sizes, bias_view.dtype, InitializationMode::kUninitialized, 0.0);
  }
  auto workspace_delta = allocate_workspace(grad_output, std::vector<std::int64_t>{tensor_dimension(q_view, 0, "q"), tensor_dimension(q_view, 3, "q"), (((tensor_dimension(q_view, 1, "q") + INT64_C(32) - 1) / INT64_C(32)) * INT64_C(32))}, TensorDType::kFloat32, false);
  auto node_0_grad_output_storage = make_node_tensor_value(grad_output, MINDCLADE_NODE_ACCESS_READ_V1, false, "grad_output");
  auto node_0_output_storage = make_node_tensor_value(output, MINDCLADE_NODE_ACCESS_READ_V1, false, "output");
  auto node_0_delta_storage = make_node_tensor_value(workspace_delta, MINDCLADE_NODE_ACCESS_WRITE_V1, false, "delta");
  const auto node_0_stream_value = make_node_stream_value(current_stream);
  const std::array<MindcladeNodeValueV1, 4> node_0_values{{node_0_grad_output_storage.value, node_0_output_storage.value, node_0_delta_storage.value, node_0_stream_value}};
  auto node_1_grad_output_storage = make_node_tensor_value(grad_output, MINDCLADE_NODE_ACCESS_READ_V1, false, "grad_output");
  auto node_1_q_storage = make_node_tensor_value(q, MINDCLADE_NODE_ACCESS_READ_V1, false, "q");
  auto node_1_k_storage = make_node_tensor_value(k, MINDCLADE_NODE_ACCESS_READ_V1, false, "k");
  auto node_1_v_storage = make_node_tensor_value(v, MINDCLADE_NODE_ACCESS_READ_V1, false, "v");
  auto node_1_bias_storage = make_node_tensor_value(bias, MINDCLADE_NODE_ACCESS_READ_V1, false, "bias");
  auto node_1_mask_storage = make_node_tensor_value(mask, MINDCLADE_NODE_ACCESS_READ_V1, false, "mask");
  const auto node_1_scale_value = make_node_float64_value(scale, MINDCLADE_NODE_ACCESS_READ_V1);
  auto node_1_lse_storage = make_node_tensor_value(lse, MINDCLADE_NODE_ACCESS_READ_V1, false, "lse");
  auto node_1_delta_storage = make_node_tensor_value(workspace_delta, MINDCLADE_NODE_ACCESS_READ_V1, false, "delta");
  auto node_1_grad_bias_storage = grad_bias.has_value() ? make_node_tensor_value(*grad_bias, MINDCLADE_NODE_ACCESS_WRITE_V1, true, "grad_bias") : make_absent_node_tensor_value(MINDCLADE_NODE_ACCESS_WRITE_V1);
  const auto node_1_need_bias_grad_value = make_node_bool_value(need_bias_grad, MINDCLADE_NODE_ACCESS_READ_V1);
  const auto node_1_stream_value = make_node_stream_value(current_stream);
  const std::array<MindcladeNodeValueV1, 12> node_1_values{{node_1_grad_output_storage.value, node_1_q_storage.value, node_1_k_storage.value, node_1_v_storage.value, node_1_bias_storage.value, node_1_mask_storage.value, node_1_scale_value, node_1_lse_storage.value, node_1_delta_storage.value, node_1_grad_bias_storage.value, node_1_need_bias_grad_value, node_1_stream_value}};
  auto node_2_grad_output_storage = make_node_tensor_value(grad_output, MINDCLADE_NODE_ACCESS_READ_V1, false, "grad_output");
  auto node_2_q_storage = make_node_tensor_value(q, MINDCLADE_NODE_ACCESS_READ_V1, false, "q");
  auto node_2_k_storage = make_node_tensor_value(k, MINDCLADE_NODE_ACCESS_READ_V1, false, "k");
  auto node_2_v_storage = make_node_tensor_value(v, MINDCLADE_NODE_ACCESS_READ_V1, false, "v");
  auto node_2_bias_storage = make_node_tensor_value(bias, MINDCLADE_NODE_ACCESS_READ_V1, false, "bias");
  auto node_2_mask_storage = make_node_tensor_value(mask, MINDCLADE_NODE_ACCESS_READ_V1, false, "mask");
  const auto node_2_scale_value = make_node_float64_value(scale, MINDCLADE_NODE_ACCESS_READ_V1);
  auto node_2_lse_storage = make_node_tensor_value(lse, MINDCLADE_NODE_ACCESS_READ_V1, false, "lse");
  auto node_2_delta_storage = make_node_tensor_value(workspace_delta, MINDCLADE_NODE_ACCESS_READ_V1, false, "delta");
  auto node_2_grad_k_storage = grad_k.has_value() ? make_node_tensor_value(*grad_k, MINDCLADE_NODE_ACCESS_WRITE_V1, true, "grad_k") : make_absent_node_tensor_value(MINDCLADE_NODE_ACCESS_WRITE_V1);
  const auto node_2_need_k_grad_value = make_node_bool_value(need_k_grad, MINDCLADE_NODE_ACCESS_READ_V1);
  const auto node_2_stream_value = make_node_stream_value(current_stream);
  const std::array<MindcladeNodeValueV1, 12> node_2_values{{node_2_grad_output_storage.value, node_2_q_storage.value, node_2_k_storage.value, node_2_v_storage.value, node_2_bias_storage.value, node_2_mask_storage.value, node_2_scale_value, node_2_lse_storage.value, node_2_delta_storage.value, node_2_grad_k_storage.value, node_2_need_k_grad_value, node_2_stream_value}};
  auto node_3_grad_output_storage = make_node_tensor_value(grad_output, MINDCLADE_NODE_ACCESS_READ_V1, false, "grad_output");
  auto node_3_q_storage = make_node_tensor_value(q, MINDCLADE_NODE_ACCESS_READ_V1, false, "q");
  auto node_3_k_storage = make_node_tensor_value(k, MINDCLADE_NODE_ACCESS_READ_V1, false, "k");
  auto node_3_v_storage = make_node_tensor_value(v, MINDCLADE_NODE_ACCESS_READ_V1, false, "v");
  auto node_3_bias_storage = make_node_tensor_value(bias, MINDCLADE_NODE_ACCESS_READ_V1, false, "bias");
  auto node_3_mask_storage = make_node_tensor_value(mask, MINDCLADE_NODE_ACCESS_READ_V1, false, "mask");
  const auto node_3_scale_value = make_node_float64_value(scale, MINDCLADE_NODE_ACCESS_READ_V1);
  auto node_3_lse_storage = make_node_tensor_value(lse, MINDCLADE_NODE_ACCESS_READ_V1, false, "lse");
  auto node_3_delta_storage = make_node_tensor_value(workspace_delta, MINDCLADE_NODE_ACCESS_READ_V1, false, "delta");
  auto node_3_grad_q_storage = grad_q.has_value() ? make_node_tensor_value(*grad_q, MINDCLADE_NODE_ACCESS_WRITE_V1, true, "grad_q") : make_absent_node_tensor_value(MINDCLADE_NODE_ACCESS_WRITE_V1);
  const auto node_3_need_q_grad_value = make_node_bool_value(need_q_grad, MINDCLADE_NODE_ACCESS_READ_V1);
  const auto node_3_stream_value = make_node_stream_value(current_stream);
  const std::array<MindcladeNodeValueV1, 12> node_3_values{{node_3_grad_output_storage.value, node_3_q_storage.value, node_3_k_storage.value, node_3_v_storage.value, node_3_bias_storage.value, node_3_mask_storage.value, node_3_scale_value, node_3_lse_storage.value, node_3_delta_storage.value, node_3_grad_q_storage.value, node_3_need_q_grad_value, node_3_stream_value}};
  auto node_4_grad_output_storage = make_node_tensor_value(grad_output, MINDCLADE_NODE_ACCESS_READ_V1, false, "grad_output");
  auto node_4_q_storage = make_node_tensor_value(q, MINDCLADE_NODE_ACCESS_READ_V1, false, "q");
  auto node_4_k_storage = make_node_tensor_value(k, MINDCLADE_NODE_ACCESS_READ_V1, false, "k");
  auto node_4_v_storage = make_node_tensor_value(v, MINDCLADE_NODE_ACCESS_READ_V1, false, "v");
  auto node_4_bias_storage = make_node_tensor_value(bias, MINDCLADE_NODE_ACCESS_READ_V1, false, "bias");
  auto node_4_mask_storage = make_node_tensor_value(mask, MINDCLADE_NODE_ACCESS_READ_V1, false, "mask");
  const auto node_4_scale_value = make_node_float64_value(scale, MINDCLADE_NODE_ACCESS_READ_V1);
  auto node_4_lse_storage = make_node_tensor_value(lse, MINDCLADE_NODE_ACCESS_READ_V1, false, "lse");
  auto node_4_grad_v_storage = grad_v.has_value() ? make_node_tensor_value(*grad_v, MINDCLADE_NODE_ACCESS_WRITE_V1, true, "grad_v") : make_absent_node_tensor_value(MINDCLADE_NODE_ACCESS_WRITE_V1);
  const auto node_4_need_v_grad_value = make_node_bool_value(need_v_grad, MINDCLADE_NODE_ACCESS_READ_V1);
  const auto node_4_stream_value = make_node_stream_value(current_stream);
  const std::array<MindcladeNodeValueV1, 11> node_4_values{{node_4_grad_output_storage.value, node_4_q_storage.value, node_4_k_storage.value, node_4_v_storage.value, node_4_bias_storage.value, node_4_mask_storage.value, node_4_scale_value, node_4_lse_storage.value, node_4_grad_v_storage.value, node_4_need_v_grad_value, node_4_stream_value}};
  const std::array<MindcladeNodeInvocationV1, 5> invocations{{
      MindcladeNodeInvocationV1{node_0_values.data(), static_cast<std::uint32_t>(node_0_values.size())},
      MindcladeNodeInvocationV1{node_1_values.data(), static_cast<std::uint32_t>(node_1_values.size())},
      MindcladeNodeInvocationV1{node_2_values.data(), static_cast<std::uint32_t>(node_2_values.size())},
      MindcladeNodeInvocationV1{node_3_values.data(), static_cast<std::uint32_t>(node_3_values.size())},
      MindcladeNodeInvocationV1{node_4_values.data(), static_cast<std::uint32_t>(node_4_values.size())},
  }};
  std::int32_t adapter_status = MINDCLADE_NODE_STATUS_SUCCESS_V1;
  const auto execution_status = mindclade_execute_qualified_capability_v1(
      capability, invocations.data(), invocations.size(), &adapter_status);
  if (execution_status != MINDCLADE_CAPABILITY_STATUS_SUCCESS_V1) {
    throw std::runtime_error("Mindclade native program group execution failed with status " +
                             std::to_string(adapter_status));
  }
  return {grad_q, grad_k, grad_v, grad_bias};
}

extern "C" torch::stable::Tensor mindclade_tilelang_triangle_multiplication_fwd_launch(const torch::stable::Tensor& left, const torch::stable::Tensor& right, const torch::stable::Tensor& mask, bool outgoing) {
  const auto left_view = require_cuda_contiguous_tensor(left, "left");
  const auto right_view = require_cuda_contiguous_tensor(right, "right");
  const auto mask_view = require_cuda_contiguous_tensor(mask, "mask");
  require_same_device(left_view, right_view, "right");
  require_same_device(left_view, mask_view, "mask");
  const std::array<MindcladeCapabilityDimensionV1, 3> workload_dimensions{{
      {"batch", tensor_dimension(left_view, 0, "left")},
      {"channels", tensor_dimension(left_view, 3, "left")},
      {"residues", tensor_dimension(left_view, 1, "left")},
  }};
  char workload_digest[72]{};
  const auto digest_status = mindclade_canonical_workload_digest_v1(
      "mindclade::triangle_multiplication", 1u,
      workload_dimensions.data(), workload_dimensions.size(),
      node_dtype(left_view.dtype), "contiguous", (outgoing ? "outgoing" : "incoming"),
      nullptr, 0u, workload_digest);
  if (digest_status != MINDCLADE_CAPABILITY_STATUS_SUCCESS_V1) {
    throw std::runtime_error("failed to canonicalize Mindclade native workload");
  }
  MindcladeCapabilityRequestV1 request{};
  request.operation = "mindclade::triangle_multiplication";
  request.phase = MINDCLADE_CAPABILITY_PHASE_FORWARD_V1;
  request.workload_digest = workload_digest;
  request.device_index = left_view.device_index;
  request.dtype = node_dtype(left_view.dtype);
  request.layout = "contiguous";
  request.mode = (outgoing ? "outgoing" : "incoming");
  request.dimensions = workload_dimensions.data();
  request.dimension_count = static_cast<std::uint32_t>(workload_dimensions.size());
  request.attributes = nullptr; request.attribute_count = 0u;
  request.require_atomic_backward = 1u;
  const MindcladeQualifiedCapabilityRowV1* capability = nullptr;
  const auto selection_status = mindclade_select_qualified_capability_v1(
      mindclade_qualified_capability_rows_v1(),
      mindclade_qualified_capability_row_count_v1(), &request,
      &mindclade_cuda_device_architecture_v1, &capability);
  if (selection_status != MINDCLADE_CAPABILITY_STATUS_SUCCESS_V1 || capability == nullptr) {
    throw std::runtime_error("no exact qualified native capability for mindclade::triangle_multiplication/forward");
  }
  void* current_stream = current_cuda_stream(left, "left");
  auto output = allocate_cuda_tensor(left, left_view.sizes, left_view.dtype, InitializationMode::kUninitialized, 0.0);
  auto node_0_left_storage = make_node_tensor_value(left, MINDCLADE_NODE_ACCESS_READ_V1, false, "left");
  auto node_0_right_storage = make_node_tensor_value(right, MINDCLADE_NODE_ACCESS_READ_V1, false, "right");
  auto node_0_mask_storage = make_node_tensor_value(mask, MINDCLADE_NODE_ACCESS_READ_V1, false, "mask");
  auto node_0_output_storage = make_node_tensor_value(output, MINDCLADE_NODE_ACCESS_WRITE_V1, false, "output");
  const auto node_0_stream_value = make_node_stream_value(current_stream);
  const std::array<MindcladeNodeValueV1, 5> node_0_values{{node_0_left_storage.value, node_0_right_storage.value, node_0_mask_storage.value, node_0_output_storage.value, node_0_stream_value}};
  const std::array<MindcladeNodeInvocationV1, 1> invocations{{
      MindcladeNodeInvocationV1{node_0_values.data(), static_cast<std::uint32_t>(node_0_values.size())},
  }};
  std::int32_t adapter_status = MINDCLADE_NODE_STATUS_SUCCESS_V1;
  const auto execution_status = mindclade_execute_qualified_capability_v1(
      capability, invocations.data(), invocations.size(), &adapter_status);
  if (execution_status != MINDCLADE_CAPABILITY_STATUS_SUCCESS_V1) {
    throw std::runtime_error("Mindclade native program group execution failed with status " +
                             std::to_string(adapter_status));
  }
  return output;
}

extern "C" std::tuple<std::optional<torch::stable::Tensor>, std::optional<torch::stable::Tensor>> mindclade_tilelang_triangle_multiplication_bwd_launch(const torch::stable::Tensor& grad_output, const torch::stable::Tensor& left, const torch::stable::Tensor& right, const torch::stable::Tensor& mask, bool outgoing, bool need_left_grad, bool need_right_grad) {
  const auto grad_output_view = require_cuda_contiguous_tensor(grad_output, "grad_output");
  const auto left_view = require_cuda_contiguous_tensor(left, "left");
  const auto right_view = require_cuda_contiguous_tensor(right, "right");
  const auto mask_view = require_cuda_contiguous_tensor(mask, "mask");
  require_same_device(grad_output_view, left_view, "left");
  require_same_device(grad_output_view, right_view, "right");
  require_same_device(grad_output_view, mask_view, "mask");
  const std::array<MindcladeCapabilityDimensionV1, 3> workload_dimensions{{
      {"batch", tensor_dimension(left_view, 0, "left")},
      {"channels", tensor_dimension(left_view, 3, "left")},
      {"residues", tensor_dimension(left_view, 1, "left")},
  }};
  char workload_digest[72]{};
  const auto digest_status = mindclade_canonical_workload_digest_v1(
      "mindclade::triangle_multiplication", 1u,
      workload_dimensions.data(), workload_dimensions.size(),
      node_dtype(left_view.dtype), "contiguous", (outgoing ? "outgoing" : "incoming"),
      nullptr, 0u, workload_digest);
  if (digest_status != MINDCLADE_CAPABILITY_STATUS_SUCCESS_V1) {
    throw std::runtime_error("failed to canonicalize Mindclade native workload");
  }
  MindcladeCapabilityRequestV1 request{};
  request.operation = "mindclade::triangle_multiplication";
  request.phase = MINDCLADE_CAPABILITY_PHASE_BACKWARD_V1;
  request.workload_digest = workload_digest;
  request.device_index = grad_output_view.device_index;
  request.dtype = node_dtype(left_view.dtype);
  request.layout = "contiguous";
  request.mode = (outgoing ? "outgoing" : "incoming");
  request.dimensions = workload_dimensions.data();
  request.dimension_count = static_cast<std::uint32_t>(workload_dimensions.size());
  request.attributes = nullptr; request.attribute_count = 0u;
  request.require_atomic_backward = 1u;
  const MindcladeQualifiedCapabilityRowV1* capability = nullptr;
  const auto selection_status = mindclade_select_qualified_capability_v1(
      mindclade_qualified_capability_rows_v1(),
      mindclade_qualified_capability_row_count_v1(), &request,
      &mindclade_cuda_device_architecture_v1, &capability);
  if (selection_status != MINDCLADE_CAPABILITY_STATUS_SUCCESS_V1 || capability == nullptr) {
    throw std::runtime_error("no exact qualified native capability for mindclade::triangle_multiplication/backward");
  }
  void* current_stream = current_cuda_stream(grad_output, "grad_output");
  std::optional<torch::stable::Tensor> grad_left;
  if (need_left_grad) {
    grad_left = allocate_cuda_tensor(grad_output, left_view.sizes, left_view.dtype, InitializationMode::kUninitialized, 0.0);
  }
  std::optional<torch::stable::Tensor> grad_right;
  if (need_right_grad) {
    grad_right = allocate_cuda_tensor(grad_output, right_view.sizes, right_view.dtype, InitializationMode::kUninitialized, 0.0);
  }
  auto node_0_grad_output_storage = make_node_tensor_value(grad_output, MINDCLADE_NODE_ACCESS_READ_V1, false, "grad_output");
  auto node_0_left_storage = make_node_tensor_value(left, MINDCLADE_NODE_ACCESS_READ_V1, false, "left");
  auto node_0_right_storage = make_node_tensor_value(right, MINDCLADE_NODE_ACCESS_READ_V1, false, "right");
  auto node_0_mask_storage = make_node_tensor_value(mask, MINDCLADE_NODE_ACCESS_READ_V1, false, "mask");
  auto node_0_grad_left_storage = grad_left.has_value() ? make_node_tensor_value(*grad_left, MINDCLADE_NODE_ACCESS_WRITE_V1, true, "grad_left") : make_absent_node_tensor_value(MINDCLADE_NODE_ACCESS_WRITE_V1);
  const auto node_0_need_left_grad_value = make_node_bool_value(need_left_grad, MINDCLADE_NODE_ACCESS_READ_V1);
  const auto node_0_stream_value = make_node_stream_value(current_stream);
  const std::array<MindcladeNodeValueV1, 7> node_0_values{{node_0_grad_output_storage.value, node_0_left_storage.value, node_0_right_storage.value, node_0_mask_storage.value, node_0_grad_left_storage.value, node_0_need_left_grad_value, node_0_stream_value}};
  auto node_1_grad_output_storage = make_node_tensor_value(grad_output, MINDCLADE_NODE_ACCESS_READ_V1, false, "grad_output");
  auto node_1_left_storage = make_node_tensor_value(left, MINDCLADE_NODE_ACCESS_READ_V1, false, "left");
  auto node_1_right_storage = make_node_tensor_value(right, MINDCLADE_NODE_ACCESS_READ_V1, false, "right");
  auto node_1_mask_storage = make_node_tensor_value(mask, MINDCLADE_NODE_ACCESS_READ_V1, false, "mask");
  auto node_1_grad_right_storage = grad_right.has_value() ? make_node_tensor_value(*grad_right, MINDCLADE_NODE_ACCESS_WRITE_V1, true, "grad_right") : make_absent_node_tensor_value(MINDCLADE_NODE_ACCESS_WRITE_V1);
  const auto node_1_need_right_grad_value = make_node_bool_value(need_right_grad, MINDCLADE_NODE_ACCESS_READ_V1);
  const auto node_1_stream_value = make_node_stream_value(current_stream);
  const std::array<MindcladeNodeValueV1, 7> node_1_values{{node_1_grad_output_storage.value, node_1_left_storage.value, node_1_right_storage.value, node_1_mask_storage.value, node_1_grad_right_storage.value, node_1_need_right_grad_value, node_1_stream_value}};
  const std::array<MindcladeNodeInvocationV1, 2> invocations{{
      MindcladeNodeInvocationV1{node_0_values.data(), static_cast<std::uint32_t>(node_0_values.size())},
      MindcladeNodeInvocationV1{node_1_values.data(), static_cast<std::uint32_t>(node_1_values.size())},
  }};
  std::int32_t adapter_status = MINDCLADE_NODE_STATUS_SUCCESS_V1;
  const auto execution_status = mindclade_execute_qualified_capability_v1(
      capability, invocations.data(), invocations.size(), &adapter_status);
  if (execution_status != MINDCLADE_CAPABILITY_STATUS_SUCCESS_V1) {
    throw std::runtime_error("Mindclade native program group execution failed with status " +
                             std::to_string(adapter_status));
  }
  return {grad_left, grad_right};
}

constexpr std::array<std::string_view, 10> kStaticLauncherPlans{{
    R"mindclade({"adapter_symbol_prefixes":["mindclade_tilelang_outer_product_mean_normalizer_launch","mindclade_tilelang_outer_product_mean_numerator_launch"],"execution_order":["normalizer","numerator"],"logical_symbol":"mindclade_tilelang_outer_product_mean_fwd_launch","operation":"mindclade::outer_product_mean","outputs":[{"initialization":null,"name":"output","saved_for_backward":true},{"initialization":null,"name":"normalizer","saved_for_backward":true}],"phase":"forward","selector_bindings":[],"workspaces":[]})mindclade",
    R"mindclade({"adapter_symbol_prefixes":["mindclade_tilelang_outer_product_mean_dleft_launch","mindclade_tilelang_outer_product_mean_dmask_launch","mindclade_tilelang_outer_product_mean_dright_launch"],"execution_order":["dleft","dmask","dright"],"logical_symbol":"mindclade_tilelang_outer_product_mean_bwd_launch","operation":"mindclade::outer_product_mean","outputs":[],"phase":"backward","selector_bindings":[],"workspaces":[]})mindclade",
    R"mindclade({"adapter_symbol_prefixes":["mindclade_tilelang_pair_weighted_average_online_forward_launch"],"execution_order":["online_forward"],"logical_symbol":"mindclade_tilelang_pair_weighted_average_fwd_launch","operation":"mindclade::pair_weighted_average","outputs":[{"initialization":null,"name":"output","saved_for_backward":true},{"initialization":null,"name":"lse","saved_for_backward":true}],"phase":"forward","selector_bindings":[],"workspaces":[]})mindclade",
    R"mindclade({"adapter_symbol_prefixes":["mindclade_tilelang_pair_weighted_average_delta_launch","mindclade_tilelang_pair_weighted_average_dvalue_launch","mindclade_tilelang_pair_weighted_average_dweights_launch"],"execution_order":["delta","dvalue","dweights"],"logical_symbol":"mindclade_tilelang_pair_weighted_average_bwd_launch","operation":"mindclade::pair_weighted_average","outputs":[],"phase":"backward","selector_bindings":[],"workspaces":[{"dtype":{"node":"constant_dtype","value":"float32"},"lifetime":"program_group","name":"delta","shape":{"dimensions":[{"argument":"value","axis":0,"node":"dim_ref"},{"argument":"weights","axis":1,"node":"dim_ref"},{"argument":"weights","axis":3,"node":"dim_ref"}],"node":"shape_tuple"},"zero_initialize":false}]})mindclade",
    R"mindclade({"adapter_symbol_prefixes":["mindclade_tilelang_transition_transition_forward_launch"],"execution_order":["transition_forward"],"logical_symbol":"mindclade_tilelang_transition_fwd_launch","operation":"mindclade::transition","outputs":[{"initialization":null,"name":"output","saved_for_backward":false},{"initialization":null,"name":"pre_mask_output","saved_for_backward":true}],"phase":"forward","selector_bindings":[],"workspaces":[]})mindclade",
    R"mindclade({"adapter_symbol_prefixes":["mindclade_tilelang_transition_grad_bias_launch","mindclade_tilelang_transition_grad_gate_launch","mindclade_tilelang_transition_grad_mask_launch","mindclade_tilelang_transition_grad_value_launch","mindclade_tilelang_transition_grad_weight_launch"],"execution_order":["grad_bias","grad_gate","grad_mask","grad_value","grad_weight"],"logical_symbol":"mindclade_tilelang_transition_bwd_launch","operation":"mindclade::transition","outputs":[],"phase":"backward","selector_bindings":[],"workspaces":[]})mindclade",
    R"mindclade({"adapter_symbol_prefixes":["mindclade_tilelang_triangle_attention_forward_launch"],"execution_order":["forward"],"logical_symbol":"mindclade_tilelang_triangle_attention_fwd_launch","operation":"mindclade::triangle_attention","outputs":[{"initialization":null,"name":"output","saved_for_backward":true},{"initialization":{"mode":"negative_infinity","type":"InitializationSpec","value":null,"version":1},"name":"lse","saved_for_backward":true}],"phase":"forward","selector_bindings":[],"workspaces":[]})mindclade",
    R"mindclade({"adapter_symbol_prefixes":["mindclade_tilelang_triangle_attention_delta_launch","mindclade_tilelang_triangle_attention_dbias_launch","mindclade_tilelang_triangle_attention_dk_launch","mindclade_tilelang_triangle_attention_dq_launch","mindclade_tilelang_triangle_attention_dv_launch"],"execution_order":["delta","dbias","dk","dq","dv"],"logical_symbol":"mindclade_tilelang_triangle_attention_bwd_launch","operation":"mindclade::triangle_attention","outputs":[],"phase":"backward","selector_bindings":[],"workspaces":[{"dtype":{"node":"constant_dtype","value":"float32"},"lifetime":"program_group","name":"delta","shape":{"dimensions":[{"argument":"q","axis":0,"node":"dim_ref"},{"argument":"q","axis":3,"node":"dim_ref"},{"multiple":{"node":"int_literal","value":32},"node":"round_up","value":{"argument":"q","axis":1,"node":"dim_ref"}}],"node":"shape_tuple"},"zero_initialize":false}]})mindclade",
    R"mindclade({"adapter_symbol_prefixes":["mindclade_tilelang_triangle_multiplication_forward_launch"],"execution_order":["forward"],"logical_symbol":"mindclade_tilelang_triangle_multiplication_fwd_launch","operation":"mindclade::triangle_multiplication","outputs":[{"initialization":null,"name":"output","saved_for_backward":false}],"phase":"forward","selector_bindings":[{"cases":[[false,"incoming"],[true,"outgoing"]],"provider_argument":"outgoing","scalar_type":"bool","selector_key":"mode","type":"ProgramSelectorBinding","version":1}],"workspaces":[]})mindclade",
    R"mindclade({"adapter_symbol_prefixes":["mindclade_tilelang_triangle_multiplication_dleft_launch","mindclade_tilelang_triangle_multiplication_dright_launch"],"execution_order":["dleft","dright"],"logical_symbol":"mindclade_tilelang_triangle_multiplication_bwd_launch","operation":"mindclade::triangle_multiplication","outputs":[],"phase":"backward","selector_bindings":[{"cases":[[false,"incoming"],[true,"outgoing"]],"provider_argument":"outgoing","scalar_type":"bool","selector_key":"mode","type":"ProgramSelectorBinding","version":1}],"workspaces":[]})mindclade",
}};
}  // namespace mindclade::native::generated

extern "C" const mindclade::native::generated::PrivateLauncher*
mindclade_native_required_private_launchers() noexcept {
  return mindclade::native::generated::kRequiredPrivateLaunchers.data();
}

extern "C" std::size_t mindclade_native_static_launcher_plan_count() noexcept {
  return mindclade::native::generated::kStaticLauncherPlans.size();
}

#if defined(__clang__)
#pragma clang diagnostic pop
#endif
