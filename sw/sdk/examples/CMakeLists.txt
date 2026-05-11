# sw/sdk/examples/CMakeLists.txt -- standalone build of every example.
#
# Two usage modes:
#
#   1. Sub-directory under sw/sdk (CMakeLists.txt top-level adds us via
#      add_subdirectory(examples) -- not enabled by default, opt in with
#      -DSA_BUILD_EXAMPLES=ON). Links against the parent `spike_accel` target.
#
#   2. Standalone -- `cd examples && cmake -B build -DSA_STUB_BACKEND=1` from a
#      fresh checkout. We rebuild the SDK sources here so users can poke the
#      examples without first installing libspike_accel.
#
# Both modes default to SA_STUB_BACKEND=1; pass -DSA_STUB_BACKEND=OFF when
# building for the ZYBO target.

cmake_minimum_required(VERSION 3.18)

if(NOT TARGET spike_accel)
    # Standalone build path: we are NOT being included from the parent.
    project(spike_accel_examples LANGUAGES C)
    set(CMAKE_C_STANDARD 11)
    set(CMAKE_POSITION_INDEPENDENT_CODE ON)

    option(SA_STUB_BACKEND "Use host-side stub backend (no /dev/uio0)" ON)

    add_library(spike_accel STATIC
        ../src/accel_drv.c
        ../src/dma_buf.c
        ../src/sa_strerror.c
        ../src/sa_version.c
    )
    target_include_directories(spike_accel PUBLIC ../include PRIVATE ../src)
    if(SA_STUB_BACKEND)
        target_compile_definitions(spike_accel PRIVATE SA_STUB_BACKEND=1)
    endif()
    target_compile_definitions(spike_accel PRIVATE _POSIX_C_SOURCE=200809L)
    if(NOT WIN32)
        target_link_libraries(spike_accel PUBLIC pthread)
    endif()
endif()

set(SA_EXAMPLES
    hello_open
    infer_one_frame
    layer_isolation
    perf_counters
    async_pipeline
)

foreach(ex IN LISTS SA_EXAMPLES)
    add_executable(${ex} ${ex}.c)
    target_link_libraries(${ex} PRIVATE spike_accel)
    if(NOT WIN32)
        target_link_libraries(${ex} PRIVATE pthread)
    endif()
endforeach()
