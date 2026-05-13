# sw/app/CMakeLists.txt — spike_accel_demo binary.
#
# Cross-compile from PC for the board:
#   cmake -B build \
#       -DCMAKE_TOOLCHAIN_FILE=cmake/zynq_toolchain.cmake \
#       -DCMAKE_BUILD_TYPE=RelWithDebInfo
#   cmake --build build
#
# Native (developer-PC) smoke build for the algorithm modules:
#   cmake -B build-host -DSA_APP_NO_V4L2=ON -DSA_APP_NO_DRM=ON
#   cmake --build build-host

cmake_minimum_required(VERSION 3.18)
project(spike_accel_demo VERSION 1.0.0 LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

option(SA_APP_NO_V4L2  "Skip /dev/videoN paths (PC dev build)" OFF)
option(SA_APP_NO_DRM   "Skip /dev/dri/cardN paths (PC dev build)" OFF)
option(SA_APP_STUB_SDK "Define SA_STUB_BACKEND so the app's view of the SDK
                        matches the host stub backend (mirrors sdk SA_BUILD_STUB)" OFF)

add_executable(spike_accel_demo
    src/main.cpp
    src/preproc.cpp
    src/postproc_nms.cpp
    src/v4l2_capture.cpp
    src/drm_display.cpp
    src/hdmi_overlay.cpp
)

target_include_directories(spike_accel_demo
    PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}/src
        ${CMAKE_CURRENT_SOURCE_DIR}/../sdk/include
)

if(SA_APP_NO_V4L2)  target_compile_definitions(spike_accel_demo PRIVATE SA_APP_NO_V4L2=1) endif()
if(SA_APP_NO_DRM)   target_compile_definitions(spike_accel_demo PRIVATE SA_APP_NO_DRM=1)  endif()
if(SA_APP_STUB_SDK) target_compile_definitions(spike_accel_demo PRIVATE SA_STUB_BACKEND=1) endif()

# Link against libspike_accel built in ../sdk/. Honor a parent project
# providing the imported target, otherwise look up via pkg-config.
if(TARGET spike_accel)
    target_link_libraries(spike_accel_demo PRIVATE spike_accel)
else()
    find_package(PkgConfig REQUIRED)
    pkg_check_modules(SPIKE_ACCEL REQUIRED spike_accel)
    target_include_directories(spike_accel_demo PRIVATE ${SPIKE_ACCEL_INCLUDE_DIRS})
    target_link_libraries(spike_accel_demo PRIVATE ${SPIKE_ACCEL_LIBRARIES})
endif()

# Optional libdrm — only required when SA_APP_NO_DRM is not set.
if(NOT SA_APP_NO_DRM)
    find_package(PkgConfig)
    if(PkgConfig_FOUND)
        pkg_check_modules(LIBDRM libdrm)
        if(LIBDRM_FOUND)
            target_include_directories(spike_accel_demo PRIVATE ${LIBDRM_INCLUDE_DIRS})
            target_link_libraries(spike_accel_demo PRIVATE ${LIBDRM_LIBRARIES})
        endif()
    endif()
endif()

target_link_libraries(spike_accel_demo PRIVATE pthread)

# -----------------------------------------------------------------------------
# postproc_nms_cli — standalone NMS exerciser (M1 W6).
# Used by tests/test_postproc_nms_consistency.py to compare C++ NMS output
# against the Python reference. Pure-C++; no V4L2/DRM/SDK dependencies.
# -----------------------------------------------------------------------------
add_executable(postproc_nms_cli
    src/postproc_nms_cli.cpp
    src/postproc_nms.cpp
)
target_include_directories(postproc_nms_cli PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/src)

# -----------------------------------------------------------------------------
# spike_accel_w9_smoke — minimum-viable end-to-end smoke test using the W9
# PTQ INT8 firmware. Pure-C, links only libspike_accel + libc, no V4L2/DRM.
# Used by tests/test_w9_smoke.sh + D1's board-nightly regression.
# -----------------------------------------------------------------------------
add_executable(spike_accel_w9_smoke
    src/spike_accel_w9_smoke.c
)
target_include_directories(spike_accel_w9_smoke
    PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}/../sdk/include
)
if(TARGET spike_accel)
    target_link_libraries(spike_accel_w9_smoke PRIVATE spike_accel)
else()
    target_include_directories(spike_accel_w9_smoke PRIVATE ${SPIKE_ACCEL_INCLUDE_DIRS})
    target_link_libraries(spike_accel_w9_smoke PRIVATE ${SPIKE_ACCEL_LIBRARIES})
endif()

install(TARGETS spike_accel_demo spike_accel_w9_smoke
        RUNTIME DESTINATION /opt
)
install(PROGRAMS scripts/run_on_board.sh
        DESTINATION /opt
)
install(FILES configs/runtime.yaml
        DESTINATION /opt/configs
)

# -----------------------------------------------------------------------------
# Tests (host-side smoke). The full ctest hook for board-side mAP regression
# is staged in tests/regression/ at the repo root (D1's territory).
# -----------------------------------------------------------------------------
enable_testing()
add_test(NAME app_main_smoke
         COMMAND bash ${CMAKE_CURRENT_SOURCE_DIR}/tests/test_main_smoke.sh
         WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR})
