// Copyright (c) 2026 Mindclade. All rights reserved.
// Proprietary and confidential. Unauthorized use, copying, or distribution is prohibited.

#include "device_architecture.h"

#include <cuda_runtime_api.h>

#include "../stable_abi/qualified_capability_table.h"

extern "C" std::int32_t mindclade_cuda_device_architecture_v1(
    std::int32_t device_index,
    std::uint32_t* architecture) {
  if (device_index < 0 || architecture == nullptr) {
    return MINDCLADE_CAPABILITY_STATUS_INVALID_ARGUMENT_V1;
  }
  *architecture = MINDCLADE_DEVICE_ARCHITECTURE_UNKNOWN_V1;
  cudaDeviceProp properties{};
  if (cudaGetDeviceProperties(&properties, device_index) != cudaSuccess) {
    return MINDCLADE_CAPABILITY_STATUS_ARCHITECTURE_QUERY_FAILED_V1;
  }
  if (properties.major == 8 && properties.minor == 0) {
    *architecture = MINDCLADE_DEVICE_ARCHITECTURE_SM80_V1;
  } else if (properties.major == 9 && properties.minor == 0) {
    *architecture = MINDCLADE_DEVICE_ARCHITECTURE_SM90A_V1;
  } else if (properties.major == 10 && properties.minor == 0) {
    *architecture = MINDCLADE_DEVICE_ARCHITECTURE_SM100A_V1;
  } else {
    return MINDCLADE_CAPABILITY_STATUS_ARCHITECTURE_QUERY_FAILED_V1;
  }
  return MINDCLADE_CAPABILITY_STATUS_SUCCESS_V1;
}
