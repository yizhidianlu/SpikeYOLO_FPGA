# URGENT_ASK_16 — HLS top function `sa_tiny_fpga_top` rejects struct-of-pointer arg `L`

**From:** Cloud Claude
**Branch:** `cloud/petalinux-builder`
**Time:** 2026-05-29T16:25+08:00
**Status:** HLS csynth blocked (Stage 2). I'll proceed with Phase A (placeholder BD → XSA → Petalinux #3) to validate DDR HA-125 fix on board; Phase B (real bitstream with spike_accel IP) waits on Main's HLS rewrite.

---

## Error (HLS_EXIT_1, after 50 s of preprocessing)

```
INFO: [HLS 200-1995] There were 49,754 instructions in the design after the 'Compile/Link' phase
ERROR: [HLS 214-298] Struct type with pointer type inside on top function argument is not
       supported, please disaggregate argument 'L' manually
       (src/tiny_fpga_top.cpp:148:0)
ERROR: [HLS 200-1715] Encountered problem during source synthesis
INFO: [HLS 200-2161] Finished Command csynth_design Elapsed time: 00:00:46
Pre-synthesis failed.
```

`L` is `const sa_layer_weights_t *L` (line 134), where:

```cpp
typedef struct {
    const sa_i8_t  *w;
    const sa_i32_t *bias;
    const sa_i8_t  *out_shift;
} sa_layer_weights_t;
```

Vitis HLS 2024.1 rejects struct-with-pointer-fields on the top function. The comment block above the struct definition (lines 97-115) anticipates this design works "IF the struct fits in 64 bits per field" — but it actually doesn't, regardless of size: it's any struct-of-pointer.

---

## Suggested fix — pass arrays of plain integer addresses, cast inside

Replace the single `L` arg with three arrays of `uint64_t` addresses, then cast inside the function:

```diff
 void sa_tiny_fpga_top(
     const sa_i8_t  *img_in,
           sa_i8_t  *feat_out,
     int             layer_id,
-    const sa_layer_weights_t *L,        /* L[30]                              */
+    const uint64_t *L_w_addrs,          /* L_w_addrs[30]; cast to const sa_i8_t* below */
+    const uint64_t *L_bias_addrs,       /* L_bias_addrs[30]; cast to const sa_i32_t* */
+    const uint64_t *L_out_shift_addrs,  /* L_out_shift_addrs[30]; cast to const sa_i8_t* */
           sa_i32_t *scratch_a,
           ...
```

Inside the dispatcher, at each layer call:

```cpp
const sa_i8_t  *w         = (const sa_i8_t  *)L_w_addrs[layer_idx];
const sa_i32_t *bias      = (const sa_i32_t *)L_bias_addrs[layer_idx];
const sa_i8_t  *out_shift = (const sa_i8_t  *)L_out_shift_addrs[layer_idx];
sa_conv2d_bn(... w, bias, out_shift ...);
```

Then update SA_AXI_MM bindings:

```diff
-SA_AXI_MM(L,             gmem2, 240)
+SA_AXI_MM(L_w_addrs,         gmem2, 240)    /* 30 * 8 bytes */
+SA_AXI_MM(L_bias_addrs,      gmem2, 240)
+SA_AXI_MM(L_out_shift_addrs, gmem2, 240)
```

Update the host side (`sw/runtime/`) to publish 3 separate uint64_t arrays from `/lib/firmware/tiny_fpga_int8.bin` instead of one struct array. The tb_tiny_fpga_top.cpp testbench needs the same shape change.

### Alternative — `#pragma HLS DISAGGREGATE`

```cpp
#pragma HLS DISAGGREGATE variable=L
```

May work in newer Vitis HLS versions; worth trying as a one-line first attempt. If HLS still errors, fall back to the uint64_t-arrays approach.

### Alternative — 30 individual ports

The comment block ("Alternative: 30 individual m_axi ports — explodes the IP regmap to >100 AXI registers") rules this out. Don't go there.

---

## Cloud-side progression (independent of this ask)

Since Stage 2 is blocked, I'm doing **Phase A** in parallel:

1. Run `vivado -mode batch -source build_bd.tcl` with `HAS_HLS_IP=0` (the script's placeholder path — `xlconstant` instead of `sa_tiny_fpga_top`). The placeholder BD still has the real PS config + DDR HA-125 override.
2. Export `system.xsa` (PS-only PL placeholder is fine for FSBL/u-boot/Linux validation — the .xsa for Petalinux only needs ps7_init.c, which comes from PS not PL).
3. Petalinux rebuild #3 with the placeholder XSA.
4. **Validation goal:** flashing this .wic should boot to u-boot → kernel → login. UART should now talk (FSBL DDR self-test passes with HA-125 timing).
5. The placeholder PL won't have spike_accel/UIO devices, so the demo binary won't run — but **the platform basics (boot, UART, SSH, /dev/udmabuf, /lib/firmware/system.bit.bin auto-load) all get validated.**

When Main pushes the HLS rewrite, I run **Phase B**:

1. `vitis_hls -f run_synth.tcl` → `sa_tiny_fpga_top.xo`
2. `cp build/sa_tiny_fpga_top.xo ip_repo/spike_accel/`
3. `vivado -mode batch -source build_bd.tcl` with `HAS_HLS_IP=1` (real IP)
4. `vivado -mode batch -source build_bitstream.tcl` → real `system.bit`
5. Petalinux rebuild #4
6. Final .wic with PL programmed at boot.

Phase A unblocks the user's "does it boot at all" verification immediately.

---

## Consolidated status

| Ask | Status |
|---|---|
| All earlier (1–15) | ✅ on origin/main |
| **HLS top function struct-of-pointer arg** | ⏳ **this ask** |

— Cloud Claude
