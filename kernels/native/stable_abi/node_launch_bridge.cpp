// Copyright (c) 2026 Mindclade. All rights reserved.
// Proprietary and confidential. Unauthorized use, copying, or distribution is prohibited.

#include "node_launch_bridge.h"

#include <stdexcept>
#include <string>
#include <utility>

#include "tensor_bridge.h"

namespace mindclade::native::stable_abi {
namespace {

MindcladeNodeValueV1 value_header(
    MindcladeNodeValueKindV1 kind,
    MindcladeNodeAccessV1 access) {
  MindcladeNodeValueV1 value{};
  value.kind = static_cast<std::uint32_t>(kind);
  value.access = static_cast<std::uint32_t>(access);
  return value;
}

}  // namespace

NodeTensorValueStorage make_node_tensor_value(
    const torch::stable::Tensor& tensor,
    MindcladeNodeAccessV1 access,
    bool optional,
    std::string_view argument) {
  TensorView view = require_cuda_contiguous_tensor(tensor, argument);
  NodeTensorValueStorage storage;
  storage.sizes = std::move(view.sizes);
  storage.strides = std::move(view.strides);
  storage.value = value_header(MINDCLADE_NODE_VALUE_TENSOR_V1, access);
  storage.value.payload.tensor = MindcladeNodeTensorV1{
      view.data,
      storage.sizes.data(),
      storage.strides.data(),
      static_cast<std::int32_t>(storage.sizes.size()),
      static_cast<std::int32_t>(node_dtype(view.dtype)),
      view.device_index,
      static_cast<std::uint32_t>(
          MINDCLADE_NODE_TENSOR_PRESENT_V1 |
          (optional ? MINDCLADE_NODE_TENSOR_OPTIONAL_V1 : 0u)),
  };
  return storage;
}

NodeTensorValueStorage make_absent_node_tensor_value(
    MindcladeNodeAccessV1 access) {
  NodeTensorValueStorage storage;
  storage.value = value_header(MINDCLADE_NODE_VALUE_TENSOR_V1, access);
  storage.value.payload.tensor.flags = MINDCLADE_NODE_TENSOR_OPTIONAL_V1;
  return storage;
}

MindcladeNodeValueV1 make_node_bool_value(
    bool value,
    MindcladeNodeAccessV1 access) {
  MindcladeNodeValueV1 result = value_header(MINDCLADE_NODE_VALUE_BOOL_V1, access);
  result.payload.boolean_value = value ? UINT64_C(1) : UINT64_C(0);
  return result;
}

MindcladeNodeValueV1 make_node_int64_value(
    std::int64_t value,
    MindcladeNodeAccessV1 access) {
  MindcladeNodeValueV1 result = value_header(MINDCLADE_NODE_VALUE_INT64_V1, access);
  result.payload.int64_value = value;
  return result;
}

MindcladeNodeValueV1 make_node_float64_value(
    double value,
    MindcladeNodeAccessV1 access) {
  MindcladeNodeValueV1 result = value_header(MINDCLADE_NODE_VALUE_FLOAT64_V1, access);
  result.payload.float64_value = value;
  return result;
}

MindcladeNodeValueV1 make_node_stream_value(void* stream) {
  if (stream == nullptr) {
    throw std::invalid_argument("Mindclade node stream must not be null");
  }
  MindcladeNodeValueV1 result = value_header(
      MINDCLADE_NODE_VALUE_STREAM_V1, MINDCLADE_NODE_ACCESS_READ_V1);
  result.payload.stream = stream;
  return result;
}

void require_node_success(std::int32_t status, std::string_view adapter_symbol) {
  if (status != MINDCLADE_NODE_STATUS_SUCCESS_V1) {
    throw std::runtime_error(
        "Mindclade node adapter " + std::string(adapter_symbol) +
        " failed with status " + std::to_string(status));
  }
}

}  // namespace mindclade::native::stable_abi
