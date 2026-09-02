// Copyright (c) 2026 Mindclade. All rights reserved.
// Proprietary and confidential. Unauthorized use, copying, or distribution is prohibited.

#ifndef MINDCLADE_NATIVE_STABLE_ABI_QUALIFIED_CAPABILITY_TABLE_H_
#define MINDCLADE_NATIVE_STABLE_ABI_QUALIFIED_CAPABILITY_TABLE_H_

#include <stddef.h>
#include <stdint.h>

#include "node_launch_abi.h"

#ifdef __cplusplus
extern "C" {
#endif

#define MINDCLADE_QUALIFIED_CAPABILITY_TABLE_ABI_VERSION UINT32_C(1)

typedef enum MindcladeCapabilityPhaseV1 {
  MINDCLADE_CAPABILITY_PHASE_FORWARD_V1 = 1,
  MINDCLADE_CAPABILITY_PHASE_BACKWARD_V1 = 2
} MindcladeCapabilityPhaseV1;

typedef enum MindcladeDeviceArchitectureV1 {
  MINDCLADE_DEVICE_ARCHITECTURE_UNKNOWN_V1 = 0,
  MINDCLADE_DEVICE_ARCHITECTURE_SM80_V1 = 1,
  MINDCLADE_DEVICE_ARCHITECTURE_SM90A_V1 = 2,
  MINDCLADE_DEVICE_ARCHITECTURE_SM100A_V1 = 3
} MindcladeDeviceArchitectureV1;

typedef int32_t (*MindcladeDeviceArchitectureProviderV1)(
    int32_t device_index,
    uint32_t* architecture);

typedef enum MindcladeCapabilityAttributeTypeV1 {
  MINDCLADE_CAPABILITY_ATTRIBUTE_BOOL_V1 = 1,
  MINDCLADE_CAPABILITY_ATTRIBUTE_INT64_V1 = 2,
  MINDCLADE_CAPABILITY_ATTRIBUTE_FLOAT64_V1 = 3,
  MINDCLADE_CAPABILITY_ATTRIBUTE_STRING_V1 = 4
} MindcladeCapabilityAttributeTypeV1;

typedef union MindcladeCapabilityAttributeValueV1 {
  uint64_t boolean_value;
  int64_t int64_value;
  double float64_value;
  const char* string_value;
} MindcladeCapabilityAttributeValueV1;

typedef struct MindcladeCapabilityAttributeV1 {
  const char* name;
  uint32_t type;
  uint32_t reserved;
  MindcladeCapabilityAttributeValueV1 value;
} MindcladeCapabilityAttributeV1;

typedef struct MindcladeCapabilityDimensionV1 {
  const char* name;
  int64_t value;
} MindcladeCapabilityDimensionV1;

typedef struct MindcladeQualifiedCapabilityRowV1 {
  const char* operation;
  uint32_t phase;
  const char* workload_digest;
  uint8_t specialization_digest[32];
  const char* capability_digest;
  const char* artifact_digest;
  const char* architecture;
  uint32_t dtype;
  const char* layout;
  const char* mode;
  const MindcladeCapabilityDimensionV1* dimensions;
  uint32_t dimension_count;
  const MindcladeCapabilityAttributeV1* attributes;
  uint32_t attribute_count;
  uint32_t specificity;
  int32_t priority;
  const MindcladeNodeAdapterV1* adapters;
  const char* const* adapter_symbols;
  uint32_t adapter_count;
} MindcladeQualifiedCapabilityRowV1;

typedef struct MindcladeCapabilityRequestV1 {
  const char* operation;
  uint32_t phase;
  const char* workload_digest;
  int32_t device_index;
  uint32_t dtype;
  const char* layout;
  const char* mode;
  const MindcladeCapabilityDimensionV1* dimensions;
  uint32_t dimension_count;
  const MindcladeCapabilityAttributeV1* attributes;
  uint32_t attribute_count;
  uint32_t require_atomic_backward;
} MindcladeCapabilityRequestV1;

typedef struct MindcladeNodeInvocationV1 {
  const MindcladeNodeValueV1* parameters;
  uint32_t parameter_count;
} MindcladeNodeInvocationV1;

typedef enum MindcladeCapabilityStatusV1 {
  MINDCLADE_CAPABILITY_STATUS_SUCCESS_V1 = 0,
  MINDCLADE_CAPABILITY_STATUS_INVALID_ARGUMENT_V1 = 1,
  MINDCLADE_CAPABILITY_STATUS_ARCHITECTURE_QUERY_FAILED_V1 = 2,
  MINDCLADE_CAPABILITY_STATUS_NO_MATCH_V1 = 3,
  MINDCLADE_CAPABILITY_STATUS_INCOMPLETE_TRAINING_PAIR_V1 = 4,
  MINDCLADE_CAPABILITY_STATUS_AMBIGUOUS_TABLE_V1 = 5,
  MINDCLADE_CAPABILITY_STATUS_ADAPTER_FAILURE_V1 = 6
} MindcladeCapabilityStatusV1;

size_t mindclade_qualified_capability_row_count_v1(void);
const MindcladeQualifiedCapabilityRowV1*
mindclade_qualified_capability_rows_v1(void);
const char* mindclade_qualified_capability_rows_digest_v1(void);
const char* mindclade_qualified_capability_table_digest_v1(void);

int32_t mindclade_select_qualified_capability_v1(
    const MindcladeQualifiedCapabilityRowV1* rows,
    size_t row_count,
    const MindcladeCapabilityRequestV1* request,
    MindcladeDeviceArchitectureProviderV1 architecture_provider,
    const MindcladeQualifiedCapabilityRowV1** selected);

int32_t mindclade_execute_qualified_capability_v1(
    const MindcladeQualifiedCapabilityRowV1* capability,
    const MindcladeNodeInvocationV1* invocations,
    size_t invocation_count,
    int32_t* adapter_status);

int32_t mindclade_canonical_workload_digest_v1(
    const char* operation,
    uint32_t canonicalization_version,
    const MindcladeCapabilityDimensionV1* dimensions,
    size_t dimension_count,
    uint32_t input_dtype,
    const char* layout,
    const char* mode,
    const MindcladeCapabilityAttributeV1* attributes,
    size_t attribute_count,
    char output_digest[72]);

#ifdef __cplusplus
}  // extern "C"
#endif

#endif  // MINDCLADE_NATIVE_STABLE_ABI_QUALIFIED_CAPABILITY_TABLE_H_
