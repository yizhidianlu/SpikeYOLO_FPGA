/*
 * main.c — TEMPORARILY OVERRIDDEN with main_jtag_only.c content for v12c
 * JTAG-only board-hash harvest. Restore with:
 *   git checkout HEAD~1 -- sw/baremetal/spike_accel_w9_smoke/src/main.c
 */

#include <stdint.h>
#include "xil_io.h"
#include "xil_cache.h"
#include "xparameters.h"
#include "sleep.h"

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

#define INPUT_NBYTES     (256 * 256 * 3)
#define OUTPUT_NBYTES    (16 * 16 * 84)
#define TIMEOUT_LOOPS    (50u * 1000u * 1000u)

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
    init_platform();

    int8_t  *input  = (int8_t *)(uintptr_t)INPUT_BUF_PHYS;
    int8_t  *output = (int8_t *)(uintptr_t)OUTPUT_BUF_PHYS;
    uint32_t *status = (uint32_t *)(uintptr_t)(OUTPUT_BUF_PHYS + STATUS_OFF);

    status[0] = 0u;
    status[1] = 0u;
    status[2] = 0u;
    status[3] = 0u;
    Xil_DCacheFlushRange((INTPTR)status, 16);

    fill_ramp(input, INPUT_NBYTES);
    Xil_DCacheFlushRange((INTPTR)input, INPUT_NBYTES);
    Xil_DCacheInvalidateRange((INTPTR)output, OUTPUT_NBYTES);

    reg_write(SA_REG_W_PTR_LO,   WEIGHTS_PHYS);
    reg_write(SA_REG_W_PTR_HI,   0u);
    reg_write(SA_REG_IN_PTR_LO,  INPUT_BUF_PHYS);
    reg_write(SA_REG_IN_PTR_HI,  0u);
    reg_write(SA_REG_OUT_PTR_LO, OUTPUT_BUF_PHYS);
    reg_write(SA_REG_OUT_PTR_HI, 0u);
    reg_write(SA_REG_LAYER_ID,   0xFFFFFFFFu);
    reg_write(SA_REG_LAYER_MASK, 0x00000FFFu);

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

    Xil_DCacheInvalidateRange((INTPTR)output, OUTPUT_NBYTES);

    status[0] = STATUS_MAGIC_OK;
    status[1] = loops;
    status[2] = ctrl;
    status[3] = STATUS_MAGIC_END;
    Xil_DCacheFlushRange((INTPTR)status, 16);

    for (;;) { __asm__ volatile ("wfi"); }

    return 0;
}
