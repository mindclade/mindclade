// Copyright (c) 2026 Mindclade. All rights reserved.
// Proprietary and confidential. Unauthorized use, copying, or distribution is prohibited.

#include "qualified_capability_table.h"

#include <algorithm>
#include <array>
#include <charconv>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <limits>
#include <string>
#include <string_view>
#include <vector>

namespace {

constexpr std::size_t kSha256Bytes = 32;
constexpr std::size_t kDigestTextBytes = 71;

bool valid_text(const char* value) noexcept {
  return value != nullptr && value[0] != '\0';
}

bool valid_digest(const char* value) noexcept {
  if (value == nullptr || std::strlen(value) != kDigestTextBytes ||
      std::strncmp(value, "sha256:", 7) != 0) {
    return false;
  }
  for (std::size_t index = 7; index < kDigestTextBytes; ++index) {
    if (!((value[index] >= '0' && value[index] <= '9') ||
          (value[index] >= 'a' && value[index] <= 'f'))) {
      return false;
    }
  }
  return true;
}

const char* architecture_name(std::uint32_t architecture) noexcept {
  switch (architecture) {
    case MINDCLADE_DEVICE_ARCHITECTURE_SM80_V1:
      return "sm80";
    case MINDCLADE_DEVICE_ARCHITECTURE_SM90A_V1:
      return "sm90a";
    case MINDCLADE_DEVICE_ARCHITECTURE_SM100A_V1:
      return "sm100a";
    default:
      return nullptr;
  }
}

const char* dtype_name(std::uint32_t dtype) noexcept {
  switch (dtype) {
    case MINDCLADE_NODE_DTYPE_FLOAT16_V1:
      return "float16";
    case MINDCLADE_NODE_DTYPE_BFLOAT16_V1:
      return "bfloat16";
    case MINDCLADE_NODE_DTYPE_FLOAT32_V1:
      return "float32";
    case MINDCLADE_NODE_DTYPE_BOOL_V1:
      return "bool";
    case MINDCLADE_NODE_DTYPE_INT64_V1:
      return "int64";
    default:
      return nullptr;
  }
}

const char* attribute_type_name(std::uint32_t type) noexcept {
  switch (type) {
    case MINDCLADE_CAPABILITY_ATTRIBUTE_BOOL_V1:
      return "bool";
    case MINDCLADE_CAPABILITY_ATTRIBUTE_INT64_V1:
      return "int64";
    case MINDCLADE_CAPABILITY_ATTRIBUTE_FLOAT64_V1:
      return "float64";
    case MINDCLADE_CAPABILITY_ATTRIBUTE_STRING_V1:
      return "string";
    default:
      return nullptr;
  }
}

void append_json_string(std::string& output, const char* value) {
  output.push_back('"');
  for (const unsigned char character : std::string_view(value)) {
    switch (character) {
      case '"': output += "\\\""; break;
      case '\\': output += "\\\\"; break;
      case '\b': output += "\\b"; break;
      case '\f': output += "\\f"; break;
      case '\n': output += "\\n"; break;
      case '\r': output += "\\r"; break;
      case '\t': output += "\\t"; break;
      default:
        if (character < 0x20u) {
          constexpr char kHex[] = "0123456789abcdef";
          output += "\\u00";
          output.push_back(kHex[character >> 4u]);
          output.push_back(kHex[character & 0x0fu]);
        } else {
          output.push_back(static_cast<char>(character));
        }
    }
  }
  output.push_back('"');
}

bool append_json_float(std::string& output, double value) {
  if (!std::isfinite(value)) {
    return false;
  }
  std::array<char, 64> buffer{};
  const auto rendered = std::to_chars(
      buffer.data(), buffer.data() + buffer.size(), value,
      std::chars_format::general);
  if (rendered.ec != std::errc{}) {
    return false;
  }
  std::string text(buffer.data(), rendered.ptr);
  if (text.find_first_of(".eE") == std::string::npos) {
    text += ".0";
  }
  output += text;
  return true;
}

std::array<std::uint8_t, kSha256Bytes> sha256(std::string_view input) {
  constexpr std::array<std::uint32_t, 64> constants{
      0x428a2f98u,0x71374491u,0xb5c0fbcfu,0xe9b5dba5u,0x3956c25bu,0x59f111f1u,0x923f82a4u,0xab1c5ed5u,
      0xd807aa98u,0x12835b01u,0x243185beu,0x550c7dc3u,0x72be5d74u,0x80deb1feu,0x9bdc06a7u,0xc19bf174u,
      0xe49b69c1u,0xefbe4786u,0x0fc19dc6u,0x240ca1ccu,0x2de92c6fu,0x4a7484aau,0x5cb0a9dcu,0x76f988dau,
      0x983e5152u,0xa831c66du,0xb00327c8u,0xbf597fc7u,0xc6e00bf3u,0xd5a79147u,0x06ca6351u,0x14292967u,
      0x27b70a85u,0x2e1b2138u,0x4d2c6dfcu,0x53380d13u,0x650a7354u,0x766a0abbu,0x81c2c92eu,0x92722c85u,
      0xa2bfe8a1u,0xa81a664bu,0xc24b8b70u,0xc76c51a3u,0xd192e819u,0xd6990624u,0xf40e3585u,0x106aa070u,
      0x19a4c116u,0x1e376c08u,0x2748774cu,0x34b0bcb5u,0x391c0cb3u,0x4ed8aa4au,0x5b9cca4fu,0x682e6ff3u,
      0x748f82eeu,0x78a5636fu,0x84c87814u,0x8cc70208u,0x90befffau,0xa4506cebu,0xbef9a3f7u,0xc67178f2u};
  std::vector<std::uint8_t> message(input.begin(), input.end());
  const std::uint64_t bit_length = static_cast<std::uint64_t>(message.size()) * 8u;
  message.push_back(0x80u);
  while (message.size() % 64u != 56u) {
    message.push_back(0u);
  }
  for (int shift = 56; shift >= 0; shift -= 8) {
    message.push_back(static_cast<std::uint8_t>(bit_length >> shift));
  }
  std::array<std::uint32_t, 8> state{
      0x6a09e667u,0xbb67ae85u,0x3c6ef372u,0xa54ff53au,
      0x510e527fu,0x9b05688cu,0x1f83d9abu,0x5be0cd19u};
  const auto rotate = [](std::uint32_t value, unsigned bits) {
    return (value >> bits) | (value << (32u - bits));
  };
  for (std::size_t offset = 0; offset < message.size(); offset += 64u) {
    std::array<std::uint32_t, 64> words{};
    for (std::size_t index = 0; index < 16u; ++index) {
      const std::size_t base = offset + index * 4u;
      words[index] = (static_cast<std::uint32_t>(message[base]) << 24u) |
                     (static_cast<std::uint32_t>(message[base + 1u]) << 16u) |
                     (static_cast<std::uint32_t>(message[base + 2u]) << 8u) |
                     static_cast<std::uint32_t>(message[base + 3u]);
    }
    for (std::size_t index = 16u; index < 64u; ++index) {
      const std::uint32_t s0 = rotate(words[index - 15u], 7u) ^
          rotate(words[index - 15u], 18u) ^ (words[index - 15u] >> 3u);
      const std::uint32_t s1 = rotate(words[index - 2u], 17u) ^
          rotate(words[index - 2u], 19u) ^ (words[index - 2u] >> 10u);
      words[index] = words[index - 16u] + s0 + words[index - 7u] + s1;
    }
    std::uint32_t a=state[0], b=state[1], c=state[2], d=state[3];
    std::uint32_t e=state[4], f=state[5], g=state[6], h=state[7];
    for (std::size_t index = 0; index < 64u; ++index) {
      const std::uint32_t s1 = rotate(e, 6u) ^ rotate(e, 11u) ^ rotate(e, 25u);
      const std::uint32_t choice = (e & f) ^ ((~e) & g);
      const std::uint32_t first = h + s1 + choice + constants[index] + words[index];
      const std::uint32_t s0 = rotate(a, 2u) ^ rotate(a, 13u) ^ rotate(a, 22u);
      const std::uint32_t majority = (a & b) ^ (a & c) ^ (b & c);
      const std::uint32_t second = s0 + majority;
      h=g; g=f; f=e; e=d+first; d=c; c=b; b=a; a=first+second;
    }
    state[0]+=a; state[1]+=b; state[2]+=c; state[3]+=d;
    state[4]+=e; state[5]+=f; state[6]+=g; state[7]+=h;
  }
  std::array<std::uint8_t, kSha256Bytes> digest{};
  for (std::size_t index = 0; index < state.size(); ++index) {
    digest[index*4u] = static_cast<std::uint8_t>(state[index] >> 24u);
    digest[index*4u+1u] = static_cast<std::uint8_t>(state[index] >> 16u);
    digest[index*4u+2u] = static_cast<std::uint8_t>(state[index] >> 8u);
    digest[index*4u+3u] = static_cast<std::uint8_t>(state[index]);
  }
  return digest;
}

bool ordered_dimensions(
    const MindcladeCapabilityDimensionV1* values,
    std::size_t count) noexcept {
  if (count == 0 || values == nullptr) return false;
  for (std::size_t index = 0; index < count; ++index) {
    if (!valid_text(values[index].name) || values[index].value < 0) return false;
    if (index != 0 && std::strcmp(values[index - 1u].name, values[index].name) >= 0) return false;
  }
  return true;
}

bool ordered_attributes(
    const MindcladeCapabilityAttributeV1* values,
    std::size_t count) noexcept {
  if (count != 0 && values == nullptr) return false;
  for (std::size_t index = 0; index < count; ++index) {
    const auto& value = values[index];
    if (!valid_text(value.name) || value.reserved != 0u) return false;
    if (index != 0 && std::strcmp(values[index - 1u].name, value.name) >= 0) return false;
    if (attribute_type_name(value.type) == nullptr) return false;
    if (value.type == MINDCLADE_CAPABILITY_ATTRIBUTE_BOOL_V1 && value.value.boolean_value > 1u) return false;
    if (value.type == MINDCLADE_CAPABILITY_ATTRIBUTE_FLOAT64_V1 && !std::isfinite(value.value.float64_value)) return false;
    if (value.type == MINDCLADE_CAPABILITY_ATTRIBUTE_STRING_V1 && value.value.string_value == nullptr) return false;
  }
  return true;
}

bool names_disjoint(
    const MindcladeCapabilityDimensionV1* dimensions,
    std::size_t dimension_count,
    const MindcladeCapabilityAttributeV1* attributes,
    std::size_t attribute_count) noexcept {
  for (std::size_t dimension = 0; dimension < dimension_count; ++dimension) {
    for (std::size_t attribute = 0; attribute < attribute_count; ++attribute) {
      if (std::strcmp(dimensions[dimension].name, attributes[attribute].name) == 0) return false;
    }
  }
  return true;
}

bool same_dimensions(
    const MindcladeCapabilityDimensionV1* lhs, std::size_t lhs_count,
    const MindcladeCapabilityDimensionV1* rhs, std::size_t rhs_count) noexcept {
  if (lhs_count != rhs_count) return false;
  for (std::size_t index = 0; index < lhs_count; ++index) {
    if (std::strcmp(lhs[index].name, rhs[index].name) != 0 ||
        lhs[index].value != rhs[index].value) return false;
  }
  return true;
}

bool same_attributes(
    const MindcladeCapabilityAttributeV1* lhs, std::size_t lhs_count,
    const MindcladeCapabilityAttributeV1* rhs, std::size_t rhs_count) noexcept {
  if (lhs_count != rhs_count) return false;
  for (std::size_t index = 0; index < lhs_count; ++index) {
    if (std::strcmp(lhs[index].name, rhs[index].name) != 0 || lhs[index].type != rhs[index].type) return false;
    switch (lhs[index].type) {
      case MINDCLADE_CAPABILITY_ATTRIBUTE_BOOL_V1:
        if (lhs[index].value.boolean_value != rhs[index].value.boolean_value) return false;
        break;
      case MINDCLADE_CAPABILITY_ATTRIBUTE_INT64_V1:
        if (lhs[index].value.int64_value != rhs[index].value.int64_value) return false;
        break;
      case MINDCLADE_CAPABILITY_ATTRIBUTE_FLOAT64_V1:
        if (lhs[index].value.float64_value != rhs[index].value.float64_value) return false;
        break;
      case MINDCLADE_CAPABILITY_ATTRIBUTE_STRING_V1:
        if (std::strcmp(lhs[index].value.string_value, rhs[index].value.string_value) != 0) return false;
        break;
      default:
        return false;
    }
  }
  return true;
}

bool valid_row(const MindcladeQualifiedCapabilityRowV1& row) noexcept {
  return valid_text(row.operation) &&
      (row.phase == MINDCLADE_CAPABILITY_PHASE_FORWARD_V1 ||
       row.phase == MINDCLADE_CAPABILITY_PHASE_BACKWARD_V1) &&
      valid_digest(row.workload_digest) && valid_digest(row.capability_digest) &&
      valid_digest(row.artifact_digest) && architecture_name(
          std::strcmp(row.architecture == nullptr ? "" : row.architecture, "sm80") == 0
              ? MINDCLADE_DEVICE_ARCHITECTURE_SM80_V1
              : std::strcmp(row.architecture == nullptr ? "" : row.architecture, "sm90a") == 0
                    ? MINDCLADE_DEVICE_ARCHITECTURE_SM90A_V1
                    : std::strcmp(row.architecture == nullptr ? "" : row.architecture, "sm100a") == 0
                          ? MINDCLADE_DEVICE_ARCHITECTURE_SM100A_V1
                          : MINDCLADE_DEVICE_ARCHITECTURE_UNKNOWN_V1) != nullptr &&
      dtype_name(row.dtype) != nullptr && valid_text(row.layout) && valid_text(row.mode) &&
      ordered_dimensions(row.dimensions, row.dimension_count) &&
      ordered_attributes(row.attributes, row.attribute_count) &&
      names_disjoint(row.dimensions, row.dimension_count, row.attributes, row.attribute_count) &&
      row.specificity == row.dimension_count + row.attribute_count &&
      row.adapter_count != 0u && row.adapters != nullptr && row.adapter_symbols != nullptr;
}

bool row_matches(
    const MindcladeQualifiedCapabilityRowV1& row,
    const MindcladeCapabilityRequestV1& request,
    const char* architecture) noexcept {
  return row.phase == request.phase && std::strcmp(row.operation, request.operation) == 0 &&
      std::strcmp(row.workload_digest, request.workload_digest) == 0 &&
      std::strcmp(row.architecture, architecture) == 0 && row.dtype == request.dtype &&
      std::strcmp(row.layout, request.layout) == 0 && std::strcmp(row.mode, request.mode) == 0 &&
      same_dimensions(row.dimensions, row.dimension_count, request.dimensions, request.dimension_count) &&
      same_attributes(row.attributes, row.attribute_count, request.attributes, request.attribute_count);
}

bool same_pair_identity(
    const MindcladeQualifiedCapabilityRowV1& lhs,
    const MindcladeQualifiedCapabilityRowV1& rhs) noexcept {
  return std::strcmp(lhs.operation, rhs.operation) == 0 &&
      std::strcmp(lhs.workload_digest, rhs.workload_digest) == 0 &&
      std::memcmp(lhs.specialization_digest, rhs.specialization_digest, kSha256Bytes) == 0 &&
      std::strcmp(lhs.capability_digest, rhs.capability_digest) == 0 &&
      std::strcmp(lhs.architecture, rhs.architecture) == 0 && lhs.dtype == rhs.dtype &&
      std::strcmp(lhs.layout, rhs.layout) == 0 && std::strcmp(lhs.mode, rhs.mode) == 0 &&
      lhs.specificity == rhs.specificity && lhs.priority == rhs.priority &&
      same_dimensions(lhs.dimensions, lhs.dimension_count, rhs.dimensions, rhs.dimension_count) &&
      same_attributes(lhs.attributes, lhs.attribute_count, rhs.attributes, rhs.attribute_count);
}

bool preferred(
    const MindcladeQualifiedCapabilityRowV1& candidate,
    const MindcladeQualifiedCapabilityRowV1& selected) noexcept {
  if (candidate.specificity != selected.specificity) return candidate.specificity > selected.specificity;
  if (candidate.priority != selected.priority) return candidate.priority > selected.priority;
  return std::strcmp(candidate.capability_digest, selected.capability_digest) < 0;
}

}  // namespace

extern "C" int32_t mindclade_canonical_workload_digest_v1(
    const char* operation,
    uint32_t canonicalization_version,
    const MindcladeCapabilityDimensionV1* dimensions,
    size_t dimension_count,
    uint32_t input_dtype,
    const char* layout,
    const char* mode,
    const MindcladeCapabilityAttributeV1* attributes,
    size_t attribute_count,
    char output_digest[72]) {
  if (!valid_text(operation) || canonicalization_version != 1u ||
      dtype_name(input_dtype) == nullptr || !valid_text(layout) || !valid_text(mode) ||
      output_digest == nullptr || !ordered_dimensions(dimensions, dimension_count) ||
      !ordered_attributes(attributes, attribute_count) ||
      !names_disjoint(dimensions, dimension_count, attributes, attribute_count)) {
    return MINDCLADE_CAPABILITY_STATUS_INVALID_ARGUMENT_V1;
  }
  std::string canonical{"{\"attributes\":["};
  for (std::size_t index = 0; index < attribute_count; ++index) {
    if (index != 0) canonical.push_back(',');
    canonical += "{\"name\":";
    append_json_string(canonical, attributes[index].name);
    canonical += ",\"type\":";
    append_json_string(canonical, attribute_type_name(attributes[index].type));
    canonical += ",\"value\":";
    switch (attributes[index].type) {
      case MINDCLADE_CAPABILITY_ATTRIBUTE_BOOL_V1:
        canonical += attributes[index].value.boolean_value != 0u ? "true" : "false";
        break;
      case MINDCLADE_CAPABILITY_ATTRIBUTE_INT64_V1:
        canonical += std::to_string(attributes[index].value.int64_value);
        break;
      case MINDCLADE_CAPABILITY_ATTRIBUTE_FLOAT64_V1:
        if (!append_json_float(canonical, attributes[index].value.float64_value)) {
          return MINDCLADE_CAPABILITY_STATUS_INVALID_ARGUMENT_V1;
        }
        break;
      case MINDCLADE_CAPABILITY_ATTRIBUTE_STRING_V1:
        append_json_string(canonical, attributes[index].value.string_value);
        break;
      default:
        return MINDCLADE_CAPABILITY_STATUS_INVALID_ARGUMENT_V1;
    }
    canonical.push_back('}');
  }
  canonical += "],\"canonicalization_version\":" + std::to_string(canonicalization_version);
  canonical += ",\"dimensions\":[";
  for (std::size_t index = 0; index < dimension_count; ++index) {
    if (index != 0) canonical.push_back(',');
    canonical += "{\"name\":";
    append_json_string(canonical, dimensions[index].name);
    canonical += ",\"value\":" + std::to_string(dimensions[index].value) + "}";
  }
  canonical += "],\"input_dtype\":";
  append_json_string(canonical, dtype_name(input_dtype));
  canonical += ",\"layout\":";
  append_json_string(canonical, layout);
  canonical += ",\"mode\":";
  append_json_string(canonical, mode);
  canonical += ",\"operation\":";
  append_json_string(canonical, operation);
  canonical.push_back('}');
  const auto digest = sha256(canonical);
  constexpr char hex[] = "0123456789abcdef";
  std::memcpy(output_digest, "sha256:", 7u);
  for (std::size_t index = 0; index < digest.size(); ++index) {
    output_digest[7u + index * 2u] = hex[digest[index] >> 4u];
    output_digest[8u + index * 2u] = hex[digest[index] & 0x0fu];
  }
  output_digest[kDigestTextBytes] = '\0';
  return MINDCLADE_CAPABILITY_STATUS_SUCCESS_V1;
}

extern "C" int32_t mindclade_select_qualified_capability_v1(
    const MindcladeQualifiedCapabilityRowV1* rows,
    size_t row_count,
    const MindcladeCapabilityRequestV1* request,
    MindcladeDeviceArchitectureProviderV1 architecture_provider,
    const MindcladeQualifiedCapabilityRowV1** selected) {
  if (rows == nullptr || row_count == 0 || request == nullptr || selected == nullptr ||
      architecture_provider == nullptr || !valid_text(request->operation) ||
      !valid_digest(request->workload_digest) || !valid_text(request->layout) ||
      !valid_text(request->mode) || dtype_name(request->dtype) == nullptr ||
      !ordered_dimensions(request->dimensions, request->dimension_count) ||
      !ordered_attributes(request->attributes, request->attribute_count) ||
      !names_disjoint(request->dimensions, request->dimension_count,
                      request->attributes, request->attribute_count) ||
      (request->phase != MINDCLADE_CAPABILITY_PHASE_FORWARD_V1 &&
       request->phase != MINDCLADE_CAPABILITY_PHASE_BACKWARD_V1) ||
      request->require_atomic_backward > 1u) {
    return MINDCLADE_CAPABILITY_STATUS_INVALID_ARGUMENT_V1;
  }
  *selected = nullptr;
  for (std::size_t index = 0; index < row_count; ++index) {
    if (!valid_row(rows[index])) return MINDCLADE_CAPABILITY_STATUS_INVALID_ARGUMENT_V1;
  }
  std::uint32_t architecture = MINDCLADE_DEVICE_ARCHITECTURE_UNKNOWN_V1;
  if (architecture_provider(request->device_index, &architecture) != 0) {
    return MINDCLADE_CAPABILITY_STATUS_ARCHITECTURE_QUERY_FAILED_V1;
  }
  const char* architecture_text = architecture_name(architecture);
  if (architecture_text == nullptr) return MINDCLADE_CAPABILITY_STATUS_ARCHITECTURE_QUERY_FAILED_V1;
  const MindcladeQualifiedCapabilityRowV1* best = nullptr;
  for (std::size_t index = 0; index < row_count; ++index) {
    if (row_matches(rows[index], *request, architecture_text) &&
        (best == nullptr || preferred(rows[index], *best))) {
      best = &rows[index];
    }
  }
  if (best == nullptr) return MINDCLADE_CAPABILITY_STATUS_NO_MATCH_V1;
  std::size_t identical = 0;
  for (std::size_t index = 0; index < row_count; ++index) {
    if (row_matches(rows[index], *request, architecture_text) &&
        rows[index].specificity == best->specificity && rows[index].priority == best->priority &&
        std::strcmp(rows[index].capability_digest, best->capability_digest) == 0) ++identical;
  }
  if (identical != 1u) return MINDCLADE_CAPABILITY_STATUS_AMBIGUOUS_TABLE_V1;
  if (request->require_atomic_backward != 0u) {
    const std::uint32_t opposite = request->phase == MINDCLADE_CAPABILITY_PHASE_FORWARD_V1
        ? MINDCLADE_CAPABILITY_PHASE_BACKWARD_V1
        : MINDCLADE_CAPABILITY_PHASE_FORWARD_V1;
    std::size_t pairs = 0;
    for (std::size_t index = 0; index < row_count; ++index) {
      if (rows[index].phase == opposite && same_pair_identity(*best, rows[index])) ++pairs;
    }
    if (pairs == 0u) return MINDCLADE_CAPABILITY_STATUS_INCOMPLETE_TRAINING_PAIR_V1;
    if (pairs != 1u) return MINDCLADE_CAPABILITY_STATUS_AMBIGUOUS_TABLE_V1;
  }
  *selected = best;
  return MINDCLADE_CAPABILITY_STATUS_SUCCESS_V1;
}

extern "C" int32_t mindclade_execute_qualified_capability_v1(
    const MindcladeQualifiedCapabilityRowV1* capability,
    const MindcladeNodeInvocationV1* invocations,
    size_t invocation_count,
    int32_t* adapter_status) {
  if (capability == nullptr || invocations == nullptr || adapter_status == nullptr ||
      !valid_row(*capability) || invocation_count != capability->adapter_count) {
    return MINDCLADE_CAPABILITY_STATUS_INVALID_ARGUMENT_V1;
  }
  *adapter_status = MINDCLADE_NODE_STATUS_SUCCESS_V1;
  for (std::size_t index = 0; index < invocation_count; ++index) {
    if ((invocations[index].parameter_count != 0u && invocations[index].parameters == nullptr) ||
        capability->adapters[index] == nullptr || !valid_text(capability->adapter_symbols[index])) {
      return MINDCLADE_CAPABILITY_STATUS_INVALID_ARGUMENT_V1;
    }
    MindcladeNodeLaunchV1 launch{};
    launch.abi_version = MINDCLADE_NODE_LAUNCH_ABI_VERSION;
    launch.parameter_count = invocations[index].parameter_count;
    std::memcpy(launch.specialization_digest, capability->specialization_digest, kSha256Bytes);
    launch.parameters = invocations[index].parameters;
    const std::int32_t status = capability->adapters[index](&launch);
    if (status != MINDCLADE_NODE_STATUS_SUCCESS_V1) {
      *adapter_status = status;
      return MINDCLADE_CAPABILITY_STATUS_ADAPTER_FAILURE_V1;
    }
  }
  return MINDCLADE_CAPABILITY_STATUS_SUCCESS_V1;
}
