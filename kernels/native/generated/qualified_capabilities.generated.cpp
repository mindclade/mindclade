// GENERATED FILE - DO NOT EDIT. Generator: kernels.native.codegen.generate@8.
#include <array>
#include <cstddef>
#include "../stable_abi/qualified_capability_table.h"

namespace {
[[maybe_unused]] constexpr MindcladeCapabilityAttributeV1 capability_bool(const char* name, bool value) {
  MindcladeCapabilityAttributeV1 result{}; result.name = name;
  result.type = MINDCLADE_CAPABILITY_ATTRIBUTE_BOOL_V1; result.value.boolean_value = value ? 1u : 0u; return result;
}
[[maybe_unused]] constexpr MindcladeCapabilityAttributeV1 capability_int64(const char* name, int64_t value) {
  MindcladeCapabilityAttributeV1 result{}; result.name = name;
  result.type = MINDCLADE_CAPABILITY_ATTRIBUTE_INT64_V1; result.value.int64_value = value; return result;
}
[[maybe_unused]] constexpr MindcladeCapabilityAttributeV1 capability_float64(const char* name, double value) {
  MindcladeCapabilityAttributeV1 result{}; result.name = name;
  result.type = MINDCLADE_CAPABILITY_ATTRIBUTE_FLOAT64_V1; result.value.float64_value = value; return result;
}
[[maybe_unused]] constexpr MindcladeCapabilityAttributeV1 capability_string(const char* name, const char* value) {
  MindcladeCapabilityAttributeV1 result{}; result.name = name;
  result.type = MINDCLADE_CAPABILITY_ATTRIBUTE_STRING_V1; result.value.string_value = value; return result;
}

}  // namespace

extern "C" std::size_t mindclade_qualified_capability_row_count_v1() {
  return 0;
}

extern "C" const MindcladeQualifiedCapabilityRowV1*
mindclade_qualified_capability_rows_v1() {
  return nullptr;
}

extern "C" const char* mindclade_qualified_capability_rows_digest_v1() {
  return "sha256:4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945";
}

extern "C" const char* mindclade_qualified_capability_table_digest_v1() {
  return "sha256:6291f881e4379215d7b2cdc92ba0f2763a4e9ddbc7801b292c136d99fd3dbc35";
}
