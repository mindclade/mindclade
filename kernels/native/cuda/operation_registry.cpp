// Copyright (c) 2026 Mindclade. All rights reserved.
// Proprietary and confidential. Unauthorized use, copying, or distribution is prohibited.

#include <string_view>

namespace {

constexpr std::string_view kDispatcherNamespace{"mindclade"};
constexpr std::string_view kRegistrationContract{
    "torch.ops.mindclade.<name>"};
constexpr std::string_view kRegistrationPrefix{"torch.ops.mindclade."};

static_assert(kDispatcherNamespace == "mindclade");
static_assert(
    kRegistrationContract.substr(0, kRegistrationPrefix.size()) ==
    kRegistrationPrefix);

}  // namespace
