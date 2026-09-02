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
    "an empty qualification inventory cannot activate CUDA dispatch"
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

string(
  JSON _qualified_artifact_sha256
  ERROR_VARIABLE _qualified_artifact_sha256_error
  GET "${_qualification_json}" artifact_sha256
)
if(
  NOT _qualified_artifact_sha256_error STREQUAL "NOTFOUND"
  OR NOT _qualified_artifact_sha256 STREQUAL MINDCLADE_NATIVE_GPU_ARTIFACT_SHA256
)
  message(FATAL_ERROR "GPU qualification manifest does not bind the configured artifact digest")
endif()

set(
  _expected_required_symbols
  ${MINDCLADE_TILELANG_REQUIRED_LOGICAL_SYMBOLS}
  ${MINDCLADE_TILELANG_REQUIRED_PRIVATE_SYMBOLS}
)
list(REMOVE_DUPLICATES _expected_required_symbols)
list(SORT _expected_required_symbols)
string(
  JSON _required_symbol_count
  ERROR_VARIABLE _required_symbol_count_error
  LENGTH "${_qualification_json}" required_symbols
)
if(NOT _required_symbol_count_error STREQUAL "NOTFOUND")
  message(FATAL_ERROR "GPU qualification manifest must declare required_symbols")
endif()
set(_qualified_required_symbols)
if(_required_symbol_count GREATER 0)
  math(EXPR _required_symbol_last "${_required_symbol_count} - 1")
  foreach(_required_symbol_index RANGE 0 ${_required_symbol_last})
    string(
      JSON _required_symbol
      GET "${_qualification_json}" required_symbols ${_required_symbol_index}
    )
    list(APPEND _qualified_required_symbols "${_required_symbol}")
  endforeach()
endif()
list(LENGTH _qualified_required_symbols _qualified_required_symbol_count)
list(REMOVE_DUPLICATES _qualified_required_symbols)
list(LENGTH _qualified_required_symbols _qualified_unique_required_symbol_count)
if(NOT _qualified_required_symbol_count EQUAL _qualified_unique_required_symbol_count)
  message(FATAL_ERROR "GPU qualification required_symbols must not contain duplicates")
endif()
list(SORT _qualified_required_symbols)
if(NOT _qualified_required_symbols STREQUAL _expected_required_symbols)
  message(FATAL_ERROR "GPU qualification required_symbols do not match generated inventory")
endif()

add_library(
  mindclade_native_cuda_registry
  OBJECT
    ../generated/operation_registry.generated.cpp
    ../generated/launcher_plans.generated.cpp
    operation_registry.cpp
)
mindclade_apply_gpu_registry_target_policy(mindclade_native_cuda_registry)

add_library(mindclade_native_gpu_artifact UNKNOWN IMPORTED GLOBAL)
set_target_properties(
  mindclade_native_gpu_artifact
  PROPERTIES IMPORTED_LOCATION "${MINDCLADE_NATIVE_GPU_ARTIFACT}"
)

if(MINDCLADE_TILELANG_REQUIRED_PRIVATE_SYMBOLS)
  if("${MINDCLADE_NATIVE_PROGRAM_GROUP_BRIDGE_LIBRARY}" STREQUAL "")
    message(
      FATAL_ERROR
      "Private TileLang symbols require an explicit qualified program-group bridge library"
    )
  endif()
  if(NOT IS_ABSOLUTE "${MINDCLADE_NATIVE_PROGRAM_GROUP_BRIDGE_LIBRARY}")
    message(FATAL_ERROR "Program-group bridge library path must be absolute")
  endif()
  if(
    NOT EXISTS "${MINDCLADE_NATIVE_PROGRAM_GROUP_BRIDGE_LIBRARY}"
    OR IS_DIRECTORY "${MINDCLADE_NATIVE_PROGRAM_GROUP_BRIDGE_LIBRARY}"
  )
    message(FATAL_ERROR "Program-group bridge library must be an existing file")
  endif()
  if("${MINDCLADE_NATIVE_PROGRAM_GROUP_BRIDGE_LIBRARY_SHA256}" STREQUAL "")
    message(FATAL_ERROR "Program-group bridge library requires an immutable digest")
  endif()
  if(
    NOT MINDCLADE_NATIVE_PROGRAM_GROUP_BRIDGE_LIBRARY_SHA256
    MATCHES "^sha256:[0-9a-f]{64}$"
  )
    message(
      FATAL_ERROR
      "MINDCLADE_NATIVE_PROGRAM_GROUP_BRIDGE_LIBRARY_SHA256 must use sha256:<64 lowercase hex>"
    )
  endif()

  file(
    SHA256
    "${MINDCLADE_NATIVE_PROGRAM_GROUP_BRIDGE_LIBRARY}"
    _program_group_bridge_actual_sha256
  )
  string(
    REGEX REPLACE
    "^sha256:"
    ""
    _program_group_bridge_expected_sha256
    "${MINDCLADE_NATIVE_PROGRAM_GROUP_BRIDGE_LIBRARY_SHA256}"
  )
  if(
    NOT _program_group_bridge_actual_sha256
    STREQUAL _program_group_bridge_expected_sha256
  )
    message(FATAL_ERROR "Program-group bridge library digest mismatch")
  endif()

  add_library(mindclade_native_program_group_bridge UNKNOWN IMPORTED GLOBAL)
  set_target_properties(
    mindclade_native_program_group_bridge
    PROPERTIES
      IMPORTED_LOCATION "${MINDCLADE_NATIVE_PROGRAM_GROUP_BRIDGE_LIBRARY}"
  )
  target_compile_definitions(
    mindclade_native_cuda_registry
    PRIVATE MINDCLADE_PROGRAM_GROUP_BRIDGE_V1=1
  )
endif()

add_library(
  mindclade_ops
  SHARED
    ../generated/registration.generated.cpp
    ../stable_abi/registration.cpp
    ../stable_abi/tensor_bridge.cpp
    ../stable_abi/tensor_bridge.h
    $<TARGET_OBJECTS:mindclade_native_cuda_registry>
)
add_library(Mindclade::ops ALIAS mindclade_ops)
mindclade_apply_gpu_registry_target_policy(mindclade_ops)
mindclade_apply_no_undefined_link_policy(mindclade_ops)
target_include_directories(mindclade_ops PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}/../stable_abi")
target_link_libraries(mindclade_ops PRIVATE mindclade_native_gpu_artifact)
if(MINDCLADE_TILELANG_REQUIRED_PRIVATE_SYMBOLS)
  target_link_libraries(mindclade_ops PRIVATE mindclade_native_program_group_bridge)
endif()
set_target_properties(
  mindclade_ops
  PROPERTIES
    OUTPUT_NAME mindclade_ops
    VERSION "${PROJECT_VERSION}"
    SOVERSION "0"
)
install(
  TARGETS mindclade_ops
  EXPORT MindcladeNativeTargets
  LIBRARY DESTINATION "${CMAKE_INSTALL_LIBDIR}" COMPONENT Runtime
  ARCHIVE DESTINATION "${CMAKE_INSTALL_LIBDIR}" COMPONENT Development
  RUNTIME DESTINATION "${CMAKE_INSTALL_BINDIR}" COMPONENT Runtime
)
