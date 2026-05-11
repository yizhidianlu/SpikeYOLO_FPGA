# sw/sdk/examples/Makefile -- plain GNU make fallback for users without cmake.
#
# Usage:
#     make                   # build all 5 examples (host stub backend)
#     make hello_open        # build a single example
#     make run-hello_open    # build + run
#     make clean
#
# Cross-compile for ZYBO Z7-20:
#     make CC=arm-linux-gnueabihf-gcc SA_STUB_BACKEND=
#
# (Drop SA_STUB_BACKEND=1 from CFLAGS by setting it empty to enable the real
# /dev/uio0 backend.)

CC          ?= gcc
SDK_ROOT    := ..
INCLUDE     := -I$(SDK_ROOT)/include -I$(SDK_ROOT)/src
SA_STUB_BACKEND ?= 1
CFLAGS      ?= -std=c11 -Wall -Wextra -O2 -D_POSIX_C_SOURCE=200809L
ifneq ($(SA_STUB_BACKEND),)
CFLAGS      += -DSA_STUB_BACKEND=$(SA_STUB_BACKEND)
endif
LDFLAGS     ?= -lpthread

SDK_SRCS := \
    $(SDK_ROOT)/src/accel_drv.c \
    $(SDK_ROOT)/src/dma_buf.c \
    $(SDK_ROOT)/src/sa_strerror.c \
    $(SDK_ROOT)/src/sa_version.c

EXAMPLES := hello_open infer_one_frame layer_isolation perf_counters async_pipeline
BINS     := $(addprefix build/,$(EXAMPLES))

.PHONY: all clean $(addprefix run-,$(EXAMPLES))

all: $(BINS)

build:
	mkdir -p build

build/%: %.c $(SDK_SRCS) | build
	$(CC) $(CFLAGS) $(INCLUDE) $< $(SDK_SRCS) $(LDFLAGS) -o $@

$(EXAMPLES): %: build/%

run-%: build/%
	./build/$*

clean:
	rm -rf build
