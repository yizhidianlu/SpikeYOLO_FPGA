/*
 * sw/sdk/src/internal.h — opaque handle + backend dispatch.
 *
 * Never included by application code; only by other .c files in this SDK.
 */

#ifndef SA_INTERNAL_H
#define SA_INTERNAL_H

#include "spike_accel.h"

#include <pthread.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>

/* Sized so a single 1080p RGB888 framebuffer (~5.9 MB) also fits if we ever
 * decide to round-trip framebuffers via libspike_accel. */
#define SA_WEIGHT_POOL_SIZE  (8 * 1024 * 1024)   /* 8 MB  weights */
#define SA_INPUT_BUF_SIZE    (3 * 256 * 256)     /* 196 608 bytes  */
#define SA_OUTPUT_BUF_SIZE   (84 * 16 * 16)      /* 21 504 bytes  */

/* AXI-Lite register offsets — must agree with hw/hls/build/tiny_fpga_regmap.yaml */
#define SA_REG_CTRL        0x00
#define SA_REG_GIE         0x04
#define SA_REG_IER         0x08
#define SA_REG_ISR         0x0C
#define SA_REG_LAYER_ID    0x10
#define SA_REG_H           0x14
#define SA_REG_W           0x18
#define SA_REG_C_IN        0x1C
#define SA_REG_C_OUT       0x20
#define SA_REG_IN_PTR_LO   0x24
#define SA_REG_IN_PTR_HI   0x28
#define SA_REG_OUT_PTR_LO  0x2C
#define SA_REG_OUT_PTR_HI  0x30
#define SA_REG_W_PTR_LO    0x34
#define SA_REG_W_PTR_HI    0x38

struct sa_handle_s {
    /* Hardware-facing fields. NULL/zero in SA_STUB_BACKEND. */
    int       uio_fd;          /* /dev/uio0                                 */
    int       dma_fd;          /* /dev/udmabuf0                             */
    void     *regs;            /* mmap'd 64 KB AXI-Lite                     */

    /* CMA buffers visible to both PS and PL. */
    uint8_t  *weight_pool;
    int8_t   *in_buf;
    int8_t   *out_buf;
    uint64_t  weight_pa;
    uint64_t  in_pa;
    uint64_t  out_pa;

    /* Cumulative performance counters. */
    sa_perf_t perf;

    /* Serializes sa_infer / sa_get_perf access. */
    pthread_mutex_t lock;

    /* Whether we are running against real hardware. Always false when the
     * library is built with SA_STUB_BACKEND=1. */
    bool      has_hw;

    /* In stub mode, an explicit "model loaded" flag so the test suite
     * exercises the same error paths the real backend would. */
    bool      weights_loaded;
};

/* Logging — keep dependency-free. */
#ifdef NDEBUG
#  define SA_LOG(...) ((void)0)
#else
#  include <stdio.h>
#  define SA_LOG(...) do { fprintf(stderr, "[spike_accel] " __VA_ARGS__); \
                           fputc('\n', stderr); } while (0)
#endif

#endif  /* SA_INTERNAL_H */
