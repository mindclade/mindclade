// Copyright (c) 2026 Mindclade. All rights reserved.
// Proprietary and confidential. Unauthorized use, copying, or distribution is prohibited.

#pragma once

#include <cstdint>
#include <string_view>
#include <vector>

#include <torch/csrc/stable/tensor.h>

#include "node_launch_abi.h"

namespace mindclade::native::stable_abi {

struct NodeTensorValueStorage final {
  MindcladeNodeValueV1 value{};
  std::vector<std::int64_t> sizes;
  std::vector<std::int64_t> strides;

  NodeTensorValueStorage() = default;
  NodeTensorValueStorage(const NodeTensorValueStorage&) = delete;
  NodeTensorValueStorage& operator=(const NodeTensorValueStorage&) = delete;
  NodeTensorValueStorage(NodeTensorValueStorage&&) noexcept = default;
  NodeTensorValueStorage& operator=(NodeTensorValueStorage&&) noexcept = default;
};

[[nodiscard]] NodeTensorValueStorage make_node_tensor_value(
    const torch::stable::Tensor& tensor,
    MindcladeNodeAccessV1 access,
    bool optional,
    std::string_view argument);

[[nodiscard]] NodeTensorValueStorage make_absent_node_tensor_value(
    MindcladeNodeAccessV1 access);

[[nodiscard]] MindcladeNodeValueV1 make_node_bool_value(
    bool value,
    MindcladeNodeAccessV1 access = MINDCLADE_NODE_ACCESS_READ_V1);

[[nodiscard]] MindcladeNodeValueV1 make_node_int64_value(
    std::int64_t value,
    MindcladeNodeAccessV1 access = MINDCLADE_NODE_ACCESS_READ_V1);

[[nodiscard]] MindcladeNodeValueV1 make_node_float64_value(
    double value,
    MindcladeNodeAccessV1 access = MINDCLADE_NODE_ACCESS_READ_V1);

[[nodiscard]] MindcladeNodeValueV1 make_node_stream_value(void* stream);

void require_node_success(std::int32_t status, std::string_view adapter_symbol);

}  // namespace mindclade::native::stable_abi
