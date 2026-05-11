# sw/sdk/CMakeLists.txt — libspike_accel.so + unit tests
#
# Target board: ZYBO Z7-20 (Cortex-A9, armv7l).
# Cross-compile from PC via:
#   cmake -B build \
#       -DCMAKE_TOOLCHAIN_FILE=cmake/zynq_toolchain.cmake \
#       -DCMAKE_BUILD_TYPE=RelWithDebInfo
#   cmake --build build
#
# Native (PC) build for the host-side test_api_contract stub:
#   cmake -B build-host
#   cmake --build build-host

cmake_minimum_required(VERSION 3.18)
project(spike_accel
    VERSION 1.0.0
    DESCRIPTION "SpikeYOLO FPGA accelerator user-space SDK"
    LANGUAGES C CXX
)

set(CMAKE_C_STANDARD   11)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

option(SA_BUILD_TESTS  "Build C2 SDK unit tests" ON)
option(SA_BUILD_STUB   "Build host-side stub backend (no real /dev/uio0)" OFF)

# -----------------------------------------------------------------------------
# Library
# -----------------------------------------------------------------------------

add_library(spike_accel SHARED
    src/accel_drv.c
    src/dma_buf.c
    src/sa_strerror.c
    src/sa_version.c
)

target_include_directories(spike_accel
    PUBLIC  ${CMAKE_CURRENT_SOURCE_DIR}/include
    PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/src
)

set_target_properties(spike_accel PROPERTIES
    VERSION   ${PROJECT_VERSION}
    SOVERSION ${PROJECT_VERSION_MAJOR}
    OUTPUT_NAME spike_accel
)

# Symbol visibility — only the API in spike_accel.h is exported.
if(NOT MSVC)
    target_compile_options(spike_accel PRIVATE -fvisibility=hidden -Wall -Wextra)
endif()

if(SA_BUILD_STUB)
    target_compile_definitions(spike_accel PRIVATE SA_STUB_BACKEND=1)
endif()

# -----------------------------------------------------------------------------
# Tests
# -----------------------------------------------------------------------------

if(SA_BUILD_TESTS)
    enable_testing()
    add_executable(test_api_contract  tests/test_api_contract.c)
    add_executable(test_dma_loopback  tests/test_dma_loopback.c)

    target_link_libraries(test_api_contract PRIVATE spike_accel)
    target_link_libraries(test_dma_loopback PRIVATE spike_accel)

    add_test(NAME api_contract  COMMAND test_api_contract)
    add_test(NAME dma_loopback  COMMAND test_dma_loopback)

    # Test_dma_loopback hits real hardware; only run when SA_HW_PRESENT=1 env var.
    set_tests_properties(dma_loopback PROPERTIES
        ENVIRONMENT "SA_HW_REQUIRED=1"
        SKIP_REGULAR_EXPRESSION "SKIP:.*no_hardware"
    )
endif()

# -----------------------------------------------------------------------------
# Install
# -----------------------------------------------------------------------------

include(GNUInstallDirs)
install(TARGETS spike_accel
    LIBRARY DESTINATION ${CMAKE_INSTALL_LIBDIR}
)
install(FILES include/spike_accel.h
    DESTINATION ${CMAKE_INSTALL_INCLUDEDIR}
)

# pkg-config descriptor so downstream apps can `pkg-config --cflags --libs spike_accel`
configure_file(spike_accel.pc.in
    ${CMAKE_BINARY_DIR}/spike_accel.pc @ONLY)
install(FILES ${CMAKE_BINARY_DIR}/spike_accel.pc
    DESTINATION ${CMAKE_INSTALL_LIBDIR}/pkgconfig
)
