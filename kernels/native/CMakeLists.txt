# Copyright (c) 2026 Mindclade. All rights reserved.
# Proprietary and confidential. Unauthorized use, copying, or distribution is prohibited.

cmake_minimum_required(VERSION 3.25)

project(
  MindcladeNative
  VERSION 0.0.0
  DESCRIPTION "Target-only Mindclade native operator integration boundary"
  LANGUAGES CXX
)

include(GNUInstallDirs)
include(cmake/MindcladeTorchStable.cmake)

set(
  MINDCLADE_TORCH_STABLE_ABI_VERSION
  "2.10"
  CACHE STRING
  "Torch Stable ABI contract represented by the schema-only target"
)
set_property(
  CACHE MINDCLADE_TORCH_STABLE_ABI_VERSION
  PROPERTY STRINGS "2.10"
)

option(
  MINDCLADE_NATIVE_ENABLE_GPU
  "Link an externally qualified immutable GPU artifact"
  OFF
)

set(
  MINDCLADE_NATIVE_GPU_QUALIFICATION_MANIFEST
  ""
  CACHE FILEPATH
  "Immutable qualification manifest for an activated GPU artifact"
)
set(
  MINDCLADE_NATIVE_GPU_QUALIFICATION_SHA256
  ""
  CACHE STRING
  "Expected sha256:<hex> digest of the qualification manifest"
)
set(
  MINDCLADE_NATIVE_GPU_ARTIFACT
  ""
  CACHE FILEPATH
  "Externally built and qualified GPU shared library"
)
set(
  MINDCLADE_NATIVE_GPU_ARTIFACT_SHA256
  ""
  CACHE STRING
  "Expected sha256:<hex> digest of the GPU shared library"
)

mindclade_assert_torch_stable_abi(
  "${MINDCLADE_TORCH_STABLE_ABI_VERSION}"
)

add_subdirectory(stable_abi)

if(MINDCLADE_NATIVE_ENABLE_GPU)
  add_subdirectory(cuda)
endif()

install(
  FILES stable_abi/abi_manifest.json
  DESTINATION "${CMAKE_INSTALL_DATADIR}/mindclade/native"
  COMPONENT Runtime
)

install(
  EXPORT MindcladeNativeTargets
  FILE MindcladeNativeTargets.cmake
  NAMESPACE Mindclade::
  DESTINATION "${CMAKE_INSTALL_LIBDIR}/cmake/MindcladeNative"
  COMPONENT Development
)
