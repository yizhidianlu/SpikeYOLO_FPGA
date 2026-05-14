# Urgent Ask #28 — M3 v10 R2 down to 88 slices over (Area_Explore)

## TL;DR

Main `2c1723d` v10 (VDMA shrink + IRQ trim) saved ~150 slices. R2 gap closed from 120 over (v9 Area_Explore) to **88 over** (v10 Area_Explore). One more small shrink should close.

## Numbers

| Iter | Strategy | req | avail | Δ |
|---|---|---:|---:|---:|
| v9 Area_Explore | best so far | 7926 | 7806 | +120 |
| v10 default | VDMA shrink | 8040 | 7818 | +222 |
| **v10 Area_Explore** | VDMA shrink + Area | **7906** | **7818** | **+88** (best) |

## Proposed final close (88 → 0)

### Option ζ — Narrow VDMA HP1 data width 64 → 32

```tcl
# build_bd.tcl Section 4 vdma_disp:
CONFIG.c_m_axi_mm2s_data_width  {32}   # was 64
```

Width halving inside VDMA's M_AXI_MM2S drops 64→32-bit byte enables, address arithmetic, FIFO width — typically ~100-150 slices. 

Bandwidth check at 1080p60: pixel rate = 1920 * 1080 * 60 = 124.4 Mpix/s. With 24-bit/pixel = 373 MB/s. HP1 at 32-bit × 100 MHz = 400 MB/s ceiling. Fits. 1080p30 is comfortable.

### Option η — Drop v_tc detection sub-block + minor sim disables

```tcl
# build_bd.tcl Section 4 v_tc_0:
CONFIG.enable_detection {false}        # was true by default
CONFIG.GEN_F1_VIDEO_FORMAT {0}         # disable second field
CONFIG.GEN_INTERLACED  {false}
```

Saves ~50-100 slices. Already mostly applied in v8/v9; verify these specifics are set.

### Option θ — Custom placement constraint to slip 88 slices into corners

Add a `LOC` constraint to spike_accel that forces it into a tighter area, freeing slices in the device middle where HDMI logic lives. Complex; ~100 LUT savings. Skip unless ζ/η fail.

### Option ι — Combined ζ + η

Both together should give 150-250 slice savings → safely fits.

## My recommendation

**Option ι (ζ + η combined)**. Pure build_bd.tcl, no Verilog edit. Single config-dict update + 2-3 v_tc properties.

Predicted post-fix: 7906 - 200 = 7706 req vs 7818 avail = 112 slice headroom. Comfortable.

— Remote Claude, 2026-05-14T22:55:00+08:00
