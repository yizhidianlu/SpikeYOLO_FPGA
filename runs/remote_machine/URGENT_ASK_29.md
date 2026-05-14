# Urgent Ask #29 — M3 v11 R2 down to 53 over

## TL;DR

Progression:
- v9 Area_Explore: **120 over**
- v10 Area_Explore (VDMA shrink): **88 over** (-32)
- **v11 Area_Explore (VDMA 32b + v_tc trim): 53 over** (-35, ~50% reduction)

Trend: each round shaves ~30 slices. One more round should close. Numbers: 7869 req vs 7816 avail.

## Proposed fixes (any one likely closes)

### Option κ — Hard-code v_tc to 1080p60, drop AXI-Lite control

```tcl
# build_bd.tcl Section 4 v_tc_0:
CONFIG.HAS_AXI4_LITE {false}     # was true — SW won't control v_tc; 1080p60 baked in
# Section 5 ic_ctrl: NUM_MI 4 -> 3 (drop v_tc master)
# Section 8: drop ctrl_to_v_tc connect_bd_intf_net
```

Saves ~50-100 slices (entire AXI-Lite slave logic in v_tc + ic_ctrl's M03 master + smartconnect M03→S00 path). 1080p60 timing is the only mode we need for demo.

### Option λ — rgb2dvi external SerialClk (drop internal PLL)

```tcl
# build_bd.tcl Section 4 rgb2dvi_0:
CONFIG.kGenerateSerialClk {false}     # was true — feed SerialClk from external clock_wizard
```

Adds requirement: provide a SerialClk = 5 × PixelClk = 5 × 142.857 = 714.3 MHz pin externally. Means we need another clock_wizard IP. **Net negative** for slice count. Skip.

### Option μ — Combine rgb2dvi kClkRange tighter

```tcl
# kClkRange options: 0 (25-120 MHz), 1 (120-240 MHz), 2 (240-360 MHz)
# We're at 142.857 MHz pixel × 5 TMDS = 714.3 MHz SerialClk. Currently kClkRange=1.
# Already correct; leave alone.
```

No-op.

### Option ν — vdma_disp.c_include_internal_genlock 0

```tcl
CONFIG.c_include_internal_genlock {0}   # was default 1
```

Drops the MM2S/S2MM sync logic. We don't have S2MM (already c_include_s2mm=0). genlock should already be unused — verify and explicitly disable. ~20-40 slices.

## My recommendation

**Option κ alone** (hard-code v_tc to 1080p60, drop AXI-Lite). Single config change + 3 cleanup lines. Saves ~50-100 slices. Predicted: 7869 - 70 = 7799 req vs 7816 avail = **+17 slice headroom**.

Tight but should close. If still 5-10 over, run Area_Explore again — strategy variation typically saves another 30.

If κ + Area_Explore still fails, drop the entire v_tc IP and let the bridge's "active = !hblank && !vblank" derive from a hardcoded counter inside the Verilog (RTL-side timing gen, no IP). That's a Verilog edit but removes v_tc entirely.

## Working-tree state

- build_bd.tcl + axis_to_video_bridge.v unchanged from your c348966.
- `m3_v11_areaexp.log` confirms 53 over.

— Remote Claude, 2026-05-15T00:01:00+08:00
