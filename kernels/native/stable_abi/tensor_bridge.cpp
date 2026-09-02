// Copyright (c) 2026 Mindclade. All rights reserved.
// Proprietary and confidential. Unauthorized use, copying, or distribution is prohibited.

#include "tensor_bridge.h"

#include <limits>
#include <optional>
#include <stdexcept>
#include <string>
#include <utility>

#include <torch/csrc/inductor/aoti_torch/c/shim.h>
#include <torch/csrc/stable/ops.h>

namespace mindclade::native::stable_abi {
namespace {

[[noreturn]] void fail(std::string_view argument, std::string_view message) {
  throw std::invalid_argument(
      "mindclade native tensor " + std::string(argument) + ": " +
      std::string(message));
}

torch::stable::ScalarType to_scalar_type(TensorDType dtype) {
  using ScalarType = torch::stable::ScalarType;
  switch (dtype) {
    case TensorDType::kFloat16:
      return ScalarType::Half;
    case TensorDType::kBFloat16:
      return ScalarType::BFloat16;
    case TensorDType::kFloat32:
      return ScalarType::Float;
    case TensorDType::kBool:
      return ScalarType::Bool;
  }
  throw std::invalid_argument("unsupported Mindclade tensor dtype");
}

TensorDType from_scalar_type(torch::stable::ScalarType dtype) {
  using ScalarType = torch::stable::ScalarType;
  switch (dtype) {
    case ScalarType::Half:
      return TensorDType::kFloat16;
    case ScalarType::BFloat16:
      return TensorDType::kBFloat16;
    case ScalarType::Float:
      return TensorDType::kFloat32;
    case ScalarType::Bool:
      return TensorDType::kBool;
    default:
      throw std::invalid_argument("unsupported Mindclade input tensor dtype");
  }
}

void validate_shape(const std::vector<std::int64_t>& shape) {
  constexpr std::size_t kMaximumRank = 16;
  if (shape.size() > kMaximumRank) {
    throw std::invalid_argument("Mindclade tensor rank exceeds 16");
  }
  std::uint64_t elements = 1;
  for (const std::int64_t dimension : shape) {
    if (dimension < 0) {
      throw std::invalid_argument("Mindclade tensor shape contains a negative dimension");
    }
    if (dimension != 0 &&
        elements > std::numeric_limits<std::uint64_t>::max() /
            static_cast<std::uint64_t>(dimension)) {
      throw std::overflow_error("Mindclade tensor element count overflow");
    }
    elements *= static_cast<std::uint64_t>(dimension);
  }
}

}  // namespace

TensorView require_cuda_contiguous_tensor(
    const torch::stable::Tensor& tensor,
    std::string_view argument,
    std::int64_t expected_rank) {
  if (!tensor.defined()) {
    fail(argument, "must be defined");
  }
  if (!tensor.is_cuda()) {
    fail(argument, "must be a CUDA tensor");
  }
  if (!tensor.is_contiguous()) {
    fail(argument, "must be contiguous");
  }
  const std::int64_t rank = tensor.dim();
  if (rank < 0 || rank > 16) {
    fail(argument, "rank is outside the supported range [0, 16]");
  }
  if (expected_rank >= 0 && rank != expected_rank) {
    fail(argument, "rank does not match the capability contract");
  }
  std::vector<std::int64_t> sizes;
  std::vector<std::int64_t> strides;
  sizes.reserve(static_cast<std::size_t>(rank));
  strides.reserve(static_cast<std::size_t>(rank));
  for (std::int64_t axis = 0; axis < rank; ++axis) {
    const std::int64_t size = tensor.size(axis);
    const std::int64_t stride = tensor.stride(axis);
    if (size < 0 || stride < 0) {
      fail(argument, "has invalid negative size or stride metadata");
    }
    sizes.push_back(size);
    strides.push_back(stride);
  }
  return TensorView{
      tensor.data_ptr(),
      std::move(sizes),
      std::move(strides),
      from_scalar_type(tensor.scalar_type()),
      tensor.get_device_index(),
  };
}

void* current_cuda_stream(
    const torch::stable::Tensor& tensor,
    std::string_view argument) {
  const TensorView view = require_cuda_contiguous_tensor(tensor, argument);
  void* stream = nullptr;
  const AOTITorchError error =
      aoti_torch_get_current_cuda_stream(view.device_index, &stream);
  if (error != 0 || stream == nullptr) {
    throw std::runtime_error("could not obtain the current CUDA stream");
  }
  return stream;
}

torch::stable::Tensor allocate_cuda_tensor(
    const torch::stable::Tensor& like,
    const std::vector<std::int64_t>& shape,
    TensorDType dtype,
    InitializationMode initialization,
    double initialization_value) {
  static_cast<void>(require_cuda_contiguous_tensor(like, "allocation template"));
  validate_shape(shape);
  const auto scalar_type =
      std::optional<torch::stable::ScalarType>(to_scalar_type(dtype));
  if (initialization == InitializationMode::kZero) {
    return torch::stable::new_zeros(like, shape, scalar_type);
  }
  torch::stable::Tensor output =
      torch::stable::new_empty(like, shape, scalar_type);
  switch (initialization) {
    case InitializationMode::kUninitialized:
      return output;
    case InitializationMode::kZero:
      return output;
    case InitializationMode::kValue:
      return torch::stable::fill_(output, initialization_value);
    case InitializationMode::kNegativeInfinity:
      return torch::stable::fill_(
          output, -std::numeric_limits<double>::infinity());
  }
  throw std::invalid_argument("unsupported Mindclade initialization mode");
}

torch::stable::Tensor allocate_workspace(
    const torch::stable::Tensor& like,
    const std::vector<std::int64_t>& shape,
    TensorDType dtype,
    bool zero_initialize) {
  return allocate_cuda_tensor(
      like,
      shape,
      dtype,
      zero_initialize ? InitializationMode::kZero
                      : InitializationMode::kUninitialized);
}

}  // namespace mindclade::native::stable_abi
