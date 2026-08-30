# Copyright (c) 2026 Mindclade. All rights reserved.
# Proprietary and confidential. Unauthorized use, copying, or distribution is prohibited.

if(NOT MINDCLADE_NATIVE_ENABLE_GPU)
  return()
endif()

if("${MINDCLADE_NATIVE_GPU_QUALIFICATION_MANIFEST}" STREQUAL "")
  message(FATAL_ERROR "GPU enablement requires a qualification manifest")
endif()
if("${MINDCLADE_NATIVE_GPU_QUALIFICATION_SHA256}" STREQUAL "")
  message(FATAL_ERROR "GPU enablement requires the qualification manifest digest")
endif()
if("${MINDCLADE_NATIVE_GPU_ARTIFACT}" STREQUAL "")
  message(FATAL_ERROR "GPU enablement requires an immutable GPU artifact")
endif()
if("${MINDCLADE_NATIVE_GPU_ARTIFACT_SHA256}" STREQUAL "")
  message(FATAL_ERROR "GPU enablement requires the GPU artifact digest")
endif()

if(NOT EXISTS "${MINDCLADE_NATIVE_GPU_QUALIFICATION_MANIFEST}")
  message(FATAL_ERROR "GPU qualification manifest does not exist")
endif()
if(NOT EXISTS "${MINDCLADE_NATIVE_GPU_ARTIFACT}")
  message(FATAL_ERROR "GPU artifact does not exist")
endif()

foreach(
  _digest_variable
  IN ITEMS
    MINDCLADE_NATIVE_GPU_QUALIFICATION_SHA256
    MINDCLADE_NATIVE_GPU_ARTIFACT_SHA256
)
  if(NOT "${${_digest_variable}}" MATCHES "^sha256:[0-9a-f]{64}$")
    message(
      FATAL_ERROR
      "${_digest_variable} must use sha256:<64 lowercase hex>"
    )
  endif()
endforeach()

file(
  SHA256
  "${MINDCLADE_NATIVE_GPU_QUALIFICATION_MANIFEST}"
  _qualification_manifest_actual_sha256
)
string(
  REGEX REPLACE
  "^sha256:"
  ""
  _qualification_manifest_expected_sha256
  "${MINDCLADE_NATIVE_GPU_QUALIFICATION_SHA256}"
)
if(
  NOT _qualification_manifest_actual_sha256
  STREQUAL _qualification_manifest_expected_sha256
)
  message(FATAL_ERROR "GPU qualification manifest digest mismatch")
endif()

file(READ "${MINDCLADE_NATIVE_GPU_QUALIFICATION_MANIFEST}" _qualification_json)

string(
  JSON _operator_namespace
  ERROR_VARIABLE _operator_namespace_error
  GET "${_qualification_json}" operator_namespace
)
if(
  NOT _operator_namespace_error STREQUAL "NOTFOUND"
  OR NOT _operator_namespace STREQUAL "mindclade"
)
  message(
    FATAL_ERROR
    "GPU qualification must bind the mindclade dispatcher namespace"
  )
endif()

string(
  JSON _registration_contract
  ERROR_VARIABLE _registration_contract_error
  GET "${_qualification_json}" registration_contract
)
if(
  NOT _registration_contract_error STREQUAL "NOTFOUND"
  OR NOT _registration_contract STREQUAL "torch.ops.mindclade.<name>"
)
  message(
    FATAL_ERROR
    "GPU qualification must bind torch.ops.mindclade.<name>"
  )
endif()

string(
  JSON _qualified_operation_count
  ERROR_VARIABLE _qualified_operation_error
  LENGTH "${_qualification_json}" qualified_operations
)
if(
  NOT _qualified_operation_error STREQUAL "NOTFOUND"
  OR NOT _qualified_operation_count GREATER 0
)
  message(
    FATAL_ERROR
    "GPU enablement requires at least one qualified operation; "
    "the repository manifest currently has zero"
  )
endif()

file(SHA256 "${MINDCLADE_NATIVE_GPU_ARTIFACT}" _gpu_artifact_actual_sha256)
string(
  REGEX REPLACE
  "^sha256:"
  ""
  _gpu_artifact_expected_sha256
  "${MINDCLADE_NATIVE_GPU_ARTIFACT_SHA256}"
)
if(NOT _gpu_artifact_actual_sha256 STREQUAL _gpu_artifact_expected_sha256)
  message(FATAL_ERROR "GPU artifact digest mismatch")
endif()

add_library(mindclade_native_cuda_registry OBJECT operation_registry.cpp)
mindclade_apply_native_target_policy(mindclade_native_cuda_registry)

add_library(mindclade_native_gpu_artifact SHARED IMPORTED GLOBAL)
set_target_properties(
  mindclade_native_gpu_artifact
  PROPERTIES IMPORTED_LOCATION "${MINDCLADE_NATIVE_GPU_ARTIFACT}"
)

target_sources(
  mindclade_native_schema
  PRIVATE $<TARGET_OBJECTS:mindclade_native_cuda_registry>
)
target_link_libraries(
  mindclade_native_schema
  PRIVATE mindclade_native_gpu_artifact
)
