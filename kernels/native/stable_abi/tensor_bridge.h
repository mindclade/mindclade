// Copyright (c) 2026 Mindclade. All rights reserved.
// Proprietary and confidential. Unauthorized use, copying, or distribution is prohibited.

#pragma once

#include <cstdint>
#include <string_view>
#include <vector>

#include <torch/csrc/stable/tensor.h>

#include "node_launch_abi.h"

namespace mindclade::native::stable_abi {

enum class TensorDType : std::uint8_t {
  kFloat16,
  kBFloat16,
  kFloat32,
  kBool,
};

enum class InitializationMode : std::uint8_t {
  kUninitialized,
  kZero,
  kValue,
  kNegativeInfinity,
};

struct TensorView final {
  void* data;
  std::vector<std::int64_t> sizes;
  std::vector<std::int64_t> strides;
  TensorDType dtype;
  std::int32_t device_index;
};

[[nodiscard]] TensorView require_cuda_contiguous_tensor(
    const torch::stable::Tensor& tensor,
    std::string_view argument,
    std::int64_t expected_rank = -1);

[[nodiscard]] std::int64_t tensor_dimension(
    const TensorView& view,
    std::int64_t axis,
    std::string_view argument);

[[nodiscard]] std::uint32_t node_dtype(TensorDType dtype);

void require_same_device(
    const TensorView& expected,
    const TensorView& actual,
    std::string_view argument);

[[nodiscard]] void* current_cuda_stream(
    const torch::stable::Tensor& tensor,
    std::string_view argument);

[[nodiscard]] torch::stable::Tensor allocate_cuda_tensor(
    const torch::stable::Tensor& like,
    const std::vector<std::int64_t>& shape,
    TensorDType dtype,
    InitializationMode initialization,
    double initialization_value = 0.0);

[[nodiscard]] torch::stable::Tensor allocate_workspace(
    const torch::stable::Tensor& like,
    const std::vector<std::int64_t>& shape,
    TensorDType dtype,
    bool zero_initialize);

}  // namespace mindclade::native::stable_abi
