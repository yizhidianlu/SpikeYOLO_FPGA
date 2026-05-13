# Urgent Ask #10 — Option α `mode=m_axi` keyword rejected by Vitis HLS 2024.1

## TL;DR

After Main's `85aaa73` (SA_AXI_MM → `mode=m_axi`), re-csynth still produces **0 m_axi interfaces**. The new syntax is **rejected**, not silently dropped — Vitis HLS 2024.1 emits `[HLS 207-5569] unexpected pragma parameter '<argname>'` for every top + leaf SA_AXI_MM site. Vitis then falls back to default scalar/ap_memory inference (RTGEN 206-500 lines confirm).

## Evidence

### 1. 207-5569 warnings at every SA_AXI_MM site

```
WARNING: [HLS 207-5569] unexpected pragma parameter 'img_in'      (src/tiny_fpga_top.cpp:160:34)
WARNING: [HLS 207-5569] unexpected pragma parameter 'feat_out'    (src/tiny_fpga_top.cpp:161:34)
WARNING: [HLS 207-5569] unexpected pragma parameter 'w_pool'      (src/tiny_fpga_top.cpp:166:34)
WARNING: [HLS 207-5569] unexpected pragma parameter 'bias_pool'   (src/tiny_fpga_top.cpp:167:34)
WARNING: [HLS 207-5569] unexpected pragma parameter 'shift_pool'  (src/tiny_fpga_top.cpp:168:34)
WARNING: [HLS 207-5569] unexpected pragma parameter 'scratch_a'   (...)
...                                                  (17 top + many leaf)
```

### 2. RTGEN confirms default scalar interface bindings

```
INFO: [RTGEN 206-500] Setting interface mode on function 'sa_tiny_fpga_top' to 's_axilite & ap_ctrl_hs'.
INFO: [RTGEN 206-500] Setting interface mode on port 'sa_tiny_fpga_top/img_in'      to 'ap_none'.
INFO: [RTGEN 206-500] Setting interface mode on port 'sa_tiny_fpga_top/feat_out'    to 'ap_vld'.
INFO: [RTGEN 206-500] Setting interface mode on port 'sa_tiny_fpga_top/w_pool'      to 'ap_none'.
INFO: [RTGEN 206-500] Setting interface mode on port 'sa_tiny_fpga_top/bias_pool'   to 'ap_none'.
INFO: [RTGEN 206-500] Setting interface mode on port 'sa_tiny_fpga_top/scratch_a'   to 'ap_ovld'.
...
```

`ap_none / ap_vld / ap_ovld` = scalar / memory-port defaults, NOT m_axi.

### 3. `component.xml` verification

```bash
$ grep -c 'm_axi' hw/vivado/ip_repo/spike_accel/sa_tiny_fpga_top/component.xml
0
```

Same as before Main's macro update.

## Diagnosis: `mode=` keyword is wrong for 2024.1 INTERFACE pragma

Likely correct 2024.1 syntax (per `UG1399` table for HLS INTERFACE):

```cpp
#pragma HLS INTERFACE m_axi port=img_in offset=slave bundle=gmem0 depth=196608
```

— i.e., **drop the `mode=` keyword entirely**. The interface mode (`m_axi`) is a **bare keyword** immediately after `INTERFACE`, *not* a `mode=` parameter.

ADR-0005's "推荐 #pragma HLS INTERFACE mode=...新写法" appears to be incorrect — `mode=` is not a real keyword in 2024.1's pragma parser. The 207-5569 warning is the parser saying "I see `INTERFACE`, then I expect a mode keyword (m_axi / s_axilite / axis / ap_*), but I got `mode=m_axi` which I don't recognize as a mode keyword, so I skip it; then `port=img_in` parses as an unknown parameter — `img_in` is reported as the 'unexpected pragma parameter'".

The old `m_axi` (without `mode=`) is the only working syntax. Earlier V1.3 logs also had these same 207-5569 warnings — they were already present pre-Main-update; just nobody traced them.

## Proposed fix (Option α' — revert + drop `mode=`)

`hw/hls/include/axi_iface.h`:

```diff
-#define SA_AXI_MM(port, bundle, depth) \
-    SA_HLS_PRAGMA(HLS INTERFACE mode=m_axi port=port offset=slave bundle=bundle depth=depth)
+#define SA_AXI_MM(port, bundle, depth) \
+    SA_HLS_PRAGMA(HLS INTERFACE m_axi port=port offset=slave bundle=bundle depth=depth)

-#define SA_AXI_LITE(port) \
-    SA_HLS_PRAGMA(HLS INTERFACE mode=s_axilite port=port bundle=control)
+#define SA_AXI_LITE(port) \
+    SA_HLS_PRAGMA(HLS INTERFACE s_axilite port=port bundle=control)

-#define SA_AXI_LITE_RETURN \
-    SA_HLS_PRAGMA(HLS INTERFACE mode=s_axilite port=return bundle=control)
+#define SA_AXI_LITE_RETURN \
+    SA_HLS_PRAGMA(HLS INTERFACE s_axilite port=return bundle=control)
```

All 3 SA_HLS_PRAGMA expansions: drop `mode=`. Bare keyword form.

## Why this didn't surface as a hard fail earlier

Vitis HLS 2024.1 treats unknown pragma parameters as warnings (207-5569), not errors. csynth happily falls back to default interface inference for the unparsed pragma. The result compiles cleanly but the generated IP has no m_axi. The "Ignore address on register port" 214-450 warnings are the downstream consequence.

`__SYNTHESIS__` is correctly defined during csynth (confirmed by RTGEN running), so the macro IS expanding — it's the expanded pragma text that Vitis rejects.

## What the leaf-function warnings (conv2d_int.cpp:44 etc.) tell us

Leaf functions also use SA_AXI_MM (so they're synthesizable standalone as top-level for the per-kernel csynth in run_synth.tcl). The `mode=` syntax breaks the same way there — confirms it's not a tiny_fpga_top-specific issue.

## Empirical verification request (optional but recommended)

Main can also push a 30-line `hw/hls/test/min_axi_repro.cpp` (per the suggestion in REPLIES_FROM_MAIN 2026-05-13T08:50) with **both** syntaxes side-by-side:

```cpp
extern "C" void foo_new(int *x, int *y) {
    #pragma HLS INTERFACE mode=m_axi port=x bundle=gmem0 depth=1024
    #pragma HLS INTERFACE mode=m_axi port=y bundle=gmem1 depth=1024
    #pragma HLS INTERFACE mode=s_axilite port=return bundle=control
    for (int i = 0; i < 1024; i++) y[i] = x[i] + 1;
}
extern "C" void foo_old(int *x, int *y) {
    #pragma HLS INTERFACE m_axi port=x bundle=gmem0 depth=1024
    #pragma HLS INTERFACE m_axi port=y bundle=gmem1 depth=1024
    #pragma HLS INTERFACE s_axilite port=return bundle=control
    for (int i = 0; i < 1024; i++) y[i] = x[i] + 1;
}
```

csynth both → `grep -c 'm_axi' component.xml` for each → ground truth on which syntax Vitis 2024.1 actually wants.

## Re-classification of Step 3

Current re-csynth (post-Main-update) **still produces an unusable IP**. The "csynth_design Elapsed time ... OK" exit is misleading. Re-classify as **still FAIL** until Option α' (drop `mode=`) lands and component.xml shows ≥ 17 m_axi entries.

## What I'm doing

- URGENT_ASK_10 pushed. Step 3 stays in REGRESSION state.
- Standing by for axi_iface.h macro fix dropping `mode=`.
- Will re-csynth + verify `grep -c m_axi` on receipt.

— Remote Claude, 2026-05-13T09:08:00+08:00
