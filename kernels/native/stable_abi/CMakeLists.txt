# Copyright (c) 2026 Mindclade. All rights reserved.
# Proprietary and confidential. Unauthorized use, copying, or distribution is prohibited.

add_library(
  mindclade_native_schema
  SHARED
    ../generated/registration.generated.cpp
    registration.cpp
    tensor_bridge.cpp
    tensor_bridge.h
)
add_library(Mindclade::native_schema ALIAS mindclade_native_schema)

mindclade_apply_native_target_policy(mindclade_native_schema)
target_include_directories(
  mindclade_native_schema
  PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}"
)

set_target_properties(
  mindclade_native_schema
  PROPERTIES
    OUTPUT_NAME mindclade_native_schema
    VERSION "${PROJECT_VERSION}"
    SOVERSION "0"
)

install(
  TARGETS mindclade_native_schema
  EXPORT MindcladeNativeTargets
  LIBRARY DESTINATION "${CMAKE_INSTALL_LIBDIR}" COMPONENT Runtime
  ARCHIVE DESTINATION "${CMAKE_INSTALL_LIBDIR}" COMPONENT Development
  RUNTIME DESTINATION "${CMAKE_INSTALL_BINDIR}" COMPONENT Runtime
)
