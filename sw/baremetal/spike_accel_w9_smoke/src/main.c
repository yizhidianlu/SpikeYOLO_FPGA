/*
 * sw/baremetal/spike_accel_w9_smoke/src/main.c
 *
 * Vitis 2024.1 baremetal port of sw/app/src/spike_accel_w9_smoke.c.
 *
 * Path C of M3 bring-up: no PetaLinux / no Linux / no /dev/uio / no CMA.
 * Direct AXI-Lite poke + DDR3 DMA buffers at fixed physical addresses.
 *
 * Weights are loaded into DDR by XSDB *before* the elf runs:
 *     mwr -bin -file models/tiny_fpga_int8_real.bin 0x10000000 1343776
 * Input is a deterministic ramp pattern generated in-app — no host file IO.
 * Output FNV-1a32 hash is printed over UART. Golden-gate compares to the
 * compiled-in W9_GOLDEN_HASH which the host generates via
 *     tools/verify/gen_w9_golden.py
 *
 * DDR layout (1 GB, ZYBO Z7-20):
 *   0x00000000..0x0FFFFFFF   .text/.data/.bss/heap/stack (256 MB)
 *   0x10000000+ 8 MB         WEIGHTS_PHYS   (XSDB-loaded)
 *   0x10800000+ 192 KB       INPUT_BUF_PHYS (app fills with ramp)
 *   0x10840000+ 24 KB        OUTPUT_BUF_PHYS (spike_accel writes via DMA)
 *
 * Cache discipline (Cortex-A9 L1/L2 vs PL AXI DMA):
 *   - Before kick: Xil_DCacheFlushRange on input → PL sees freshest bytes
 *   - After done : Xil_DCacheInvalidateRange on output → PS reads PL's bytes
 *
 * Build: Vitis "Application Project" template, BSP standalone_psu7. See
 * ../README.md for full step-by-step.
 */

#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "xil_io.h"
#include "xil_cache.h"
#include "xil_printf.h"
#include "xparameters.h"
#include "xtime_l.h"
#include "sleep.h"

/* ---------- Physical addresses (must match address_map.yaml) ---------- */
#define SA_REG_BASE        0x43C00000u

#define WEIGHTS_PHYS       0x10000000u
#define INPUT_BUF_PHYS     0x10800000u
#define OUTPUT_BUF_PHYS    0x10840000u

/* ---------- AXI-Lite register offsets (mirror sw/sdk/src/internal.h) ---- */
#define SA_REG_CTRL        0x00
#define SA_REG_GIE         0x04
#define SA_REG_IER         0x08
#define SA_REG_ISR         0x0C
#define SA_REG_LAYER_ID    0x10
#define SA_REG_LAYER_MASK  0x14
#define SA_REG_H           0x18
#define SA_REG_W           0x1C
#define SA_REG_C_IN        0x20
#define SA_REG_C_OUT       0x24
#define SA_REG_IN_PTR_LO   0x28
#define SA_REG_IN_PTR_HI   0x2C
#define SA_REG_OUT_PTR_LO  0x30
#define SA_REG_OUT_PTR_HI  0x34
#define SA_REG_W_PTR_LO    0x38
#define SA_REG_W_PTR_HI    0x3C

#define AP_START_BIT       0x1u
#define AP_DONE_BIT        0x2u

/* ---------- Geometry (Contract 1) ---------- */
#define INPUT_H            256
#define INPUT_W            256
#define INPUT_C              3
#define INPUT_NBYTES   (INPUT_H * INPUT_W * INPUT_C)        /* 196608 */

#define OUTPUT_H            16
#define OUTPUT_W            16
#define OUTPUT_C            84
#define OUTPUT_NBYTES  (OUTPUT_H * OUTPUT_W * OUTPUT_C)     /*  21504 */

#define WEIGHTS_NBYTES   1343776u     /* sha256-keyed to tiny_fpga_int8_real.bin */

/* ---------- Optional golden gate ---------- */
/* Set to a non-zero value to enable byte-exact comparison; 0 disables.
 * Host generator: tools/verify/gen_w9_golden.py --input ramp --weights ... */
#ifndef W9_GOLDEN_HASH
#define W9_GOLDEN_HASH     0u
#endif

#define TIMEOUT_LOOPS      (50u * 1000u * 1000u)   /* ~5 s worst-case @ 667 MHz */

/* ---------- Register helpers ---------- */
static inline void reg_write(uint32_t off, uint32_t v) {
    Xil_Out32(SA_REG_BASE + off, v);
}
static inline uint32_t reg_read(uint32_t off) {
    return Xil_In32(SA_REG_BASE + off);
}

/* ---------- 32-bit FNV-1a (byte-exact match for host gen_w9_golden.py) --- */
static uint32_t fnv1a32(const void *buf, uint32_t n) {
    const uint8_t *p = (const uint8_t *)buf;
    uint32_t h = 0x811C9DC5u;
    for (uint32_t i = 0; i < n; i++) {
        h ^= p[i];
        h *= 0x01000193u;
    }
    return h;
}

/* ---------- Deterministic ramp (matches host generator) ---------- */
static void fill_ramp(int8_t *buf, uint32_t n) {
    for (uint32_t i = 0; i < n; i++) {
        buf[i] = (int8_t)(i & 0xff);
    }
}

/* ---------- ms from XTime ticks (timer @ COREPLL/2 = ~333 MHz) ---------- */
static double ticks_to_ms(XTime ticks) {
    return ((double)ticks * 1000.0) / (double)COUNTS_PER_SECOND;
}

int main(void) {
    init_platform();   /* enables MMU, caches, UART — provided by BSP */

    xil_printf("\r\n");
    xil_printf("============================================================\r\n");
    xil_printf("[w9-smoke-baremetal] SpikeYOLO W9 PTQ INT8 byte-exact gate\r\n");
    xil_printf("[w9-smoke-baremetal] regs @ 0x%08x  weights @ 0x%08x\r\n",
               SA_REG_BASE, WEIGHTS_PHYS);
    xil_printf("[w9-smoke-baremetal] in @ 0x%08x  out @ 0x%08x\r\n",
               INPUT_BUF_PHYS, OUTPUT_BUF_PHYS);

    int8_t *input  = (int8_t *)(uintptr_t)INPUT_BUF_PHYS;
    int8_t *output = (int8_t *)(uintptr_t)OUTPUT_BUF_PHYS;

    /* Sanity-probe weights pool: XSDB should have mwr'd here pre-launch. */
    uint8_t *weights = (uint8_t *)(uintptr_t)WEIGHTS_PHYS;
    Xil_DCacheInvalidateRange((INTPTR)weights, 16);
    uint32_t w_head = fnv1a32(weights, 16);
    xil_printf("[w9-smoke-baremetal] weights[0..15] fnv1a32 = 0x%08x  "
               "(0x00000000 = XSDB load missing)\r\n", (unsigned)w_head);

    /* Fill input with the deterministic ramp the host generator will mirror. */
    fill_ramp(input, INPUT_NBYTES);
    uint32_t in_hash = fnv1a32(input, INPUT_NBYTES);
    xil_printf("[w9-smoke-baremetal] input fnv1a32 = 0x%08x\r\n",
               (unsigned)in_hash);

    /* Push input out of D-cache so the PL DMA reads the real bytes from DDR. */
    Xil_DCacheFlushRange((INTPTR)input, INPUT_NBYTES);
    /* Output region: invalidate so any stale lines won't shadow PL writes. */
    Xil_DCacheInvalidateRange((INTPTR)output, OUTPUT_NBYTES);

    /* ----- Program spike_accel registers ----- */
    reg_write(SA_REG_W_PTR_LO,   WEIGHTS_PHYS);
    reg_write(SA_REG_W_PTR_HI,   0u);
    reg_write(SA_REG_IN_PTR_LO,  INPUT_BUF_PHYS);
    reg_write(SA_REG_IN_PTR_HI,  0u);
    reg_write(SA_REG_OUT_PTR_LO, OUTPUT_BUF_PHYS);
    reg_write(SA_REG_OUT_PTR_HI, 0u);
    reg_write(SA_REG_LAYER_ID,   0xFFFFFFFFu);   /* -1 = run all 12 layers */
    reg_write(SA_REG_LAYER_MASK, 0x00000FFFu);

    /* ----- Kick + poll ap_done ----- */
    XTime t0, t1;
    XTime_GetTime(&t0);
    reg_write(SA_REG_CTRL, AP_START_BIT);

    uint32_t loops = 0;
    uint32_t ctrl  = 0;
    while (((ctrl = reg_read(SA_REG_CTRL)) & AP_DONE_BIT) == 0u) {
        if (++loops > TIMEOUT_LOOPS) {
            xil_printf("[w9-smoke-baremetal] TIMEOUT after %u loops  ctrl=0x%08x\r\n",
                       (unsigned)loops, (unsigned)ctrl);
            cleanup_platform();
            return 2;
        }
    }
    XTime_GetTime(&t1);

    /* Pull output back through D-cache before hashing (PL wrote DDR directly). */
    Xil_DCacheInvalidateRange((INTPTR)output, OUTPUT_NBYTES);

    uint32_t out_hash = fnv1a32(output, OUTPUT_NBYTES);
    double dt_ms = ticks_to_ms(t1 - t0);

    xil_printf("[w9-smoke-baremetal] DONE  ctrl=0x%08x  loops=%u  "
               "infer = %d.%03d ms\r\n",
               (unsigned)ctrl, (unsigned)loops,
               (int)dt_ms, (int)((dt_ms - (int)dt_ms) * 1000.0));
    xil_printf("[w9-smoke-baremetal] output[0..15] hex:\r\n  ");
    for (int i = 0; i < 16; i++) xil_printf("%02x ", (unsigned)(uint8_t)output[i]);
    xil_printf("\r\n");
    xil_printf("[w9-smoke-baremetal] output fnv1a32 = 0x%08x\r\n",
               (unsigned)out_hash);

#if W9_GOLDEN_HASH != 0u
    if (out_hash == (uint32_t)W9_GOLDEN_HASH) {
        xil_printf("[w9-smoke-baremetal] *** PASS *** golden 0x%08x matched\r\n",
                   (unsigned)W9_GOLDEN_HASH);
        cleanup_platform();
        return 0;
    }
    xil_printf("[w9-smoke-baremetal] *** FAIL *** got 0x%08x, expected 0x%08x\r\n",
               (unsigned)out_hash, (unsigned)W9_GOLDEN_HASH);
    cleanup_platform();
    return 3;
#else
    xil_printf("[w9-smoke-baremetal] OK end-to-end (no golden compiled in; "
               "baseline = 0x%08x)\r\n", (unsigned)out_hash);
    xil_printf("[w9-smoke-baremetal] To enable byte-exact gate, rebuild with\r\n");
    xil_printf("                     -DW9_GOLDEN_HASH=0x<host-generated>\r\n");
    cleanup_platform();
    return 0;
#endif
}

/* ---- BSP entry points expected by Vitis "Empty Application (C)" template */
extern void init_platform(void);
extern void cleanup_platform(void);
