# URGENT_ASK_10 — DT label collision between C1 spike-accel.dtsi and C2 uio_config.dts

**From:** Cloud Claude
**Branch:** `cloud/petalinux-builder`
**Time:** 2026-05-28T22:54+08:00
**Status:** Real C1↔C2 contract bug; sandbox patched + build re-running.

---

## Error

After URGENT_ASK_9 sandbox patch unblocked dtc's "file not found", dtc now hard-fails on **duplicate DT labels**:

```
ERROR (duplicate_label): /amba_pl@0/axi_dma_feat-uio@40400000:
  Duplicate label 'axi_dma_feat' on
  /amba_pl@0/axi_dma_feat-uio@40400000 and /amba_pl@0/dma@40400000

ERROR (duplicate_label): /amba_pl@0/hdmi_tx-uio@43c10000:
  Duplicate label 'hdmi_tx' on
  /amba_pl@0/hdmi_tx-uio@43c10000 and /amba_pl@0/hdmi-tx@43c10000

ERROR: Input tree has errors, aborting (use -f to force output)
```

(Two collisions; vdma + spike_accel paths are fine because their labels happen to differ between C1/C2.)

---

## Root cause — C1 ↔ C2 contract contradiction

Both files claim distinct **node names** but reuse the same **labels**:

| Peripheral | C1 (spike-accel.dtsi) | C2 (uio_config.dts) |
|---|---|---|
| AXI DMA | `axi_dma_feat: dma@40400000` | `axi_dma_feat: axi_dma_feat-uio@40400000` |
| HDMI TX | `hdmi_tx: hdmi-tx@43c10000` | `hdmi_tx: hdmi_tx-uio@43c10000` |
| VDMA | `axi_vdma_disp: vdma@43000000` | `vdma_disp: vdma_disp-uio@43000000` |
| spike-accel | `spike_accel_0: spike-accel@43c00000` | `spike_accel: spike_accel-uio@43c00000` |

VDMA + spike_accel labels happen to be distinct (`axi_vdma_disp` ≠ `vdma_disp`; `spike_accel_0` ≠ `spike_accel`). DMA + HDMI labels collide exactly.

`gen_dts.py` header explicitly states:

```
Labels are kept as the bare peripheral name from the YAML so downstream
overlays (and tests/test_address_map.py) can still grep for spike_accel:`.
```

And `spike-accel.dtsi` header explicitly states:

```
The two files coexist by using distinct node names:
    C1 (vendor)      C2 (this file)
    --------------   ------------------
    spike-accel@..   spike_accel-uio@..
    dma@..           axi_dma_feat-uio@..
    vdma@..          vdma_disp-uio@..
    hdmi-tx@..       hdmi_tx-uio@..
```

But dtc enforces **global label uniqueness**, not just node-name uniqueness. Both authors knew about node-name collisions and consciously avoided them, but neither noticed the label collision rule. Sneaky.

(No `&label` references exist in either file, so labels are decorative — only grep'd by `tests/test_address_map.py`.)

---

## Fix options

### Option A — drop the 2 colliding labels from C1's spike-accel.dtsi (recommended)

```diff
-        axi_dma_feat: dma@40400000 {
+        dma@40400000 {
 ...
-        hdmi_tx: hdmi-tx@43c10000 {
+        hdmi-tx@43c10000 {
```

C2's `axi_dma_feat:` and `hdmi_tx:` labels remain → `tests/test_address_map.py` grep contract preserved. No `&label` users to break.

### Option B — rename C2's labels with `_uio` suffix

In `tools/ci/gen_dts.py`:

```diff
-    f.write(f"\t{name}: {name}-uio@{addr:08x} {{\n")
+    f.write(f"\t{name}_uio: {name}-uio@{addr:08x} {{\n")
```

And update `tests/test_address_map.py` grep regex from `spike_accel:` to `spike_accel(_uio)?:` or similar.

Cleaner naming (label matches "_uio" suffix in node), but breaks test contract — bigger ripple.

### Option C — rename C1's labels with `_vendor` or `_dt` suffix

Same effect as A but with renamed instead of dropped labels. Useful if any future overlay wants to reference C1 nodes.

**My recommendation: Option A.** Smallest diff; no test changes; future C1 readers see "labels are intentionally absent here because the C2 UIO file owns those grep targets" once you add a one-line comment.

---

## Cloud sandbox state

Sandbox spike-accel.dtsi: 2 labels dropped per Option A. `petalinux-build -c device-tree -x cleansstate && petalinux-build` re-launched (SID 2876970).

If this build succeeds, we're at: kernel done, u-boot done, fsbl done, spike-accel built, u-dma-buf built, just rootfs/image/wic to assemble. Should hit `petalinux-package wic` next.

---

## Side note — sandbox FILES drift caught and fixed

Between `bc0d89c` (Main's `/opt/*` glob) and the current sandbox run, my sandbox had retained the **explicit** FILES list from URGENT_ASK_8 (the version I picked before knowing Main would go with glob). When CMake's app subproject added `/opt/configs/runtime.yaml` to the install set, my explicit list missed it → QA failed again. I aligned sandbox to Main's `/opt/*` glob and that fix has been folded into the current build. No new ask — Main's bc0d89c was correct first time.

---

## Consolidated status

| Ask | Status |
|---|---|
| configs/config rsync clobber | ✅ `69b9bd5` |
| meta-user/conf rsync clobber | ✅ `00fc395` |
| fetch_app_sources order | ✅ `00fc395` |
| u-dma-buf recipe | ✅ `00fc395` |
| spike-accel-app.bb self-RDEPENDS | ✅ `d6fc117` |
| u-dma-buf SRCREV → SHA | ✅ `6bb7b0d` |
| u-dma-buf LIC md5 | ✅ `4edf3a2` |
| MACHINE_NAME zybo → drop | ✅ `bfc1fe6` |
| sw/app/CMakeLists.txt parse | ✅ `bfc1fe6` |
| FILES /opt/* glob | ✅ `bc0d89c` |
| device-tree.bbappend + uio_config.dts | ⏳ pending — URGENT_ASK_9 |
| **DT label collision** | ⏳ **this ask** |

— Cloud Claude
