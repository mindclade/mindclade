// Copyright (c) 2026 Mindclade. All rights reserved.
// Proprietary and confidential. Unauthorized use, copying, or distribution is prohibited.

#ifndef MINDCLADE_NATIVE_STABLE_ABI_NODE_LAUNCH_ABI_H_
#define MINDCLADE_NATIVE_STABLE_ABI_NODE_LAUNCH_ABI_H_

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define MINDCLADE_NODE_LAUNCH_ABI_VERSION UINT32_C(1)
#define MINDCLADE_NODE_ANY_RANK_V1 INT32_C(-1)

#if defined(_MSC_VER)
#define MINDCLADE_NODE_ALIGN_8 __declspec(align(8))
#elif defined(__GNUC__) || defined(__clang__)
#define MINDCLADE_NODE_ALIGN_8 __attribute__((aligned(8)))
#else
#error "Mindclade node ABI requires an explicit 8-byte alignment spelling"
#endif

typedef enum MindcladeNodeValueKindV1 {
  MINDCLADE_NODE_VALUE_TENSOR_V1 = 1,
  MINDCLADE_NODE_VALUE_BOOL_V1 = 2,
  MINDCLADE_NODE_VALUE_INT64_V1 = 3,
  MINDCLADE_NODE_VALUE_FLOAT64_V1 = 4,
  MINDCLADE_NODE_VALUE_STREAM_V1 = 5
} MindcladeNodeValueKindV1;

typedef enum MindcladeNodeAccessV1 {
  MINDCLADE_NODE_ACCESS_READ_V1 = 1,
  MINDCLADE_NODE_ACCESS_WRITE_V1 = 2,
  MINDCLADE_NODE_ACCESS_READ_WRITE_V1 = 3
} MindcladeNodeAccessV1;

typedef enum MindcladeNodeDTypeV1 {
  MINDCLADE_NODE_DTYPE_FLOAT16_V1 = 1,
  MINDCLADE_NODE_DTYPE_BFLOAT16_V1 = 2,
  MINDCLADE_NODE_DTYPE_FLOAT32_V1 = 3,
  MINDCLADE_NODE_DTYPE_BOOL_V1 = 4,
  MINDCLADE_NODE_DTYPE_INT64_V1 = 5
} MindcladeNodeDTypeV1;

typedef enum MindcladeNodeStatusV1 {
  MINDCLADE_NODE_STATUS_SUCCESS_V1 = 0,
  MINDCLADE_NODE_STATUS_INVALID_ABI_V1 = 1,
  MINDCLADE_NODE_STATUS_INVALID_PARAMETER_COUNT_V1 = 2,
  MINDCLADE_NODE_STATUS_INVALID_PARAMETER_V1 = 3,
  MINDCLADE_NODE_STATUS_ENTRY_FAILURE_V1 = 4,
  MINDCLADE_NODE_STATUS_CUDA_FAILURE_V1 = 5
} MindcladeNodeStatusV1;

enum {
  MINDCLADE_NODE_TENSOR_PRESENT_V1 = 1u << 0,
  MINDCLADE_NODE_TENSOR_OPTIONAL_V1 = 1u << 1
};

enum {
  MINDCLADE_NODE_CONTRACT_OPTIONAL_V1 = 1u << 0,
  MINDCLADE_NODE_CONTRACT_WORKSPACE_V1 = 1u << 1
};

typedef struct MINDCLADE_NODE_ALIGN_8 MindcladeNodeTensorV1 {
  void* data;
  const int64_t* sizes;
  const int64_t* strides;
  int32_t rank;
  int32_t dtype;
  int32_t device_index;
  uint32_t flags;
} MindcladeNodeTensorV1;

typedef union MINDCLADE_NODE_ALIGN_8 MindcladeNodePayloadV1 {
  MindcladeNodeTensorV1 tensor;
  uint64_t boolean_value;
  int64_t int64_value;
  double float64_value;
  void* stream;
} MindcladeNodePayloadV1;

typedef struct MINDCLADE_NODE_ALIGN_8 MindcladeNodeValueV1 {
  uint32_t kind;
  uint32_t access;
  MindcladeNodePayloadV1 payload;
} MindcladeNodeValueV1;

typedef struct MINDCLADE_NODE_ALIGN_8 MindcladeNodeLaunchV1 {
  uint32_t abi_version;
  uint32_t parameter_count;
  uint8_t specialization_digest[32];
  const MindcladeNodeValueV1* parameters;
} MindcladeNodeLaunchV1;

typedef struct MINDCLADE_NODE_ALIGN_8 MindcladeNodeParameterContractV1 {
  uint32_t kind;
  uint32_t access;
  int32_t rank;
  uint32_t flags;
} MindcladeNodeParameterContractV1;

typedef struct MINDCLADE_NODE_ALIGN_8 MindcladeNodeLaunchContractV1 {
  uint32_t parameter_count;
  uint32_t reserved;
  uint8_t specialization_digest[32];
  const MindcladeNodeParameterContractV1* parameters;
} MindcladeNodeLaunchContractV1;

typedef int32_t (*MindcladeNodeAdapterV1)(
    const MindcladeNodeLaunchV1* launch);

int32_t mindclade_validate_node_launch_v1(
    const MindcladeNodeLaunchV1* launch);

int32_t mindclade_validate_node_launch_contract_v1(
    const MindcladeNodeLaunchV1* launch,
    const MindcladeNodeLaunchContractV1* contract);

#ifdef __cplusplus
}  // extern "C"

static_assert(sizeof(void*) == 8, "Mindclade node ABI requires 64-bit pointers");
static_assert(sizeof(MindcladeNodeTensorV1) == 40, "unexpected tensor ABI layout");
static_assert(sizeof(MindcladeNodeValueV1) == 48, "unexpected value ABI layout");
static_assert(sizeof(MindcladeNodeLaunchV1) == 48, "unexpected launch ABI layout");
static_assert(sizeof(MindcladeNodeParameterContractV1) == 16,
              "unexpected parameter contract ABI layout");
static_assert(sizeof(MindcladeNodeLaunchContractV1) == 48,
              "unexpected launch contract ABI layout");
static_assert(offsetof(MindcladeNodeLaunchV1, specialization_digest) == 8,
              "unexpected specialization digest offset");
static_assert(offsetof(MindcladeNodeLaunchV1, parameters) == 40,
              "unexpected parameter pointer offset");
static_assert(alignof(MindcladeNodeTensorV1) == 8, "unexpected tensor ABI alignment");
static_assert(alignof(MindcladeNodeValueV1) == 8, "unexpected value ABI alignment");
static_assert(alignof(MindcladeNodeLaunchV1) == 8, "unexpected launch ABI alignment");
static_assert(alignof(MindcladeNodeParameterContractV1) == 8,
              "unexpected parameter contract ABI alignment");
static_assert(alignof(MindcladeNodeLaunchContractV1) == 8,
              "unexpected launch contract ABI alignment");
#elif defined(__STDC_VERSION__) && __STDC_VERSION__ >= 201112L
_Static_assert(sizeof(void*) == 8, "Mindclade node ABI requires 64-bit pointers");
_Static_assert(sizeof(MindcladeNodeTensorV1) == 40, "unexpected tensor ABI layout");
_Static_assert(sizeof(MindcladeNodeValueV1) == 48, "unexpected value ABI layout");
_Static_assert(sizeof(MindcladeNodeLaunchV1) == 48, "unexpected launch ABI layout");
_Static_assert(sizeof(MindcladeNodeParameterContractV1) == 16,
               "unexpected parameter contract ABI layout");
_Static_assert(sizeof(MindcladeNodeLaunchContractV1) == 48,
               "unexpected launch contract ABI layout");
_Static_assert(offsetof(MindcladeNodeLaunchV1, specialization_digest) == 8,
               "unexpected specialization digest offset");
_Static_assert(offsetof(MindcladeNodeLaunchV1, parameters) == 40,
               "unexpected parameter pointer offset");
_Static_assert(_Alignof(MindcladeNodeTensorV1) == 8, "unexpected tensor ABI alignment");
_Static_assert(_Alignof(MindcladeNodeValueV1) == 8, "unexpected value ABI alignment");
_Static_assert(_Alignof(MindcladeNodeLaunchV1) == 8, "unexpected launch ABI alignment");
_Static_assert(_Alignof(MindcladeNodeParameterContractV1) == 8,
               "unexpected parameter contract ABI alignment");
_Static_assert(_Alignof(MindcladeNodeLaunchContractV1) == 8,
               "unexpected launch contract ABI alignment");
#endif

#undef MINDCLADE_NODE_ALIGN_8

#endif  // MINDCLADE_NATIVE_STABLE_ABI_NODE_LAUNCH_ABI_H_
