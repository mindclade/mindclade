// Copyright (c) 2026 Mindclade. All rights reserved.
// Proprietary and confidential. Unauthorized use, copying, or distribution is prohibited.

#pragma once

#include <cstdint>

extern "C" std::int32_t mindclade_cuda_device_architecture_v1(
    std::int32_t device_index,
    std::uint32_t* architecture);
