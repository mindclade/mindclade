// Copyright (c) 2026 Mindclade. All rights reserved.
// Proprietary and confidential. Unauthorized use, copying, or distribution is prohibited.

#include <array>
#include <string_view>

namespace {

constexpr std::string_view kDispatcherNamespace{"mindclade"};
constexpr std::string_view kRegistrationContract{
    "torch.ops.mindclade.<name>"};
constexpr std::string_view kRegistrationPrefix{"torch.ops.mindclade."};
constexpr std::array<std::string_view, 0> kQualifiedOperations{};

static_assert(kDispatcherNamespace == "mindclade");
static_assert(
    kRegistrationContract.substr(0, kRegistrationPrefix.size()) ==
    kRegistrationPrefix);
static_assert(kQualifiedOperations.empty());

}  // namespace
