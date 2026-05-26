/*
 * main_jtag_only.c — W9 baremetal smoke that bypasses UART entirely.
 *
 * Companion to main.c. Same kick + poll + cache discipline, but:
 *   - No xil_printf anywhere (UART1 is disabled in v12b BD; xil_printf would
 *     busy-wait forever on the dead UART peripheral and hang the CPU).
 *   - After spike_accel ap_done, write a 4-word "status block" into
 *     OUTPUT_BUF_PHYS + 0x5400 (just past the 21504-byte output region) and
 *     spin in WFI. xsct halts the CPU and reads the output via `mrd`.
 *
 * Build: replace src/main.c in the Vitis app with this file (or import as
 * additional source and drop the original main.c). Same BSP / xparameters /
 * linker script as the regular W9 smoke build.
 *
 * Pairs with runs/main_machine/M3_pbt_deploy_request.md and the JTAG-only
 * harvest flow described in REPLIES_FROM_MAIN.md 2026-05-26T14:55.
 */

#include <stdint.h>
#include "xil_io.h"
#include "xil_cache.h"
#include "xparameters.h"
#include "sleep.h"

/* ---- Physical addresses (match main.c) ---- */
#define SA_REG_BASE        0x43C00000u

#define WEIGHTS_PHYS       0x10000000u
#define INPUT_BUF_PHYS     0x10800000u
#define OUTPUT_BUF_PHYS    0x10840000u

#define SA_REG_CTRL        0x00
#define SA_REG_LAYER_ID    0x10
#define SA_REG_LAYER_MASK  0x14
#define SA_REG_IN_PTR_LO   0x28
#define SA_REG_IN_PTR_HI   0x2C
#define SA_REG_OUT_PTR_LO  0x30
#define SA_REG_OUT_PTR_HI  0x34
#define SA_REG_W_PTR_LO    0x38
#define SA_REG_W_PTR_HI    0x3C

#define AP_START_BIT       0x1u
#define AP_DONE_BIT        0x2u

#define INPUT_NBYTES     (256 * 256 * 3)        /* 196608 */
#define OUTPUT_NBYTES    (16 * 16 * 84)         /* 21504  */
#define TIMEOUT_LOOPS    (50u * 1000u * 1000u)

/* ---- Status block (4 u32 words at OUTPUT_BUF_PHYS + 0x5400) -----------
 *   STATUS_OFF + 0 = magic:   0xDEADBEEF = ap_done seen
 *                             0xBADC0DE0 = timeout
 *                             0x00000000 = never finished (CPU still in poll)
 *   STATUS_OFF + 4 = loops counter (when ap_done seen)
 *   STATUS_OFF + 8 = final SA_REG_CTRL value
 *   STATUS_OFF +12 = magic2: 0xC0DECAFE (sentinel of sentinel; lets xsct
 *                                         confirm CPU actually reached spin)
 */
#define STATUS_OFF       0x5400u
#define STATUS_MAGIC_OK  0xDEADBEEFu
#define STATUS_MAGIC_TO  0xBADC0DE0u
#define STATUS_MAGIC_END 0xC0DECAFEu

static inline void reg_write(uint32_t off, uint32_t v) {
    Xil_Out32(SA_REG_BASE + off, v);
}
static inline uint32_t reg_read(uint32_t off) {
    return Xil_In32(SA_REG_BASE + off);
}

static void fill_ramp(int8_t *buf, uint32_t n) {
    for (uint32_t i = 0; i < n; i++) buf[i] = (int8_t)(i & 0xFF);
}

extern void init_platform(void);

int main(void) {
    init_platform();   /* cache enable only — does NOT touch UART */

    int8_t  *input  = (int8_t *)(uintptr_t)INPUT_BUF_PHYS;
    int8_t  *output = (int8_t *)(uintptr_t)OUTPUT_BUF_PHYS;
    uint32_t *status = (uint32_t *)(uintptr_t)(OUTPUT_BUF_PHYS + STATUS_OFF);

    /* Mark "not yet finished" before any work begins. */
    status[0] = 0u;
    status[1] = 0u;
    status[2] = 0u;
    status[3] = 0u;
    Xil_DCacheFlushRange((INTPTR)status, 16);

    /* Fill deterministic ramp input. */
    fill_ramp(input, INPUT_NBYTES);
    Xil_DCacheFlushRange((INTPTR)input, INPUT_NBYTES);
    Xil_DCacheInvalidateRange((INTPTR)output, OUTPUT_NBYTES);

    /* Program spike_accel. */
    reg_write(SA_REG_W_PTR_LO,   WEIGHTS_PHYS);
    reg_write(SA_REG_W_PTR_HI,   0u);
    reg_write(SA_REG_IN_PTR_LO,  INPUT_BUF_PHYS);
    reg_write(SA_REG_IN_PTR_HI,  0u);
    reg_write(SA_REG_OUT_PTR_LO, OUTPUT_BUF_PHYS);
    reg_write(SA_REG_OUT_PTR_HI, 0u);
    reg_write(SA_REG_LAYER_ID,   0xFFFFFFFFu);
    reg_write(SA_REG_LAYER_MASK, 0x00000FFFu);

    /* Kick + poll ap_done. */
    reg_write(SA_REG_CTRL, AP_START_BIT);

    uint32_t loops = 0;
    uint32_t ctrl  = 0;
    while (((ctrl = reg_read(SA_REG_CTRL)) & AP_DONE_BIT) == 0u) {
        if (++loops > TIMEOUT_LOOPS) {
            status[0] = STATUS_MAGIC_TO;
            status[1] = loops;
            status[2] = ctrl;
            status[3] = STATUS_MAGIC_END;
            Xil_DCacheFlushRange((INTPTR)status, 16);
            for (;;) { __asm__ volatile ("wfi"); }
        }
    }

    /* ap_done seen — pull output back through D-cache. */
    Xil_DCacheInvalidateRange((INTPTR)output, OUTPUT_NBYTES);

    /* Publish status block to DDR so xsct mrd sees it. */
    status[0] = STATUS_MAGIC_OK;
    status[1] = loops;
    status[2] = ctrl;
    status[3] = STATUS_MAGIC_END;
    Xil_DCacheFlushRange((INTPTR)status, 16);

    /* Spin forever — xsct halts and harvests output via mrd. */
    for (;;) { __asm__ volatile ("wfi"); }

    /* unreachable */
    return 0;
}
