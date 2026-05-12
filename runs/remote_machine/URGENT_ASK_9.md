# Urgent Ask #9 from Remote Claude — Step 3 IP has 0 m_axi master interfaces

## TL;DR / severity

**Step 3 csynth "5/5 PASS" was misleading.** The generated `sa_tiny_fpga_top.zip` IP contains **zero m_axi master interfaces** — every pointer top-arg (`img_in`, `feat_out`, `w_pool`, `bias_pool`, `shift_pool`, `scratch_a..f`, `scratch_spike`, `scratch_acc`, `scratch_spk_a..e`) was demoted to scalar / `ap_memory` register port. The kernel cannot read DDR3 at runtime. The .xo is non-functional even though it compiled.

This is **why Step 5 BD attempt 5 fails** at `[BD 5-232] No interface pins matched 'spike_accel_0/m_axi_gmem0'` — the build_bd.tcl assumed 5 m_axi masters `m_axi_gmem0..gmem4`; the actual IP has none.

## Evidence

```bash
$ grep -c 'm_axi' hw/vivado/ip_repo/spike_accel/sa_tiny_fpga_top/component.xml
0

$ awk '/<spirit:busInterface>/{flag=1} flag && /<spirit:name>/{print; flag=0}' .../component.xml
      <spirit:name>s_axi_control</spirit:name>      ← only AXI-Lite
      <spirit:name>ap_clk</spirit:name>
      <spirit:name>ap_rst_n</spirit:name>
      <spirit:name>interrupt</spirit:name>
      <spirit:name>img_in</spirit:name>             ← scalar / ap_memory (not m_axi)
      <spirit:name>feat_out</spirit:name>
      <spirit:name>layer_id</spirit:name>
      <spirit:name>w_pool</spirit:name>
      <spirit:name>bias_pool</spirit:name>
      <spirit:name>shift_pool</spirit:name>
      <spirit:name>scratch_a_i</spirit:name>        ← _i/_o suffix = ap_memory dual-port
      <spirit:name>scratch_a_o</spirit:name>
      ... (all 11 scratch buffers as _i/_o pairs)
```

Source pragmas are present:

```cpp
// hw/hls/src/tiny_fpga_top.cpp:160
SA_AXI_MM(img_in,        gmem0, 196608)
SA_AXI_MM(feat_out,      gmem1, 21504)
SA_AXI_MM(w_pool,        gmem2, SA_W_POOL_BYTES)
... (17 SA_AXI_MM macros)
SA_AXI_LITE(layer_id)
SA_AXI_LITE_RETURN
```

But Vitis HLS 2024.1 ignored them and synthesized scalar / ap_memory bindings instead.

## Smoking-gun warnings (from `step3_synth_stdout.log`)

```
WARNING: [HLS 214-450] Ignore address on register port 'shift_pool'  (line 367)
WARNING: [HLS 214-450] Ignore address on register port 'w_pool'      (line ...)
WARNING: [HLS 214-450] Ignore address on register port 'bias_pool'   (line ...)
WARNING: [HLS 214-450] Ignore address on register port 'scratch_a'   (line ...)
WARNING: [HLS 214-450] Ignore address on register port 'feat_out'    (line ...)
...
WARNING: [HLS 214-450] Ignore address on register port 'pool_buf3'   (spike_sppf.cpp:138)
WARNING: [HLS 214-450] Ignore address on register port 'spk_buf'     (lif_expand.cpp:55)
```

"Ignore address on register port" means: Vitis classified the port as a **scalar register**, not m_axi, so it treated array-index reads as no-ops (the address bits are register, not bus). **All these warnings were silently dropped during csynth** while my reports labeled the run "5/5 PASS".

V1.3 only succeeded at csynth because it removed the body-side `(const sa_i32_t *)w_pool` cast that triggered the original HLS 214-323 *error*. The underlying register-mode classification persisted from V1 / V1.1 / V1.2 — V1.3 just stopped Vitis from erroring on the consequences.

## Root cause hypothesis

Vitis HLS 2024.1's interface-pragma application has a stricter scope / ordering than 2023.2. Likely candidates:

1. **`#pragma HLS INTERFACE m_axi port=X offset=slave bundle=Y depth=Z`** (the `SA_AXI_MM` expansion) — the *old* syntax. ADR-0005 noted this is deprecated in 2024.1; should still work per Xilinx UG902 §"Backwards compatibility", but evidently the parser sometimes silently drops the pragma when the body has cast/arithmetic on the same port (which V1.3 doesn't have — but V1/V1.1/V1.2 did). Bug appears to persist post-V1.3.

2. **`mode=...` new syntax** is now mandatory for some param combinations. The 2024.1 UG1399 may require:
   ```cpp
   #pragma HLS INTERFACE mode=m_axi port=w_pool offset=slave bundle=gmem2 depth=...
   ```
   (note the explicit `mode=` keyword)

3. **Default binding mode change**: in 2024.1, top-level pointer args may default to `ap_memory` (or `bram`) unless `mode=m_axi` is **explicitly** declared with the new syntax. The old syntax may be parsed but downgraded to a warning-only "hint".

## Suggested fix paths (for B1 owner)

### Option α — update SA_AXI_MM macro to new syntax  *(minimal change, recommended)*

`hw/hls/include/axi_iface.h`:

```diff
-#define SA_AXI_MM(port, bundle, depth) \
-    SA_HLS_PRAGMA(HLS INTERFACE m_axi port=port offset=slave bundle=bundle depth=depth)
+#define SA_AXI_MM(port, bundle, depth) \
+    SA_HLS_PRAGMA(HLS INTERFACE mode=m_axi port=port offset=slave bundle=bundle depth=depth)
```

1-character keyword change. All 17 sites in `tiny_fpga_top.cpp` inherit the new syntax through the macro.

### Option β — also remove the `ap_vld` default for scalars

Add explicit `mode=s_axilite` on `layer_id` and `return`:

```cpp
#pragma HLS INTERFACE mode=s_axilite port=layer_id bundle=control
#pragma HLS INTERFACE mode=s_axilite port=return   bundle=control
```

Likely required if Option α alone leaves layer_id as `ap_vld`.

### Option γ — verify with a 1-arg minimum repro

Compile a stripped-down `void foo(int *x)` with the old + new pragmas, dump component.xml, see which one yields `m_axi`. ~5 min experiment. Confirms the syntax issue empirically before touching the real top.

## Implication for prior PASS reports

- **Step 1 csim 10/10 PASS** — still valid (csim ignores interface mode, just executes C++ in host mode with byte-identical golden compare)
- **Step 3 csynth 5/5 "PASS"** — must be **re-classified as FAIL** despite csynth exiting 0. The .xo doesn't have m_axi where it must.
- **Step 4 resource gate** — numbers are still real (DSP 16 / LUT 15654 / etc.) but they reflect a non-functional design. They're a **lower bound** on what an m_axi-correct design would use (m_axi adapter logic adds FF/LUT).
- **risk_R1_timing.md** — WNS -0.04ns is also non-meaningful since the actual data-path control didn't synthesize correctly.

## What I'm doing

- URGENT_ASK_9 pushed; Step 5 final partial report updated.
- Step 6 (LFS push) is queued but produces no useful bitstream until Step 3 is re-done with m_axi-correct IP.
- Standing by. Will not retry Step 5 — needs Step 3 re-csynth with Option α first.

## My recommendation

**Option α + Option γ**: B1 owner updates `SA_AXI_MM` macro to use `mode=m_axi` syntax (~1 line), runs the γ minimum repro to confirm Vitis accepts it, then I re-csynth from clean and verify `grep -c 'm_axi' component.xml > 0`. ETA on remote side: ~5 min compile-verify + ~5 min full csynth + ~45 min Vivado BD/impl/bitstream after that.

Sorry for not catching this at Step 3. The "Ignore address on register port" warnings were in the logs but I treated them as the same noise-class as the deprecated-pragma WARNs (per ADR-0005). They're not — they're the smoking gun for the demotion that defeats the whole point of the kernel.

— Remote Claude, 2026-05-12T22:25:00+08:00
