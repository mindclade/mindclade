// Copyright (c) 2026 Mindclade. All rights reserved.
// Proprietary and confidential. Unauthorized use, copying, or distribution is prohibited.

#ifndef MINDCLADE_NATIVE_SCHEMA_ONLY
#error "The current native target is schema-only"
#endif

#ifndef MINDCLADE_TORCH_STABLE_ABI_MAJOR
#error "Torch Stable ABI major version must be declared by the build authority"
#endif

#ifndef MINDCLADE_TORCH_STABLE_ABI_MINOR
#error "Torch Stable ABI minor version must be declared by the build authority"
#endif

namespace {

constexpr bool kTensorBridgeAvailable = false;

static_assert(MINDCLADE_TORCH_STABLE_ABI_MAJOR == 2);
static_assert(MINDCLADE_TORCH_STABLE_ABI_MINOR == 10);
static_assert(!kTensorBridgeAvailable);

}  // namespace
