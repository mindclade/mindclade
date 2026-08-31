# Copyright (c) 2026 Mindclade. All rights reserved.
# Proprietary and confidential. Unauthorized use, copying, or distribution is prohibited.

include_guard(GLOBAL)

set(_MINDCLADE_TORCH_STABLE_ABI_VERSION "2.10")

function(mindclade_assert_torch_stable_abi requested_version)
  if(NOT requested_version STREQUAL _MINDCLADE_TORCH_STABLE_ABI_VERSION)
    message(
      FATAL_ERROR
      "Mindclade native TARGET metadata is fixed to Torch Stable ABI "
      "${_MINDCLADE_TORCH_STABLE_ABI_VERSION}; requested "
      "${requested_version}. A version change requires authoritative lock "
      "reconciliation and qualification evidence."
    )
  endif()
endfunction()

function(_mindclade_apply_native_common_target_policy target)
  if(NOT TARGET "${target}")
    message(FATAL_ERROR "Unknown native target: ${target}")
  endif()

  target_compile_features("${target}" PRIVATE cxx_std_17)
  target_compile_definitions(
    "${target}"
    PRIVATE
      MINDCLADE_TORCH_STABLE_ABI_MAJOR=2
      MINDCLADE_TORCH_STABLE_ABI_MINOR=10
  )
  target_compile_options(
    "${target}"
    PRIVATE
      "$<$<CXX_COMPILER_ID:MSVC>:/W4>"
      "$<$<CXX_COMPILER_ID:MSVC>:/WX>"
      "$<$<CXX_COMPILER_ID:MSVC>:/permissive->"
      "$<$<NOT:$<CXX_COMPILER_ID:MSVC>>:-Wall>"
      "$<$<NOT:$<CXX_COMPILER_ID:MSVC>>:-Wextra>"
      "$<$<NOT:$<CXX_COMPILER_ID:MSVC>>:-Wpedantic>"
      "$<$<NOT:$<CXX_COMPILER_ID:MSVC>>:-Werror>"
  )
  set_target_properties(
    "${target}"
    PROPERTIES
      CXX_EXTENSIONS OFF
      CXX_VISIBILITY_PRESET hidden
      POSITION_INDEPENDENT_CODE ON
      VISIBILITY_INLINES_HIDDEN YES
  )
endfunction()

# Compatibility entry point for the stable/schema target. GPU registry object
# targets must use mindclade_apply_gpu_registry_target_policy instead.
function(mindclade_apply_native_target_policy target)
  _mindclade_apply_native_common_target_policy("${target}")
  target_compile_definitions(
    "${target}"
    PRIVATE MINDCLADE_NATIVE_SCHEMA_ONLY=1
  )
endfunction()

function(mindclade_apply_gpu_registry_target_policy target)
  _mindclade_apply_native_common_target_policy("${target}")
endfunction()
